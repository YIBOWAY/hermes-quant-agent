from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

import hqa.workflow_authority as workflow_authority_module
from hqa.workflow_authority import WorkflowAuthority, WorkflowAuthorityError
from hqa.workflow_contract import (
    ExpiryTombstoneEvidence,
    ObserveRun,
    ObserveSubmission,
    ProposePlan,
    StartResearch,
)


NOW = "2026-07-19T01:00:00.000000Z"
EXPIRES = "2026-07-20T01:00:00.000000Z"
PAYLOAD = "payload:sha256:" + "a" * 64
PLAN = "b" * 64
WORKSPACE = "workspace:local"
SESSION = "session:managed"


def _authority(root: Path) -> WorkflowAuthority:
    return WorkflowAuthority(root, "owner-local-1", now=lambda: NOW)


def test_backup_restore_replay_preserves_task_event_and_payload_digests(tmp_path) -> None:
    original = _authority(tmp_path / "original")
    receipt = original.apply(
        StartResearch("op-start", WORKSPACE, SESSION, PAYLOAD, EXPIRES)
    )
    receipt = original.apply(
        ObserveSubmission(
            "op-submit",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "command:plan",
        )
    )
    receipt = original.apply(
        ObserveRun(
            "op-run",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "command:plan",
            "run:plan",
        )
    )
    original.apply(
        ProposePlan(
            "op-plan",
            receipt.task_ref,
            receipt.task_version,
            1,
            PLAN,
            "run:plan",
            False,
        )
    )
    backup_path = tmp_path / "workflow-backup.v2.json"

    backup_receipt = original.backup(backup_path)
    restored = _authority(tmp_path / "restored")
    restore_receipt = restored.restore(backup_path)

    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    assert restore_receipt["status"] == "consistent"
    assert backup_receipt["projection_sha256"] == restore_receipt[
        "projection_sha256"
    ]
    assert restored.snapshot(receipt.task_ref) == original.snapshot(receipt.task_ref)
    assert [event.event_id for event in restored.events(receipt.task_ref).events] == [
        event.event_id for event in original.events(receipt.task_ref).events
    ]
    assert restored.snapshot(receipt.task_ref).attempts[0].payload_digest == "a" * 64
    assert restored.reverse_audit()["status"] == "consistent"


def test_backup_restore_replays_legacy_shaped_private_expiry_event(tmp_path) -> None:
    original = _authority(tmp_path / "original-expiry")
    started = original.apply(
        StartResearch("op-start-expiry", WORKSPACE, SESSION, PAYLOAD, EXPIRES)
    )
    assert started.attempt_ref is not None
    evidence = ExpiryTombstoneEvidence(
        owner_user_id="owner-local-1",
        workspace_ref=WORKSPACE,
        managed_session_ref=SESSION,
        attempt_ref=started.attempt_ref,
        payload_ref=PAYLOAD,
        tombstone_event_ref="event:" + "c" * 64,
        tombstone_digest="d" * 64,
    )
    expired = WorkflowAuthority(
        original.root,
        "owner-local-1",
        now=lambda: "2026-07-21T01:00:00.000000Z",
    )
    receipt = expired.consume_expiry_tombstones((evidence,), limit=1).receipts[0]
    legacy_document = {
        "schema_version": 2,
        "kind": "workflow.expire_intent",
        "operation_id": receipt.operation_id,
        "task_ref": receipt.task_ref,
        "expected_version": receipt.task_version - 1,
        "attempt_ref": receipt.attempt_ref,
        "payload_ref": evidence.payload_ref,
        "tombstone_event_ref": evidence.tombstone_event_ref,
        "tombstone_digest": evidence.tombstone_digest,
    }
    expected_digest = hashlib.sha256(
        json.dumps(
            legacy_document,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert receipt.operation_digest == expected_digest

    backup_path = tmp_path / "expiry-backup.v2.json"
    expired.backup(backup_path)
    restored = WorkflowAuthority(
        tmp_path / "restored-expiry",
        "owner-local-1",
        now=lambda: "2026-07-21T01:00:00.000000Z",
    )
    assert restored.restore(backup_path)["status"] == "consistent"
    replay = restored.consume_expiry_tombstones((evidence,), limit=1)

    assert replay.replayed_count == 1
    assert replay.receipts[0].event_id == receipt.event_id
    assert replay.receipts[0].operation_digest == expected_digest
    assert restored.snapshot(started.task_ref).terminal_outcome == "intent_expired"


def test_restore_refuses_nonempty_authority_and_backup_overwrite(tmp_path) -> None:
    original = _authority(tmp_path / "original")
    original.apply(
        StartResearch("op-start", WORKSPACE, SESSION, PAYLOAD, EXPIRES)
    )
    backup_path = tmp_path / "backup.json"
    original.backup(backup_path)

    with pytest.raises(WorkflowAuthorityError) as overwrite:
        original.backup(backup_path)
    assert overwrite.value.code == "workflow_backup_conflict"

    destination = _authority(tmp_path / "destination")
    destination.apply(
        StartResearch("op-existing", WORKSPACE, SESSION, PAYLOAD, EXPIRES)
    )
    with pytest.raises(WorkflowAuthorityError) as conflict:
        destination.restore(backup_path)
    assert conflict.value.code == "workflow_restore_conflict"


def test_backup_hash_or_record_tampering_fails_closed(tmp_path) -> None:
    original = _authority(tmp_path / "original")
    original.apply(
        StartResearch("op-start", WORKSPACE, SESSION, PAYLOAD, EXPIRES)
    )
    backup_path = tmp_path / "backup.json"
    original.backup(backup_path)
    document = json.loads(backup_path.read_text())
    document["records"][0]["data"]["payload_digest"] = "f" * 64
    backup_path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":"))
    )
    os.chmod(backup_path, 0o600)

    restored = _authority(tmp_path / "restored")
    with pytest.raises(WorkflowAuthorityError) as corrupt:
        restored.restore(backup_path)
    assert corrupt.value.code in (
        "workflow_journal_corrupt",
        "workflow_backup_corrupt",
    )
    assert not restored.root.exists()


