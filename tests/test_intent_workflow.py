from __future__ import annotations

from pathlib import Path

from hqa.intent_payload_crypto import DeterministicCryptoFake
from hqa.intent_payloads import IntentPayloadStore


def _payload_store(tmp_path: Path) -> IntentPayloadStore:
    return IntentPayloadStore(
        tmp_path / "intent-payloads-v2",
        crypto=DeterministicCryptoFake(key=b"c" * 32),
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )


def _request(kind: str, client_intent_id: str) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "kind": kind,
        "owner_id": "owner-1",
        "workspace_id": "workspace:managed-1",
        "session_id": "session:managed-1",
        "client_intent_id": client_intent_id,
        "provider_policy": {"route": "managed-default"},
        "prompt": "private prompt body",
        "ttl_days": 7,
    }


class _ForbiddenWorkflow:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError("ordinary conversation must not touch workflow authority")


class _FailFirstBind:
    def __init__(self, store: IntentPayloadStore) -> None:
        self.store = store
        self.failed = False

    def put(self, request: dict[str, object]) -> dict[str, object]:
        return self.store.put(request)

    def status(self, payload_ref: str, **arguments: object) -> dict[str, object]:
        return self.store.status(payload_ref, **arguments)

    def bind_consumer(self, **arguments: object) -> dict[str, object]:
        if not self.failed:
            self.failed = True
            raise OSError("simulated crash after workflow commit")
        return self.store.bind_consumer(**arguments)


class _ExpireAfterPut:
    def __init__(self, store: IntentPayloadStore, clock: list[str]) -> None:
        self.store = store
        self.clock = clock

    def put(self, request: dict[str, object]) -> dict[str, object]:
        receipt = self.store.put(request)
        self.clock[0] = "2026-07-21T12:00:00.000000Z"
        return receipt

    def status(self, payload_ref: str, **arguments: object) -> dict[str, object]:
        return self.store.status(payload_ref, **arguments)

    def bind_consumer(self, **arguments: object) -> dict[str, object]:
        return self.store.bind_consumer(**arguments)


class _RecordingWorkflow:
    def __init__(self) -> None:
        self.command = None
        self.owner_user_id = "owner-1"

    def apply(self, command: object):
        from hqa.workflow_contract import WorkflowReceipt

        self.command = command
        return WorkflowReceipt(
            operation_id=command.operation_id,
            operation_digest="d" * 64,
            event_id="event:" + "e" * 64,
            task_ref=command.task_ref,
            task_version=command.expected_version + 1,
            attempt_ref="attempt:" + "f" * 64,
            replayed=False,
        )

    def snapshot(self, _task_ref: str):
        from types import SimpleNamespace

        return SimpleNamespace(
            owner_user_id="owner-1",
            workspace_ref="workspace:managed-1",
            managed_session_ref="session:managed-1",
        )


def test_ordinary_conversation_creates_only_an_encrypted_payload(tmp_path: Path) -> None:
    from hqa.intent_workflow import IntentWorkflowCoordinator

    coordinator = IntentWorkflowCoordinator(
        payload_store=_payload_store(tmp_path),
        workflow_authority=_ForbiddenWorkflow(),
    )

    receipt = coordinator.accept_conversation(
        _request("conversation_turn", "conversation-1")
    )

    assert receipt == {
        "schema_version": "2.0",
        "kind": "conversation_turn",
        "payload_ref": receipt["payload_ref"],
        "payload_digest": receipt["payload_digest"],
        "expires_at": "2026-07-26T12:00:00.000000Z",
        "consumer_ref": None,
        "task_ref": None,
        "attempt_ref": None,
        "workflow_event_id": None,
        "task_version": None,
        "workflow_replayed": None,
    }
    assert "private prompt body" not in repr(receipt)


