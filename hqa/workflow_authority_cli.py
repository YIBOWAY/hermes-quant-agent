from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
import json
import sys
from typing import Any, Mapping, Optional, Sequence

from hqa import config
from hqa.workflow_authority import WorkflowAuthority, WorkflowAuthorityError
from hqa.workflow_contract import WorkflowContractError


class _CliError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CliError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="hqa-research-task")
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show")
    show.add_argument("--task-ref", required=True)
    events = commands.add_parser("events")
    events.add_argument("--task-ref", required=True)
    events.add_argument("--after-event-id")
    events.add_argument("--limit", type=int, default=100)
    commands.add_parser("audit")
    commands.add_parser("rebuild")
    return parser


def _authority() -> WorkflowAuthority:
    return WorkflowAuthority(
        config.WORKFLOW_AUTHORITY_DIR,
        config.WORKFLOW_OWNER_USER_ID,
    )


def _document(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _document(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _document(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_document(item) for item in value]
    if isinstance(value, list):
        return [_document(item) for item in value]
    return value


def _emit(value: Any) -> None:
    sys.stdout.write(
        json.dumps(
            _document(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _execute(arguments: argparse.Namespace) -> Any:
    authority = _authority()
    if arguments.command == "show":
        return authority.snapshot(arguments.task_ref)
    if arguments.command == "events":
        return authority.events(
            arguments.task_ref,
            after_event_id=arguments.after_event_id,
            limit=arguments.limit,
        )
    if arguments.command == "audit":
        return authority.reverse_audit()
    return authority.rebuild_projection()


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        arguments = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        result = _execute(arguments)
    except (_CliError, WorkflowContractError):
        _emit(
            {
                "error": {
                    "code": "workflow_invalid_request",
                    "message": "workflow command is invalid",
                    "retryable": False,
                }
            }
        )
        return 2
    except WorkflowAuthorityError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": "workflow authority rejected the operation",
                    "retryable": exc.code
                    in {
                        "workflow_storage_unavailable",
                        "workflow_durability_unknown",
                    },
                }
            }
        )
        return 1
    except (OSError, ValueError, TypeError):
        _emit(
            {
                "error": {
                    "code": "workflow_authority_unavailable",
                    "message": "workflow authority is unavailable",
                    "retryable": True,
                }
            }
        )
        return 1
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
