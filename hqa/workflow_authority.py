from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Callable, Iterator, Optional, Sequence, Tuple

from hqa.agent_workspace_states import WorkspaceStateError, validate_transition
from hqa.workflow_contract import (
    AttemptSnapshot,
    BeginReconcile,
    BindCandidateManifest,
    COMMAND_TYPES,
    CompleteAttempt,
    CompleteTask,
    ConfirmFormula,
    ConfirmPlan,
    ContinueResearch,
    EnterDomainGate,
    ExpiryTombstoneConsumeReport,
    ExpiryTombstoneEvidence,
    Gate3Snapshot,
    LinkResult,
    ObserveGate3,
    ObserveProviderEvidence,
    ObserveRun,
    ObserveStop,
    ObserveSubmission,
    ProposePlan,
    RevisePlan,
    RequestPlanConfirmation,
    RequestStop,
    ResolveDomainGate,
    ResolveReconcile,
    StartResearch,
    WorkflowCommand,
    WorkflowContractError,
    WorkflowEvent,
    WorkflowEventPage,
    WorkflowReceipt,
    WorkflowSnapshot,
    canonical_command_digest,
    normalize_timestamp,
    payload_digest_from_ref,
    validate_event_limit,
)


_SCHEMA_VERSION = 2
_LOCK_NAME = ".workflow-authority-v2.lock"
_JOURNAL_NAME = "workflow-events.v2.jsonl"
_PROJECTION_NAME = "workflow-projection.v2.json"
_MAX_JOURNAL_BYTES = 64 * 1024 * 1024
_MAX_RECORD_BYTES = 64 * 1024
_MAX_BACKUP_BYTES = 72 * 1024 * 1024
_MAX_PROJECTION_BYTES = 64 * 1024 * 1024
_MAX_EVENTS = 100_000
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_RECORD_FIELDS = {
    "schema_version",
    "sequence",
    "event_id",
    "operation_id",
    "operation_digest",
    "owner_user_id",
    "task_ref",
    "attempt_ref",
    "task_version",
    "event_type",
    "occurred_at",
    "data",
    "previous_record_sha256",
    "record_sha256",
}