def test_research_start_atomically_converges_to_one_attempt_binding(
    tmp_path: Path,
) -> None:
    from hqa.intent_workflow import IntentWorkflowCoordinator
    from hqa.workflow_authority import WorkflowAuthority

    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=_payload_store(tmp_path),
        workflow_authority=workflow,
    )
    request = _request("research_start", "research-1")

    first = coordinator.start_research(request, operation_id="operation-start-1")
    replay = coordinator.start_research(request, operation_id="operation-start-1")

    assert first["task_ref"] == replay["task_ref"]
    assert first["attempt_ref"] == replay["attempt_ref"]
    assert first["consumer_ref"] == first["attempt_ref"]
    assert first["workflow_replayed"] is False
    assert replay["workflow_replayed"] is True
    snapshot = workflow.snapshot(first["task_ref"])
    assert len(snapshot.attempts) == 1
    assert snapshot.attempts[0].payload_ref == first["payload_ref"]
    assert snapshot.attempts[0].intent_expires_at == first["expires_at"]
    assert "private prompt body" not in repr(first)
    assert "private prompt body" not in repr(snapshot)


def test_research_start_rejects_cross_owner_payload_before_workflow_write(
    tmp_path: Path,
) -> None:
    import pytest

    from hqa.intent_workflow import IntentWorkflowCoordinator, IntentWorkflowError
    from hqa.workflow_authority import WorkflowAuthority

    payloads = _payload_store(tmp_path)
    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-authority",
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=payloads,
        workflow_authority=workflow,
    )

    with pytest.raises(IntentWorkflowError) as caught:
        coordinator.start_research(
            _request("research_start", "research-cross-owner-1"),
            operation_id="operation-cross-owner-1",
        )

    assert caught.value.code == "intent_workflow_owner_mismatch"
    assert not (tmp_path / "intent-payloads-v2").exists()
    assert not workflow.journal_path.exists()
    assert not workflow.projection_path.exists()


def test_retry_after_workflow_commit_before_payload_binding_converges(
    tmp_path: Path,
) -> None:
    import pytest

    from hqa.intent_workflow import IntentWorkflowCoordinator
    from hqa.workflow_authority import WorkflowAuthority

    payloads = _FailFirstBind(_payload_store(tmp_path))
    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=payloads,
        workflow_authority=workflow,
    )
    request = _request("research_start", "research-crash-1")

    with pytest.raises(OSError, match="simulated crash"):
        coordinator.start_research(request, operation_id="operation-crash-1")

    recovered = coordinator.start_research(
        request,
        operation_id="operation-crash-1",
    )

    assert recovered["workflow_replayed"] is True
    assert recovered["consumer_ref"] == recovered["attempt_ref"]
    assert len(workflow.snapshot(recovered["task_ref"]).attempts) == 1


def test_changed_operation_for_existing_payload_is_rejected_before_workflow_write(
    tmp_path: Path,
) -> None:
    import pytest

    from hqa.intent_workflow import IntentWorkflowCoordinator, IntentWorkflowError
    from hqa.workflow_authority import WorkflowAuthority

    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=_payload_store(tmp_path),
        workflow_authority=workflow,
    )
    request = _request("research_start", "research-operation-drift-1")
    accepted = coordinator.start_research(
        request,
        operation_id="operation-original-1",
    )
    before = workflow.reverse_audit()

    with pytest.raises(IntentWorkflowError) as caught:
        coordinator.start_research(
            request,
            operation_id="operation-changed-1",
        )

    assert caught.value.code == "intent_workflow_operation_conflict"
    assert workflow.reverse_audit() == before
    snapshot = workflow.snapshot(accepted["task_ref"])
    assert snapshot.attempts[0].attempt_ref == accepted["attempt_ref"]
    assert snapshot.attempts[0].payload_ref == accepted["payload_ref"]


def test_payload_expiring_before_apply_is_rejected_with_zero_workflow_write(
    tmp_path: Path,
) -> None:
    import pytest

    from hqa.intent_workflow import IntentWorkflowCoordinator, IntentWorkflowError
    from hqa.workflow_authority import WorkflowAuthority

    clock = ["2026-07-19T12:00:00.000000Z"]
    payload_store = IntentPayloadStore(
        tmp_path / "intent-payloads-v2",
        crypto=DeterministicCryptoFake(key=b"e" * 32),
        now=lambda: clock[0],
    )
    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=_ExpireAfterPut(payload_store, clock),
        workflow_authority=workflow,
    )
    expiring = _request("research_start", "research-expired-before-apply-1")
    expiring["ttl_days"] = 1

    with pytest.raises(IntentWorkflowError) as caught:
        coordinator.start_research(
            expiring,
            operation_id="operation-expired-before-apply-1",
        )

    assert caught.value.code == "intent_workflow_payload_expired"
    assert not workflow.journal_path.exists()
    assert not workflow.projection_path.exists()


