#!/usr/bin/python3
"""Non-evaluating launcher for one exact paper-Gate read.

Managed Hermes intentionally does not inherit Platform database credentials.
This launcher reads only the database keys needed by ``paper-gate show`` from
the fixed owner-only Platform backend env. It never sources or evaluates it.
"""

from __future__ import annotations

import errno
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

_PLATFORM_DIR = Path("__HQA_PLATFORM_DIR__")
_RUNTIME_ENV = _PLATFORM_DIR / "data" / "_runtime" / "agent-v0.2-backend.env"
_QUANT_SYSTEM = _PLATFORM_DIR / "ai-quant" / "bin" / "quant-system"
_MAX_ENV_BYTES = 64 * 1024
_MAX_DATABASE_URL_BYTES = 4096
_GATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CONTEXT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_ASSIGNMENT_RE = re.compile(r"^(?:export[ \t]+)?([A-Z][A-Z0-9_]*)=(.*)$")
_KEYCHAIN_DATABASE_URL = (
    "postgresql://quant_app_runtime:$(security find-generic-password -w "
    '-s ai-quant-platform-agent-v02-db -a "${USER}")'
    "@127.0.0.1:5432/quantplatform"
)
_DATABASE_KEYS = frozenset(
    {
        "QS_DATABASE_AUTO_MIGRATE",
        "QS_DATABASE_CONNECT_TIMEOUT_SECONDS",
        "QS_DATABASE_ENABLED",
        "QS_DATABASE_URL",
    }
)
_SAFE_CHILD_ENV = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "SSL_CERT_FILE",
        "TMPDIR",
        "TZ",
    }
)


class ConfigError(RuntimeError):
    """A stable, secret-free configuration failure."""


def _fail(code: str) -> int:
    print(f"paper_gate_env_error={code}", file=sys.stderr)
    return 78