class WorkflowAuthorityError(RuntimeError):
    """Stable, value-free error raised by the workflow authority."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _error(code: str) -> None:
    raise WorkflowAuthorityError(code)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise WorkflowAuthorityError("workflow_invalid_json") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _reject_duplicates(pairs: Sequence[Tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if type(key) is not str or key in value:
            raise ValueError("duplicate or non-string key")
        value[key] = item
    return value


def _strict_loads(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise WorkflowAuthorityError("workflow_journal_corrupt") from exc


def _safe_ref(value: Any, prefix: str) -> bool:
    return (
        type(value) is str
        and value.startswith(prefix)
        and _IDENTIFIER_RE.fullmatch(value[len(prefix) :]) is not None
    )


def _safe_digest(value: Any) -> bool:
    return type(value) is str and _HEX64_RE.fullmatch(value) is not None


def _safe_event_ref(value: Any) -> bool:
    return (
        type(value) is str
        and value.startswith("event:")
        and _HEX64_RE.fullmatch(value[len("event:") :]) is not None
    )


def _require_fields(value: Any, fields: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _error("workflow_journal_corrupt")
    return value


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_time(value: str) -> datetime:
    normalized = normalize_timestamp(value, "timestamp")
    return datetime.fromisoformat(normalized[:-1] + "+00:00")


def _validate_owner_id(value: Any) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _error("workflow_invalid_owner")
    return value


def _copy_json(value: Any) -> Any:
    return json.loads(_canonical_bytes(value).decode("utf-8"))


@dataclass(frozen=True)
class _ExpiryMutation:
    operation_id: str
    task_ref: str
    expected_version: int
    attempt_ref: str
    payload_ref: str
    tombstone_event_ref: str
    tombstone_digest: str

    def __post_init__(self) -> None:
        if (
            _IDENTIFIER_RE.fullmatch(self.operation_id) is None
            or not _safe_ref(self.task_ref, "task:")
            or type(self.expected_version) is not int
            or not 1 <= self.expected_version <= 2**63 - 1
            or not _safe_ref(self.attempt_ref, "attempt:")
            or not _safe_ref(self.payload_ref, "payload:sha256:")
            or not _safe_event_ref(self.tombstone_event_ref)
            or not _safe_digest(self.tombstone_digest)
        ):
            _error("workflow_invalid_internal_expiry")


@dataclass(frozen=True)
class _ExpireIntent(_ExpiryMutation):
    """Private state-closing form used only by the retention bridge."""


@dataclass(frozen=True)
class _ObservePayloadTombstone(_ExpiryMutation):
    """Private metadata-only form used only by the retention bridge."""


def _expiry_command_document(command: _ExpiryMutation) -> dict[str, Any]:
    kinds = {
        _ExpireIntent: "workflow.expire_intent",
        _ObservePayloadTombstone: "workflow.observe_payload_tombstone",
    }
    kind = kinds.get(type(command))
    if kind is None:
        raise TypeError("unknown internal expiry mutation")
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": kind,
        "operation_id": command.operation_id,
        "task_ref": command.task_ref,
        "expected_version": command.expected_version,
        "attempt_ref": command.attempt_ref,
        "payload_ref": command.payload_ref,
        "tombstone_event_ref": command.tombstone_event_ref,
        "tombstone_digest": command.tombstone_digest,
    }


def _canonical_expiry_command_digest(command: _ExpiryMutation) -> str:
    return _sha256(_canonical_bytes(_expiry_command_document(command)))


class WorkflowAuthority:
    """Owner-scoped, append-only v2 authority for research workflow facts.

    The journal stores references and digests only.  It has no platform,
    Hermes, provider, database, migration, or dispatch adapter.
    """

    def __init__(
        self,
        root: Path,
        owner_user_id: str,
        *,
        now: Optional[Callable[[], str]] = None,
    ) -> None:
        self.root = Path(os.path.abspath(root))
        if self.root == Path(self.root.anchor):
            raise ValueError("workflow root must not be the filesystem root")
        self.owner_user_id = _validate_owner_id(owner_user_id)
        self._now = now or _now_utc

    @property
    def journal_path(self) -> Path:
        return self.root / _JOURNAL_NAME

    @property
    def projection_path(self) -> Path:
        return self.root / _PROJECTION_NAME

    @property
    def lock_path(self) -> Path:
        return self.root / _LOCK_NAME

    def apply(self, command: WorkflowCommand) -> WorkflowReceipt:
        if type(command) not in COMMAND_TYPES:
            raise TypeError(
                "WorkflowAuthority accepts only the closed WorkflowCommand union"
            )
        return self._apply_command(command, canonical_command_digest(command))

    def _apply_expiry_mutation(
        self, command: _ExpiryMutation
    ) -> WorkflowReceipt:
        if type(command) not in (_ExpireIntent, _ObservePayloadTombstone):
            raise TypeError("unknown internal expiry mutation")
        return self._apply_command(
            command,
            _canonical_expiry_command_digest(command),
        )

    def _apply_command(
        self,
        command: WorkflowCommand | _ExpiryMutation,
        operation_digest: str,
    ) -> WorkflowReceipt:
        with self._locked(create=True) as root_fd:
            records = self._load_records(root_fd)
            projection = self._replay(records)
            existing = projection["operations"].get(command.operation_id)
            if existing is not None:
                if existing["operation_digest"] != operation_digest:
                    _error("workflow_idempotency_conflict")
                self._repair_disposable_projection(root_fd, projection)
                return self._receipt_from_document(existing["receipt"], replayed=True)

            if len(records) >= _MAX_EVENTS:
                _error("workflow_event_quota")
            occurred_at = normalize_timestamp(self._now(), "occurred_at")
            event_type, task_ref, attempt_ref, data = self._plan_event(
                projection,
                command,
                operation_digest,
                occurred_at,
            )
            task_version = 1
            if type(command) is not StartResearch:
                task_version = projection["tasks"][task_ref]["version"] + 1
            record = self._build_record(
                sequence=len(records) + 1,
                previous_record_sha256=(
                    records[-1]["record_sha256"] if records else None
                ),
                operation_id=command.operation_id,
                operation_digest=operation_digest,
                task_ref=task_ref,
                attempt_ref=attempt_ref,
                task_version=task_version,
                event_type=event_type,
                occurred_at=occurred_at,
                data=data,
            )

            candidate_projection = _copy_json(projection)
            self._reduce(candidate_projection, record)
            self._projection_bytes(candidate_projection)
            self._append_record(root_fd, record)
            self._write_projection(root_fd, candidate_projection)
            receipt_document = candidate_projection["operations"][
                command.operation_id
            ]["receipt"]
            return self._receipt_from_document(receipt_document, replayed=False)

    def snapshot(self, task_ref: str) -> WorkflowSnapshot:
        if not _safe_ref(task_ref, "task:"):
            _error("workflow_invalid_ref")
        with self._locked(create=False) as root_fd:
            projection = self._replay(self._load_records(root_fd))
            self._repair_disposable_projection(root_fd, projection)
            task = projection["tasks"].get(task_ref)
            if task is None:
                _error("workflow_task_not_found")
            return self._snapshot_from_task(task)

    def consume_expiry_tombstones(
        self,
        evidences: Tuple[ExpiryTombstoneEvidence, ...],
        *,
        limit: int = 100,
    ) -> ExpiryTombstoneConsumeReport:
        """Consume a bounded batch of exact payload tombstones via CAS.

        This in-process retention seam is intentionally separate from the
        read-only Hermes CLI. It accepts no bodies. A latest, untouched planned
        Attempt may close as ``intent_expired``; every other Attempt receives a
        metadata-only tombstone observation that preserves workflow outcome.
        """
        if type(limit) is not int or not 1 <= limit <= 1_000:
            _error("workflow_batch_quota")
        if type(evidences) is not tuple:
            _error("workflow_invalid_batch")
        if len(evidences) > limit:
            _error("workflow_batch_quota")

        unique: list[ExpiryTombstoneEvidence] = []
        seen_events: dict[str, ExpiryTombstoneEvidence] = {}
        seen_attempts: dict[str, ExpiryTombstoneEvidence] = {}
        seen_payloads: dict[str, ExpiryTombstoneEvidence] = {}
        for evidence in evidences:
            if type(evidence) is not ExpiryTombstoneEvidence:
                _error("workflow_invalid_batch")
            if evidence.owner_user_id != self.owner_user_id:
                _error("workflow_binding_conflict")
            duplicate = False
            for index, key in (
                (seen_events, evidence.tombstone_event_ref),
                (seen_attempts, evidence.attempt_ref),
                (seen_payloads, evidence.payload_ref),
            ):
                existing = index.get(key)
                if existing is not None and existing != evidence:
                    _error("workflow_binding_conflict")
                if existing == evidence:
                    duplicate = True
                index[key] = evidence
            if not duplicate:
                unique.append(evidence)

        receipts = [
            self._consume_expiry_tombstone(evidence) for evidence in unique
        ]
        return ExpiryTombstoneConsumeReport(
            receipts=tuple(receipts),
            consumed_count=sum(not receipt.replayed for receipt in receipts),
            replayed_count=sum(receipt.replayed for receipt in receipts),
        )

    def events(
        self,
        task_ref: str,
        after_event_id: Optional[str] = None,
        limit: int = 100,
    ) -> WorkflowEventPage:
        if not _safe_ref(task_ref, "task:"):
            _error("workflow_invalid_ref")
        validate_event_limit(limit)
        if after_event_id is not None and not _safe_event_ref(after_event_id):
            _error("workflow_invalid_cursor")
        with self._locked(create=False) as root_fd:
            records = self._load_records(root_fd)
            projection = self._replay(records)
            self._repair_disposable_projection(root_fd, projection)
            if task_ref not in projection["tasks"]:
                _error("workflow_task_not_found")
            task_records = [record for record in records if record["task_ref"] == task_ref]
            start = 0
            if after_event_id is not None:
                matching = [
                    index
                    for index, record in enumerate(task_records)
                    if record["event_id"] == after_event_id
                ]
                if len(matching) != 1:
                    _error("workflow_event_cursor_stale")
                start = matching[0] + 1
            selected = task_records[start : start + limit]
            events = tuple(self._public_event(record) for record in selected)
            return WorkflowEventPage(
                events=events,
                next_after_event_id=(
                    events[-1].event_id if events else after_event_id
                ),
                has_more=start + len(selected) < len(task_records),
            )

    def rebuild_projection(self) -> dict[str, Any]:
        with self._locked(create=False) as root_fd:
            projection = self._replay(self._load_records(root_fd))
            self._write_projection(root_fd, projection)
            return self._audit_document(projection, "consistent")

    def reverse_audit(self) -> dict[str, Any]:
        with self._locked(create=False) as root_fd:
            records = self._load_records(root_fd)
            projection = self._replay(records)
            expected = self._projection_bytes(projection)
            if not self._entry_exists(root_fd, _PROJECTION_NAME):
                return self._audit_document(projection, "projection_missing")
            actual = self._read_secure_entry(
                root_fd,
                _PROJECTION_NAME,
                _MAX_PROJECTION_BYTES,
                "workflow projection",
            )
            status_value = "consistent" if actual == expected else "projection_mismatch"
            return self._audit_document(projection, status_value)

    def backup(self, destination: Path) -> dict[str, Any]:
        destination = Path(destination)
        with self._locked(create=False) as root_fd:
            records = self._load_records(root_fd)
            projection = self._replay(records)
            projection_bytes = self._projection_bytes(projection)
            journal_bytes = b"".join(
                _canonical_bytes(record) + b"\n" for record in records
            )
            backup_document = {
                "schema_version": _SCHEMA_VERSION,
                "kind": "workflow_authority_backup",
                "owner_user_id": self.owner_user_id,
                "event_count": len(records),
                "journal_sha256": _sha256(journal_bytes),
                "projection_sha256": _sha256(projection_bytes),
                "records": records,
            }
            content = _canonical_bytes(backup_document)
            if len(content) > _MAX_BACKUP_BYTES:
                _error("workflow_backup_quota")
            self._write_exclusive(destination, content)
            return {
                "schema_version": _SCHEMA_VERSION,
                "event_count": len(records),
                "journal_sha256": backup_document["journal_sha256"],
                "projection_sha256": backup_document["projection_sha256"],
                "backup_sha256": _sha256(content),
            }

    def restore(self, source: Path) -> dict[str, Any]:
        source = Path(source)
        backup_document = self._read_backup(source)
        records = backup_document["records"]
        projection = self._replay(records)
        projection_bytes = self._projection_bytes(projection)
        if _sha256(projection_bytes) != backup_document[
            "projection_sha256"
        ]:
            _error("workflow_backup_corrupt")
        journal_bytes = b"".join(
            _canonical_bytes(record) + b"\n" for record in records
        )
        if _sha256(journal_bytes) != backup_document["journal_sha256"]:
            _error("workflow_backup_corrupt")

        with self._locked(create=True) as root_fd:
            allowed = {self.lock_path.name, _JOURNAL_NAME, _PROJECTION_NAME}
            if any(name not in allowed for name in os.listdir(root_fd)):
                _error("workflow_restore_conflict")
            if self._entry_exists(root_fd, _JOURNAL_NAME):
                existing_records = self._load_records(root_fd)
                existing_projection = self._replay(existing_records)
                existing_journal = b"".join(
                    _canonical_bytes(record) + b"\n"
                    for record in existing_records
                )
                if (
                    _sha256(existing_journal)
                    != backup_document["journal_sha256"]
                    or _sha256(self._projection_bytes(existing_projection))
                    != backup_document["projection_sha256"]
                ):
                    _error("workflow_restore_conflict")
                self._write_projection(root_fd, existing_projection)
                return self._audit_document(existing_projection, "consistent")
            if self._entry_exists(root_fd, _PROJECTION_NAME):
                _error("workflow_restore_conflict")
            self._write_new_entry(root_fd, _JOURNAL_NAME, journal_bytes)
            self._write_projection(root_fd, projection)
            return self._audit_document(projection, "consistent")

    @contextmanager
    def _locked(self, *, create: bool) -> Iterator[int]:
        root_fd = self._open_root(create=create)
        if root_fd is None:
            _error("workflow_authority_not_found")
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        lock_flags = os.O_RDWR | no_follow
        lock_exists = self._entry_exists(root_fd, _LOCK_NAME)
        try:
            if create and not lock_exists:
                try:
                    lock_fd = os.open(
                        _LOCK_NAME,
                        lock_flags | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=root_fd,
                    )
                    os.fsync(root_fd)
                except FileExistsError:
                    lock_fd = os.open(_LOCK_NAME, lock_flags, dir_fd=root_fd)
            else:
                if not lock_exists:
                    _error("workflow_authority_not_found")
                lock_fd = os.open(_LOCK_NAME, lock_flags, dir_fd=root_fd)
        except WorkflowAuthorityError:
            os.close(root_fd)
            raise
        except OSError as exc:
            os.close(root_fd)
            if getattr(exc, "errno", None) == errno.ELOOP:
                raise WorkflowAuthorityError("workflow_storage_insecure") from exc
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc
        acquired = False
        try:
            self._assert_secure_file(lock_fd, "workflow lock", 0o600)
            self._assert_path_identity(root_fd, _LOCK_NAME, lock_fd)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            acquired = True
            self._assert_path_identity(root_fd, _LOCK_NAME, lock_fd)
            self._cleanup_stale_temporaries(root_fd)
            self._validate_root_inventory(root_fd)
            yield root_fd
        finally:
            if acquired:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(lock_fd)
            os.close(root_fd)

    def _open_root(self, *, create: bool) -> Optional[int]:
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            current_fd = os.open(self.root.anchor or os.sep, flags)
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc
        try:
            components = self.root.parts[1:]
            for index, component in enumerate(components):
                final = index == len(components) - 1
                if create:
                    try:
                        os.mkdir(
                            component,
                            0o700 if final else 0o755,
                            dir_fd=current_fd,
                        )
                        os.fsync(current_fd)
                    except FileExistsError:
                        pass
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except FileNotFoundError:
                    if not create:
                        os.close(current_fd)
                        return None
                    raise
                except OSError as exc:
                    if getattr(exc, "errno", None) in (
                        errno.ENOTDIR,
                        errno.ELOOP,
                    ):
                        raise WorkflowAuthorityError(
                            "workflow_storage_insecure"
                        ) from exc
                    raise
                os.close(current_fd)
                current_fd = next_fd
                if final:
                    metadata = os.fstat(current_fd)
                    if (
                        not stat.S_ISDIR(metadata.st_mode)
                        or stat.S_IMODE(metadata.st_mode) != 0o700
                        or metadata.st_uid != os.geteuid()
                    ):
                        _error("workflow_storage_insecure")
            return current_fd
        except Exception:
            try:
                os.close(current_fd)
            except OSError:
                pass
            raise

    def _authority_root_exists(self) -> bool:
        root_fd = self._open_root(create=False)
        if root_fd is None:
            return False
        os.close(root_fd)
        return True

    @staticmethod
    def _entry_exists(parent_fd: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _assert_secure_file(fd: int, _label: str, mode: int) -> None:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
        ):
            _error("workflow_storage_insecure")

    @staticmethod
    def _assert_path_identity(parent_fd: int, name: str, fd: int) -> None:
        opened = os.fstat(fd)
        try:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_journal_corrupt") from exc
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            _error("workflow_journal_corrupt")

    def _validate_root_inventory(self, root_fd: int) -> None:
        allowed = {_LOCK_NAME, _JOURNAL_NAME, _PROJECTION_NAME}
        if set(os.listdir(root_fd)) - allowed:
            _error("workflow_journal_corrupt")

    def _cleanup_stale_temporaries(self, root_fd: int) -> None:
        prefixes = (
            "." + _JOURNAL_NAME + ".",
            "." + _PROJECTION_NAME + ".",
        )
        try:
            for name in os.listdir(root_fd):
                if not name.startswith(prefixes):
                    continue
                descriptor = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=root_fd,
                )
                try:
                    self._assert_secure_file(
                        descriptor, "workflow temporary", 0o600
                    )
                    self._assert_path_identity(root_fd, name, descriptor)
                finally:
                    os.close(descriptor)
                os.unlink(name, dir_fd=root_fd)
                os.fsync(root_fd)
        except WorkflowAuthorityError:
            raise
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc

    def _load_records(self, root_fd: int) -> list[dict[str, Any]]:
        if not self._entry_exists(root_fd, _JOURNAL_NAME):
            if self._entry_exists(root_fd, _PROJECTION_NAME):
                _error("workflow_journal_corrupt")
            return []
        try:
            raw = self._read_secure_entry(
                root_fd,
                _JOURNAL_NAME,
                _MAX_JOURNAL_BYTES,
                "workflow journal",
            )
            records: list[dict[str, Any]] = []
            if raw and not raw.endswith(b"\n"):
                _error("workflow_journal_corrupt")
            for line in raw.splitlines(keepends=True):
                if len(line) > _MAX_RECORD_BYTES + 1 or line == b"\n":
                    _error("workflow_journal_corrupt")
                payload = line[:-1]
                record = _strict_loads(payload)
                if type(record) is not dict or _canonical_bytes(record) != payload:
                    _error("workflow_journal_corrupt")
                records.append(record)
                if len(records) > _MAX_EVENTS:
                    _error("workflow_journal_quota")
            return records
        except WorkflowAuthorityError:
            raise
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc

    def _read_secure_entry(
        self,
        root_fd: int,
        name: str,
        ceiling: int,
        label: str,
    ) -> bytes:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
        except OSError as exc:
            if getattr(exc, "errno", None) == errno.ELOOP:
                raise WorkflowAuthorityError("workflow_storage_insecure") from exc
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc
        try:
            self._assert_secure_file(descriptor, label, 0o600)
            self._assert_path_identity(root_fd, name, descriptor)
            metadata = os.fstat(descriptor)
            if metadata.st_size > ceiling:
                _error(
                    "workflow_projection_quota"
                    if name == _PROJECTION_NAME
                    else "workflow_journal_quota"
                )
            chunks = []
            remaining = ceiling + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if len(content) > ceiling:
                _error(
                    "workflow_projection_quota"
                    if name == _PROJECTION_NAME
                    else "workflow_journal_quota"
                )
            self._assert_path_identity(root_fd, name, descriptor)
            return content
        finally:
            os.close(descriptor)

    def _replay(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "owner_user_id": self.owner_user_id,
            "last_sequence": 0,
            "last_record_sha256": None,
            "operations": {},
            "bindings": {
                "command_refs": {},
                "run_refs": {},
                "provider_evidence_refs": {},
                "result_refs": {},
                "gate_refs": {},
                "tombstone_event_refs": {},
                "payload_tombstone_observations": {},
                "candidate_refs": {},
                "payload_refs": {},
            },
            "tasks": {},
        }
        previous: Optional[str] = None
        for expected_sequence, record in enumerate(records, start=1):
            try:
                self._validate_record(record, expected_sequence, previous)
                self._reduce(projection, record)
            except WorkflowAuthorityError as exc:
                if exc.code in (
                    "workflow_journal_quota",
                    "workflow_storage_insecure",
                    "workflow_storage_unavailable",
                ):
                    raise
                raise WorkflowAuthorityError("workflow_journal_corrupt") from exc
            previous = record["record_sha256"]
        return projection

    def _validate_record(
        self,
        record: dict[str, Any],
        expected_sequence: int,
        previous: Optional[str],
    ) -> None:
        if set(record) != _RECORD_FIELDS:
            _error("workflow_journal_corrupt")
        if record["schema_version"] != _SCHEMA_VERSION:
            _error("workflow_journal_corrupt")
        if type(record["sequence"]) is not int or record["sequence"] != expected_sequence:
            _error("workflow_journal_corrupt")
        if record["previous_record_sha256"] != previous:
            _error("workflow_journal_corrupt")
        if record["owner_user_id"] != self.owner_user_id:
            _error("workflow_journal_corrupt")
        if not _safe_event_ref(record["event_id"]):
            _error("workflow_journal_corrupt")
        if not _safe_digest(record["operation_digest"]):
            _error("workflow_journal_corrupt")
        if not _safe_digest(record["record_sha256"]):
            _error("workflow_journal_corrupt")
        if (
            type(record["operation_id"]) is not str
            or _IDENTIFIER_RE.fullmatch(record["operation_id"]) is None
        ):
            _error("workflow_journal_corrupt")
        if not _safe_ref(record["task_ref"], "task:"):
            _error("workflow_journal_corrupt")
        if record["attempt_ref"] is not None and not _safe_ref(
            record["attempt_ref"], "attempt:"
        ):
            _error("workflow_journal_corrupt")
        if (
            type(record["task_version"]) is not int
            or not 1 <= record["task_version"] <= 2**63 - 1
        ):
            _error("workflow_journal_corrupt")
        if (
            type(record["event_type"]) is not str
            or _IDENTIFIER_RE.fullmatch(record["event_type"]) is None
        ):
            _error("workflow_journal_corrupt")
        try:
            normalized = normalize_timestamp(record["occurred_at"], "occurred_at")
        except WorkflowContractError as exc:
            raise WorkflowAuthorityError("workflow_journal_corrupt") from exc
        if normalized != record["occurred_at"]:
            _error("workflow_journal_corrupt")
        expected_event_id = self._semantic_event_id(
            record["operation_id"],
            record["operation_digest"],
            record["task_ref"],
            record["event_type"],
        )
        if record["event_id"] != expected_event_id:
            _error("workflow_journal_corrupt")
        unhashed = dict(record)
        del unhashed["record_sha256"]
        if _sha256(_canonical_bytes(unhashed)) != record["record_sha256"]:
            _error("workflow_journal_corrupt")

    def _build_record(
        self,
        *,
        sequence: int,
        previous_record_sha256: Optional[str],
        operation_id: str,
        operation_digest: str,
        task_ref: str,
        attempt_ref: Optional[str],
        task_version: int,
        event_type: str,
        occurred_at: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "schema_version": _SCHEMA_VERSION,
            "sequence": sequence,
            "event_id": self._semantic_event_id(
                operation_id,
                operation_digest,
                task_ref,
                event_type,
            ),
            "operation_id": operation_id,
            "operation_digest": operation_digest,
            "owner_user_id": self.owner_user_id,
            "task_ref": task_ref,
            "attempt_ref": attempt_ref,
            "task_version": task_version,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "data": data,
            "previous_record_sha256": previous_record_sha256,
        }
        record["record_sha256"] = _sha256(_canonical_bytes(record))
        return record

    def _semantic_event_id(
        self,
        operation_id: str,
        operation_digest: str,
        task_ref: str,
        event_type: str,
    ) -> str:
        return "event:" + _sha256(
            _canonical_bytes(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "owner_user_id": self.owner_user_id,
                    "operation_id": operation_id,
                    "operation_digest": operation_digest,
                    "task_ref": task_ref,
                    "event_type": event_type,
                }
            )
        )

    def _generated_ref(self, prefix: str, *parts: Any) -> str:
        return prefix + _sha256(_canonical_bytes(list(parts)))

    def _plan_event(
        self,
        projection: dict[str, Any],
        command: WorkflowCommand | _ExpiryMutation,
        operation_digest: str,
        occurred_at: str,
    ) -> tuple[str, str, Optional[str], dict[str, Any]]:
        if type(command) is StartResearch:
            if _parse_time(occurred_at) >= _parse_time(command.intent_expires_at):
                _error("workflow_intent_expired")
            task_ref = self._generated_ref(
                "task:", self.owner_user_id, command.operation_id, operation_digest
            )
            attempt_ref = self._generated_ref(
                "attempt:", task_ref, 1, operation_digest
            )
            if task_ref in projection["tasks"]:
                _error("workflow_binding_conflict")
            return (
                "research_started",
                task_ref,
                attempt_ref,
                {
                    "workspace_ref": command.workspace_ref,
                    "managed_session_ref": command.managed_session_ref,
                    "attempt_ref": attempt_ref,
                    "attempt_number": 1,
                    "payload_ref": command.payload_ref,
                    "payload_digest": payload_digest_from_ref(command.payload_ref),
                    "intent_expires_at": command.intent_expires_at,
                },
            )

        task = projection["tasks"].get(command.task_ref)
        if task is None:
            _error("workflow_task_not_found")
        if type(command) is _ObservePayloadTombstone:
            if command.expected_version != task["version"]:
                _error("workflow_stale_version")
            attempt = self._attempt(task, command.attempt_ref)
            if attempt["payload_ref"] != command.payload_ref:
                _error("workflow_binding_conflict")
            if _parse_time(occurred_at) < _parse_time(
                attempt["intent_expires_at"]
            ):
                _error("workflow_intent_not_expired")
            return (
                "payload_tombstone_observed",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "payload_ref": command.payload_ref,
                    "tombstone_event_ref": command.tombstone_event_ref,
                    "tombstone_digest": command.tombstone_digest,
                },
            )
        if task["state"] == "terminal":
            _error("workflow_terminal_immutable")
        if command.expected_version != task["version"]:
            _error("workflow_stale_version")

        if type(command) is ContinueResearch:
            if _parse_time(occurred_at) >= _parse_time(command.intent_expires_at):
                _error("workflow_intent_expired")
            number = len(task["attempts"]) + 1
            attempt_ref = self._generated_ref(
                "attempt:", task["task_ref"], number, operation_digest
            )
            return (
                "research_continued",
                task["task_ref"],
                attempt_ref,
                {
                    "attempt_ref": attempt_ref,
                    "attempt_number": number,
                    "payload_ref": command.payload_ref,
                    "payload_digest": payload_digest_from_ref(command.payload_ref),
                    "intent_expires_at": command.intent_expires_at,
                    "plan_version": task["plan_version"],
                    "plan_digest": task["plan_digest"],
                    "plan_source_ref": task["plan_source_ref"],
                },
            )
        if type(command) is ProposePlan:
            return (
                "plan_proposed",
                task["task_ref"],
                task["attempts"][-1]["attempt_ref"],
                {
                    "plan_version": command.plan_version,
                    "plan_digest": command.plan_digest,
                    "plan_source_ref": command.plan_source_ref,
                    "requires_formula_confirmation": (
                        command.requires_formula_confirmation
                    ),
                },
            )
        if type(command) is RevisePlan:
            return (
                "plan_revised",
                task["task_ref"],
                task["attempts"][-1]["attempt_ref"],
                {
                    "plan_version": command.plan_version,
                    "plan_digest": command.plan_digest,
                    "plan_source_ref": command.plan_source_ref,
                    "requires_formula_confirmation": (
                        command.requires_formula_confirmation
                    ),
                },
            )
        if type(command) is RequestPlanConfirmation:
            return (
                "plan_confirmation_requested",
                task["task_ref"],
                task["attempts"][-1]["attempt_ref"],
                {
                    "plan_version": command.plan_version,
                    "plan_digest": command.plan_digest,
                },
            )
        if type(command) is ConfirmPlan:
            return (
                "plan_confirmed",
                task["task_ref"],
                task["attempts"][-1]["attempt_ref"],
                {
                    "plan_version": command.plan_version,
                    "plan_digest": command.plan_digest,
                    "confirmation_note_digest": _sha256(
                        command.confirmation_note.encode("utf-8")
                    ),
                },
            )
        if type(command) is ConfirmFormula:
            return (
                "formula_confirmed",
                task["task_ref"],
                task["attempts"][-1]["attempt_ref"],
                {
                    "gate_ref": command.gate_ref,
                    "reviewed_source_digest": command.reviewed_source_digest,
                    "confirmation_note_digest": _sha256(
                        command.confirmation_note.encode("utf-8")
                    ),
                },
            )
        if type(command) is BindCandidateManifest:
            return (
                "candidate_manifest_bound",
                task["task_ref"],
                task["attempts"][-1]["attempt_ref"],
                {
                    "gate_ref": command.gate_ref,
                    "candidate_ref": command.candidate_ref,
                    "manifest_digest": command.manifest_digest,
                },
            )
        if type(command) is ObserveSubmission:
            return (
                "submission_observed",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "command_ref": command.command_ref,
                },
            )
        if type(command) is ObserveRun:
            return (
                "run_observed",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "command_ref": command.command_ref,
                    "run_ref": command.run_ref,
                },
            )
        if type(command) is ObserveProviderEvidence:
            return (
                "provider_evidence_observed",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "run_ref": command.run_ref,
                    "provider_evidence_ref": command.provider_evidence_ref,
                },
            )
        if type(command) is ObserveGate3:
            return (
                "gate3_observed",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "run_ref": command.run_ref,
                    "gate_ref": command.gate_ref,
                    "candidate_ref": command.candidate_ref,
                    "manifest_digest": command.manifest_digest,
                    "final_receipt_ref": command.final_receipt_ref,
                    "base_commit": command.base_commit,
                },
            )
        if type(command) is LinkResult:
            return (
                "result_linked",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "run_ref": command.run_ref,
                    "result_ref": command.result_ref,
                },
            )
        if type(command) is EnterDomainGate:
            return (
                "domain_gate_entered",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "gate_ref": command.gate_ref,
                },
            )
        if type(command) is ResolveDomainGate:
            return (
                "domain_gate_resolved",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "gate_ref": command.gate_ref,
                    "outcome": command.outcome,
                },
            )
        if type(command) is BeginReconcile:
            return (
                "reconcile_started",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "reason_code": command.reason_code,
                },
            )
        if type(command) is ResolveReconcile:
            return (
                "reconcile_resolved",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "resolved_state": command.resolved_state,
                    "observation_digest": command.observation_digest,
                    "terminal_outcome": command.terminal_outcome,
                },
            )
        if type(command) is RequestStop:
            return (
                "stop_requested",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "run_ref": command.run_ref,
                    "stop_command_ref": command.stop_command_ref,
                },
            )
        if type(command) is ObserveStop:
            return (
                "stop_observed",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "stop_command_ref": command.stop_command_ref,
                    "outcome": command.outcome,
                    "observation_digest": command.observation_digest,
                    "actual_terminal_outcome": (
                        command.actual_terminal_outcome
                    ),
                },
            )
        if type(command) is CompleteAttempt:
            return (
                "attempt_completed",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "terminal_outcome": command.terminal_outcome,
                    "run_ref": command.run_ref,
                    "provider_evidence_ref": command.provider_evidence_ref,
                },
            )
        if type(command) is CompleteTask:
            return (
                "task_completed",
                task["task_ref"],
                task["attempts"][-1]["attempt_ref"],
                {
                    "terminal_outcome": command.terminal_outcome,
                    "run_ref": command.run_ref,
                    "provider_evidence_ref": command.provider_evidence_ref,
                },
            )
        if type(command) is _ExpireIntent:
            attempt = self._attempt(task, command.attempt_ref)
            if attempt["payload_ref"] != command.payload_ref:
                _error("workflow_binding_conflict")
            if _parse_time(occurred_at) < _parse_time(
                attempt["intent_expires_at"]
            ):
                _error("workflow_intent_not_expired")
            return (
                "intent_expired",
                task["task_ref"],
                command.attempt_ref,
                {
                    "attempt_ref": command.attempt_ref,
                    "payload_ref": command.payload_ref,
                    "tombstone_event_ref": command.tombstone_event_ref,
                    "tombstone_digest": command.tombstone_digest,
                },
            )
        raise TypeError("unknown workflow mutation")

    def _reduce(
        self,
        projection: dict[str, Any],
        record: dict[str, Any],
    ) -> None:
        if record["operation_id"] in projection["operations"]:
            _error("workflow_duplicate_operation")
        event_type = record["event_type"]
        data = record["data"]
        task = projection["tasks"].get(record["task_ref"])
        if event_type == "research_started":
            self._reduce_research_started(projection, record, data)
            task = projection["tasks"][record["task_ref"]]
        else:
            if task is None or (
                task["state"] == "terminal"
                and event_type != "payload_tombstone_observed"
            ):
                _error("workflow_terminal_or_missing_task")
            if record["task_version"] != task["version"] + 1:
                _error("workflow_stale_version")
            self._reduce_existing_event(projection, task, record, data)
            task["version"] = record["task_version"]

        projection["last_sequence"] = record["sequence"]
        projection["last_record_sha256"] = record["record_sha256"]
        receipt = {
            "operation_id": record["operation_id"],
            "operation_digest": record["operation_digest"],
            "event_id": record["event_id"],
            "task_ref": record["task_ref"],
            "task_version": record["task_version"],
            "attempt_ref": record["attempt_ref"],
        }
        projection["operations"][record["operation_id"]] = {
            "operation_digest": record["operation_digest"],
            "receipt": receipt,
        }

    def _reduce_research_started(
        self,
        projection: dict[str, Any],
        record: dict[str, Any],
        data: Any,
    ) -> None:
        data = _require_fields(
            data,
            {
                "workspace_ref",
                "managed_session_ref",
                "attempt_ref",
                "attempt_number",
                "payload_ref",
                "payload_digest",
                "intent_expires_at",
            },
        )
        if record["task_version"] != 1 or record["task_ref"] in projection["tasks"]:
            _error("workflow_journal_corrupt")
        expected_task_ref = self._generated_ref(
            "task:",
            self.owner_user_id,
            record["operation_id"],
            record["operation_digest"],
        )
        expected_attempt_ref = self._generated_ref(
            "attempt:", expected_task_ref, 1, record["operation_digest"]
        )
        if (
            record["task_ref"] != expected_task_ref
            or record["attempt_ref"] != expected_attempt_ref
            or data["attempt_ref"] != expected_attempt_ref
        ):
            _error("workflow_binding_conflict")
        if not _safe_ref(data["workspace_ref"], "workspace:") or not _safe_ref(
            data["managed_session_ref"], "session:"
        ):
            _error("workflow_journal_corrupt")
        self._validate_attempt_creation(data, record["attempt_ref"], 1)
        if _parse_time(record["occurred_at"]) >= _parse_time(
            data["intent_expires_at"]
        ):
            _error("workflow_intent_expired")
        self._bind_global(
            projection,
            "payload_refs",
            data["payload_ref"],
            self._payload_index_binding(
                record=record,
                workspace_ref=data["workspace_ref"],
                managed_session_ref=data["managed_session_ref"],
            ),
        )
        projection["tasks"][record["task_ref"]] = {
            "task_ref": record["task_ref"],
            "workspace_ref": data["workspace_ref"],
            "managed_session_ref": data["managed_session_ref"],
            "version": 1,
            "state": "draft",
            "plan_version": None,
            "plan_digest": None,
            "plan_source_ref": None,
            "requires_formula_confirmation": None,
            "plan_confirmation_note_digest": None,
            "gate1_ref": None,
            "gate1_source_digest": None,
            "gate1_note_digest": None,
            "gate1_candidate_ref": None,
            "gate1_manifest_digest": None,
            "gate3_refs": [],
            "result_refs": [],
            "terminal_outcome": None,
            "attempts": [self._new_attempt(data, record)],
        }

    def _reduce_existing_event(
        self,
        projection: dict[str, Any],
        task: dict[str, Any],
        record: dict[str, Any],
        data: Any,
    ) -> None:
        event_type = record["event_type"]
        if event_type == "research_continued":
            data = _require_fields(
                data,
                {
                    "attempt_ref",
                    "attempt_number",
                    "payload_ref",
                    "payload_digest",
                    "intent_expires_at",
                    "plan_version",
                    "plan_digest",
                    "plan_source_ref",
                },
            )
            if task["state"] not in ("ready", "running"):
                _error("workflow_invalid_transition")
            if task["attempts"][-1]["state"] != "terminal":
                _error("workflow_attempt_not_terminal")
            if task["requires_formula_confirmation"] and (
                task["gate1_ref"] is None
                or task["gate1_source_digest"] is None
                or task["gate1_note_digest"] is None
                or task["gate1_candidate_ref"] is None
                or task["gate1_manifest_digest"] is None
            ):
                _error("workflow_binding_conflict")
            if (
                data["plan_version"] != task["plan_version"]
                or data["plan_digest"] != task["plan_digest"]
                or data["plan_source_ref"] != task["plan_source_ref"]
            ):
                _error("workflow_plan_conflict")
            expected_number = len(task["attempts"]) + 1
            self._validate_attempt_creation(
                data, record["attempt_ref"], expected_number
            )
            expected_attempt_ref = self._generated_ref(
                "attempt:",
                task["task_ref"],
                expected_number,
                record["operation_digest"],
            )
            if data["attempt_ref"] != expected_attempt_ref:
                _error("workflow_binding_conflict")
            if _parse_time(record["occurred_at"]) >= _parse_time(
                data["intent_expires_at"]
            ):
                _error("workflow_intent_expired")
            if any(
                attempt["attempt_ref"] == data["attempt_ref"]
                for attempt in task["attempts"]
            ):
                _error("workflow_binding_conflict")
            self._bind_global(
                projection,
                "payload_refs",
                data["payload_ref"],
                self._payload_index_binding(
                    record=record,
                    workspace_ref=task["workspace_ref"],
                    managed_session_ref=task["managed_session_ref"],
                ),
            )
            task["attempts"].append(self._new_attempt(data, record))
            return
        if event_type in ("plan_proposed", "plan_revised"):
            data = _require_fields(
                data,
                {
                    "plan_version",
                    "plan_digest",
                    "plan_source_ref",
                    "requires_formula_confirmation",
                },
            )
            if event_type == "plan_proposed":
                if task["plan_version"] is not None:
                    _error("workflow_plan_conflict")
                expected_plan_version = 1
            else:
                if task["plan_version"] is None:
                    _error("workflow_plan_conflict")
                expected_plan_version = task["plan_version"] + 1
            if type(data["plan_version"]) is not int or data["plan_version"] != expected_plan_version:
                _error("workflow_plan_conflict")
            if not _safe_digest(data["plan_digest"]):
                _error("workflow_journal_corrupt")
            latest_attempt = task["attempts"][-1]
            if (
                not _safe_ref(data["plan_source_ref"], "run:")
                or latest_attempt["run_ref"] != data["plan_source_ref"]
            ):
                _error("workflow_plan_conflict")
            if event_type == "plan_revised" and latest_attempt["state"] != "terminal":
                _error("workflow_attempt_not_terminal")
            self._require_global_binding(
                projection,
                "run_refs",
                data["plan_source_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": latest_attempt["attempt_ref"],
                    "command_ref": latest_attempt["submission_command_ref"],
                },
            )
            if type(data["requires_formula_confirmation"]) is not bool:
                _error("workflow_journal_corrupt")
            if task["state"] != "plan_proposed":
                self._transition_task(task, "plan_proposed")
            task["plan_version"] = data["plan_version"]
            task["plan_digest"] = data["plan_digest"]
            task["plan_source_ref"] = data["plan_source_ref"]
            task["requires_formula_confirmation"] = data[
                "requires_formula_confirmation"
            ]
            task["plan_confirmation_note_digest"] = None
            task["gate1_ref"] = None
            task["gate1_source_digest"] = None
            task["gate1_note_digest"] = None
            task["gate1_candidate_ref"] = None
            task["gate1_manifest_digest"] = None
            return
        if event_type == "plan_confirmation_requested":
            self._validate_plan_binding(task, data)
            self._transition_task(task, "awaiting_plan_confirmation")
            return
        if event_type == "plan_confirmed":
            data = _require_fields(
                data,
                {"plan_version", "plan_digest", "confirmation_note_digest"},
            )
            self._validate_plan_binding(
                task,
                {
                    "plan_version": data["plan_version"],
                    "plan_digest": data["plan_digest"],
                },
            )
            if not _safe_digest(data["confirmation_note_digest"]):
                _error("workflow_journal_corrupt")
            if task["state"] != "awaiting_plan_confirmation":
                _error("workflow_invalid_transition")
            task["plan_confirmation_note_digest"] = data[
                "confirmation_note_digest"
            ]
            destination = (
                "awaiting_formula_confirmation"
                if task["requires_formula_confirmation"]
                else "ready"
            )
            self._transition_task(task, destination)
            return
        if event_type == "formula_confirmed":
            data = _require_fields(
                data,
                {"gate_ref", "reviewed_source_digest", "confirmation_note_digest"},
            )
            if (
                not _safe_ref(data["gate_ref"], "gate:")
                or not _safe_digest(data["reviewed_source_digest"])
                or not _safe_digest(data["confirmation_note_digest"])
            ):
                _error("workflow_journal_corrupt")
            if task["state"] != "awaiting_formula_confirmation":
                _error("workflow_invalid_transition")
            self._bind_global(
                projection,
                "gate_refs",
                data["gate_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": task["attempts"][-1]["attempt_ref"],
                    "role": "gate1",
                },
            )
            task["gate1_ref"] = data["gate_ref"]
            task["gate1_source_digest"] = data["reviewed_source_digest"]
            task["gate1_note_digest"] = data["confirmation_note_digest"]
            self._transition_task(task, "ready")
            return
        if event_type == "candidate_manifest_bound":
            data = _require_fields(
                data,
                {"gate_ref", "candidate_ref", "manifest_digest"},
            )
            if (
                task["gate1_ref"] != data["gate_ref"]
                or task["state"] not in ("ready", "running")
                or not _safe_ref(data["candidate_ref"], "candidate:")
                or not _safe_digest(data["manifest_digest"])
            ):
                _error("workflow_binding_conflict")
            if task["gate1_candidate_ref"] is not None:
                _error("workflow_binding_conflict")
            self._require_global_binding(
                projection,
                "gate_refs",
                data["gate_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": task["attempts"][-1]["attempt_ref"],
                    "role": "gate1",
                },
            )
            self._bind_global(
                projection,
                "candidate_refs",
                data["candidate_ref"],
                {"manifest_digest": data["manifest_digest"]},
            )
            task["gate1_candidate_ref"] = data["candidate_ref"]
            task["gate1_manifest_digest"] = data["manifest_digest"]
            return
        if event_type == "task_completed":
            data = _require_fields(
                data,
                {
                    "terminal_outcome",
                    "run_ref",
                    "provider_evidence_ref",
                },
            )
            if any(item["state"] != "terminal" for item in task["attempts"]):
                _error("workflow_attempt_not_terminal")
            latest = task["attempts"][-1]
            if data["terminal_outcome"] != latest["terminal_outcome"]:
                _error("workflow_binding_conflict")
            if data["terminal_outcome"] == "completed":
                self._validate_completed_attempt(
                    task,
                    latest,
                    data["run_ref"],
                    data["provider_evidence_ref"],
                    task_terminal=True,
                )
            if data["terminal_outcome"] != "completed" and (
                data["run_ref"] is not None
                or data["provider_evidence_ref"] is not None
            ):
                _error("workflow_journal_corrupt")
            self._transition_task(task, "terminal")
            task["terminal_outcome"] = data["terminal_outcome"]
            return

        attempt_ref = record["attempt_ref"]
        if attempt_ref is None:
            _error("workflow_journal_corrupt")
        attempt = self._attempt(task, attempt_ref)
        if event_type == "payload_tombstone_observed":
            if self._expiry_can_terminalize(task, attempt):
                _error("workflow_expiry_requires_terminal")
            self._record_payload_tombstone(
                projection,
                task,
                attempt,
                record,
                data,
            )
            return
        if attempt["state"] == "terminal":
            _error("workflow_terminal_immutable")

        if event_type == "submission_observed":
            data = _require_fields(data, {"attempt_ref", "command_ref"})
            self._validate_attempt_ref(data, attempt_ref)
            if not _safe_ref(data["command_ref"], "command:"):
                _error("workflow_journal_corrupt")
            if attempt["state"] not in ("planned", "reconciling") or attempt[
                "submission_command_ref"
            ] is not None:
                _error("workflow_binding_conflict")
            if task["state"] in ("ready", "running") and (
                attempt["plan_version"] != task["plan_version"]
                or attempt["plan_digest"] != task["plan_digest"]
                or attempt["plan_source_ref"] != task["plan_source_ref"]
            ):
                _error("workflow_plan_conflict")
            self._bind_global(
                projection,
                "command_refs",
                data["command_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "role": "submission",
                },
            )
            attempt["submission_command_ref"] = data["command_ref"]
            return
        if event_type == "run_observed":
            data = _require_fields(
                data, {"attempt_ref", "command_ref", "run_ref"}
            )
            self._validate_attempt_ref(data, attempt_ref)
            if not _safe_ref(data["command_ref"], "command:") or not _safe_ref(
                data["run_ref"], "run:"
            ):
                _error("workflow_journal_corrupt")
            if attempt["submission_command_ref"] != data["command_ref"]:
                _error("workflow_binding_conflict")
            if attempt["run_ref"] is not None:
                _error("workflow_binding_conflict")
            if attempt["state"] not in ("planned", "reconciling"):
                _error("workflow_invalid_transition")
            self._require_global_binding(
                projection,
                "command_refs",
                data["command_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "role": "submission",
                },
            )
            self._bind_global(
                projection,
                "run_refs",
                data["run_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "command_ref": data["command_ref"],
                },
            )
            self._transition_attempt(attempt, "running")
            attempt["run_ref"] = data["run_ref"]
            if task["state"] == "ready":
                self._transition_task(task, "running")
            return
        if event_type == "provider_evidence_observed":
            data = _require_fields(
                data,
                {"attempt_ref", "run_ref", "provider_evidence_ref"},
            )
            self._validate_run_binding(attempt, data, attempt_ref)
            if not _safe_ref(data["provider_evidence_ref"], "provider-evidence:"):
                _error("workflow_journal_corrupt")
            if data["provider_evidence_ref"] in attempt["provider_evidence_refs"]:
                _error("workflow_binding_conflict")
            self._require_global_binding(
                projection,
                "run_refs",
                data["run_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "command_ref": attempt["submission_command_ref"],
                },
            )
            self._bind_global(
                projection,
                "provider_evidence_refs",
                data["provider_evidence_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "run_ref": data["run_ref"],
                },
            )
            attempt["provider_evidence_refs"].append(data["provider_evidence_ref"])
            return
        if event_type == "gate3_observed":
            data = _require_fields(
                data,
                {
                    "attempt_ref",
                    "run_ref",
                    "gate_ref",
                    "candidate_ref",
                    "manifest_digest",
                    "final_receipt_ref",
                    "base_commit",
                },
            )
            self._validate_run_binding(attempt, data, attempt_ref)
            if (
                attempt["plan_digest"] is None
                or attempt["domain_gate_ref"] != data["gate_ref"]
                or attempt["domain_gate_outcome"] != "passed"
                or task["gate1_candidate_ref"] != data["candidate_ref"]
                or task["gate1_manifest_digest"] != data["manifest_digest"]
                or not _safe_ref(data["final_receipt_ref"], "result:")
                or data["final_receipt_ref"] not in attempt["result_refs"]
                or type(data["base_commit"]) is not str
                or re.fullmatch(r"[0-9a-f]{40}", data["base_commit"]) is None
            ):
                _error("workflow_journal_corrupt")
            if data["gate_ref"] in task["gate3_refs"]:
                _error("workflow_binding_conflict")
            self._require_global_binding(
                projection,
                "gate_refs",
                data["gate_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "role": "domain",
                },
            )
            self._require_global_binding(
                projection,
                "result_refs",
                data["final_receipt_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "run_ref": data["run_ref"],
                },
            )
            self._require_global_binding(
                projection,
                "candidate_refs",
                data["candidate_ref"],
                {"manifest_digest": data["manifest_digest"]},
            )
            attempt["gate3_refs"].append(data["gate_ref"])
            attempt["gate3_entries"].append(
                {
                    "run_ref": data["run_ref"],
                    "gate_ref": data["gate_ref"],
                    "candidate_ref": data["candidate_ref"],
                    "manifest_digest": data["manifest_digest"],
                    "final_receipt_ref": data["final_receipt_ref"],
                    "base_commit": data["base_commit"],
                }
            )
            task["gate3_refs"].append(data["gate_ref"])
            return
        if event_type == "result_linked":
            data = _require_fields(
                data, {"attempt_ref", "run_ref", "result_ref"}
            )
            self._validate_run_binding(attempt, data, attempt_ref)
            if attempt["plan_digest"] is None:
                _error("workflow_plan_conflict")
            if not _safe_ref(data["result_ref"], "result:"):
                _error("workflow_journal_corrupt")
            if data["result_ref"] in task["result_refs"]:
                _error("workflow_binding_conflict")
            self._require_global_binding(
                projection,
                "run_refs",
                data["run_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "command_ref": attempt["submission_command_ref"],
                },
            )
            self._bind_global(
                projection,
                "result_refs",
                data["result_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "run_ref": data["run_ref"],
                },
            )
            attempt["result_refs"].append(data["result_ref"])
            task["result_refs"].append(data["result_ref"])
            return
        if event_type == "domain_gate_entered":
            data = _require_fields(data, {"attempt_ref", "gate_ref"})
            self._validate_attempt_ref(data, attempt_ref)
            if not _safe_ref(data["gate_ref"], "gate:"):
                _error("workflow_journal_corrupt")
            if attempt["state"] != "running" or task["state"] != "running":
                _error("workflow_invalid_transition")
            if attempt["domain_gate_ref"] is not None:
                _error("workflow_binding_conflict")
            self._bind_global(
                projection,
                "gate_refs",
                data["gate_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "role": "domain",
                },
            )
            attempt["domain_gate_ref"] = data["gate_ref"]
            attempt["domain_gate_outcome"] = "pending"
            self._transition_task(task, "awaiting_domain_gate")
            return
        if event_type == "domain_gate_resolved":
            data = _require_fields(data, {"attempt_ref", "gate_ref", "outcome"})
            self._validate_attempt_ref(data, attempt_ref)
            if attempt["domain_gate_ref"] != data["gate_ref"]:
                _error("workflow_binding_conflict")
            if task["state"] != "awaiting_domain_gate" or data["outcome"] not in (
                "passed",
                "rejected",
            ):
                _error("workflow_invalid_transition")
            if data["outcome"] == "passed":
                self._transition_task(task, "running")
                attempt["domain_gate_outcome"] = "passed"
            else:
                self._transition_attempt(attempt, "terminal")
                attempt["terminal_outcome"] = "domain_gate_rejected"
                self._transition_task(task, "terminal")
                task["terminal_outcome"] = "domain_gate_rejected"
                attempt["domain_gate_outcome"] = "rejected"
            return
        if event_type == "reconcile_started":
            data = _require_fields(data, {"attempt_ref", "reason_code"})
            self._validate_attempt_ref(data, attempt_ref)
            if data["reason_code"] not in (
                "submission_outcome_unknown",
                "run_outcome_unknown",
                "stop_outcome_unknown",
                "authority_recovery",
            ):
                _error("workflow_journal_corrupt")
            if data["reason_code"] == "submission_outcome_unknown" and (
                attempt["state"] != "planned"
                or attempt["submission_command_ref"] is not None
            ):
                _error("workflow_binding_conflict")
            if data["reason_code"] == "run_outcome_unknown" and (
                attempt["submission_command_ref"] is None
                or attempt["run_ref"] is not None
            ):
                _error("workflow_binding_conflict")
            if data["reason_code"] == "stop_outcome_unknown" and (
                attempt["stop_command_ref"] is None
                or attempt["state"] != "stop_requested"
            ):
                _error("workflow_binding_conflict")
            if data["reason_code"] == "authority_recovery" and not any(
                (
                    attempt["submission_command_ref"],
                    attempt["run_ref"],
                    attempt["stop_command_ref"],
                )
            ):
                _error("workflow_binding_conflict")
            self._transition_attempt(attempt, "reconciling")
            attempt["reconcile_reason"] = data["reason_code"]
            return
        if event_type == "reconcile_resolved":
            data = _require_fields(
                data,
                {
                    "attempt_ref",
                    "resolved_state",
                    "observation_digest",
                    "terminal_outcome",
                },
            )
            self._validate_attempt_ref(data, attempt_ref)
            if attempt["state"] != "reconciling" or data["resolved_state"] not in (
                "running",
                "terminal",
            ):
                _error("workflow_invalid_transition")
            if not _safe_digest(data["observation_digest"]):
                _error("workflow_journal_corrupt")
            if data["resolved_state"] == "running" and attempt["run_ref"] is None:
                _error("workflow_binding_conflict")
            self._transition_attempt(attempt, data["resolved_state"])
            attempt["reconcile_reason"] = None
            if data["resolved_state"] == "terminal":
                if data["terminal_outcome"] not in ("failed", "cancelled"):
                    _error("workflow_invalid_transition")
                attempt["terminal_outcome"] = data["terminal_outcome"]
                attempt["terminal_observation_digest"] = data[
                    "observation_digest"
                ]
            elif data["terminal_outcome"] is not None:
                _error("workflow_journal_corrupt")
            return
        if event_type == "stop_requested":
            data = _require_fields(
                data, {"attempt_ref", "run_ref", "stop_command_ref"}
            )
            self._validate_attempt_ref(data, attempt_ref)
            if attempt["run_ref"] != data["run_ref"] or not _safe_ref(
                data["stop_command_ref"], "command:"
            ):
                _error("workflow_binding_conflict")
            if attempt["stop_command_ref"] is not None:
                _error("workflow_binding_conflict")
            self._require_global_binding(
                projection,
                "run_refs",
                data["run_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "command_ref": attempt["submission_command_ref"],
                },
            )
            self._bind_global(
                projection,
                "command_refs",
                data["stop_command_ref"],
                {
                    "task_ref": task["task_ref"],
                    "attempt_ref": attempt_ref,
                    "role": "stop",
                },
            )
            self._transition_attempt(attempt, "stop_requested")
            attempt["stop_command_ref"] = data["stop_command_ref"]
            attempt["stop_outcome"] = "requested"
            return
        if event_type == "stop_observed":
            data = _require_fields(
                data,
                {
                    "attempt_ref",
                    "stop_command_ref",
                    "outcome",
                    "observation_digest",
                    "actual_terminal_outcome",
                },
            )
            self._validate_attempt_ref(data, attempt_ref)
            if (
                attempt["stop_command_ref"] != data["stop_command_ref"]
                or not _safe_digest(data["observation_digest"])
            ):
                _error("workflow_binding_conflict")
            if data["outcome"] == "outcome_unknown":
                if attempt["state"] == "stop_requested":
                    self._transition_attempt(attempt, "reconciling")
                elif attempt["state"] != "reconciling":
                    _error("workflow_invalid_transition")
                attempt["reconcile_reason"] = "stop_outcome_unknown"
            elif data["outcome"] in ("confirmed", "already_terminal"):
                actual = data["actual_terminal_outcome"]
                if data["outcome"] == "confirmed" and actual != "stopped":
                    _error("workflow_binding_conflict")
                if actual not in ("completed", "failed", "cancelled", "stopped"):
                    _error("workflow_journal_corrupt")
                if actual == "completed":
                    provider_evidence_ref = (
                        attempt["provider_evidence_refs"][-1]
                        if attempt["provider_evidence_refs"]
                        else None
                    )
                    self._validate_completed_attempt(
                        task,
                        attempt,
                        attempt["run_ref"],
                        provider_evidence_ref,
                        task_terminal=False,
                    )
                self._transition_attempt(attempt, "terminal")
                attempt["terminal_outcome"] = actual
            else:
                _error("workflow_journal_corrupt")
            attempt["stop_outcome"] = data["outcome"]
            attempt["stop_observation_digest"] = data["observation_digest"]
            return
        if event_type == "attempt_completed":
            data = _require_fields(
                data,
                {
                    "attempt_ref",
                    "terminal_outcome",
                    "run_ref",
                    "provider_evidence_ref",
                },
            )
            self._validate_attempt_ref(data, attempt_ref)
            if (
                data["terminal_outcome"] != "completed"
                or task["state"] == "awaiting_domain_gate"
            ):
                _error("workflow_binding_conflict")
            self._validate_completed_attempt(
                task,
                attempt,
                data["run_ref"],
                data["provider_evidence_ref"],
                task_terminal=False,
            )
            self._transition_attempt(attempt, "terminal")
            attempt["terminal_outcome"] = data["terminal_outcome"]
            return
        if event_type == "intent_expired":
            if not self._expiry_can_terminalize(task, attempt):
                _error("workflow_expiry_requires_reconcile")
            self._record_payload_tombstone(
                projection,
                task,
                attempt,
                record,
                data,
            )
            self._transition_attempt(attempt, "terminal")
            attempt["terminal_outcome"] = "intent_expired"
            self._transition_task(task, "terminal")
            task["terminal_outcome"] = "intent_expired"
            return
        _error("workflow_unknown_event")

    def _new_attempt(
        self, data: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "attempt_ref": data["attempt_ref"],
            "attempt_number": data["attempt_number"],
            "state": "planned",
            "payload_ref": data["payload_ref"],
            "payload_digest": data["payload_digest"],
            "intent_expires_at": data["intent_expires_at"],
            "creation_operation_id": record["operation_id"],
            "creation_operation_digest": record["operation_digest"],
            "creation_event_id": record["event_id"],
            "payload_tombstone_event_ref": None,
            "payload_tombstone_digest": None,
            "payload_tombstone_operation_id": None,
            "payload_tombstone_operation_digest": None,
            "payload_tombstone_workflow_event_id": None,
            "plan_version": data.get("plan_version"),
            "plan_digest": data.get("plan_digest"),
            "plan_source_ref": data.get("plan_source_ref"),
            "submission_command_ref": None,
            "run_ref": None,
            "provider_evidence_refs": [],
            "gate3_refs": [],
            "gate3_entries": [],
            "result_refs": [],
            "domain_gate_ref": None,
            "domain_gate_outcome": None,
            "stop_command_ref": None,
            "stop_outcome": None,
            "stop_observation_digest": None,
            "reconcile_reason": None,
            "terminal_observation_digest": None,
            "terminal_outcome": None,
        }

    @staticmethod
    def _expiry_can_terminalize(
        task: dict[str, Any], attempt: dict[str, Any]
    ) -> bool:
        return (
            attempt is task["attempts"][-1]
            and attempt["state"] == "planned"
            and attempt["submission_command_ref"] is None
            and attempt["run_ref"] is None
            and attempt["stop_command_ref"] is None
        )

    def _record_payload_tombstone(
        self,
        projection: dict[str, Any],
        task: dict[str, Any],
        attempt: dict[str, Any],
        record: dict[str, Any],
        data: Any,
    ) -> None:
        data = _require_fields(
            data,
            {
                "attempt_ref",
                "payload_ref",
                "tombstone_event_ref",
                "tombstone_digest",
            },
        )
        self._validate_attempt_ref(data, attempt["attempt_ref"])
        if attempt["payload_ref"] != data["payload_ref"]:
            _error("workflow_binding_conflict")
        if not _safe_event_ref(data["tombstone_event_ref"]) or not _safe_digest(
            data["tombstone_digest"]
        ):
            _error("workflow_journal_corrupt")
        if _parse_time(record["occurred_at"]) < _parse_time(
            attempt["intent_expires_at"]
        ):
            _error("workflow_intent_not_expired")

        self._bind_global(
            projection,
            "tombstone_event_refs",
            data["tombstone_event_ref"],
            {
                "attempt_ref": attempt["attempt_ref"],
                "payload_ref": data["payload_ref"],
                "tombstone_digest": data["tombstone_digest"],
            },
        )
        observation = {
            "owner_user_id": self.owner_user_id,
            "workspace_ref": task["workspace_ref"],
            "managed_session_ref": task["managed_session_ref"],
            "task_ref": task["task_ref"],
            "attempt_ref": attempt["attempt_ref"],
            "payload_ref": data["payload_ref"],
            "tombstone_event_ref": data["tombstone_event_ref"],
            "tombstone_digest": data["tombstone_digest"],
            "operation_id": record["operation_id"],
            "operation_digest": record["operation_digest"],
            "workflow_event_id": record["event_id"],
            "workflow_event_type": record["event_type"],
        }
        self._bind_global(
            projection,
            "payload_tombstone_observations",
            attempt["attempt_ref"],
            observation,
        )
        if any(
            attempt[field] is not None
            for field in (
                "payload_tombstone_event_ref",
                "payload_tombstone_digest",
                "payload_tombstone_operation_id",
                "payload_tombstone_operation_digest",
                "payload_tombstone_workflow_event_id",
            )
        ):
            _error("workflow_binding_conflict")
        attempt["payload_tombstone_event_ref"] = data[
            "tombstone_event_ref"
        ]
        attempt["payload_tombstone_digest"] = data["tombstone_digest"]
        attempt["payload_tombstone_operation_id"] = record["operation_id"]
        attempt["payload_tombstone_operation_digest"] = record[
            "operation_digest"
        ]
        attempt["payload_tombstone_workflow_event_id"] = record["event_id"]

    def _validate_attempt_creation(
        self,
        data: dict[str, Any],
        record_attempt_ref: Optional[str],
        expected_number: int,
    ) -> None:
        if (
            not _safe_ref(data["attempt_ref"], "attempt:")
            or data["attempt_ref"] != record_attempt_ref
            or type(data["attempt_number"]) is not int
            or data["attempt_number"] != expected_number
            or not _safe_ref(data["payload_ref"], "payload:sha256:")
            or not _safe_digest(data["payload_digest"])
            or data["payload_ref"] != "payload:sha256:" + data["payload_digest"]
        ):
            _error("workflow_journal_corrupt")
        try:
            normalized = normalize_timestamp(
                data["intent_expires_at"], "intent_expires_at"
            )
        except WorkflowContractError as exc:
            raise WorkflowAuthorityError("workflow_journal_corrupt") from exc
        if normalized != data["intent_expires_at"]:
            _error("workflow_journal_corrupt")
        plan_fields = ("plan_version", "plan_digest", "plan_source_ref")
        present = [field in data for field in plan_fields]
        if any(present) and not all(present):
            _error("workflow_journal_corrupt")
        if all(present) and (
            type(data["plan_version"]) is not int
            or data["plan_version"] < 1
            or not _safe_digest(data["plan_digest"])
            or not _safe_ref(data["plan_source_ref"], "run:")
        ):
            _error("workflow_journal_corrupt")

    def _validate_plan_binding(
        self, task: dict[str, Any], data: Any
    ) -> None:
        data = _require_fields(data, {"plan_version", "plan_digest"})
        if (
            data["plan_version"] != task["plan_version"]
            or data["plan_digest"] != task["plan_digest"]
        ):
            _error("workflow_plan_conflict")

    def _validate_attempt_ref(
        self, data: dict[str, Any], attempt_ref: str
    ) -> None:
        if data["attempt_ref"] != attempt_ref:
            _error("workflow_binding_conflict")

    def _validate_run_binding(
        self,
        attempt: dict[str, Any],
        data: dict[str, Any],
        attempt_ref: str,
    ) -> None:
        self._validate_attempt_ref(data, attempt_ref)
        if attempt["run_ref"] != data["run_ref"]:
            _error("workflow_binding_conflict")

    def _validate_terminal_value(self, value: Any) -> None:
        if value not in (
            "completed",
            "failed",
            "cancelled",
            "stopped",
            "domain_gate_rejected",
            "intent_expired",
        ):
            _error("workflow_journal_corrupt")

    def _payload_index_binding(
        self,
        *,
        record: dict[str, Any],
        workspace_ref: str,
        managed_session_ref: str,
    ) -> dict[str, Any]:
        attempt_ref = record["attempt_ref"]
        if attempt_ref is None:
            _error("workflow_journal_corrupt")
        return {
            "owner_user_id": self.owner_user_id,
            "workspace_ref": workspace_ref,
            "managed_session_ref": managed_session_ref,
            "task_ref": record["task_ref"],
            "attempt_ref": attempt_ref,
            "creation_operation_id": record["operation_id"],
            "creation_operation_digest": record["operation_digest"],
            "creation_event_id": record["event_id"],
        }

    def _bind_global(
        self,
        projection: dict[str, Any],
        namespace: str,
        external_ref: str,
        binding: dict[str, Any],
    ) -> None:
        indexes = projection.get("bindings")
        if type(indexes) is not dict or namespace not in (
            "command_refs",
            "run_refs",
            "provider_evidence_refs",
            "result_refs",
            "gate_refs",
            "tombstone_event_refs",
            "payload_tombstone_observations",
            "candidate_refs",
            "payload_refs",
        ):
            _error("workflow_journal_corrupt")
        index = indexes.get(namespace)
        if type(index) is not dict:
            _error("workflow_journal_corrupt")
        existing = index.get(external_ref)
        if existing is None:
            index[external_ref] = _copy_json(binding)
        elif existing != binding:
            _error("workflow_binding_conflict")

    def _require_global_binding(
        self,
        projection: dict[str, Any],
        namespace: str,
        external_ref: str,
        binding: dict[str, Any],
    ) -> None:
        indexes = projection.get("bindings")
        if type(indexes) is not dict:
            _error("workflow_journal_corrupt")
        index = indexes.get(namespace)
        if type(index) is not dict or index.get(external_ref) != binding:
            _error("workflow_binding_conflict")

    def _validate_completed_attempt(
        self,
        task: dict[str, Any],
        attempt: dict[str, Any],
        run_ref: Any,
        provider_evidence_ref: Any,
        *,
        task_terminal: bool,
    ) -> None:
        if (
            attempt["run_ref"] != run_ref
            or provider_evidence_ref not in attempt["provider_evidence_refs"]
        ):
            _error("workflow_binding_conflict")

        is_research_attempt = attempt["plan_digest"] is not None
        if is_research_attempt:
            if (
                attempt["plan_version"] != task["plan_version"]
                or attempt["plan_digest"] != task["plan_digest"]
                or attempt["plan_source_ref"] != task["plan_source_ref"]
                or not attempt["result_refs"]
            ):
                _error("workflow_plan_conflict")
            if task["requires_formula_confirmation"]:
                if (
                    task["gate1_ref"] is None
                    or task["gate1_source_digest"] is None
                    or task["gate1_note_digest"] is None
                    or task["gate1_candidate_ref"] is None
                    or task["gate1_manifest_digest"] is None
                    or attempt["domain_gate_ref"] is None
                    or attempt["domain_gate_outcome"] != "passed"
                    or len(attempt["gate3_entries"]) != 1
                ):
                    _error("workflow_binding_conflict")
                gate3 = attempt["gate3_entries"][0]
                if (
                    gate3["run_ref"] != run_ref
                    or gate3["gate_ref"] != attempt["domain_gate_ref"]
                    or gate3["candidate_ref"] != task["gate1_candidate_ref"]
                    or gate3["manifest_digest"] != task["gate1_manifest_digest"]
                    or gate3["final_receipt_ref"] not in attempt["result_refs"]
                ):
                    _error("workflow_binding_conflict")

        if task_terminal and (
            not is_research_attempt
            or task["plan_confirmation_note_digest"] is None
            or task["plan_version"] is None
            or task["plan_digest"] is None
            or task["plan_source_ref"] is None
        ):
            _error("workflow_plan_conflict")

    @staticmethod
    def _is_generated_ref(value: Any, prefix: str) -> bool:
        return (
            type(value) is str
            and value.startswith(prefix)
            and _HEX64_RE.fullmatch(value[len(prefix) :]) is not None
        )

    def _consume_expiry_tombstone(
        self, evidence: ExpiryTombstoneEvidence
    ) -> WorkflowReceipt:
        operation_id = self._expiry_operation_id(evidence)
        retryable_races = {
            "workflow_stale_version",
            "workflow_terminal_immutable",
            "workflow_idempotency_conflict",
            "workflow_expiry_requires_reconcile",
            "workflow_expiry_requires_terminal",
        }
        for _attempt_number in range(4):
            context = self._expiry_context(evidence, operation_id)
            receipt = context.get("receipt")
            if receipt is not None:
                return receipt
            command_type = (
                _ExpireIntent
                if context["terminalize"]
                else _ObservePayloadTombstone
            )
            command = command_type(
                operation_id=operation_id,
                task_ref=context["task_ref"],
                expected_version=context["task_version"],
                attempt_ref=evidence.attempt_ref,
                payload_ref=evidence.payload_ref,
                tombstone_event_ref=evidence.tombstone_event_ref,
                tombstone_digest=evidence.tombstone_digest,
            )
            try:
                return self._apply_expiry_mutation(command)
            except WorkflowAuthorityError as exc:
                if exc.code not in retryable_races:
                    raise
        _error("workflow_stale_version")

    def _expiry_context(
        self,
        evidence: ExpiryTombstoneEvidence,
        operation_id: str,
    ) -> dict[str, Any]:
        if not self._authority_root_exists():
            _error("workflow_attempt_not_found")
        with self._locked(create=False) as root_fd:
            projection = self._replay(self._load_records(root_fd))
            self._repair_disposable_projection(root_fd, projection)
            matches = [
                (task, attempt)
                for task in projection["tasks"].values()
                for attempt in task["attempts"]
                if attempt["attempt_ref"] == evidence.attempt_ref
            ]
            if not matches:
                _error("workflow_attempt_not_found")
            if len(matches) != 1:
                _error("workflow_journal_corrupt")
            task, attempt = matches[0]
            if (
                evidence.owner_user_id != self.owner_user_id
                or evidence.workspace_ref != task["workspace_ref"]
                or evidence.managed_session_ref
                != task["managed_session_ref"]
                or evidence.payload_ref != attempt["payload_ref"]
            ):
                _error("workflow_binding_conflict")

            expected_payload_binding = {
                "owner_user_id": self.owner_user_id,
                "workspace_ref": task["workspace_ref"],
                "managed_session_ref": task["managed_session_ref"],
                "task_ref": task["task_ref"],
                "attempt_ref": attempt["attempt_ref"],
                "creation_operation_id": attempt["creation_operation_id"],
                "creation_operation_digest": attempt[
                    "creation_operation_digest"
                ],
                "creation_event_id": attempt["creation_event_id"],
            }
            if (
                projection["bindings"]["payload_refs"].get(
                    evidence.payload_ref
                )
                != expected_payload_binding
            ):
                _error("workflow_journal_corrupt")

            observation = projection["bindings"][
                "payload_tombstone_observations"
            ].get(evidence.attempt_ref)
            if observation is not None:
                expected_evidence = {
                    "owner_user_id": evidence.owner_user_id,
                    "workspace_ref": evidence.workspace_ref,
                    "managed_session_ref": evidence.managed_session_ref,
                    "attempt_ref": evidence.attempt_ref,
                    "payload_ref": evidence.payload_ref,
                    "tombstone_event_ref": evidence.tombstone_event_ref,
                    "tombstone_digest": evidence.tombstone_digest,
                }
                if any(
                    observation[field] != value
                    for field, value in expected_evidence.items()
                ):
                    _error("workflow_binding_conflict")
                return {
                    "receipt": self._expiry_receipt_from_projection(
                        projection,
                        task,
                        attempt,
                        observation,
                    )
                }

            tombstone_fields = (
                "payload_tombstone_event_ref",
                "payload_tombstone_digest",
                "payload_tombstone_operation_id",
                "payload_tombstone_operation_digest",
                "payload_tombstone_workflow_event_id",
            )
            if any(attempt[field] is not None for field in tombstone_fields):
                _error("workflow_journal_corrupt")
            if operation_id in projection["operations"]:
                _error("workflow_binding_conflict")
            return {
                "receipt": None,
                "task_ref": task["task_ref"],
                "task_version": task["version"],
                "terminalize": self._expiry_can_terminalize(task, attempt),
            }

    def _expiry_receipt_from_projection(
        self,
        projection: dict[str, Any],
        task: dict[str, Any],
        attempt: dict[str, Any],
        observation: dict[str, Any],
    ) -> WorkflowReceipt:
        operation = projection["operations"].get(observation["operation_id"])
        if operation is None:
            _error("workflow_journal_corrupt")
        document = operation["receipt"]
        if (
            operation["operation_digest"] != observation["operation_digest"]
            or document["event_id"] != observation["workflow_event_id"]
            or document["task_ref"] != task["task_ref"]
            or document["attempt_ref"] != attempt["attempt_ref"]
            or document["task_version"] < 2
            or attempt["payload_tombstone_event_ref"]
            != observation["tombstone_event_ref"]
            or attempt["payload_tombstone_digest"]
            != observation["tombstone_digest"]
            or attempt["payload_tombstone_operation_id"]
            != observation["operation_id"]
            or attempt["payload_tombstone_operation_digest"]
            != observation["operation_digest"]
            or attempt["payload_tombstone_workflow_event_id"]
            != observation["workflow_event_id"]
        ):
            _error("workflow_journal_corrupt")
        command_types = {
            "intent_expired": _ExpireIntent,
            "payload_tombstone_observed": _ObservePayloadTombstone,
        }
        command_type = command_types.get(observation["workflow_event_type"])
        if command_type is None:
            _error("workflow_journal_corrupt")
        command = command_type(
            operation_id=observation["operation_id"],
            task_ref=task["task_ref"],
            expected_version=document["task_version"] - 1,
            attempt_ref=attempt["attempt_ref"],
            payload_ref=attempt["payload_ref"],
            tombstone_event_ref=observation["tombstone_event_ref"],
            tombstone_digest=observation["tombstone_digest"],
        )
        if (
            _canonical_expiry_command_digest(command)
            != operation["operation_digest"]
        ):
            _error("workflow_journal_corrupt")
        return self._receipt_from_document(document, replayed=True)

    def _expiry_operation_id(
        self, evidence: ExpiryTombstoneEvidence
    ) -> str:
        return "payload-tombstone-" + _sha256(
            _canonical_bytes(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "owner_user_id": self.owner_user_id,
                    "attempt_ref": evidence.attempt_ref,
                    "payload_ref": evidence.payload_ref,
                    "tombstone_event_ref": evidence.tombstone_event_ref,
                    "tombstone_digest": evidence.tombstone_digest,
                }
            )
        )

    def _attempt(
        self, task: dict[str, Any], attempt_ref: str
    ) -> dict[str, Any]:
        matching = [
            attempt
            for attempt in task["attempts"]
            if attempt["attempt_ref"] == attempt_ref
        ]
        if len(matching) != 1:
            _error("workflow_attempt_not_found")
        return matching[0]

    def _transition_task(self, task: dict[str, Any], destination: str) -> None:
        self._transition("task", task, destination)

    def _transition_attempt(
        self, attempt: dict[str, Any], destination: str
    ) -> None:
        self._transition("attempt", attempt, destination)

    def _transition(
        self, kind: str, record: dict[str, Any], destination: str
    ) -> None:
        try:
            validate_transition(kind, record["state"], destination)
        except WorkspaceStateError as exc:
            raise WorkflowAuthorityError("workflow_invalid_transition") from exc
        record["state"] = destination

    def _append_record(self, root_fd: int, record: dict[str, Any]) -> None:
        content = _canonical_bytes(record) + b"\n"
        if len(content) > _MAX_RECORD_BYTES:
            _error("workflow_record_quota")
        if not self._entry_exists(root_fd, _JOURNAL_NAME):
            self._write_new_entry(root_fd, _JOURNAL_NAME, b"")
        flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(_JOURNAL_NAME, flags, dir_fd=root_fd)
            try:
                self._assert_secure_file(
                    descriptor, "workflow journal", 0o600
                )
                self._assert_path_identity(root_fd, _JOURNAL_NAME, descriptor)
                current_size = os.fstat(descriptor).st_size
                if current_size + len(content) > _MAX_JOURNAL_BYTES:
                    _error("workflow_journal_quota")
                view = memoryview(content)
                try:
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise OSError("journal append made no progress")
                        view = view[written:]
                except OSError as write_error:
                    try:
                        os.ftruncate(descriptor, current_size)
                        os.fsync(descriptor)
                    except OSError as rollback_error:
                        raise WorkflowAuthorityError(
                            "workflow_durability_unknown"
                        ) from rollback_error
                    raise write_error
                try:
                    os.fsync(descriptor)
                except OSError as exc:
                    raise WorkflowAuthorityError(
                        "workflow_durability_unknown"
                    ) from exc
                self._assert_path_identity(root_fd, _JOURNAL_NAME, descriptor)
            finally:
                os.close(descriptor)
        except WorkflowAuthorityError:
            raise
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc

    @staticmethod
    def _projection_bytes(projection: dict[str, Any]) -> bytes:
        content = _canonical_bytes(projection)
        if len(content) > _MAX_PROJECTION_BYTES:
            _error("workflow_projection_quota")
        return content

    def _write_projection(
        self, root_fd: int, projection: dict[str, Any]
    ) -> None:
        self._publish_entry(
            root_fd,
            _PROJECTION_NAME,
            self._projection_bytes(projection),
            replace=True,
        )

    def _repair_disposable_projection(
        self, root_fd: int, projection: dict[str, Any]
    ) -> None:
        expected = self._projection_bytes(projection)
        try:
            if self._entry_exists(root_fd, _PROJECTION_NAME):
                if self._read_secure_entry(
                    root_fd,
                    _PROJECTION_NAME,
                    _MAX_PROJECTION_BYTES,
                    "workflow projection",
                ) == expected:
                    return
            self._publish_entry(
                root_fd, _PROJECTION_NAME, expected, replace=True
            )
        except WorkflowAuthorityError:
            raise
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc

    def _write_new_entry(
        self, root_fd: int, name: str, content: bytes
    ) -> None:
        self._publish_entry(root_fd, name, content, replace=False)

    def _publish_entry(
        self,
        root_fd: int,
        name: str,
        content: bytes,
        *,
        replace: bool,
    ) -> None:
        if self._entry_exists(root_fd, name):
            if not replace:
                _error("workflow_restore_conflict")
            existing = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
            try:
                self._assert_secure_file(existing, "workflow entry", 0o600)
                self._assert_path_identity(root_fd, name, existing)
            finally:
                os.close(existing)
        temporary = ".{}.{}.tmp".format(name, secrets.token_hex(12))
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(temporary, flags, 0o600, dir_fd=root_fd)
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc
        published = False
        try:
            os.fchmod(descriptor, 0o600)
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("workflow entry write made no progress")
                view = view[written:]
            os.fsync(descriptor)
            self._assert_secure_file(descriptor, "workflow temporary", 0o600)
            self._assert_path_identity(root_fd, temporary, descriptor)
            if replace:
                os.replace(
                    temporary,
                    name,
                    src_dir_fd=root_fd,
                    dst_dir_fd=root_fd,
                )
            else:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=root_fd,
                    dst_dir_fd=root_fd,
                    follow_symlinks=False,
                )
                os.unlink(temporary, dir_fd=root_fd)
            published = True
            os.fsync(root_fd)
            final_fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
            try:
                self._assert_secure_file(final_fd, "workflow entry", 0o600)
                self._assert_path_identity(root_fd, name, final_fd)
            finally:
                os.close(final_fd)
        except FileExistsError as exc:
            raise WorkflowAuthorityError("workflow_restore_conflict") from exc
        except WorkflowAuthorityError:
            raise
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc
        finally:
            os.close(descriptor)
            if not published or replace:
                try:
                    os.unlink(temporary, dir_fd=root_fd)
                except FileNotFoundError:
                    pass

    def _receipt_from_document(
        self, document: dict[str, Any], *, replayed: bool
    ) -> WorkflowReceipt:
        return WorkflowReceipt(
            operation_id=document["operation_id"],
            operation_digest=document["operation_digest"],
            event_id=document["event_id"],
            task_ref=document["task_ref"],
            task_version=document["task_version"],
            attempt_ref=document["attempt_ref"],
            replayed=replayed,
        )

    def _snapshot_from_task(self, task: dict[str, Any]) -> WorkflowSnapshot:
        attempts = tuple(
            AttemptSnapshot(
                attempt_ref=attempt["attempt_ref"],
                attempt_number=attempt["attempt_number"],
                state=attempt["state"],
                payload_ref=attempt["payload_ref"],
                payload_digest=attempt["payload_digest"],
                intent_expires_at=attempt["intent_expires_at"],
                payload_tombstone_event_ref=attempt[
                    "payload_tombstone_event_ref"
                ],
                payload_tombstone_digest=attempt[
                    "payload_tombstone_digest"
                ],
                plan_version=attempt["plan_version"],
                plan_digest=attempt["plan_digest"],
                plan_source_ref=attempt["plan_source_ref"],
                submission_command_ref=attempt["submission_command_ref"],
                run_ref=attempt["run_ref"],
                provider_evidence_refs=tuple(attempt["provider_evidence_refs"]),
                gate3_refs=tuple(attempt["gate3_refs"]),
                gate3_bindings=tuple(
                    Gate3Snapshot(**binding)
                    for binding in attempt["gate3_entries"]
                ),
                result_refs=tuple(attempt["result_refs"]),
                domain_gate_ref=attempt["domain_gate_ref"],
                domain_gate_outcome=attempt["domain_gate_outcome"],
                stop_command_ref=attempt["stop_command_ref"],
                stop_outcome=attempt["stop_outcome"],
                stop_observation_digest=attempt[
                    "stop_observation_digest"
                ],
                reconcile_reason=attempt["reconcile_reason"],
                terminal_observation_digest=attempt[
                    "terminal_observation_digest"
                ],
                terminal_outcome=attempt["terminal_outcome"],
            )
            for attempt in task["attempts"]
        )
        return WorkflowSnapshot(
            owner_user_id=self.owner_user_id,
            workspace_ref=task["workspace_ref"],
            managed_session_ref=task["managed_session_ref"],
            task_ref=task["task_ref"],
            version=task["version"],
            state=task["state"],
            plan_version=task["plan_version"],
            plan_digest=task["plan_digest"],
            plan_source_ref=task["plan_source_ref"],
            requires_formula_confirmation=task[
                "requires_formula_confirmation"
            ],
            plan_confirmation_note_digest=task[
                "plan_confirmation_note_digest"
            ],
            gate1_ref=task["gate1_ref"],
            gate1_source_digest=task["gate1_source_digest"],
            gate1_note_digest=task["gate1_note_digest"],
            gate1_candidate_ref=task["gate1_candidate_ref"],
            gate1_manifest_digest=task["gate1_manifest_digest"],
            gate3_refs=tuple(task["gate3_refs"]),
            result_refs=tuple(task["result_refs"]),
            terminal_outcome=task["terminal_outcome"],
            attempts=attempts,
        )

    def _public_event(self, record: dict[str, Any]) -> WorkflowEvent:
        return WorkflowEvent(
            sequence=record["sequence"],
            event_id=record["event_id"],
            operation_id=record["operation_id"],
            operation_digest=record["operation_digest"],
            task_ref=record["task_ref"],
            task_version=record["task_version"],
            event_type=record["event_type"],
            occurred_at=record["occurred_at"],
            data=_copy_json(record["data"]),
        )

    def _audit_document(
        self, projection: dict[str, Any], status_value: str
    ) -> dict[str, Any]:
        bindings = projection["bindings"]
        return {
            "schema_version": _SCHEMA_VERSION,
            "status": status_value,
            "owner_user_id": self.owner_user_id,
            "event_count": projection["last_sequence"],
            "task_count": len(projection["tasks"]),
            "operation_count": len(projection["operations"]),
            "binding_counts": {
                namespace: len(bindings[namespace])
                for namespace in (
                    "command_refs",
                    "run_refs",
                    "provider_evidence_refs",
                    "result_refs",
                    "gate_refs",
                    "tombstone_event_refs",
                    "payload_tombstone_observations",
                    "candidate_refs",
                    "payload_refs",
                )
            },
            "last_record_sha256": projection["last_record_sha256"],
            "projection_sha256": _sha256(self._projection_bytes(projection)),
        }

    def _write_exclusive(self, path: Path, content: bytes) -> None:
        absolute = Path(os.path.abspath(path))
        parent_fd = self._open_backup_directory(absolute.parent)
        temporary = ".{}.{}.tmp".format(
            absolute.name, secrets.token_hex(12)
        )
        descriptor: Optional[int] = None
        published = False
        try:
            if self._entry_exists(parent_fd, absolute.name):
                _error("workflow_backup_conflict")
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_fd,
            )
            os.fchmod(descriptor, 0o600)
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("backup write made no progress")
                view = view[written:]
            os.fsync(descriptor)
            self._assert_secure_file(descriptor, "workflow backup", 0o600)
            self._assert_path_identity(parent_fd, temporary, descriptor)
            os.link(
                temporary,
                absolute.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            os.unlink(temporary, dir_fd=parent_fd)
            published = True
            os.fsync(parent_fd)
            final_fd = os.open(
                absolute.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                self._assert_secure_file(
                    final_fd, "workflow backup", 0o600
                )
                self._assert_path_identity(
                    parent_fd, absolute.name, final_fd
                )
            finally:
                os.close(final_fd)
        except FileExistsError as exc:
            raise WorkflowAuthorityError("workflow_backup_conflict") from exc
        except WorkflowAuthorityError:
            raise
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if not published:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
            os.close(parent_fd)

    def _read_backup(self, path: Path) -> dict[str, Any]:
        absolute = Path(os.path.abspath(path))
        parent_fd = self._open_backup_directory(absolute.parent)
        try:
            raw = self._read_secure_named_file(
                parent_fd,
                absolute.name,
                _MAX_BACKUP_BYTES,
                "workflow_backup_quota",
            )
            document = _strict_loads(raw)
            if _canonical_bytes(document) != raw:
                _error("workflow_backup_corrupt")
        except WorkflowAuthorityError as exc:
            if exc.code == "workflow_journal_corrupt":
                raise WorkflowAuthorityError("workflow_backup_corrupt") from exc
            raise
        except OSError as exc:
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc
        finally:
            os.close(parent_fd)
        expected = {
            "schema_version",
            "kind",
            "owner_user_id",
            "event_count",
            "journal_sha256",
            "projection_sha256",
            "records",
        }
        if type(document) is not dict or set(document) != expected:
            _error("workflow_backup_corrupt")
        if (
            document["schema_version"] != _SCHEMA_VERSION
            or document["kind"] != "workflow_authority_backup"
            or document["owner_user_id"] != self.owner_user_id
            or type(document["records"]) is not list
            or document["event_count"] != len(document["records"])
            or not _safe_digest(document["journal_sha256"])
            or not _safe_digest(document["projection_sha256"])
        ):
            _error("workflow_backup_corrupt")
        return document

    def _open_backup_directory(self, path: Path) -> int:
        absolute = Path(os.path.abspath(path))
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        current_fd = os.open(absolute.anchor or os.sep, flags)
        try:
            for component in absolute.parts[1:]:
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    if getattr(exc, "errno", None) in (
                        errno.ENOTDIR,
                        errno.ELOOP,
                    ):
                        raise WorkflowAuthorityError(
                            "workflow_storage_insecure"
                        ) from exc
                    raise WorkflowAuthorityError(
                        "workflow_backup_destination_invalid"
                    ) from exc
                os.close(current_fd)
                current_fd = next_fd
            metadata = os.fstat(current_fd)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                _error("workflow_storage_insecure")
            return current_fd
        except Exception:
            try:
                os.close(current_fd)
            except OSError:
                pass
            raise

    def _read_secure_named_file(
        self,
        parent_fd: int,
        name: str,
        ceiling: int,
        quota_code: str,
    ) -> bytes:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except FileNotFoundError as exc:
            raise WorkflowAuthorityError("workflow_backup_not_found") from exc
        except OSError as exc:
            if getattr(exc, "errno", None) == errno.ELOOP:
                raise WorkflowAuthorityError("workflow_storage_insecure") from exc
            raise WorkflowAuthorityError("workflow_storage_unavailable") from exc
        try:
            self._assert_secure_file(descriptor, "workflow backup", 0o600)
            self._assert_path_identity(parent_fd, name, descriptor)
            if os.fstat(descriptor).st_size > ceiling:
                _error(quota_code)
            chunks = []
            remaining = ceiling + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if len(content) > ceiling:
                _error(quota_code)
            self._assert_path_identity(parent_fd, name, descriptor)
            return content
        finally:
            os.close(descriptor)


__all__ = ("WorkflowAuthority", "WorkflowAuthorityError")
