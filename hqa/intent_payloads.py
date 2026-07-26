from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import base64
import binascii
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import time
from typing import Any, Callable, Iterator, Mapping, Optional

from hqa.intent_payload_crypto import CryptoFailure, IntentPayloadCrypto
from hqa.research_claim import ResearchClaimError, normalize_research_claim


_SCHEMA_VERSION = "2.0"
_INTENT_KINDS = frozenset(
    {"conversation_turn", "research_start", "research_continue"}
)
_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "owner_id",
        "workspace_id",
        "session_id",
        "client_intent_id",
        "provider_policy",
        "prompt",
        "ttl_days",
    }
)
_RESEARCH_CLAIM_FIELD = frozenset({"research_claim"})
_ENVELOPE_METADATA_FIELDS = {
    "provider_policy_digest",
    "created_at",
    "expires_at",
}
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_WORKSPACE_RE = re.compile(r"workspace:[A-Za-z0-9][A-Za-z0-9._:-]{0,189}\Z")
_SESSION_RE = re.compile(r"session:[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z")
_RESEARCH_CONSUMER_RE = re.compile(r"attempt:[0-9a-f]{64}\Z")
_COMMAND_CONSUMER_RE = re.compile(
    r"command:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z"
)
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_PAYLOAD_REF_RE = re.compile(r"payload:sha256:([0-9a-f]{64})\Z")
_EVENT_ID_RE = re.compile(r"event:[0-9a-f]{64}\Z")
_MAX_PROMPT_BYTES = 262_144
_MAX_PROVIDER_POLICY_BYTES = 65_536
_MAX_ENVELOPE_BYTES = 524_288
_MAX_BLOB_BYTES = 1_000_000
_MAX_EVENT_BYTES = 262_144
_MAX_JOURNAL_BYTES = 64 * 1024 * 1024
_MAX_INDEX_BYTES = 64 * 1024 * 1024
_MAX_BACKUP_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_PAYLOAD_COUNT = 4_096
_MAX_AGGREGATE_CIPHERTEXT_BYTES = 256 * 1024 * 1024


class IntentPayloadError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _invalid(message: str) -> IntentPayloadError:
    return IntentPayloadError("intent_invalid_request", message)


def _corrupt(message: str) -> IntentPayloadError:
    return IntentPayloadError("intent_payload_corrupt", message)


def _insecure(message: str) -> IntentPayloadError:
    return IntentPayloadError("intent_storage_insecure", message)


def _reject_constant(_: str) -> None:
    raise _corrupt("intent authority contains a non-finite JSON number")


def _without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _corrupt("intent authority contains a duplicate JSON object key")
        result[key] = value
    return result


def _validate_json_tree(value: Any, *, stored: bool = False) -> None:
    error = _corrupt if stored else _invalid
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > 32:
            raise error("intent JSON nesting exceeds the supported maximum")
        if item is None or type(item) in (str, int, bool):
            if type(item) is str:
                try:
                    item.encode("utf-8", errors="strict")
                except UnicodeEncodeError as exc:
                    raise error("intent JSON contains invalid unicode") from exc
            elif type(item) is int and abs(item) > 9_007_199_254_740_991:
                raise error("intent JSON integer exceeds the interoperable range")
            continue
        if type(item) is float:
            if not math.isfinite(item):
                raise error("intent JSON numbers must be finite")
            continue
        if type(item) is list:
            stack.extend((child, depth + 1) for child in item)
            continue
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise error("intent JSON object keys must be strings")
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
            continue
        raise error("intent values must be strict JSON")


def _canonical_bytes(value: Any) -> bytes:
    _validate_json_tree(value)
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise _invalid("intent values must be strict JSON") from exc


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> str:
    canonical = _canonical_bytes(value)
    return _digest_bytes(canonical[:-1])


