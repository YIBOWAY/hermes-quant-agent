from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from hqa.intent_payload_crypto import (
    CryptoFailure,
    DeterministicCryptoFake,
    MacOSKeychainCrypto,
)


def test_deterministic_fake_round_trips_and_authenticates_aad() -> None:
    crypto = DeterministicCryptoFake(key=b"k" * 32, key_id="test-key-v1")

    first = crypto.encrypt(b"private prompt", aad=b"metadata")
    second = crypto.encrypt(b"private prompt", aad=b"metadata")

    assert first == second
    assert first["algorithm"] == "HQA-TEST-HMAC-STREAM-V1"
    assert first["key_id"] == "test-key-v1"
    assert b"private prompt" not in json.dumps(first).encode()
    assert crypto.decrypt(first, aad=b"metadata") == b"private prompt"
    with pytest.raises(CryptoFailure, match="authentication failed"):
        crypto.decrypt(first, aad=b"different metadata")


def test_deterministic_fake_rejects_tampering_without_disclosing_plaintext() -> None:
    crypto = DeterministicCryptoFake(key=b"z" * 32)
    encrypted = crypto.encrypt(b"never disclose me", aad=b"aad")
    encrypted["ciphertext_b64"] = "AA=="

    with pytest.raises(CryptoFailure) as caught:
        crypto.decrypt(encrypted, aad=b"aad")

    assert "never disclose me" not in str(caught.value)


def test_macos_adapter_transports_secrets_only_over_private_file_descriptors(
    tmp_path: Path,
) -> None:
    helper = tmp_path / "crypto-helper"
    helper.write_text(
        """#!/usr/bin/env python3
import base64, json, os, sys
request_fd = int(sys.argv[2]); response_fd = int(sys.argv[4])
raw = b''
while True:
    chunk = os.read(request_fd, 65536)
    if not chunk: break
    raw += chunk
request = json.loads(raw)
if request['operation'] == 'encrypt':
    response = {
      'ok': True, 'algorithm': 'AES-256-GCM', 'key_id': request['key_id'],
      'nonce_b64': base64.b64encode(b'n' * 12).decode(),
      'ciphertext_b64': request['plaintext_b64'],
      'tag_b64': base64.b64encode(b't' * 16).decode(),
    }
else:
    response = {'ok': True, 'plaintext_b64': request['ciphertext_b64']}
os.write(response_fd, json.dumps(response, separators=(',', ':')).encode())
""",
        encoding="utf-8",
    )
    helper.chmod(0o700)
    crypto = MacOSKeychainCrypto(helper, key_id="owner-key-v1", allow_non_darwin=True)

    encrypted = crypto.encrypt(b"fd-only-secret", aad=b"bound metadata")
    assert crypto.decrypt(encrypted, aad=b"bound metadata") == b"fd-only-secret"

    # The helper only receives numeric FD switches in argv.  Its inherited
    # environment is empty and stdout/stderr are never protocol channels.
    assert encrypted["algorithm"] == "AES-256-GCM"
    assert "fd-only-secret" not in repr(crypto.command)
    assert os.environ.get("fd-only-secret") is None


def test_macos_adapter_redacts_helper_failures(tmp_path: Path) -> None:
    helper = tmp_path / "crypto-helper"
    helper.write_text(
        """#!/usr/bin/env python3
import json, os, sys
request_fd = int(sys.argv[2]); response_fd = int(sys.argv[4])
while os.read(request_fd, 65536): pass
os.write(response_fd, json.dumps({'ok': False, 'code': 'keychain_unavailable'}).encode())
""",
        encoding="utf-8",
    )
    helper.chmod(0o700)
    crypto = MacOSKeychainCrypto(helper, allow_non_darwin=True)

    with pytest.raises(CryptoFailure) as caught:
        crypto.encrypt(b"super secret prompt", aad=b"metadata")

    assert caught.value.code == "keychain_unavailable"
    assert "super secret prompt" not in str(caught.value)


def test_macos_adapter_rejects_symlink_or_insecure_helper(tmp_path: Path) -> None:
    helper = tmp_path / "helper"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o722)
    with pytest.raises(CryptoFailure, match="helper is insecure"):
        MacOSKeychainCrypto(helper, allow_non_darwin=True)

    helper.chmod(0o700)
    link = tmp_path / "helper-link"
    link.symlink_to(helper)
    with pytest.raises(CryptoFailure, match="helper is insecure"):
        MacOSKeychainCrypto(link, allow_non_darwin=True)


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("xcrun") is None,
    reason="the production helper requires macOS CryptoKit and Security",
)
def test_real_swift_helper_returns_one_valid_response_over_private_pipe(
    tmp_path: Path,
) -> None:
    source = (
        Path(__file__).parents[1]
        / "native"
        / "intent-payload-crypto"
        / "main.swift"
    )
    helper = tmp_path / "intent-payload-crypto"
    sdk_path = subprocess.check_output(
        ["xcrun", "--show-sdk-path"], text=True, timeout=30
    ).strip()
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-sdk",
            sdk_path,
            str(source),
            "-o",
            str(helper),
        ],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=30,
    )

    def invoke(raw: bytes) -> tuple[int, object]:
        request_read, request_write = os.pipe()
        response_read, response_write = os.pipe()
        process = subprocess.Popen(
            [
                str(helper),
                "--request-fd",
                str(request_read),
                "--response-fd",
                str(response_write),
            ],
            pass_fds=(request_read, response_write),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={},
        )
        os.close(request_read)
        os.close(response_write)
        os.write(request_write, raw)
        os.close(request_write)
        chunks = []
        while True:
            chunk = os.read(response_read, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
        os.close(response_read)
        return process.wait(timeout=5), json.loads(b"".join(chunks))

    assert invoke(b"{}") == (0, {"ok": False, "code": "invalid_request"})
    assert invoke(b'{"operation":"encrypt","operation":"decrypt"}') == (
        0,
        {"ok": False, "code": "invalid_request"},
    )
