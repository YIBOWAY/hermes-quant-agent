from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit


_REPOSITORIES = frozenset({"hqa", "platform", "hermes"})
RUNTIME_ENVIRONMENT_KEYS = frozenset(
    {
        "APP_ENV",
        "HERMES_DURABLE_RUNS_ENABLED",
        "HERMES_MODE",
        "HQA_CHAT_WRITE_READY",
        "HQA_ENV",
        "HQA_PUBLIC_COMPOSER_ENABLED",
        "HQA_WORKER_CLAIM_ENABLED",
        "HQA_WORKER_DISPATCH_ENABLED",
        "LANG",
        "LC_ALL",
        "PYTHON_IMPLEMENTATION",
        "PYTHON_VERSION",
        "QS_ENV",
        "TZ",
        "VIRTUAL_ENV",
    }
)
RUNTIME_CONFIG_KEYS = frozenset(
    {
        "app_mode",
        "bind_host",
        "chat_write_ready",
        "database_schema_version",
        "durable_runs_enabled",
        "kill_switch_enabled",
        "live_trading_enabled",
        "migration_version",
        "paper_trading",
        "port",
        "provider_policy_digest",
        "public_composer_enabled",
        "runtime_mode",
        "transport",
        "worker_claim_enabled",
        "worker_dispatch_enabled",
    }
)
_BOOLEAN_CONFIG_KEYS = frozenset(
    {
        "chat_write_ready",
        "durable_runs_enabled",
        "kill_switch_enabled",
        "live_trading_enabled",
        "paper_trading",
        "public_composer_enabled",
        "worker_claim_enabled",
        "worker_dispatch_enabled",
    }
)
_INTEGER_CONFIG_KEYS = frozenset(
    {"database_schema_version", "migration_version", "port"}
)
_SECRET_KEY_PARTS = frozenset(
    {
        "apikey",
        "auth",
        "bearer",
        "credential",
        "credentials",
        "passwd",
        "password",
        "privatekey",
        "secret",
        "token",
    }
)
_KEY_PART_RE = re.compile(r"[^a-z0-9]+")
_HEX_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ReleaseManifestError(ValueError):
    """Base class for fail-closed release manifest failures."""


class ManifestValidationError(ReleaseManifestError):
    """The supplied manifest or specification is outside the closed schema."""


class ManifestIntegrityError(ReleaseManifestError):
    """Canonical or derived release evidence does not agree."""


def _validate_bounded_text(value: Any, field: str, *, maximum: int = 2_048) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value.isprintable()
        or len(value.encode("utf-8")) > maximum
    ):
        raise ManifestValidationError(f"{field} must be a bounded printable string")
    return value


def _validate_git_oid(value: Any, field: str) -> str:
    if not isinstance(value, str) or _HEX_RE.fullmatch(value) is None:
        raise ManifestValidationError(f"{field} must be a full lowercase Git object ID")
    return value


def _validate_remote(value: Any) -> str:
    remote = _validate_bounded_text(value, "expected_remote", maximum=4_096)
    parsed = urlsplit(remote)
    if parsed.scheme and (parsed.username is not None or parsed.password is not None):
        raise ManifestValidationError("expected_remote must not contain credentials")
    return remote


def _normalize_declared_paths(value: Any, field: str) -> Tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{field} must be a tuple or list")
    paths = []
    for item in value:
        path = _validate_bounded_text(item, field, maximum=4_096)
        pure = PurePosixPath(path)
        if (
            path.startswith("/")
            or "\\" in path
            or path != pure.as_posix()
            or any(part in ("", ".", "..") for part in pure.parts)
        ):
            raise ManifestValidationError(
                f"{field} must contain normalized repository-relative POSIX paths"
            )
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise ManifestValidationError(f"{field} must not contain duplicate paths")
    return tuple(sorted(paths))