def test_expired_exact_binding_replay_returns_expired_without_new_workflow_fact(
    tmp_path: Path,
) -> None:
    import pytest

    from hqa.intent_payloads import IntentPayloadError
    from hqa.intent_workflow import IntentWorkflowCoordinator
    from hqa.workflow_authority import WorkflowAuthority

    clock = ["2026-07-19T12:00:00.000000Z"]
    payload_store = IntentPayloadStore(
        tmp_path / "intent-payloads-v2",
        crypto=DeterministicCryptoFake(key=b"f" * 32),
        now=lambda: clock[0],
    )
    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=payload_store,
        workflow_authority=workflow,
    )
    expiring = _request("research_start", "research-expired-replay-1")
    expiring["ttl_days"] = 1
    accepted = coordinator.start_research(
        expiring,
        operation_id="operation-expired-replay-1",
    )
    before = workflow.reverse_audit()
    clock[0] = "2026-07-21T12:00:00.000000Z"

    with pytest.raises(IntentPayloadError) as caught:
        coordinator.start_research(
            expiring,
            operation_id="operation-expired-replay-1",
        )

    assert caught.value.code == "intent_payload_expired"
    assert workflow.reverse_audit() == before
    snapshot = workflow.snapshot(accepted["task_ref"])
    assert snapshot.attempts[0].attempt_ref == accepted["attempt_ref"]
    assert snapshot.attempts[0].payload_ref == accepted["payload_ref"]


def test_research_continue_derives_one_closed_command_and_exact_binding(
    tmp_path: Path,
) -> None:
    from hqa.intent_workflow import IntentWorkflowCoordinator
    from hqa.workflow_contract import ContinueResearch

    workflow = _RecordingWorkflow()
    coordinator = IntentWorkflowCoordinator(
        payload_store=_payload_store(tmp_path),
        workflow_authority=workflow,
    )

    receipt = coordinator.continue_research(
        _request("research_continue", "continue-1"),
        operation_id="operation-continue-1",
        task_ref="task:" + "1" * 64,
        expected_version=7,
    )

    assert type(workflow.command) is ContinueResearch
    assert workflow.command.operation_id == "operation-continue-1"
    assert workflow.command.task_ref == "task:" + "1" * 64
    assert workflow.command.expected_version == 7
    assert workflow.command.payload_ref == receipt["payload_ref"]
    assert workflow.command.intent_expires_at == receipt["expires_at"]
    assert receipt["consumer_ref"] == "attempt:" + "f" * 64
    assert receipt["attempt_ref"] == receipt["consumer_ref"]


