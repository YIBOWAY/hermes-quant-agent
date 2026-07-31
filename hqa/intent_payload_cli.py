"""Trusted local Intent Payload Store CLI Port.

Closed-schema JSON on stdin/stdout. Prompt plaintext never appears on argv,
the environment, or log lines. ``bind_resolve`` is for parent-process pipes
only (BFF never calls it; the supervised worker does). Key ``probe`` is
non-creating; only the explicit operator ``initialize-key`` command may create
the Keychain key.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Mapping, Optional, Sequence

from hqa import config
from hqa.intent_payload_crypto import (
    CryptoFailure,
    IntentPayloadCrypto,
    MacOSKeychainCrypto,
)
from hqa.intent_payloads import IntentPayloadError, IntentPayloadStore


_STDIN_LIMIT = 600_000
_COMMANDS = frozenset({"put", "bind_resolve", "probe", "initialize-key"})

_RETRYABLE_CRYPTO_FAILURES = frozenset(
    {
        "keychain_unavailable",
        "crypto_helper_unavailable",
        "crypto_helper_timeout",
        "crypto_helper_failed",
    }
)

_RETRYABLE_INTENT_FAILURES = frozenset(
    {
        "intent_storage_io_error",
        "intent_crypto_unavailable",
        "intent_lock_timeout",
    }
)


class _CliArgumentError(ValueError):
    pass


class _InputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _InputError("intent_invalid_json", "duplicate JSON field")
        document[key] = value
    return document


def _reject_constant(_value: str) -> None:
    raise _InputError("intent_invalid_json", "non-finite JSON number")


def _read_stdin_object() -> dict[str, Any]:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(_STDIN_LIMIT + 1)
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _InputError("intent_invalid_json", "invalid JSON stdin") from exc
    if not raw or len(raw) > _STDIN_LIMIT:
        raise _InputError("intent_invalid_json", "empty or oversized JSON stdin")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except _InputError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise _InputError("intent_invalid_json", "invalid JSON stdin") from exc
    if not isinstance(document, dict):
        raise _InputError("intent_invalid_json", "JSON stdin must be an object")
    return document


def _emit(document: Mapping[str, Any]) -> None:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload.encode("utf-8", errors="strict")
    sys.stdout.write(payload + "\n")


def _emit_error(code: str, message: str, *, retryable: bool) -> None:
    _emit(
        {
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
            }
        }
    )


def _store() -> IntentPayloadStore:
    return IntentPayloadStore(
        config.INTENT_PAYLOAD_DIR,
        crypto=MacOSKeychainCrypto(config.INTENT_PAYLOAD_CRYPTO_HELPER),
    )


def _crypto() -> IntentPayloadCrypto:
    return MacOSKeychainCrypto(config.INTENT_PAYLOAD_CRYPTO_HELPER)


def _require_string(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if type(value) is not str or not value:
        raise _InputError("intent_invalid_request", f"{key} must be a nonempty string")
    return value


def _put(store: IntentPayloadStore, request: dict[str, Any]) -> dict[str, Any]:
    receipt = store.put(request)
    # Metadata only — never echo prompt.
    return {
        "ok": True,
        "schema_version": receipt["schema_version"],
        "payload_ref": receipt["payload_ref"],
        "payload_digest": receipt["payload_digest"],
        "kind": receipt["kind"],
        "owner_id": receipt["owner_id"],
        "workspace_id": receipt["workspace_id"],
        "session_id": receipt["session_id"],
        "client_intent_id": receipt["client_intent_id"],
        "provider_policy_digest": receipt["provider_policy_digest"],
        "created_at": receipt["created_at"],
        "expires_at": receipt["expires_at"],
        "ttl_days": receipt["ttl_days"],
        "status": receipt["status"],
    }


def _bind_resolve(store: IntentPayloadStore, request: dict[str, Any]) -> dict[str, Any]:
    payload_ref = _require_string(request, "payload_ref")
    owner_id = _require_string(request, "owner_id")
    workspace_id = _require_string(request, "workspace_id")
    session_id = _require_string(request, "session_id")
    consumer_ref = _require_string(request, "consumer_ref")
    if set(request) - {
        "payload_ref",
        "owner_id",
        "workspace_id",
        "session_id",
        "consumer_ref",
    }:
        raise _InputError(
            "intent_invalid_request",
            "bind_resolve rejects unknown fields",
        )
    store.bind_consumer(
        payload_ref=payload_ref,
        consumer_ref=consumer_ref,
        owner_id=owner_id,
        workspace_id=workspace_id,
        session_id=session_id,
    )
    envelope = store.resolve(
        payload_ref,
        owner_id=owner_id,
        workspace_id=workspace_id,
        session_id=session_id,
        consumer_ref=consumer_ref,
    )
    prompt = envelope.get("prompt")
    if type(prompt) is not str or not prompt:
        raise IntentPayloadError(
            "intent_payload_corrupt",
            "resolved intent envelope is missing prompt",
        )
    return {
        "ok": True,
        "payload_ref": payload_ref,
        "payload_digest": envelope.get("payload_digest")
        if type(envelope.get("payload_digest")) is str
        else None,
        "prompt": prompt,
        "consumer_ref": consumer_ref,
    }


def _key_command(
    crypto_factory: Callable[[], IntentPayloadCrypto],
    request: dict[str, Any],
    *,
    initialize: bool,
) -> dict[str, Any]:
    if request:
        raise _InputError(
            "intent_invalid_request",
            "key command requires an empty JSON object",
        )
    crypto = crypto_factory()
    if initialize:
        crypto.initialize()
    else:
        crypto.probe()
    return {"ok": True, "status": "ready"}


def _parse_command(argv: Sequence[str]) -> str:
    if len(argv) != 1 or argv[0] not in _COMMANDS:
        raise _CliArgumentError(
            "expected single command: put | bind_resolve | probe | initialize-key"
        )
    return argv[0]


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    store_factory: Optional[Callable[[], IntentPayloadStore]] = None,
    crypto_factory: Optional[Callable[[], IntentPayloadCrypto]] = None,
) -> int:
    try:
        command = _parse_command(list(sys.argv[1:] if argv is None else argv))
    except _CliArgumentError:
        _emit_error(
            "intent_invalid_arguments",
            "expected single command: put | bind_resolve | probe | initialize-key",
            retryable=False,
        )
        return 2

    try:
        request = _read_stdin_object()
        if command == "probe":
            document = _key_command(
                crypto_factory or _crypto,
                request,
                initialize=False,
            )
        elif command == "initialize-key":
            document = _key_command(
                crypto_factory or _crypto,
                request,
                initialize=True,
            )
        elif command == "put":
            store = (store_factory or _store)()
            document = _put(store, request)
        else:
            store = (store_factory or _store)()
            document = _bind_resolve(store, request)
    except _InputError as exc:
        _emit_error(exc.code, exc.message, retryable=False)
        return 2
    except IntentPayloadError as exc:
        retryable = bool(exc.retryable) or exc.code in _RETRYABLE_INTENT_FAILURES
        _emit_error(exc.code, str(exc), retryable=retryable)
        return 1 if retryable else 2
    except CryptoFailure as exc:
        retryable = exc.code in _RETRYABLE_CRYPTO_FAILURES
        _emit_error(exc.code, "intent crypto is unavailable", retryable=retryable)
        return 1 if retryable else 2
    except (OSError, TypeError, ValueError):
        _emit_error(
            "intent_payload_cli_unavailable",
            "intent payload cli is unavailable",
            retryable=True,
        )
        return 1

    # Strip optional null payload_digest for a closed schema on success.
    if document.get("payload_digest") is None and "payload_digest" in document:
        document = {key: value for key, value in document.items() if key != "payload_digest"}
    _emit(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