def _validate_command(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or not value or len(value) > 64:
        raise ManifestValidationError("command must contain 1 to 64 arguments")
    command = tuple(
        _validate_bounded_text(item, "command argument", maximum=4_096)
        for item in value
    )
    for argument in command:
        if not argument.startswith("-"):
            continue
        option = argument.lstrip("-").split("=", 1)[0]
        if _looks_secret_key(option):
            raise ManifestValidationError("command contains a secret-like option")
    return command


def _normalize_started_at(value: Any) -> str:
    timestamp = _validate_bounded_text(value, "started_at", maximum=64)
    parsed_value = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    try:
        parsed = datetime.fromisoformat(parsed_value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (ValueError, OverflowError, OSError) as exc:
        raise ManifestValidationError(
            "started_at must be a timezone-aware RFC3339 timestamp"
        ) from exc


@dataclass(frozen=True)
class RepositorySpec:
    repo: str
    checkout: Path
    expected_remote: str
    expected_branch: str
    expected_base_commit: str
    expected_head_commit: str
    remote_name: str = "origin"
    runtime_required: Optional[bool] = None
    declared_tracked_dirty: Tuple[str, ...] = ()
    declared_untracked_dirty: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.repo not in _REPOSITORIES:
            raise ManifestValidationError("repo must be hqa, platform, or hermes")
        if not isinstance(self.checkout, (str, Path)):
            raise TypeError("checkout must be path-like")
        checkout = Path(self.checkout)
        _validate_remote(self.expected_remote)
        branch = _validate_bounded_text(
            self.expected_branch, "expected_branch", maximum=255
        )
        if branch.startswith("-") or branch.endswith("/") or ".." in branch:
            raise ManifestValidationError("expected_branch is not canonical")
        _validate_git_oid(self.expected_base_commit, "expected_base_commit")
        _validate_git_oid(self.expected_head_commit, "expected_head_commit")
        remote_name = _validate_bounded_text(
            self.remote_name, "remote_name", maximum=128
        )
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", remote_name) is None:
            raise ManifestValidationError("remote_name is not canonical")
        runtime_required = self.runtime_required
        if runtime_required is None:
            runtime_required = self.repo == "hermes"
        if type(runtime_required) is not bool:
            raise TypeError("runtime_required must be boolean")
        if self.repo == "hermes" and not runtime_required:
            raise ManifestValidationError("the Hermes runtime must remain required")
        tracked = _normalize_declared_paths(
            self.declared_tracked_dirty, "declared_tracked_dirty"
        )
        untracked = _normalize_declared_paths(
            self.declared_untracked_dirty, "declared_untracked_dirty"
        )
        if set(tracked) & set(untracked):
            raise ManifestValidationError(
                "tracked and untracked dirty declarations must not overlap"
            )
        object.__setattr__(self, "checkout", checkout)
        object.__setattr__(self, "remote_name", remote_name)
        object.__setattr__(self, "runtime_required", runtime_required)
        object.__setattr__(
            self,
            "declared_tracked_dirty",
            tracked,
        )
        object.__setattr__(
            self,
            "declared_untracked_dirty",
            untracked,
        )


@dataclass(frozen=True)
class RuntimeSpec:
    repo: str
    command: Tuple[str, ...]
    version: str
    installed_commit: str
    installed_archive_sha256: str
    running_commit: str
    running_archive_sha256: str
    pid: int
    started_at: str
    environment: Mapping[str, str]
    config: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.repo not in _REPOSITORIES:
            raise ManifestValidationError("repo must be hqa, platform, or hermes")
        command = _validate_command(self.command)
        version = _validate_bounded_text(self.version, "version", maximum=200)
        installed_commit = _validate_git_oid(self.installed_commit, "installed_commit")
        running_commit = _validate_git_oid(self.running_commit, "running_commit")
        if (
            not isinstance(self.installed_archive_sha256, str)
            or _SHA256_RE.fullmatch(self.installed_archive_sha256) is None
        ):
            raise ManifestValidationError(
                "installed_archive_sha256 must be lowercase SHA-256"
            )
        if (
            not isinstance(self.running_archive_sha256, str)
            or _SHA256_RE.fullmatch(self.running_archive_sha256) is None
        ):
            raise ManifestValidationError(
                "running_archive_sha256 must be lowercase SHA-256"
            )
        if type(self.pid) is not int or not (1 <= self.pid <= 2**31 - 1):
            raise ManifestValidationError("pid must be a positive process identifier")
        started_at = _normalize_started_at(self.started_at)
        environment = _validate_runtime_mapping(
            self.environment,
            allowed_keys=RUNTIME_ENVIRONMENT_KEYS,
            field="environment",
            string_values_only=True,
        )
        config = _validate_runtime_mapping(
            self.config,
            allowed_keys=RUNTIME_CONFIG_KEYS,
            field="config",
            string_values_only=False,
        )
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "installed_commit", installed_commit)
        object.__setattr__(self, "running_commit", running_commit)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(
            self,
            "environment",
            MappingProxyType(environment),
        )
        object.__setattr__(
            self,
            "config",
            MappingProxyType(config),
        )


def _looks_secret_key(key: str) -> bool:
    collapsed = _KEY_PART_RE.sub("", key.casefold())
    parts = {part for part in _KEY_PART_RE.split(key.casefold()) if part}
    return (
        collapsed in _SECRET_KEY_PARTS
        or bool(parts & _SECRET_KEY_PARTS)
        or collapsed.endswith("apikey")
        or collapsed.endswith("privatekey")
    )


def _validate_runtime_mapping(
    value: Mapping[str, Any],
    *,
    allowed_keys: frozenset[str],
    field: str,
    string_values_only: bool,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    copied: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise TypeError(f"{field} keys must be non-empty strings")
        if _looks_secret_key(key):
            raise ValueError(f"{field} contains a secret-like key")
        if key not in allowed_keys:
            raise ValueError(f"{field} contains an unknown key: {key}")
        if string_values_only:
            if not isinstance(item, str):
                raise TypeError(f"{field}.{key} must be a string")
        elif type(item) not in (bool, int, str):
            raise TypeError(f"{field}.{key} must be a JSON scalar")
        if not string_values_only:
            if key in _BOOLEAN_CONFIG_KEYS and type(item) is not bool:
                raise ValueError(f"{field}.{key} must be boolean")
            if key in _INTEGER_CONFIG_KEYS:
                if type(item) is not int or item < 0 or item > 65_535:
                    raise ValueError(f"{field}.{key} must be a bounded integer")
                if key == "port" and item == 0:
                    raise ValueError(f"{field}.port must be between 1 and 65535")
            if key == "provider_policy_digest" and (
                not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None
            ):
                raise ValueError(
                    f"{field}.provider_policy_digest must be lowercase SHA-256"
                )
            if (
                key not in _BOOLEAN_CONFIG_KEYS
                and key not in _INTEGER_CONFIG_KEYS
                and key != "provider_policy_digest"
                and not isinstance(item, str)
            ):
                raise ValueError(f"{field}.{key} must be a string")
        if isinstance(item, str) and (
            not item.isprintable() or len(item.encode("utf-8")) > 2_048
        ):
            raise ValueError(f"{field}.{key} must be a bounded printable value")
        copied[key] = item
    return dict(sorted(copied.items()))


@dataclass(frozen=True)
class RepositoryRecord:
    repo: str
    checkout: str
    remote_name: str
    remote: str
    expected_remote: str
    branch: Optional[str]
    expected_branch: str
    parent_commit: Optional[str]
    base_commit: str
    base_present: bool
    base_is_ancestor: bool
    head_commit: str
    expected_head_commit: str
    tree_oid: str
    archive_sha256: str
    tracked_dirty: Tuple[str, ...]
    untracked_dirty: Tuple[str, ...]
    declared_tracked_dirty: Tuple[str, ...]
    declared_untracked_dirty: Tuple[str, ...]
    dirty_matches: bool
    working_tree_clean: bool
    source_identity_matches: bool
    runtime_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "checkout": self.checkout,
            "remote_name": self.remote_name,
            "remote": self.remote,
            "expected_remote": self.expected_remote,
            "branch": self.branch,
            "expected_branch": self.expected_branch,
            "parent_commit": self.parent_commit,
            "base_commit": self.base_commit,
            "base_present": self.base_present,
            "base_is_ancestor": self.base_is_ancestor,
            "head_commit": self.head_commit,
            "expected_head_commit": self.expected_head_commit,
            "tree_oid": self.tree_oid,
            "archive_sha256": self.archive_sha256,
            "tracked_dirty": list(self.tracked_dirty),
            "untracked_dirty": list(self.untracked_dirty),
            "declared_tracked_dirty": list(self.declared_tracked_dirty),
            "declared_untracked_dirty": list(self.declared_untracked_dirty),
            "dirty_matches": self.dirty_matches,
            "working_tree_clean": self.working_tree_clean,
            "source_identity_matches": self.source_identity_matches,
            "runtime_required": self.runtime_required,
        }


@dataclass(frozen=True)
class RuntimeRecord:
    repo: str
    command: Tuple[str, ...]
    version: str
    installed_commit: str
    installed_archive_sha256: str
    running_commit: str
    running_archive_sha256: str
    pid: int
    started_at: str
    environment: Mapping[str, str]
    config: Mapping[str, Any]
    candidate_installed: bool
    runtime_aligned: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "command": list(self.command),
            "version": self.version,
            "installed_commit": self.installed_commit,
            "installed_archive_sha256": self.installed_archive_sha256,
            "running_commit": self.running_commit,
            "running_archive_sha256": self.running_archive_sha256,
            "pid": self.pid,
            "started_at": self.started_at,
            "environment": dict(self.environment),
            "config": dict(self.config),
            "candidate_installed": self.candidate_installed,
            "runtime_aligned": self.runtime_aligned,
        }


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    repositories: Tuple[RepositoryRecord, ...]
    runtimes: Tuple[RuntimeRecord, ...]
    dirty_declarations_match: bool
    candidate_source_committed: bool
    working_trees_clean: bool
    runtime_coverage: bool
    runtime_blockers: Tuple[str, ...]
    candidate_installed: bool
    runtime_aligned: bool
    write_ready: bool
    manifest_digest: str

    def to_dict(self) -> dict[str, Any]:
        document = _manifest_document(self, include_digest=True)
        return document

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "repositories",
        "runtimes",
        "dirty_declarations_match",
        "candidate_source_committed",
        "working_trees_clean",
        "runtime_coverage",
        "runtime_blockers",
        "candidate_installed",
        "runtime_aligned",
        "write_ready",
        "manifest_digest",
    }
)
_REPOSITORY_RECORD_FIELDS = frozenset(RepositoryRecord.__dataclass_fields__)
_RUNTIME_RECORD_FIELDS = frozenset(RuntimeRecord.__dataclass_fields__)