def test_reverse_audit_detects_disposable_projection_mismatch_then_rebuilds(
    tmp_path,
) -> None:
    authority = _authority(tmp_path / "authority")
    authority.apply(
        StartResearch("op-start", WORKSPACE, SESSION, PAYLOAD, EXPIRES)
    )
    authority.projection_path.write_text("{}")
    os.chmod(authority.projection_path, 0o600)

    assert authority.reverse_audit()["status"] == "projection_mismatch"
    rebuilt = authority.rebuild_projection()
    assert rebuilt["status"] == "consistent"
    assert authority.reverse_audit()["status"] == "consistent"


def test_partial_restore_after_journal_publish_is_idempotently_recoverable(
    tmp_path, monkeypatch
) -> None:
    original = _authority(tmp_path / "original")
    original.apply(
        StartResearch("op-start", WORKSPACE, SESSION, PAYLOAD, EXPIRES)
    )
    backup_path = tmp_path / "backup.json"
    original.backup(backup_path)
    restored = _authority(tmp_path / "restored")
    original_write = restored._write_projection

    def fail_projection(_root_fd, _projection) -> None:
        raise WorkflowAuthorityError("workflow_storage_unavailable")

    monkeypatch.setattr(restored, "_write_projection", fail_projection)
    with pytest.raises(WorkflowAuthorityError):
        restored.restore(backup_path)
    assert restored.journal_path.exists()
    assert not restored.projection_path.exists()

    monkeypatch.setattr(restored, "_write_projection", original_write)
    assert restored.restore(backup_path)["status"] == "consistent"
    assert restored.reverse_audit()["status"] == "consistent"


def test_backup_symlink_and_hardlink_sources_fail_closed(tmp_path) -> None:
    original = _authority(tmp_path / "original")
    original.apply(
        StartResearch("op-start", WORKSPACE, SESSION, PAYLOAD, EXPIRES)
    )
    backup_path = tmp_path / "backup.json"
    original.backup(backup_path)

    symlink = tmp_path / "backup-symlink.json"
    symlink.symlink_to(backup_path)
    with pytest.raises(WorkflowAuthorityError) as symlink_error:
        _authority(tmp_path / "symlink-restore").restore(symlink)
    assert symlink_error.value.code == "workflow_storage_insecure"

    hardlink = tmp_path / "backup-hardlink.json"
    os.link(backup_path, hardlink)
    with pytest.raises(WorkflowAuthorityError) as hardlink_error:
        _authority(tmp_path / "hardlink-restore").restore(backup_path)
    assert hardlink_error.value.code == "workflow_storage_insecure"


def test_projection_quota_bounds_backup_rebuild_and_restore(
    tmp_path, monkeypatch
) -> None:
    original = _authority(tmp_path / "original")
    original.apply(
        StartResearch("op-start", WORKSPACE, SESSION, PAYLOAD, EXPIRES)
    )
    projection_before = original.projection_path.read_bytes()
    backup_path = tmp_path / "bounded-backup.json"
    original.backup(backup_path)

    monkeypatch.setattr(
        workflow_authority_module,
        "_MAX_PROJECTION_BYTES",
        1,
    )
    with pytest.raises(WorkflowAuthorityError) as rebuild_quota:
        original.rebuild_projection()
    assert rebuild_quota.value.code == "workflow_projection_quota"
    assert original.projection_path.read_bytes() == projection_before

    with pytest.raises(WorkflowAuthorityError) as backup_quota:
        original.backup(tmp_path / "must-not-exist.json")
    assert backup_quota.value.code == "workflow_projection_quota"
    assert not (tmp_path / "must-not-exist.json").exists()

    restored = _authority(tmp_path / "restored")
    with pytest.raises(WorkflowAuthorityError) as restore_quota:
        restored.restore(backup_path)
    assert restore_quota.value.code == "workflow_projection_quota"
    assert not restored.root.exists()