def _read_runtime_env() -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(_RUNTIME_ENV, flags)
    except FileNotFoundError as exc:
        raise ConfigError("runtime_env_missing") from exc
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ConfigError("runtime_env_not_regular") from exc
        raise ConfigError("runtime_env_open_failed") from exc

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ConfigError("runtime_env_not_regular")
        if metadata.st_uid != os.geteuid():
            raise ConfigError("runtime_env_wrong_owner")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ConfigError("runtime_env_mode_must_be_600")
        if metadata.st_size > _MAX_ENV_BYTES:
            raise ConfigError("runtime_env_too_large")
        payload = bytearray()
        while len(payload) <= _MAX_ENV_BYTES:
            chunk = os.read(descriptor, min(8192, _MAX_ENV_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > _MAX_ENV_BYTES:
            raise ConfigError("runtime_env_too_large")
    finally:
        os.close(descriptor)

    try:
        return bytes(payload).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError("runtime_env_not_utf8") from exc


def _literal_value(raw: str) -> str:
    if "\x00" in raw or "\r" in raw:
        raise ConfigError("runtime_env_malformed")
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1]
    if raw.startswith(("'", '"')) or raw.endswith(("'", '"')):
        raise ConfigError("runtime_env_malformed")
    if any(character.isspace() for character in raw):
        raise ConfigError("runtime_env_malformed")
    return raw


def _database_values(payload: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in payload.splitlines():
        if not line or line.startswith("#"):
            continue
        if line != line.strip():
            raise ConfigError("runtime_env_malformed")
        match = _ASSIGNMENT_RE.fullmatch(line)
        if match is None:
            raise ConfigError("runtime_env_malformed")
        name, raw = match.groups()
        if name not in _DATABASE_KEYS:
            # Unknown backend keys are checked as dotenv but never loaded.
            continue
        if name in values:
            raise ConfigError("runtime_env_duplicate_database_key")
        values[name] = _literal_value(raw)

    if values.get("QS_DATABASE_ENABLED", "").lower() != "true":
        raise ConfigError("database_not_enabled")
    if not values.get("QS_DATABASE_URL"):
        raise ConfigError("database_url_missing")
    if values.get("QS_DATABASE_AUTO_MIGRATE", "false").lower() not in {
        "false",
        "0",
        "no",
        "off",
    }:
        raise ConfigError("database_auto_migrate_forbidden")

    timeout = values.get("QS_DATABASE_CONNECT_TIMEOUT_SECONDS")
    if timeout is not None:
        try:
            parsed_timeout = int(timeout)
        except ValueError as exc:
            raise ConfigError("database_connect_timeout_invalid") from exc
        if not 1 <= parsed_timeout <= 60:
            raise ConfigError("database_connect_timeout_invalid")
        values["QS_DATABASE_CONNECT_TIMEOUT_SECONDS"] = str(parsed_timeout)
    return values


def _resolve_database_url(value: str) -> str:
    if value == _KEYCHAIN_DATABASE_URL:
        account = pwd.getpwuid(os.geteuid()).pw_name
        try:
            resolved = subprocess.run(
                [
                    "/usr/bin/security",
                    "find-generic-password",
                    "-w",
                    "-s",
                    "ai-quant-platform-agent-v02-db",
                    "-a",
                    account,
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ConfigError("database_keychain_unavailable") from exc
        password = resolved.stdout.rstrip("\n")
        if (
            resolved.returncode != 0
            or resolved.stderr
            or not password
            or any(character.isspace() for character in password)
            or len(password.encode("utf-8")) > 1024
        ):
            raise ConfigError("database_keychain_unavailable")
        value = (
            f"postgresql://quant_app_runtime:{password}@127.0.0.1:5432/quantplatform"
        )
    elif "$" in value or "`" in value or "\\" in value:
        # Only the exact fixed Keychain template above is resolvable.
        raise ConfigError("database_url_shell_syntax_forbidden")

    if len(value.encode("utf-8")) > _MAX_DATABASE_URL_BYTES:
        raise ConfigError("database_url_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("database_url_invalid") from exc
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is None
        or parsed.password is None
        or port is None
        or not parsed.path
        or parsed.path == "/"
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError("database_url_invalid")
    return value


def _child_environment(values: dict[str, str]) -> dict[str, str]:
    child = {key: os.environ[key] for key in _SAFE_CHILD_ENV if key in os.environ}
    child.update(
        {
            "QS_DATABASE_AUTO_MIGRATE": "false",
            "QS_DATABASE_ENABLED": "true",
            "QS_DATABASE_URL": _resolve_database_url(values["QS_DATABASE_URL"]),
            # Fixed safety rails are not loaded from the runtime env.
            "QS_DRY_RUN": "true",
            "QS_KILL_SWITCH": "true",
            "QS_LIVE_TRADING_ENABLED": "false",
            "QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED": "false",
            "QS_PAPER_TRADING": "true",
        }
    )
    timeout = values.get("QS_DATABASE_CONNECT_TIMEOUT_SECONDS")
    if timeout is not None:
        child["QS_DATABASE_CONNECT_TIMEOUT_SECONDS"] = timeout
    return child


def main() -> int:
    if (
        len(sys.argv) != 4
        or _GATE_ID_RE.fullmatch(sys.argv[1]) is None
        or _CONTEXT_ID_RE.fullmatch(sys.argv[2]) is None
        or _CONTEXT_ID_RE.fullmatch(sys.argv[3]) is None
    ):
        print("REFUSED: invalid exact paper-gate selectors", file=sys.stderr)
        return 2
    gate_id, workspace_id, platform_session_id = sys.argv[1:]

    try:
        values = _database_values(_read_runtime_env())
        child_env = _child_environment(values)
    except ConfigError as exc:
        return _fail(str(exc))

    if not _QUANT_SYSTEM.is_file() or not os.access(_QUANT_SYSTEM, os.X_OK):
        return _fail("quant_system_unavailable")
    request = json.dumps(
        {
            "gate_id": gate_id,
            "platform_session_id": platform_session_id,
            "workspace_id": workspace_id,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        completed = subprocess.run(
            [str(_QUANT_SYSTEM), "hermes", "paper-gate", "show"],
            cwd=_PLATFORM_DIR,
            env=child_env,
            input=request + "\n",
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _fail("quant_system_timeout")
    except OSError:
        return _fail("quant_system_exec_failed")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
