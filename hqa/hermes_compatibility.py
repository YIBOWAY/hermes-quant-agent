"""Deterministic post-update compatibility watcher for local Hermes.

The public interface is deliberately small: callers provide a frozen
``CompatibilityConfig`` and receive a ``CompatibilityResult`` from
``check_compatibility``.  The implementation owns re-probe identity collection,
loopback-only GET probes, strict response validation, canonical evidence,
locking, and fail-closed baseline management.

This module never imports Hermes, invokes a model/provider, or performs an HTTP
mutation.  The stronger ``local_agent_v0_2`` profile may read one owner-only
Hermes API-key file solely to authenticate ``GET /v1/capabilities``; the key is
never persisted or printed. A successful re-probe baseline suppresses all HTTP
traffic until the profile, Hermes checkout, shared Platform manifest, watcher
contract, or an HQA/platform re-probe trigger digest changes. Those file
digests trigger observation; they are not source or runtime attestation.
"""

from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import math
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
    "hqa/hermes_run_cli.py",
    "hqa/hermes_managed_session.py",
)

PLATFORM_REPROBE_TRIGGER_FILES: Tuple[str, ...] = (
    "src/quant_system/api/routes/health.py",
    "src/quant_system/api/routes/hermes.py",
    "src/quant_system/api/safety/middleware.py",
    "src/quant_system/api/schemas/hermes.py",
    "src/quant_system/hermes/gateway_client.py",
)
PLATFORM_LOCAL_AGENT_TRIGGER_FILES: Tuple[str, ...] = (
    "src/quant_system/hermes/agent_v02_hermes_compatibility.v1.json",
    "src/quant_system/config/runtime_paths.py",
    "src/quant_system/config/settings.py",
    "src/quant_system/hermes/candidate_admission_authority.py",
    "src/quant_system/hermes/candidate_admission_gate.py",
    "src/quant_system/hermes/command_ledger.py",
    "src/quant_system/hermes/composer_readiness.py",
    "src/quant_system/hermes/connector_liveness.py",
    "src/quant_system/hermes/dark_identity_profile.py",
    "src/quant_system/hermes/effective_release_gate.py",
    "src/quant_system/hermes/release_authority.py",
    "src/quant_system/hermes/release_runtime.py",
    "src/quant_system/hermes/run_control_outcome_authority.py",
    "src/quant_system/hermes/session_registry.py",
    "src/quant_system/hermes/test_execution_evidence.py",
    "src/quant_system/hermes/workflow_binding.py",
    "src/quant_system/storage/database.py",
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
_PROFILES = frozenset({"dark_readonly", "local_agent_v0_2"})
_PLATFORM_CONTRACT_RELATIVE_PATH = (
    "src/quant_system/hermes/agent_v02_hermes_compatibility.v1.json"
)
_BOUNDED_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_EVENT_CURSOR = 2**63 - 1
_MAX_CONNECTOR_AGE_SECONDS = 10 * 366 * 24 * 60 * 60
_MAX_READY_CONNECTOR_AGE_SECONDS = 300.0
_CONNECTOR_REASON_VALUES = frozenset(
    {
        "connector_generation_missing",
        "connector_not_active",
        "connector_mode_not_supervised",
        "connector_runtime_digest_mismatch",
        "connector_heartbeat_in_future",
        "connector_heartbeat_stale",
        "connector_session_lock_missing",
        "connector_liveness_unavailable",
        "ready",
    }
)
_LEGACY_LEDGER_KEYS = frozenset(
    {
        "database_configured",
        "schema_ready",
        "schema_version",
        "workflow_binding_schema_ready",
        "workflow_binding_schema_version",
        "mutation_enabled",
    }
)
_LOCAL_LEDGER_KEYS = _LEGACY_LEDGER_KEYS | {
    "session_registry_schema_ready",
    "session_registry_schema_version",
    "agent_workspace_authorities_ready",
    "research_binding_ready",
    "composer_write_ready",
    "chat_write_ready",
}
_CURRENT_LEDGER_KEYS = _LOCAL_LEDGER_KEYS | {
    "admission_mode",
    "admission_workspace_id",
    "configured_release_workspace_id",
    "candidate_admission_id",
    "candidate_admission_digest",
    "connector_liveness_ready",
    "connector_liveness_reason",
    "connector_worker_id",
    "connector_mode",
    "connector_heartbeat_age_seconds",
    "release_authorized",
    "release_stamp_id",
    "public_cutover_id",
    "release_event_cursor",
}
_PLATFORM_CONTRACT_KEYS = {
    "schema_version",
    "profile",
    "hermes_contract_version_min",
    "required_bool_features",
    "required_exact_features",
    "required_durable",
    "durable_evidence_template",
    "hqa_cli_operations",
    "http_endpoints",
    "write_contract",
}
_LOCAL_REQUIRED_BOOL_FEATURES = (
    "session_resources",
    "run_submission",
    "run_events_sse",
    "run_events_snapshot",
    "run_status",
    "run_approval_response",
    "run_stop",
    "managed_run_sessions",
)
_LOCAL_REQUIRED_EXACT_FEATURES = {
    "managed_run_history_authority": "hermes_session_db",
    "managed_session_fork_mode": "preserve_source_exact_message_cursor",
}
_LOCAL_REQUIRED_DURABLE = (
    "idempotency",
    "event_replay",
    "approval_cas",
    "idempotent_stop",
    "restart_reconcile",
    "run_evidence",
)
_LOCAL_DURABLE_EVIDENCE_TEMPLATE = "store.transactional_probe:{capability}"
_LOCAL_HTTP_ENDPOINTS = (
    ("GET", "/v1/capabilities"),
    ("POST", "/v1/runs"),
    ("GET", "/v1/runs/{run_id}"),
    ("GET", "/v1/runs/{run_id}/events"),
    ("GET", "/v1/runs/{run_id}/events/snapshot"),
    ("POST", "/v1/runs/{run_id}/approval"),
    ("POST", "/v1/runs/{run_id}/stop"),
    ("POST", "/api/sessions"),
    ("GET", "/api/sessions/{session_id}"),
    ("GET", "/api/sessions/{session_id}/messages"),
    ("POST", "/api/sessions/{session_id}/fork"),
)


class CompatibilityError(RuntimeError):
    """Fail-closed compatibility or local-evidence failure."""


@dataclass(frozen=True)
class CompatibilityConfig:
    hqa_repo: Path
    platform_repo: Path
    hermes_repo: Path
    state_dir: Path
    profile: str = "dark_readonly"
    hermes_base_url: str = "http://127.0.0.1:8642"
    platform_base_url: str = "http://127.0.0.1:8765"
    hermes_cli_path: Path = field(
        default_factory=lambda: Path.home() / ".local" / "bin" / "hermes"
    )
    hermes_api_key_file: Optional[Path] = None
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
        if self.hermes_api_key_file is not None:
            if not isinstance(self.hermes_api_key_file, (str, Path)):
                raise TypeError("hermes_api_key_file must be path-like")
            object.__setattr__(
                self,
                "hermes_api_key_file",
                Path(self.hermes_api_key_file),
            )
        if self.profile not in _PROFILES:
            raise ValueError("profile must be dark_readonly or local_agent_v0_2")
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


@dataclass(frozen=True)
class PlatformCompatibilityContract:
    document: Mapping[str, Any]
    digest: str
    schema_version: int


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


def _unique_json_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    document: Dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise CompatibilityError("platform_contract_manifest_schema")
        document[key] = value
    return document


def _reject_json_constant(_value: str) -> None:
    raise CompatibilityError("platform_contract_manifest_schema")


def _load_platform_contract(
    config: CompatibilityConfig,
) -> PlatformCompatibilityContract:
    path = config.platform_repo / _PLATFORM_CONTRACT_RELATIVE_PATH
    try:
        root = config.platform_repo.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        if path.is_symlink() or not resolved.is_file():
            raise CompatibilityError("platform_contract_manifest_unavailable")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        descriptor = os.open(resolved, flags)
    except (OSError, ValueError) as exc:
        raise CompatibilityError("platform_contract_manifest_unavailable") from exc
    try:
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_size < 1
                or info.st_size > 65_536
            ):
                raise CompatibilityError("platform_contract_manifest_schema")
            raw = os.read(descriptor, 65_537)
        except OSError as exc:
            raise CompatibilityError(
                "platform_contract_manifest_unavailable"
            ) from exc
    finally:
        os.close(descriptor)
    if not raw or len(raw) > 65_536:
        raise CompatibilityError("platform_contract_manifest_schema")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except CompatibilityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise CompatibilityError("platform_contract_manifest_schema") from exc
    if type(document) is not dict or set(document) != _PLATFORM_CONTRACT_KEYS:
        raise CompatibilityError("platform_contract_manifest_schema")

    from hqa.hermes_run_cli import (
        HERMES_RUN_CLI_OPERATIONS,
        HERMES_RUN_FORBIDDEN_FIELDS,
        HERMES_RUN_SUBMIT_FIELDS,
        HERMES_SESSION_FORK_POINT_FORMAT,
        HERMES_SESSION_FORK_PRESERVE_SOURCE,
    )

    endpoints = document.get("http_endpoints")
    if type(endpoints) is not list:
        raise CompatibilityError("platform_contract_manifest_schema")
    endpoint_pairs: List[Tuple[str, str]] = []
    for endpoint in endpoints:
        if type(endpoint) is not dict or set(endpoint) != {"method", "path"}:
            raise CompatibilityError("platform_contract_manifest_schema")
        method = endpoint.get("method")
        endpoint_path = endpoint.get("path")
        if (
            type(method) is not str
            or type(endpoint_path) is not str
            or method not in {"GET", "POST"}
            or not endpoint_path.startswith("/")
            or len(endpoint_path) > 256
        ):
            raise CompatibilityError("platform_contract_manifest_schema")
        endpoint_pairs.append((method, endpoint_path))

    write_contract = document.get("write_contract")
    if type(write_contract) is not dict or set(write_contract) != {
        "run_submit_fields",
        "platform_must_not_send",
        "fork_requires",
    }:
        raise CompatibilityError("platform_contract_manifest_schema")
    fork_requires = write_contract.get("fork_requires")
    if type(fork_requires) is not dict or set(fork_requires) != {
        "preserve_source",
        "fork_point_format",
    }:
        raise CompatibilityError("platform_contract_manifest_schema")

    if (
        type(document.get("schema_version")) is not int
        or document.get("schema_version") != 1
        or document.get("profile") != "local_agent_v0_2"
        or type(document.get("hermes_contract_version_min")) is not int
        or document.get("hermes_contract_version_min") != 1
        or tuple(document.get("required_bool_features") or ())
        != _LOCAL_REQUIRED_BOOL_FEATURES
        or document.get("required_exact_features")
        != _LOCAL_REQUIRED_EXACT_FEATURES
        or tuple(document.get("required_durable") or ())
        != _LOCAL_REQUIRED_DURABLE
        or document.get("durable_evidence_template")
        != _LOCAL_DURABLE_EVIDENCE_TEMPLATE
        or tuple(document.get("hqa_cli_operations") or ())
        != HERMES_RUN_CLI_OPERATIONS
        or tuple(endpoint_pairs) != _LOCAL_HTTP_ENDPOINTS
        or tuple(write_contract.get("run_submit_fields") or ())
        != HERMES_RUN_SUBMIT_FIELDS
        or tuple(write_contract.get("platform_must_not_send") or ())
        != HERMES_RUN_FORBIDDEN_FIELDS
        or fork_requires.get("preserve_source")
        is not HERMES_SESSION_FORK_PRESERVE_SOURCE
        or fork_requires.get("fork_point_format")
        != HERMES_SESSION_FORK_POINT_FORMAT
    ):
        raise CompatibilityError("platform_contract_manifest_drift")
    return PlatformCompatibilityContract(
        document=document,
        digest=_digest(document),
        schema_version=1,
    )