def _strict_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    field: str,
) -> None:
    if not isinstance(value, Mapping):
        raise ManifestValidationError(f"{field} must be an object")
    actual = set(value)
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise ManifestValidationError(
            f"{field} contains unknown fields: {sorted(unknown)}"
        )
    if missing:
        raise ManifestValidationError(f"{field} is missing fields: {sorted(missing)}")


def _tuple_of_strings(value: Any, field: str) -> Tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManifestValidationError(f"{field} must be a list of strings")
    if value != sorted(value) or len(value) != len(set(value)):
        raise ManifestValidationError(f"{field} must be sorted and unique")
    try:
        return _normalize_declared_paths(value, field)
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(str(exc)) from exc


def _repository_record_from_mapping(value: Mapping[str, Any]) -> RepositoryRecord:
    _strict_fields(value, _REPOSITORY_RECORD_FIELDS, "repository")
    checkout_value = value["checkout"]
    if not isinstance(checkout_value, str):
        raise ManifestValidationError("repository.checkout must be a string")
    checkout = Path(checkout_value)
    if (
        not checkout.is_absolute()
        or ".." in checkout.parts
        or checkout.as_posix() != checkout_value
    ):
        raise ManifestValidationError(
            "repository.checkout must be a canonical absolute path"
        )
    try:
        spec = RepositorySpec(
            repo=value["repo"],
            checkout=checkout,
            expected_remote=value["expected_remote"],
            expected_branch=value["expected_branch"],
            expected_base_commit=value["base_commit"],
            expected_head_commit=value["expected_head_commit"],
            remote_name=value["remote_name"],
            runtime_required=value["runtime_required"],
            declared_tracked_dirty=value["declared_tracked_dirty"],
            declared_untracked_dirty=value["declared_untracked_dirty"],
        )
        remote = _validate_remote(value["remote"])
        branch = value["branch"]
        if branch is not None:
            branch = _validate_bounded_text(branch, "branch", maximum=255)
        parent_commit = value["parent_commit"]
        if parent_commit is not None:
            parent_commit = _validate_git_oid(parent_commit, "parent_commit")
        head_commit = _validate_git_oid(value["head_commit"], "head_commit")
        tree_oid = _validate_git_oid(value["tree_oid"], "tree_oid")
        archive_sha256 = value["archive_sha256"]
        if (
            not isinstance(archive_sha256, str)
            or _SHA256_RE.fullmatch(archive_sha256) is None
        ):
            raise ManifestValidationError(
                "repository.archive_sha256 must be lowercase SHA-256"
            )
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(str(exc)) from exc
    for bool_field in (
        "base_present",
        "base_is_ancestor",
        "dirty_matches",
        "working_tree_clean",
        "source_identity_matches",
        "runtime_required",
    ):
        if type(value[bool_field]) is not bool:
            raise ManifestValidationError(f"repository.{bool_field} must be boolean")
    tracked_dirty = _tuple_of_strings(value["tracked_dirty"], "tracked_dirty")
    untracked_dirty = _tuple_of_strings(value["untracked_dirty"], "untracked_dirty")
    return RepositoryRecord(
        repo=spec.repo,
        checkout=checkout_value,
        remote_name=spec.remote_name,
        remote=remote,
        expected_remote=spec.expected_remote,
        branch=branch,
        expected_branch=spec.expected_branch,
        parent_commit=parent_commit,
        base_commit=spec.expected_base_commit,
        base_present=value["base_present"],
        base_is_ancestor=value["base_is_ancestor"],
        head_commit=head_commit,
        expected_head_commit=spec.expected_head_commit,
        tree_oid=tree_oid,
        archive_sha256=archive_sha256,
        tracked_dirty=tracked_dirty,
        untracked_dirty=untracked_dirty,
        declared_tracked_dirty=spec.declared_tracked_dirty,
        declared_untracked_dirty=spec.declared_untracked_dirty,
        dirty_matches=value["dirty_matches"],
        working_tree_clean=value["working_tree_clean"],
        source_identity_matches=value["source_identity_matches"],
        runtime_required=spec.runtime_required,
    )


