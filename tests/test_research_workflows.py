from __future__ import annotations

import hashlib
import json
import os
import stat

import pytest

from hqa.research_workflows import (
    ResearchWorkflowError,
    ResearchWorkflowStore,
    as_platform_prepared_command,
    transport_binding_digest,
)


NOW = "2026-07-16T01:02:03.000000Z"
OWNER_USER_ID = "00000000-0000-0000-0000-000000000001"


def _request() -> dict:
    return {
        "schema_version": "1.0",
        "platform_session_id": "session-local-1",
        "client_request_id": "request-local-1",
        "command_kind": "research_chat",
        "payload_ttl_days": 30,
        "prompt": "Compare a bounded read-only momentum hypothesis.",
        "provider_policy": {
            "primary": {"provider": "openai-codex", "model": "gpt-5-codex"},
            "fallbacks": [{"provider": "xai", "model": "grok-4.5"}],
        },
        "plan": {
            "schema_version": 1,
            "version": 1,
            "goal": "Compare a read-only momentum hypothesis.",
            "steps": [
                {
                    "step_id": "inspect-existing-results",
                    "kind": "read_only",
                    "description": "Read existing result references only.",
                }
            ],
        },
    }


def test_prepare_round_trip_persists_one_event_and_replays_same_projection(
    tmp_path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)

    receipt = store.prepare(_request())

    assert set(receipt) == {
        "schema_version",
        "workflow_saga_id",
        "owner_user_id",
        "platform_session_id",
        "client_request_id",
        "command_kind",
        "canonical_request_digest",
        "payload_ref",
        "payload_digest",
        "payload_expires_at",
        "provider_policy_digest",
        "task_id",
        "task_version",
        "attempt_id",
        "attempt_number",
        "prepared_event_id",
        "prepared_event_digest",
        "plan_schema_version",
        "plan_version",
        "plan_digest",
        "workflow_preparation_digest",
    }
    assert receipt["schema_version"] == "1.0"
    assert receipt["owner_user_id"] == OWNER_USER_ID
    assert receipt["workflow_saga_id"].startswith("hqs_")
    assert receipt["task_id"].startswith("hqt_")
    assert receipt["attempt_id"].startswith("hqa_")
    assert receipt["prepared_event_id"].startswith("hqe_")
    assert receipt["task_version"] == 1
    assert receipt["attempt_number"] == 1
    assert receipt["payload_expires_at"] == "2026-08-15T01:02:03.000000Z"
    assert receipt["payload_ref"] == (
        f"hqa-payload:sha256:{receipt['payload_digest']}"
    )

    task = store.show(receipt["task_id"])
    assert task["task_id"] == receipt["task_id"]
    assert task["version"] == 1
    assert task["state"] == "awaiting_transport_binding"
    assert task["active_attempt"]["attempt_id"] == receipt["attempt_id"]
    assert task["preparation"] == receipt

    page = store.events(receipt["task_id"])
    assert page["events"][0]["event_id"] == receipt["prepared_event_id"]
    assert page["events"][0]["kind"] == "workflow_prepared"
    assert page["next_cursor"] is None

    journal_text = (tmp_path / "workflows" / "events.v1.jsonl").read_text(
        encoding="utf-8"
    )
    projection_text = (tmp_path / "workflows" / "projection.v1.json").read_text(
        encoding="utf-8"
    )
    assert _request()["prompt"] not in journal_text
    assert _request()["prompt"] not in projection_text
    workflow_root = tmp_path / "workflows"
    assert stat.S_IMODE(workflow_root.stat().st_mode) == 0o700
    assert stat.S_IMODE((workflow_root / ".ledger.lock").stat().st_mode) == 0o600
    assert stat.S_IMODE((workflow_root / "events.v1.jsonl").stat().st_mode) == 0o600
    assert stat.S_IMODE((workflow_root / "projection.v1.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(
        (workflow_root / "payloads" / f"{receipt['payload_digest']}.json").stat().st_mode
    ) == 0o400


def test_inventory_missing_authority_is_read_only_and_creates_nothing(tmp_path) -> None:
    root = tmp_path / "missing" / "workflows"
    store = ResearchWorkflowStore(root, now=lambda: NOW)

    inventory = store.inventory_tasks()

    assert inventory == {
        "schema_version": "1.0",
        "authority_state": "absent",
        "last_sequence": 0,
        "last_record_sha256": None,
        "tasks": [],
    }
    assert not root.exists()
    assert not root.parent.exists()


def test_inventory_replays_and_returns_only_safe_exact_metadata(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    command_id = "10000000-0000-0000-0000-000000000001"
    store.observe_transport_binding(
        task_id=prepared["task_id"],
        expected_version=1,
        command_id=command_id,
        binding_digest=transport_binding_digest(prepared, command_id),
    )

    inventory = store.inventory_tasks()

    assert inventory["authority_state"] == "present"
    assert inventory["last_sequence"] == 2
    assert inventory["last_record_sha256"] == store.events(prepared["task_id"])[
        "events"
    ][-1]["record_sha256"]
    assert inventory["tasks"] == [
        {
            "schema_version": prepared["schema_version"],
            "workflow_saga_id": prepared["workflow_saga_id"],
            "owner_user_id": prepared["owner_user_id"],
            "platform_session_id": prepared["platform_session_id"],
            "client_request_id": prepared["client_request_id"],
            "command_kind": prepared["command_kind"],
            "canonical_request_digest": prepared["canonical_request_digest"],
            "payload_ref": prepared["payload_ref"],
            "payload_digest": prepared["payload_digest"],
            "payload_expires_at": prepared["payload_expires_at"],
            "provider_policy_digest": prepared["provider_policy_digest"],
            "task_id": prepared["task_id"],
            "task_version": prepared["task_version"],
            "attempt_id": prepared["attempt_id"],
            "attempt_number": prepared["attempt_number"],
            "prepared_event_id": prepared["prepared_event_id"],
            "prepared_event_digest": prepared["prepared_event_digest"],
            "plan_schema_version": prepared["plan_schema_version"],
            "plan_version": prepared["plan_version"],
            "plan_digest": prepared["plan_digest"],
            "workflow_preparation_digest": prepared[
                "workflow_preparation_digest"
            ],
            "payload_status": "available",
            "transport_binding": {
                "command_id": command_id,
                "binding_digest": transport_binding_digest(prepared, command_id),
                "workflow_preparation_digest": prepared[
                    "workflow_preparation_digest"
                ],
            },
        }
    ]
    serialized = json.dumps(inventory, sort_keys=True)
    assert _request()["prompt"] not in serialized
    assert _request()["plan"]["goal"] not in serialized
    assert "openai-codex" not in serialized
    assert str(store.root) not in serialized


def test_inventory_fails_closed_on_partial_authority_restore(tmp_path) -> None:
    root = tmp_path / "workflows"
    store = ResearchWorkflowStore(root, now=lambda: NOW)
    store.prepare(_request())
    (root / ".ledger.lock").unlink()

    with pytest.raises(ResearchWorkflowError) as caught:
        store.inventory_tasks()

    assert caught.value.code == "workflow_ledger_corrupt"


def test_missing_canonical_authority_with_remnants_never_recreates_from_payload(
    tmp_path,
) -> None:
    root = tmp_path / "workflows"
    store = ResearchWorkflowStore(root, now=lambda: NOW)
    store.prepare(_request())
    (root / ".ledger.lock").unlink()
    (root / "events.v1.jsonl").unlink()
    remaining_before = sorted(path.name for path in root.iterdir())

    with pytest.raises(ResearchWorkflowError) as inventory_error:
        store.inventory_tasks()
    with pytest.raises(ResearchWorkflowError) as prepare_error:
        store.prepare(_request())

    assert inventory_error.value.code == "workflow_ledger_corrupt"
    assert prepare_error.value.code == "workflow_ledger_corrupt"
    assert sorted(path.name for path in root.iterdir()) == remaining_before
    assert remaining_before == ["payloads", "projection.v1.json"]


@pytest.mark.parametrize(
    ("truncate_ready_lock", "remove_noncanonical_state"),
    [
        (False, False),
        (False, True),
        (True, False),
    ],
)
def test_empty_canonical_journal_never_reconstructs_initialized_authority(
    tmp_path,
    truncate_ready_lock,
    remove_noncanonical_state,
) -> None:
    root = tmp_path / "workflows"
    store = ResearchWorkflowStore(root, now=lambda: NOW)
    store.prepare(_request())
    (root / "events.v1.jsonl").write_bytes(b"")
    if truncate_ready_lock:
        (root / ".ledger.lock").write_bytes(b"")
    if remove_noncanonical_state:
        (root / "projection.v1.json").unlink()
        payload_dir = root / "payloads"
        for payload in payload_dir.iterdir():
            payload.unlink()
        payload_dir.rmdir()

    with pytest.raises(ResearchWorkflowError) as inventory_error:
        store.inventory_tasks()
    with pytest.raises(ResearchWorkflowError) as prepare_error:
        store.prepare(_request())

    assert inventory_error.value.code == "workflow_ledger_corrupt"
    assert prepare_error.value.code == "workflow_ledger_corrupt"
    assert (root / "events.v1.jsonl").read_bytes() == b""


def test_unready_lock_with_missing_journal_and_remnants_is_data_loss(tmp_path) -> None:
    root = tmp_path / "workflows"
    store = ResearchWorkflowStore(root, now=lambda: NOW)
    store.prepare(_request())
    (root / "events.v1.jsonl").unlink()
    (root / ".ledger.lock").write_bytes(b"")
    os.chmod(root / ".ledger.lock", 0o600)
    remaining_before = {
        path.name: path.stat().st_size for path in root.iterdir()
    }

    with pytest.raises(ResearchWorkflowError) as inventory_error:
        store.inventory_tasks()
    with pytest.raises(ResearchWorkflowError) as prepare_error:
        store.prepare(_request())

    assert inventory_error.value.code == "workflow_ledger_corrupt"
    assert prepare_error.value.code == "workflow_ledger_corrupt"
    assert {path.name: path.stat().st_size for path in root.iterdir()} == (
        remaining_before
    )


def test_inventory_empty_prejournal_root_is_uninitialized_without_writes(
    tmp_path,
) -> None:
    root = tmp_path / "workflows"
    root.mkdir(mode=0o700)
    store = ResearchWorkflowStore(root, now=lambda: NOW)

    inventory = store.inventory_tasks()

    assert inventory["authority_state"] == "absent"
    assert list(root.iterdir()) == []


def test_prepare_retry_returns_original_expiry_and_does_not_append(tmp_path) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    first = store.prepare(_request())
    observed_now[0] = "2026-07-17T01:02:03.000000Z"

    second = store.prepare(_request())

    assert second == first
    assert second["payload_expires_at"] == "2026-08-15T01:02:03.000000Z"
    assert len(
        (tmp_path / "workflows" / "events.v1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ) == 1


def test_observe_transport_binding_uses_exact_preparation_and_version_cas(
    tmp_path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    command_id = "10000000-0000-0000-0000-000000000001"
    binding_digest = transport_binding_digest(prepared, command_id)

    task = store.observe_transport_binding(
        task_id=prepared["task_id"],
        expected_version=1,
        command_id=command_id,
        binding_digest=binding_digest,
    )

    assert task["version"] == 2
    assert task["state"] == "ready"
    assert task["transport_binding"] == {
        "schema_version": "1.0",
        "command_id": command_id,
        "binding_digest": binding_digest,
        "workflow_preparation_digest": prepared["workflow_preparation_digest"],
        "observed_at": NOW,
    }
    assert [event["kind"] for event in store.events(prepared["task_id"])["events"]] == [
        "workflow_prepared",
        "transport_binding_observed",
    ]


def test_observe_transport_binding_retry_is_idempotent(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    command_id = "10000000-0000-0000-0000-000000000001"
    digest = transport_binding_digest(prepared, command_id)
    first = store.observe_transport_binding(
        task_id=prepared["task_id"],
        expected_version=1,
        command_id=command_id,
        binding_digest=digest,
    )

    second = store.observe_transport_binding(
        task_id=prepared["task_id"],
        expected_version=1,
        command_id=command_id,
        binding_digest=digest,
    )

    assert second == first
    assert len(
        (tmp_path / "workflows" / "events.v1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ) == 2


def test_authority_root_rejects_a_symlink_anywhere_in_its_path(tmp_path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    symlink_parent = tmp_path / "linked-parent"
    symlink_parent.symlink_to(real_parent, target_is_directory=True)
    store = ResearchWorkflowStore(symlink_parent / "workflows", now=lambda: NOW)

    with pytest.raises(ResearchWorkflowError) as caught:
        store.prepare(_request())

    assert caught.value.code == "workflow_storage_insecure"
    assert "path chain must not contain symbolic links" in caught.value.message


def test_payload_publish_failure_never_exposes_a_partial_final_name(
    tmp_path,
    monkeypatch,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    store.prepare(_request())
    payload = b'{"probe":"crash-before-publish"}\n'
    digest = hashlib.sha256(payload).hexdigest()

    def fail_publish(*args, **kwargs):
        raise OSError("simulated no-replace publish failure")

    monkeypatch.setattr(os, "link", fail_publish)
    with store._locked(exclusive=True, create=False) as locked:
        assert locked is not None
        root_fd, _, _ = locked
        with pytest.raises(OSError, match="simulated no-replace publish failure"):
            store._write_or_verify_payload(root_fd, digest, payload)

    payload_dir = tmp_path / "workflows" / "payloads"
    assert not (payload_dir / f"{digest}.json").exists()
    assert not list(payload_dir.glob(f".payload.{digest}.*.tmp"))


def test_payload_publish_recovers_the_post_link_pre_unlink_crash_window(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    receipt = store.prepare(_request())
    payload_dir = tmp_path / "workflows" / "payloads"
    final = payload_dir / f"{receipt['payload_digest']}.json"
    temporary = payload_dir / f".payload.{receipt['payload_digest']}.crash.tmp"
    os.link(final, temporary)
    payload = final.read_bytes()
    assert final.stat().st_nlink == 2

    with store._locked(exclusive=True, create=False) as locked:
        assert locked is not None
        root_fd, _, _ = locked
        store._write_or_verify_payload(
            root_fd,
            receipt["payload_digest"],
            payload,
        )

    metadata = final.stat()
    assert stat.S_IMODE(metadata.st_mode) == 0o400
    assert metadata.st_nlink == 1
    assert not temporary.exists()


def test_expired_payload_reconcile_is_audited_deletes_and_then_is_idempotent(
    tmp_path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    expired_at = "2026-08-15T01:02:03.000001Z"

    first = store.reconcile_expired_payloads(as_of=expired_at)

    assert first["requested_task_ids"] == [prepared["task_id"]]
    assert first["completed_task_ids"] == [prepared["task_id"]]
    assert first["already_deleted_task_ids"] == []
    assert not (
        tmp_path
        / "workflows"
        / "payloads"
        / f"{prepared['payload_digest']}.json"
    ).exists()
    task = store.show(prepared["task_id"])
    assert task["state"] == "payload_deleted"
    assert task["payload_status"] == "deleted"
    assert task["goal"] is None
    assert [event["kind"] for event in store.events(prepared["task_id"])["events"]] == [
        "workflow_prepared",
        "payload_deletion_requested",
        "payload_deletion_completed",
    ]
    with pytest.raises(ResearchWorkflowError) as caught:
        store.resolve_payload(prepared["payload_ref"], as_of=NOW)
    assert caught.value.code == "workflow_payload_deleted"

    second = store.reconcile_expired_payloads(as_of=expired_at)

    assert second["requested_task_ids"] == []
    assert second["completed_task_ids"] == []
    assert second["already_deleted_task_ids"] == [prepared["task_id"]]
    assert len(store.events(prepared["task_id"])["events"]) == 3


def test_expired_payload_reconcile_recovers_after_unlink_before_completion_event(
    tmp_path,
    monkeypatch,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    original_append = store._append_event
    failed = False

    def fail_first_completion(fd, event):
        nonlocal failed
        if event["kind"] == "payload_deletion_completed" and not failed:
            failed = True
            raise OSError("simulated crash after payload unlink")
        return original_append(fd, event)

    monkeypatch.setattr(store, "_append_event", fail_first_completion)
    with pytest.raises(ResearchWorkflowError) as caught:
        store.reconcile_expired_payloads(as_of="2026-08-15T01:02:03.000001Z")
    assert caught.value.code == "workflow_storage_io_error"
    assert not (
        tmp_path
        / "workflows"
        / "payloads"
        / f"{prepared['payload_digest']}.json"
    ).exists()
    assert [event["kind"] for event in store.events(prepared["task_id"])["events"]] == [
        "workflow_prepared",
        "payload_deletion_requested",
    ]

    monkeypatch.setattr(store, "_append_event", original_append)
    recovered = store.reconcile_expired_payloads(
        as_of="2026-08-15T01:02:03.000001Z"
    )

    assert recovered["requested_task_ids"] == []
    assert recovered["completed_task_ids"] == [prepared["task_id"]]
    assert store.show(prepared["task_id"])["payload_status"] == "deleted"


def test_platform_adapter_is_the_exact_metadata_only_receipt_contract(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())

    adapted = as_platform_prepared_command(prepared)

    assert adapted == prepared
    assert adapted is not prepared
    assert set(adapted) == set(prepared)
    assert "prompt" not in adapted
    assert adapted["workflow_preparation_digest"] == (
        "0b1cc9b95c2cbdecc9f052c30c68b42e626d6214745d50c96aac779c8a2716a1"
    )
    assert transport_binding_digest(
        adapted,
        "10000000-0000-0000-0000-000000000001",
    ) == "baaea27ea6173ed18a52c1eedfd99f0161576ed0f4b954efe3d61077b1d3c8d0"


def test_exact_platform_binding_can_be_observed_after_payload_expiry_but_is_not_ready(
    tmp_path,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    prepared = store.prepare(_request())
    command_id = "10000000-0000-0000-0000-000000000001"
    digest = transport_binding_digest(prepared, command_id)
    observed_now[0] = "2026-08-16T01:02:03.000000Z"

    task = store.observe_transport_binding(
        task_id=prepared["task_id"],
        expected_version=1,
        command_id=command_id,
        binding_digest=digest,
    )

    assert task["transport_binding"]["binding_digest"] == digest
    assert task["state"] == "payload_expired"
    assert task["payload_status"] == "expired"
    with pytest.raises(ResearchWorkflowError) as caught:
        store.resolve_payload(prepared["payload_ref"], as_of=observed_now[0])
    assert caught.value.code == "workflow_payload_expired"

    store.reconcile_expired_payloads(as_of=observed_now[0])
    deleted = store.show(prepared["task_id"])
    assert deleted["state"] == "payload_deleted"
    assert deleted["transport_binding"]["binding_digest"] == digest
    assert [event["kind"] for event in store.events(prepared["task_id"])["events"]] == [
        "workflow_prepared",
        "transport_binding_observed",
        "payload_deletion_requested",
        "payload_deletion_completed",
    ]


def test_deleting_one_expired_payload_does_not_break_other_task_replay(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    request_a = _request()
    request_a["payload_ttl_days"] = 1
    prepared_a = store.prepare(request_a)
    request_b = _request()
    request_b["platform_session_id"] = "session-local-2"
    request_b["client_request_id"] = "request-local-2"
    request_b["prompt"] = "Keep this second bounded payload available."
    request_b["plan"] = {
        **request_b["plan"],
        "goal": "Keep a second read-only hypothesis available.",
    }
    prepared_b = store.prepare(request_b)

    report = store.reconcile_expired_payloads(
        as_of="2026-07-18T01:02:03.000000Z"
    )

    assert report["completed_task_ids"] == [prepared_a["task_id"]]
    assert store.show(prepared_a["task_id"])["payload_status"] == "deleted"
    assert store.events(prepared_a["task_id"])["events"][-1]["kind"] == (
        "payload_deletion_completed"
    )
    task_b = store.show(prepared_b["task_id"])
    assert task_b["payload_status"] == "available"
    assert task_b["goal"] is None
    assert store.resolve_payload(
        prepared_b["payload_ref"],
        as_of="2026-07-18T01:02:03.000000Z",
    )["prompt"] == request_b["prompt"]


def test_forward_binding_reconcile_after_ttl_deletion_keeps_task_non_runnable(
    tmp_path,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    request = _request()
    request["payload_ttl_days"] = 1
    prepared = store.prepare(request)
    command_id = "10000000-0000-0000-0000-000000000001"
    digest = transport_binding_digest(prepared, command_id)
    expired_at = "2026-07-18T01:02:03.000000Z"
    store.reconcile_expired_payloads(as_of=expired_at)
    observed_now[0] = expired_at

    task = store.observe_transport_binding(
        task_id=prepared["task_id"],
        expected_version=3,
        command_id=command_id,
        binding_digest=digest,
    )

    assert task["version"] == 4
    assert task["state"] == "payload_deleted"
    assert task["payload_status"] == "deleted"
    assert task["transport_binding"]["binding_digest"] == digest
    assert [event["kind"] for event in store.events(prepared["task_id"])["events"]] == [
        "workflow_prepared",
        "payload_deletion_requested",
        "payload_deletion_completed",
        "transport_binding_observed",
    ]


def test_prepare_retry_repairs_ready_marker_after_post_projection_crash(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    first = store.prepare(_request())
    lock_path = tmp_path / "workflows" / ".ledger.lock"
    lock_path.write_bytes(b"")
    os.chmod(lock_path, 0o600)

    second = store.prepare(_request())

    assert second == first
    assert lock_path.read_bytes() == b"HQA_RESEARCH_WORKFLOW_LEDGER_READY_V1\n"


def test_platform_identifier_contract_accepts_200_chars_and_rejects_slash(
    tmp_path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    accepted = _request()
    accepted["platform_session_id"] = "s" + "a" * 199
    accepted["client_request_id"] = "r" + "b" * 199
    assert store.prepare(accepted)["platform_session_id"] == accepted[
        "platform_session_id"
    ]

    rejected = _request()
    rejected["platform_session_id"] = "bad/session"
    with pytest.raises(ResearchWorkflowError) as caught:
        store.prepare(rejected)
    assert caught.value.code == "workflow_invalid_request"


def test_prepare_reuses_sensitive_orphan_after_payload_first_journal_second_crash(
    tmp_path,
    monkeypatch,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    original_append = store._append_event

    def fail_before_journal(_fd, _event):
        raise OSError("simulated crash before workflow_prepared append")

    monkeypatch.setattr(store, "_append_event", fail_before_journal)
    with pytest.raises(ResearchWorkflowError) as caught:
        store.prepare(_request())
    assert caught.value.code == "workflow_storage_io_error"
    payload_dir = tmp_path / "workflows" / "payloads"
    original_payloads = list(payload_dir.glob("*.json"))
    assert len(original_payloads) == 1

    observed_now[0] = "2026-07-17T01:02:03.000000Z"
    monkeypatch.setattr(store, "_append_event", original_append)
    receipt = store.prepare(_request())

    assert receipt["payload_expires_at"] == "2026-08-15T01:02:03.000000Z"
    assert list(payload_dir.glob("*.json")) == original_payloads
    assert receipt["payload_digest"] == original_payloads[0].stem


def test_prejournal_orphan_reserves_the_idempotency_identity(tmp_path, monkeypatch) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    original_append = store._append_event
    monkeypatch.setattr(
        store,
        "_append_event",
        lambda _fd, _event: (_ for _ in ()).throw(OSError("pre-journal crash")),
    )
    with pytest.raises(ResearchWorkflowError):
        store.prepare(_request())
    payload_dir = tmp_path / "workflows" / "payloads"
    original_payloads = sorted(payload_dir.glob("*.json"))

    changed = _request()
    changed["prompt"] = "A different intent must not steal the same request key."
    monkeypatch.setattr(store, "_append_event", original_append)
    with pytest.raises(ResearchWorkflowError) as caught:
        store.prepare(changed)

    assert caught.value.code == "workflow_idempotency_conflict"
    assert sorted(payload_dir.glob("*.json")) == original_payloads
    assert (tmp_path / "workflows" / "events.v1.jsonl").read_bytes() == b""


def test_prepare_recovers_linked_temp_then_reuses_prejournal_orphan(
    tmp_path,
    monkeypatch,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    original_append = store._append_event

    def fail_before_journal(_fd, _event):
        raise OSError("simulated crash before workflow_prepared append")

    monkeypatch.setattr(store, "_append_event", fail_before_journal)
    with pytest.raises(ResearchWorkflowError):
        store.prepare(_request())
    payload_dir = tmp_path / "workflows" / "payloads"
    final = next(payload_dir.glob("*.json"))
    linked_temp = payload_dir / f".payload.{final.stem}.linked-crash.tmp"
    os.link(final, linked_temp)
    assert final.stat().st_nlink == 2

    monkeypatch.setattr(store, "_append_event", original_append)
    receipt = store.prepare(_request())

    assert receipt["payload_digest"] == final.stem
    assert final.stat().st_nlink == 1
    assert not linked_temp.exists()


def test_prepare_recovers_prelink_temp_without_changing_original_expiry(
    tmp_path,
    monkeypatch,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    original_append = store._append_event
    monkeypatch.setattr(
        store,
        "_append_event",
        lambda _fd, _event: (_ for _ in ()).throw(OSError("pre-journal crash")),
    )
    with pytest.raises(ResearchWorkflowError):
        store.prepare(_request())
    payload_dir = tmp_path / "workflows" / "payloads"
    final = next(payload_dir.glob("*.json"))
    digest = final.stem
    prelink_temp = payload_dir / f".payload.{digest}.prelink-crash.tmp"
    final.rename(prelink_temp)
    observed_now[0] = "2026-07-17T01:02:03.000000Z"

    monkeypatch.setattr(store, "_append_event", original_append)
    receipt = store.prepare(_request())

    assert receipt["payload_digest"] == digest
    assert receipt["payload_expires_at"] == "2026-08-15T01:02:03.000000Z"
    assert (payload_dir / f"{digest}.json").exists()
    assert not prelink_temp.exists()
    assert len(list(payload_dir.glob("*.json"))) == 1


def test_prepare_removes_an_unpublished_partial_temp_after_write_crash(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    with store._locked(exclusive=True, create=True) as locked:
        assert locked is not None
        root_fd, _, _ = locked
        payload_fd = store._payload_dir_fd(root_fd, create=True)
        try:
            digest = "a" * 64
            name = f".payload.{digest}.partial-write.tmp"
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400, dir_fd=payload_fd)
            try:
                os.write(fd, b'{"prompt":"sensitive partial')
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(payload_fd)
        finally:
            os.close(payload_fd)

    receipt = store.prepare(_request())

    assert receipt["task_id"].startswith("hqt_")
    assert not (tmp_path / "workflows" / "payloads" / name).exists()


def test_partial_temp_cleanup_keeps_progress_beyond_legacy_entry_cap(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    with store._locked(exclusive=True, create=True) as locked:
        assert locked is not None
        root_fd, _, _ = locked
        payload_fd = store._payload_dir_fd(root_fd, create=True)
        try:
            digest = "b" * 64
            for index in range(4_097):
                name = f".payload.{digest}.partial-{index}.tmp"
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o400,
                    dir_fd=payload_fd,
                )
                os.close(fd)
            os.fsync(payload_fd)
        finally:
            os.close(payload_fd)

    receipt = store.prepare(_request())

    assert receipt["task_id"].startswith("hqt_")
    assert not list((tmp_path / "workflows" / "payloads").glob("*.tmp"))


def test_reconcile_deletes_expired_unreferenced_sensitive_orphan(
    tmp_path,
    monkeypatch,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    original_append = store._append_event
    monkeypatch.setattr(
        store,
        "_append_event",
        lambda _fd, _event: (_ for _ in ()).throw(OSError("pre-journal crash")),
    )
    with pytest.raises(ResearchWorkflowError):
        store.prepare(_request())
    payload_dir = tmp_path / "workflows" / "payloads"
    orphan = next(payload_dir.glob("*.json"))
    digest = orphan.stem
    observed_now[0] = "2026-08-16T01:02:03.000000Z"
    monkeypatch.setattr(store, "_append_event", original_append)

    report = store.reconcile_expired_payloads()

    assert report["expired_orphan_payload_digests_deleted"] == [digest]
    assert not orphan.exists()
    audit_events = [
        json.loads(line)
        for line in (tmp_path / "workflows" / "events.v1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["kind"] for event in audit_events] == [
        "orphan_payload_deletion_requested",
        "orphan_payload_deletion_completed",
    ]


def test_orphan_deletion_audit_recovers_after_unlink_before_completion(
    tmp_path,
    monkeypatch,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    original_append = store._append_event
    monkeypatch.setattr(
        store,
        "_append_event",
        lambda _fd, _event: (_ for _ in ()).throw(OSError("pre-journal crash")),
    )
    with pytest.raises(ResearchWorkflowError):
        store.prepare(_request())
    orphan = next((tmp_path / "workflows" / "payloads").glob("*.json"))
    digest = orphan.stem
    observed_now[0] = "2026-08-16T01:02:03.000000Z"
    failed = False

    def fail_completion(fd, event):
        nonlocal failed
        if event["kind"] == "orphan_payload_deletion_completed" and not failed:
            failed = True
            raise OSError("crash after orphan unlink")
        return original_append(fd, event)

    monkeypatch.setattr(store, "_append_event", fail_completion)
    with pytest.raises(ResearchWorkflowError) as caught:
        store.reconcile_expired_payloads()
    assert caught.value.code == "workflow_storage_io_error"
    assert not orphan.exists()
    requested = (tmp_path / "workflows" / "events.v1.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"kind":"orphan_payload_deletion_requested"' in requested
    assert '"kind":"orphan_payload_deletion_completed"' not in requested

    monkeypatch.setattr(store, "_append_event", original_append)
    recovered = store.reconcile_expired_payloads()

    assert recovered["expired_orphan_payload_digests_deleted"] == [digest]
    completed = (tmp_path / "workflows" / "events.v1.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"kind":"orphan_payload_deletion_completed"' in completed


def test_expired_orphan_tombstone_permanently_reserves_client_request_id(
    tmp_path,
    monkeypatch,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    original_append = store._append_event
    monkeypatch.setattr(
        store,
        "_append_event",
        lambda _fd, _event: (_ for _ in ()).throw(OSError("pre-journal crash")),
    )
    with pytest.raises(ResearchWorkflowError):
        store.prepare(_request())
    monkeypatch.setattr(store, "_append_event", original_append)
    observed_now[0] = "2026-08-16T01:02:03.000000Z"
    store.reconcile_expired_payloads()

    with pytest.raises(ResearchWorkflowError) as exact_retry:
        store.prepare(_request())
    assert exact_retry.value.code == "workflow_idempotency_expired"

    changed = _request()
    changed["prompt"] = "A different intent on the tombstoned key."
    with pytest.raises(ResearchWorkflowError) as conflict:
        store.prepare(changed)
    assert conflict.value.code == "workflow_idempotency_conflict"
    assert not list((tmp_path / "workflows" / "payloads").glob("*.json"))


def test_prompt_alias_never_crosses_into_projection_or_show(tmp_path) -> None:
    secret = "DO-NOT-PROJECT-THIS-PROMPT"
    request = _request()
    request["prompt"] = secret
    request["plan"] = {**request["plan"], "goal": secret}
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)

    receipt = store.prepare(request)

    projection = (tmp_path / "workflows" / "projection.v1.json").read_text(
        encoding="utf-8"
    )
    assert secret not in projection
    assert secret not in json.dumps(store.show(receipt["task_id"]))
    assert store.resolve_payload(receipt["payload_ref"])["prompt"] == secret


def test_stored_receipt_and_event_integer_fields_reject_booleans(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    receipt = store.prepare(_request())
    invalid_receipt = {**receipt, "task_version": True}
    with pytest.raises(ResearchWorkflowError) as receipt_error:
        store._validate_receipt(invalid_receipt)
    assert receipt_error.value.code == "workflow_ledger_corrupt"

    event = json.loads(
        (tmp_path / "workflows" / "events.v1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    event["sequence"] = True
    with pytest.raises(ResearchWorkflowError) as event_error:
        store._validate_event(
            event,
            expected_sequence=1,
            previous_record_sha256=None,
        )
    assert event_error.value.code == "workflow_ledger_corrupt"


def test_request_plan_schema_version_rejects_boolean(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    request = _request()
    request["plan"]["schema_version"] = True

    with pytest.raises(ResearchWorkflowError) as caught:
        store.prepare(request)

    assert caught.value.code == "workflow_invalid_request"


@pytest.mark.parametrize("invalid_kind", [[], {}])
def test_request_plan_step_kind_rejects_non_string_json_values(
    tmp_path,
    invalid_kind,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    request = _request()
    request["plan"]["steps"][0]["kind"] = invalid_kind

    with pytest.raises(ResearchWorkflowError) as caught:
        store.prepare(request)

    assert caught.value.code == "workflow_invalid_request"


def test_reconcile_repairs_projection_after_completion_append_replace_crash(
    tmp_path,
    monkeypatch,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    request = _request()
    request["payload_ttl_days"] = 1
    prepared = store.prepare(request)
    original_publish = store._publish_projection
    failed = False

    def fail_first_deleted_projection(root_fd, projection):
        nonlocal failed
        task = projection["tasks"].get(prepared["task_id"])
        if task and task["payload_status"] == "deleted" and not failed:
            failed = True
            raise OSError("simulated projection replace crash")
        return original_publish(root_fd, projection)

    monkeypatch.setattr(store, "_publish_projection", fail_first_deleted_projection)
    with pytest.raises(ResearchWorkflowError) as caught:
        store.reconcile_expired_payloads(as_of="2026-07-18T01:02:03.000000Z")
    assert caught.value.code == "workflow_storage_io_error"
    on_disk = (
        tmp_path / "workflows" / "projection.v1.json"
    ).read_text(encoding="utf-8")
    assert '"payload_status":"deletion_pending"' in on_disk

    monkeypatch.setattr(store, "_publish_projection", original_publish)
    recovered = store.reconcile_expired_payloads(
        as_of="2026-07-18T01:02:03.000000Z"
    )

    assert recovered["already_deleted_task_ids"] == [prepared["task_id"]]
    repaired = (
        tmp_path / "workflows" / "projection.v1.json"
    ).read_text(encoding="utf-8")
    assert '"payload_status":"deleted"' in repaired


def test_deleted_diagnostics_never_starve_new_expired_work(tmp_path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)

    def prepare_distinct(index: int, ttl_days: int) -> dict:
        request = _request()
        request["platform_session_id"] = f"session-{index}"
        request["client_request_id"] = f"request-{index}"
        request["prompt"] = f"Bounded payload {index}."
        request["payload_ttl_days"] = ttl_days
        return store.prepare(request)

    prepare_distinct(1, 1)
    prepare_distinct(2, 1)
    store.reconcile_expired_payloads(
        as_of="2026-07-18T01:02:03.000000Z",
        limit=500,
    )
    newest = prepare_distinct(3, 2)

    report = store.reconcile_expired_payloads(
        as_of="2026-07-19T01:02:03.000000Z",
        limit=1,
    )

    assert len(report["already_deleted_task_ids"]) == 1
    assert report["completed_task_ids"] == [newest["task_id"]]
    assert report["has_more"] is False


def test_prepare_retry_after_audited_payload_deletion_returns_original_receipt(
    tmp_path,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    request = _request()
    request["payload_ttl_days"] = 1
    first = store.prepare(request)
    observed_now[0] = "2026-07-18T01:02:03.000000Z"
    store.reconcile_expired_payloads()

    second = store.prepare(request)

    assert second == first
    assert store.show(first["task_id"])["payload_status"] == "deleted"
    assert len(store.events(first["task_id"])["events"]) == 3
    assert not list((tmp_path / "workflows" / "payloads").glob("*.json"))