def _canonical_timestamp(value: Any, field: str, *, stored: bool = False) -> str:
    error = _corrupt if stored else _invalid
    if type(value) is not str or not value:
        raise error("{} must be a timezone-aware timestamp".format(field))
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError) as exc:
        raise error("{} must be a timezone-aware timestamp".format(field)) from exc


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _identifier(value: Any, field: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise _invalid("{} is invalid".format(field))
    return value


def _scoped_ref(value: Any, field: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise _invalid("{} is not a canonical scoped reference".format(field))
    return value


def _payload_digest_from_ref(payload_ref: Any) -> str:
    if type(payload_ref) is not str:
        raise _invalid("payload_ref is invalid")
    match = _PAYLOAD_REF_RE.fullmatch(payload_ref)
    if match is None:
        raise _invalid("payload_ref must be payload:sha256:<lowercase digest>")
    return match.group(1)


def _validate_consumer_for_kind(value: Any, kind: str) -> str:
    pattern = (
        _COMMAND_CONSUMER_RE
        if kind == "conversation_turn"
        else _RESEARCH_CONSUMER_RE
    )
    if type(value) is not str or pattern.fullmatch(value) is None:
        expected = "command:" if kind == "conversation_turn" else "attempt:"
        raise _invalid("consumer_ref must be an exact {} reference".format(expected))
    return value


def _normalize_request(request: Any) -> dict[str, Any]:
    if type(request) is not dict or set(request) not in {
        _REQUEST_FIELDS,
        _REQUEST_FIELDS | _RESEARCH_CLAIM_FIELD,
    }:
        raise _invalid("intent request fields are invalid")
    if request["schema_version"] != _SCHEMA_VERSION:
        raise _invalid("intent schema_version is unsupported")
    kind = request["kind"]
    if type(kind) is not str or kind not in _INTENT_KINDS:
        raise _invalid("intent kind is unsupported")
    owner_id = _identifier(request["owner_id"], "owner_id")
    workspace_id = _scoped_ref(request["workspace_id"], "workspace_id", _WORKSPACE_RE)
    session_id = _scoped_ref(request["session_id"], "session_id", _SESSION_RE)
    client_intent_id = _identifier(request["client_intent_id"], "client_intent_id")
    ttl_days = request["ttl_days"]
    if type(ttl_days) is not int or not 1 <= ttl_days <= 30:
        raise _invalid("ttl_days must be an integer from 1 through 30")
    prompt = request["prompt"]
    if type(prompt) is not str or not prompt.strip():
        raise _invalid("prompt must be nonempty text")
    try:
        prompt_size = len(prompt.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise _invalid("prompt must be valid UTF-8") from exc
    if prompt_size > _MAX_PROMPT_BYTES:
        raise _invalid("prompt exceeds the maximum size")
    provider_policy = request["provider_policy"]
    if type(provider_policy) is not dict:
        raise _invalid("provider_policy must be a JSON object")
    _validate_json_tree(provider_policy)
    provider_policy_bytes = _canonical_bytes(provider_policy)
    if len(provider_policy_bytes) > _MAX_PROVIDER_POLICY_BYTES:
        raise _invalid("provider_policy exceeds the maximum size")
    provider_policy = json.loads(provider_policy_bytes.decode("utf-8"))
    normalized = {
        "schema_version": _SCHEMA_VERSION,
        "kind": kind,
        "owner_id": owner_id,
        "workspace_id": workspace_id,
        "session_id": session_id,
        "client_intent_id": client_intent_id,
        "provider_policy": provider_policy,
        "prompt": prompt,
        "ttl_days": ttl_days,
    }
    if "research_claim" in request:
        if kind not in {"research_start", "research_continue"}:
            raise _invalid("research_claim is valid only for research intents")
        try:
            normalized["research_claim"] = normalize_research_claim(
                request["research_claim"]
            )
        except ResearchClaimError as exc:
            raise _invalid("research_claim is invalid") from exc
    if len(_canonical_bytes(normalized)) > _MAX_ENVELOPE_BYTES:
        raise _invalid("intent canonical envelope exceeds the maximum size")
    return normalized


def _client_identity(request: Mapping[str, Any]) -> dict[str, str]:
    return {
        "owner_id": request["owner_id"],
        "workspace_id": request["workspace_id"],
        "session_id": request["session_id"],
        "client_intent_id": request["client_intent_id"],
    }


def _aad_document(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "payload_digest": entry["payload_digest"],
        "kind": entry["kind"],
        "owner_id": entry["owner_id"],
        "workspace_id": entry["workspace_id"],
        "session_id": entry["session_id"],
        "client_intent_id": entry["client_intent_id"],
        "provider_policy_digest": entry["provider_policy_digest"],
        "created_at": entry["created_at"],
        "expires_at": entry["expires_at"],
        "ttl_days": entry["ttl_days"],
        "key_id": entry["key_id"],
    }


def _record_digest(event: Mapping[str, Any]) -> str:
    return _digest({key: value for key, value in event.items() if key != "record_sha256"})


class IntentPayloadStore:
    """Encrypted, content-addressed authority for v0.2 intent payloads.

    The append-only event journal and its index contain metadata only.  Prompt
    and provider policy plaintext exist solely inside an authenticated encrypted
    blob and in caller memory during put/resolve.
    """

    def __init__(
        self,
        root: Path,
        *,
        crypto: IntentPayloadCrypto,
        now: Optional[Callable[[], str]] = None,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self.root = Path(os.path.abspath(root))
        self.crypto = crypto
        self._now = now or (
            lambda: datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        key_id = getattr(crypto, "key_id", None)
        algorithm = getattr(crypto, "algorithm", None)
        if type(key_id) is not str or _IDENTIFIER_RE.fullmatch(key_id) is None:
            raise ValueError("crypto must expose a bounded key_id")
        if (
            type(algorithm) is not str
            or algorithm
            not in {"AES-256-GCM", "HQA-TEST-HMAC-STREAM-V1"}
        ):
            raise ValueError("crypto must expose a supported algorithm")
        if not callable(getattr(crypto, "encrypt", None)) or not callable(
            getattr(crypto, "decrypt", None)
        ):
            raise TypeError("crypto must expose encrypt and decrypt")
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(float(lock_timeout_seconds))
            or not 0 < float(lock_timeout_seconds) <= 30
        ):
            raise ValueError("lock timeout must be finite and from 0 to 30 seconds")
        self._lock_timeout_seconds = float(lock_timeout_seconds)

    def put(self, request: dict[str, Any]) -> dict[str, Any]:
        """Durably accept one closed-schema intent and return metadata only."""
        normalized = _normalize_request(request)
        request_digest = _digest(normalized)
        client_identity_digest = _digest(_client_identity(normalized))
        try:
            with self._locked(create=True) as locked:
                assert locked is not None
                root_fd, event_fd = locked
                events, projection = self._load_state(root_fd, event_fd)
                events, projection = self._expire_due(root_fd, event_fd, events, projection)
                existing_digest = projection["clients"].get(client_identity_digest)
                if existing_digest is not None:
                    entry = projection["payloads"][existing_digest]
                    if entry["request_digest"] != request_digest:
                        raise IntentPayloadError(
                            "intent_idempotency_conflict",
                            "client_intent_id already belongs to a different intent",
                        )
                    if entry["status"] == "expired":
                        raise IntentPayloadError(
                            "intent_payload_expired",
                            "intent payload expired; create a new client_intent_id",
                        )
                    self._audit_inventory(root_fd, projection)
                    self._verify_blob(root_fd, entry)
                    self._publish_index(root_fd, projection)
                    return self._put_receipt(entry)

                created_at = _canonical_timestamp(self._now(), "created_at")
                expires_at = (
                    _parse_timestamp(created_at)
                    + timedelta(days=normalized["ttl_days"])
                ).isoformat(timespec="microseconds").replace("+00:00", "Z")
                provider_policy_digest = _digest(normalized["provider_policy"])
                envelope = {
                    **normalized,
                    "provider_policy_digest": provider_policy_digest,
                    "created_at": created_at,
                    "expires_at": expires_at,
                }
                envelope_bytes = _canonical_bytes(envelope)
                if len(envelope_bytes) > _MAX_ENVELOPE_BYTES:
                    raise _invalid("intent canonical envelope exceeds the maximum size")
                payload_digest = _digest_bytes(envelope_bytes)
                entry = {
                    "payload_digest": payload_digest,
                    "payload_ref": "payload:sha256:" + payload_digest,
                    "client_identity_digest": client_identity_digest,
                    "request_digest": request_digest,
                    "kind": normalized["kind"],
                    "owner_id": normalized["owner_id"],
                    "workspace_id": normalized["workspace_id"],
                    "session_id": normalized["session_id"],
                    "client_intent_id": normalized["client_intent_id"],
                    "provider_policy_digest": provider_policy_digest,
                    "created_at": created_at,
                    "expires_at": expires_at,
                    "ttl_days": normalized["ttl_days"],
                    "key_id": self.crypto.key_id,
                }
                aad = _canonical_bytes(_aad_document(entry))
                try:
                    encrypted = self.crypto.encrypt(envelope_bytes, aad=aad)
                except CryptoFailure as exc:
                    raise self._mapped_crypto_failure(exc, decrypting=False) from None
                if not isinstance(encrypted, Mapping) or set(encrypted) != {
                    "algorithm",
                    "key_id",
                    "nonce_b64",
                    "ciphertext_b64",
                    "tag_b64",
                }:
                    raise IntentPayloadError(
                        "intent_crypto_error", "intent encryption failed"
                    )
                if (
                    encrypted.get("key_id") != self.crypto.key_id
                    or encrypted.get("algorithm") != self.crypto.algorithm
                    or any(type(value) is not str for value in encrypted.values())
                    or any(len(value) > 1_400_000 for value in encrypted.values())
                ):
                    raise IntentPayloadError(
                        "intent_crypto_error", "intent encryption failed"
                    )
                blob = {
                    "schema_version": _SCHEMA_VERSION,
                    "payload_digest": payload_digest,
                    "aad_sha256": _digest_bytes(aad),
                    "encryption": dict(encrypted),
                }
                blob_bytes = _canonical_bytes(blob)
                if len(blob_bytes) > _MAX_BLOB_BYTES:
                    raise _invalid("encrypted intent payload exceeds the maximum size")
                entry["blob_sha256"] = _digest_bytes(blob_bytes)
                self._write_or_verify_blob(root_fd, payload_digest, blob_bytes)
                event = self._new_event(
                    events=events,
                    kind="payload_stored",
                    recorded_at=created_at,
                    payload=entry,
                )
                self._append_event(event_fd, event)
                events = [*events, event]
                projection = self._project(events)
                self._audit_inventory(root_fd, projection)
                self._publish_index(root_fd, projection)
                return self._put_receipt(projection["payloads"][payload_digest])
        except IntentPayloadError:
            raise
        except OSError as exc:
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent payload write failed",
                retryable=True,
            ) from exc

    def bind_consumer(
        self,
        *,
        payload_ref: str,
        consumer_ref: str,
        owner_id: str,
        workspace_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Bind exactly one scoped command/attempt consumer, idempotently."""
        payload_digest = _payload_digest_from_ref(payload_ref)
        owner_id = _identifier(owner_id, "owner_id")
        workspace_id = _scoped_ref(workspace_id, "workspace_id", _WORKSPACE_RE)
        session_id = _scoped_ref(session_id, "session_id", _SESSION_RE)
        if type(consumer_ref) is not str or len(consumer_ref) > 256:
            raise _invalid("consumer_ref is invalid")
        try:
            with self._locked(create=False) as locked:
                if locked is None:
                    raise IntentPayloadError(
                        "intent_payload_not_found", "intent payload was not found"
                    )
                root_fd, event_fd = locked
                events, projection = self._load_state(root_fd, event_fd)
                events, projection = self._expire_due(root_fd, event_fd, events, projection)
                entry = projection["payloads"].get(payload_digest)
                if entry is None:
                    raise IntentPayloadError(
                        "intent_payload_not_found", "intent payload was not found"
                    )
                self._require_scope(
                    entry,
                    owner_id=owner_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                )
                consumer_ref = _validate_consumer_for_kind(
                    consumer_ref, entry["kind"]
                )
                if entry["status"] == "expired":
                    raise IntentPayloadError(
                        "intent_payload_expired", "intent payload has expired"
                    )
                if entry["consumer_ref"] is not None:
                    if entry["consumer_ref"] != consumer_ref:
                        raise IntentPayloadError(
                            "intent_consumer_conflict",
                            "intent payload already belongs to a different consumer",
                        )
                    self._audit_inventory(root_fd, projection)
                    self._verify_blob(root_fd, entry)
                    return self._receipt(entry)
                event = self._new_event(
                    events=events,
                    kind="consumer_bound",
                    recorded_at=_canonical_timestamp(self._now(), "recorded_at"),
                    payload={
                        "payload_digest": payload_digest,
                        "payload_ref": payload_ref,
                        "consumer_ref": consumer_ref,
                    },
                )
                self._append_event(event_fd, event)
                events = [*events, event]
                projection = self._project(events)
                self._audit_inventory(root_fd, projection)
                self._publish_index(root_fd, projection)
                return self._receipt(projection["payloads"][payload_digest])
        except IntentPayloadError:
            raise
        except OSError as exc:
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent consumer binding failed",
                retryable=True,
            ) from exc

    def resolve(
        self,
        payload_ref: str,
        *,
        owner_id: str,
        workspace_id: str,
        session_id: str,
        consumer_ref: Optional[str] = None,
    ) -> dict[str, Any]:
        """Resolve plaintext for a trusted in-process consumer only.

        This method is deliberately not a CLI, cron, log, or stdout surface.
        """
        payload_digest = _payload_digest_from_ref(payload_ref)
        owner_id = _identifier(owner_id, "owner_id")
        workspace_id = _scoped_ref(workspace_id, "workspace_id", _WORKSPACE_RE)
        session_id = _scoped_ref(session_id, "session_id", _SESSION_RE)
        if consumer_ref is not None and (
            type(consumer_ref) is not str
            or len(consumer_ref) > 256
        ):
            raise _invalid("consumer_ref is invalid")
        try:
            with self._locked(create=False) as locked:
                if locked is None:
                    raise IntentPayloadError(
                        "intent_payload_not_found", "intent payload was not found"
                    )
                root_fd, event_fd = locked
                events, projection = self._load_state(root_fd, event_fd)
                events, projection = self._expire_due(root_fd, event_fd, events, projection)
                entry = projection["payloads"].get(payload_digest)
                if entry is None:
                    raise IntentPayloadError(
                        "intent_payload_not_found", "intent payload was not found"
                    )
                if entry["status"] == "expired":
                    raise IntentPayloadError(
                        "intent_payload_expired", "intent payload has expired"
                    )
                self._require_scope(
                    entry,
                    owner_id=owner_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                )
                if consumer_ref is not None:
                    consumer_ref = _validate_consumer_for_kind(
                        consumer_ref, entry["kind"]
                    )
                if entry["consumer_ref"] != consumer_ref:
                    raise IntentPayloadError(
                        "intent_consumer_mismatch",
                        "intent payload consumer binding does not match",
                    )
                self._audit_inventory(root_fd, projection)
                envelope = self._verify_blob(root_fd, entry)
                self._publish_index(root_fd, projection)
                return envelope
        except IntentPayloadError:
            raise
        except OSError as exc:
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent payload resolution failed",
                retryable=True,
            ) from exc

    def status(
        self,
        payload_ref: str,
        *,
        owner_id: str,
        workspace_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Return owner/workspace/session-scoped metadata without plaintext."""
        payload_digest = _payload_digest_from_ref(payload_ref)
        owner_id = _identifier(owner_id, "owner_id")
        workspace_id = _scoped_ref(workspace_id, "workspace_id", _WORKSPACE_RE)
        session_id = _scoped_ref(session_id, "session_id", _SESSION_RE)
        try:
            with self._locked(create=False) as locked:
                if locked is None:
                    raise IntentPayloadError(
                        "intent_payload_not_found", "intent payload was not found"
                    )
                root_fd, event_fd = locked
                events, projection = self._load_state(root_fd, event_fd)
                events, projection = self._expire_due(root_fd, event_fd, events, projection)
                entry = projection["payloads"].get(payload_digest)
                if entry is None:
                    raise IntentPayloadError(
                        "intent_payload_not_found", "intent payload was not found"
                    )
                self._require_scope(
                    entry,
                    owner_id=owner_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                )
                self._audit_inventory(root_fd, projection)
                if entry["status"] == "active":
                    self._verify_blob(root_fd, entry)
                self._publish_index(root_fd, projection)
                return self._receipt(entry)
        except IntentPayloadError:
            raise
        except OSError as exc:
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent payload status failed",
                retryable=True,
            ) from exc

    def reconcile_expired(self, *, limit: int = 100) -> dict[str, Any]:
        """Bounded no-agent retention entrypoint; output never contains bodies."""
        if type(limit) is not int or not 1 <= limit <= 1_000:
            raise _invalid("limit must be an integer from 1 through 1000")
        try:
            with self._locked(create=False) as locked:
                if locked is None:
                    return {
                        "schema_version": _SCHEMA_VERSION,
                        "expired": [],
                        "tombstones": [],
                        "active_count": 0,
                        "remaining_due": 0,
                        "pending_tombstone_count": 0,
                    }
                root_fd, event_fd = locked
                events, projection = self._load_state(root_fd, event_fd)
                before = {
                    digest
                    for digest, entry in projection["payloads"].items()
                    if entry["status"] == "expired"
                }
                events, projection = self._expire_due(
                    root_fd, event_fd, events, projection, limit=limit
                )
                after = {
                    digest
                    for digest, entry in projection["payloads"].items()
                    if entry["status"] == "expired"
                }
                pending_tombstones = sorted(
                    (
                        entry
                        for entry in projection["payloads"].values()
                        if entry["status"] == "expired"
                        and entry["expiry_acknowledged_event_id"] is None
                        and entry["kind"]
                        in {"research_start", "research_continue"}
                        and type(entry["consumer_ref"]) is str
                        and _RESEARCH_CONSUMER_RE.fullmatch(
                            entry["consumer_ref"]
                        )
                        is not None
                    ),
                    key=lambda entry: (
                        entry["expired_at"],
                        entry["payload_digest"],
                    ),
                )
                self._audit_inventory(root_fd, projection)
                self._publish_index(root_fd, projection)
                return {
                    "schema_version": _SCHEMA_VERSION,
                    "expired": ["payload:sha256:" + value for value in sorted(after - before)],
                    "tombstones": [
                        self._tombstone_receipt(entry)
                        for entry in pending_tombstones[:limit]
                    ],
                    "active_count": sum(
                        entry["status"] == "active"
                        for entry in projection["payloads"].values()
                    ),
                    "remaining_due": sum(
                        entry["status"] == "active"
                        and _parse_timestamp(entry["expires_at"])
                        <= _parse_timestamp(
                            _canonical_timestamp(self._now(), "observed_at")
                        )
                        for entry in projection["payloads"].values()
                    ),
                    "pending_tombstone_count": len(pending_tombstones),
                }
        except IntentPayloadError:
            raise
        except OSError as exc:
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent expiry reconciliation failed",
                retryable=True,
            ) from exc

    def acknowledge_expiry(
        self,
        *,
        payload_ref: str,
        tombstone_event_ref: str,
        tombstone_digest: str,
        consumer_ref: str,
        consumer_event_ref: str,
        consumer_operation_digest: str,
        owner_id: str,
        workspace_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Record exact downstream consumption of one expiry tombstone."""
        payload_digest = _payload_digest_from_ref(payload_ref)
        owner_id = _identifier(owner_id, "owner_id")
        workspace_id = _scoped_ref(workspace_id, "workspace_id", _WORKSPACE_RE)
        session_id = _scoped_ref(session_id, "session_id", _SESSION_RE)
        for value, field in (
            (tombstone_event_ref, "tombstone_event_ref"),
            (consumer_event_ref, "consumer_event_ref"),
        ):
            if type(value) is not str or _EVENT_ID_RE.fullmatch(value) is None:
                raise _invalid("{} is invalid".format(field))
        for value, field in (
            (tombstone_digest, "tombstone_digest"),
            (consumer_operation_digest, "consumer_operation_digest"),
        ):
            if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
                raise _invalid("{} is invalid".format(field))
        if type(consumer_ref) is not str or len(consumer_ref) > 256:
            raise _invalid("consumer_ref is invalid")
        try:
            with self._locked(create=False) as locked:
                if locked is None:
                    raise IntentPayloadError(
                        "intent_payload_not_found", "intent payload was not found"
                    )
                root_fd, event_fd = locked
                events, projection = self._load_state(root_fd, event_fd)
                events, projection = self._expire_due(
                    root_fd, event_fd, events, projection
                )
                entry = projection["payloads"].get(payload_digest)
                if entry is None:
                    raise IntentPayloadError(
                        "intent_payload_not_found", "intent payload was not found"
                    )
                self._require_scope(
                    entry,
                    owner_id=owner_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                )
                consumer_ref = _validate_consumer_for_kind(
                    consumer_ref, entry["kind"]
                )
                if (
                    entry["kind"]
                    not in {"research_start", "research_continue"}
                    or _RESEARCH_CONSUMER_RE.fullmatch(consumer_ref) is None
                ):
                    raise IntentPayloadError(
                        "intent_expiry_acknowledgement_not_required",
                        "intent payload has no research workflow consumer",
                    )
                if entry["status"] != "expired":
                    raise IntentPayloadError(
                        "intent_payload_not_expired",
                        "intent payload has not expired",
                    )
                expected = {
                    "payload_digest": payload_digest,
                    "payload_ref": payload_ref,
                    "tombstone_event_ref": tombstone_event_ref,
                    "tombstone_digest": tombstone_digest,
                    "consumer_ref": consumer_ref,
                    "consumer_event_ref": consumer_event_ref,
                    "consumer_operation_digest": consumer_operation_digest,
                }
                if (
                    entry["expired_event_id"] != tombstone_event_ref
                    or entry["expired_record_sha256"] != tombstone_digest
                    or entry["consumer_ref"] != consumer_ref
                ):
                    raise IntentPayloadError(
                        "intent_expiry_acknowledgement_conflict",
                        "intent expiry acknowledgement does not match",
                    )
                if entry["expiry_acknowledged_event_id"] is not None:
                    if (
                        entry["expiry_consumer_event_ref"] != consumer_event_ref
                        or entry["expiry_consumer_operation_digest"]
                        != consumer_operation_digest
                    ):
                        raise IntentPayloadError(
                            "intent_expiry_acknowledgement_conflict",
                            "intent expiry acknowledgement does not match",
                        )
                    return self._expiry_acknowledgement_receipt(entry)
                event = self._new_event(
                    events=events,
                    kind="expiry_acknowledged",
                    recorded_at=_canonical_timestamp(
                        self._now(), "acknowledged_at"
                    ),
                    payload=expected,
                )
                self._append_event(event_fd, event)
                events = [*events, event]
                projection = self._project(events)
                self._audit_inventory(root_fd, projection)
                self._publish_index(root_fd, projection)
                return self._expiry_acknowledgement_receipt(
                    projection["payloads"][payload_digest]
                )
        except IntentPayloadError:
            raise
        except OSError as exc:
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent expiry acknowledgement failed",
                retryable=True,
            ) from exc

    def reverse_audit(self) -> dict[str, Any]:
        """Verify journal, index, ciphertext inventory, and active decryptability."""
        try:
            with self._locked(create=False) as locked:
                if locked is None:
                    return {
                        "schema_version": _SCHEMA_VERSION,
                        "status": "ok",
                        "event_count": 0,
                        "payload_count": 0,
                        "active_payloads": 0,
                        "expired_payloads": 0,
                        "last_record_sha256": None,
                    }
                root_fd, event_fd = locked
                events, projection = self._load_state(root_fd, event_fd)
                events, projection = self._expire_due(root_fd, event_fd, events, projection)
                self._audit_inventory(root_fd, projection)
                for entry in projection["payloads"].values():
                    if entry["status"] == "active":
                        self._verify_blob(root_fd, entry)
                self._publish_index(root_fd, projection)
                return {
                    "schema_version": _SCHEMA_VERSION,
                    "status": "ok",
                    "event_count": len(events),
                    "payload_count": len(projection["payloads"]),
                    "active_payloads": sum(
                        entry["status"] == "active"
                        for entry in projection["payloads"].values()
                    ),
                    "expired_payloads": sum(
                        entry["status"] == "expired"
                        for entry in projection["payloads"].values()
                    ),
                    "last_record_sha256": (
                        events[-1]["record_sha256"] if events else None
                    ),
                }
        except IntentPayloadError:
            raise
        except OSError as exc:
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent reverse audit failed",
                retryable=True,
            ) from exc

    def rebuild_index(self) -> dict[str, Any]:
        """Rebuild the disposable metadata index from the canonical journal."""
        try:
            with self._locked(create=False) as locked:
                if locked is None:
                    return {
                        "schema_version": _SCHEMA_VERSION,
                        "event_count": 0,
                        "payload_count": 0,
                    }
                root_fd, event_fd = locked
                events = self._read_events(event_fd)
                projection = self._project(events)
                self._recover_storage(root_fd, projection)
                projection_events, projection = self._expire_due(
                    root_fd, event_fd, events, projection
                )
                self._audit_inventory(root_fd, projection)
                for entry in projection["payloads"].values():
                    if entry["status"] == "active":
                        self._verify_blob(root_fd, entry)
                self._publish_index(root_fd, projection)
                return {
                    "schema_version": _SCHEMA_VERSION,
                    "event_count": len(projection_events),
                    "payload_count": len(projection["payloads"]),
                }
        except IntentPayloadError:
            raise
        except OSError as exc:
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent projection rebuild failed",
                retryable=True,
            ) from exc

    def backup(self, destination: Path) -> dict[str, Any]:
        """Create an owner-only ciphertext backup with bounded aggregate size."""
        destination = Path(os.path.abspath(destination))
        self._reject_overlapping_path(destination)
        try:
            with self._locked(create=False) as locked:
                if locked is None:
                    events: list[dict[str, Any]] = []
                    projection = self._project(events)
                    event_bytes = b""
                    blob_bytes: dict[str, bytes] = {}
                else:
                    root_fd, event_fd = locked
                    events, projection = self._load_state(root_fd, event_fd)
                    events, projection = self._expire_due(
                        root_fd, event_fd, events, projection
                    )
                    self._audit_inventory(root_fd, projection)
                    blob_bytes = {}
                    aggregate_ciphertext_bytes = 0
                    for digest, entry in projection["payloads"].items():
                        if entry["status"] != "active":
                            continue
                        if len(blob_bytes) >= _MAX_PAYLOAD_COUNT:
                            raise _corrupt(
                                "intent backup exceeds the payload count limit"
                            )
                        self._verify_blob(root_fd, entry)
                        raw = self._read_blob(root_fd, digest)
                        aggregate_ciphertext_bytes += len(raw)
                        if (
                            aggregate_ciphertext_bytes
                            > _MAX_AGGREGATE_CIPHERTEXT_BYTES
                        ):
                            raise _corrupt(
                                "intent backup exceeds the aggregate ciphertext limit"
                            )
                        blob_bytes[digest] = raw
                    event_bytes = self._read_fd_bounded(
                        event_fd, _MAX_JOURNAL_BYTES, "intent journal"
                    )
                    self._publish_index(root_fd, projection)

                created_at = _canonical_timestamp(self._now(), "created_at")
                manifest: dict[str, Any] = {
                    "schema_version": _SCHEMA_VERSION,
                    "kind": "intent_payload_backup",
                    "created_at": created_at,
                    "key_ids": sorted(
                        {
                            entry["key_id"]
                            for entry in projection["payloads"].values()
                            if entry["status"] == "active"
                        }
                    ),
                    "events_sha256": _digest_bytes(event_bytes),
                    "event_count": len(events),
                    "last_record_sha256": (
                        events[-1]["record_sha256"] if events else None
                    ),
                    "blobs": {
                        digest: _digest_bytes(raw)
                        for digest, raw in sorted(blob_bytes.items())
                    },
                }
                manifest["manifest_sha256"] = _digest(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "manifest_sha256"
                    }
                )
                self._write_backup(destination, event_bytes, blob_bytes, manifest)
                return manifest
        except IntentPayloadError:
            raise
        except OSError as exc:
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent backup failed",
                retryable=True,
            ) from exc

    def restore(self, source: Path) -> dict[str, Any]:
        """Validate in staging and atomically publish a same-key restore."""
        source = Path(os.path.abspath(source))
        self._reject_overlapping_path(source)
        manifest, event_bytes, blob_bytes = self._read_backup(source)
        if any(key_id != self.crypto.key_id for key_id in manifest["key_ids"]):
            raise IntentPayloadError(
                "intent_restore_key_mismatch",
                "intent backup requires a different device key",
            )
        backup_events = self._decode_events(event_bytes)
        backup_projection = self._project(backup_events)
        if len(backup_events) != manifest["event_count"] or (
            backup_events[-1]["record_sha256"] if backup_events else None
        ) != manifest["last_record_sha256"]:
            raise _corrupt("intent backup event manifest does not match")
        expected_active = {
            digest
            for digest, entry in backup_projection["payloads"].items()
            if entry["status"] == "active"
        }
        if set(blob_bytes) != expected_active:
            raise _corrupt("intent backup blob inventory does not match its events")
        restored_at = _canonical_timestamp(self._now(), "restored_at")
        restored_now = _parse_timestamp(restored_at)
        for digest, raw in blob_bytes.items():
            entry = backup_projection["payloads"][digest]
            if _parse_timestamp(entry["expires_at"]) <= restored_now:
                self._verify_blob_container(raw, entry)
            else:
                self._verify_blob_bytes(raw, entry)

        try:
            target_metadata = os.lstat(self.root)
        except FileNotFoundError:
            target_metadata = None
        if target_metadata is not None:
            if stat.S_ISLNK(target_metadata.st_mode):
                raise _insecure("intent restore target must not be a symbolic link")
            raise IntentPayloadError(
                "intent_restore_requires_empty",
                "intent restore target must not exist before atomic restore",
            )

        parent = self.root.parent
        self._assert_directory_chain(parent)
        parent_metadata = os.stat(parent, follow_symlinks=False)
        if parent_metadata.st_uid != os.geteuid():
            raise _insecure("intent restore parent must be owned by the current user")
        staging = parent / ("." + self.root.name + ".intent-restore-v2.tmp")
        self._remove_restore_staging(staging)
        staging_store = IntentPayloadStore(
            staging,
            crypto=self.crypto,
            now=lambda: restored_at,
            lock_timeout_seconds=self._lock_timeout_seconds,
        )
        try:
            result = staging_store._materialize_restore(
                manifest=manifest,
                backup_events=backup_events,
                backup_projection=backup_projection,
                blob_bytes=blob_bytes,
                restored_at=restored_at,
            )
            staging_store.reverse_audit()
            self._fsync_directory(staging)
            parent_fd = os.open(
                parent,
                os.O_RDONLY
                | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                if self._entry_exists(parent_fd, self.root.name):
                    raise IntentPayloadError(
                        "intent_restore_requires_empty",
                        "intent restore target appeared before atomic publish",
                    )
                os.rename(
                    staging.name,
                    self.root.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            return result
        except IntentPayloadError:
            self._remove_restore_staging(staging)
            raise
        except OSError as exc:
            self._remove_restore_staging(staging)
            raise IntentPayloadError(
                "intent_storage_io_error",
                "intent restore failed",
                retryable=True,
            ) from exc

    def _materialize_restore(
        self,
        *,
        manifest: dict[str, Any],
        backup_events: list[dict[str, Any]],
        backup_projection: dict[str, Any],
        blob_bytes: dict[str, bytes],
        restored_at: str,
    ) -> dict[str, Any]:
        with self._locked(create=True) as locked:
            assert locked is not None
            root_fd, event_fd = locked
            if self._read_events(event_fd):
                raise _corrupt("intent restore staging authority is not empty")
            events = list(backup_events)
            projection = backup_projection
            restored_now = _parse_timestamp(restored_at)
            due = sorted(
                digest
                for digest, entry in projection["payloads"].items()
                if entry["status"] == "active"
                and _parse_timestamp(entry["expires_at"]) <= restored_now
            )
            for digest in due:
                event = self._new_event(
                    events=events,
                    kind="payload_expired",
                    recorded_at=restored_at,
                    payload={
                        "payload_digest": digest,
                        "payload_ref": "payload:sha256:" + digest,
                        "reason": "ttl_elapsed",
                    },
                )
                events.append(event)
            projection = self._project(events)
            restored_payloads = 0
            for digest, raw in sorted(blob_bytes.items()):
                if projection["payloads"][digest]["status"] == "expired":
                    continue
                self._write_or_verify_blob(root_fd, digest, raw)
                restored_payloads += 1
            final_event_bytes = b"".join(_canonical_bytes(event) for event in events)
            if len(final_event_bytes) > _MAX_JOURNAL_BYTES:
                raise _corrupt("restored intent journal exceeds the supported size")
            if final_event_bytes:
                self._write_all_at_end(event_fd, final_event_bytes)
                os.fsync(event_fd)
            self._audit_inventory(root_fd, projection)
            for entry in projection["payloads"].values():
                if entry["status"] == "active":
                    self._verify_blob(root_fd, entry)
            self._publish_index(root_fd, projection)
            return {
                "schema_version": _SCHEMA_VERSION,
                "restored_payloads": restored_payloads,
                "expired_payloads": sum(
                    entry["status"] == "expired"
                    for entry in projection["payloads"].values()
                ),
                "event_count": len(events),
                "key_ids": list(manifest["key_ids"]),
            }

    @staticmethod
    def _remove_restore_staging(staging: Path) -> None:
        try:
            metadata = os.lstat(staging)
        except FileNotFoundError:
            return
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            raise _insecure("intent restore staging path is insecure")
        shutil.rmtree(staging)

    def _load_state(
        self, root_fd: int, event_fd: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        events = self._read_events(event_fd)
        projection = self._project(events)
        self._recover_storage(root_fd, projection)
        if self._entry_exists(root_fd, "index.v2.json"):
            recorded = self._read_index(root_fd)
            index_matches = recorded == projection
        else:
            index_matches = not events
        if not index_matches:
            self._audit_inventory(root_fd, projection)
            for entry in projection["payloads"].values():
                if entry["status"] == "active":
                    self._verify_blob(root_fd, entry)
            self._publish_index(root_fd, projection)
        return events, projection

    def _expire_due(
        self,
        root_fd: int,
        event_fd: int,
        events: list[dict[str, Any]],
        projection: dict[str, Any],
        limit: Optional[int] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        now_text = _canonical_timestamp(self._now(), "expired_at")
        now = _parse_timestamp(now_text)
        due_candidates = (
            (entry["expires_at"], digest)
            for digest, entry in projection["payloads"].items()
            if entry["status"] == "active"
            and _parse_timestamp(entry["expires_at"]) <= now
        )
        due = [digest for _, digest in sorted(due_candidates)]
        if limit is not None:
            due = due[:limit]
        for digest in due:
            event = self._new_event(
                events=events,
                kind="payload_expired",
                recorded_at=now_text,
                payload={
                    "payload_digest": digest,
                    "payload_ref": "payload:sha256:" + digest,
                    "reason": "ttl_elapsed",
                },
            )
            self._append_event(event_fd, event)
            events = [*events, event]
            projection = self._project(events)
            self._unlink_blob_if_present(root_fd, digest)
        self._recover_tombstoned_blobs(root_fd, projection)
        if due:
            self._publish_index(root_fd, projection)
        return events, projection

    @staticmethod
    def _receipt(entry: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "payload_ref": entry["payload_ref"],
            "payload_digest": entry["payload_digest"],
            "kind": entry["kind"],
            "owner_id": entry["owner_id"],
            "workspace_id": entry["workspace_id"],
            "session_id": entry["session_id"],
            "client_intent_id": entry["client_intent_id"],
            "provider_policy_digest": entry["provider_policy_digest"],
            "created_at": entry["created_at"],
            "expires_at": entry["expires_at"],
            "ttl_days": entry["ttl_days"],
            "status": entry["status"],
            "consumer_ref": entry["consumer_ref"],
        }

    @staticmethod
    def _put_receipt(entry: Mapping[str, Any]) -> dict[str, Any]:
        receipt = IntentPayloadStore._receipt(entry)
        receipt["status"] = "active"
        receipt["consumer_ref"] = None
        return receipt

    @staticmethod
    def _tombstone_receipt(entry: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "payload_ref": entry["payload_ref"],
            "payload_digest": entry["payload_digest"],
            "kind": entry["kind"],
            "owner_id": entry["owner_id"],
            "workspace_id": entry["workspace_id"],
            "session_id": entry["session_id"],
            "consumer_ref": entry["consumer_ref"],
            "expires_at": entry["expires_at"],
            "expired_at": entry["expired_at"],
            "tombstone_event_ref": entry["expired_event_id"],
            "tombstone_digest": entry["expired_record_sha256"],
        }

    @staticmethod
    def _expiry_acknowledgement_receipt(
        entry: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "payload_ref": entry["payload_ref"],
            "tombstone_event_ref": entry["expired_event_id"],
            "tombstone_digest": entry["expired_record_sha256"],
            "consumer_ref": entry["consumer_ref"],
            "consumer_event_ref": entry["expiry_consumer_event_ref"],
            "consumer_operation_digest": entry[
                "expiry_consumer_operation_digest"
            ],
            "acknowledgement_event_ref": entry[
                "expiry_acknowledged_event_id"
            ],
            "status": "acknowledged",
        }

    @staticmethod
    def _require_scope(
        entry: Mapping[str, Any],
        *,
        owner_id: str,
        workspace_id: str,
        session_id: str,
    ) -> None:
        if (
            entry["owner_id"] != owner_id
            or entry["workspace_id"] != workspace_id
            or entry["session_id"] != session_id
        ):
            raise IntentPayloadError(
                "intent_payload_forbidden",
                "intent payload identity does not match the caller",
            )

    def _new_event(
        self,
        *,
        events: list[dict[str, Any]],
        kind: str,
        recorded_at: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        semantic = {
            "schema_version": _SCHEMA_VERSION,
            "kind": kind,
            "payload": payload,
        }
        semantic_digest = _digest(semantic)
        event: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "sequence": len(events) + 1,
            "event_id": "event:" + semantic_digest,
            "kind": kind,
            "recorded_at": recorded_at,
            "previous_record_sha256": (
                events[-1]["record_sha256"] if events else None
            ),
            "payload": payload,
        }
        event["record_sha256"] = _record_digest(event)
        self._validate_event(event, events[-1] if events else None)
        return event

    def _read_events(self, fd: int) -> list[dict[str, Any]]:
        raw = self._read_fd_bounded(fd, _MAX_JOURNAL_BYTES, "intent journal")
        return self._decode_events(raw)

    def _decode_events(self, raw: bytes) -> list[dict[str, Any]]:
        if not raw:
            return []
        if not raw.endswith(b"\n"):
            raise _corrupt("intent journal is not newline terminated")
        events: list[dict[str, Any]] = []
        offset = 0
        for line in raw.splitlines(keepends=True):
            offset += len(line)
            if len(line) > _MAX_EVENT_BYTES:
                raise _corrupt("intent event exceeds the supported size")
            event = self._decode_canonical_json(line, "intent event")
            if type(event) is not dict:
                raise _corrupt("intent event must be a JSON object")
            self._validate_event(event, events[-1] if events else None)
            if event["sequence"] != len(events) + 1:
                raise _corrupt("intent event sequence is not contiguous")
            events.append(event)
        if offset != len(raw):
            raise _corrupt("intent journal framing is invalid")
        return events

    def _validate_event(
        self, event: dict[str, Any], previous: Optional[dict[str, Any]]
    ) -> None:
        if set(event) != {
            "schema_version",
            "sequence",
            "event_id",
            "kind",
            "recorded_at",
            "previous_record_sha256",
            "payload",
            "record_sha256",
        }:
            raise _corrupt("intent event fields are invalid")
        if event["schema_version"] != _SCHEMA_VERSION:
            raise _corrupt("intent event schema_version is unsupported")
        if type(event["sequence"]) is not int or event["sequence"] < 1:
            raise _corrupt("intent event sequence is invalid")
        if type(event["event_id"]) is not str or _EVENT_ID_RE.fullmatch(
            event["event_id"]
        ) is None:
            raise _corrupt("intent event identifier is invalid")
        recorded_at = _canonical_timestamp(
            event["recorded_at"], "recorded_at", stored=True
        )
        if recorded_at != event["recorded_at"]:
            raise _corrupt("intent event timestamp is not canonical")
        if previous is not None and _parse_timestamp(recorded_at) < _parse_timestamp(
            previous["recorded_at"]
        ):
            raise _corrupt("intent event timestamps are not monotonic")
        expected_previous = previous["record_sha256"] if previous else None
        if event["previous_record_sha256"] != expected_previous:
            raise _corrupt("intent event hash chain is broken")
        kind = event["kind"]
        payload = event["payload"]
        if type(payload) is not dict:
            raise _corrupt("intent event payload must be a JSON object")
        if kind == "payload_stored":
            self._validate_stored_payload(payload)
        elif kind == "consumer_bound":
            if set(payload) != {"payload_digest", "payload_ref", "consumer_ref"}:
                raise _corrupt("consumer binding event fields are invalid")
            self._validate_digest_ref(payload)
            if type(payload["consumer_ref"]) is not str or not (
                _COMMAND_CONSUMER_RE.fullmatch(payload["consumer_ref"])
                or _RESEARCH_CONSUMER_RE.fullmatch(payload["consumer_ref"])
            ):
                raise _corrupt("consumer binding event value is invalid")
        elif kind == "payload_expired":
            if set(payload) != {"payload_digest", "payload_ref", "reason"}:
                raise _corrupt("payload expiry event fields are invalid")
            self._validate_digest_ref(payload)
            if payload["reason"] != "ttl_elapsed":
                raise _corrupt("payload expiry reason is invalid")
        elif kind == "expiry_acknowledged":
            if set(payload) != {
                "payload_digest",
                "payload_ref",
                "tombstone_event_ref",
                "tombstone_digest",
                "consumer_ref",
                "consumer_event_ref",
                "consumer_operation_digest",
            }:
                raise _corrupt("expiry acknowledgement event fields are invalid")
            self._validate_digest_ref(payload)
            if (
                type(payload["tombstone_event_ref"]) is not str
                or _EVENT_ID_RE.fullmatch(payload["tombstone_event_ref"])
                is None
                or type(payload["consumer_event_ref"]) is not str
                or _EVENT_ID_RE.fullmatch(payload["consumer_event_ref"])
                is None
                or type(payload["tombstone_digest"]) is not str
                or _DIGEST_RE.fullmatch(payload["tombstone_digest"]) is None
                or type(payload["consumer_operation_digest"]) is not str
                or _DIGEST_RE.fullmatch(
                    payload["consumer_operation_digest"]
                )
                is None
                or type(payload["consumer_ref"]) is not str
                or not (
                    _COMMAND_CONSUMER_RE.fullmatch(payload["consumer_ref"])
                    or _RESEARCH_CONSUMER_RE.fullmatch(payload["consumer_ref"])
                )
            ):
                raise _corrupt("expiry acknowledgement event value is invalid")
        else:
            raise _corrupt("intent event kind is unsupported")
        semantic_digest = _digest(
            {
                "schema_version": _SCHEMA_VERSION,
                "kind": kind,
                "payload": payload,
            }
        )
        if event["event_id"] != "event:" + semantic_digest:
            raise _corrupt("intent event identifier does not match its facts")
        if type(event["record_sha256"]) is not str or event[
            "record_sha256"
        ] != _record_digest(event):
            raise _corrupt("intent event record digest does not match")

    @staticmethod
    def _validate_digest_ref(payload: Mapping[str, Any]) -> None:
        digest = payload.get("payload_digest")
        if type(digest) is not str or _DIGEST_RE.fullmatch(digest) is None:
            raise _corrupt("payload digest is invalid")
        if payload.get("payload_ref") != "payload:sha256:" + digest:
            raise _corrupt("payload reference does not match its digest")

    def _validate_stored_payload(self, payload: dict[str, Any]) -> None:
        if set(payload) != {
            "payload_digest",
            "payload_ref",
            "client_identity_digest",
            "request_digest",
            "kind",
            "owner_id",
            "workspace_id",
            "session_id",
            "client_intent_id",
            "provider_policy_digest",
            "created_at",
            "expires_at",
            "ttl_days",
            "key_id",
            "blob_sha256",
        }:
            raise _corrupt("stored payload event fields are invalid")
        self._validate_digest_ref(payload)
        for field in (
            "client_identity_digest",
            "request_digest",
            "provider_policy_digest",
            "blob_sha256",
        ):
            if type(payload[field]) is not str or _DIGEST_RE.fullmatch(payload[field]) is None:
                raise _corrupt("stored payload digest field is invalid")
        if payload["kind"] not in _INTENT_KINDS:
            raise _corrupt("stored payload intent kind is invalid")
        for field in (
            "owner_id",
            "client_intent_id",
            "key_id",
        ):
            if type(payload[field]) is not str or _IDENTIFIER_RE.fullmatch(payload[field]) is None:
                raise _corrupt("stored payload identity field is invalid")
        if (
            type(payload["workspace_id"]) is not str
            or _WORKSPACE_RE.fullmatch(payload["workspace_id"]) is None
            or type(payload["session_id"]) is not str
            or _SESSION_RE.fullmatch(payload["session_id"]) is None
        ):
            raise _corrupt("stored payload scoped identity is invalid")
        created_at = _canonical_timestamp(payload["created_at"], "created_at", stored=True)
        expires_at = _canonical_timestamp(payload["expires_at"], "expires_at", stored=True)
        if created_at != payload["created_at"] or expires_at != payload["expires_at"]:
            raise _corrupt("stored payload timestamps are not canonical")
        ttl_days = payload["ttl_days"]
        if (
            type(ttl_days) is not int
            or not 1 <= ttl_days <= 30
            or _parse_timestamp(created_at) + timedelta(days=ttl_days)
            != _parse_timestamp(expires_at)
        ):
            raise _corrupt("stored payload TTL is invalid")
        if payload["client_identity_digest"] != _digest(
            {
                "owner_id": payload["owner_id"],
                "workspace_id": payload["workspace_id"],
                "session_id": payload["session_id"],
                "client_intent_id": payload["client_intent_id"],
            }
        ):
            raise _corrupt("stored payload client identity digest does not match")

    def _project(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        payloads: dict[str, dict[str, Any]] = {}
        clients: dict[str, str] = {}
        for event in events:
            payload = event["payload"]
            if event["kind"] == "payload_stored":
                digest = payload["payload_digest"]
                client_digest = payload["client_identity_digest"]
                if digest in payloads or client_digest in clients:
                    raise _corrupt("intent payload storage event is duplicated")
                payloads[digest] = {
                    **payload,
                    "status": "active",
                    "consumer_ref": None,
                    "stored_event_id": event["event_id"],
                    "bound_event_id": None,
                    "expired_event_id": None,
                    "expired_record_sha256": None,
                    "expired_at": None,
                    "expiry_acknowledged_event_id": None,
                    "expiry_consumer_event_ref": None,
                    "expiry_consumer_operation_digest": None,
                }
                clients[client_digest] = digest
            elif event["kind"] == "consumer_bound":
                digest = payload["payload_digest"]
                entry = payloads.get(digest)
                if entry is None or entry["status"] != "active":
                    raise _corrupt("consumer binding has no active payload")
                if entry["consumer_ref"] is not None:
                    raise _corrupt("intent payload has multiple consumer bindings")
                try:
                    _validate_consumer_for_kind(
                        payload["consumer_ref"], entry["kind"]
                    )
                except IntentPayloadError as exc:
                    raise _corrupt(
                        "consumer binding kind does not match the payload"
                    ) from exc
                entry["consumer_ref"] = payload["consumer_ref"]
                entry["bound_event_id"] = event["event_id"]
            elif event["kind"] == "payload_expired":
                digest = payload["payload_digest"]
                entry = payloads.get(digest)
                if entry is None or entry["status"] != "active":
                    raise _corrupt("payload expiry has no active payload")
                if _parse_timestamp(event["recorded_at"]) < _parse_timestamp(
                    entry["expires_at"]
                ):
                    raise _corrupt("payload expiry predates its immutable expiry")
                entry["status"] = "expired"
                entry["expired_event_id"] = event["event_id"]
                entry["expired_record_sha256"] = event["record_sha256"]
                entry["expired_at"] = event["recorded_at"]
            elif event["kind"] == "expiry_acknowledged":
                digest = payload["payload_digest"]
                entry = payloads.get(digest)
                if (
                    entry is None
                    or entry["status"] != "expired"
                    or entry["expiry_acknowledged_event_id"] is not None
                    or entry["expired_event_id"]
                    != payload["tombstone_event_ref"]
                    or entry["expired_record_sha256"]
                    != payload["tombstone_digest"]
                    or entry["consumer_ref"] != payload["consumer_ref"]
                ):
                    raise _corrupt(
                        "expiry acknowledgement has no exact pending tombstone"
                    )
                entry["expiry_acknowledged_event_id"] = event["event_id"]
                entry["expiry_consumer_event_ref"] = payload[
                    "consumer_event_ref"
                ]
                entry["expiry_consumer_operation_digest"] = payload[
                    "consumer_operation_digest"
                ]
        basis: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "event_count": len(events),
            "last_record_sha256": events[-1]["record_sha256"] if events else None,
            "payloads": payloads,
            "clients": clients,
        }
        basis["index_sha256"] = _digest(basis)
        return basis

    def _append_event(self, fd: int, event: dict[str, Any]) -> None:
        payload = _canonical_bytes(event)
        if len(payload) > _MAX_EVENT_BYTES:
            raise _invalid("intent event exceeds the maximum size")
        original_size = os.lseek(fd, 0, os.SEEK_END)
        if original_size + len(payload) > _MAX_JOURNAL_BYTES:
            raise IntentPayloadError(
                "intent_authority_capacity_exceeded",
                "intent journal reached its bounded capacity",
            )
        try:
            self._write_all_at_end(fd, payload)
        except OSError as write_error:
            try:
                os.ftruncate(fd, original_size)
                os.fsync(fd)
            except OSError as rollback_error:
                raise IntentPayloadError(
                    "intent_durability_unknown",
                    "intent event append outcome is unknown",
                    retryable=True,
                ) from rollback_error
            raise write_error
        try:
            os.fsync(fd)
        except OSError as exc:
            raise IntentPayloadError(
                "intent_durability_unknown",
                "intent event durability could not be confirmed",
                retryable=True,
            ) from exc

    @staticmethod
    def _write_all_at_end(fd: int, payload: bytes) -> None:
        os.lseek(fd, 0, os.SEEK_END)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("write made no progress")
            view = view[written:]

    @contextmanager
    def _locked(
        self, *, create: bool
    ) -> Iterator[Optional[tuple[int, int]]]:
        root_fd = self._open_root(create=create)
        if root_fd is None:
            yield None
            return
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        lock_exists = self._entry_exists(root_fd, ".payload.lock")
        if not lock_exists and not create:
            entries = set(os.listdir(root_fd))
            if not entries:
                os.close(root_fd)
                yield None
                return
            # Initialization may have published the stable lock after the
            # first stat.  Refresh once before treating remnants as corrupt.
            lock_exists = self._entry_exists(root_fd, ".payload.lock")
            if not lock_exists:
                os.close(root_fd)
                raise _corrupt("intent authority is partial or uninitialized")
        lock_flags = os.O_RDWR | no_follow
        created_lock = False
        try:
            if create and not lock_exists:
                try:
                    lock_fd = os.open(
                        ".payload.lock",
                        lock_flags | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=root_fd,
                    )
                    created_lock = True
                except FileExistsError:
                    lock_fd = os.open(
                        ".payload.lock", lock_flags, 0o600, dir_fd=root_fd
                    )
            else:
                lock_fd = os.open(
                    ".payload.lock", lock_flags, 0o600, dir_fd=root_fd
                )
        except OSError as exc:
            os.close(root_fd)
            if exc.errno == errno.ELOOP:
                raise _insecure("intent lock must not be a symbolic link") from exc
            raise
        event_fd: Optional[int] = None
        acquired = False
        try:
            self._assert_secure_file(lock_fd, "intent lock", 0o600)
            self._assert_path_identity(root_fd, ".payload.lock", lock_fd, "intent lock")
            deadline = time.monotonic() + self._lock_timeout_seconds
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise IntentPayloadError(
                            "intent_authority_busy",
                            "intent authority lock timed out",
                            retryable=True,
                        ) from exc
                    time.sleep(0.01)
            self._assert_path_identity(root_fd, ".payload.lock", lock_fd, "intent lock")
            self._clean_index_temps(root_fd)
            event_exists = self._entry_exists(root_fd, "events.v2.jsonl")
            if created_lock and event_exists:
                lock_created_ns = os.fstat(lock_fd).st_ctime_ns
                journal_created_ns = os.stat(
                    "events.v2.jsonl",
                    dir_fd=root_fd,
                    follow_symlinks=False,
                ).st_ctime_ns
                # Another contender may acquire the just-published stable
                # lock first and legitimately create the journal.  Only a
                # journal observably older than this lock is an orphaned
                # pre-lock authority; equal timestamps remain subject to the
                # full closed-schema and path-identity checks below.
                if journal_created_ns < lock_created_ns:
                    raise _corrupt(
                        "intent journal predates its newly created stable lock"
                    )
            if not event_exists and not create:
                allowed = {".payload.lock"}
                if set(os.listdir(root_fd)) != allowed:
                    raise _corrupt("intent authority is missing its journal")
                yield None
                return
            event_flags = os.O_RDWR | os.O_APPEND | no_follow
            if create:
                event_flags |= os.O_CREAT
            try:
                event_fd = os.open(
                    "events.v2.jsonl", event_flags, 0o600, dir_fd=root_fd
                )
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise _insecure("intent journal must not be a symbolic link") from exc
                raise
            self._assert_secure_file(event_fd, "intent journal", 0o600)
            self._assert_path_identity(
                root_fd, "events.v2.jsonl", event_fd, "intent journal"
            )
            self._validate_root_inventory(root_fd)
            os.fsync(root_fd)
            yield root_fd, event_fd
        finally:
            if event_fd is not None:
                os.close(event_fd)
            if acquired:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(lock_fd)
            os.close(root_fd)

    def _open_root(self, *, create: bool) -> Optional[int]:
        absolute = self.root
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        current_fd = os.open(absolute.anchor or os.sep, flags)
        try:
            components = absolute.parts[1:]
            for index, component in enumerate(components):
                is_final = index == len(components) - 1
                if create:
                    try:
                        os.mkdir(component, 0o700 if is_final else 0o755, dir_fd=current_fd)
                        os.fsync(current_fd)
                    except FileExistsError:
                        pass
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except FileNotFoundError:
                    if not create:
                        os.close(current_fd)
                        return None
                    raise
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise _insecure(
                            "intent authority path chain must not contain symbolic links"
                        ) from exc
                    raise
                os.close(current_fd)
                current_fd = next_fd
                chain_metadata = os.fstat(current_fd)
                if (
                    chain_metadata.st_uid not in {0, os.geteuid()}
                    or chain_metadata.st_mode & 0o022
                ):
                    raise _insecure(
                        "intent authority path chain must not be group or world writable"
                    )
                if is_final:
                    metadata = chain_metadata
                    if (
                        not stat.S_ISDIR(metadata.st_mode)
                        or stat.S_IMODE(metadata.st_mode) != 0o700
                        or metadata.st_uid != os.geteuid()
                    ):
                        raise _insecure("intent root must be an owner-only directory")
            return current_fd
        except Exception:
            try:
                os.close(current_fd)
            except OSError:
                pass
            raise

    def _validate_root_inventory(self, root_fd: int) -> None:
        allowed = {
            ".payload.lock",
            "events.v2.jsonl",
            "index.v2.json",
            "blobs",
        }
        extras = set(os.listdir(root_fd)) - allowed
        if extras:
            raise _corrupt("intent authority contains unknown root entries")

    def _clean_index_temps(self, root_fd: int) -> None:
        for name in os.listdir(root_fd):
            if not (
                name.startswith(".index.v2.json.") and name.endswith(".tmp")
            ):
                continue
            fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
            try:
                self._assert_secure_file(fd, "intent index temporary", 0o600)
                self._assert_path_identity(root_fd, name, fd, "intent index temporary")
            finally:
                os.close(fd)
            os.unlink(name, dir_fd=root_fd)
            os.fsync(root_fd)

    @staticmethod
    def _entry_exists(parent_fd: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _assert_secure_file(fd: int, label: str, mode: int) -> None:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
        ):
            raise _insecure(
                "{} must be an owner-only non-hardlinked regular file".format(label)
            )

    @staticmethod
    def _assert_path_identity(
        parent_fd: int, name: str, fd: int, label: str
    ) -> None:
        opened = os.fstat(fd)
        try:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise _corrupt("{} path disappeared after open".format(label)) from exc
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise _corrupt("{} path identity changed after open".format(label))

    def _blobs_dir_fd(self, root_fd: int, *, create: bool) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        if create:
            try:
                os.mkdir("blobs", 0o700, dir_fd=root_fd)
                os.fsync(root_fd)
            except FileExistsError:
                pass
        try:
            fd = os.open("blobs", flags, dir_fd=root_fd)
        except FileNotFoundError:
            raise _corrupt("intent blob directory is missing")
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise _insecure("intent blob directory must not be a symbolic link") from exc
            raise
        metadata = os.fstat(fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            os.close(fd)
            raise _insecure("intent blob directory must be owner-only")
        return fd

    @staticmethod
    def _read_fd_bounded(fd: int, maximum: int, label: str) -> bytes:
        metadata = os.fstat(fd)
        if metadata.st_size > maximum:
            raise _corrupt("{} exceeds the supported size".format(label))
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(65_536, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise _corrupt("{} exceeds the supported size".format(label))
        return b"".join(chunks)

    def _decode_canonical_json(self, raw: bytes, label: str) -> Any:
        if not raw.endswith(b"\n"):
            raise _corrupt("{} is not canonical JSON".format(label))
        try:
            value = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_without_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except IntentPayloadError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
            raise _corrupt("{} is invalid JSON".format(label)) from exc
        _validate_json_tree(value, stored=True)
        try:
            canonical = _canonical_bytes(value)
        except IntentPayloadError as exc:
            raise _corrupt("{} is invalid JSON".format(label)) from exc
        if raw != canonical:
            raise _corrupt("{} is not canonical JSON".format(label))
        return value

    def _recover_storage(self, root_fd: int, projection: dict[str, Any]) -> None:
        if not self._entry_exists(root_fd, "blobs"):
            if any(
                entry["status"] == "active"
                for entry in projection["payloads"].values()
            ):
                raise _corrupt("intent blob directory is missing")
            return
        blobs_fd = self._blobs_dir_fd(root_fd, create=False)
        try:
            grouped: dict[str, list[str]] = {}
            for name in sorted(os.listdir(blobs_fd)):
                match = re.fullmatch(
                    r"\.blob\.([0-9a-f]{64})\.([0-9a-f]{24})\.tmp", name
                )
                if match is not None:
                    grouped.setdefault(match.group(1), []).append(name)
            for digest, names in grouped.items():
                final_name = digest + ".blob"
                try:
                    final = os.stat(
                        final_name, dir_fd=blobs_fd, follow_symlinks=False
                    )
                except FileNotFoundError:
                    final = None
                if final is not None and (
                    not stat.S_ISREG(final.st_mode)
                    or stat.S_IMODE(final.st_mode) != 0o400
                    or final.st_uid != os.geteuid()
                ):
                    raise _insecure("intent blob final file is insecure")
                metadata: dict[str, os.stat_result] = {}
                linked: list[str] = []
                for name in names:
                    item = os.stat(name, dir_fd=blobs_fd, follow_symlinks=False)
                    if (
                        not stat.S_ISREG(item.st_mode)
                        or stat.S_IMODE(item.st_mode) != 0o400
                        or item.st_uid != os.geteuid()
                    ):
                        raise _insecure("intent blob temporary is insecure")
                    metadata[name] = item
                    if final is not None and (item.st_dev, item.st_ino) == (
                        final.st_dev,
                        final.st_ino,
                    ):
                        linked.append(name)
                if final is not None and final.st_nlink != 1 + len(linked):
                    raise _insecure("intent blob has an unaccounted hard link")
                for name, item in metadata.items():
                    if name not in linked and item.st_nlink != 1:
                        raise _insecure(
                            "intent blob temporary has an unaccounted hard link"
                        )
                    os.unlink(name, dir_fd=blobs_fd)
                if names:
                    os.fsync(blobs_fd)
            referenced = set(projection["payloads"])
            for name in sorted(os.listdir(blobs_fd)):
                match = re.fullmatch(r"([0-9a-f]{64})\.blob", name)
                if match is None or match.group(1) in referenced:
                    continue
                digest = match.group(1)
                raw = self._read_blob_from_fd(blobs_fd, name)
                orphan = self._decode_canonical_json(raw, "orphan intent blob")
                if (
                    type(orphan) is not dict
                    or set(orphan)
                    != {
                        "schema_version",
                        "payload_digest",
                        "aad_sha256",
                        "encryption",
                    }
                    or orphan["schema_version"] != _SCHEMA_VERSION
                    or orphan["payload_digest"] != digest
                    or type(orphan["aad_sha256"]) is not str
                    or _DIGEST_RE.fullmatch(orphan["aad_sha256"]) is None
                    or type(orphan["encryption"]) is not dict
                    or orphan["encryption"].get("key_id") != self.crypto.key_id
                    or orphan["encryption"].get("algorithm")
                    != self.crypto.algorithm
                ):
                    raise _corrupt("orphan intent blob is not recoverable")
                os.unlink(name, dir_fd=blobs_fd)
                os.fsync(blobs_fd)
        finally:
            os.close(blobs_fd)
        self._recover_tombstoned_blobs(root_fd, projection)

    def _recover_tombstoned_blobs(
        self, root_fd: int, projection: dict[str, Any]
    ) -> None:
        if not self._entry_exists(root_fd, "blobs"):
            return
        for digest, entry in projection["payloads"].items():
            if entry["status"] == "expired":
                self._unlink_blob_if_present(root_fd, digest)

    def _audit_inventory(self, root_fd: int, projection: dict[str, Any]) -> None:
        expected = {
            digest + ".blob"
            for digest, entry in projection["payloads"].items()
            if entry["status"] == "active"
        }
        if not self._entry_exists(root_fd, "blobs"):
            if expected:
                raise _corrupt("intent blob directory is missing")
            return
        blobs_fd = self._blobs_dir_fd(root_fd, create=False)
        try:
            actual = set(os.listdir(blobs_fd))
            if actual != expected:
                raise _corrupt("intent blob inventory does not match the event authority")
            for name in actual:
                fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=blobs_fd,
                )
                try:
                    self._assert_secure_file(fd, "intent blob", 0o400)
                    self._assert_path_identity(blobs_fd, name, fd, "intent blob")
                finally:
                    os.close(fd)
        finally:
            os.close(blobs_fd)

    def _write_or_verify_blob(
        self, root_fd: int, digest: str, blob_bytes: bytes
    ) -> None:
        blobs_fd = self._blobs_dir_fd(root_fd, create=True)
        name = digest + ".blob"
        try:
            if self._entry_exists(blobs_fd, name):
                existing = self._read_blob_from_fd(blobs_fd, name)
                if existing != blob_bytes:
                    raise _corrupt("intent payload content-address collision")
                return
            temporary = ".blob.{}.{}.tmp".format(digest, secrets.token_hex(12))
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
            )
            fd = os.open(temporary, flags, 0o400, dir_fd=blobs_fd)
            try:
                os.fchmod(fd, 0o400)
                view = memoryview(blob_bytes)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("blob write made no progress")
                    view = view[written:]
                os.fsync(fd)
                self._assert_secure_file(fd, "intent blob temporary", 0o400)
                self._assert_path_identity(
                    blobs_fd, temporary, fd, "intent blob temporary"
                )
            except Exception:
                try:
                    os.unlink(temporary, dir_fd=blobs_fd)
                    os.fsync(blobs_fd)
                except OSError:
                    pass
                raise
            finally:
                os.close(fd)
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=blobs_fd,
                    dst_dir_fd=blobs_fd,
                    follow_symlinks=False,
                )
                os.fsync(blobs_fd)
            except FileExistsError:
                existing = self._read_blob_from_fd(blobs_fd, name)
                if existing != blob_bytes:
                    raise _corrupt("intent payload content-address collision")
            finally:
                try:
                    os.unlink(temporary, dir_fd=blobs_fd)
                    os.fsync(blobs_fd)
                except FileNotFoundError:
                    pass
            existing = self._read_blob_from_fd(blobs_fd, name)
            if existing != blob_bytes:
                raise _corrupt("intent payload publication did not converge")
        finally:
            os.close(blobs_fd)

    def _read_blob(self, root_fd: int, digest: str) -> bytes:
        blobs_fd = self._blobs_dir_fd(root_fd, create=False)
        try:
            return self._read_blob_from_fd(blobs_fd, digest + ".blob")
        finally:
            os.close(blobs_fd)

    def _read_blob_from_fd(self, blobs_fd: int, name: str) -> bytes:
        try:
            fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=blobs_fd,
            )
        except FileNotFoundError as exc:
            raise _corrupt("intent ciphertext blob is missing") from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _insecure("intent blob must not be a symbolic link") from exc
            raise
        try:
            self._assert_secure_file(fd, "intent blob", 0o400)
            self._assert_path_identity(blobs_fd, name, fd, "intent blob")
            raw = self._read_fd_bounded(fd, _MAX_BLOB_BYTES, "intent blob")
            self._assert_path_identity(blobs_fd, name, fd, "intent blob")
            return raw
        finally:
            os.close(fd)

    def _unlink_blob_if_present(self, root_fd: int, digest: str) -> bool:
        if not self._entry_exists(root_fd, "blobs"):
            return False
        blobs_fd = self._blobs_dir_fd(root_fd, create=False)
        name = digest + ".blob"
        try:
            if not self._entry_exists(blobs_fd, name):
                return False
            self._read_blob_from_fd(blobs_fd, name)
            os.unlink(name, dir_fd=blobs_fd)
            os.fsync(blobs_fd)
            return True
        finally:
            os.close(blobs_fd)

    def _verify_blob(self, root_fd: int, entry: Mapping[str, Any]) -> dict[str, Any]:
        return self._verify_blob_bytes(
            self._read_blob(root_fd, entry["payload_digest"]), entry
        )

    def _verify_blob_bytes(
        self, raw: bytes, entry: Mapping[str, Any]
    ) -> dict[str, Any]:
        blob, aad = self._verify_blob_container(raw, entry)
        try:
            plaintext = self.crypto.decrypt(blob["encryption"], aad=aad)
        except CryptoFailure as exc:
            raise self._mapped_crypto_failure(exc, decrypting=True) from None
        if len(plaintext) > _MAX_ENVELOPE_BYTES:
            raise _corrupt("intent plaintext envelope exceeds the supported size")
        if _digest_bytes(plaintext) != entry["payload_digest"]:
            raise _corrupt("intent plaintext digest does not match its reference")
        envelope = self._decode_canonical_json(plaintext, "intent plaintext envelope")
        request_fields = (
            _REQUEST_FIELDS | _RESEARCH_CLAIM_FIELD
            if type(envelope) is dict and "research_claim" in envelope
            else _REQUEST_FIELDS
        )
        if (
            type(envelope) is not dict
            or set(envelope) != request_fields | _ENVELOPE_METADATA_FIELDS
        ):
            raise _corrupt("intent plaintext envelope fields are invalid")
        try:
            normalized = _normalize_request(
                {field: envelope[field] for field in request_fields}
            )
        except IntentPayloadError as exc:
            raise _corrupt("intent plaintext envelope values are invalid") from exc
        created_at = _canonical_timestamp(
            envelope["created_at"], "created_at", stored=True
        )
        expires_at = _canonical_timestamp(
            envelope["expires_at"], "expires_at", stored=True
        )
        if (
            created_at != entry["created_at"]
            or expires_at != entry["expires_at"]
            or envelope["provider_policy_digest"]
            != _digest(normalized["provider_policy"])
            or envelope["provider_policy_digest"]
            != entry["provider_policy_digest"]
            or _digest(normalized) != entry["request_digest"]
            or _digest(_client_identity(normalized))
            != entry["client_identity_digest"]
        ):
            raise _corrupt("intent plaintext envelope does not match its event metadata")
        return envelope

    def _verify_blob_container(
        self, raw: bytes, entry: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bytes]:
        if _digest_bytes(raw) != entry["blob_sha256"]:
            raise _corrupt("intent blob digest does not match its event")
        blob = self._decode_canonical_json(raw, "intent blob")
        if type(blob) is not dict or set(blob) != {
            "schema_version",
            "payload_digest",
            "aad_sha256",
            "encryption",
        }:
            raise _corrupt("intent blob fields are invalid")
        if (
            blob["schema_version"] != _SCHEMA_VERSION
            or blob["payload_digest"] != entry["payload_digest"]
        ):
            raise _corrupt("intent blob identity does not match")
        if type(blob["encryption"]) is not dict or set(blob["encryption"]) != {
            "algorithm",
            "key_id",
            "nonce_b64",
            "ciphertext_b64",
            "tag_b64",
        }:
            raise _corrupt("intent encryption envelope is invalid")
        if (
            blob["encryption"].get("key_id") != entry["key_id"]
            or blob["encryption"].get("algorithm") != self.crypto.algorithm
            or any(type(value) is not str for value in blob["encryption"].values())
            or any(len(value) > 1_400_000 for value in blob["encryption"].values())
        ):
            raise _corrupt("intent encryption key identifier does not match")
        try:
            nonce = base64.b64decode(
                blob["encryption"]["nonce_b64"].encode("ascii"), validate=True
            )
            ciphertext = base64.b64decode(
                blob["encryption"]["ciphertext_b64"].encode("ascii"),
                validate=True,
            )
            tag = base64.b64decode(
                blob["encryption"]["tag_b64"].encode("ascii"), validate=True
            )
        except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
            raise _corrupt("intent encryption encoding is invalid") from exc
        expected_tag_size = (
            16 if self.crypto.algorithm == "AES-256-GCM" else 32
        )
        if (
            len(nonce) != 12
            or len(tag) != expected_tag_size
            or len(ciphertext) > _MAX_ENVELOPE_BYTES
        ):
            raise _corrupt("intent encryption encoding is invalid")
        aad = _canonical_bytes(_aad_document(entry))
        if blob["aad_sha256"] != _digest_bytes(aad):
            raise _corrupt("intent blob AAD digest does not match")
        return blob, aad

    @staticmethod
    def _mapped_crypto_failure(
        failure: CryptoFailure, *, decrypting: bool
    ) -> IntentPayloadError:
        unavailable = {
            "keychain_unavailable",
            "crypto_helper_unavailable",
            "crypto_helper_timeout",
            "crypto_helper_failed",
        }
        integrity = {
            "key_not_found",
            "key_corrupt",
            "crypto_key_mismatch",
            "crypto_algorithm_mismatch",
            "crypto_invalid_envelope",
            "crypto_authentication_failed",
            "crypto_failed",
            "crypto_helper_protocol_error",
        }
        if failure.code in unavailable:
            return IntentPayloadError(
                "intent_crypto_unavailable",
                "intent crypto authority is temporarily unavailable",
                retryable=True,
            )
        if decrypting and failure.code in integrity:
            return IntentPayloadError(
                "intent_payload_corrupt",
                "intent ciphertext could not be authenticated",
            )
        return IntentPayloadError(
            "intent_crypto_error", "intent crypto operation failed"
        )

    def _read_index(self, root_fd: int) -> dict[str, Any]:
        try:
            fd = os.open(
                "index.v2.json",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
        except FileNotFoundError as exc:
            raise _corrupt("intent index is missing") from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _insecure("intent index must not be a symbolic link") from exc
            raise
        try:
            self._assert_secure_file(fd, "intent index", 0o600)
            self._assert_path_identity(root_fd, "index.v2.json", fd, "intent index")
            raw = self._read_fd_bounded(fd, _MAX_INDEX_BYTES, "intent index")
            value = self._decode_canonical_json(raw, "intent index")
            if type(value) is not dict:
                raise _corrupt("intent index must be a JSON object")
            if set(value) != {
                "schema_version",
                "event_count",
                "last_record_sha256",
                "payloads",
                "clients",
                "index_sha256",
            }:
                raise _corrupt("intent index fields are invalid")
            if value["index_sha256"] != _digest(
                {key: item for key, item in value.items() if key != "index_sha256"}
            ):
                raise _corrupt("intent index digest does not match")
            return value
        finally:
            os.close(fd)

    def _publish_index(self, root_fd: int, projection: dict[str, Any]) -> None:
        payload = _canonical_bytes(projection)
        if len(payload) > _MAX_INDEX_BYTES:
            raise _corrupt("intent index exceeds the supported size")
        if self._entry_exists(root_fd, "index.v2.json"):
            existing_fd = os.open(
                "index.v2.json",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
            try:
                self._assert_secure_file(existing_fd, "intent index", 0o600)
                self._assert_path_identity(
                    root_fd, "index.v2.json", existing_fd, "intent index"
                )
            finally:
                os.close(existing_fd)
        temporary = ".index.v2.json.{}.tmp".format(secrets.token_hex(12))
        fd = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=root_fd,
        )
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("index write made no progress")
                view = view[written:]
            os.fsync(fd)
            self._assert_secure_file(fd, "intent index temporary", 0o600)
            self._assert_path_identity(
                root_fd, temporary, fd, "intent index temporary"
            )
        except Exception:
            try:
                os.unlink(temporary, dir_fd=root_fd)
            except OSError:
                pass
            raise
        finally:
            os.close(fd)
        try:
            os.replace(
                temporary,
                "index.v2.json",
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
            os.fsync(root_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=root_fd)
            except FileNotFoundError:
                pass

    def _reject_overlapping_path(self, other: Path) -> None:
        root = str(self.root)
        candidate = str(other)
        try:
            common = os.path.commonpath([root, candidate])
        except ValueError as exc:
            raise _invalid("backup path is invalid") from exc
        if common in {root, candidate}:
            raise _invalid("backup and authority paths must not overlap")

    def _write_backup(
        self,
        destination: Path,
        event_bytes: bytes,
        blob_bytes: dict[str, bytes],
        manifest: dict[str, Any],
    ) -> None:
        parent = destination.parent
        self._assert_directory_chain(parent)
        parent_meta = os.stat(parent, follow_symlinks=False)
        if parent_meta.st_uid != os.geteuid():
            raise _insecure("backup parent must be owned by the current user")
        try:
            os.mkdir(destination, 0o700)
        except FileExistsError as exc:
            raise IntentPayloadError(
                "intent_backup_exists", "intent backup destination already exists"
            ) from exc
        destination.chmod(0o700)
        destination_meta = os.lstat(destination)
        if (
            not stat.S_ISDIR(destination_meta.st_mode)
            or stat.S_IMODE(destination_meta.st_mode) != 0o700
            or destination_meta.st_uid != os.geteuid()
        ):
            raise _insecure("backup destination must be owner-only")
        blobs_path = destination / "blobs"
        blobs_path.mkdir(mode=0o700)
        self._write_private_path(destination / "events.v2.jsonl", event_bytes, 0o600)
        for digest, raw in sorted(blob_bytes.items()):
            self._write_private_path(blobs_path / (digest + ".blob"), raw, 0o400)
        self._write_private_path(
            destination / "manifest.v2.json", _canonical_bytes(manifest), 0o600
        )
        self._fsync_directory(blobs_path)
        self._fsync_directory(destination)
        self._fsync_directory(parent)

    @staticmethod
    def _write_private_path(path: Path, payload: bytes, mode: int) -> None:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = os.open(path, flags, mode)
        try:
            os.fchmod(fd, mode)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("backup write made no progress")
                view = view[written:]
            os.fsync(fd)
            IntentPayloadStore._assert_secure_file(fd, "intent backup file", mode)
        finally:
            os.close(fd)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        fd = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _read_backup(
        self, source: Path
    ) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
        self._assert_directory_chain(source)
        source_meta = os.lstat(source)
        if (
            not stat.S_ISDIR(source_meta.st_mode)
            or stat.S_IMODE(source_meta.st_mode) != 0o700
            or source_meta.st_uid != os.geteuid()
        ):
            raise _insecure("intent backup root must be owner-only")
        entries = {path.name for path in source.iterdir()}
        if entries != {"manifest.v2.json", "events.v2.jsonl", "blobs"}:
            raise _corrupt("intent backup root entries are invalid")
        blobs_path = source / "blobs"
        blobs_meta = os.lstat(blobs_path)
        if (
            not stat.S_ISDIR(blobs_meta.st_mode)
            or stat.S_IMODE(blobs_meta.st_mode) != 0o700
            or blobs_meta.st_uid != os.geteuid()
        ):
            raise _insecure("intent backup blob directory must be owner-only")
        manifest_raw = self._read_private_path(
            source / "manifest.v2.json", 0o600, _MAX_BACKUP_MANIFEST_BYTES
        )
        event_bytes = self._read_private_path(
            source / "events.v2.jsonl", 0o600, _MAX_JOURNAL_BYTES
        )
        manifest = self._decode_canonical_json(manifest_raw, "intent backup manifest")
        if type(manifest) is not dict or set(manifest) != {
            "schema_version",
            "kind",
            "created_at",
            "key_ids",
            "events_sha256",
            "event_count",
            "last_record_sha256",
            "blobs",
            "manifest_sha256",
        }:
            raise _corrupt("intent backup manifest fields are invalid")
        if (
            manifest["schema_version"] != _SCHEMA_VERSION
            or manifest["kind"] != "intent_payload_backup"
            or manifest["created_at"]
            != _canonical_timestamp(
                manifest["created_at"], "created_at", stored=True
            )
            or type(manifest["event_count"]) is not int
            or manifest["event_count"] < 0
            or type(manifest["key_ids"]) is not list
            or any(
                type(key_id) is not str or _IDENTIFIER_RE.fullmatch(key_id) is None
                for key_id in manifest["key_ids"]
            )
            or manifest["key_ids"] != sorted(set(manifest["key_ids"]))
            or type(manifest["blobs"]) is not dict
        ):
            raise _corrupt("intent backup manifest values are invalid")
        if manifest["events_sha256"] != _digest_bytes(event_bytes):
            raise _corrupt("intent backup journal digest does not match")
        if manifest["manifest_sha256"] != _digest(
            {
                key: value
                for key, value in manifest.items()
                if key != "manifest_sha256"
            }
        ):
            raise _corrupt("intent backup manifest digest does not match")
        expected_blob_names = set()
        blob_bytes: dict[str, bytes] = {}
        if len(manifest["blobs"]) > _MAX_PAYLOAD_COUNT:
            raise _corrupt("intent backup exceeds the payload count limit")
        aggregate_ciphertext_bytes = 0
        for digest, expected_digest in manifest["blobs"].items():
            if (
                type(digest) is not str
                or _DIGEST_RE.fullmatch(digest) is None
                or type(expected_digest) is not str
                or _DIGEST_RE.fullmatch(expected_digest) is None
            ):
                raise _corrupt("intent backup blob manifest is invalid")
            expected_blob_names.add(digest + ".blob")
            raw = self._read_private_path(
                blobs_path / (digest + ".blob"), 0o400, _MAX_BLOB_BYTES
            )
            aggregate_ciphertext_bytes += len(raw)
            if aggregate_ciphertext_bytes > _MAX_AGGREGATE_CIPHERTEXT_BYTES:
                raise _corrupt(
                    "intent backup exceeds the aggregate ciphertext limit"
                )
            if _digest_bytes(raw) != expected_digest:
                raise _corrupt("intent backup blob digest does not match")
            blob_bytes[digest] = raw
        if {path.name for path in blobs_path.iterdir()} != expected_blob_names:
            raise _corrupt("intent backup blob inventory is invalid")
        return manifest, event_bytes, blob_bytes

    @staticmethod
    def _assert_directory_chain(path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        current = os.open(absolute.anchor or os.sep, flags)
        try:
            for component in absolute.parts[1:]:
                try:
                    next_fd = os.open(component, flags, dir_fd=current)
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise _insecure(
                            "backup path chain must not contain symbolic links"
                        ) from exc
                    raise
                os.close(current)
                current = next_fd
                metadata = os.fstat(current)
                if (
                    metadata.st_uid not in {0, os.geteuid()}
                    or metadata.st_mode & 0o022
                ):
                    raise _insecure(
                        "backup path chain must not be group or world writable"
                    )
        finally:
            os.close(current)

    @staticmethod
    def _read_private_path(path: Path, mode: int, maximum: int) -> bytes:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _insecure("intent backup file must not be a symbolic link") from exc
            raise
        try:
            IntentPayloadStore._assert_secure_file(fd, "intent backup file", mode)
            opened = os.fstat(fd)
            current = os.stat(path, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise _corrupt("intent backup file identity changed after open")
            return IntentPayloadStore._read_fd_bounded(
                fd, maximum, "intent backup file"
            )
        finally:
            os.close(fd)