def _runtime_record_from_mapping(value: Mapping[str, Any]) -> RuntimeRecord:
    _strict_fields(value, _RUNTIME_RECORD_FIELDS, "runtime")
    try:
        spec = RuntimeSpec(
            repo=value["repo"],
            command=value["command"],
            version=value["version"],
            installed_commit=value["installed_commit"],
            installed_archive_sha256=value["installed_archive_sha256"],
            running_commit=value["running_commit"],
            running_archive_sha256=value["running_archive_sha256"],
            pid=value["pid"],
            started_at=value["started_at"],
            environment=value["environment"],
            config=value["config"],
        )
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(str(exc)) from exc
    if type(value["candidate_installed"]) is not bool:
        raise ManifestValidationError("runtime.candidate_installed must be boolean")
    if type(value["runtime_aligned"]) is not bool:
        raise ManifestValidationError("runtime.runtime_aligned must be boolean")
    return RuntimeRecord(
        repo=spec.repo,
        command=spec.command,
        version=spec.version,
        installed_commit=spec.installed_commit,
        installed_archive_sha256=spec.installed_archive_sha256,
        running_commit=spec.running_commit,
        running_archive_sha256=spec.running_archive_sha256,
        pid=spec.pid,
        started_at=spec.started_at,
        environment=spec.environment,
        config=spec.config,
        candidate_installed=value["candidate_installed"],
        runtime_aligned=value["runtime_aligned"],
    )