def test_research_continue_rejects_cross_workspace_before_workflow_write(
    tmp_path: Path,
) -> None:
    import pytest

    from hqa.intent_workflow import IntentWorkflowCoordinator, IntentWorkflowError
    from hqa.workflow_authority import WorkflowAuthority
    from hqa.workflow_contract import (
        CompleteAttempt,
        ConfirmPlan,
        ObserveProviderEvidence,
        ObserveRun,
        ObserveSubmission,
        ProposePlan,
        RequestPlanConfirmation,
    )

    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=_payload_store(tmp_path),
        workflow_authority=workflow,
    )
    started = coordinator.start_research(
        _request("research_start", "research-scope-start-1"),
        operation_id="operation-scope-start-1",
    )
    task_ref = started["task_ref"]
    attempt_ref = started["attempt_ref"]
    version = started["task_version"]
    submission = workflow.apply(
        ObserveSubmission(
            "operation-scope-submit-1",
            task_ref,
            version,
            attempt_ref,
            "command:scope-plan",
        )
    )
    run = workflow.apply(
        ObserveRun(
            "operation-scope-run-1",
            task_ref,
            submission.task_version,
            attempt_ref,
            "command:scope-plan",
            "run:scope-plan",
        )
    )
    evidence = workflow.apply(
        ObserveProviderEvidence(
            "operation-scope-evidence-1",
            task_ref,
            run.task_version,
            attempt_ref,
            "run:scope-plan",
            "provider-evidence:scope-plan",
        )
    )
    plan_digest = "d" * 64
    proposed = workflow.apply(
        ProposePlan(
            "operation-scope-plan-1",
            task_ref,
            evidence.task_version,
            1,
            plan_digest,
            "run:scope-plan",
            False,
        )
    )
    requested = workflow.apply(
        RequestPlanConfirmation(
            "operation-scope-request-1",
            task_ref,
            proposed.task_version,
            1,
            plan_digest,
        )
    )
    completed = workflow.apply(
        CompleteAttempt(
            "operation-scope-complete-1",
            task_ref,
            requested.task_version,
            attempt_ref,
            "completed",
            "run:scope-plan",
            "provider-evidence:scope-plan",
        )
    )
    ready = workflow.apply(
        ConfirmPlan(
            "operation-scope-confirm-1",
            task_ref,
            completed.task_version,
            1,
            plan_digest,
            "Reviewed exact plan.",
        )
    )
    before = workflow.reverse_audit()
    mismatched = _request("research_continue", "research-cross-scope-1")
    mismatched["workspace_id"] = "workspace:other"
    mismatched["session_id"] = "session:other"

    with pytest.raises(IntentWorkflowError) as caught:
        coordinator.continue_research(
            mismatched,
            operation_id="operation-cross-scope-1",
            task_ref=task_ref,
            expected_version=ready.task_version,
        )

    assert caught.value.code == "intent_workflow_scope_mismatch"
    assert workflow.reverse_audit() == before


def test_cross_authority_backup_restore_replays_exact_refs_without_prompt(
    tmp_path: Path,
) -> None:
    from hqa.intent_workflow import IntentWorkflowCoordinator
    from hqa.workflow_authority import WorkflowAuthority

    crypto = DeterministicCryptoFake(key=b"b" * 32)
    payloads = IntentPayloadStore(
        tmp_path / "source" / "intent-payloads-v2",
        crypto=crypto,
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    workflow = WorkflowAuthority(
        tmp_path / "source" / "workflow-authority-v2",
        "owner-1",
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=payloads,
        workflow_authority=workflow,
    )
    accepted = coordinator.start_research(
        _request("research_start", "backup-1"),
        operation_id="operation-backup-1",
    )
    original_snapshot = workflow.snapshot(accepted["task_ref"])
    original_events = workflow.events(accepted["task_ref"])

    intent_backup = tmp_path / "backups" / "intent"
    workflow_backup = tmp_path / "backups" / "workflow.json"
    intent_backup.parent.mkdir(mode=0o700)
    payloads.backup(intent_backup)
    workflow.backup(workflow_backup)

    (tmp_path / "restored").mkdir(mode=0o700)
    restored_payloads = IntentPayloadStore(
        tmp_path / "restored" / "intent-payloads-v2",
        crypto=crypto,
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    restored_workflow = WorkflowAuthority(
        tmp_path / "restored" / "workflow-authority-v2",
        "owner-1",
        now=lambda: "2026-07-19T12:00:00.000000Z",
    )
    restored_payloads.restore(intent_backup)
    restored_workflow.restore(workflow_backup)

    assert restored_payloads.status(
        accepted["payload_ref"],
        owner_id="owner-1",
        workspace_id="workspace:managed-1",
        session_id="session:managed-1",
    )["payload_digest"] == accepted["payload_digest"]
    assert restored_workflow.snapshot(accepted["task_ref"]) == original_snapshot
    assert restored_workflow.events(accepted["task_ref"]) == original_events
    assert all(
        b"private prompt body" not in path.read_bytes()
        for path in intent_backup.rglob("*")
        if path.is_file()
    )
    assert b"private prompt body" not in workflow_backup.read_bytes()
