"""Strict JSON subprocess port for the canonical Hermes durable Run surface.

The platform is a sibling repository and must never import :mod:`hqa`.
Instead it may invoke this module with one operation name, write one bounded
JSON object to stdin, and read one JSON object from stdout.  Prompt text and
the upstream bearer token therefore never appear in argv or log messages.

The production adapter remains loopback-only and fail-closed on the six
durable capability probes.  Tests inject ``ScriptedFakeHermesAdapter`` through
``adapter_factory``; the fake is never selected by an environment flag.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from hqa.hermes_run_adapter import (
    HermesRunError,
    HermesRunPort,
    OfficialHermesHttpAdapter,
    UrllibLoopbackHttpTransport,
)

_STDIN_LIMIT = 1_200_000
_COMMANDS = frozenset(
    {"submit", "status", "events", "approval", "stop", "capabilities"}
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,511}\Z")
_RETRYABLE_ERRORS = frozenset(
    {"transport_error", "durable_unavailable", "run_cli_unavailable"}
)


class _CliArgumentError(ValueError):
    pass


class _InputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key: Optional[str]
    timeout_seconds: float


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
        raise _InputError("run_invalid_json", "empty or oversized JSON stdin")
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
    _emit({"error": {"code": code, "message": message, "retryable": retryable}})


def _parse_command(argv: Sequence[str]) -> str:
    if len(argv) != 1 or argv[0] not in _COMMANDS:
        raise _CliArgumentError(
            "expected one operation: submit | status | events | approval | stop | capabilities"
        )
    return argv[0]


def _require_exact_fields(
    document: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] = set(),
) -> None:
    fields = set(document)
    missing = required - fields
    unexpected = fields - required - optional
    if missing or unexpected:
        raise _InputError(
            "run_invalid_request",
            "request fields do not match the closed schema",
        )


def _require_identifier(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise _InputError("run_invalid_request", f"{key} must be a bounded identifier")
    return value


def _parse_endpoint(value: Any) -> Endpoint:
    if type(value) is not dict:
        raise _InputError("run_invalid_request", "endpoint must be an object")
    _require_exact_fields(
        value,
        required={"base_url", "timeout_seconds"},
        optional={"api_key"},
    )
    base_url = value.get("base_url")
    api_key = value.get("api_key")
    timeout = value.get("timeout_seconds")
    if type(base_url) is not str or not base_url:
        raise _InputError("run_invalid_request", "endpoint.base_url is required")
    if api_key is not None and (type(api_key) is not str or not api_key):
        raise _InputError("run_invalid_request", "endpoint.api_key must be nonempty")
    if type(timeout) not in (int, float) or isinstance(timeout, bool):
        raise _InputError("run_invalid_request", "endpoint.timeout_seconds is invalid")
    timeout_float = float(timeout)
    if not 0.1 <= timeout_float <= 600.0:
        raise _InputError("run_invalid_request", "endpoint.timeout_seconds is invalid")
    return Endpoint(base_url=base_url, api_key=api_key, timeout_seconds=timeout_float)


def _default_adapter(endpoint: Endpoint) -> HermesRunPort:
    return OfficialHermesHttpAdapter(
        transport=UrllibLoopbackHttpTransport(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            timeout_s=endpoint.timeout_seconds,
        )
    )


def _dispatch(command: str, request: dict[str, Any], adapter: HermesRunPort) -> dict[str, Any]:
    if command == "capabilities":
        _require_exact_fields(request, required={"endpoint"})
        capabilities = dict(adapter.capabilities())
        availability = adapter.durable_availability()
        return {
            "ok": True,
            "capabilities": capabilities,
            "durable_available": availability.available,
            "durable_blockers": list(availability.blockers),
            "contract_version": availability.contract_version,
        }

    if command == "submit":
        _require_exact_fields(
            request,
            required={"endpoint", "idempotency_key", "request_body"},
        )
        idempotency_key = _require_identifier(request, "idempotency_key")
        body = request.get("request_body")
        if type(body) is not dict or not body:
            raise _InputError("run_invalid_request", "request_body must be an object")
        handle = adapter.submit_or_get(
            idempotency_key=idempotency_key,
            request_body=body,
        )
        return {
            "ok": True,
            "run_id": handle.run_id,
            "created": handle.created,
            "idempotency_key": handle.idempotency_key,
        }

    if command == "status":
        _require_exact_fields(request, required={"endpoint", "run_id"})
        snapshot = adapter.get_status(_require_identifier(request, "run_id"))
        return {"ok": True, **asdict(snapshot)}

    if command == "events":
        _require_exact_fields(
            request,
            required={"endpoint", "run_id"},
            optional={"since_seq"},
        )
        run_id = _require_identifier(request, "run_id")
        since_seq = request.get("since_seq", 0)
        if type(since_seq) is not int or not 0 <= since_seq <= (2**63 - 1):
            raise _InputError("run_invalid_request", "since_seq is invalid")
        events = adapter.stream_events(run_id, since_seq=since_seq)
        rows = [asdict(event) for event in events]
        return {
            "ok": True,
            "run_id": run_id,
            "since_seq": since_seq,
            "events": rows,
            "next_seq": max((event.seq for event in events), default=since_seq),
        }

    if command == "approval":
        _require_exact_fields(
            request,
            required={
                "endpoint",
                "run_id",
                "choice",
                "challenge_id",
                "action_digest",
            },
        )
        result = adapter.respond_approval(
            _require_identifier(request, "run_id"),
            choice=_require_identifier(request, "choice"),
            challenge_id=_require_identifier(request, "challenge_id"),
            action_digest=_require_identifier(request, "action_digest"),
        )
        return {"ok": True, **asdict(result)}

    if command == "stop":
        _require_exact_fields(request, required={"endpoint", "run_id"})
        result = adapter.stop(_require_identifier(request, "run_id"))
        return {"ok": True, **asdict(result)}

    raise _InputError("run_invalid_arguments", "unsupported operation")


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    adapter_factory: Optional[Callable[[Endpoint], HermesRunPort]] = None,
) -> int:
    try:
        command = _parse_command(list(sys.argv[1:] if argv is None else argv))
    except _CliArgumentError as exc:
        _emit_error("run_invalid_arguments", str(exc), retryable=False)
        return 2

    try:
        request = _read_stdin_object()
        # Validate the whole command schema before constructing a transport;
        # malformed requests therefore cannot cause network I/O.
        allowed = {
            "capabilities": ({"endpoint"}, set()),
            "submit": ({"endpoint", "idempotency_key", "request_body"}, set()),
            "status": ({"endpoint", "run_id"}, set()),
            "events": ({"endpoint", "run_id"}, {"since_seq"}),
            "approval": (
                {"endpoint", "run_id", "choice", "challenge_id", "action_digest"},
                set(),
            ),
            "stop": ({"endpoint", "run_id"}, set()),
        }
        required, optional = allowed[command]
        _require_exact_fields(request, required=required, optional=optional)
        endpoint = _parse_endpoint(request.get("endpoint"))
        adapter = (adapter_factory or _default_adapter)(endpoint)
        response = _dispatch(command, request, adapter)
    except _InputError as exc:
        _emit_error(exc.code, exc.message, retryable=False)
        return 2
    except HermesRunError as exc:
        retryable = exc.code in _RETRYABLE_ERRORS
        _emit_error(exc.code, exc.message, retryable=retryable)
        return 1 if retryable else 2
    except (OSError, TypeError, ValueError, KeyError):
        _emit_error(
            "run_cli_unavailable",
            "Hermes durable Run port is unavailable",
            retryable=True,
        )
        return 1

    _emit(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
