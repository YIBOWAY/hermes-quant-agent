from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Optional

_CANDIDATE_RE = re.compile(r"candidate_id=(\S+)")
_CANDIDATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_CONFIRMATION_ID_RE = re.compile(r"^gate1-[0-9a-f]{32}$")
_TASK_REF_RE = re.compile(r"^task:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_METRIC_KEYS = ("sharpe", "total_return", "max_drawdown")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_PROMOTION_ID_RE = re.compile(
    r"^promo-[0-9a-f]{32}(?:-r(?:[2-9]|[1-9][0-9]+))?$"
)
_BACKTEST_RECEIPT_ID_RE = re.compile(r"^backtest-[0-9a-f]{32}$")
_MAX_GATE1_SOURCE_BYTES = 1_048_576
_MAX_GATE3_PATCH_BYTES = 8_388_608
_MAX_BACKTEST_ARTIFACT_BYTES = 8_388_608
_MAX_PROMOTION_SCAN_ENTRIES = 1_000


def _canonical_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _open_parent_directory(path: Path, *, create: bool) -> tuple[int, str]:
    absolute = Path(os.path.abspath(path))
    name = absolute.name
    if name in {"", ".", ".."} or "/" in name or "\\" in name:
        raise ValueError(f"unsafe audit path component: {name!r}")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    current_fd = os.open(absolute.anchor or os.sep, directory_flags)
    try:
        for component in absolute.parent.parts[1:]:
            if create:
                try:
                    os.mkdir(component, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
            next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd, name
    except Exception:
        os.close(current_fd)
        raise


def _read_regular_file_at(
    parent_fd: int,
    name: str,
    *,
    label: str,
    max_bytes: int,
) -> bytes:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{label} must be a regular non-symlink file")
    if before.st_size > max_bytes:
        raise ValueError(f"{label} exceeds the maximum size")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino, before.st_size)
            != (opened.st_dev, opened.st_ino, opened.st_size)
        ):
            raise ValueError(f"{label} changed before it was opened")
        if opened.st_size > max_bytes:
            raise ValueError(f"{label} exceeds the maximum size")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"{label} exceeds the maximum size")
            chunks.append(chunk)
    finally:
        os.close(fd)
    after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        (before.st_dev, before.st_ino, before.st_size)
        != (after.st_dev, after.st_ino, after.st_size)
        or (opened.st_dev, opened.st_ino, opened.st_size)
        != (after.st_dev, after.st_ino, after.st_size)
    ):
        raise ValueError(f"{label} changed during verification")
    return b"".join(chunks)