def _read_owner_only_api_key(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    if not path.is_absolute():
        raise CompatibilityError("hermes_api_key_invalid")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CompatibilityError("hermes_api_key_unavailable") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o077
            or (hasattr(os, "getuid") and info.st_uid != os.getuid())
        ):
            raise CompatibilityError("hermes_api_key_invalid")
        raw = os.read(fd, 4097)
    finally:
        os.close(fd)
    if not raw or len(raw) > 4096:
        raise CompatibilityError("hermes_api_key_invalid")
    try:
        decoded = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise CompatibilityError("hermes_api_key_invalid") from exc
    if decoded.endswith("\r\n"):
        token = decoded[:-2]
    elif decoded.endswith("\n"):
        token = decoded[:-1]
    else:
        token = decoded
    if (
        not token
        or len(token) > 4096
        or any(not 0x21 <= ord(char) <= 0x7E for char in token)
    ):
        raise CompatibilityError("hermes_api_key_invalid")
    return token


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
        platform_trigger_files = PLATFORM_REPROBE_TRIGGER_FILES
        if config.profile == "local_agent_v0_2":
            platform_trigger_files = (
                *platform_trigger_files,
                *PLATFORM_LOCAL_AGENT_TRIGGER_FILES,
            )
        platform_digest = _contract_digest(
            config.platform_repo, platform_trigger_files
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

    reprobe_identity: Dict[str, Any] = {
        "schema_version": 1,
        "profile": config.profile,
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
    if config.profile == "local_agent_v0_2":
        try:
            contract = _load_platform_contract(config)
            reprobe_identity["platform_contract"] = {
                "schema_version": contract.schema_version,
                "digest": contract.digest,
            }
        except CompatibilityError as exc:
            code = str(exc)
            if not re.fullmatch(r"[a-z0-9_]{1,64}", code):
                code = "platform_contract_manifest_unavailable"
            reprobe_identity["platform_contract"] = {
                "schema_version": None,
                "digest": "unavailable",
            }
            blockers.append(code)
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


def _validate_platform_health(value: Any, *, profile: str) -> None:
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
    ledger_keys = frozenset(ledger)
    accepted_keys = (
        {_CURRENT_LEDGER_KEYS}
        if profile == "local_agent_v0_2"
        else {_LEGACY_LEDGER_KEYS, _LOCAL_LEDGER_KEYS, _CURRENT_LEDGER_KEYS}
    )
    if ledger_keys not in accepted_keys:
        raise CompatibilityError("platform_health_schema")
    bool_keys = [
        "database_configured",
        "schema_ready",
        "workflow_binding_schema_ready",
        "mutation_enabled",
    ]
    if ledger_keys in {_LOCAL_LEDGER_KEYS, _CURRENT_LEDGER_KEYS}:
        bool_keys.extend(
            [
                "session_registry_schema_ready",
                "agent_workspace_authorities_ready",
                "research_binding_ready",
                "composer_write_ready",
                "chat_write_ready",
            ]
        )
    for key in bool_keys:
        if type(ledger[key]) is not bool:
            raise CompatibilityError("platform_health_schema")
    version_pairs = [
        ("schema_ready", "schema_version"),
        ("workflow_binding_schema_ready", "workflow_binding_schema_version"),
    ]
    if ledger_keys in {_LOCAL_LEDGER_KEYS, _CURRENT_LEDGER_KEYS}:
        version_pairs.append(
            ("session_registry_schema_ready", "session_registry_schema_version")
        )
    for ready_key, version_key in version_pairs:
        version = ledger[version_key]
        if ledger[ready_key] is not (
            type(version) is int and not isinstance(version, bool) and version >= 1
        ):
            raise CompatibilityError("platform_health_schema")
    if profile == "dark_readonly" and ledger["mutation_enabled"] is not False:
        raise CompatibilityError("platform_mutation_enabled_drift")
    if ledger_keys in {_LOCAL_LEDGER_KEYS, _CURRENT_LEDGER_KEYS}:
        if profile == "dark_readonly" and (
            ledger["composer_write_ready"] is not False
            or ledger["chat_write_ready"] is not False
        ):
            raise CompatibilityError("platform_mutation_enabled_drift")
        if profile == "local_agent_v0_2" and not all(
            ledger[key] is True
            for key in (
                "database_configured",
                "schema_ready",
                "workflow_binding_schema_ready",
                "session_registry_schema_ready",
                "agent_workspace_authorities_ready",
                "research_binding_ready",
            )
        ):
            raise CompatibilityError("platform_agent_authority_unready")
    if ledger_keys == _CURRENT_LEDGER_KEYS:
        _validate_current_ledger_projection(ledger, profile=profile)
    _validate_safety(health["safety"])


def _is_bounded_id(value: Any) -> bool:
    return type(value) is str and _BOUNDED_ID_RE.fullmatch(value) is not None


def _is_optional_bounded_id(value: Any) -> bool:
    return value is None or _is_bounded_id(value)


def _validate_current_ledger_projection(
    ledger: Mapping[str, Any],
    *,
    profile: str,
) -> None:
    admission_mode = ledger["admission_mode"]
    admission_workspace = ledger["admission_workspace_id"]
    configured_workspace = ledger["configured_release_workspace_id"]
    candidate_id = ledger["candidate_admission_id"]
    candidate_digest = ledger["candidate_admission_digest"]
    connector_ready = ledger["connector_liveness_ready"]
    connector_reason = ledger["connector_liveness_reason"]
    connector_worker = ledger["connector_worker_id"]
    connector_mode = ledger["connector_mode"]
    connector_age = ledger["connector_heartbeat_age_seconds"]
    release_authorized = ledger["release_authorized"]
    release_stamp = ledger["release_stamp_id"]
    public_cutover = ledger["public_cutover_id"]
    event_cursor = ledger["release_event_cursor"]

    if (
        admission_mode not in {"closed", "candidate", "local_trust", "release"}
        or admission_workspace != "ws-local-main"
        or not _is_bounded_id(configured_workspace)
        or type(connector_ready) is not bool
        or type(connector_reason) is not str
        or connector_reason not in _CONNECTOR_REASON_VALUES
        or not _is_optional_bounded_id(connector_worker)
        or connector_mode not in {None, "supervised_dispatch", "reconcile_only"}
        or type(release_authorized) is not bool
        or not _is_optional_bounded_id(release_stamp)
        or not _is_optional_bounded_id(public_cutover)
        or type(event_cursor) is not int
        or event_cursor < 0
        or event_cursor > _MAX_EVENT_CURSOR
    ):
        raise CompatibilityError("platform_health_schema")

    candidate_pair_absent = candidate_id is None and candidate_digest is None
    candidate_pair_valid = (
        _is_bounded_id(candidate_id)
        and type(candidate_digest) is str
        and _SHA256_RE.fullmatch(candidate_digest) is not None
    )
    if not candidate_pair_absent and not candidate_pair_valid:
        raise CompatibilityError("platform_health_schema")

    if connector_age is not None:
        if type(connector_age) is int:
            age_is_valid = abs(connector_age) <= _MAX_CONNECTOR_AGE_SECONDS
        elif type(connector_age) is float:
            age_is_valid = (
                math.isfinite(connector_age)
                and abs(connector_age) <= _MAX_CONNECTOR_AGE_SECONDS
            )
        else:
            age_is_valid = False
        if not age_is_valid:
            raise CompatibilityError("platform_health_schema")
    connector_identity_absent = (
        connector_worker is None and connector_mode is None and connector_age is None
    )
    connector_record_present = (
        connector_worker is not None
        and connector_mode is not None
        and connector_age is not None
    )
    connector_candidate_observation = (
        connector_worker is not None
        and connector_mode is None
        and connector_age is not None
    )
    if not (
        connector_identity_absent
        or connector_record_present
        or connector_candidate_observation
    ):
        raise CompatibilityError("platform_health_schema")
    if connector_reason == "connector_generation_missing":
        connector_shape_valid = connector_identity_absent
    elif connector_reason == "connector_liveness_unavailable":
        connector_shape_valid = connector_identity_absent or (
            admission_mode == "closed"
            and (candidate_pair_valid or release_authorized)
            and ledger["mutation_enabled"] is True
            and connector_candidate_observation
        )
    elif connector_reason == "connector_not_active":
        connector_shape_valid = connector_record_present
    elif connector_reason == "connector_mode_not_supervised":
        connector_shape_valid = (
            connector_record_present and connector_mode == "reconcile_only"
        )
    elif connector_reason == "connector_runtime_digest_mismatch":
        connector_shape_valid = (
            connector_record_present and connector_mode == "supervised_dispatch"
        )
    elif connector_reason == "connector_heartbeat_in_future":
        connector_shape_valid = (
            connector_record_present
            and connector_mode == "supervised_dispatch"
            and connector_age < 0
        )
    elif connector_reason == "connector_heartbeat_stale":
        connector_shape_valid = (
            connector_record_present
            and connector_mode == "supervised_dispatch"
            and connector_age > 1.0
        )
    elif connector_reason == "connector_session_lock_missing":
        connector_shape_valid = (
            connector_record_present
            and connector_mode == "supervised_dispatch"
            and 0 <= connector_age <= _MAX_READY_CONNECTOR_AGE_SECONDS
        )
    else:
        connector_shape_valid = (
            connector_reason == "ready"
            and connector_record_present
            and connector_mode == "supervised_dispatch"
            and 0 <= connector_age <= _MAX_READY_CONNECTOR_AGE_SECONDS
        )
    if not connector_shape_valid:
        raise CompatibilityError("platform_health_schema")
    if (
        admission_mode == "closed"
        and candidate_pair_valid
        and connector_reason != "connector_liveness_unavailable"
    ):
        raise CompatibilityError("platform_health_schema")
    if (
        admission_mode == "closed"
        and release_authorized
        and connector_reason not in {"ready", "connector_liveness_unavailable"}
    ):
        raise CompatibilityError("platform_health_schema")
    if connector_ready:
        if (
            connector_reason != "ready"
            or not connector_record_present
        ):
            raise CompatibilityError("platform_health_schema")
    elif connector_reason == "ready":
        raise CompatibilityError("platform_health_schema")
    if connector_mode == "reconcile_only" and connector_ready:
        raise CompatibilityError("platform_health_schema")
    composer_ready = ledger["composer_write_ready"]
    chat_ready = ledger["chat_write_ready"]
    if composer_ready is not chat_ready:
        raise CompatibilityError("platform_health_schema")
    if admission_workspace != configured_workspace:
        if (
            admission_mode != "closed"
            or not candidate_pair_absent
            or release_authorized
            or composer_ready
            or release_stamp is not None
            or public_cutover is not None
            or event_cursor != 0
            or connector_ready
            or not connector_identity_absent
            or connector_reason != "connector_liveness_unavailable"
        ):
            raise CompatibilityError("platform_health_schema")
    if admission_mode == "closed" and composer_ready:
        raise CompatibilityError("platform_health_schema")
    if profile == "dark_readonly" and (
        admission_mode != "closed" or release_authorized
    ):
        raise CompatibilityError("platform_mutation_enabled_drift")
    if release_authorized and ledger["mutation_enabled"] is not True:
        raise CompatibilityError("platform_health_schema")
    if (
        release_authorized
        and admission_mode == "closed"
        and not candidate_pair_absent
    ):
        raise CompatibilityError("platform_health_schema")
    if admission_mode == "candidate" and (
        not candidate_pair_valid
        or release_authorized
        or not connector_ready
        or ledger["mutation_enabled"] is not True
        or composer_ready is not True
    ):
        raise CompatibilityError("platform_health_schema")
    if admission_mode == "local_trust" and (
        profile != "local_agent_v0_2"
        or not candidate_pair_absent
        or release_authorized
        or not connector_ready
        or ledger["mutation_enabled"] is not True
        or composer_ready is not True
        or release_stamp is not None
        or public_cutover is not None
        or event_cursor != 0
    ):
        raise CompatibilityError("platform_health_schema")
    if admission_mode == "release" and (
        not release_authorized
        or not candidate_pair_valid
        or release_stamp is None
        or public_cutover is None
        or ledger["mutation_enabled"] is not True
        or composer_ready is not connector_ready
    ):
        raise CompatibilityError("platform_health_schema")
    if composer_ready and (
        ledger["mutation_enabled"] is not True
        or admission_mode == "closed"
        or not connector_ready
    ):
        raise CompatibilityError("platform_health_schema")
    if public_cutover is not None and release_stamp is None:
        raise CompatibilityError("platform_health_schema")
    if release_authorized and (
        release_stamp is None or public_cutover is None
    ):
        raise CompatibilityError("platform_health_schema")


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


def _validate_gateway(
    value: Any,
    *,
    profile: str,
    contract: Optional[PlatformCompatibilityContract],
) -> None:
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
        or type(gateway["chat_write_ready"]) is not bool
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
    if profile == "dark_readonly" and gateway["chat_write_ready"] is not False:
        raise CompatibilityError("platform_gateway_contract_drift")
    if profile == "local_agent_v0_2":
        if contract is None:
            raise CompatibilityError("platform_contract_manifest_unavailable")
        required = contract.document["required_bool_features"]
        if not isinstance(required, list) or any(
            features.get(name) is not True for name in required
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


def _validate_hermes_capabilities(
    value: Any,
    contract: PlatformCompatibilityContract,
) -> None:
    if type(value) is not dict:
        raise CompatibilityError("capabilities_schema")
    if (
        value.get("object") != "hermes.api_server.capabilities"
        or value.get("platform") != "hermes-agent"
    ):
        raise CompatibilityError("capabilities_envelope_drift")
    minimum = contract.document["hermes_contract_version_min"]
    version = value.get("contract_version")
    if (
        type(version) is not int
        or isinstance(version, bool)
        or type(minimum) is not int
        or version < minimum
    ):
        raise CompatibilityError("contract_version_drift")

    features = value.get("features")
    if type(features) is not dict:
        raise CompatibilityError("features_schema")
    required_bool = contract.document["required_bool_features"]
    if not isinstance(required_bool, list) or any(
        features.get(name) is not True for name in required_bool
    ):
        raise CompatibilityError("bool_feature_drift")
    required_exact = contract.document["required_exact_features"]
    if not isinstance(required_exact, dict) or any(
        features.get(name) != expected
        for name, expected in required_exact.items()
    ):
        raise CompatibilityError("exact_feature_drift")

    durable = value.get("durable")
    required_durable = contract.document["required_durable"]
    template = contract.document["durable_evidence_template"]
    if (
        type(durable) is not dict
        or not isinstance(required_durable, list)
        or type(template) is not str
    ):
        raise CompatibilityError("durable_schema")
    for capability in required_durable:
        fact = durable.get(capability)
        expected_evidence = template.replace("{capability}", capability)
        if (
            type(fact) is not dict
            or set(fact) != {"supported", "grounded", "evidence"}
            or fact.get("supported") is not True
            or fact.get("grounded") is not True
            or fact.get("evidence") != expected_evidence
        ):
            raise CompatibilityError(f"durable_{capability}_drift")

    endpoints = value.get("endpoints")
    if type(endpoints) is not dict:
        raise CompatibilityError("http_endpoint_drift")
    advertised = set()
    for endpoint in endpoints.values():
        if (
            type(endpoint) is not dict
            or set(endpoint) != {"method", "path"}
            or type(endpoint.get("method")) is not str
            or type(endpoint.get("path")) is not str
        ):
            raise CompatibilityError("http_endpoint_drift")
        advertised.add((endpoint["method"], endpoint["path"]))
    required_endpoints = contract.document["http_endpoints"]
    if not isinstance(required_endpoints, list):
        raise CompatibilityError("http_endpoint_drift")
    expected = {
        (endpoint["method"], endpoint["path"])
        for endpoint in required_endpoints
        if isinstance(endpoint, dict)
    }
    if len(expected) != len(required_endpoints) or not expected.issubset(advertised):
        raise CompatibilityError("http_endpoint_drift")


def _request_json(
    url: str,
    config: CompatibilityConfig,
    *,
    authorization_token: Optional[str] = None,
) -> Any:
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    headers = {
        "Accept": "application/json",
        "User-Agent": "hqa-compatibility/1",
    }
    if authorization_token is not None:
        headers["Authorization"] = f"Bearer {authorization_token}"
    request = Request(
        url,
        method="GET",
        headers=headers,
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
    contract: Optional[PlatformCompatibilityContract] = None
    authorization_token: Optional[str] = None
    if config.profile == "local_agent_v0_2":
        try:
            contract = _load_platform_contract(config)
            results.append(
                {
                    "name": "platform_contract_manifest",
                    "method": "LOCAL",
                    "ok": True,
                }
            )
        except CompatibilityError as exc:
            code = _safe_error_code(
                str(exc),
                fallback="platform_contract_manifest_unavailable",
            )
            results.append(
                {
                    "name": "platform_contract_manifest",
                    "method": "LOCAL",
                    "ok": False,
                    "error_code": code,
                }
            )
            blockers.append(code)
        try:
            authorization_token = _read_owner_only_api_key(
                config.hermes_api_key_file
            )
        except CompatibilityError as exc:
            code = _safe_error_code(
                str(exc),
                fallback="hermes_api_key_unavailable",
            )
            results.append(
                {
                    "name": "hermes_capabilities_auth",
                    "method": "LOCAL",
                    "ok": False,
                    "error_code": code,
                }
            )
            blockers.append(code)

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
            if name == "hermes_health":
                _validate_hermes_health(payload)
            elif name == "platform_health":
                _validate_platform_health(payload, profile=config.profile)
            elif name == "platform_gateway":
                _validate_gateway(
                    payload,
                    profile=config.profile,
                    contract=contract,
                )
            else:
                _validate_sessions(payload)
            results.append({"name": name, "method": "GET", "ok": True})
        except CompatibilityError as exc:
            code = _safe_error_code(str(exc), fallback="probe_failed")
            results.append(
                {"name": name, "method": "GET", "ok": False, "error_code": code}
            )
            blockers.append(f"{name}:{code}")
        if name == "hermes_health" and config.profile == "local_agent_v0_2":
            if contract is None:
                code = "platform_contract_manifest_unavailable"
                results.append(
                    {
                        "name": "hermes_capabilities",
                        "method": "GET",
                        "ok": False,
                        "error_code": code,
                    }
                )
                blockers.append(f"hermes_capabilities:{code}")
                continue
            try:
                capabilities = _request_json(
                    bases["hermes"] + "/v1/capabilities",
                    config,
                    authorization_token=authorization_token,
                )
                _validate_hermes_capabilities(capabilities, contract)
                results.append(
                    {
                        "name": "hermes_capabilities",
                        "method": "GET",
                        "ok": True,
                    }
                )
            except CompatibilityError as exc:
                code = _safe_error_code(str(exc), fallback="probe_failed")
                results.append(
                    {
                        "name": "hermes_capabilities",
                        "method": "GET",
                        "ok": False,
                        "error_code": code,
                    }
                )
                blockers.append(f"hermes_capabilities:{code}")
    return results, blockers


def _safe_error_code(value: str, *, fallback: str) -> str:
    return value if re.fullmatch(r"[a-z0-9_]{1,64}", value) else fallback


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
    """Check one local compatibility profile and preserve its last good baseline.

    A matching successful trigger identity returns without any HTTP request.
    Changed or previously failed identities execute four bounded loopback GETs;
    ``local_agent_v0_2`` adds the authenticated capabilities GET and shared
    Platform manifest validation. Failed checks write evidence but never
    replace ``baseline.json``.
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
    "PLATFORM_LOCAL_AGENT_TRIGGER_FILES",
    "WATCHER_CONTRACT_FILES",
    "check_compatibility",
]
