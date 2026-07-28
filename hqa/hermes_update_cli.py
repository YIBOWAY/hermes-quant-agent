"""CLI for the operator-controlled two-worktree Hermes updater."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fcntl
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from hqa.hermes_update import (
    HermesUpdateError,
    UpdateConfig,
    UpdateReceipt,
    apply_update,
    check_update,
    rollback_update,
)


class _ArgumentError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="hqa-hermes-update")
    subcommands = parser.add_subparsers(dest="command", required=True)
    check = subcommands.add_parser("check")
    check.add_argument("--no-fetch", action="store_true")
    subcommands.add_parser("apply")
    rollback = subcommands.add_parser("rollback")
    rollback.add_argument("--receipt", type=Path, required=True)
    return parser


def _absolute_environment_path(name: str, fallback: Path) -> Path:
    path = Path(os.environ.get(name, str(fallback))).expanduser()
    if not path.is_absolute():
        raise HermesUpdateError(
            "paths_must_be_absolute",
            f"{name} must be an absolute path",
        )
    return path


def _environment_config() -> UpdateConfig:
    home = Path.home()
    root = _absolute_environment_path(
        "HQA_HERMES_UPDATE_ROOT",
        home / ".hermes" / "hermes-agent",
    )
    runtime = _absolute_environment_path(
        "HQA_HERMES_UPDATE_RUNTIME",
        root / ".claude" / "worktrees" / "v2-integration",
    )
    state = _absolute_environment_path(
        "HQA_HERMES_UPDATE_STATE",
        home / ".hermes" / "hqa-update",
    )
    uv = os.environ.get("HQA_HERMES_UPDATE_UV") or shutil.which("uv") or "uv"
    hermes = (
        os.environ.get("HQA_HERMES_UPDATE_HERMES_CLI")
        or shutil.which("hermes")
        or str(home / ".local" / "bin" / "hermes")
    )
    return UpdateConfig(
        hermes_root=root,
        runtime_worktree=runtime,
        state_dir=state,
        command_timeout_seconds=1800,
        validation_commands=(
            (
                uv,
                "sync",
                "--frozen",
                "--extra",
                "dev",
                "--extra",
                "messaging",
            ),
            (
                "bash",
                "scripts/run_tests.sh",
                "tests/gateway/test_api_server_capabilities_probe.py",
                "tests/gateway/test_api_server_durable_wiring.py",
                "tests/gateway/test_api_server_managed_runs.py",
                "tests/gateway/test_api_server_approval_cas.py",
                "tests/gateway/test_api_server_run_events_durable.py",
                "tests/gateway/test_api_server_runs_idempotency.py",
                "tests/gateway/test_api_server_stop_reconcile.py",
                "-q",
            ),
        ),
        install_commands=(
            (
                uv,
                "sync",
                "--frozen",
                "--extra",
                "all",
                "--extra",
                "messaging",
                "--extra",
                "edge-tts",
                "--extra",
                "voice",
            ),
        ),
        restart_commands=(
            (hermes, "gateway", "restart"),
            (hermes, "gateway", "status"),
        ),
        health_url="http://127.0.0.1:8642/health",
    )


@contextlib.contextmanager
def _operator_lock(config: UpdateConfig):
    config.state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(config.state_dir, 0o700)
    descriptor = os.open(
        config.state_dir / "operator.lock",
        os.O_RDWR | os.O_CREAT,
        0o600,
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HermesUpdateError(
                "update_already_running",
                "another Hermes update or rollback is already running",
            ) from exc
        yield
    finally:
        os.close(descriptor)


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _emit(value: Any) -> None:
    sys.stdout.write(
        json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _receipt_exit_code(receipt: UpdateReceipt) -> int:
    if receipt.status in {"applied", "rolled_back"}:
        return 0
    if receipt.status == "rollback_failed":
        return 5
    return 4


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(
            list(sys.argv[1:] if argv is None else argv)
        )
        config = _environment_config()
        if arguments.command == "check":
            _emit(check_update(config, fetch=not arguments.no_fetch))
            return 0
        if arguments.command == "apply":
            current = check_update(config, fetch=True)
            if current.status == "up_to_date":
                _emit(current)
                return 0
            with _operator_lock(config):
                receipt = apply_update(config)
            _emit(receipt)
            return _receipt_exit_code(receipt)
        with _operator_lock(config):
            receipt = rollback_update(config, arguments.receipt)
        _emit(receipt)
        return _receipt_exit_code(receipt)
    except _ArgumentError:
        _emit(
            {
                "status": "error",
                "error_code": "invalid_arguments",
                "message": (
                    "usage: hqa-hermes-update check [--no-fetch] | apply | "
                    "rollback --receipt ABSOLUTE_PATH"
                ),
            }
        )
        return 2
    except HermesUpdateError as exc:
        _emit(
            {
                "status": "error",
                "error_code": exc.code,
                "message": str(exc),
            }
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
