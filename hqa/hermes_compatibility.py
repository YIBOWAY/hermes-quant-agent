"""Deterministic post-update compatibility watcher for local Hermes.

The public interface is deliberately small: callers provide a frozen
``CompatibilityConfig`` and receive a ``CompatibilityResult`` from
``check_compatibility``.  The implementation owns re-probe identity collection,
loopback-only GET probes, strict response validation, canonical evidence,
locking, and fail-closed baseline management.

This module never imports Hermes, reads its API key, invokes a model/provider,
or performs an HTTP mutation. A successful re-probe baseline suppresses all
HTTP traffic until the Hermes checkout, watcher contract, or an HQA/platform
re-probe trigger digest changes. Those file digests trigger observation; they
are not source or runtime attestation.
"""

from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)


HQA_REPROBE_TRIGGER_FILES: Tuple[str, ...] = (
    "config/hermes-gateway-capabilities.v1.json",
    "hqa/agent_workspace_actions.py",
    "hqa/agent_workspace_contract.py",
    "hqa/agent_workspace_model.py",
    "hqa/agent_workspace_security.py",
    "hqa/agent_workspace_states.py",
    "hqa/hermes_run_adapter.py",
)

PLATFORM_REPROBE_TRIGGER_FILES: Tuple[str, ...] = (
    "src/quant_system/api/routes/health.py",
    "src/quant_system/api/routes/hermes.py",
    "src/quant_system/api/safety/middleware.py",
    "src/quant_system/api/schemas/hermes.py",
    "src/quant_system/hermes/gateway_client.py",
)

WATCHER_CONTRACT_FILES: Tuple[str, ...] = (
    "hqa/hermes_compatibility.py",
    "hqa/hermes_compatibility_cli.py",
    "config/hermes-cron.v1.json",
    "scripts/hermes/hqa-hermes-compatibility-watch.sh",
)

_HEX_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_REPORT_SCHEMA_VERSION = 1
_BASELINE_SCHEMA_VERSION = 1
_REPORT_RETENTION = 128
_REPORT_NAME_RE = re.compile(r"([0-9a-f]{64})\.json\Z")
_PROBES: Tuple[Tuple[str, str, str], ...] = (
    ("hermes_health", "hermes", "/health"),
    ("platform_health", "platform", "/api/health"),
    ("platform_gateway", "platform", "/api/hermes/gateway"),
    (
        "platform_sessions",
        "platform",
        "/api/hermes/sessions?limit=1&offset=0",
    ),
)
_EXPECTED_SAFETY = {
    "dry_run": True,
    "paper_trading": True,
    "live_trading_enabled": False,
    "kill_switch": True,
}


class CompatibilityError(RuntimeError):
    """Fail-closed compatibility or local-evidence failure."""


@dataclass(frozen=True)
class CompatibilityConfig:
    hqa_repo: Path
    platform_repo: Path
    hermes_repo: Path
    state_dir: Path
    hermes_base_url: str = "http://127.0.0.1:8642"
    platform_base_url: str = "http://127.0.0.1:8765"
    hermes_cli_path: Path = field(
        default_factory=lambda: Path.home() / ".local" / "bin" / "hermes"
    )
    timeout_seconds: float = 2.0
    max_response_bytes: int = 65_536

    def __post_init__(self) -> None:
        for field_name in (
            "hqa_repo",
            "platform_repo",
            "hermes_repo",
            "state_dir",
            "hermes_cli_path",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, (str, Path)):
                raise TypeError(f"{field_name} must be path-like")
            object.__setattr__(self, field_name, Path(value))
        _validate_loopback_base_url(self.hermes_base_url, "hermes_base_url")
        _validate_loopback_base_url(self.platform_base_url, "platform_base_url")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(
            self.timeout_seconds, bool
        ):
            raise TypeError("timeout_seconds must be numeric")
        if not 0.05 <= float(self.timeout_seconds) <= 10.0:
            raise ValueError("timeout_seconds must be between 0.05 and 10 seconds")
        if (
            not isinstance(self.max_response_bytes, int)
            or isinstance(self.max_response_bytes, bool)
            or not 1_024 <= self.max_response_bytes <= 1_048_576
        ):
            raise ValueError("max_response_bytes must be between 1024 and 1048576")


