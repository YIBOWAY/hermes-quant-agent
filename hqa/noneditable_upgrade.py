"""Published-baseline to final non-editable HQA upgrade rehearsal."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit


class NoneditableUpgradeError(RuntimeError):
    """The release upgrade rehearsal failed closed."""


@dataclass(frozen=True)
class ReleaseAuthority:
    """Immutable repository coordinates required by one upgrade rehearsal."""

    absolute_checkout_path: Path
    branch: str
    publication_remote_name: str
    publication_url: str
    published_baseline: str


CANONICAL_AUTHORITY = ReleaseAuthority(
    absolute_checkout_path=Path(
        "/Users/sunyibo/programs/Hermes-quant-agent/"
        "data/_runtime/agent-v02-work/Hermes-quant-agent"
    ),
    branch="codex/agent-v0-2-release",
    publication_remote_name="github",
    publication_url="https://github.com/YIBOWAY/hermes-quant-agent.git",
    published_baseline="a5589ba0626e76bc99b55bd1a126d578196c51f4",
)
GIT_BINARY = Path("/usr/bin/git")
NETWORK_SANDBOX = Path("/usr/bin/sandbox-exec")
NETWORK_SANDBOX_PROFILE = "(version 1) (allow default) (deny network*)"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _network_guarded(argv: list[str]) -> list[str]:
    if (
        not NETWORK_SANDBOX.is_file()
        or NETWORK_SANDBOX.is_symlink()
        or not os.access(NETWORK_SANDBOX, os.X_OK)
    ):
        raise NoneditableUpgradeError("network-deny sandbox is unavailable")
    return [
        str(NETWORK_SANDBOX),
        "-p",
        NETWORK_SANDBOX_PROFILE,
        *argv,
    ]


def _safe_environment() -> dict[str, str]:
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": os.devnull,
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _git(
    repository_root: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    if (
        not GIT_BINARY.is_file()
        or GIT_BINARY.is_symlink()
        or not os.access(GIT_BINARY, os.X_OK)
    ):
        raise NoneditableUpgradeError("pinned Git executable is unavailable")
    completed = subprocess.run(
        _network_guarded(
            [
                str(GIT_BINARY),
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "credential.helper=",
                "-C",
                str(repository_root),
                *arguments,
            ]
        ),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_safe_environment(),
    )
    if check and completed.returncode != 0:
        raise NoneditableUpgradeError(
            "Git observation failed "
            f"exit={completed.returncode} stderr_sha256={_sha256(completed.stderr)}"
        )
    return completed


def _git_text(repository_root: Path, *arguments: str) -> str:
    return (
        _git(repository_root, *arguments)
        .stdout.decode("utf-8", "strict")
        .strip()
    )


def _canonical_publication_url(raw: str) -> str:
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise NoneditableUpgradeError("publication URL is not canonical")
    normalized = urlunsplit(
        ("https", parsed.hostname, parsed.path, "", "")
    )
    if normalized != raw or not parsed.path.endswith(".git"):
        raise NoneditableUpgradeError("publication URL is not canonical")
    return normalized


def observe_release_identity(
    repository_root: Path,
    authority: ReleaseAuthority = CANONICAL_AUTHORITY,
) -> dict[str, object]:
    """Observe exact, offline Git authority and reject mutable residue."""

    lexical = Path(os.path.abspath(os.fspath(repository_root)))
    try:
        repository_root = lexical.resolve(strict=True)
    except OSError as exc:
        raise NoneditableUpgradeError("canonical checkout does not exist") from exc
    if lexical != repository_root or repository_root != authority.absolute_checkout_path.resolve():
        raise NoneditableUpgradeError("repository is not the canonical checkout")
    top = Path(
        _git_text(repository_root, "rev-parse", "--path-format=absolute", "--show-toplevel")
    ).resolve(strict=True)
    if top != repository_root:
        raise NoneditableUpgradeError("repository is not the canonical checkout")
    branch = _git_text(repository_root, "symbolic-ref", "--short", "HEAD")
    if branch != authority.branch:
        raise NoneditableUpgradeError("release branch identity changed")
    publication_url = _canonical_publication_url(
        _git_text(
            repository_root,
            "remote",
            "get-url",
            authority.publication_remote_name,
        )
    )
    push_url = _canonical_publication_url(
        _git_text(
            repository_root,
            "remote",
            "get-url",
            "--push",
            authority.publication_remote_name,
        )
    )
    if publication_url != authority.publication_url or push_url != authority.publication_url:
        raise NoneditableUpgradeError("publication URL identity changed")
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", authority.published_baseline) is None:
        raise NoneditableUpgradeError("published baseline identity is malformed")
    commit = _git_text(repository_root, "rev-parse", "--verify", "HEAD")
    tree = _git_text(repository_root, "rev-parse", "--verify", "HEAD^{tree}")
    if (
        re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None
        or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", tree) is None
    ):
        raise NoneditableUpgradeError("release commit or tree identity is malformed")
    ancestor = _git(
        repository_root,
        "merge-base",
        "--is-ancestor",
        authority.published_baseline,
        commit,
        check=False,
    )
    if ancestor.returncode != 0:
        raise NoneditableUpgradeError(
            "published baseline is not an ancestor of final commit"
        )
    remote_ref = (
        f"refs/remotes/{authority.publication_remote_name}/{authority.branch}"
    )
    remote_commit = _git_text(
        repository_root,
        "rev-parse",
        "--verify",
        remote_ref,
    )
    if remote_commit != commit:
        raise NoneditableUpgradeError("final commit is not publication-ref bound")
    status = _git(
        repository_root,
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=all",
    ).stdout
    if status:
        raise NoneditableUpgradeError("release checkout is not clean")
    replacements = _git_text(repository_root, "for-each-ref", "--format=%(refname)", "refs/replace")
    if replacements:
        raise NoneditableUpgradeError("Git replacement refs are forbidden")
    hidden: list[str] = []
    listing = _git(repository_root, "ls-files", "-v", "-z").stdout
    if listing and not listing.endswith(b"\0"):
        raise NoneditableUpgradeError("hidden index observation is malformed")
    for record in listing.split(b"\0"):
        if not record:
            continue
        try:
            tag, raw_path = record.split(b" ", 1)
            path = raw_path.decode("utf-8", "strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise NoneditableUpgradeError(
                "hidden index observation is malformed"
            ) from exc
        if tag != b"H":
            hidden.append(path)
    if hidden:
        raise NoneditableUpgradeError("release checkout has hidden index paths")
    return {
        "absolute_checkout_path": str(repository_root),
        "base_is_ancestor": True,
        "branch": branch,
        "commit": commit,
        "hidden_index_paths": [],
        "publication_ref": f"refs/heads/{authority.branch}",
        "publication_remote_name": authority.publication_remote_name,
        "publication_url": publication_url,
        "published_baseline": authority.published_baseline,
        "remote_head_commit": remote_commit,
        "remote_published": True,
        "tree": tree,
        "working_tree_clean": True,
    }


def _wheel_digest(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
    return digest.rstrip(b"=").decode("ascii")


def _wheel_member(path: str, payload: bytes, *, executable: bool) -> tuple[zipfile.ZipInfo, bytes]:
    member = PurePosixPath(path)
    if (
        member.is_absolute()
        or "\\" in path
        or any(part in {"", ".", ".."} for part in member.parts)
    ):
        raise NoneditableUpgradeError("unsafe wheel member path")
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info, payload


def _baseline_package_files(root: Path) -> list[tuple[str, bytes, bool]]:
    package = root / "hqa"
    if package.is_symlink() or not package.is_dir():
        raise NoneditableUpgradeError("published baseline lacks a regular hqa package")
    result: list[tuple[str, bytes, bool]] = []
    for path in sorted(package.rglob("*"), key=lambda item: item.as_posix().encode()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            if path.is_symlink():
                raise NoneditableUpgradeError("baseline package contains a symlink")
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise NoneditableUpgradeError(
                "baseline package contains a non-regular member"
            )
        result.append(
            (
                relative,
                path.read_bytes(),
                bool(stat.S_IMODE(metadata.st_mode) & 0o111),
            )
        )
    if not result or result[0][0] != "hqa/__init__.py":
        raise NoneditableUpgradeError("published baseline package is incomplete")
    return result


def build_baseline_compatibility_wheel(
    baseline_root: Path,
    destination: Path,
    *,
    baseline_commit: str,
) -> dict[str, object]:
    """Build deterministic wheel metadata around exact pre-packaging baseline bytes.

    The published HQA baseline contains a pytest-only ``pyproject.toml`` but no
    PEP 621 project table and no lockfile.  The compatibility metadata is
    therefore generated by the final release authority instead of pretending
    the historical commit had an install contract.
    """

    if re.fullmatch(r"[0-9a-f]{40}", baseline_commit) is None:
        raise NoneditableUpgradeError("published baseline commit is malformed")
    baseline_root = baseline_root.resolve(strict=True)
    pyproject = baseline_root / "pyproject.toml"
    if not pyproject.is_file() or pyproject.is_symlink():
        raise NoneditableUpgradeError("published baseline pytest metadata is missing")
    try:
        baseline_metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise NoneditableUpgradeError(
            "published baseline pyproject is invalid"
        ) from exc
    if "project" in baseline_metadata:
        raise NoneditableUpgradeError(
            "published baseline unexpectedly contains project metadata"
        )
    if (baseline_root / "uv.lock").exists() or (baseline_root / "uv.lock").is_symlink():
        raise NoneditableUpgradeError(
            "published baseline unexpectedly contains a dependency lock"
        )

    destination = Path(os.path.abspath(os.fspath(destination)))
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    destination.chmod(0o700)
    version = f"0+baseline.{baseline_commit[:12]}"
    distribution = "hermes_quant_agent"
    dist_info = f"{distribution}-{version}.dist-info"
    filename = f"{distribution}-{version}-py3-none-any.whl"
    wheel_path = destination / filename
    package_files = _baseline_package_files(baseline_root)
    metadata = (
        "Metadata-Version: 2.3\n"
        "Name: hermes-quant-agent\n"
        f"Version: {version}\n"
        "Requires-Python: >=3.9\n"
        "\n"
    ).encode("utf-8")
    wheel_metadata = (
        "Wheel-Version: 1.0\n"
        "Generator: hqa-noneditable-upgrade\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
        "\n"
    ).encode("utf-8")
    members = [
        *package_files,
        (f"{dist_info}/METADATA", metadata, False),
        (f"{dist_info}/WHEEL", wheel_metadata, False),
    ]
    rows: list[list[str]] = []
    for path, payload, _executable in members:
        rows.append([path, f"sha256={_wheel_digest(payload)}", str(len(payload))])
    record_name = f"{dist_info}/RECORD"
    rows.append([record_name, "", ""])
    record_buffer = io.StringIO(newline="")
    csv.writer(record_buffer, lineterminator="\n").writerows(rows)
    record = record_buffer.getvalue().encode("utf-8")

    try:
        descriptor = os.open(
            wheel_path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise NoneditableUpgradeError(
            "refusing to replace baseline compatibility wheel"
        ) from exc
    with os.fdopen(descriptor, "wb") as raw:
        with zipfile.ZipFile(raw, mode="w") as archive:
            for path, payload, executable in members:
                archive.writestr(
                    *_wheel_member(path, payload, executable=executable)
                )
            archive.writestr(
                *_wheel_member(record_name, record, executable=False)
            )
        raw.flush()
        os.fsync(raw.fileno())

    source_inventory = [
        {
            "bytes": len(payload),
            "executable": executable,
            "path": path,
            "sha256": _sha256(payload),
        }
        for path, payload, executable in package_files
    ]
    return {
        "baseline_lock_present": False,
        "baseline_project_metadata_present": False,
        "compatibility_metadata_generated": True,
        "path": str(wheel_path),
        "sha256": _sha256(wheel_path.read_bytes()),
        "source_inventory_sha256": _sha256(
            _canonical_json_bytes(source_inventory)
        ),
        "version": version,
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _required_probe_path(document: dict[str, Any], key: str) -> Path:
    value = document.get(key)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise NoneditableUpgradeError(f"import probe lacks a valid {key}")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise NoneditableUpgradeError(f"import probe {key} is not absolute")
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise NoneditableUpgradeError(
            f"import probe {key} does not resolve"
        ) from exc


def _wheel_package_inventory(wheel: Path) -> tuple[int, str]:
    inventory: list[dict[str, object]] = []
    try:
        with zipfile.ZipFile(wheel) as archive:
            members = sorted(
                (
                    member
                    for member in archive.infolist()
                    if not member.is_dir()
                    and PurePosixPath(member.filename).parts[:1] == ("hqa",)
                ),
                key=lambda member: member.filename.encode("utf-8"),
            )
            for member in members:
                relative = PurePosixPath(member.filename)
                if (
                    relative.is_absolute()
                    or "\\" in member.filename
                    or any(part in {"", ".", ".."} for part in relative.parts)
                ):
                    raise NoneditableUpgradeError(
                        "wheel package inventory contains an unsafe path"
                    )
                payload = archive.read(member)
                inventory.append(
                    {
                        "bytes": len(payload),
                        "path": PurePosixPath(*relative.parts[1:]).as_posix(),
                        "sha256": _sha256(payload),
                    }
                )
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise NoneditableUpgradeError("expected wheel is unreadable") from exc
    if not inventory:
        raise NoneditableUpgradeError("expected wheel has no hqa package")
    return len(inventory), _sha256(_canonical_json_bytes(inventory))


def validate_noneditable_probe(
    document: dict[str, Any],
    *,
    environment_root: Path,
    expected_version: str,
    expected_wheel: Path,
    forbidden_source_roots: tuple[Path, ...],
) -> dict[str, bool]:
    """Validate that an import came only from the exact installed wheel."""

    expected_fields = {
        "direct_url",
        "distribution",
        "installed_file_count",
        "installed_tree_sha256",
        "module",
        "pth",
        "pythonpath",
        "site_packages",
        "symlink_components",
        "sys_executable",
        "sys_path",
        "version",
    }
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise NoneditableUpgradeError("non-editable import probe fields are not closed")
    environment_root = environment_root.resolve(strict=True)
    expected_python = (environment_root / "bin/python").resolve(strict=True)
    site_packages = _required_probe_path(document, "site_packages")
    module = _required_probe_path(document, "module")
    distribution = _required_probe_path(document, "distribution")
    executable = _required_probe_path(document, "sys_executable")
    if executable != expected_python:
        raise NoneditableUpgradeError("import probe used the wrong interpreter")
    if not _is_within(site_packages, environment_root):
        raise NoneditableUpgradeError("site-packages escaped the upgrade environment")
    if (
        not _is_within(module, site_packages)
        or not _is_within(distribution, site_packages)
        or module.name != "__init__.py"
        or module.parent.name != "hqa"
    ):
        raise NoneditableUpgradeError("import did not resolve from installed hqa")
    if document["version"] != expected_version:
        raise NoneditableUpgradeError("installed distribution version is unexpected")
    if document["pythonpath"] is not None:
        raise NoneditableUpgradeError("PYTHONPATH reached the import probe")
    pth = document["pth"]
    if not isinstance(pth, list) or pth:
        raise NoneditableUpgradeError("site-packages contains a .pth injection surface")
    symlinks = document["symlink_components"]
    if not isinstance(symlinks, list) or symlinks:
        raise NoneditableUpgradeError("installed identity traverses a symlink")
    sys_path = document["sys_path"]
    if (
        not isinstance(sys_path, list)
        or not all(isinstance(value, str) and value for value in sys_path)
        or str(site_packages) not in sys_path
    ):
        raise NoneditableUpgradeError("isolated import path is malformed")
    resolved_forbidden = tuple(root.resolve() for root in forbidden_source_roots)
    if any(_is_within(module, root) for root in resolved_forbidden):
        raise NoneditableUpgradeError("import resolved from a source checkout")
    for raw_path in sys_path:
        candidate = Path(raw_path)
        if candidate.is_absolute() and any(
            _is_within(candidate, root) for root in resolved_forbidden
        ):
            raise NoneditableUpgradeError("source checkout leaked into sys.path")
    if (
        not isinstance(document["installed_file_count"], int)
        or isinstance(document["installed_file_count"], bool)
        or document["installed_file_count"] <= 0
        or not isinstance(document["installed_tree_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", document["installed_tree_sha256"])
        is None
    ):
        raise NoneditableUpgradeError("installed package inventory is malformed")
    expected_count, expected_tree = _wheel_package_inventory(expected_wheel)
    if (
        document["installed_file_count"] != expected_count
        or document["installed_tree_sha256"] != expected_tree
    ):
        raise NoneditableUpgradeError("installed package bytes do not match wheel")
    direct_url = document["direct_url"]
    raw_wheel_url = direct_url.get("url") if isinstance(direct_url, dict) else None
    parsed_wheel_url = urlsplit(raw_wheel_url) if isinstance(raw_wheel_url, str) else None
    if (
        not isinstance(direct_url, dict)
        or parsed_wheel_url is None
        or parsed_wheel_url.scheme != "file"
        or parsed_wheel_url.netloc
        or parsed_wheel_url.query
        or parsed_wheel_url.fragment
        or Path(unquote(parsed_wheel_url.path)).resolve(strict=True)
        != expected_wheel.resolve(strict=True)
    ):
        raise NoneditableUpgradeError("installed distribution is not wheel-bound")
    if direct_url.get("dir_info", {}).get("editable") is True:
        raise NoneditableUpgradeError("installed distribution is editable")
    archive_info = direct_url.get("archive_info")
    expected_hash = f"sha256={_sha256(expected_wheel.read_bytes())}"
    if (
        not isinstance(archive_info, dict)
        or (
            archive_info.get("hash") not in {None, expected_hash}
            or set(archive_info) - {"hash", "hashes"}
        )
    ):
        raise NoneditableUpgradeError("installed distribution wheel hash changed")
    hashes = archive_info.get("hashes")
    if hashes is not None and (
        not isinstance(hashes, dict)
        or hashes.get("sha256") != expected_hash.removeprefix("sha256=")
    ):
        raise NoneditableUpgradeError("installed distribution wheel hashes changed")
    return {
        "editable": False,
        "isolated": True,
        "source_root_import": False,
        "source_root_pth": False,
        "symlink_free": True,
        "wheel_bound": True,
    }


def _private_directory(path: Path, *, create: bool = True) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path)))
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise NoneditableUpgradeError("private output traverses a symlink")
        if current != candidate and not stat.S_ISDIR(metadata.st_mode):
            raise NoneditableUpgradeError("private output parent is not a directory")
    if create:
        candidate.mkdir(mode=0o700, parents=True, exist_ok=False)
    metadata = candidate.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise NoneditableUpgradeError("private output must be owner-only mode 0700")
    return candidate


def _write_private(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise NoneditableUpgradeError(
            "refusing to replace private upgrade evidence"
        ) from exc
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise NoneditableUpgradeError("short private evidence write")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _command_log(
    *,
    argv: list[str],
    completed: subprocess.CompletedProcess[bytes],
) -> dict[str, object]:
    return {
        "argv": argv,
        "exit_code": completed.returncode,
        "raw_output_persisted": False,
        "stderr_bytes": len(completed.stderr),
        "stderr_sha256": _sha256(completed.stderr),
        "stdout_bytes": len(completed.stdout),
        "stdout_sha256": _sha256(completed.stdout),
        "stdout_stderr_bytes": len(completed.stdout) + len(completed.stderr),
        "stdout_stderr_sha256": _sha256(completed.stdout + completed.stderr),
    }


def _run_upgrade_command(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    log_path: Path,
) -> tuple[dict[str, object], bytes, bytes]:
    guarded = _network_guarded(argv)
    completed = subprocess.run(
        guarded,
        cwd=cwd,
        env=environment,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    facts = _command_log(argv=guarded, completed=completed)
    facts["log_path"] = str(log_path)
    _write_private(log_path, _canonical_json_bytes(facts))
    if completed.returncode != 0:
        raise NoneditableUpgradeError(
            f"upgrade command failed: {log_path.name}"
        )
    return facts, completed.stdout, completed.stderr


def _isolated_environment(
    output_dir: Path,
    *,
    uv_binary: Path,
    python_binary: Path,
) -> tuple[dict[str, str], dict[str, object]]:
    runtime = _private_directory(output_dir / "execution-environment")
    paths: dict[str, Path] = {}
    for name, relative in (
        ("HOME", "home"),
        ("TMPDIR", "tmp"),
        ("TMP", "tmp-shared"),
        ("TEMP", "temp"),
        ("XDG_CACHE_HOME", "xdg-cache"),
        ("PYTHONPYCACHEPREFIX", "pycache"),
        ("UV_CACHE_DIR", "uv-cache"),
    ):
        paths[name] = _private_directory(runtime / relative)
    sensitive_names = sorted(
        name
        for name in os.environ
        if re.search(
            r"(?:API_KEY|TOKEN|SECRET|PASSWORD|BROKER|FUTU|TIINGO|"
            r"OPENAI|ANTHROPIC|DATABASE_URL)",
            name,
            re.IGNORECASE,
        )
    )
    path_entries = {
        str(uv_binary.parent.resolve()),
        str(python_binary.parent.resolve()),
        "/usr/bin",
        "/bin",
    }
    environment = {
        "COLUMNS": "120",
        "HQA_PROVIDER_ACCESS": "disabled",
        "HOME": str(paths["HOME"]),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "PATH": ":".join(sorted(path_entries)),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": str(paths["PYTHONPYCACHEPREFIX"]),
        "QS_DATABASE_AUTO_MIGRATE": "false",
        "QS_KILL_SWITCH": "true",
        "QS_LIVE_TRADING_ENABLED": "false",
        "TEMP": str(paths["TEMP"]),
        "TERM": "dumb",
        "TMP": str(paths["TMP"]),
        "TMPDIR": str(paths["TMPDIR"]),
        "UV_CACHE_DIR": str(paths["UV_CACHE_DIR"]),
        "UV_NO_CONFIG": "1",
        "UV_OFFLINE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "XDG_CACHE_HOME": str(paths["XDG_CACHE_HOME"]),
    }
    return environment, {
        "credential_like_names_removed": sensitive_names,
        "environment_variable_names": sorted(environment),
        "network": "denied",
        "private_paths": {name: str(path) for name, path in paths.items()},
        "provider_or_trading_credentials_inherited": False,
        "sandbox": str(NETWORK_SANDBOX),
        "sandbox_profile_sha256": _sha256(
            NETWORK_SANDBOX_PROFILE.encode("utf-8")
        ),
    }


def _safe_extract_archive(payload: bytes, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    root = destination.resolve(strict=True)
    total_bytes = 0
    file_count = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for member in archive:
            raw = member.name.rstrip("/")
            relative = PurePosixPath(raw)
            if (
                not raw
                or relative.is_absolute()
                or "\\" in raw
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise NoneditableUpgradeError("Git archive contains an unsafe path")
            target = root.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.chmod(0o700)
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise NoneditableUpgradeError(
                    "Git archive contains a non-regular member"
                )
            extracted = archive.extractfile(member)
            if extracted is None:
                raise NoneditableUpgradeError("Git archive member is unreadable")
            content = extracted.read(256 * 1024 * 1024 + 1)
            total_bytes += len(content)
            file_count += 1
            if (
                len(content) > 256 * 1024 * 1024
                or total_bytes > 512 * 1024 * 1024
                or file_count > 100_000
            ):
                raise NoneditableUpgradeError("Git archive exceeds safety bounds")
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _write_private(target, content)
            target.chmod(0o700 if member.mode & 0o111 else 0o600)


def _archive_commit(
    repository_root: Path,
    commit: str,
    *,
    destination: Path,
    archive_path: Path,
) -> dict[str, object]:
    completed = _git(
        repository_root,
        "archive",
        "--format=tar",
        commit,
    )
    _write_private(archive_path, completed.stdout)
    _safe_extract_archive(completed.stdout, destination)
    return {
        "archive_bytes": len(completed.stdout),
        "archive_path": str(archive_path),
        "archive_sha256": _sha256(completed.stdout),
        "commit": commit,
    }


def _final_project_facts(root: Path) -> dict[str, object]:
    pyproject = root / "pyproject.toml"
    lock = root / "uv.lock"
    if (
        not pyproject.is_file()
        or pyproject.is_symlink()
        or not lock.is_file()
        or lock.is_symlink()
    ):
        raise NoneditableUpgradeError("final archive lacks project metadata or lock")
    try:
        project_document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        lock_document = tomllib.loads(lock.read_text(encoding="utf-8"))
        project = project_document["project"]
        name = project["name"]
        version = project["version"]
        requires_python = project["requires-python"]
        dependencies = project["dependencies"]
        packages = lock_document["package"]
    except (KeyError, OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise NoneditableUpgradeError("final package authority is malformed") from exc
    if (
        name != "hermes-quant-agent"
        or not isinstance(version, str)
        or not version
        or requires_python != ">=3.11"
        or dependencies != []
        or not isinstance(packages, list)
    ):
        raise NoneditableUpgradeError("final package authority changed")
    matches = [
        package
        for package in packages
        if isinstance(package, dict)
        and package.get("name") == name
        and package.get("version") == version
    ]
    if len(matches) != 1 or matches[0].get("source") != {"editable": "."}:
        raise NoneditableUpgradeError("final lock does not bind the project")
    return {
        "dependencies": [],
        "name": name,
        "pyproject_sha256": _sha256(pyproject.read_bytes()),
        "requires_python": requires_python,
        "uv_lock_sha256": _sha256(lock.read_bytes()),
        "version": version,
    }


def _build_final_wheel(
    final_root: Path,
    destination: Path,
    *,
    project: dict[str, object],
) -> dict[str, object]:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    destination.chmod(0o700)
    version = str(project["version"])
    dist_info = f"hermes_quant_agent-{version}.dist-info"
    wheel_path = destination / f"hermes_quant_agent-{version}-py3-none-any.whl"
    package_files = _baseline_package_files(final_root)
    metadata = (
        "Metadata-Version: 2.3\n"
        "Name: hermes-quant-agent\n"
        f"Version: {version}\n"
        f"Requires-Python: {project['requires_python']}\n"
        "\n"
    ).encode("utf-8")
    wheel_metadata = (
        "Wheel-Version: 1.0\n"
        "Generator: hqa-noneditable-upgrade\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
        "\n"
    ).encode("utf-8")
    members = [
        *package_files,
        (f"{dist_info}/METADATA", metadata, False),
        (f"{dist_info}/WHEEL", wheel_metadata, False),
    ]
    rows = [
        [path, f"sha256={_wheel_digest(payload)}", str(len(payload))]
        for path, payload, _executable in members
    ]
    record_name = f"{dist_info}/RECORD"
    rows.append([record_name, "", ""])
    record_buffer = io.StringIO(newline="")
    csv.writer(record_buffer, lineterminator="\n").writerows(rows)
    record = record_buffer.getvalue().encode("utf-8")
    try:
        descriptor = os.open(
            wheel_path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise NoneditableUpgradeError(
            "refusing to replace final wheel"
        ) from exc
    with os.fdopen(descriptor, "wb") as raw:
        with zipfile.ZipFile(raw, mode="w") as archive:
            for path, payload, executable in members:
                archive.writestr(
                    *_wheel_member(path, payload, executable=executable)
                )
            archive.writestr(
                *_wheel_member(record_name, record, executable=False)
            )
        raw.flush()
        os.fsync(raw.fileno())
    source_inventory = [
        {
            "bytes": len(payload),
            "executable": executable,
            "path": path,
            "sha256": _sha256(payload),
        }
        for path, payload, executable in package_files
    ]
    return {
        "bytes": wheel_path.stat().st_size,
        "path": str(wheel_path),
        "sha256": _sha256(wheel_path.read_bytes()),
        "source_inventory_sha256": _sha256(
            _canonical_json_bytes(source_inventory)
        ),
        "version": version,
    }


def _venv_environment(
    environment: dict[str, str],
    root: Path,
) -> dict[str, str]:
    result = dict(environment)
    result["VIRTUAL_ENV"] = str(root.resolve(strict=True))
    result["UV_PROJECT_ENVIRONMENT"] = str(root.resolve(strict=True))
    return result


def _create_environment(
    *,
    base_python: Path,
    root: Path,
    cwd: Path,
    environment: dict[str, str],
    log_path: Path,
) -> tuple[dict[str, object], Path, dict[str, str]]:
    facts, _stdout, _stderr = _run_upgrade_command(
        [
            str(base_python),
            "-I",
            "-B",
            "-m",
            "venv",
            "--copies",
            "--without-pip",
            str(root),
        ],
        cwd=cwd,
        environment=environment,
        log_path=log_path,
    )
    root.chmod(0o700)
    python = root / "bin/python"
    if (
        not python.is_file()
        or python.is_symlink()
        or not os.access(python, os.X_OK)
    ):
        raise NoneditableUpgradeError(
            "virtual environment Python is not an independent copy"
        )
    facts["python"] = str(python.resolve(strict=True))
    facts["python_sha256"] = _sha256(python.read_bytes())
    return facts, python, _venv_environment(environment, root)


def _probe_script() -> str:
    return r'''
import hashlib
import importlib.metadata as metadata
import json
import os
import stat
import sys
import sysconfig
from pathlib import Path

module = Path(__import__("hqa").__file__).resolve(strict=True)
site_packages = Path(sysconfig.get_path("purelib")).resolve(strict=True)
matches = [
    item for item in metadata.distributions()
    if (item.metadata.get("Name") or "").lower() == "hermes-quant-agent"
]
if len(matches) != 1:
    raise SystemExit(70)
distribution = matches[0]
distribution_path = Path(distribution._path).resolve(strict=True)
direct_url_path = distribution_path / "direct_url.json"
direct_url = json.loads(direct_url_path.read_text(encoding="utf-8"))
pth = [
    {"path": str(path.resolve(strict=True)), "text": path.read_text(encoding="utf-8")}
    for path in sorted(site_packages.glob("*.pth"))
]

def symlink_components(path):
    absolute = Path(path).absolute()
    current = Path(absolute.anchor)
    result = []
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            result.append(str(current))
    return result

package_root = module.parent
inventory = []
for path in sorted(package_root.rglob("*")):
    if path.is_dir():
        continue
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise SystemExit(71)
    payload = path.read_bytes()
    inventory.append({
        "bytes": len(payload),
        "path": path.relative_to(package_root).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    })
tree = hashlib.sha256(
    json.dumps(inventory, separators=(",", ":"), sort_keys=True).encode()
).hexdigest()
document = {
    "direct_url": direct_url,
    "distribution": str(distribution_path),
    "installed_file_count": len(inventory),
    "installed_tree_sha256": tree,
    "module": str(module),
    "pth": pth,
    "pythonpath": os.environ.get("PYTHONPATH"),
    "site_packages": str(site_packages),
    "symlink_components": sorted(set(
        symlink_components(sys.executable)
        + symlink_components(module)
        + symlink_components(distribution_path)
        + symlink_components(site_packages)
    )),
    "sys_executable": str(Path(sys.executable).resolve(strict=True)),
    "sys_path": [str(Path(value).resolve()) for value in sys.path if value],
    "version": distribution.version,
}
print(json.dumps(document, separators=(",", ":"), sort_keys=True))
'''


def _run_probe(
    *,
    python: Path,
    environment_root: Path,
    cwd: Path,
    environment: dict[str, str],
    expected_version: str,
    expected_wheel: Path,
    forbidden_source_roots: tuple[Path, ...],
    log_path: Path,
) -> tuple[dict[str, Any], dict[str, bool], dict[str, object]]:
    script = _probe_script()
    guarded = _network_guarded([str(python), "-I", "-B", "-c", script])
    completed = subprocess.run(
        guarded,
        cwd=cwd,
        env=environment,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    safe_argv = [
        *guarded[:-1],
        f"<probe-script-sha256:{_sha256(script.encode('utf-8'))}>",
    ]
    command = _command_log(argv=safe_argv, completed=completed)
    command["log_path"] = str(log_path)
    if completed.returncode != 0:
        _write_private(log_path, _canonical_json_bytes({"command": command}))
        raise NoneditableUpgradeError(
            f"non-editable import probe failed: {log_path.name}"
        )
    try:
        document = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _write_private(log_path, _canonical_json_bytes({"command": command}))
        raise NoneditableUpgradeError(
            "non-editable import probe output is invalid"
        ) from exc
    try:
        validation = validate_noneditable_probe(
            document,
            environment_root=environment_root,
            expected_version=expected_version,
            expected_wheel=expected_wheel,
            forbidden_source_roots=forbidden_source_roots,
        )
    except NoneditableUpgradeError as exc:
        _write_private(
            log_path,
            _canonical_json_bytes(
                {
                    "command": command,
                    "probe": document,
                    "validation": {"error": str(exc), "status": "rejected"},
                }
            ),
        )
        raise
    _write_private(
        log_path,
        _canonical_json_bytes(
            {
                "command": command,
                "probe": document,
                "validation": validation,
            }
        ),
    )
    return document, validation, command


def _sync_final_dependencies(
    *,
    uv_binary: Path,
    final_root: Path,
    environment: dict[str, str],
    log_path: Path,
    inexact: bool,
) -> dict[str, object]:
    argv = [
        str(uv_binary),
        "sync",
        "--frozen",
        "--offline",
    ]
    if inexact:
        argv.append("--inexact")
    argv.extend(
        [
            "--no-dev",
            "--no-editable",
            "--no-install-project",
            "--active",
            "--no-python-downloads",
        ]
    )
    facts, _stdout, _stderr = _run_upgrade_command(
        argv,
        cwd=final_root,
        environment=environment,
        log_path=log_path,
    )
    return facts


def _install_wheel(
    *,
    uv_binary: Path,
    python: Path,
    wheel: Path,
    cwd: Path,
    environment: dict[str, str],
    log_path: Path,
) -> dict[str, object]:
    facts, _stdout, _stderr = _run_upgrade_command(
        [
            str(uv_binary),
            "pip",
            "install",
            "--offline",
            "--python",
            str(python),
            "--reinstall",
            "--no-deps",
            str(wheel),
        ],
        cwd=cwd,
        environment=environment,
        log_path=log_path,
    )
    return facts


def _dependency_check(
    *,
    uv_binary: Path,
    python: Path,
    cwd: Path,
    environment: dict[str, str],
    log_path: Path,
) -> dict[str, object]:
    facts, _stdout, _stderr = _run_upgrade_command(
        [
            str(uv_binary),
            "pip",
            "check",
            "--offline",
            "--python",
            str(python),
            "--no-python-downloads",
        ],
        cwd=cwd,
        environment=environment,
        log_path=log_path,
    )
    return facts


def _inventory(
    *,
    uv_binary: Path,
    python: Path,
    cwd: Path,
    environment: dict[str, str],
    log_path: Path,
) -> tuple[dict[str, object], bytes]:
    facts, stdout, _stderr = _run_upgrade_command(
        [
            str(uv_binary),
            "pip",
            "freeze",
            "--strict",
            "--offline",
            "--python",
            str(python),
            "--no-python-downloads",
        ],
        cwd=cwd,
        environment=environment,
        log_path=log_path,
    )
    return facts, stdout


def _cli_smoke(
    *,
    python: Path,
    cwd: Path,
    environment: dict[str, str],
    log_path: Path,
) -> tuple[dict[str, object], bytes, bytes]:
    return _run_upgrade_command(
        [
            str(python),
            "-I",
            "-B",
            "-m",
            "hqa.noneditable_upgrade_cli",
            "--help",
        ],
        cwd=cwd,
        environment=environment,
        log_path=log_path,
    )


def verify_noneditable_upgrade(
    *,
    repository_root: Path,
    output_dir: Path,
    authority: ReleaseAuthority = CANONICAL_AUTHORITY,
    python_binary: Path | None = None,
    uv_binary: Path | None = None,
    bootstrap_authority: dict[str, object] | None = None,
) -> dict[str, object]:
    """Run one exact offline baseline-to-final upgrade and fresh-final control."""

    repository_root = Path(os.path.abspath(os.fspath(repository_root)))
    output_candidate = Path(os.path.abspath(os.fspath(output_dir)))
    if _is_within(output_candidate, repository_root):
        raise NoneditableUpgradeError(
            "upgrade evidence must be outside the release checkout"
        )
    output_dir = _private_directory(output_candidate)
    receipt_path = output_dir / "noneditable-upgrade-receipt.json"
    work = _private_directory(output_dir / "work")
    identity_before = observe_release_identity(repository_root, authority)
    final_commit = str(identity_before["commit"])
    if bootstrap_authority is None:
        if authority == CANONICAL_AUTHORITY:
            raise NoneditableUpgradeError(
                "canonical rehearsal requires commit-bound bootstrap authority"
            )
        bootstrap_identity_bound = False
    else:
        if (
            bootstrap_authority.get("schema_version")
            != "hqa.noneditable-upgrade-bootstrap.v1"
            or bootstrap_authority.get("repository_root")
            != str(repository_root.resolve(strict=True))
            or bootstrap_authority.get("commit") != identity_before["commit"]
            or bootstrap_authority.get("tree") != identity_before["tree"]
        ):
            raise NoneditableUpgradeError(
                "commit-bound bootstrap identity does not match release checkout"
            )
        bootstrap_identity_bound = True

    uv = Path(
        uv_binary
        or os.environ.get("HQA_UPGRADE_UV", "/opt/homebrew/bin/uv")
    ).resolve(strict=True)
    if uv.is_symlink() or not uv.is_file() or not os.access(uv, os.X_OK):
        raise NoneditableUpgradeError("uv executable is unavailable")
    if python_binary is None:
        candidate = Path(
            os.environ.get(
                "HQA_UPGRADE_PYTHON",
                "/Users/sunyibo/.local/bin/python3.11",
            )
        )
    else:
        candidate = Path(python_binary)
    python = candidate.resolve(strict=True)
    if not python.is_file() or not os.access(python, os.X_OK):
        raise NoneditableUpgradeError("Python 3.11 executable is unavailable")
    environment, isolation = _isolated_environment(
        output_dir,
        uv_binary=uv,
        python_binary=python,
    )
    python_version, python_stdout, python_stderr = _run_upgrade_command(
        [str(python), "--version"],
        cwd=work,
        environment=environment,
        log_path=output_dir / "python-version.log",
    )
    uv_version, _stdout, _stderr = _run_upgrade_command(
        [str(uv), "--version"],
        cwd=work,
        environment=environment,
        log_path=output_dir / "uv-version.log",
    )
    try:
        rendered_python_version = (python_stdout + python_stderr).decode(
            "ascii", "strict"
        ).strip()
    except UnicodeDecodeError as exc:
        raise NoneditableUpgradeError(
            "Python version output is malformed"
        ) from exc
    if re.fullmatch(r"Python 3\.11\.[0-9]+", rendered_python_version) is None:
        raise NoneditableUpgradeError("upgrade rehearsal requires Python 3.11")

    baseline_root = work / "baseline"
    final_root = work / "final"
    baseline_archive = _archive_commit(
        repository_root,
        authority.published_baseline,
        destination=baseline_root,
        archive_path=work / "baseline.tar",
    )
    final_archive = _archive_commit(
        repository_root,
        final_commit,
        destination=final_root,
        archive_path=work / "final.tar",
    )
    final_project = _final_project_facts(final_root)
    baseline_wheel = build_baseline_compatibility_wheel(
        baseline_root,
        work / "baseline-dist",
        baseline_commit=authority.published_baseline,
    )
    final_wheel = _build_final_wheel(
        final_root,
        work / "final-dist",
        project=final_project,
    )
    baseline_wheel_path = Path(str(baseline_wheel["path"]))
    final_wheel_path = Path(str(final_wheel["path"]))
    if baseline_wheel["source_inventory_sha256"] == final_wheel["source_inventory_sha256"]:
        raise NoneditableUpgradeError("baseline and final package trees are identical")

    neutral = _private_directory(work / "neutral")
    forbidden = (
        (repository_root / "hqa").resolve(strict=True),
        (baseline_root / "hqa").resolve(strict=True),
        (final_root / "hqa").resolve(strict=True),
    )
    upgrade_root = baseline_root / ".upgrade-venv"
    (
        upgrade_environment_create,
        upgrade_python,
        upgrade_environment,
    ) = _create_environment(
        base_python=python,
        root=upgrade_root,
        cwd=baseline_root,
        environment=environment,
        log_path=output_dir / "upgrade-environment-create.log",
    )
    baseline_install = _install_wheel(
        uv_binary=uv,
        python=upgrade_python,
        wheel=baseline_wheel_path,
        cwd=neutral,
        environment=upgrade_environment,
        log_path=output_dir / "baseline-wheel-install.log",
    )
    (
        baseline_import,
        baseline_import_validation,
        baseline_import_command,
    ) = _run_probe(
        python=upgrade_python,
        environment_root=upgrade_root,
        cwd=neutral,
        environment=upgrade_environment,
        expected_version=str(baseline_wheel["version"]),
        expected_wheel=baseline_wheel_path,
        forbidden_source_roots=forbidden,
        log_path=output_dir / "baseline-import.log",
    )
    final_sync = _sync_final_dependencies(
        uv_binary=uv,
        final_root=final_root,
        environment=upgrade_environment,
        log_path=output_dir / "final-dependency-sync.log",
        inexact=True,
    )
    (
        after_sync_import,
        after_sync_validation,
        after_sync_command,
    ) = _run_probe(
        python=upgrade_python,
        environment_root=upgrade_root,
        cwd=neutral,
        environment=upgrade_environment,
        expected_version=str(baseline_wheel["version"]),
        expected_wheel=baseline_wheel_path,
        forbidden_source_roots=forbidden,
        log_path=output_dir / "after-final-sync-import.log",
    )
    continuity_fields = (
        "direct_url",
        "distribution",
        "installed_file_count",
        "installed_tree_sha256",
        "module",
        "site_packages",
        "sys_executable",
        "version",
    )
    if any(
        after_sync_import[field] != baseline_import[field]
        for field in continuity_fields
    ):
        raise NoneditableUpgradeError(
            "final dependency synchronization replaced baseline distribution"
        )
    upgrade = _install_wheel(
        uv_binary=uv,
        python=upgrade_python,
        wheel=final_wheel_path,
        cwd=neutral,
        environment=upgrade_environment,
        log_path=output_dir / "final-upgrade.log",
    )
    upgraded_check = _dependency_check(
        uv_binary=uv,
        python=upgrade_python,
        cwd=neutral,
        environment=upgrade_environment,
        log_path=output_dir / "upgraded-final-pip-check.log",
    )
    upgraded_inventory, upgraded_inventory_bytes = _inventory(
        uv_binary=uv,
        python=upgrade_python,
        cwd=neutral,
        environment=upgrade_environment,
        log_path=output_dir / "upgraded-final-pip-freeze.log",
    )
    (
        upgraded_import,
        upgraded_validation,
        upgraded_import_command,
    ) = _run_probe(
        python=upgrade_python,
        environment_root=upgrade_root,
        cwd=neutral,
        environment=upgrade_environment,
        expected_version=str(final_project["version"]),
        expected_wheel=final_wheel_path,
        forbidden_source_roots=forbidden,
        log_path=output_dir / "upgraded-final-import.log",
    )
    (
        upgraded_cli,
        upgraded_cli_stdout,
        upgraded_cli_stderr,
    ) = _cli_smoke(
        python=upgrade_python,
        cwd=neutral,
        environment=upgrade_environment,
        log_path=output_dir / "upgraded-final-cli.log",
    )

    fresh_root = final_root / ".fresh-venv"
    (
        fresh_environment_create,
        fresh_python,
        fresh_environment,
    ) = _create_environment(
        base_python=python,
        root=fresh_root,
        cwd=final_root,
        environment=environment,
        log_path=output_dir / "fresh-environment-create.log",
    )
    fresh_sync = _sync_final_dependencies(
        uv_binary=uv,
        final_root=final_root,
        environment=fresh_environment,
        log_path=output_dir / "fresh-final-dependency-sync.log",
        inexact=False,
    )
    fresh_install = _install_wheel(
        uv_binary=uv,
        python=fresh_python,
        wheel=final_wheel_path,
        cwd=neutral,
        environment=fresh_environment,
        log_path=output_dir / "fresh-final-wheel-install.log",
    )
    fresh_check = _dependency_check(
        uv_binary=uv,
        python=fresh_python,
        cwd=neutral,
        environment=fresh_environment,
        log_path=output_dir / "fresh-final-pip-check.log",
    )
    fresh_inventory, fresh_inventory_bytes = _inventory(
        uv_binary=uv,
        python=fresh_python,
        cwd=neutral,
        environment=fresh_environment,
        log_path=output_dir / "fresh-final-pip-freeze.log",
    )
    fresh_import, fresh_validation, fresh_import_command = _run_probe(
        python=fresh_python,
        environment_root=fresh_root,
        cwd=neutral,
        environment=fresh_environment,
        expected_version=str(final_project["version"]),
        expected_wheel=final_wheel_path,
        forbidden_source_roots=forbidden,
        log_path=output_dir / "fresh-final-import.log",
    )
    fresh_cli, fresh_cli_stdout, fresh_cli_stderr = _cli_smoke(
        python=fresh_python,
        cwd=neutral,
        environment=fresh_environment,
        log_path=output_dir / "fresh-final-cli.log",
    )
    equivalent_fields = (
        "direct_url",
        "installed_file_count",
        "installed_tree_sha256",
        "pth",
        "version",
    )
    if any(
        upgraded_import[field] != fresh_import[field]
        for field in equivalent_fields
    ):
        raise NoneditableUpgradeError(
            "upgraded and fresh final environments differ"
        )
    if upgraded_inventory_bytes != fresh_inventory_bytes:
        raise NoneditableUpgradeError(
            "upgraded and fresh dependency inventories differ"
        )
    if (
        upgraded_cli_stdout != fresh_cli_stdout
        or upgraded_cli_stderr != fresh_cli_stderr
    ):
        raise NoneditableUpgradeError(
            "upgraded and fresh CLI smoke output differs"
        )
    if upgraded_import["installed_tree_sha256"] == baseline_import["installed_tree_sha256"]:
        raise NoneditableUpgradeError("installed baseline and final trees are identical")
    identity_after = observe_release_identity(repository_root, authority)
    if identity_after != identity_before:
        raise NoneditableUpgradeError(
            "release repository identity changed during upgrade rehearsal"
        )

    receipt: dict[str, object] = {
        "after_final_sync_import": after_sync_import,
        "after_final_sync_import_command": after_sync_command,
        "after_final_sync_import_validation": after_sync_validation,
        "baseline_archive": baseline_archive,
        "baseline_cli_smoke": {
            "reason": (
                "published baseline has no project metadata, lock, or "
                "repository-authoritative CLI install contract"
            ),
            "status": "not_required_before_upgrade",
        },
        "baseline_import": baseline_import,
        "baseline_import_command": baseline_import_command,
        "baseline_import_validation": baseline_import_validation,
        "baseline_is_ancestor": True,
        "baseline_wheel": baseline_wheel,
        "baseline_wheel_install": baseline_install,
        "bootstrap_authority": bootstrap_authority,
        "bootstrap_identity_bound": bootstrap_identity_bound,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "final_archive": final_archive,
        "final_cli_equivalent": True,
        "final_dependency_sync_in_upgrade_environment": final_sync,
        "final_environment_equivalent": True,
        "final_lock_consumed_in_same_environment": True,
        "final_project": final_project,
        "final_wheel": final_wheel,
        "fresh_final_cli_smoke": fresh_cli,
        "fresh_final_dependency_check": fresh_check,
        "fresh_final_dependency_sync": fresh_sync,
        "fresh_final_environment_create": fresh_environment_create,
        "fresh_final_import": fresh_import,
        "fresh_final_import_command": fresh_import_command,
        "fresh_final_import_validation": fresh_validation,
        "fresh_final_inventory": fresh_inventory,
        "fresh_final_wheel_install": fresh_install,
        "fresh_final_control": True,
        "isolated_import": True,
        "network_denied": True,
        "noneditable": True,
        "offline": True,
        "process_isolation": isolation,
        "provider_or_trading_credentials_inherited": False,
        "published_baseline": authority.published_baseline,
        "repository_after": identity_after,
        "repository_before": identity_before,
        "repository_identity_stable": True,
        "safety": {
            "database_auto_migrate": False,
            "global_kill_switch": True,
            "live_trading_enabled": False,
            "provider_access": "disabled",
        },
        "schema_version": "hqa.agent-v0.2.2-noneditable-upgrade.v1",
        "status": "passed",
        "tools": {
            "python": {
                **python_version,
                "path": str(python),
                "sha256": _sha256(python.read_bytes()),
            },
            "uv": {
                **uv_version,
                "path": str(uv),
                "sha256": _sha256(uv.read_bytes()),
            },
        },
        "upgrade": upgrade,
        "upgrade_continuity_verified": True,
        "upgrade_environment_create": upgrade_environment_create,
        "upgraded_final_cli_smoke": upgraded_cli,
        "upgraded_final_dependency_check": upgraded_check,
        "upgraded_final_import": upgraded_import,
        "upgraded_final_import_command": upgraded_import_command,
        "upgraded_final_import_validation": upgraded_validation,
        "upgraded_final_inventory": upgraded_inventory,
    }
    _write_private(receipt_path, _canonical_json_bytes(receipt))
    return receipt
