from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from hqa import config
from hqa.research_workflow_saga import (
    PlatformBindingConflict,
    PlatformBindingOutcomeUnknown,
    PlatformBindingRejected,
    PlatformBindingUnavailable,
    ResearchWorkflowSaga,
    SubprocessPlatformWorkflowBindingClient,
)
from hqa.research_workflows import ResearchWorkflowError, ResearchWorkflowStore


_STDIN_LIMIT = 600_000


class _CliArgumentError(ValueError):
    pass


class _WorkflowInputError(ValueError):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CliArgumentError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _WorkflowInputError("duplicate JSON field")
        document[key] = value
    return document


def _reject_constant(_value: str) -> None:
    raise _WorkflowInputError("non-finite JSON number")


def _read_prepare_request() -> dict[str, Any]:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(_STDIN_LIMIT + 1)
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _WorkflowInputError("invalid JSON stdin") from exc
    if not raw or len(raw) > _STDIN_LIMIT:
        raise _WorkflowInputError("empty or oversized JSON stdin")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except _WorkflowInputError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise _WorkflowInputError("invalid JSON stdin") from exc
    if not isinstance(document, dict):
        raise _WorkflowInputError("JSON stdin must be an object")
    return document


def _emit(document: Any) -> None:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload.encode("utf-8", errors="strict")
    sys.stdout.write(payload + "\n")


def _store() -> ResearchWorkflowStore:
    return ResearchWorkflowStore(config.RESEARCH_WORKFLOW_DIR)


def _saga() -> ResearchWorkflowSaga:
    return ResearchWorkflowSaga(
        store=_store(),
        platform=SubprocessPlatformWorkflowBindingClient(
            executable=config.QUANT_SYSTEM_BIN,
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="hqa-research-task")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("submit")
    sub.add_parser("audit-authorities")

    show = sub.add_parser("show")
    show.add_argument("--task-id", required=True)

    events = sub.add_parser("events")
    events.add_argument("--task-id", required=True)
    events.add_argument("--after-event-id")
    events.add_argument("--limit", type=int, default=100)

    reconcile_binding = sub.add_parser("reconcile-binding")
    reconcile_binding.add_argument("--task-id", required=True)

    reconcile = sub.add_parser("reconcile-payloads")
    reconcile.add_argument("--limit", type=int, default=100)
    return parser


def _execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "submit":
        return _saga().submit(_read_prepare_request())
    if args.command == "audit-authorities":
        return _saga().audit_authorities()
    if args.command == "reconcile-binding":
        return _saga().reconcile(args.task_id)
    store = _store()
    if args.command == "prepare":
        return store.prepare(_read_prepare_request())
    if args.command == "show":
        return store.show(args.task_id)
    if args.command == "events":
        return store.events(
            args.task_id,
            after_event_id=args.after_event_id,
            limit=args.limit,
        )
    # Production cleanup always uses the store's authority clock.  An arbitrary
    # caller-supplied future timestamp would permit premature payload deletion.
    return store.reconcile_expired_payloads(limit=args.limit)


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _CliArgumentError:
        _emit(
            {
                "error": {
                    "code": "workflow_invalid_arguments",
                    "message": "invalid research workflow command arguments",
                    "retryable": False,
                }
            }
        )
        return 2
    try:
        document = _execute(args)
    except _WorkflowInputError:
        _emit(
            {
                "error": {
                    "code": "workflow_invalid_json",
                    "message": "prepare requires one strict JSON object on stdin",
                    "retryable": False,
                }
            }
        )
        return 2
    except PlatformBindingOutcomeUnknown:
        _emit(
            {
                "error": {
                    "code": "workflow_platform_outcome_unknown",
                    "message": (
                        "platform binding outcome is unknown; reconcile by exact task"
                    ),
                    "retryable": True,
                }
            }
        )
        return 1
    except PlatformBindingUnavailable:
        _emit(
            {
                "error": {
                    "code": "workflow_platform_unavailable",
                    "message": "platform binding authority is unavailable",
                    "retryable": True,
                }
            }
        )
        return 1
    except (PlatformBindingConflict, PlatformBindingRejected) as exc:
        code = (
            "workflow_platform_conflict"
            if isinstance(exc, PlatformBindingConflict)
            else "workflow_platform_rejected"
        )
        _emit(
            {
                "error": {
                    "code": code,
                    "message": "platform rejected the exact workflow binding",
                    "retryable": False,
                }
            }
        )
        return 2
    except ResearchWorkflowError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            }
        )
        conflict_codes = {
            "workflow_invalid_request",
            "workflow_idempotency_conflict",
            "workflow_idempotency_expired",
            "workflow_version_conflict",
            "workflow_transition_conflict",
            "workflow_binding_mismatch",
            "workflow_binding_conflict",
            "workflow_event_cursor_unknown",
        }
        return 2 if exc.code in conflict_codes else 1
    except OSError:
        _emit(
            {
                "error": {
                    "code": "workflow_storage_io_error",
                    "message": "workflow storage is unavailable",
                    "retryable": True,
                }
            }
        )
        return 1
    _emit(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
