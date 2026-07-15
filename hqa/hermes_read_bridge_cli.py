"""CLI for fail-closed Hermes read-only bridge operations.

Commands:
  list-sessions
  session-status --session-id <id>
  session-history --session-id <id>

Each command rebuilds the live capability gate from the default contract +
installation probe. Refuses when ``chat_read_enabled`` is false. Never exposes
prompt.submit / session.create / resume / interrupt / approval.respond /
config.set.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

from hqa import config, hermes_capability_cli
from hqa.hermes_capabilities import CapabilityContractError
from hqa.hermes_read_bridge import (
    BridgeGateError,
    BridgeTransportError,
    HermesReadBridge,
    JsonRpcTransport,
    gate_from_mapping,
    open_read_bridge,
)

_SESSION_TOKEN_ENV = "HERMES_DASHBOARD_SESSION_TOKEN"
_SESSION_TOKEN_FILE_ENV = "HQA_HERMES_SESSION_TOKEN_FILE"
_MAX_SESSION_TOKEN_BYTES = 4096


class _ArgumentError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentError(message)


def _emit(document: Mapping[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="hqa-hermes-read-bridge")
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="WebSocket JSON-RPC timeout seconds (default 10)",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help=(
            "Optional loopback WebSocket endpoint override. "
            "Defaults to the contract endpoint. Non-loopback values fail closed."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_sessions = sub.add_parser(
        "list-sessions",
        help="Call session.list (read-only)",
    )
    list_sessions.add_argument("--limit", type=int, default=200)

    status = sub.add_parser(
        "session-status",
        help="Call session.status (read-only)",
    )
    status.add_argument("--session-id", required=True)

    history = sub.add_parser(
        "session-history",
        help="Call session.history (read-only)",
    )
    history.add_argument("--session-id", required=True)

    # Explicit rejection surface for mutation names so they never silently
    # fall through as unknown argparse commands without a clear JSON error.
    for forbidden in (
        "session-create",
        "prompt-submit",
        "session-resume",
        "session-interrupt",
        "approval-respond",
        "config-set",
    ):
        sub.add_parser(forbidden, help=argparse.SUPPRESS)

    return parser


def load_live_capability_document(
    contract_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Load default contract, apply review + installation gates."""
    path = contract_path or config.HERMES_GATEWAY_CAPABILITIES_PATH
    document = hermes_capability_cli._read(path)
    document = hermes_capability_cli._apply_review_gate(document, path)
    document = hermes_capability_cli._apply_installation_gate(document)
    return document


def _validated_session_token(raw: bytes) -> Optional[str]:
    if len(raw) > _MAX_SESSION_TOKEN_BYTES:
        raise BridgeTransportError(
            "session_token_invalid",
            "Hermes session token must be non-empty and bounded",
        )
    try:
        token = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise BridgeTransportError(
            "session_token_invalid",
            "Hermes session token must be valid UTF-8",
        ) from exc
    if any(char in token for char in ("\r", "\n", "\x00")):
        raise BridgeTransportError(
            "session_token_invalid",
            "Hermes session token contains invalid characters",
        )
    return token or None


def _read_owner_only_session_token_file(file_path: str) -> Optional[str]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(file_path, flags)
    except OSError as exc:
        raise BridgeTransportError(
            "session_token_file_invalid",
            f"{_SESSION_TOKEN_FILE_ENV} must point to a regular non-symlink file",
        ) from exc
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise BridgeTransportError(
                "session_token_file_invalid",
                f"{_SESSION_TOKEN_FILE_ENV} must point to a regular non-symlink file",
            )
        if stat.S_IMODE(file_stat.st_mode) & 0o077:
            raise BridgeTransportError(
                "session_token_file_permissions",
                f"{_SESSION_TOKEN_FILE_ENV} must be owner-only (mode 0600 or stricter)",
            )
        if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
            raise BridgeTransportError(
                "session_token_file_owner",
                f"{_SESSION_TOKEN_FILE_ENV} must be owned by the current user",
            )
        raw = os.read(fd, _MAX_SESSION_TOKEN_BYTES + 1)
    except BridgeTransportError:
        raise
    except OSError as exc:
        raise BridgeTransportError(
            "session_token_file_invalid",
            f"{_SESSION_TOKEN_FILE_ENV} is unavailable",
        ) from exc
    finally:
        os.close(fd)
    return _validated_session_token(raw)


def resolve_session_token() -> Optional[str]:
    """Resolve the Hermes loopback WS token without printing it.

    Order: ``HERMES_DASHBOARD_SESSION_TOKEN`` → contents of
    ``HQA_HERMES_SESSION_TOKEN_FILE`` (single line, owner-only permissions).
    Tokens are never accepted on the command line because process arguments are
    visible to other local processes. Empty means "no token"; live Hermes will
    then return websocket_upgrade_failed (403).
    """
    env_token = os.environ.get(_SESSION_TOKEN_ENV)
    if env_token:
        return _validated_session_token(env_token.encode("utf-8"))
    file_path = (os.environ.get(_SESSION_TOKEN_FILE_ENV) or "").strip()
    if not file_path:
        return None
    return _read_owner_only_session_token_file(file_path)