@dataclass(frozen=True)
class CompatibilityResult:
    status: str
    probed: bool
    reason: str
    trigger_digest: Optional[str]
    report_digest: Optional[str]
    report_path: Optional[Path]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        raise HTTPError(req.full_url, code, "redirect refused", headers, fp)


def _validate_loopback_base_url(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(f"{field} must be a bounded URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.hostname is None
        or parsed.port is None
    ):
        raise ValueError(f"{field} must be an explicit loopback http origin")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError(f"{field} must use a numeric loopback address") from exc
    if not address.is_loopback:
        raise ValueError(f"{field} must use a loopback address")
    return value.rstrip("/")


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompatibilityError("evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _secure_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise CompatibilityError("state path must be a physical directory")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise CompatibilityError("state directory must be owned by the current user")
    os.chmod(path, 0o700)


def _open_nofollow(path: Path, flags: int, mode: int = 0o600) -> int:
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(str(path), flags, mode)
    except OSError as exc:
        raise CompatibilityError("secure state file access failed") from exc


def _read_json_file(path: Path, *, maximum: int = 1_048_576) -> Any:
    fd = _open_nofollow(path, os.O_RDONLY)
    try:
        chunks: List[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    finally:
        os.close(fd)
    if len(payload) > maximum:
        raise CompatibilityError("state file exceeds size limit")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompatibilityError("state file is not valid JSON") from exc


def _atomic_write(path: Path, payload: bytes) -> None:
    _secure_directory(path.parent)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        written = 0
        while written < len(payload):
            written += os.write(fd, payload[written:])
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(str(temporary), str(path))
        os.chmod(path, 0o600)
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _git_output(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            timeout=5.0,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompatibilityError("Hermes checkout identity is unavailable") from exc


def _contract_digest(repo: Path, paths: Iterable[str]) -> str:
    hasher = hashlib.sha256()
    root = repo.resolve(strict=True)
    for relative in paths:
        path = repo / relative
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_file() or path.is_symlink():
                raise CompatibilityError("contract path is not a physical file")
            payload = resolved.read_bytes()
        except (OSError, ValueError) as exc:
            raise CompatibilityError("critical contract is unavailable") from exc
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(hashlib.sha256(payload).digest())
        hasher.update(b"\0")
    return hasher.hexdigest()


def _collect_reprobe_identity(
    config: CompatibilityConfig,
) -> Tuple[Dict[str, Any], List[str]]:
    blockers: List[str] = []
    try:
        head = (
            _git_output(config.hermes_repo, "rev-parse", "HEAD").decode("ascii").strip()
        )
        tree = (
            _git_output(config.hermes_repo, "rev-parse", "HEAD^{tree}")
            .decode("ascii")
            .strip()
        )
        if _HEX_OID.fullmatch(head) is None or _HEX_OID.fullmatch(tree) is None:
            raise CompatibilityError(
                "Hermes checkout returned a non-canonical object ID"
            )
        tracked_status = _git_output(
            config.hermes_repo,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=no",
        )
    except (UnicodeDecodeError, CompatibilityError):
        head = "unavailable"
        tree = "unavailable"
        tracked_status = b""
        blockers.append("hermes_checkout_identity_unavailable")

    try:
        hqa_digest = _contract_digest(config.hqa_repo, HQA_REPROBE_TRIGGER_FILES)
    except CompatibilityError:
        hqa_digest = "unavailable"
        blockers.append("hqa_reprobe_trigger_unavailable")
    try:
        platform_digest = _contract_digest(
            config.platform_repo, PLATFORM_REPROBE_TRIGGER_FILES
        )
    except CompatibilityError:
        platform_digest = "unavailable"
        blockers.append("platform_reprobe_trigger_unavailable")
    try:
        watcher_digest = _contract_digest(config.hqa_repo, WATCHER_CONTRACT_FILES)
    except CompatibilityError:
        watcher_digest = "unavailable"
        blockers.append("watcher_contract_unavailable")

    if tracked_status:
        blockers.append("hermes_tracked_checkout_dirty")

    reprobe_identity = {
        "schema_version": 1,
        "hermes": {
            "checkout_head": head,
            "checkout_tree": tree,
            "tracked_status_digest": hashlib.sha256(tracked_status).hexdigest(),
            "tracked_worktree_clean": not bool(tracked_status),
        },
        "reprobe_triggers": {
            "hqa_trigger_digest": hqa_digest,
            "platform_trigger_digest": platform_digest,
            "watcher_contract_digest": watcher_digest,
        },
    }
    return reprobe_identity, sorted(set(blockers))


def _expect_exact_keys(value: Any, keys: Iterable[str], label: str) -> Dict[str, Any]:
    if type(value) is not dict or set(value) != set(keys):
        raise CompatibilityError(f"{label}_schema")
    return value


def _validate_safety(value: Any) -> None:
    safety = _expect_exact_keys(
        value,
        (*_EXPECTED_SAFETY.keys(), "bind_address"),
        "safety",
    )
    for key, expected in _EXPECTED_SAFETY.items():
        if safety[key] is not expected:
            raise CompatibilityError(f"safety_{key}_drift")
    if safety["bind_address"] not in ("127.0.0.1", "::1"):
        raise CompatibilityError("safety_bind_address_drift")


def _validate_hermes_health(value: Any) -> None:
    health = _expect_exact_keys(
        value, ("status", "platform", "version"), "hermes_health"
    )
    if (
        health["status"] != "ok"
        or health["platform"] != "hermes-agent"
        or not isinstance(health["version"], str)
        or not health["version"]
        or len(health["version"]) > 128
    ):
        raise CompatibilityError("hermes_health_contract_drift")


def _validate_platform_health(value: Any) -> None:
    health = _expect_exact_keys(
        value,
        (
            "status",
            "app_name",
            "environment",
            "data_provider",
            "futu_opend",
            "database",
            "hermes_command_ledger",
            "safety",
        ),
        "platform_health",
    )
    if health["status"] != "ok":
        raise CompatibilityError("platform_health_status_drift")
    for key in ("app_name", "environment"):
        if (
            not isinstance(health[key], str)
            or not health[key]
            or len(health[key]) > 256
        ):
            raise CompatibilityError("platform_health_schema")
    for key in ("data_provider", "futu_opend", "database", "hermes_command_ledger"):
        if type(health[key]) is not dict:
            raise CompatibilityError("platform_health_schema")

    provider = health["data_provider"]
    if (
        set(provider) != {"configured_default", "tiingo_token_present"}
        or not isinstance(provider["configured_default"], str)
        or not 0 < len(provider["configured_default"]) <= 64
        or type(provider["tiingo_token_present"]) is not bool
    ):
        raise CompatibilityError("platform_health_schema")

    _validate_dependency_health(health["futu_opend"], "futu_opend")
    _validate_dependency_health(health["database"], "database")

    ledger = health["hermes_command_ledger"]
    if set(ledger) != {
        "database_configured",
        "schema_ready",
        "schema_version",
        "workflow_binding_schema_ready",
        "workflow_binding_schema_version",
        "mutation_enabled",
    }:
        raise CompatibilityError("platform_health_schema")
    for key in (
        "database_configured",
        "schema_ready",
        "workflow_binding_schema_ready",
        "mutation_enabled",
    ):
        if type(ledger[key]) is not bool:
            raise CompatibilityError("platform_health_schema")
    for ready_key, version_key in (
        ("schema_ready", "schema_version"),
        ("workflow_binding_schema_ready", "workflow_binding_schema_version"),
    ):
        version = ledger[version_key]
        if ledger[ready_key] is not (
            type(version) is int and not isinstance(version, bool) and version >= 1
        ):
            raise CompatibilityError("platform_health_schema")
    if ledger["mutation_enabled"] is not False:
        raise CompatibilityError("platform_mutation_enabled_drift")
    _validate_safety(health["safety"])


def _validate_dependency_health(value: Dict[str, Any], label: str) -> None:
    enabled = value.get("enabled")
    if type(enabled) is not bool:
        raise CompatibilityError("platform_health_schema")
    if enabled is False:
        if set(value) != {"enabled"}:
            raise CompatibilityError("platform_health_schema")
        return
    common = {"enabled", "reachable", "error"}
    expected = common | ({"host", "port"} if label == "futu_opend" else set())
    if set(value) != expected or type(value["reachable"]) is not bool:
        raise CompatibilityError("platform_health_schema")
    error = value["error"]
    if error is not None and (not isinstance(error, str) or len(error) > 500):
        raise CompatibilityError("platform_health_schema")
    if value["reachable"] is True and error is not None:
        raise CompatibilityError("platform_health_schema")
    if label == "futu_opend" and (
        not isinstance(value["host"], str)
        or not 0 < len(value["host"]) <= 255
        or type(value["port"]) is not int
        or not 1 <= value["port"] <= 65_535
    ):
        raise CompatibilityError("platform_health_schema")


def _strings(value: Any, maximum: int = 32) -> bool:
    return (
        type(value) is list
        and len(value) <= maximum
        and all(isinstance(item, str) and 0 < len(item) <= 256 for item in value)
    )


def _validate_gateway(value: Any) -> None:
    gateway = _expect_exact_keys(
        value,
        (
            "read_status",
            "connected",
            "model",
            "session_api_available",
            "chat_write_ready",
            "features",
            "upstream_blockers",
            "platform_delivery_blockers",
            "blockers",
            "warnings",
            "safety",
        ),
        "platform_gateway",
    )
    features = gateway["features"]
    if (
        gateway["read_status"] != "available"
        or gateway["connected"] is not True
        or gateway["session_api_available"] is not True
        or gateway["chat_write_ready"] is not False
        or type(features) is not dict
        or features.get("session_resources") is not True
        or not all(
            isinstance(key, str) and type(item) is bool
            for key, item in features.items()
        )
        or not _strings(gateway["upstream_blockers"])
        or not _strings(gateway["platform_delivery_blockers"])
        or not _strings(gateway["blockers"])
        or type(gateway["warnings"]) is not list
        or gateway["warnings"]
    ):
        raise CompatibilityError("platform_gateway_contract_drift")
    if gateway["model"] is not None and not isinstance(gateway["model"], str):
        raise CompatibilityError("platform_gateway_schema")
    _validate_safety(gateway["safety"])


def _optional_text(value: Any, maximum: int) -> bool:
    return value is None or (isinstance(value, str) and len(value) <= maximum)


def _validate_sessions(value: Any) -> None:
    response = _expect_exact_keys(
        value,
        (
            "read_status",
            "sessions",
            "limit",
            "offset",
            "has_more",
            "warnings",
            "safety",
        ),
        "platform_sessions",
    )
    if (
        response["read_status"] != "available"
        or type(response["sessions"]) is not list
        or len(response["sessions"]) > 1
        or response["limit"] != 1
        or response["offset"] != 0
        or type(response["has_more"]) is not bool
        or type(response["warnings"]) is not list
        or response["warnings"]
    ):
        raise CompatibilityError("platform_sessions_contract_drift")
    expected_summary_keys = {
        "id",
        "title",
        "source",
        "model",
        "message_count",
        "last_active",
        "preview",
        "parent_session_id",
        "ended_at",
    }
    for summary in response["sessions"]:
        if type(summary) is not dict or set(summary) != expected_summary_keys:
            raise CompatibilityError("platform_sessions_schema")
        if not isinstance(summary["id"], str) or not 0 < len(summary["id"]) <= 256:
            raise CompatibilityError("platform_sessions_schema")
        if not all(
            _optional_text(summary[key], 1_000)
            for key in (
                "title",
                "source",
                "model",
                "last_active",
                "preview",
                "parent_session_id",
                "ended_at",
            )
        ):
            raise CompatibilityError("platform_sessions_schema")
        if summary["message_count"] is not None and (
            type(summary["message_count"]) is not int or summary["message_count"] < 0
        ):
            raise CompatibilityError("platform_sessions_schema")
    _validate_safety(response["safety"])


_VALIDATORS = {
    "hermes_health": _validate_hermes_health,
    "platform_health": _validate_platform_health,
    "platform_gateway": _validate_gateway,
    "platform_sessions": _validate_sessions,
}


def _request_json(url: str, config: CompatibilityConfig) -> Any:
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    request = Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "hqa-compatibility/1"},
    )
    try:
        with opener.open(request, timeout=float(config.timeout_seconds)) as response:
            if response.status != 200:
                raise CompatibilityError("http_status")
            content_type = response.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise CompatibilityError("content_type")
            body = response.read(config.max_response_bytes + 1)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise CompatibilityError("redirect_refused") from exc
        raise CompatibilityError("http_status") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise CompatibilityError("network_unavailable") from exc
    if len(body) > config.max_response_bytes:
        raise CompatibilityError("response_too_large")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompatibilityError("invalid_json") from exc


def _run_probes(config: CompatibilityConfig) -> Tuple[List[Dict[str, Any]], List[str]]:
    results: List[Dict[str, Any]] = []
    blockers: List[str] = []
    service_result, service_blocker = _probe_gateway_service(config)
    results.append(service_result)
    if service_blocker is not None:
        blockers.append(service_blocker)
    bases = {
        "hermes": _validate_loopback_base_url(
            config.hermes_base_url, "hermes_base_url"
        ),
        "platform": _validate_loopback_base_url(
            config.platform_base_url, "platform_base_url"
        ),
    }
    for name, target, path in _PROBES:
        try:
            payload = _request_json(bases[target] + path, config)
            _VALIDATORS[name](payload)
            results.append({"name": name, "method": "GET", "ok": True})
        except CompatibilityError as exc:
            code = str(exc)
            if not re.fullmatch(r"[a-z0-9_]{1,64}", code):
                code = "probe_failed"
            results.append(
                {"name": name, "method": "GET", "ok": False, "error_code": code}
            )
            blockers.append(f"{name}:{code}")
    return results, blockers


def _probe_gateway_service(
    config: CompatibilityConfig,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Run the one fixed, read-only Hermes service-status command.

    Only a bounded classification is returned.  The command output (which may
    contain a PID, paths, or remediation advice) is never persisted.
    """

    path = config.hermes_cli_path
    try:
        info = path.lstat()
        if (
            not path.is_absolute()
            or stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or not os.access(path, os.X_OK)
        ):
            raise CompatibilityError("gateway_service_status_unavailable")
        safe_environment = {
            key: os.environ[key]
            for key in ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
            if key in os.environ
        }
        safe_environment["PYTHONNOUSERSITE"] = "1"
        completed = subprocess.run(
            [str(path), "gateway", "status"],
            check=False,
            cwd=str(config.hermes_repo),
            env=safe_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=float(config.timeout_seconds),
        )
        output = completed.stdout
        if completed.returncode != 0 or len(output) > 32_768:
            raise CompatibilityError("gateway_service_status_unavailable")
        text = output.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError, CompatibilityError):
        code = "gateway_service_status_unavailable"
        return (
            {
                "name": "gateway_service_status",
                "method": "LOCAL",
                "ok": False,
                "error_code": code,
            },
            code,
        )

    if "Service definition is stale relative to the current Hermes install" in text:
        code = "gateway_service_definition_stale"
        return (
            {
                "name": "gateway_service_status",
                "method": "LOCAL",
                "ok": False,
                "error_code": code,
            },
            code,
        )
    if "Gateway is supervised by launchd" not in text:
        code = "gateway_service_unsupervised"
        return (
            {
                "name": "gateway_service_status",
                "method": "LOCAL",
                "ok": False,
                "error_code": code,
            },
            code,
        )
    return {"name": "gateway_service_status", "method": "LOCAL", "ok": True}, None


def _load_baseline(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        value = _read_json_file(path, maximum=65_536)
    except CompatibilityError:
        return None
    if (
        type(value) is not dict
        or set(value)
        != {
            "schema_version",
            "trigger_digest",
            "report_digest",
            "report_file",
        }
        or value["schema_version"] != _BASELINE_SCHEMA_VERSION
        or not isinstance(value["trigger_digest"], str)
        or not isinstance(value["report_digest"], str)
        or not isinstance(value["report_file"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["trigger_digest"]) is None
        or re.fullmatch(r"[0-9a-f]{64}", value["report_digest"]) is None
        or value["report_file"] != f"reports/{value['report_digest']}.json"
    ):
        return None
    report_path = path.parent / value["report_file"]
    try:
        report = _read_json_file(report_path, maximum=1_048_576)
    except CompatibilityError:
        return None
    expected_report_keys = {
        "schema_version",
        "checked_at",
        "status",
        "trigger_digest",
        "reprobe_identity",
        "probes",
        "blockers",
        "report_digest",
    }
    if (
        type(report) is not dict
        or set(report) != expected_report_keys
        or report["schema_version"] != _REPORT_SCHEMA_VERSION
        or report["status"] != "compatible"
        or report["trigger_digest"] != value["trigger_digest"]
        or report["report_digest"] != value["report_digest"]
        or report["blockers"] != []
        or type(report["probes"]) is not list
        or type(report["reprobe_identity"]) is not dict
    ):
        return None
    basis = {key: item for key, item in report.items() if key != "report_digest"}
    if _digest(basis) != value["report_digest"]:
        return None
    return value


def _write_report(
    config: CompatibilityConfig,
    *,
    reprobe_identity: Dict[str, Any],
    trigger_digest: str,
    status: str,
    probes: List[Dict[str, Any]],
    blockers: List[str],
    protected_report_digests: Iterable[str] = (),
) -> Tuple[str, Path]:
    basis = {
        "schema_version": _REPORT_SCHEMA_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "trigger_digest": trigger_digest,
        "reprobe_identity": reprobe_identity,
        "probes": probes,
        "blockers": sorted(set(blockers)),
    }
    report_digest = _digest(basis)
    report = dict(basis, report_digest=report_digest)
    reports_dir = config.state_dir / "reports"
    _secure_directory(reports_dir)
    path = reports_dir / f"{report_digest}.json"
    _atomic_write(path, _canonical_bytes(report))
    _atomic_write(config.state_dir / "latest.json", _canonical_bytes(report))
    _prune_reports(
        reports_dir,
        protected_digests={*protected_report_digests, report_digest},
    )
    return report_digest, path


def _prune_reports(reports_dir: Path, *, protected_digests: Iterable[str]) -> None:
    """Retain at most 128 owned, regular, canonically named reports.

    Symlinks, directories, foreign-owned entries and non-canonical names are
    never followed or removed. The current report and last-good baseline report
    are protected even when they are among the oldest entries.
    """

    protected = set(protected_digests)
    candidates: List[Tuple[int, str, str, Path]] = []
    try:
        entries = list(reports_dir.iterdir())
    except OSError:
        return
    current_uid = os.getuid() if hasattr(os, "getuid") else None
    for entry in entries:
        match = _REPORT_NAME_RE.fullmatch(entry.name)
        if match is None:
            continue
        try:
            info = entry.lstat()
        except OSError:
            continue
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or (current_uid is not None and info.st_uid != current_uid)
        ):
            continue
        candidates.append((info.st_mtime_ns, entry.name, match.group(1), entry))

    excess = len(candidates) - _REPORT_RETENTION
    if excess <= 0:
        return
    for _mtime, _name, digest, entry in sorted(candidates):
        if excess <= 0:
            break
        if digest in protected:
            continue
        try:
            info = entry.lstat()
            if (
                _REPORT_NAME_RE.fullmatch(entry.name) is None
                or stat.S_ISLNK(info.st_mode)
                or not stat.S_ISREG(info.st_mode)
                or (current_uid is not None and info.st_uid != current_uid)
            ):
                continue
            entry.unlink()
        except OSError:
            continue
        excess -= 1


def check_compatibility(config: CompatibilityConfig) -> CompatibilityResult:
    """Check local Hermes/platform read compatibility and preserve the last good baseline.

    A matching successful trigger identity returns without any HTTP request.
    Changed or previously failed trigger identities execute four bounded,
    loopback-only GET
    probes.  Failed checks write evidence but never replace ``baseline.json``.
    """

    if not isinstance(config, CompatibilityConfig):
        raise TypeError("config must be CompatibilityConfig")
    _secure_directory(config.state_dir)
    lock_path = config.state_dir / "watch.lock"
    lock_fd = _open_nofollow(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return CompatibilityResult(
                status="busy",
                probed=False,
                reason="another_check_is_running",
                trigger_digest=None,
                report_digest=None,
                report_path=None,
            )

        reprobe_identity, trigger_blockers = _collect_reprobe_identity(config)
        trigger_digest = _digest(reprobe_identity)
        baseline = _load_baseline(config.state_dir / "baseline.json")
        if (
            not trigger_blockers
            and baseline is not None
            and baseline["trigger_digest"] == trigger_digest
        ):
            report_path = config.state_dir / baseline["report_file"]
            return CompatibilityResult(
                status="compatible",
                probed=False,
                reason="unchanged_successful_baseline",
                trigger_digest=trigger_digest,
                report_digest=baseline["report_digest"],
                report_path=report_path,
            )

        probes, probe_blockers = _run_probes(config)
        blockers = sorted(set((*trigger_blockers, *probe_blockers)))
        status = "compatible" if not blockers else "incompatible"
        report_digest, report_path = _write_report(
            config,
            reprobe_identity=reprobe_identity,
            trigger_digest=trigger_digest,
            status=status,
            probes=probes,
            blockers=blockers,
            protected_report_digests=(
                (baseline["report_digest"],) if baseline is not None else ()
            ),
        )
        if status == "compatible":
            baseline_payload = {
                "schema_version": _BASELINE_SCHEMA_VERSION,
                "trigger_digest": trigger_digest,
                "report_digest": report_digest,
                "report_file": f"reports/{report_digest}.json",
            }
            _atomic_write(
                config.state_dir / "baseline.json",
                _canonical_bytes(baseline_payload),
            )
        return CompatibilityResult(
            status=status,
            probed=True,
            reason="trigger_changed_or_unverified",
            trigger_digest=trigger_digest,
            report_digest=report_digest,
            report_path=report_path,
        )
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


__all__ = [
    "CompatibilityConfig",
    "CompatibilityError",
    "CompatibilityResult",
    "HQA_REPROBE_TRIGGER_FILES",
    "PLATFORM_REPROBE_TRIGGER_FILES",
    "WATCHER_CONTRACT_FILES",
    "check_compatibility",
]