def _manifest_from_mapping(value: Mapping[str, Any]) -> ReleaseManifest:
    _strict_fields(value, _MANIFEST_FIELDS, "manifest")
    if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
        raise ManifestValidationError("unsupported manifest schema_version")
    repository_documents = value["repositories"]
    runtime_documents = value["runtimes"]
    if not isinstance(repository_documents, list) or not isinstance(
        runtime_documents, list
    ):
        raise ManifestValidationError("repositories and runtimes must be lists")
    for bool_field in (
        "dirty_declarations_match",
        "candidate_source_committed",
        "working_trees_clean",
        "runtime_coverage",
        "candidate_installed",
        "runtime_aligned",
        "write_ready",
    ):
        if type(value[bool_field]) is not bool:
            raise ManifestValidationError(f"manifest.{bool_field} must be boolean")
    repositories = tuple(
        _repository_record_from_mapping(item) for item in repository_documents
    )
    runtimes = tuple(_runtime_record_from_mapping(item) for item in runtime_documents)
    runtime_blockers = value["runtime_blockers"]
    if (
        not isinstance(runtime_blockers, list)
        or runtime_blockers != sorted(runtime_blockers)
        or len(runtime_blockers) != len(set(runtime_blockers))
        or any(
            not isinstance(item, str)
            or re.fullmatch(
                r"(?:missing_required_runtime|candidate_not_installed|runtime_not_aligned):(?:hqa|platform|hermes)",
                item,
            )
            is None
            for item in runtime_blockers
        )
    ):
        raise ManifestValidationError(
            "manifest.runtime_blockers must be canonical known blockers"
        )
    return ReleaseManifest(
        schema_version=1,
        repositories=repositories,
        runtimes=runtimes,
        dirty_declarations_match=value["dirty_declarations_match"],
        candidate_source_committed=value["candidate_source_committed"],
        working_trees_clean=value["working_trees_clean"],
        runtime_coverage=value["runtime_coverage"],
        runtime_blockers=tuple(runtime_blockers),
        candidate_installed=value["candidate_installed"],
        runtime_aligned=value["runtime_aligned"],
        write_ready=value["write_ready"],
        manifest_digest=value["manifest_digest"],
    )


def _run_git(checkout: Path, *args: str, text: bool = True):
    completed = subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=True,
        capture_output=True,
        text=text,
    )
    return completed.stdout