def build_bridge_from_document(
    document: Mapping[str, Any],
    *,
    endpoint: Optional[str] = None,
    timeout_s: float = 10.0,
    transport: Optional[JsonRpcTransport] = None,
    session_token: Optional[str] = None,
) -> tuple[HermesReadBridge, dict[str, Any]]:
    """Construct a read bridge or raise BridgeGateError if chat_read is closed.

    Returns ``(bridge, meta)`` where meta records endpoint + gate summary.
    Meta never includes the session token.
    """
    gate_raw = document.get("gate")
    if not isinstance(gate_raw, Mapping):
        raise BridgeGateError("invalid_gate", "capability document missing gate")
    gate = gate_from_mapping(gate_raw)
    if gate.chat_read_enabled is not True:
        raise BridgeGateError(
            "chat_read_disabled",
            "Hermes read bridge refuses operation while chat_read_enabled is false",
        )
    # Writes stay fail-closed even when a caller only asked for reads; surface
    # honesty in meta without claiming chat ready.
    contract = document.get("contract") if isinstance(document.get("contract"), Mapping) else {}
    resolved_endpoint = endpoint or str(contract.get("endpoint") or "")
    if not resolved_endpoint:
        raise BridgeTransportError(
            "missing_endpoint",
            "capability contract has no endpoint and no --endpoint override was given",
        )
    if transport is None:
        bridge = open_read_bridge(
            gate=gate,
            endpoint=resolved_endpoint,
            timeout_s=timeout_s,
            session_token=session_token,
        )
    else:
        bridge = HermesReadBridge(gate=gate, transport=transport)
    meta = {
        "endpoint": resolved_endpoint,
        "chat_read_enabled": True,
        "chat_write_enabled": gate.chat_write_enabled is True,
        "stream_enabled": gate.stream_enabled is True,
        "chat_ready": False,  # never claim fully connected from the read CLI
        "session_token_present": bool(session_token),
        "gate_blockers": list(gate.blockers),
    }
    return bridge, meta


def _error_document(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    payload.update(extra)
    return payload


def main(
    argv: Optional[list[str]] = None,
    *,
    transport: Optional[JsonRpcTransport] = None,
    document: Optional[Mapping[str, Any]] = None,
) -> int:
    """Entry point. ``transport`` / ``document`` are hermetic test seams only."""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if any(
        item == "--session-token" or item.startswith("--session-token=")
        for item in raw_argv
    ):
        _emit(
            _error_document(
                "session_token_argv_forbidden",
                "session tokens must be supplied through the environment or an owner-only token file",
            )
        )
        return 2
    try:
        args = _parser().parse_args(raw_argv)
    except _ArgumentError as exc:
        _emit(_error_document("invalid_arguments", str(exc)))
        return 2

    forbidden_aliases = {
        "session-create",
        "prompt-submit",
        "session-resume",
        "session-interrupt",
        "approval-respond",
        "config-set",
    }
    if args.command in forbidden_aliases:
        _emit(
            _error_document(
                "mutation_forbidden",
                f"command {args.command} is never allowed on the Hermes read bridge CLI",
                chat_ready=False,
            )
        )
        return 3

    try:
        live_document: Mapping[str, Any]
        if document is not None:
            live_document = document
        else:
            live_document = load_live_capability_document()
        resolved_token = resolve_session_token()
        bridge, meta = build_bridge_from_document(
            live_document,
            endpoint=args.endpoint,
            timeout_s=float(args.timeout),
            transport=transport,
            session_token=resolved_token,
        )
    except CapabilityContractError as exc:
        _emit(
            _error_document(
                "capability_contract_invalid",
                str(exc),
                chat_ready=False,
            )
        )
        return 1
    except BridgeGateError as exc:
        exit_code = 3 if exc.code in {"chat_read_disabled", "mutation_forbidden"} else 1
        _emit(
            _error_document(
                exc.code,
                exc.message,
                chat_ready=False,
            )
        )
        return exit_code

    try:
        if args.command == "list-sessions":
            result = bridge.list_sessions(limit=int(args.limit))
        elif args.command == "session-status":
            result = bridge.session_status(args.session_id)
        elif args.command == "session-history":
            result = bridge.session_history(args.session_id)
        else:
            _emit(
                _error_document(
                    "unknown_command",
                    f"unknown command: {args.command}",
                    chat_ready=False,
                )
            )
            return 2
    except BridgeGateError as exc:
        # BridgeTransportError subclasses BridgeGateError; both are fail-closed.
        exit_code = 3 if exc.code in {"chat_read_disabled", "mutation_forbidden"} else 1
        _emit(
            {
                "error": {"code": exc.code, "message": exc.message},
                "meta": meta,
                "chat_ready": False,
                "chat_write_enabled": meta.get("chat_write_enabled", False),
            }
        )
        return exit_code

    _emit(
        {
            "status": "ok",
            "command": args.command,
            "result": result,
            "meta": meta,
            # Explicit honesty: read path does not authorize write/stream.
            "chat_ready": False,
            "chat_write_enabled": meta["chat_write_enabled"],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
