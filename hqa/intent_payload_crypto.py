from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import sys
import time
from typing import Any, Mapping, Optional, Protocol


_KEY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_B64_RE = re.compile(r"[A-Za-z0-9+/]*={0,2}\Z")
_MAX_HELPER_REQUEST_BYTES = 1_500_000
_MAX_HELPER_RESPONSE_BYTES = 2_000_000


class CryptoFailure(RuntimeError):
    """A redacted failure at the payload-crypto boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IntentPayloadCrypto(Protocol):
    """Closed crypto seam implemented by the test fake and macOS adapter."""

    algorithm: str
    key_id: str

    def probe(self) -> None:
        ...

    def initialize(self) -> None:
        ...

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> dict[str, str]:
        ...

    def decrypt(self, envelope: Mapping[str, Any], *, aad: bytes) -> bytes:
        ...


def _validate_key_id(value: Any) -> str:
    if type(value) is not str or _KEY_ID_RE.fullmatch(value) is None:
        raise CryptoFailure("crypto_invalid_request", "crypto key identifier is invalid")
    return value


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: Any, *, field: str, maximum: int) -> bytes:
    if (
        type(value) is not str
        or len(value) > ((maximum + 2) // 3) * 4 + 4
        or _B64_RE.fullmatch(value) is None
    ):
        raise CryptoFailure("crypto_invalid_envelope", "encrypted payload is invalid")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, binascii.Error, UnicodeEncodeError) as exc:
        raise CryptoFailure(
            "crypto_invalid_envelope", "encrypted payload is invalid"
        ) from exc
    if len(decoded) > maximum:
        raise CryptoFailure("crypto_invalid_envelope", "encrypted payload is invalid")
    return decoded


class DeterministicCryptoFake:
    """Authenticated deterministic fake for hermetic tests only.

    This is intentionally not a production cipher.  It makes crash/replay tests
    reproducible while still detecting ciphertext and AAD tampering.
    """

    algorithm = "HQA-TEST-HMAC-STREAM-V1"

    def __init__(self, *, key: bytes, key_id: str = "hqa-test-key-v1") -> None:
        if type(key) is not bytes or len(key) < 32:
            raise ValueError("test crypto key must contain at least 32 bytes")
        self._key = key
        self.key_id = _validate_key_id(key_id)

    def probe(self) -> None:
        return None

    def initialize(self) -> None:
        return None

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> dict[str, str]:
        if type(plaintext) is not bytes or type(aad) is not bytes:
            raise CryptoFailure("crypto_invalid_request", "crypto input is invalid")
        nonce = hmac.new(self._key, b"nonce\0" + aad + plaintext, hashlib.sha256).digest()[:12]
        stream = self._stream(nonce=nonce, aad=aad, size=len(plaintext))
        ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(
            self._key,
            b"tag\0" + aad + nonce + ciphertext,
            hashlib.sha256,
        ).digest()
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "nonce_b64": _b64encode(nonce),
            "ciphertext_b64": _b64encode(ciphertext),
            "tag_b64": _b64encode(tag),
        }

    def decrypt(self, envelope: Mapping[str, Any], *, aad: bytes) -> bytes:
        if type(aad) is not bytes or not isinstance(envelope, Mapping):
            raise CryptoFailure("crypto_invalid_request", "crypto input is invalid")
        if set(envelope) != {
            "algorithm",
            "key_id",
            "nonce_b64",
            "ciphertext_b64",
            "tag_b64",
        }:
            raise CryptoFailure("crypto_invalid_envelope", "encrypted payload is invalid")
        if envelope.get("algorithm") != self.algorithm:
            raise CryptoFailure("crypto_algorithm_mismatch", "crypto algorithm is unsupported")
        if envelope.get("key_id") != self.key_id:
            raise CryptoFailure("crypto_key_mismatch", "crypto key identifier does not match")
        nonce = _b64decode(envelope.get("nonce_b64"), field="nonce", maximum=12)
        ciphertext = _b64decode(
            envelope.get("ciphertext_b64"), field="ciphertext", maximum=1_000_000
        )
        tag = _b64decode(envelope.get("tag_b64"), field="tag", maximum=32)
        if len(nonce) != 12 or len(tag) != 32:
            raise CryptoFailure("crypto_invalid_envelope", "encrypted payload is invalid")
        expected = hmac.new(
            self._key,
            b"tag\0" + aad + nonce + ciphertext,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise CryptoFailure("crypto_authentication_failed", "crypto authentication failed")
        stream = self._stream(nonce=nonce, aad=aad, size=len(ciphertext))
        return bytes(left ^ right for left, right in zip(ciphertext, stream))

    def _stream(self, *, nonce: bytes, aad: bytes, size: int) -> bytes:
        chunks = []
        counter = 0
        remaining = size
        while remaining:
            block = hmac.new(
                self._key,
                b"stream\0" + aad + nonce + counter.to_bytes(8, "big"),
                hashlib.sha256,
            ).digest()
            chunks.append(block[:remaining])
            remaining -= min(remaining, len(block))
            counter += 1
        return b"".join(chunks)


class MacOSKeychainCrypto:
    """CryptoKit/Keychain adapter using private inherited pipe descriptors.

    Plaintext, decrypted bytes, AAD, and key identifiers never enter argv, the
    environment, stdout, stderr, or exception text.  The Swift helper owns all
    Keychain access and returns only closed-schema JSON through the response FD.
    """

    algorithm = "AES-256-GCM"

    def __init__(
        self,
        helper: Path,
        *,
        key_id: str = "hqa-intent-payload-owner-v1",
        timeout_seconds: float = 5.0,
        allow_non_darwin: bool = False,
    ) -> None:
        self.helper = Path(os.path.abspath(helper))
        self.key_id = _validate_key_id(key_id)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 30
        ):
            raise ValueError("crypto helper timeout must be finite and from 0 to 30 seconds")
        self._timeout_seconds = float(timeout_seconds)
        if sys.platform != "darwin" and not allow_non_darwin:
            raise CryptoFailure("crypto_platform_unsupported", "Keychain crypto is unavailable")
        self._assert_helper_secure()

    @property
    def command(self) -> tuple[str, ...]:
        return (str(self.helper),)

    def probe(self) -> None:
        self._key_operation("probe")

    def initialize(self) -> None:
        self._key_operation("initialize")

    def _key_operation(self, operation: str) -> None:
        response = self._invoke(
            {
                "schema_version": "1.0",
                "operation": operation,
                "key_id": self.key_id,
            }
        )
        if response != {"ok": True, "status": "ready"}:
            raise CryptoFailure(
                "crypto_helper_protocol_error",
                "crypto helper response is invalid",
            )

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> dict[str, str]:
        if type(plaintext) is not bytes or type(aad) is not bytes:
            raise CryptoFailure("crypto_invalid_request", "crypto input is invalid")
        response = self._invoke(
            {
                "schema_version": "1.0",
                "operation": "encrypt",
                "key_id": self.key_id,
                "aad_b64": _b64encode(aad),
                "plaintext_b64": _b64encode(plaintext),
            }
        )
        expected = {
            "ok",
            "algorithm",
            "key_id",
            "nonce_b64",
            "ciphertext_b64",
            "tag_b64",
        }
        if set(response) != expected or response.get("ok") is not True:
            raise CryptoFailure("crypto_helper_protocol_error", "crypto helper response is invalid")
        envelope = {key: response[key] for key in expected - {"ok"}}
        self._validate_production_envelope(envelope)
        return envelope

    def decrypt(self, envelope: Mapping[str, Any], *, aad: bytes) -> bytes:
        if type(aad) is not bytes or not isinstance(envelope, Mapping):
            raise CryptoFailure("crypto_invalid_request", "crypto input is invalid")
        self._validate_production_envelope(envelope)
        response = self._invoke(
            {
                "schema_version": "1.0",
                "operation": "decrypt",
                "key_id": self.key_id,
                "aad_b64": _b64encode(aad),
                "nonce_b64": envelope["nonce_b64"],
                "ciphertext_b64": envelope["ciphertext_b64"],
                "tag_b64": envelope["tag_b64"],
            }
        )
        if set(response) != {"ok", "plaintext_b64"} or response.get("ok") is not True:
            raise CryptoFailure("crypto_helper_protocol_error", "crypto helper response is invalid")
        return _b64decode(
            response["plaintext_b64"], field="plaintext", maximum=750_000
        )

    def _validate_production_envelope(self, envelope: Mapping[str, Any]) -> None:
        if set(envelope) != {
            "algorithm",
            "key_id",
            "nonce_b64",
            "ciphertext_b64",
            "tag_b64",
        }:
            raise CryptoFailure("crypto_invalid_envelope", "encrypted payload is invalid")
        if envelope.get("algorithm") != self.algorithm:
            raise CryptoFailure("crypto_algorithm_mismatch", "crypto algorithm is unsupported")
        if envelope.get("key_id") != self.key_id:
            raise CryptoFailure("crypto_key_mismatch", "crypto key identifier does not match")
        nonce = _b64decode(envelope.get("nonce_b64"), field="nonce", maximum=12)
        tag = _b64decode(envelope.get("tag_b64"), field="tag", maximum=16)
        _b64decode(envelope.get("ciphertext_b64"), field="ciphertext", maximum=750_000)
        if len(nonce) != 12 or len(tag) != 16:
            raise CryptoFailure("crypto_invalid_envelope", "encrypted payload is invalid")

    def _assert_helper_secure(self) -> None:
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        current = os.open(self.helper.anchor or os.sep, flags)
        try:
            for component in self.helper.parent.parts[1:]:
                next_fd = os.open(component, flags, dir_fd=current)
                os.close(current)
                current = next_fd
                directory = os.fstat(current)
                if (
                    directory.st_uid not in {0, os.geteuid()}
                    or directory.st_mode & 0o022
                ):
                    raise CryptoFailure(
                        "crypto_helper_insecure", "crypto helper is insecure"
                    )
            helper_fd = os.open(
                self.helper.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            try:
                metadata = os.fstat(helper_fd)
                current_metadata = os.stat(
                    self.helper.name, dir_fd=current, follow_symlinks=False
                )
                if (metadata.st_dev, metadata.st_ino) != (
                    current_metadata.st_dev,
                    current_metadata.st_ino,
                ):
                    raise CryptoFailure(
                        "crypto_helper_insecure", "crypto helper is insecure"
                    )
            finally:
                os.close(helper_fd)
        except (OSError, CryptoFailure) as exc:
            if isinstance(exc, CryptoFailure):
                raise
            raise CryptoFailure(
                "crypto_helper_insecure", "crypto helper is insecure"
            ) from exc
        finally:
            os.close(current)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o022
            or not metadata.st_mode & stat.S_IXUSR
        ):
            raise CryptoFailure("crypto_helper_insecure", "crypto helper is insecure")

    def _invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        self._assert_helper_secure()
        try:
            payload = json.dumps(
                request,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise CryptoFailure("crypto_invalid_request", "crypto input is invalid") from exc
        if len(payload) > _MAX_HELPER_REQUEST_BYTES:
            raise CryptoFailure("crypto_request_too_large", "crypto input exceeds the size limit")

        request_read, request_write = os.pipe()
        response_read, response_write = os.pipe()
        process: Optional[subprocess.Popen[bytes]] = None
        try:
            process = subprocess.Popen(
                [
                    str(self.helper),
                    "--request-fd",
                    str(request_read),
                    "--response-fd",
                    str(response_write),
                ],
                close_fds=True,
                pass_fds=(request_read, response_write),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={},
            )
            os.close(request_read)
            request_read = -1
            os.close(response_write)
            response_write = -1
            raw = self._exchange(
                process=process,
                request_fd=request_write,
                response_fd=response_read,
                payload=payload,
            )
            request_write = -1
            response_read = -1
            try:
                response = json.loads(raw.decode("utf-8", errors="strict"))
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
                raise CryptoFailure(
                    "crypto_helper_protocol_error", "crypto helper response is invalid"
                ) from exc
            if not isinstance(response, dict) or any(
                type(key) is not str for key in response
            ):
                raise CryptoFailure(
                    "crypto_helper_protocol_error", "crypto helper response is invalid"
                )
            if response.get("ok") is False:
                code = response.get("code")
                if type(code) is not str or _KEY_ID_RE.fullmatch(code) is None:
                    code = "crypto_helper_failed"
                raise CryptoFailure(code, "crypto helper operation failed")
            return response
        except CryptoFailure:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise CryptoFailure("crypto_helper_unavailable", "crypto helper is unavailable") from exc
        finally:
            for fd in (request_read, request_write, response_read, response_write):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            if process is not None and process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=1)
                except subprocess.SubprocessError:
                    pass

    def _exchange(
        self,
        *,
        process: subprocess.Popen[bytes],
        request_fd: int,
        response_fd: int,
        payload: bytes,
    ) -> bytes:
        os.set_blocking(request_fd, False)
        os.set_blocking(response_fd, False)
        selector = selectors.DefaultSelector()
        selector.register(request_fd, selectors.EVENT_WRITE, "write")
        selector.register(response_fd, selectors.EVENT_READ, "read")
        written = 0
        response = bytearray()
        deadline = time.monotonic() + self._timeout_seconds
        request_open = True
        response_open = True
        try:
            while response_open:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CryptoFailure("crypto_helper_timeout", "crypto helper timed out")
                events = selector.select(remaining)
                if not events and process.poll() is not None:
                    raise CryptoFailure("crypto_helper_failed", "crypto helper operation failed")
                for key, mask in events:
                    if key.data == "write" and mask & selectors.EVENT_WRITE:
                        try:
                            count = os.write(request_fd, payload[written : written + 65_536])
                        except BlockingIOError:
                            continue
                        if count <= 0:
                            raise CryptoFailure("crypto_helper_failed", "crypto helper operation failed")
                        written += count
                        if written == len(payload):
                            selector.unregister(request_fd)
                            os.close(request_fd)
                            request_open = False
                    elif key.data == "read" and mask & selectors.EVENT_READ:
                        try:
                            chunk = os.read(response_fd, 65_536)
                        except BlockingIOError:
                            continue
                        if chunk:
                            response.extend(chunk)
                            if len(response) > _MAX_HELPER_RESPONSE_BYTES:
                                raise CryptoFailure(
                                    "crypto_helper_protocol_error",
                                    "crypto helper response exceeds the size limit",
                                )
                        else:
                            selector.unregister(response_fd)
                            os.close(response_fd)
                            response_open = False
            return_code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if return_code != 0 or request_open or not response:
                raise CryptoFailure("crypto_helper_failed", "crypto helper operation failed")
            return bytes(response)
        except subprocess.TimeoutExpired as exc:
            raise CryptoFailure("crypto_helper_timeout", "crypto helper timed out") from exc
        finally:
            selector.close()
            if request_open:
                try:
                    os.close(request_fd)
                except OSError:
                    pass
            if response_open:
                try:
                    os.close(response_fd)
                except OSError:
                    pass