def _write_exclusive_or_verify(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    parent_fd, name = _open_parent_directory(path, create=True)
    try:
        try:
            fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
        except FileExistsError:
            try:
                existing = _read_regular_file_at(
                    parent_fd,
                    name,
                    label="existing audit record",
                    max_bytes=max(len(payload), 1),
                )
            except (OSError, ValueError) as exc:
                raise ValueError(f"Gate 1 audit collision at {path}") from exc
            if existing != payload:
                raise ValueError(f"Gate 1 audit collision at {path}")
            return
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short Gate 1 audit write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _read_regular_file(path: Path, *, label: str, max_bytes: int) -> bytes:
    parent_fd, name = _open_parent_directory(path, create=False)
    try:
        return _read_regular_file_at(
            parent_fd,
            name,
            label=label,
            max_bytes=max_bytes,
        )
    finally:
        os.close(parent_fd)


def _chmod_regular_file(path: Path, mode: int) -> None:
    parent_fd, name = _open_parent_directory(path, create=False)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("audit source must remain a regular file")
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _read_gate1_source(path: Path) -> bytes:
    return _read_regular_file(
        path,
        label="Gate 1 source",
        max_bytes=_MAX_GATE1_SOURCE_BYTES,
    )


def _read_external_gate1_source(path: Path) -> bytes:
    absolute = Path(os.path.abspath(path))
    canonical_parent = Path(os.path.realpath(absolute.parent))
    return _read_regular_file(
        canonical_parent / absolute.name,
        label="Gate 1 source",
        max_bytes=_MAX_GATE1_SOURCE_BYTES,
    )


def _canonical_authority_dir(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    # macOS exposes a small set of root-owned compatibility aliases (notably
    # /tmp -> /private/tmp and /var -> /private/var).  Normalize only those
    # fixed aliases.  Resolving the whole parent would follow user-controlled
    # ancestor symlinks and could redirect immutable audit writes outside the
    # configured authority tree.
    parts = absolute.parts
    if len(parts) >= 2:
        alias_targets = {
            "tmp": Path("/private/tmp"),
            "var": Path("/private/var"),
        }
        expected_target = alias_targets.get(parts[1])
        if expected_target is not None:
            alias = Path(os.sep) / parts[1]
            if Path(os.path.realpath(alias)) == expected_target:
                return expected_target.joinpath(*parts[2:])
    return absolute


def _read_canonical_json_record(path: Path, *, label: str) -> dict:
    try:
        raw = _read_gate1_source(path)
        payload = json.loads(raw.decode("utf-8"))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ValueError(f"invalid {label} record: {path}") from exc
    try:
        canonical = _canonical_bytes(payload) if isinstance(payload, dict) else None
    except (RecursionError, ValueError) as exc:
        raise ValueError(f"invalid {label} record: {path}") from exc
    if not isinstance(payload, dict) or raw != canonical:
        raise ValueError(f"non-canonical {label} record: {path}")
    return payload


def _verify_gate1_confirmation(*, gate_dir: Path, binding: dict) -> dict:
    confirmation_id = binding.get("confirmation_id")
    source_digest = binding.get("source_digest")
    if not isinstance(confirmation_id, str) or _CONFIRMATION_ID_RE.fullmatch(
        confirmation_id
    ) is None:
        raise ValueError("invalid Gate 1 confirmation ID")
    if not isinstance(source_digest, str) or _HEX64.fullmatch(source_digest) is None:
        raise ValueError("invalid Gate 1 source digest")

    confirmations_dir = gate_dir / "confirmations"
    sources_dir = gate_dir / "sources"
    if (
        not confirmations_dir.is_dir()
        or confirmations_dir.is_symlink()
        or not sources_dir.is_dir()
        or sources_dir.is_symlink()
    ):
        raise ValueError("Gate 1 confirmation authority missing")

    confirmation_path = confirmations_dir / f"{confirmation_id}.json"
    confirmation = _read_canonical_json_record(
        confirmation_path,
        label="Gate 1 confirmation",
    )
    confirmation_fields = {
        "schema_version",
        "gate",
        "goal",
        "universe",
        "source_digest",
        "confirmation_note",
        "staged_source",
        "confirmation_id",
        "confirmed_at",
    }
    if set(confirmation) != confirmation_fields:
        raise ValueError(f"invalid Gate 1 confirmation schema: {confirmation_path}")
    if (
        confirmation.get("schema_version") != "1.0"
        or confirmation.get("gate") != "formula_translation_confirmation"
        or confirmation.get("confirmation_id") != confirmation_id
        or confirmation.get("source_digest") != source_digest
        or not isinstance(confirmation.get("goal"), str)
        or not isinstance(confirmation.get("universe"), str)
        or not isinstance(confirmation.get("confirmation_note"), str)
        or not confirmation["confirmation_note"].strip()
        or not isinstance(confirmation.get("staged_source"), str)
        or not isinstance(confirmation.get("confirmed_at"), str)
    ):
        raise ValueError(f"invalid Gate 1 confirmation values: {confirmation_path}")

    confirmed = {
        key: confirmation[key]
        for key in (
            "schema_version",
            "gate",
            "goal",
            "universe",
            "source_digest",
            "confirmation_note",
            "staged_source",
        )
    }
    expected_confirmation_hash = hashlib.sha256(_canonical_bytes(confirmed)).hexdigest()
    if confirmation_id != f"gate1-{expected_confirmation_hash[:32]}":
        raise ValueError(f"Gate 1 confirmation content address mismatch: {confirmation_path}")

    expected_source = sources_dir / f"{source_digest}.py"
    recorded_source = Path(confirmation["staged_source"])
    if Path(os.path.abspath(recorded_source)) != Path(os.path.abspath(expected_source)):
        raise ValueError(f"Gate 1 staged source path mismatch: {confirmation_path}")
    observed_source_digest = hashlib.sha256(_read_gate1_source(expected_source)).hexdigest()
    if observed_source_digest != source_digest:
        raise ValueError(
            "Gate 1 staged source digest mismatch: "
            f"expected {source_digest}, got {observed_source_digest}"
        )
    return confirmation


def prepare_gate1_confirmation(
    *,
    goal: str,
    universe: str,
    source_file: str,
    expected_source_digest: str,
    confirmation_note: str,
    gate_dir: Path,
) -> tuple[str, str, str]:
    """Verify human-reviewed source bytes and persist Gate 1 before proposal."""
    gate_dir = _canonical_authority_dir(gate_dir)
    if _HEX64.fullmatch(expected_source_digest) is None:
        raise ValueError("expected-source-digest must be lowercase SHA-256")
    note = confirmation_note.strip()
    if not note:
        raise ValueError("confirmation-note must be non-empty")
    source = Path(source_file)
    payload = _read_external_gate1_source(source)
    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected_source_digest:
        raise ValueError(
            f"Gate 1 source digest mismatch: expected {expected_source_digest}, got {observed}"
        )

    stable_source = gate_dir / "sources" / f"{observed}.py"
    _write_exclusive_or_verify(stable_source, payload)
    _chmod_regular_file(stable_source, 0o400)

    confirmed = {
        "schema_version": "1.0",
        "gate": "formula_translation_confirmation",
        "goal": goal,
        "universe": universe,
        "source_digest": observed,
        "confirmation_note": note,
        "staged_source": str(stable_source),
    }
    confirmation_hash = hashlib.sha256(_canonical_bytes(confirmed)).hexdigest()
    confirmation_id = f"gate1-{confirmation_hash[:32]}"
    record = {
        **confirmed,
        "confirmation_id": confirmation_id,
        "confirmed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    record_path = gate_dir / "confirmations" / f"{confirmation_id}.json"
    if record_path.exists():
        _verify_gate1_confirmation(
            gate_dir=gate_dir,
            binding={
                "confirmation_id": confirmation_id,
                "source_digest": observed,
            },
        )
    else:
        _write_exclusive_or_verify(record_path, _canonical_bytes(record))
        _verify_gate1_confirmation(
            gate_dir=gate_dir,
            binding={
                "confirmation_id": confirmation_id,
                "source_digest": observed,
            },
        )
    return confirmation_id, observed, str(stable_source)


def reuse_gate1_confirmation(
    *,
    gate_dir: Path,
    confirmation_id: str,
    task_ref: str,
    source_file: str,
    expected_source_digest: str,
) -> tuple[str, str, str, str]:
    """Re-attest one Browser-created Gate 1 confirmation for proposal.

    The confirmation remains the sole authority for its original goal,
    universe, human note, and content-addressed staged source.  The caller must
    also supply the public Task reference from the same Gate receipt so a
    confirmation from another Task fails before any Platform proposal.
    """

    gate_dir = _canonical_authority_dir(gate_dir)
    if _CONFIRMATION_ID_RE.fullmatch(confirmation_id) is None:
        raise ValueError("invalid Gate 1 confirmation ID")
    if type(task_ref) is not str or _TASK_REF_RE.fullmatch(task_ref) is None:
        raise ValueError("invalid Gate 1 task reference")
    if _HEX64.fullmatch(expected_source_digest) is None:
        raise ValueError("expected-source-digest must be lowercase SHA-256")
    confirmation = _verify_gate1_confirmation(
        gate_dir=gate_dir,
        binding={
            "confirmation_id": confirmation_id,
            "source_digest": expected_source_digest,
        },
    )
    if confirmation.get("goal") != task_ref:
        raise ValueError("Gate 1 confirmation task binding mismatch")
    source = _read_external_gate1_source(Path(source_file))
    observed = hashlib.sha256(source).hexdigest()
    if observed != expected_source_digest:
        raise ValueError(
            "Gate 1 source digest mismatch: "
            f"expected {expected_source_digest}, got {observed}"
        )
    goal = confirmation.get("goal")
    universe = confirmation.get("universe")
    staged_source = confirmation.get("staged_source")
    if (
        type(goal) is not str
        or not goal.strip()
        or type(universe) is not str
        or not universe.strip()
        or type(staged_source) is not str
        or not staged_source
    ):
        raise ValueError("Gate 1 confirmation cannot authorize a proposal")
    return goal, universe, expected_source_digest, staged_source


def record_gate1_candidate_binding(
    *,
    gate_dir: Path,
    confirmation_id: str,
    source_digest: str,
    candidate_id: str,
    manifest_digest: str,
) -> Path:
    gate_dir = _canonical_authority_dir(gate_dir)
    if (
        _CONFIRMATION_ID_RE.fullmatch(confirmation_id) is None
        or _CANDIDATE_ID_RE.fullmatch(candidate_id) is None
        or _HEX64.fullmatch(source_digest) is None
        or _HEX64.fullmatch(manifest_digest) is None
    ):
        raise ValueError("Gate 1 binding digests must be lowercase SHA-256")
    payload = {
        "schema_version": "1.0",
        "confirmation_id": confirmation_id,
        "source_digest": source_digest,
        "candidate_id": candidate_id,
        "manifest_digest": manifest_digest,
    }
    _verify_gate1_confirmation(gate_dir=gate_dir, binding=payload)
    binding_hash = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    path = gate_dir / "bindings" / f"binding-{binding_hash[:32]}.json"
    _write_exclusive_or_verify(path, _canonical_bytes(payload))
    require_gate1_candidate_binding(
        gate_dir=gate_dir,
        candidate_id=candidate_id,
        manifest_digest=manifest_digest,
    )
    return path


def require_gate1_candidate_binding(
    *,
    gate_dir: Path,
    candidate_id: str,
    manifest_digest: str,
    confirmation_id: str | None = None,
    source_digest: str | None = None,
) -> None:
    """Fail closed unless Gate 2 inputs match one durable Gate 1 binding."""
    gate_dir = _canonical_authority_dir(gate_dir)
    if _HEX64.fullmatch(manifest_digest) is None:
        raise ValueError("Gate 1 binding lookup requires a lowercase SHA-256")
    if _CANDIDATE_ID_RE.fullmatch(candidate_id) is None:
        raise ValueError("Gate 1 binding lookup requires a valid candidate ID")
    if (confirmation_id is None) != (source_digest is None):
        raise ValueError(
            "exact Gate 1 binding requires confirmation and source together"
        )
    if confirmation_id is not None and (
        _CONFIRMATION_ID_RE.fullmatch(confirmation_id) is None
        or source_digest is None
        or _HEX64.fullmatch(source_digest) is None
    ):
        raise ValueError("exact Gate 1 binding identity is invalid")
    if gate_dir.is_symlink() or not gate_dir.is_dir():
        raise ValueError("Gate 1 authority directory missing")
    bindings_dir = gate_dir / "bindings"
    if not bindings_dir.is_dir() or bindings_dir.is_symlink():
        raise ValueError("Gate 1 binding missing")
    found = False
    for path in sorted(bindings_dir.glob("binding-*.json")):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"unsafe Gate 1 binding record: {path}")
        payload = _read_canonical_json_record(path, label="Gate 1 binding")
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "confirmation_id",
            "source_digest",
            "candidate_id",
            "manifest_digest",
        }:
            raise ValueError(f"invalid Gate 1 binding schema: {path}")
        if payload.get("schema_version") != "1.0":
            raise ValueError(f"unsupported Gate 1 binding schema: {path}")
        if (
            not isinstance(payload.get("confirmation_id"), str)
            or _CONFIRMATION_ID_RE.fullmatch(payload["confirmation_id"]) is None
            or not isinstance(payload.get("source_digest"), str)
            or _HEX64.fullmatch(payload["source_digest"]) is None
            or not isinstance(payload.get("candidate_id"), str)
            or _CANDIDATE_ID_RE.fullmatch(payload["candidate_id"]) is None
            or not isinstance(payload.get("manifest_digest"), str)
            or _HEX64.fullmatch(payload["manifest_digest"]) is None
        ):
            raise ValueError(f"invalid Gate 1 binding values: {path}")
        binding_hash = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
        if path.name != f"binding-{binding_hash[:32]}.json":
            raise ValueError(f"Gate 1 binding content address mismatch: {path}")
        _verify_gate1_confirmation(gate_dir=gate_dir, binding=payload)
        if (
            payload.get("candidate_id") == candidate_id
            and payload.get("manifest_digest") == manifest_digest
            and (
                confirmation_id is None
                or (
                    payload.get("confirmation_id") == confirmation_id
                    and payload.get("source_digest") == source_digest
                )
            )
        ):
            found = True
    if not found:
        raise ValueError("Gate 1 binding missing for exact candidate and manifest digest")


def require_exact_candidate_approval_lock(
    *,
    candidates_root: Path,
    source_path: str,
    candidate_id: str,
    manifest_digest: str,
    note: str,
) -> str:
    """Verify the immutable Platform approval lock for receipt-loss recovery."""
    if (
        _CANDIDATE_ID_RE.fullmatch(candidate_id) is None
        or _HEX64.fullmatch(manifest_digest) is None
        or not isinstance(note, str)
        or not note.strip()
    ):
        raise ValueError("invalid candidate approval recovery binding")
    root = Path(os.path.abspath(candidates_root))
    expected_candidate = root / candidate_id
    source = Path(os.path.abspath(source_path))
    if (
        source.name != "factor.py.candidate"
        or source.parent != expected_candidate
        or Path(os.path.realpath(source.parent))
        != Path(os.path.realpath(expected_candidate))
    ):
        raise ValueError("candidate approval recovery escaped canonical root")
    lock = _read_canonical_json_record(
        expected_candidate / "approved.lock",
        label="candidate approval",
    )
    if (
        set(lock)
        != {
            "schema_version",
            "candidate_id",
            "decision",
            "manifest_digest",
            "note",
            "reviewer",
            "created_at",
        }
        or lock.get("schema_version") != "1.0"
        or lock.get("candidate_id") != candidate_id
        or lock.get("decision") != "approve"
        or lock.get("manifest_digest") != manifest_digest
        or lock.get("note") != note
        or lock.get("reviewer") != "manual"
        or not isinstance(lock.get("created_at"), str)
        or not lock["created_at"]
    ):
        raise ValueError("candidate approval recovery binding mismatch")
    return hashlib.sha256(note.encode("utf-8")).hexdigest()


def verify_experiment_receipt(
    receipt: dict,
    *,
    platform_dir: Path,
    experiment_output_dir: Path,
    candidate_id: str,
    manifest_digest: str,
    factor_id: str,
    provider: str,
    symbols: list[str],
    start: str,
    end: str,
) -> dict:
    """Verify the platform's persisted config, summary, and report evidence."""
    expected_fields = {
        "experiment_id",
        "run_count",
        "best_run_id",
        "data_source",
        "config",
        "config_sha256",
        "agent_summary",
        "agent_summary_sha256",
        "report",
        "report_sha256",
        "approved_candidates_loaded",
        "candidate_binding",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_fields:
        raise ValueError("invalid experiment receipt schema")
    binding = {
        "candidate_id": candidate_id,
        "manifest_digest": manifest_digest,
        "factor_id": factor_id,
    }
    if (
        not isinstance(receipt.get("experiment_id"), str)
        or not receipt["experiment_id"].strip()
        or not isinstance(receipt.get("best_run_id"), str)
        or not receipt["best_run_id"].strip()
        or not isinstance(receipt.get("run_count"), int)
        or isinstance(receipt["run_count"], bool)
        or receipt["run_count"] != 1
        or receipt.get("data_source") != provider
        or receipt.get("approved_candidates_loaded") != [factor_id]
        or receipt.get("candidate_binding") != binding
        or provider not in {"futu", "tiingo"}
    ):
        raise ValueError("experiment receipt binding mismatch")

    artifact_bytes: dict[str, bytes] = {}
    artifact_paths: dict[str, Path] = {}
    for field, digest_field in (
        ("config", "config_sha256"),
        ("agent_summary", "agent_summary_sha256"),
        ("report", "report_sha256"),
    ):
        value = receipt.get(field)
        digest = receipt.get(digest_field)
        if (
            not isinstance(value, str)
            or not value
            or not isinstance(digest, str)
            or _HEX64.fullmatch(digest) is None
        ):
            raise ValueError(f"invalid experiment {field} evidence")
        path = Path(value)
        if not path.is_absolute():
            path = platform_dir / path
        path = Path(os.path.abspath(path))
        payload = _read_regular_file(
            path,
            label=f"experiment {field}",
            max_bytes=_MAX_BACKTEST_ARTIFACT_BYTES,
        )
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError(f"experiment {field} digest mismatch")
        artifact_paths[field] = path
        artifact_bytes[field] = payload
    if not artifact_bytes["report"].strip():
        raise ValueError("experiment report is empty")

    try:
        persisted_config = json.loads(artifact_bytes["config"].decode("utf-8"))
        agent_summary = json.loads(artifact_bytes["agent_summary"].decode("utf-8"))
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ValueError("experiment JSON evidence is invalid") from exc
    if not isinstance(persisted_config, dict) or not isinstance(agent_summary, dict):
        raise ValueError("experiment JSON evidence must be objects")

    experiment_name = f"factor-repro-{candidate_id}"
    experiment_id_pattern = re.compile(
        rf"^{re.escape(experiment_name)}-([0-9]{{8}}T[0-9]{{12}}Z)-[0-9a-f]{{12}}$"
    )
    experiment_id_match = experiment_id_pattern.fullmatch(receipt["experiment_id"])
    if experiment_id_match is None:
        raise ValueError("experiment receipt has an invalid unique experiment ID")
    try:
        datetime.datetime.strptime(
            experiment_id_match.group(1), "%Y%m%dT%H%M%S%fZ"
        )
    except ValueError as exc:
        raise ValueError(
            "experiment receipt has an invalid unique experiment ID"
        ) from exc
    sanitized_experiment_id = re.sub(
        r"[^A-Za-z0-9_]+", "_", receipt["experiment_id"]
    ).strip("_") or "experiment"
    output_root = Path(os.path.abspath(experiment_output_dir))
    expected_experiment_dir = output_root / "experiments" / sanitized_experiment_id
    expected_report_dir = output_root / "reports" / sanitized_experiment_id
    expected_artifact_paths = {
        "config": expected_experiment_dir / "experiment_config.json",
        "agent_summary": expected_experiment_dir / "agent_summary.json",
        "report": expected_report_dir / "experiment_comparison_report.md",
    }
    if artifact_paths != expected_artifact_paths:
        raise ValueError("experiment artifacts escaped the unique experiment namespace")
    commission_bps = persisted_config.get("commission_bps")
    slippage_bps = persisted_config.get("slippage_bps")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
        or float(value) > 10_000.0
        for value in (commission_bps, slippage_bps)
    ):
        raise ValueError("persisted experiment cost assumption is invalid")
    expected_config = {
        "candidate_binding": binding,
        "commission_bps": float(commission_bps),
        "end": end,
        "experiment_name": experiment_name,
        "factor_blend": {
            "factors": [
                {
                    "direction": "higher_is_better",
                    "factor_id": factor_id,
                    "weight": 1.0,
                }
            ],
            "rebalance_every_n_bars": 1,
        },
        "initial_cash": 100_000.0,
        "slippage_bps": float(slippage_bps),
        "start": start,
        "sweep": {},
        "symbols": symbols,
        "target_gross_exposure": 1.0,
        "walk_forward": {
            "enabled": False,
            "step_bars": 20,
            "train_bars": 60,
            "validation_bars": 20,
        },
    }
    automation_config = persisted_config.get("automation_evidence")
    if automation_config is not None:
        if (
            not isinstance(automation_config, dict)
            or set(automation_config) != {"holdout_days"}
            or isinstance(automation_config.get("holdout_days"), bool)
            or not isinstance(automation_config.get("holdout_days"), int)
            or not 1 <= automation_config["holdout_days"] <= 3_650
        ):
            raise ValueError("persisted automation evidence config is invalid")
        expected_config["automation_evidence"] = automation_config
    if persisted_config != expected_config:
        raise ValueError("persisted experiment config binding mismatch")

    summary_fields = {
        "experiment_id",
        "experiment_name",
        "created_at",
        "purpose",
        "safety",
        "data",
        "walk_forward",
        "candidate_binding",
        "best_run_id",
        "runs",
        "notes",
    }
    expected_safety = {
        "live_trading": False,
        "paper_trading": False,
        "auto_promotion": False,
    }
    expected_data = {
        "source": provider,
        "symbols": symbols,
        "start": start,
        "end": end,
    }
    verified_automation_evidence: dict[str, float | int] | None = None
    if automation_config is not None:
        summary_data = agent_summary.get("data")
        observed = (
            summary_data.get("automation_evidence")
            if isinstance(summary_data, dict)
            else None
        )
        if (
            not isinstance(observed, dict)
            or set(observed)
            != {
                "holdout_days",
                "sample_rows",
                "out_of_sample_rows",
                "data_coverage_ratio",
            }
            or observed.get("holdout_days") != automation_config["holdout_days"]
            or isinstance(observed.get("sample_rows"), bool)
            or not isinstance(observed.get("sample_rows"), int)
            or observed["sample_rows"] <= 0
            or isinstance(observed.get("out_of_sample_rows"), bool)
            or not isinstance(observed.get("out_of_sample_rows"), int)
            or not 0 < observed["out_of_sample_rows"] <= observed["sample_rows"]
            or isinstance(observed.get("data_coverage_ratio"), bool)
            or not isinstance(observed.get("data_coverage_ratio"), (int, float))
            or not math.isfinite(float(observed["data_coverage_ratio"]))
            or not 0.0 <= float(observed["data_coverage_ratio"]) <= 1.0
        ):
            raise ValueError("agent summary automation evidence is invalid")
        verified_automation_evidence = {
            "sample_rows": observed["sample_rows"],
            "out_of_sample_rows": observed["out_of_sample_rows"],
            "data_coverage_ratio": float(observed["data_coverage_ratio"]),
        }
        expected_data["automation_evidence"] = observed
    expected_notes = [
        "Scores are standardized cross-sectionally at each signal timestamp.",
        "Backtests execute on tradeable timestamps only.",
        "This summary is for AI-assisted review, not automatic deployment.",
    ]
    data = agent_summary.get("data")
    runs = agent_summary.get("runs")
    safety = agent_summary.get("safety")
    created_at = agent_summary.get("created_at")
    try:
        parsed_created_at = (
            datetime.datetime.fromisoformat(created_at)
            if isinstance(created_at, str)
            else None
        )
    except ValueError:
        parsed_created_at = None
    if (
        set(agent_summary) != summary_fields
        or agent_summary.get("experiment_id") != receipt["experiment_id"]
        or agent_summary.get("experiment_name") != experiment_name
        or parsed_created_at is None
        or parsed_created_at.tzinfo is None
        or parsed_created_at.utcoffset() != datetime.timedelta(0)
        or agent_summary.get("purpose")
        != "Research experiment comparison for human review."
        or agent_summary.get("best_run_id") != receipt["best_run_id"]
        or agent_summary.get("candidate_binding") != binding
        or agent_summary.get("walk_forward") != expected_config["walk_forward"]
        or data != expected_data
        or safety != expected_safety
        or agent_summary.get("notes") != expected_notes
        or not isinstance(runs, list)
        or len(runs) != receipt["run_count"]
        or receipt["best_run_id"] != "run-001"
    ):
        raise ValueError("agent summary binding mismatch")
    best_run = next(
        (
            run
            for run in runs
            if isinstance(run, dict) and run.get("run_id") == receipt["best_run_id"]
        ),
        None,
    )
    if best_run is None:
        raise ValueError("agent summary best run is missing")
    run_ids: list[str] = []
    for run in runs:
        if (
            not isinstance(run, dict)
            or set(run)
            != {
                "run_id",
                "created_at",
                "parameters",
                "total_return",
                "annualized_return",
                "volatility",
                "sharpe",
                "max_drawdown",
                "turnover",
                "fold_count",
            }
            or not isinstance(run.get("run_id"), str)
            or run["run_id"] != "run-001"
            or not isinstance(run.get("created_at"), str)
            or not run["created_at"]
            or run["created_at"] != created_at
            or run.get("parameters") != {}
            or not isinstance(run.get("fold_count"), int)
            or isinstance(run.get("fold_count"), bool)
            or run["fold_count"] != 0
        ):
            raise ValueError("agent summary run identity is invalid")
        run_ids.append(run["run_id"])
        for key in (
            "total_return",
            "annualized_return",
            "volatility",
            "sharpe",
            "max_drawdown",
            "turnover",
        ):
            value = run.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError("agent summary best run metrics are incomplete")
            try:
                finite = math.isfinite(float(value))
            except (OverflowError, TypeError, ValueError) as exc:
                raise ValueError(
                    "agent summary best run metrics are incomplete"
                ) from exc
            if not finite:
                raise ValueError("agent summary best run metrics are incomplete")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("agent summary run identities are duplicated")
    if best_run["sharpe"] != max(run["sharpe"] for run in runs):
        raise ValueError("agent summary best run does not have the maximum sharpe")
    metrics = {key: best_run[key] for key in _METRIC_KEYS}

    try:
        report_text = artifact_bytes["report"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("experiment report is not UTF-8") from exc
    expected_report_lines = [
        "# Phase 4 Experiment Comparison Report",
        "",
        "## Scope",
        "",
        (
            "This report compares research experiments only. It does not select a "
            "live strategy and does not place orders."
        ),
        "",
        "## Experiment",
        "",
        f"- Experiment id: {receipt['experiment_id']}",
        f"- Name: {experiment_name}",
        f"- Symbols: {', '.join(symbols)}",
        f"- Date range: {start} to {end}",
        "- Walk-forward enabled: False",
        "",
        "## Results",
        "",
        "| run_id | total_return | sharpe | max_drawdown | turnover | fold_count | params |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for run in sorted(runs, key=lambda item: item["sharpe"], reverse=True):
        expected_report_lines.append(
            f"| {run['run_id']} | {float(run['total_return']):.6f} | "
            f"{float(run['sharpe']):.6f} | {float(run['max_drawdown']):.6f} | "
            f"{float(run['turnover']):.6f} | {run['fold_count']} | {{}} |"
        )
    expected_report_lines.extend(
        [
            "",
            "## Leakage Controls",
            "",
            "- Factor standardization is cross-sectional at each `signal_ts`.",
            "- Composite scores use only factor values already stamped by Phase 2.",
            "- Backtests execute only at `tradeable_ts`.",
            (
                "- Walk-forward validation computes factors with train+validation "
                "history but only evaluates validation dates."
            ),
            "- No run is promoted to live automatically.",
            "",
        ]
    )
    if report_text != "\n".join(expected_report_lines):
        raise ValueError("experiment report provenance mismatch")
    return {
        "experiment_id": receipt["experiment_id"],
        "run_count": receipt["run_count"],
        "best_run_id": receipt["best_run_id"],
        "config_path": str(artifact_paths["config"]),
        "config_sha256": receipt["config_sha256"],
        "agent_summary_path": str(artifact_paths["agent_summary"]),
        "agent_summary_sha256": receipt["agent_summary_sha256"],
        "report": str(artifact_paths["report"]),
        "report_sha256": receipt["report_sha256"],
        "metrics": metrics,
        "verified_policy_evidence": {
            **(verified_automation_evidence or {}),
            "transaction_cost_bps": float(commission_bps) + float(slippage_bps),
            "max_drawdown": float(best_run["max_drawdown"]),
            "turnover": float(best_run["turnover"]),
        },
    }


def record_final_backtest_receipt(
    *,
    gate_dir: Path,
    experiment_output_dir: Path,
    candidate_id: str,
    manifest_digest: str,
    factor_id: str,
    experiment_id: str,
    run_count: int,
    best_run_id: str,
    provider: str,
    symbols: list[str],
    start: str,
    end: str,
    config_path: str,
    config_sha256: str,
    agent_summary_path: str,
    agent_summary_sha256: str,
    report: str,
    report_sha256: str,
) -> str:
    """Persist an immutable successful full-window receipt for Gate 3."""
    gate_dir = _canonical_authority_dir(gate_dir)
    require_gate1_candidate_binding(
        gate_dir=gate_dir,
        candidate_id=candidate_id,
        manifest_digest=manifest_digest,
    )
    if _CANDIDATE_ID_RE.fullmatch(candidate_id) is None:
        raise ValueError("final backtest receipt requires a valid candidate ID")
    if _HEX64.fullmatch(manifest_digest) is None:
        raise ValueError("final backtest receipt requires a lowercase SHA-256")
    string_fields = {
        "factor_id": factor_id,
        "experiment_id": experiment_id,
        "best_run_id": best_run_id,
        "provider": provider,
        "start": start,
        "end": end,
        "config_path": config_path,
        "config_sha256": config_sha256,
        "agent_summary_path": agent_summary_path,
        "agent_summary_sha256": agent_summary_sha256,
        "report": report,
        "report_sha256": report_sha256,
    }
    if any(
        not isinstance(value, str) or not value.strip()
        for value in string_fields.values()
    ):
        raise ValueError("final backtest receipt requires complete experiment evidence")
    if provider not in {"futu", "tiingo"}:
        raise ValueError("final backtest receipt requires a real configured provider")
    if not symbols or any(
        not isinstance(symbol, str) or not symbol.strip() for symbol in symbols
    ):
        raise ValueError("final backtest receipt requires non-empty symbols")
    verify_experiment_receipt(
        {
            "experiment_id": experiment_id,
            "run_count": run_count,
            "best_run_id": best_run_id,
            "data_source": provider,
            "config": config_path,
            "config_sha256": config_sha256,
            "agent_summary": agent_summary_path,
            "agent_summary_sha256": agent_summary_sha256,
            "report": report,
            "report_sha256": report_sha256,
            "approved_candidates_loaded": [factor_id],
            "candidate_binding": {
                "candidate_id": candidate_id,
                "manifest_digest": manifest_digest,
                "factor_id": factor_id,
            },
        },
        platform_dir=Path.cwd(),
        experiment_output_dir=experiment_output_dir,
        candidate_id=candidate_id,
        manifest_digest=manifest_digest,
        factor_id=factor_id,
        provider=provider,
        symbols=symbols,
        start=start,
        end=end,
    )

    evidence = {
        "schema_version": "1.0",
        "gate": "final_one_shot_backtest",
        "status": "succeeded",
        "final": True,
        "candidate_id": candidate_id,
        "manifest_digest": manifest_digest,
        "factor_id": factor_id,
        "experiment_id": experiment_id,
        "run_count": run_count,
        "best_run_id": best_run_id,
        "provider": provider,
        "symbols": list(symbols),
        "start": start,
        "end": end,
        "config_path": config_path,
        "config_sha256": config_sha256,
        "agent_summary_path": agent_summary_path,
        "agent_summary_sha256": agent_summary_sha256,
        "report": report,
        "report_sha256": report_sha256,
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    receipt_hash = hashlib.sha256(_canonical_bytes(evidence)).hexdigest()
    receipt_id = f"backtest-{receipt_hash[:32]}"
    record = {**evidence, "receipt_id": receipt_id}
    path = gate_dir / "backtests" / f"{receipt_id}.json"
    _write_exclusive_or_verify(path, _canonical_bytes(record))
    require_final_backtest_receipt(
        gate_dir=gate_dir,
        experiment_output_dir=experiment_output_dir,
        receipt_id=receipt_id,
        candidate_id=candidate_id,
        manifest_digest=manifest_digest,
    )
    return receipt_id


def require_final_backtest_receipt(
    *,
    gate_dir: Path,
    experiment_output_dir: Path,
    receipt_id: str,
    candidate_id: str,
    manifest_digest: str,
) -> dict:
    """Fail closed unless Gate 3 consumes one exact successful --final run."""
    gate_dir = _canonical_authority_dir(gate_dir)
    if _BACKTEST_RECEIPT_ID_RE.fullmatch(receipt_id) is None:
        raise ValueError("invalid final backtest receipt ID")
    if _CANDIDATE_ID_RE.fullmatch(candidate_id) is None:
        raise ValueError("final backtest receipt requires a valid candidate ID")
    if _HEX64.fullmatch(manifest_digest) is None:
        raise ValueError("final backtest receipt requires a lowercase SHA-256")
    if gate_dir.is_symlink() or not gate_dir.is_dir():
        raise ValueError("final backtest authority directory missing")
    receipts_dir = gate_dir / "backtests"
    if receipts_dir.is_symlink() or not receipts_dir.is_dir():
        raise ValueError("final backtest receipt missing")
    path = receipts_dir / f"{receipt_id}.json"
    record = _read_canonical_json_record(path, label="final backtest receipt")
    expected_fields = {
        "schema_version",
        "gate",
        "status",
        "final",
        "candidate_id",
        "manifest_digest",
        "factor_id",
        "experiment_id",
        "run_count",
        "best_run_id",
        "provider",
        "symbols",
        "start",
        "end",
        "config_path",
        "config_sha256",
        "agent_summary_path",
        "agent_summary_sha256",
        "report",
        "report_sha256",
        "completed_at",
        "receipt_id",
    }
    if set(record) != expected_fields:
        raise ValueError(f"invalid final backtest receipt schema: {path}")
    if (
        record.get("schema_version") != "1.0"
        or record.get("gate") != "final_one_shot_backtest"
        or record.get("status") != "succeeded"
        or record.get("final") is not True
        or record.get("receipt_id") != receipt_id
        or record.get("candidate_id") != candidate_id
        or record.get("manifest_digest") != manifest_digest
        or record.get("provider") not in {"futu", "tiingo"}
        or record.get("run_count") != 1
        or any(
            not isinstance(record.get(field), str) or not record[field].strip()
            for field in (
                "factor_id",
                "experiment_id",
                "best_run_id",
                "provider",
                "start",
                "end",
                "config_path",
                "config_sha256",
                "agent_summary_path",
                "agent_summary_sha256",
                "report",
                "report_sha256",
                "completed_at",
            )
        )
        or not isinstance(record.get("symbols"), list)
        or not record["symbols"]
        or any(
            not isinstance(symbol, str) or not symbol.strip()
            for symbol in record["symbols"]
        )
    ):
        raise ValueError(f"invalid final backtest receipt values: {path}")
    evidence = {key: value for key, value in record.items() if key != "receipt_id"}
    expected_id = (
        f"backtest-{hashlib.sha256(_canonical_bytes(evidence)).hexdigest()[:32]}"
    )
    if receipt_id != expected_id:
        raise ValueError(f"final backtest receipt content address mismatch: {path}")
    for path_field, digest_field in (
        ("config_path", "config_sha256"),
        ("agent_summary_path", "agent_summary_sha256"),
        ("report", "report_sha256"),
    ):
        digest = record[digest_field]
        if _HEX64.fullmatch(digest) is None:
            raise ValueError(f"invalid final backtest artifact digest: {path}")
        artifact = _read_regular_file(
            Path(record[path_field]),
            label=f"final backtest {path_field}",
            max_bytes=_MAX_BACKTEST_ARTIFACT_BYTES,
        )
        if hashlib.sha256(artifact).hexdigest() != digest:
            raise ValueError(f"final backtest artifact digest mismatch: {path}")
    verified_experiment = verify_experiment_receipt(
        {
            "experiment_id": record["experiment_id"],
            "run_count": record["run_count"],
            "best_run_id": record["best_run_id"],
            "data_source": record["provider"],
            "config": record["config_path"],
            "config_sha256": record["config_sha256"],
            "agent_summary": record["agent_summary_path"],
            "agent_summary_sha256": record["agent_summary_sha256"],
            "report": record["report"],
            "report_sha256": record["report_sha256"],
            "approved_candidates_loaded": [record["factor_id"]],
            "candidate_binding": {
                "candidate_id": record["candidate_id"],
                "manifest_digest": record["manifest_digest"],
                "factor_id": record["factor_id"],
            },
        },
        platform_dir=Path.cwd(),
        experiment_output_dir=experiment_output_dir,
        candidate_id=record["candidate_id"],
        manifest_digest=record["manifest_digest"],
        factor_id=record["factor_id"],
        provider=record["provider"],
        symbols=record["symbols"],
        start=record["start"],
        end=record["end"],
    )
    return {
        **record,
        "verified_policy_evidence": verified_experiment[
            "verified_policy_evidence"
        ],
    }


def verify_gate3_receipt(
    receipt: dict,
    *,
    candidate_id: str,
    manifest_digest: str,
    final_backtest_receipt_id: str,
    factor_id: str,
    base_commit: str,
    promotion_root: Path,
    worktree_root: Path,
) -> dict:
    """Bind the four-field platform receipt back to its immutable Gate 3 manifest."""
    fields = {"promotion_id", "worktree", "patch", "manifest"}
    if not isinstance(receipt, dict) or set(receipt) != fields:
        raise ValueError("invalid Gate 3 receipt schema")
    if (
        _CANDIDATE_ID_RE.fullmatch(candidate_id) is None
        or _CANDIDATE_ID_RE.fullmatch(factor_id) is None
        or _HEX64.fullmatch(manifest_digest) is None
        or _BACKTEST_RECEIPT_ID_RE.fullmatch(final_backtest_receipt_id) is None
        or _GIT_COMMIT_RE.fullmatch(base_commit) is None
    ):
        raise ValueError("invalid Gate 3 expected binding")
    if any(not isinstance(receipt[field], str) or not receipt[field] for field in fields):
        raise ValueError("invalid Gate 3 receipt values")

    promotion_id = receipt["promotion_id"]
    if _PROMOTION_ID_RE.fullmatch(promotion_id) is None:
        raise ValueError("invalid Gate 3 promotion ID")
    worktree = Path(receipt["worktree"])
    patch_path = Path(receipt["patch"])
    manifest_path = Path(receipt["manifest"])
    expected_worktree_root = Path(os.path.abspath(worktree_root))
    expected_promotion_root = Path(os.path.abspath(promotion_root))
    canonical_worktree_root = Path(os.path.realpath(expected_worktree_root))
    canonical_promotion_root = Path(os.path.realpath(expected_promotion_root))
    expected_promotion_dir = expected_promotion_root / promotion_id
    receipt_worktree_parent = Path(os.path.abspath(worktree.parent))
    if (
        (
            receipt_worktree_parent != expected_worktree_root
            and Path(os.path.realpath(receipt_worktree_parent))
            != canonical_worktree_root
        )
        or Path(os.path.abspath(manifest_path.parent.parent))
        != expected_promotion_root
        or Path(os.path.abspath(patch_path))
        != expected_promotion_dir / "scoped.patch"
        or Path(os.path.abspath(manifest_path))
        != expected_promotion_dir / "manifest.v1.json"
    ):
        raise ValueError("Gate 3 receipt escaped the managed roots")
    canonical_worktree = canonical_worktree_root / promotion_id
    canonical_promotion_dir = canonical_promotion_root / promotion_id
    if (
        Path(os.path.realpath(worktree)) != canonical_worktree
        or Path(os.path.realpath(manifest_path.parent)) != canonical_promotion_dir
    ):
        raise ValueError("Gate 3 receipt canonical root mismatch")
    worktree = canonical_worktree
    patch_path = canonical_promotion_dir / "scoped.patch"
    manifest_path = canonical_promotion_dir / "manifest.v1.json"
    try:
        worktree_stat = worktree.lstat()
    except OSError as exc:
        raise ValueError("Gate 3 worktree is unavailable") from exc
    if (
        stat.S_ISLNK(worktree_stat.st_mode)
        or not stat.S_ISDIR(worktree_stat.st_mode)
        or worktree.name != promotion_id
    ):
        raise ValueError("invalid Gate 3 worktree")
    if (
        patch_path.name != "scoped.patch"
        or manifest_path.name != "manifest.v1.json"
        or patch_path.parent != manifest_path.parent
        or manifest_path.parent.name != promotion_id
    ):
        raise ValueError("invalid Gate 3 receipt paths")

    try:
        raw_manifest = _read_regular_file(
            manifest_path,
            label="Gate 3 manifest",
            max_bytes=_MAX_GATE1_SOURCE_BYTES,
        )
        manifest = json.loads(raw_manifest.decode("utf-8"))
        patch = _read_regular_file(
            patch_path,
            label="Gate 3 patch",
            max_bytes=_MAX_GATE3_PATCH_BYTES,
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ValueError("invalid Gate 3 manifest or patch") from exc

    manifest_fields = {
        "schema_version",
        "promotion_id",
        "base_commit",
        "candidate_id",
        "candidate_digest",
        "final_backtest_receipt_id",
        "scoped_paths",
        "files",
        "patch_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != manifest_fields:
        raise ValueError("invalid Gate 3 manifest schema")
    if (
        manifest.get("schema_version") != "1.1"
        or manifest.get("promotion_id") != promotion_id
        or manifest.get("base_commit") != base_commit
        or manifest.get("candidate_id") != candidate_id
        or manifest.get("candidate_digest") != manifest_digest
        or manifest.get("final_backtest_receipt_id")
        != final_backtest_receipt_id
        or not isinstance(manifest.get("scoped_paths"), list)
        or not manifest["scoped_paths"]
        or not all(isinstance(path, str) and path for path in manifest["scoped_paths"])
        or not isinstance(manifest.get("files"), list)
        or not manifest["files"]
        or not isinstance(manifest.get("patch_sha256"), str)
        or _HEX64.fullmatch(manifest["patch_sha256"]) is None
    ):
        raise ValueError("Gate 3 manifest binding mismatch")
    if hashlib.sha256(patch).hexdigest() != manifest["patch_sha256"]:
        raise ValueError("Gate 3 patch digest mismatch")
    promoted_root = PurePosixPath("src/quant_system/factors/library/promoted")
    tests_root = PurePosixPath("tests/factors")
    promoted_prefix = str(promoted_root) + "/"
    promoted_targets = [
        path
        for path in manifest["scoped_paths"]
        if path.startswith(promoted_prefix) and path != promoted_prefix + "__init__.py"
    ]
    test_targets = [
        path
        for path in manifest["scoped_paths"]
        if path.startswith("tests/factors/test_") and path.endswith(".py")
    ]
    if (
        len(manifest["scoped_paths"]) != 3
        or promoted_prefix + "__init__.py" not in manifest["scoped_paths"]
        or len(promoted_targets) != 1
        or len(test_targets) != 1
        or not promoted_targets[0].endswith(".py")
    ):
        raise ValueError("Gate 3 scoped paths escaped the promotion allowlist")
    promoted_factor = Path(promoted_targets[0]).stem
    test_factor = Path(test_targets[0]).stem.removeprefix("test_")
    if (
        not promoted_factor
        or promoted_factor == "__init__"
        or promoted_factor != test_factor
        or promoted_factor != factor_id
        or PurePosixPath(promoted_targets[0]).parent != promoted_root
        or PurePosixPath(test_targets[0]).parent != tests_root
        or promoted_targets[0] != str(promoted_root / f"{factor_id}.py")
        or test_targets[0] != str(tests_root / f"test_{factor_id}.py")
    ):
        raise ValueError("Gate 3 scoped factor paths do not match")
    entry_paths: list[str] = []
    for entry in manifest["files"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "mode", "sha256"}
            or not isinstance(entry.get("path"), str)
            or not entry["path"]
            or entry.get("mode") != "100644"
            or not isinstance(entry.get("sha256"), str)
            or _HEX64.fullmatch(entry["sha256"]) is None
        ):
            raise ValueError("invalid Gate 3 file manifest entry")
        pure_path = PurePosixPath(entry["path"])
        if (
            pure_path.is_absolute()
            or ".." in pure_path.parts
            or "." in pure_path.parts
            or "\\" in entry["path"]
            or str(pure_path) != entry["path"]
        ):
            raise ValueError("invalid Gate 3 worktree file path")
        current = worktree
        for component in pure_path.parts[:-1]:
            current = current / component
            current_stat = current.lstat()
            if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(
                current_stat.st_mode
            ):
                raise ValueError("unsafe Gate 3 worktree parent")
        file_path = worktree.joinpath(*pure_path.parts)
        file_bytes = _read_regular_file(
            file_path,
            label="Gate 3 worktree file",
            max_bytes=_MAX_GATE3_PATCH_BYTES,
        )
        if hashlib.sha256(file_bytes).hexdigest() != entry["sha256"]:
            raise ValueError("Gate 3 worktree file digest mismatch")
        parent_fd, name = _open_parent_directory(file_path, create=False)
        try:
            observed_mode = stat.S_IMODE(
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False).st_mode
            )
        finally:
            os.close(parent_fd)
        if observed_mode & 0o111:
            raise ValueError("Gate 3 worktree file mode mismatch")
        entry_paths.append(entry["path"])
    if entry_paths != manifest["scoped_paths"] or len(set(entry_paths)) != 3:
        raise ValueError("Gate 3 scoped paths do not match file entries")
    identity = {
        "base_commit": base_commit,
        "candidate_digest": manifest_digest,
        "candidate_id": candidate_id,
        "final_backtest_receipt_id": final_backtest_receipt_id,
        "files": manifest["files"],
        "patch_sha256": manifest["patch_sha256"],
        "scoped_paths": manifest["scoped_paths"],
    }
    try:
        identity_bytes = json.dumps(
            identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise ValueError("invalid Gate 3 promotion identity") from exc
    base_promotion_id = f"promo-{hashlib.sha256(identity_bytes).hexdigest()[:32]}"
    if promotion_id != base_promotion_id and not re.fullmatch(
        re.escape(base_promotion_id) + r"-r(?:[2-9]|[1-9][0-9]+)",
        promotion_id,
    ):
        raise ValueError("Gate 3 promotion ID is not deterministic")

    def git_bytes(*args: str) -> bytes:
        try:
            completed = subprocess.run(
                ["git", "-C", str(worktree), *args],
                check=False,
                capture_output=True,
                shell=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("Gate 3 git verification failed") from exc
        if completed.returncode != 0:
            raise ValueError("Gate 3 git verification failed")
        return completed.stdout

    try:
        git_root = git_bytes("rev-parse", "--show-toplevel").decode("utf-8").strip()
        git_head = git_bytes("rev-parse", "HEAD").decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("Gate 3 git identity is invalid") from exc
    if Path(os.path.realpath(git_root)) != Path(os.path.realpath(worktree)):
        raise ValueError("Gate 3 worktree is not a git root")
    if git_head != base_commit:
        raise ValueError("Gate 3 worktree HEAD does not match base commit")

    raw_status = git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all")
    status_paths: list[str] = []
    for raw_record in raw_status.split(b"\0"):
        if not raw_record:
            continue
        if len(raw_record) < 4 or raw_record[2:3] != b" ":
            raise ValueError("Gate 3 worktree status is not canonical")
        if raw_record[:2] not in {b" M", b" A"}:
            raise ValueError("Gate 3 worktree has unexpected staged or dirty state")
        try:
            status_paths.append(raw_record[3:].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("Gate 3 worktree status path is invalid") from exc
    if len(status_paths) != 3 or set(status_paths) != set(manifest["scoped_paths"]):
        raise ValueError("Gate 3 worktree contains unexpected dirty paths")

    observed_patch = git_bytes(
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-textconv",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--",
        *manifest["scoped_paths"],
    )
    if observed_patch != patch:
        raise ValueError("Gate 3 prepared patch differs from worktree")
    return {
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "patch_sha256": manifest["patch_sha256"],
        "candidate_id": candidate_id,
        "candidate_digest": manifest_digest,
        "final_backtest_receipt_id": final_backtest_receipt_id,
        "base_commit": base_commit,
        "scoped_paths": manifest["scoped_paths"],
    }


def find_exact_gate3_receipt(
    *,
    gate_dir: Path,
    experiment_output_dir: Path,
    candidate_id: str,
    manifest_digest: str,
    final_backtest_receipt_id: str,
    base_commit: str,
    promotion_root: Path,
    worktree_root: Path,
) -> Optional[dict[str, str]]:
    """Read-only recovery for one lost Gate 3 prepare receipt."""
    final_backtest = require_final_backtest_receipt(
        gate_dir=gate_dir,
        experiment_output_dir=experiment_output_dir,
        receipt_id=final_backtest_receipt_id,
        candidate_id=candidate_id,
        manifest_digest=manifest_digest,
    )
    factor_id = final_backtest.get("factor_id")
    if (
        not isinstance(factor_id, str)
        or _CANDIDATE_ID_RE.fullmatch(factor_id) is None
        or _GIT_COMMIT_RE.fullmatch(base_commit) is None
    ):
        raise ValueError("invalid Gate 3 recovery binding")

    root = Path(os.path.abspath(promotion_root))
    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("Gate 3 promotion root is unsafe")
    entries = sorted(root.iterdir(), key=lambda item: item.name)
    if len(entries) > _MAX_PROMOTION_SCAN_ENTRIES:
        raise ValueError("Gate 3 promotion recovery scan exceeds quota")

    matches: list[dict[str, str]] = []
    for entry in entries:
        if _PROMOTION_ID_RE.fullmatch(entry.name) is None:
            continue
        entry_stat = entry.lstat()
        if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(entry_stat.st_mode):
            raise ValueError("Gate 3 promotion record is unsafe")
        manifest_path = entry / "manifest.v1.json"
        try:
            manifest = json.loads(
                _read_regular_file(
                    manifest_path,
                    label="Gate 3 recovery manifest",
                    max_bytes=_MAX_GATE1_SOURCE_BYTES,
                ).decode("utf-8")
            )
        except FileNotFoundError:
            continue
        if not isinstance(manifest, dict):
            raise ValueError("invalid Gate 3 recovery manifest")
        if (
            manifest.get("candidate_id") != candidate_id
            or manifest.get("candidate_digest") != manifest_digest
            or manifest.get("final_backtest_receipt_id")
            != final_backtest_receipt_id
            or manifest.get("base_commit") != base_commit
        ):
            continue
        receipt = {
            "promotion_id": entry.name,
            "worktree": str(Path(os.path.abspath(worktree_root)) / entry.name),
            "patch": str(entry / "scoped.patch"),
            "manifest": str(manifest_path),
        }
        verify_gate3_receipt(
            receipt,
            candidate_id=candidate_id,
            manifest_digest=manifest_digest,
            final_backtest_receipt_id=final_backtest_receipt_id,
            factor_id=factor_id,
            base_commit=base_commit,
            promotion_root=root,
            worktree_root=worktree_root,
        )
        matches.append(receipt)
    if len(matches) > 1:
        raise ValueError("multiple exact Gate 3 recovery receipts found")
    return matches[0] if matches else None


def parse_json_payload(output: str) -> Optional[dict]:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except (json.JSONDecodeError, RecursionError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None
    return None


def parse_candidate_id(output: str) -> Optional[str]:
    payload = parse_json_payload(output)
    if payload is not None:
        candidate_id = payload.get("candidate_id")
        if candidate_id is not None:
            return str(candidate_id)
    match = _CANDIDATE_RE.search(output)
    return match.group(1) if match else None


def parse_experiment_summary(output: str) -> dict[str, str]:
    payload = parse_json_payload(output)
    if payload is not None and "experiment_id" in payload:
        # Drop null values instead of stringifying them: a JSON null best_run_id
        # would otherwise become the string "None", defeating the CLI's
        # summary.get("best_run_id", "?") fallback (F7). The regex path below
        # never emits a null, so absence keeps both paths consistent.
        return {
            key: str(value) for key, value in payload.items() if value is not None
        }
    for line in output.splitlines():
        if "experiment_id=" in line:
            return {
                key: value
                for key, _, value in (token.partition("=") for token in line.split() if "=" in token)
            }
    return {}


def parse_candidate_binding(output: str) -> dict[str, str]:
    payload = parse_json_payload(output)
    if payload is None:
        return {}
    binding = payload.get("candidate_binding")
    if not isinstance(binding, dict):
        return {}
    required = ("candidate_id", "manifest_digest", "factor_id")
    if not all(isinstance(binding.get(key), str) for key in required):
        return {}
    return {key: binding[key] for key in required}


def extract_best_run_metrics(agent_summary_json: str) -> dict[str, float]:
    try:
        data = json.loads(agent_summary_json)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    best_id = data.get("best_run_id")
    runs = data.get("runs")
    if not isinstance(runs, list):
        return {}
    for run in runs:
        if isinstance(run, dict) and run.get("run_id") == best_id:
            return {key: run[key] for key in _METRIC_KEYS if key in run}
    return {}