def _git_succeeds(checkout: Path, *args: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def _nul_paths(raw: bytes) -> Tuple[str, ...]:
    return tuple(
        sorted(
            item.decode("utf-8", errors="strict") for item in raw.split(b"\0") if item
        )
    )


def _capture_repository(spec: RepositorySpec) -> RepositoryRecord:
    checkout = spec.checkout.expanduser().resolve(strict=True)
    root = Path(_run_git(checkout, "rev-parse", "--show-toplevel").strip()).resolve()
    if root != checkout:
        raise ValueError("checkout must be the absolute repository root")
    remote = _validate_remote(
        _run_git(
            checkout,
            "config",
            "--get",
            f"remote.{spec.remote_name}.url",
        ).strip()
    )
    branch = _run_git(checkout, "branch", "--show-current").strip() or None
    parents = _run_git(checkout, "rev-list", "--parents", "-n", "1", "HEAD").split()
    parent_commit = parents[1] if len(parents) > 1 else None
    head_commit = _run_git(checkout, "rev-parse", "HEAD").strip()
    tree_oid = _run_git(checkout, "rev-parse", "HEAD^{tree}").strip()
    archive = _run_git(
        checkout,
        "archive",
        "--format=tar",
        "HEAD",
        text=False,
    )
    archive_sha256 = hashlib.sha256(archive).hexdigest()
    tracked_dirty = _normalize_declared_paths(
        _nul_paths(
            _run_git(
                checkout,
                "diff",
                "--name-only",
                "-z",
                "--no-renames",
                "--no-ext-diff",
                "HEAD",
                "--",
                text=False,
            )
        ),
        "tracked_dirty",
    )
    untracked_dirty = _normalize_declared_paths(
        _nul_paths(
            _run_git(
                checkout,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                text=False,
            )
        ),
        "untracked_dirty",
    )
    dirty_matches = (
        tracked_dirty == spec.declared_tracked_dirty
        and untracked_dirty == spec.declared_untracked_dirty
    )
    base_present = _git_succeeds(
        checkout,
        "cat-file",
        "-e",
        f"{spec.expected_base_commit}^{{commit}}",
    )
    base_is_ancestor = base_present and _git_succeeds(
        checkout,
        "merge-base",
        "--is-ancestor",
        spec.expected_base_commit,
        "HEAD",
    )
    working_tree_clean = not tracked_dirty and not untracked_dirty
    source_identity_matches = (
        remote == spec.expected_remote
        and branch == spec.expected_branch
        and head_commit == spec.expected_head_commit
        and base_is_ancestor
    )
    return RepositoryRecord(
        repo=spec.repo,
        checkout=str(checkout),
        remote_name=spec.remote_name,
        remote=remote,
        expected_remote=spec.expected_remote,
        branch=branch,
        expected_branch=spec.expected_branch,
        parent_commit=parent_commit,
        base_commit=spec.expected_base_commit,
        base_present=base_present,
        base_is_ancestor=base_is_ancestor,
        head_commit=head_commit,
        expected_head_commit=spec.expected_head_commit,
        tree_oid=tree_oid,
        archive_sha256=archive_sha256,
        tracked_dirty=tracked_dirty,
        untracked_dirty=untracked_dirty,
        declared_tracked_dirty=spec.declared_tracked_dirty,
        declared_untracked_dirty=spec.declared_untracked_dirty,
        dirty_matches=dirty_matches,
        working_tree_clean=working_tree_clean,
        source_identity_matches=source_identity_matches,
        runtime_required=spec.runtime_required,
    )


def _capture_runtime(
    spec: RuntimeSpec,
    repository: RepositoryRecord,
) -> RuntimeRecord:
    candidate_installed = (
        spec.installed_commit == repository.head_commit
        and spec.installed_archive_sha256 == repository.archive_sha256
    )
    runtime_aligned = (
        spec.running_commit == spec.installed_commit
        and spec.running_archive_sha256 == spec.installed_archive_sha256
    )
    return RuntimeRecord(
        repo=spec.repo,
        command=spec.command,
        version=spec.version,
        installed_commit=spec.installed_commit,
        installed_archive_sha256=spec.installed_archive_sha256,
        running_commit=spec.running_commit,
        running_archive_sha256=spec.running_archive_sha256,
        pid=spec.pid,
        started_at=spec.started_at,
        environment=spec.environment,
        config=spec.config,
        candidate_installed=candidate_installed,
        runtime_aligned=runtime_aligned,
    )


def _derive_runtime_facts(
    repositories: Sequence[RepositoryRecord],
    runtimes: Sequence[RuntimeRecord],
) -> tuple[bool, Tuple[str, ...], bool, bool]:
    runtimes_by_repo = {runtime.repo: runtime for runtime in runtimes}
    required_repos = tuple(
        repository.repo for repository in repositories if repository.runtime_required
    )
    blockers = []
    for repo in required_repos:
        runtime = runtimes_by_repo.get(repo)
        if runtime is None:
            blockers.append(f"missing_required_runtime:{repo}")
            continue
        if not runtime.candidate_installed:
            blockers.append(f"candidate_not_installed:{repo}")
        if not runtime.runtime_aligned:
            blockers.append(f"runtime_not_aligned:{repo}")
    runtime_coverage = all(repo in runtimes_by_repo for repo in required_repos)
    candidate_installed = runtime_coverage and all(
        runtimes_by_repo[repo].candidate_installed for repo in required_repos
    )
    runtime_aligned = runtime_coverage and all(
        runtimes_by_repo[repo].runtime_aligned for repo in required_repos
    )
    return (
        runtime_coverage,
        tuple(sorted(blockers)),
        candidate_installed,
        runtime_aligned,
    )


def _manifest_document(
    manifest: ReleaseManifest,
    *,
    include_digest: bool,
) -> dict[str, Any]:
    document = {
        "schema_version": manifest.schema_version,
        "repositories": [item.to_dict() for item in manifest.repositories],
        "runtimes": [item.to_dict() for item in manifest.runtimes],
        "dirty_declarations_match": manifest.dirty_declarations_match,
        "candidate_source_committed": manifest.candidate_source_committed,
        "working_trees_clean": manifest.working_trees_clean,
        "runtime_coverage": manifest.runtime_coverage,
        "runtime_blockers": list(manifest.runtime_blockers),
        "candidate_installed": manifest.candidate_installed,
        "runtime_aligned": manifest.runtime_aligned,
        "write_ready": manifest.write_ready,
    }
    if include_digest:
        document["manifest_digest"] = manifest.manifest_digest
    return document


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")


def build_release_manifest(
    repository_specs: Sequence[RepositorySpec],
    runtime_specs: Sequence[RuntimeSpec],
) -> ReleaseManifest:
    repositories = tuple(sorted(repository_specs, key=lambda item: item.repo))
    runtimes = tuple(sorted(runtime_specs, key=lambda item: item.repo))
    if {item.repo for item in repositories} != _REPOSITORIES or len(repositories) != 3:
        raise ValueError(
            "exactly hqa, platform, and hermes repository specs are required"
        )
    runtime_repos = [item.repo for item in runtimes]
    if (
        len(runtimes) > 3
        or len(runtime_repos) != len(set(runtime_repos))
        or any(repo not in _REPOSITORIES for repo in runtime_repos)
    ):
        raise ValueError("runtime specs must contain at most one entry per known repo")

    repository_records = tuple(_capture_repository(spec) for spec in repositories)
    records_by_repo = {record.repo: record for record in repository_records}
    runtime_records = tuple(
        _capture_runtime(spec, records_by_repo[spec.repo]) for spec in runtimes
    )
    dirty_declarations_match = all(
        record.dirty_matches for record in repository_records
    )
    candidate_source_committed = all(
        record.source_identity_matches for record in repository_records
    )
    working_trees_clean = all(
        record.working_tree_clean for record in repository_records
    )
    (
        runtime_coverage,
        runtime_blockers,
        candidate_installed,
        runtime_aligned,
    ) = _derive_runtime_facts(
        repository_records,
        runtime_records,
    )
    write_ready = (
        dirty_declarations_match
        and candidate_source_committed
        and working_trees_clean
        and runtime_coverage
        and candidate_installed
        and runtime_aligned
    )
    unsigned = ReleaseManifest(
        schema_version=1,
        repositories=repository_records,
        runtimes=runtime_records,
        dirty_declarations_match=dirty_declarations_match,
        candidate_source_committed=candidate_source_committed,
        working_trees_clean=working_trees_clean,
        runtime_coverage=runtime_coverage,
        runtime_blockers=runtime_blockers,
        candidate_installed=candidate_installed,
        runtime_aligned=runtime_aligned,
        write_ready=write_ready,
        manifest_digest="",
    )
    digest = hashlib.sha256(
        _canonical_json_bytes(_manifest_document(unsigned, include_digest=False))
    ).hexdigest()
    return ReleaseManifest(
        schema_version=unsigned.schema_version,
        repositories=unsigned.repositories,
        runtimes=unsigned.runtimes,
        dirty_declarations_match=unsigned.dirty_declarations_match,
        candidate_source_committed=unsigned.candidate_source_committed,
        working_trees_clean=unsigned.working_trees_clean,
        runtime_coverage=unsigned.runtime_coverage,
        runtime_blockers=unsigned.runtime_blockers,
        candidate_installed=unsigned.candidate_installed,
        runtime_aligned=unsigned.runtime_aligned,
        write_ready=unsigned.write_ready,
        manifest_digest=digest,
    )


def verify_release_manifest(
    manifest: Any,
    repository_specs: Optional[Sequence[RepositorySpec]] = None,
    runtime_specs: Optional[Sequence[RuntimeSpec]] = None,
) -> ReleaseManifest:
    """Verify schema, derived facts, digest, and optionally fresh Git evidence."""

    if isinstance(manifest, ReleaseManifest):
        parsed = _manifest_from_mapping(manifest.to_dict())
    elif isinstance(manifest, Mapping):
        parsed = _manifest_from_mapping(manifest)
    else:
        raise ManifestValidationError("manifest must be a ReleaseManifest or mapping")

    if [item.repo for item in parsed.repositories] != sorted(_REPOSITORIES):
        raise ManifestValidationError(
            "manifest must contain canonical hermes, hqa, and platform repositories"
        )
    runtime_repos = [item.repo for item in parsed.runtimes]
    if (
        runtime_repos != sorted(runtime_repos)
        or len(runtime_repos) != len(set(runtime_repos))
        or any(repo not in _REPOSITORIES for repo in runtime_repos)
    ):
        raise ManifestValidationError(
            "manifest runtimes must be canonical unique known repositories"
        )
    repositories = {item.repo: item for item in parsed.repositories}
    for record in parsed.repositories:
        expected_dirty_match = (
            record.tracked_dirty == record.declared_tracked_dirty
            and record.untracked_dirty == record.declared_untracked_dirty
        )
        expected_working_tree_clean = (
            not record.tracked_dirty and not record.untracked_dirty
        )
        expected_source_identity_match = (
            record.remote == record.expected_remote
            and record.branch == record.expected_branch
            and record.head_commit == record.expected_head_commit
            and record.base_present
            and record.base_is_ancestor
        )
        if (
            record.dirty_matches != expected_dirty_match
            or record.working_tree_clean != expected_working_tree_clean
            or record.source_identity_matches != expected_source_identity_match
        ):
            raise ManifestIntegrityError("repository derived facts do not agree")

    for runtime in parsed.runtimes:
        repository = repositories[runtime.repo]
        expected_candidate_installed = (
            runtime.installed_commit == repository.head_commit
            and runtime.installed_archive_sha256 == repository.archive_sha256
        )
        expected_runtime_aligned = (
            runtime.running_commit == runtime.installed_commit
            and runtime.running_archive_sha256 == runtime.installed_archive_sha256
        )
        if (
            runtime.candidate_installed != expected_candidate_installed
            or runtime.runtime_aligned != expected_runtime_aligned
        ):
            raise ManifestIntegrityError("runtime derived facts do not agree")

    dirty_declarations_match = all(item.dirty_matches for item in parsed.repositories)
    candidate_source_committed = all(
        item.source_identity_matches for item in parsed.repositories
    )
    working_trees_clean = all(item.working_tree_clean for item in parsed.repositories)
    (
        runtime_coverage,
        runtime_blockers,
        candidate_installed,
        runtime_aligned,
    ) = _derive_runtime_facts(parsed.repositories, parsed.runtimes)
    write_ready = (
        dirty_declarations_match
        and candidate_source_committed
        and working_trees_clean
        and runtime_coverage
        and candidate_installed
        and runtime_aligned
    )
    derived = (
        dirty_declarations_match,
        candidate_source_committed,
        working_trees_clean,
        runtime_coverage,
        runtime_blockers,
        candidate_installed,
        runtime_aligned,
        write_ready,
    )
    declared = (
        parsed.dirty_declarations_match,
        parsed.candidate_source_committed,
        parsed.working_trees_clean,
        parsed.runtime_coverage,
        parsed.runtime_blockers,
        parsed.candidate_installed,
        parsed.runtime_aligned,
        parsed.write_ready,
    )
    if derived != declared:
        raise ManifestIntegrityError("manifest readiness facts do not agree")
    if (
        not isinstance(parsed.manifest_digest, str)
        or _SHA256_RE.fullmatch(parsed.manifest_digest) is None
    ):
        raise ManifestValidationError("manifest_digest must be lowercase SHA-256")
    expected_digest = hashlib.sha256(
        _canonical_json_bytes(_manifest_document(parsed, include_digest=False))
    ).hexdigest()
    if parsed.manifest_digest != expected_digest:
        raise ManifestIntegrityError("manifest digest mismatch")

    if (repository_specs is None) != (runtime_specs is None):
        raise ManifestValidationError(
            "repository_specs and runtime_specs must be supplied together"
        )
    if repository_specs is not None and runtime_specs is not None:
        fresh = build_release_manifest(repository_specs, runtime_specs)
        if fresh.to_json_bytes() != parsed.to_json_bytes():
            raise ManifestIntegrityError("manifest does not match fresh source/runtime")
    return parsed
