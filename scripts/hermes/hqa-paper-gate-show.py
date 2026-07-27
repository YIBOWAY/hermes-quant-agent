#!/usr/bin/python3
"""Non-evaluating fixed runtime port from managed Hermes to Platform.

Managed Hermes intentionally does not inherit Platform runtime credentials.
This launcher reads only an operation-specific allowlist from the fixed
owner-only Platform backend env. It never sources or evaluates that file,
never loads provider secrets, and always overwrites the trading safety rails.

The historical positional ``gate_id workspace_id platform_session_id`` form is
kept for the read-only wrapper. New callers must use one of the exact fixed
Platform argv sequences below and pass one bounded JSON document on stdin.
"""

from __future__ import annotations

import errno
import json
import os
import pwd
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

_PLATFORM_DIR = Path("__HQA_PLATFORM_DIR__")
_RUNTIME_ENV = _PLATFORM_DIR / "data" / "_runtime" / "agent-v0.2-backend.env"
_QUANT_SYSTEM = _PLATFORM_DIR / "ai-quant" / "bin" / "quant-system"
_MAX_ENV_BYTES = 64 * 1024
_MAX_DATABASE_URL_BYTES = 4096
_MAX_REQUEST_BYTES = 256 * 1024
_PAPER_GATE_TIMEOUT_SECONDS = 30.0
_VERTICAL_A_TIMEOUT_SECONDS = 120.0
_PROCESS_TERMINATE_GRACE_SECONDS = 1.0
_PROCESS_GROUP_REAP_SECONDS = 2.0
_PROCESS_GROUP_POLL_SECONDS = 0.02
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
_HERMES_GATEWAY_KEYS = frozenset(
    {
        "QS_HERMES_GATEWAY_ALLOW_EPHEMERAL_RUNS",
        "QS_HERMES_GATEWAY_API_KEY_FILE",
        "QS_HERMES_GATEWAY_BASE_URL",
        "QS_HERMES_GATEWAY_DISPATCH_TIMEOUT_SECONDS",
        "QS_HERMES_GATEWAY_ENABLED",
        "QS_HERMES_GATEWAY_MAX_MESSAGES",
        "QS_HERMES_GATEWAY_MAX_RESPONSE_BYTES",
        "QS_HERMES_GATEWAY_RUNTIME_ROOT",
        "QS_HERMES_GATEWAY_TIMEOUT_SECONDS",
    }
)
_CANDIDATE_KEYS = frozenset(
    {
        "QS_AGENT_V02_CANDIDATE_ENABLED",
        "QS_AGENT_V02_CANDIDATE_FINAL_EVIDENCE_FILE",
        "QS_AGENT_V02_CANDIDATE_PREFLIGHT_EVIDENCE_FILE",
        "QS_AGENT_V02_CANDIDATE_TTL_SECONDS",
    }
)
_RELEASE_KEYS = frozenset(
    {
        "QS_AGENT_V02_RELEASE_CAPABILITY_MAX_AGE_SECONDS",
        "QS_AGENT_V02_RELEASE_CONNECTOR_HEARTBEAT_MAX_AGE_SECONDS",
        "QS_AGENT_V02_RELEASE_EVIDENCE_FILE",
        "QS_AGENT_V02_RELEASE_WORKSPACE_ID",
    }
)
_MUTATION_KEYS = frozenset(
    {
        "QS_LOCAL_MUTATION_COMPOSER_OPEN",
        "QS_LOCAL_MUTATION_ENABLED",
    }
)
_INTENT_PAYLOAD_KEYS = frozenset(
    {
        "QS_INTENT_PAYLOAD_HQA_ROOT",
        "QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE",
        "QS_INTENT_PAYLOAD_TIMEOUT_SECONDS",
    }
)
_SAFETY_KEYS = frozenset(
    {
        "QS_DRY_RUN",
        "QS_ENVIRONMENT",
        "QS_KILL_SWITCH",
        "QS_LIVE_TRADING_ENABLED",
        "QS_NO_LIVE_TRADE_WITHOUT_MANUAL_APPROVAL",
        "QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED",
        "QS_PAPER_ACCOUNT_DB_MODE",
        "QS_PAPER_TRADING",
    }
)
_RUNTIME_KEYS = frozenset().union(
    _DATABASE_KEYS,
    _HERMES_GATEWAY_KEYS,
    _CANDIDATE_KEYS,
    _RELEASE_KEYS,
    _MUTATION_KEYS,
    _INTENT_PAYLOAD_KEYS,
    _SAFETY_KEYS,
)
_VERTICAL_A_KEYS = _RUNTIME_KEYS
_PLATFORM_CONTEXT_KEYS = frozenset(
    {
        "HERMES_PLATFORM_COMMAND_ID",
        "HERMES_PLATFORM_MANAGED_SESSION_ID",
        "HERMES_PLATFORM_RUN_ID",
        "HERMES_PLATFORM_SESSION_ID",
    }
)
_PAPER_GATE_OPERATIONS = frozenset(
    {"attest-run", "complete", "list", "register", "show"}
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


def _runtime_values(payload: str) -> dict[str, str]:
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
        if name not in _RUNTIME_KEYS:
            # Unknown backend keys are checked as dotenv but never loaded.
            continue
        if name in values:
            raise ConfigError("runtime_env_duplicate_key")
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


def _child_environment(
    values: dict[str, str],
    *,
    selected_keys: frozenset[str],
    include_platform_context: bool,
) -> dict[str, str]:
    child = {key: os.environ[key] for key in _SAFE_CHILD_ENV if key in os.environ}
    child.update(
        {
            key: values[key]
            for key in selected_keys
            if key in values and key not in _DATABASE_KEYS
        }
    )
    if include_platform_context:
        child.update(
            {
                key: os.environ[key]
                for key in _PLATFORM_CONTEXT_KEYS
                if key in os.environ
            }
        )
    child.update(
        {
            "QS_DATABASE_AUTO_MIGRATE": "false",
            "QS_DATABASE_ENABLED": "true",
            "QS_DATABASE_URL": _resolve_database_url(values["QS_DATABASE_URL"]),
            # Fixed safety rails are not loaded from the runtime env.
            "QS_DRY_RUN": "true",
            "QS_KILL_SWITCH": "true",
            "QS_LIVE_TRADING_ENABLED": "false",
            "QS_NO_LIVE_TRADE_WITHOUT_MANUAL_APPROVAL": "true",
            "QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED": "false",
            "QS_PAPER_TRADING": "true",
        }
    )
    timeout = values.get("QS_DATABASE_CONNECT_TIMEOUT_SECONDS")
    if timeout is not None:
        child["QS_DATABASE_CONNECT_TIMEOUT_SECONDS"] = timeout
    return child


def _read_request() -> bytes:
    request = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
    if len(request) > _MAX_REQUEST_BYTES:
        raise ConfigError("request_too_large")
    return request


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate, kill, and reap one isolated Platform invocation."""

    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        pass

    try:
        process.wait(timeout=_PROCESS_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass

    # Always follow the grace interval with SIGKILL when the group still
    # exists. The direct process may have exited while a descendant ignored
    # SIGTERM, so checking only process.poll() would leak that descendant.
    if _process_group_exists(process_group_id):
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass

    if process.poll() is None:
        try:
            process.wait(timeout=_PROCESS_GROUP_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            # Defensive direct-child fallback; start_new_session means the
            # group SIGKILL above should normally make this unreachable.
            process.kill()
            process.wait(timeout=_PROCESS_GROUP_REAP_SECONDS)

    deadline = time.monotonic() + _PROCESS_GROUP_REAP_SECONDS
    while _process_group_exists(process_group_id) and time.monotonic() < deadline:
        time.sleep(_PROCESS_GROUP_POLL_SECONDS)


def _run_platform(
    argv: list[str],
    *,
    request: bytes,
    selected_keys: frozenset[str],
    include_platform_context: bool,
    timeout_seconds: float,
) -> int:
    try:
        values = _runtime_values(_read_runtime_env())
        child_env = _child_environment(
            values,
            selected_keys=selected_keys,
            include_platform_context=include_platform_context,
        )
    except ConfigError as exc:
        return _fail(str(exc))

    if not _QUANT_SYSTEM.is_file() or not os.access(_QUANT_SYSTEM, os.X_OK):
        return _fail("quant_system_unavailable")
    try:
        process = subprocess.Popen(
            [str(_QUANT_SYSTEM), *argv],
            cwd=_PLATFORM_DIR,
            env=child_env,
            stdin=subprocess.PIPE,
            start_new_session=True,
        )
        process.communicate(input=request, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        return _fail("quant_system_timeout")
    except OSError:
        return _fail("quant_system_exec_failed")
    return int(process.returncode)


def main() -> int:
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "hermes":
        if (
            len(arguments) == 3
            and arguments[:2] == ["hermes", "paper-gate"]
            and arguments[2] in _PAPER_GATE_OPERATIONS
        ):
            try:
                request = _read_request()
            except ConfigError as exc:
                return _fail(str(exc))
            selected_keys = _DATABASE_KEYS
            if arguments[2] == "attest-run":
                selected_keys = selected_keys | _HERMES_GATEWAY_KEYS
            return _run_platform(
                arguments,
                request=request,
                selected_keys=selected_keys,
                include_platform_context=False,
                timeout_seconds=_PAPER_GATE_TIMEOUT_SECONDS,
            )

        if arguments == ["hermes", "vertical-a", "execute-from-hermes"]:
            try:
                request = _read_request()
            except ConfigError as exc:
                return _fail(str(exc))
            return _run_platform(
                arguments,
                request=request,
                selected_keys=_VERTICAL_A_KEYS,
                include_platform_context=True,
                timeout_seconds=_VERTICAL_A_TIMEOUT_SECONDS,
            )

        print("REFUSED: invalid fixed runtime port invocation", file=sys.stderr)
        return 2

    if (
        len(arguments) == 3
        and _GATE_ID_RE.fullmatch(arguments[0]) is not None
        and _CONTEXT_ID_RE.fullmatch(arguments[1]) is not None
        and _CONTEXT_ID_RE.fullmatch(arguments[2]) is not None
    ):
        gate_id, workspace_id, platform_session_id = arguments
        request = (
            json.dumps(
                {
                    "gate_id": gate_id,
                    "platform_session_id": platform_session_id,
                    "workspace_id": workspace_id,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        return _run_platform(
            ["hermes", "paper-gate", "show"],
            request=request,
            selected_keys=_DATABASE_KEYS,
            include_platform_context=False,
            timeout_seconds=_PAPER_GATE_TIMEOUT_SECONDS,
        )

    print("REFUSED: invalid fixed runtime port invocation", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
