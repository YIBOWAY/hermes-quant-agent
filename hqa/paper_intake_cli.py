"""Bounded subprocess verifier for ``hqa.paper_intake/v1``.

The platform calls this module only after an exact Hermes Run reports
``succeeded``.  The verifier resolves the command-bound encrypted intake,
reads the authoritative managed-session transcript over loopback HTTP, and
persists one metadata-only receipt before the platform may mark the command
succeeded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence
from urllib.parse import quote

from hqa import config
from hqa.hermes_run_adapter import HermesRunError, UrllibLoopbackHttpTransport
from hqa.intent_payload_crypto import CryptoFailure, MacOSKeychainCrypto
from hqa.intent_payloads import IntentPayloadError, IntentPayloadStore
from hqa.paper_intake import (
    PaperIntakeError,
    build_execution_contract,
    execution_contract_digest,
    verify_paper_intake,
)
from hqa.research_claim import (
    ResearchClaimError,
    build_research_claim,
    research_claim_digest,
)


_COMMANDS = frozenset({"prepare", "verify"})
_STDIN_LIMIT = 64_000
_STDOUT_LIMIT = 64_000
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,254}\Z")
_PAYLOAD_RE = re.compile(r"payload:sha256:[0-9a-f]{64}\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_VERIFY_REQUEST_FIELDS = {
    "endpoint",
    "workspace_id",
    "platform_session_id",
    "command_id",
    "payload_ref",
    "hermes_session_id",
    "hermes_run_id",
    "observation_evidence_digest",
}
_PREPARE_REQUEST_FIELDS = {
    "schema_version",
    "kind",
    "owner_id",
    "workspace_id",
    "session_id",
    "client_intent_id",
    "provider_policy",
    "prompt",
    "ttl_days",
    "paper_title",
    "universe",
}


class _PayloadStore(Protocol):
    def put(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def resolve(
        self,
        payload_ref: str,
        *,
        owner_id: str,
        workspace_id: str,
        session_id: str,
        consumer_ref: str | None = None,
    ) -> dict[str, Any]: ...


TranscriptReader = Callable[[str, object], Sequence[Mapping[str, Any]]]


class _InputError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InputError("duplicate field")
        result[key] = value
    return result


def _read_request(*, expected_fields: set[str]) -> dict[str, Any]:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(_STDIN_LIMIT + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="strict")
    if not raw or len(raw) > _STDIN_LIMIT:
        raise _InputError("empty or oversized request")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(_InputError()),
        )
    except (_InputError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise _InputError("invalid request") from None
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise _InputError("invalid request fields")
    return document


def _identifier(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise _InputError(f"{key} is invalid")
    return value


def _validated_request(document: Mapping[str, Any]) -> dict[str, Any]:
    endpoint = document.get("endpoint")
    if not isinstance(endpoint, Mapping) or set(endpoint) not in {
        frozenset({"base_url", "timeout_seconds"}),
        frozenset({"base_url", "timeout_seconds", "api_key"}),
    }:
        raise _InputError("endpoint is invalid")
    base_url = endpoint.get("base_url")
    timeout = endpoint.get("timeout_seconds")
    api_key = endpoint.get("api_key")
    if (
        type(base_url) is not str
        or isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0.1 <= float(timeout) <= 30.0
        or (api_key is not None and (type(api_key) is not str or not api_key))
    ):
        raise _InputError("endpoint is invalid")
    # Constructor enforces loopback and credential shape before any I/O.
    UrllibLoopbackHttpTransport(
        base_url=base_url,
        api_key=api_key,
        timeout_s=float(timeout),
    )
    payload_ref = document.get("payload_ref")
    digest = document.get("observation_evidence_digest")
    if (
        type(payload_ref) is not str
        or _PAYLOAD_RE.fullmatch(payload_ref) is None
        or type(digest) is not str
        or _DIGEST_RE.fullmatch(digest) is None
    ):
        raise _InputError("content identity is invalid")
    return {
        "endpoint": {
            "base_url": base_url,
            "timeout_seconds": float(timeout),
            **({"api_key": api_key} if api_key is not None else {}),
        },
        "workspace_id": _identifier(document, "workspace_id"),
        "platform_session_id": _identifier(document, "platform_session_id"),
        "command_id": _identifier(document, "command_id"),
        "payload_ref": payload_ref,
        "hermes_session_id": _identifier(document, "hermes_session_id"),
        "hermes_run_id": _identifier(document, "hermes_run_id"),
        "observation_evidence_digest": digest,
    }


def _prepare(
    store: _PayloadStore,
    document: Mapping[str, Any],
    *,
    source_root: Path,
) -> dict[str, object]:
    if document.get("schema_version") != "2.0" or document.get("kind") != "paper_intake":
        raise _InputError("paper intake prepare schema is invalid")
    title = document.get("paper_title")
    universe = document.get("universe")
    if type(title) is not str or not isinstance(universe, list):
        raise _InputError("paper intake claim is invalid")
    try:
        claim = build_research_claim(title, universe)
    except ResearchClaimError as exc:
        raise _InputError("paper intake claim is invalid") from exc
    client_intent_id = document.get("client_intent_id")
    if type(client_intent_id) is not str or _ID_RE.fullmatch(client_intent_id) is None:
        raise _InputError("client_intent_id is invalid")

    root = Path(os.path.abspath(source_root))
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
    except OSError as exc:
        raise PaperIntakeError("paper_intake_source_unavailable", retryable=True) from exc
    source_name = hashlib.sha256(
        client_intent_id.encode("utf-8", errors="strict")
    ).hexdigest()
    contract = build_execution_contract(
        source_file_ref=root / f"factor-{source_name}.py"
    )
    put_request = {
        key: value
        for key, value in document.items()
        if key not in {"paper_title", "universe"}
    }
    put_request["research_claim"] = claim
    put_request["execution_contract"] = contract
    receipt = store.put(put_request)
    return {
        "ok": True,
        "schema_version": receipt["schema_version"],
        "payload_ref": receipt["payload_ref"],
        "payload_digest": receipt["payload_digest"],
        "kind": receipt["kind"],
        "client_intent_id": receipt["client_intent_id"],
        "provider_policy_digest": receipt["provider_policy_digest"],
        "created_at": receipt["created_at"],
        "expires_at": receipt["expires_at"],
        "ttl_days": receipt["ttl_days"],
        "status": receipt["status"],
        "research_claim_digest": research_claim_digest(claim),
        "execution_contract_digest": execution_contract_digest(contract),
    }


def _store() -> IntentPayloadStore:
    return IntentPayloadStore(
        config.INTENT_PAYLOAD_DIR,
        crypto=MacOSKeychainCrypto(config.INTENT_PAYLOAD_CRYPTO_HELPER),
    )


def _read_transcript(
    session_id: str,
    endpoint: object,
) -> Sequence[Mapping[str, Any]]:
    if not isinstance(endpoint, Mapping):
        raise PaperIntakeError("paper_intake_transcript_unavailable", retryable=True)
    transport = UrllibLoopbackHttpTransport(
        base_url=str(endpoint.get("base_url")),
        api_key=(
            str(endpoint["api_key"])
            if endpoint.get("api_key") is not None
            else None
        ),
        timeout_s=float(endpoint.get("timeout_seconds", 5.0)),
    )
    payload = transport.get_json(
        f"/api/sessions/{quote(session_id, safe='')}/messages?limit=500&order=latest"
    )
    if payload.get("session_id") != session_id or not isinstance(payload.get("data"), list):
        raise PaperIntakeError("paper_intake_transcript_invalid", retryable=True)
    rows = payload["data"]
    if len(rows) > 500 or any(not isinstance(row, Mapping) for row in rows):
        raise PaperIntakeError("paper_intake_transcript_invalid", retryable=True)
    return [dict(row) for row in rows]


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PaperIntakeError("paper_intake_receipt_invalid") from exc


def _persist_receipt(receipt: Mapping[str, Any], root: Path) -> tuple[str, str]:
    raw = _canonical_bytes(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    root = Path(os.path.abspath(root))
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        target = root / f"receipt-{digest}.json"
        if target.exists():
            if target.read_bytes() != raw:
                raise PaperIntakeError("paper_intake_receipt_conflict")
        else:
            temporary = root / f".receipt-{digest}.{os.getpid()}.tmp"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb", closefd=True) as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            dir_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except PaperIntakeError:
        raise
    except OSError as exc:
        raise PaperIntakeError("paper_intake_receipt_unavailable", retryable=True) from exc
    return f"paper-intake-receipt:sha256:{digest}", digest


def _emit(document: Mapping[str, Any]) -> None:
    raw = _canonical_bytes(document)
    if len(raw) > _STDOUT_LIMIT:
        raise PaperIntakeError("paper_intake_receipt_invalid")
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(raw)
    else:
        sys.stdout.write(raw.decode("utf-8"))


def _safe_error(code: object, *, retryable: bool) -> dict[str, object]:
    safe = (
        code
        if type(code) is str
        and 1 <= len(code) <= 100
        and code.replace("_", "").isalnum()
        else "paper_intake_verification_failed"
    )
    return {
        "ok": False,
        "error": {
            "code": safe,
            "message": "paper intake verification failed",
            "retryable": retryable,
        },
    }


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    store_factory: Callable[[], _PayloadStore] = _store,
    transcript_reader: TranscriptReader = _read_transcript,
    receipt_root: Optional[Path] = None,
    source_root: Optional[Path] = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in _COMMANDS:
        _emit(_safe_error("paper_intake_invalid_arguments", retryable=False))
        return 2
    try:
        if args[0] == "prepare":
            request = _read_request(expected_fields=_PREPARE_REQUEST_FIELDS)
            document = _prepare(
                store_factory(),
                request,
                source_root=source_root or (config.PAPER_INTAKE_DIR / "drafts"),
            )
            _emit(document)
            return 0
        request = _validated_request(
            _read_request(expected_fields=_VERIFY_REQUEST_FIELDS)
        )
        store = store_factory()
        envelope = store.resolve(
            request["payload_ref"],
            owner_id=config.WORKFLOW_OWNER_USER_ID,
            workspace_id=f"workspace:{request['workspace_id']}",
            session_id=f"session:{request['platform_session_id']}",
            consumer_ref=f"command:{request['command_id']}",
        )
        if envelope.get("kind") != "paper_intake":
            _emit({
                "ok": True,
                "disposition": "not_required",
                "command_id": request["command_id"],
                "payload_ref": request["payload_ref"],
                "hermes_run_id": request["hermes_run_id"],
            })
            return 0
        receipt = verify_paper_intake(
            execution_contract=envelope.get("execution_contract"),
            research_claim=envelope.get("research_claim"),
            prompt=envelope.get("prompt"),
            messages=transcript_reader(
                request["hermes_session_id"],
                request["endpoint"],
            ),
            command_id=request["command_id"],
            payload_ref=request["payload_ref"],
            hermes_session_id=request["hermes_session_id"],
            hermes_run_id=request["hermes_run_id"],
            observation_evidence_digest=request["observation_evidence_digest"],
        )
        receipt_ref, receipt_digest = _persist_receipt(
            receipt,
            receipt_root or (config.PAPER_INTAKE_DIR / "receipts"),
        )
        _emit({
            "ok": True,
            **receipt,
            "receipt_ref": receipt_ref,
            "receipt_digest": receipt_digest,
        })
        return 0
    except _InputError:
        document = _safe_error("paper_intake_invalid_request", retryable=False)
        exit_code = 2
    except PaperIntakeError as exc:
        document = _safe_error(exc.code, retryable=exc.retryable)
        exit_code = 1 if exc.retryable else 2
    except IntentPayloadError as exc:
        document = _safe_error(exc.code, retryable=bool(exc.retryable))
        exit_code = 1 if exc.retryable else 2
    except HermesRunError:
        document = _safe_error("paper_intake_transcript_unavailable", retryable=True)
        exit_code = 1
    except CryptoFailure:
        document = _safe_error("paper_intake_payload_unavailable", retryable=True)
        exit_code = 1
    except (OSError, TypeError, ValueError):
        document = _safe_error("paper_intake_verifier_unavailable", retryable=True)
        exit_code = 1
    _emit(document)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
