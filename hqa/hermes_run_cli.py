"""Bounded subprocess CLI for the official Hermes Run and Session HTTP ports.

The platform invokes this module with exactly one operation and one JSON object
on stdin.  Credentials and prompt bodies therefore never appear in argv or
environment variables.  stdout is exactly one bounded JSON line; stderr stays
empty for all handled failures.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from hqa.hermes_managed_session import (
    OfficialHermesManagedSessionPort,
    derive_managed_session_id,
)
from hqa.hermes_run_adapter import (
    OfficialHermesHttpAdapter,
    UrllibLoopbackHttpTransport,
    evaluate_durable_run_availability,
    HermesRunError,
)

_STDIN_LIMIT = 1_200_000
_STDOUT_LIMIT = 4_194_304
_PROMPT_LIMIT = 16_384
_IDENTIFIER_MAX = 512
_API_KEY_MAX = 4096
HERMES_RUN_CLI_OPERATIONS = (
    "capabilities",
    "submit",
    "status",
    "events",
    "session-ensure",
    "session-fork",
)
HERMES_RUN_SUBMIT_FIELDS = ("input", "session_id", "metadata")
HERMES_RUN_FORBIDDEN_FIELDS = (
    "conversation_history",
    "previous_response_id",
)
HERMES_SESSION_FORK_PRESERVE_SOURCE = True
HERMES_SESSION_FORK_POINT_FORMAT = "message:<positive-integer-id>"
_COMMANDS = frozenset(HERMES_RUN_CLI_OPERATIONS)
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RETRYABLE_CODES = frozenset(
    {
        "durable_unavailable",
        "managed_session_invalid_receipt",
        "run_cli_unavailable",
        "session_db_unavailable",
        "session_fork_unavailable",
        "transport_error",
    }
)


class _CliArgumentError(ValueError):
    pass


class _InputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class HermesEndpoint:
    base_url: str
    timeout_seconds: float
    api_key: Optional[str]


RunAdapterFactory = Callable[[HermesEndpoint], OfficialHermesHttpAdapter]
SessionPortFactory = Callable[
    [HermesEndpoint],
    OfficialHermesManagedSessionPort,
]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _InputError("run_invalid_json", "duplicate JSON field")
        document[key] = value
    return document


def _reject_constant(_value: str) -> None:
    raise _InputError("run_invalid_json", "non-finite JSON number")


def _read_stdin_object() -> dict[str, Any]:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(_STDIN_LIMIT + 1)
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _InputError("run_invalid_json", "invalid JSON stdin") from exc
    if not raw or len(raw) > _STDIN_LIMIT:
        raise _InputError(
            "run_invalid_json",
            "empty or oversized JSON stdin",
        )
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except _InputError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise _InputError("run_invalid_json", "invalid JSON stdin") from exc
    if not isinstance(document, dict):
        raise _InputError("run_invalid_json", "JSON stdin must be an object")
    return document


def _encoded(document: Mapping[str, Any]) -> bytes:
    try:
        raw = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise HermesRunError(
            "run_cli_invalid_receipt",
            "Hermes Run CLI response is invalid",
            http_status=502,
        ) from exc
    if not raw or len(raw) > _STDOUT_LIMIT:
        raise HermesRunError(
            "run_cli_invalid_receipt",
            "Hermes Run CLI response is oversized",
            http_status=502,
        )
    return raw


def _emit(document: Mapping[str, Any]) -> None:
    raw = _encoded(document)
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(raw + b"\n")
    else:
        sys.stdout.write(raw.decode("utf-8") + "\n")


def _emit_error(code: str, *, retryable: bool) -> None:
    safe_code = (
        code
        if type(code) is str
        and 1 <= len(code) <= 100
        and code.replace("_", "").isalnum()
        else "run_cli_failed"
    )
    _emit(
        {
            "error": {
                "code": safe_code,
                "message": "Hermes Run CLI request failed",
                "retryable": retryable,
            }
        }
    )


def _parse_command(argv: Sequence[str]) -> str:
    if len(argv) != 1 or argv[0] not in _COMMANDS:
        raise _CliArgumentError("expected exactly one supported operation")
    return argv[0]


def _require_exact_fields(
    document: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
) -> None:
    keys = set(document)
    if not required.issubset(keys) or keys - required - optional:
        raise _InputError(
            "run_invalid_request",
            "request fields do not match the operation schema",
        )


def _endpoint(document: Mapping[str, Any]) -> HermesEndpoint:
    raw = document.get("endpoint")
    if not isinstance(raw, Mapping):
        raise _InputError("run_invalid_request", "endpoint must be an object")
    _require_exact_fields(
        raw,
        required={"base_url", "timeout_seconds"},
        optional={"api_key"},
    )
    base_url = raw.get("base_url")
    timeout = raw.get("timeout_seconds")
    api_key = raw.get("api_key")
    if type(base_url) is not str or not base_url:
        raise _InputError("run_invalid_request", "endpoint base_url is invalid")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or not 0.1 <= float(timeout) <= 600.0
    ):
        raise _InputError("run_invalid_request", "endpoint timeout is invalid")
    if api_key is not None and (
        type(api_key) is not str
        or not api_key
        or len(api_key.encode("utf-8")) > _API_KEY_MAX
        or any(char in api_key for char in ("\r", "\n", "\x00"))
    ):
        raise _InputError("run_invalid_request", "endpoint api_key is invalid")
    # Constructor enforces http + explicit port + loopback with no network I/O.
    UrllibLoopbackHttpTransport(
        base_url=base_url,
        api_key=api_key,
        timeout_s=float(timeout),
    )
    return HermesEndpoint(
        base_url=base_url,
        timeout_seconds=float(timeout),
        api_key=api_key,
    )


def _default_run_adapter(endpoint: HermesEndpoint) -> OfficialHermesHttpAdapter:
    return OfficialHermesHttpAdapter(
        transport=UrllibLoopbackHttpTransport(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            timeout_s=endpoint.timeout_seconds,
        )
    )


def _default_session_port(
    endpoint: HermesEndpoint,
) -> OfficialHermesManagedSessionPort:
    return OfficialHermesManagedSessionPort(
        transport=UrllibLoopbackHttpTransport(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            timeout_s=endpoint.timeout_seconds,
        )
    )


def _require_identifier(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= _IDENTIFIER_MAX
        or not value.isprintable()
        or any(char.isspace() for char in value)
    ):
        raise _InputError("run_invalid_request", f"{field} is invalid")
    return value


def _require_session_id(value: object) -> str:
    if (
        type(value) is not str
        or _SESSION_ID_RE.fullmatch(value) is None
        or not value.startswith("web_")
    ):
        raise _InputError(
            "run_invalid_request",
            "session_id must be a managed Hermes Session",
        )
    return value


def _require_digest(value: object) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise _InputError("run_invalid_request", "action_digest is invalid")
    return value


def _optional_string(
    document: Mapping[str, Any],
    key: str,
    *,
    maximum: int,
) -> Optional[str]:
    value = document.get(key)
    if value is None:
        return None
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > maximum
        or not value.isprintable()
    ):
        raise _InputError("run_invalid_request", f"{key} is invalid")
    return value.strip()


def _capabilities(
    adapter: OfficialHermesHttpAdapter,
) -> dict[str, Any]:
    capabilities = adapter.capabilities()
    if not isinstance(capabilities, Mapping):
        raise HermesRunError(
            "durable_unavailable",
            "Hermes capabilities response is invalid",
        )
    availability = evaluate_durable_run_availability(capabilities)
    availability.require_available()
    features = capabilities.get("features")
    if (
        not isinstance(features, Mapping)
        or features.get("run_submission") is not True
        or features.get("managed_run_sessions") is not True
        or features.get("managed_run_history_authority")
        != "hermes_session_db"
        or features.get("managed_session_fork_mode")
        != "preserve_source_exact_message_cursor"
    ):
        raise HermesRunError(
            "durable_unavailable",
            "Hermes managed Session history authority is unavailable",
        )
    return {
        "ok": True,
        "capabilities": dict(capabilities),
        "cli_contract": {
            "schema_version": 1,
            "profile": "local_agent_v0_2",
            "operations": list(HERMES_RUN_CLI_OPERATIONS),
            "write_contract": {
                "run_submit_fields": list(HERMES_RUN_SUBMIT_FIELDS),
                "platform_must_not_send": list(HERMES_RUN_FORBIDDEN_FIELDS),
                "fork_requires": {
                    "preserve_source": HERMES_SESSION_FORK_PRESERVE_SOURCE,
                    "fork_point_format": HERMES_SESSION_FORK_POINT_FORMAT,
                },
            },
        },
        "durable_ready": True,
        "managed_session_ready": True,
    }


def _submit(
    request: Mapping[str, Any],
    adapter: OfficialHermesHttpAdapter,
) -> dict[str, Any]:
    _require_exact_fields(
        request,
        required={"endpoint", "idempotency_key", "request_body"},
    )
    idempotency_key = _require_identifier(
        request.get("idempotency_key"),
        "idempotency_key",
    )
    raw_body = request.get("request_body")
    if not isinstance(raw_body, Mapping):
        raise _InputError("run_invalid_request", "request_body must be an object")
    _require_exact_fields(
        raw_body,
        required=set(HERMES_RUN_SUBMIT_FIELDS),
    )
    prompt = raw_body.get("input")
    session_id = _require_session_id(raw_body.get("session_id"))
    metadata = raw_body.get("metadata")
    if (
        type(prompt) is not str
        or not prompt.strip()
        or len(prompt.encode("utf-8")) > _PROMPT_LIMIT
    ):
        raise _InputError("run_invalid_request", "input is invalid or oversized")
    if not isinstance(metadata, Mapping):
        raise _InputError("run_invalid_request", "metadata must be an object")
    try:
        # Reject non-finite/non-JSON metadata and freeze a plain dict before the
        # adapter sends the body.  No conversation history is accepted here:
        # Hermes resolves it canonically from ``session_id``.
        json.dumps(metadata, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise _InputError("run_invalid_request", "metadata is invalid") from exc
    body = {
        "input": prompt,
        "session_id": session_id,
        "metadata": dict(metadata),
    }
    handle = adapter.submit_or_get(
        idempotency_key=idempotency_key,
        request_body=body,
    )
    run_id = _require_identifier(handle.run_id, "run_id")
    return {
        "ok": True,
        "run_id": run_id,
        "session_id": session_id,
        "created": bool(handle.created),
        "idempotency_key": idempotency_key,
    }


def _status(
    request: Mapping[str, Any],
    adapter: OfficialHermesHttpAdapter,
) -> dict[str, Any]:
    _require_exact_fields(request, required={"endpoint", "run_id"})
    run_id = _require_identifier(request.get("run_id"), "run_id")
    snapshot = adapter.get_status(run_id)
    if snapshot.run_id != run_id:
        raise HermesRunError(
            "run_identity_mismatch",
            "Hermes Run status substituted run identity",
            http_status=409,
        )
    document: dict[str, Any] = {"ok": True, **asdict(snapshot)}
    return {key: value for key, value in document.items() if value is not None}


def _events(
    request: Mapping[str, Any],
    adapter: OfficialHermesHttpAdapter,
) -> dict[str, Any]:
    _require_exact_fields(
        request,
        required={"endpoint", "run_id", "since_seq"},
    )
    run_id = _require_identifier(request.get("run_id"), "run_id")
    since_seq = request.get("since_seq")
    if type(since_seq) is not int or since_seq < 0:
        raise _InputError("run_invalid_request", "since_seq is invalid")
    events = adapter.stream_events(run_id, since_seq=since_seq)
    rows: list[dict[str, Any]] = []
    next_seq = since_seq
    for event in events:
        if event.run_id != run_id or event.seq <= next_seq:
            raise HermesRunError(
                "run_replay_invalid",
                "Hermes Run event replay is invalid",
                http_status=502,
            )
        next_seq = event.seq
        rows.append(
            {
                "seq": event.seq,
                "event_type": event.event_type,
                "run_id": event.run_id,
                "payload": dict(event.payload),
                "event_id": event.event_id,
            }
        )
    return {
        "ok": True,
        "run_id": run_id,
        "since_seq": since_seq,
        "next_seq": next_seq,
        "events": rows,
    }


def _session_ensure(
    request: Mapping[str, Any],
    sessions: OfficialHermesManagedSessionPort,
) -> dict[str, Any]:
    _require_exact_fields(
        request,
        required={"endpoint", "action_digest", "session_id"},
        optional={"title", "model"},
    )
    action_digest = _require_digest(request.get("action_digest"))
    session_id = _require_session_id(request.get("session_id"))
    if session_id != derive_managed_session_id(action_digest):
        raise _InputError(
            "managed_session_identity_mismatch",
            "session_id does not match action_digest",
        )
    receipt = sessions.ensure(
        action_digest=action_digest,
        session_id=session_id,
        title=_optional_string(request, "title", maximum=500),
        model=_optional_string(request, "model", maximum=500),
    )
    if receipt.session_id != session_id:
        raise HermesRunError(
            "managed_session_identity_mismatch",
            "managed Session receipt substituted identity",
            http_status=409,
        )
    return {
        "ok": True,
        "action_digest": action_digest,
        "session_id": receipt.session_id,
        "created": receipt.created,
        "recovered": receipt.recovered,
        "session": dict(receipt.session),
    }


def _session_fork(
    request: Mapping[str, Any],
    sessions: OfficialHermesManagedSessionPort,
) -> dict[str, Any]:
    _require_exact_fields(
        request,
        required={
            "endpoint",
            "action_digest",
            "source_session_id",
            "session_id",
            "fork_point",
        },
        optional={"title"},
    )
    action_digest = _require_digest(request.get("action_digest"))
    source_id = _require_identifier(
        request.get("source_session_id"),
        "source_session_id",
    )
    session_id = _require_session_id(request.get("session_id"))
    if session_id != derive_managed_session_id(action_digest):
        raise _InputError(
            "managed_session_identity_mismatch",
            "session_id does not match action_digest",
        )
    fork_point = _require_identifier(request.get("fork_point"), "fork_point")
    receipt = sessions.fork(
        action_digest=action_digest,
        source_session_id=source_id,
        session_id=session_id,
        fork_point=fork_point,
        title=_optional_string(request, "title", maximum=500),
    )
    if (
        receipt.session_id != session_id
        or receipt.source_session_id != source_id
        or receipt.fork_point != fork_point
    ):
        raise HermesRunError(
            "managed_session_identity_mismatch",
            "managed Session fork receipt substituted lineage",
            http_status=409,
        )
    return {
        "ok": True,
        "action_digest": action_digest,
        "session_id": receipt.session_id,
        "source_session_id": receipt.source_session_id,
        "resolved_source_session_id": receipt.resolved_source_session_id,
        "fork_point": receipt.fork_point,
        "preserve_source": True,
        "created": receipt.created,
        "recovered": receipt.recovered,
        "session": dict(receipt.session),
    }


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    adapter_factory: Optional[RunAdapterFactory] = None,
    session_port_factory: Optional[SessionPortFactory] = None,
) -> int:
    try:
        command = _parse_command(list(sys.argv[1:] if argv is None else argv))
    except _CliArgumentError:
        _emit_error("run_invalid_arguments", retryable=False)
        return 2

    try:
        request = _read_stdin_object()
        endpoint = _endpoint(request)
        if command in {"capabilities", "submit", "status", "events"}:
            adapter = (adapter_factory or _default_run_adapter)(endpoint)
            if command == "capabilities":
                _require_exact_fields(request, required={"endpoint"})
                response = _capabilities(adapter)
            elif command == "submit":
                response = _submit(request, adapter)
            elif command == "status":
                response = _status(request, adapter)
            else:
                response = _events(request, adapter)
        else:
            sessions = (session_port_factory or _default_session_port)(endpoint)
            if command == "session-ensure":
                response = _session_ensure(request, sessions)
            else:
                response = _session_fork(request, sessions)
        # Validate/size-bound before the first byte reaches stdout.
        _ = _encoded(response)
    except _InputError as exc:
        _emit_error(exc.code, retryable=False)
        return 2
    except HermesRunError as exc:
        retryable = (
            exc.code in _RETRYABLE_CODES
            or exc.code.endswith("_unavailable")
            or exc.http_status >= 500
        )
        _emit_error(exc.code, retryable=retryable)
        return 1 if retryable else 2
    except (OSError, TypeError, ValueError):
        _emit_error("run_cli_unavailable", retryable=True)
        return 1

    _emit(response)
    return 0


__all__ = [
    "HERMES_RUN_CLI_OPERATIONS",
    "HERMES_RUN_FORBIDDEN_FIELDS",
    "HERMES_RUN_SUBMIT_FIELDS",
    "HERMES_SESSION_FORK_POINT_FORMAT",
    "HERMES_SESSION_FORK_PRESERVE_SOURCE",
    "HermesEndpoint",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
