from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import stat

import pytest

import hqa.workflow_authority as workflow_authority_module
from hqa.workflow_authority import WorkflowAuthority, WorkflowAuthorityError
from hqa.workflow_contract import (
    BeginReconcile,
    BindCandidateManifest,
    CompleteAttempt,
    CompleteTask,
    ConfirmFormula,
    ConfirmPlan,
    ContinueResearch,
    EnterDomainGate,
    ExpiryTombstoneEvidence,
    LinkResult,
    ObserveGate3,
    ObserveProviderEvidence,
    ObserveRun,
    ObserveStop,
    ObserveSubmission,
    ProposePlan,
    RequestPlanConfirmation,
    RequestStop,
    RevisePlan,
    ResolveDomainGate,
    ResolveReconcile,
    StartResearch,
)


NOW = "2026-07-19T01:00:00.000000Z"
EXPIRES = "2026-07-20T01:00:00.000000Z"
PAYLOAD_A = "payload:sha256:" + "a" * 64
PAYLOAD_B = "payload:sha256:" + "b" * 64
PLAN = "c" * 64
SOURCE = "d" * 64
OBSERVATION = "e" * 64
WORKSPACE = "workspace:local"
SESSION = "session:managed"


def _store(tmp_path: Path, now: str = NOW) -> WorkflowAuthority:
    return WorkflowAuthority(
        tmp_path / "workflow-authority",
        "owner-local-1",
        now=lambda: now,
    )


def _start(store: WorkflowAuthority):
    return store.apply(
        StartResearch("op-start", WORKSPACE, SESSION, PAYLOAD_A, EXPIRES)
    )


def _start_with_run(store: WorkflowAuthority):
    receipt = _start(store)
    assert receipt.attempt_ref is not None
    receipt = store.apply(
        ObserveSubmission(
            "op-plan-submit",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "command:plan-source",
        )
    )
    return store.apply(
        ObserveRun(
            "op-plan-run",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "command:plan-source",
            "run:plan-source",
        )
    )


def _running_research(store: WorkflowAuthority):
    receipt = _start_with_run(store)
    task_ref = receipt.task_ref
    first_attempt = receipt.attempt_ref
    assert first_attempt is not None
    receipt = store.apply(
        ObserveProviderEvidence(
            "op-plan-provider",
            task_ref,
            receipt.task_version,
            first_attempt,
            "run:plan-source",
            "provider-evidence:plan",
        )
    )
    receipt = store.apply(
        ProposePlan(
            "op-plan",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
            "run:plan-source",
            True,
        )
    )
    receipt = store.apply(
        RequestPlanConfirmation(
            "op-plan-request", task_ref, receipt.task_version, 1, PLAN
        )
    )
    receipt = store.apply(
        CompleteAttempt(
            "op-plan-complete",
            task_ref,
            receipt.task_version,
            first_attempt,
            "completed",
            "run:plan-source",
            "provider-evidence:plan",
        )
    )
    receipt = store.apply(
        ConfirmPlan(
            "op-plan-confirm",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
            "Reviewed exact plan.",
        )
    )
    receipt = store.apply(
        ConfirmFormula(
            "op-formula-confirm",
            task_ref,
            receipt.task_version,
            "gate:gate1",
            SOURCE,
            "Reviewed exact source.",
        )
    )
    receipt = store.apply(
        BindCandidateManifest(
            "op-candidate-bind",
            task_ref,
            receipt.task_version,
            "gate:gate1",
            "candidate:one",
            "9" * 64,
        )
    )
    receipt = store.apply(
        ContinueResearch(
            "op-continue",
            task_ref,
            receipt.task_version,
            PAYLOAD_B,
            EXPIRES,
        )
    )
    attempt_ref = receipt.attempt_ref
    assert attempt_ref is not None
    receipt = store.apply(
        ObserveSubmission(
            "op-research-submit",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:research",
        )
    )
    receipt = store.apply(
        ObserveRun(
            "op-research-run",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:research",
            "run:research",
        )
    )
    receipt = store.apply(
        ObserveProviderEvidence(
            "op-research-provider",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:research",
            "provider-evidence:research",
        )
    )
    return receipt, task_ref, attempt_ref


def _planned_research_attempt(
    store: WorkflowAuthority,
    prefix: str,
    *,
    requires_formula_confirmation: bool = False,
    candidate_ref=None,
    manifest_digest: str = "9" * 64,
):
    start_payload_ref = "payload:sha256:" + hashlib.sha256(
        (prefix + ":start").encode("utf-8")
    ).hexdigest()
    continue_payload_ref = "payload:sha256:" + hashlib.sha256(
        (prefix + ":continue").encode("utf-8")
    ).hexdigest()
    receipt = store.apply(
        StartResearch(
            prefix + "-start",
            "workspace:" + prefix,
            "session:" + prefix,
            start_payload_ref,
            EXPIRES,
        )
    )
    task_ref = receipt.task_ref
    plan_attempt_ref = receipt.attempt_ref
    assert plan_attempt_ref is not None
    plan_command_ref = "command:" + prefix + "-plan"
    plan_run_ref = "run:" + prefix + "-plan"
    receipt = store.apply(
        ObserveSubmission(
            prefix + "-plan-submit",
            task_ref,
            receipt.task_version,
            plan_attempt_ref,
            plan_command_ref,
        )
    )
    receipt = store.apply(
        ObserveRun(
            prefix + "-plan-run",
            task_ref,
            receipt.task_version,
            plan_attempt_ref,
            plan_command_ref,
            plan_run_ref,
        )
    )
    plan_provider_ref = "provider-evidence:" + prefix + "-plan"
    receipt = store.apply(
        ObserveProviderEvidence(
            prefix + "-plan-provider",
            task_ref,
            receipt.task_version,
            plan_attempt_ref,
            plan_run_ref,
            plan_provider_ref,
        )
    )
    receipt = store.apply(
        ProposePlan(
            prefix + "-plan-propose",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
            plan_run_ref,
            requires_formula_confirmation,
        )
    )
    receipt = store.apply(
        RequestPlanConfirmation(
            prefix + "-plan-request",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
        )
    )
    receipt = store.apply(
        CompleteAttempt(
            prefix + "-plan-complete",
            task_ref,
            receipt.task_version,
            plan_attempt_ref,
            "completed",
            plan_run_ref,
            plan_provider_ref,
        )
    )
    receipt = store.apply(
        ConfirmPlan(
            prefix + "-plan-confirm",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
            "Reviewed exact plan " + prefix + ".",
        )
    )
    if requires_formula_confirmation:
        gate_ref = "gate:" + prefix + "-gate1"
        receipt = store.apply(
            ConfirmFormula(
                prefix + "-formula-confirm",
                task_ref,
                receipt.task_version,
                gate_ref,
                SOURCE,
                "Reviewed exact formula " + prefix + ".",
            )
        )
        receipt = store.apply(
            BindCandidateManifest(
                prefix + "-candidate-bind",
                task_ref,
                receipt.task_version,
                gate_ref,
                candidate_ref or "candidate:" + prefix,
                manifest_digest,
            )
        )
    receipt = store.apply(
        ContinueResearch(
            prefix + "-continue",
            task_ref,
            receipt.task_version,
            continue_payload_ref,
            EXPIRES,
        )
    )
    assert receipt.attempt_ref is not None
    return receipt, task_ref, receipt.attempt_ref


def _apply_concurrent(root: str, operation_id: str, queue) -> None:
    try:
        authority = WorkflowAuthority(
            Path(root),
            "owner-local-1",
            now=lambda: NOW,
        )
        receipt = authority.apply(
            StartResearch(
                operation_id,
                WORKSPACE,
                SESSION,
                "payload:sha256:"
                + hashlib.sha256(operation_id.encode("utf-8")).hexdigest(),
                EXPIRES,
            )
        )
        queue.put(("ok", receipt.task_ref))
    except Exception as exc:  # pragma: no cover - returned to parent process
        queue.put(("error", type(exc).__name__))


def test_full_two_attempt_lifecycle_uses_frozen_states_and_exact_refs(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = _start(store)
    task_ref = receipt.task_ref
    first_attempt = receipt.attempt_ref
    assert first_attempt is not None

    receipt = store.apply(
        ObserveSubmission(
            "op-submit-plan",
            task_ref,
            receipt.task_version,
            first_attempt,
            "command:plan-one",
        )
    )
    receipt = store.apply(
        ObserveRun(
            "op-run-plan",
            task_ref,
            receipt.task_version,
            first_attempt,
            "command:plan-one",
            "run:plan-one",
        )
    )
    receipt = store.apply(
        ObserveProviderEvidence(
            "op-plan-provider-evidence",
            task_ref,
            receipt.task_version,
            first_attempt,
            "run:plan-one",
            "provider-evidence:plan-receipt",
        )
    )
    receipt = store.apply(
        ProposePlan(
            "op-propose",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
            "run:plan-one",
            True,
        )
    )
    receipt = store.apply(
        RequestPlanConfirmation(
            "op-request-plan-confirmation",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
        )
    )
    receipt = store.apply(
        CompleteAttempt(
            "op-plan-attempt-terminal",
            task_ref,
            receipt.task_version,
            first_attempt,
            "completed",
            "run:plan-one",
            "provider-evidence:plan-receipt",
        )
    )
    receipt = store.apply(
        ConfirmPlan(
            "op-confirm-plan",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
            "Reviewed the exact plan card.",
        )
    )
    assert store.snapshot(task_ref).state == "awaiting_formula_confirmation"
    receipt = store.apply(
        ConfirmFormula(
            "op-confirm-formula",
            task_ref,
            receipt.task_version,
            "gate:gate1-exact-source",
            SOURCE,
            "Reviewed the exact source bytes.",
        )
    )
    receipt = store.apply(
        BindCandidateManifest(
            "op-bind-candidate",
            task_ref,
            receipt.task_version,
            "gate:gate1-exact-source",
            "candidate:exact-one",
            "9" * 64,
        )
    )
    assert store.snapshot(task_ref).state == "ready"

    receipt = store.apply(
        ContinueResearch(
            "op-continue",
            task_ref,
            receipt.task_version,
            PAYLOAD_B,
            EXPIRES,
        )
    )
    second_attempt = receipt.attempt_ref
    assert second_attempt is not None and second_attempt != first_attempt
    receipt = store.apply(
        ObserveSubmission(
            "op-submit-research",
            task_ref,
            receipt.task_version,
            second_attempt,
            "command:research-one",
        )
    )
    receipt = store.apply(
        ObserveRun(
            "op-run-research",
            task_ref,
            receipt.task_version,
            second_attempt,
            "command:research-one",
            "run:research-one",
        )
    )
    receipt = store.apply(
        ObserveProviderEvidence(
            "op-provider-evidence",
            task_ref,
            receipt.task_version,
            second_attempt,
            "run:research-one",
            "provider-evidence:receipt-one",
        )
    )
    receipt = store.apply(
        LinkResult(
            "op-result",
            task_ref,
            receipt.task_version,
            second_attempt,
            "run:research-one",
            "result:experiment-one",
        )
    )
    receipt = store.apply(
        EnterDomainGate(
            "op-enter-gate",
            task_ref,
            receipt.task_version,
            second_attempt,
            "gate:gate3-review-one",
        )
    )
    assert store.snapshot(task_ref).state == "awaiting_domain_gate"
    receipt = store.apply(
        ResolveDomainGate(
            "op-resolve-gate",
            task_ref,
            receipt.task_version,
            second_attempt,
            "gate:gate3-review-one",
            "passed",
        )
    )
    receipt = store.apply(
        ObserveGate3(
            "op-gate3-evidence",
            task_ref,
            receipt.task_version,
            second_attempt,
            "run:research-one",
            "gate:gate3-review-one",
            "candidate:exact-one",
            "9" * 64,
            "result:experiment-one",
            "1" * 40,
        )
    )
    receipt = store.apply(
        CompleteAttempt(
            "op-research-attempt-terminal",
            task_ref,
            receipt.task_version,
            second_attempt,
            "completed",
            "run:research-one",
            "provider-evidence:receipt-one",
        )
    )
    receipt = store.apply(
        CompleteTask(
            "op-task-terminal",
            task_ref,
            receipt.task_version,
            "completed",
            "run:research-one",
            "provider-evidence:receipt-one",
        )
    )

    snapshot = store.snapshot(task_ref)
    assert snapshot.owner_user_id == "owner-local-1"
    assert snapshot.workspace_ref == WORKSPACE
    assert snapshot.managed_session_ref == SESSION
    assert snapshot.state == "terminal"
    assert snapshot.terminal_outcome == "completed"
    assert [attempt.attempt_number for attempt in snapshot.attempts] == [1, 2]
    assert snapshot.attempts[1].provider_evidence_refs == (
        "provider-evidence:receipt-one",
    )
    assert snapshot.gate1_ref == "gate:gate1-exact-source"
    assert snapshot.gate3_refs == ("gate:gate3-review-one",)
    assert snapshot.attempts[1].gate3_bindings[0].candidate_ref == (
        "candidate:exact-one"
    )
    assert snapshot.attempts[1].gate3_bindings[0].final_receipt_ref == (
        "result:experiment-one"
    )
    assert snapshot.result_refs == ("result:experiment-one",)
    assert snapshot.plan_confirmation_note_digest is not None
    assert snapshot.gate1_note_digest is not None

    with pytest.raises(WorkflowAuthorityError) as immutable:
        store.apply(
            ContinueResearch(
                "op-after-terminal",
                task_ref,
                receipt.task_version,
                PAYLOAD_A,
                EXPIRES,
            )
        )
    assert immutable.value.code == "workflow_terminal_immutable"


def test_operation_id_digest_is_recoverable_after_ack_loss_and_conflicts_fail_closed(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    command = StartResearch("op-stable", WORKSPACE, SESSION, PAYLOAD_A, EXPIRES)

    first = store.apply(command)
    store.projection_path.unlink()
    recovered = WorkflowAuthority(
        store.root,
        "owner-local-1",
        now=lambda: "2030-01-01T00:00:00Z",
    ).apply(command)

    assert recovered.replayed is True
    assert first.event_id.startswith("event:")
    assert len(first.event_id) == len("event:") + 64
    assert recovered.event_id == first.event_id
    assert recovered.task_ref == first.task_ref
    assert recovered.task_version == first.task_version
    assert store.projection_path.exists()
    with pytest.raises(WorkflowAuthorityError) as conflict:
        store.apply(
            StartResearch("op-stable", WORKSPACE, SESSION, PAYLOAD_B, EXPIRES)
        )
    assert conflict.value.code == "workflow_idempotency_conflict"
    assert store.reverse_audit()["event_count"] == 1


def test_only_exact_read_only_operation_receipt_is_exposed(tmp_path) -> None:
    assert not hasattr(WorkflowAuthority, "attempt_binding")
    assert not hasattr(WorkflowAuthority, "payload_binding")
    store = _store(tmp_path)
    applied = _start(store)
    before = store.reverse_audit()

    observed = store.operation_receipt("op-start")

    assert observed is not None
    assert observed.replayed is True
    assert observed.event_id == applied.event_id
    assert observed.attempt_ref == applied.attempt_ref
    assert store.operation_receipt("op-not-recorded") is None
    assert store.reverse_audit() == before


@pytest.mark.parametrize(
    "private_type_name",
    ("_ExpireIntent", "_ObservePayloadTombstone"),
)
def test_public_apply_rejects_private_expiry_mutations(
    tmp_path,
    private_type_name,
) -> None:
    store = _store(tmp_path)
    receipt = _start(store)
    assert receipt.attempt_ref is not None
    private_type = getattr(workflow_authority_module, private_type_name)
    command = private_type(
        operation_id="op-forged-expiry",
        task_ref=receipt.task_ref,
        expected_version=receipt.task_version,
        attempt_ref=receipt.attempt_ref,
        payload_ref=PAYLOAD_A,
        tombstone_event_ref="event:" + "f" * 64,
        tombstone_digest="1" * 64,
    )

    with pytest.raises(TypeError):
        store.apply(command)

    assert store.reverse_audit()["event_count"] == 1


def test_payload_ref_is_globally_single_consumer_before_second_task_commit(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    first = _start(store)

    with pytest.raises(WorkflowAuthorityError) as conflict:
        store.apply(
            StartResearch(
                "op-second-consumer",
                "workspace:second",
                "session:second",
                PAYLOAD_A,
                EXPIRES,
            )
        )

    assert conflict.value.code == "workflow_binding_conflict"
    assert store.reverse_audit()["event_count"] == 1
    snapshot = store.snapshot(first.task_ref)
    assert len(snapshot.attempts) == 1
    assert snapshot.attempts[0].payload_ref == PAYLOAD_A


@pytest.mark.parametrize(
    ("workspace_ref", "managed_session_ref"),
    (
        ("workspace:other", SESSION),
        (WORKSPACE, "session:other"),
    ),
)
def test_start_idempotency_cannot_cross_workspace_or_managed_session(
    tmp_path,
    workspace_ref,
    managed_session_ref,
) -> None:
    store = _store(tmp_path)
    original = store.apply(
        StartResearch("op-scoped", WORKSPACE, SESSION, PAYLOAD_A, EXPIRES)
    )

    with pytest.raises(WorkflowAuthorityError) as conflict:
        store.apply(
            StartResearch(
                "op-scoped",
                workspace_ref,
                managed_session_ref,
                PAYLOAD_A,
                EXPIRES,
            )
        )

    assert conflict.value.code == "workflow_idempotency_conflict"
    snapshot = store.snapshot(original.task_ref)
    assert snapshot.workspace_ref == WORKSPACE
    assert snapshot.managed_session_ref == SESSION
    assert store.reverse_audit()["event_count"] == 1


def test_global_command_ref_cannot_be_rebound_across_tasks(tmp_path) -> None:
    store = _store(tmp_path)
    first, first_task, first_attempt = _planned_research_attempt(store, "cmd-a")
    second, second_task, second_attempt = _planned_research_attempt(store, "cmd-b")
    store.apply(
        ObserveSubmission(
            "cmd-a-shared-submit",
            first_task,
            first.task_version,
            first_attempt,
            "command:globally-shared",
        )
    )

    with pytest.raises(WorkflowAuthorityError) as conflict:
        store.apply(
            ObserveSubmission(
                "cmd-b-shared-submit",
                second_task,
                second.task_version,
                second_attempt,
                "command:globally-shared",
            )
        )

    assert conflict.value.code == "workflow_binding_conflict"
    assert store.snapshot(second_task).attempts[-1].submission_command_ref is None


def test_global_run_ref_cannot_be_rebound_across_tasks(tmp_path) -> None:
    store = _store(tmp_path)
    first, first_task, first_attempt = _planned_research_attempt(store, "run-a")
    second, second_task, second_attempt = _planned_research_attempt(store, "run-b")
    first = store.apply(
        ObserveSubmission(
            "run-a-submit",
            first_task,
            first.task_version,
            first_attempt,
            "command:run-a",
        )
    )
    second = store.apply(
        ObserveSubmission(
            "run-b-submit",
            second_task,
            second.task_version,
            second_attempt,
            "command:run-b",
        )
    )
    store.apply(
        ObserveRun(
            "run-a-observe",
            first_task,
            first.task_version,
            first_attempt,
            "command:run-a",
            "run:globally-shared",
        )
    )

    with pytest.raises(WorkflowAuthorityError) as conflict:
        store.apply(
            ObserveRun(
                "run-b-observe",
                second_task,
                second.task_version,
                second_attempt,
                "command:run-b",
                "run:globally-shared",
            )
        )

    assert conflict.value.code == "workflow_binding_conflict"
    assert store.snapshot(second_task).attempts[-1].run_ref is None


def test_global_provider_result_and_gate_refs_cannot_cross_tasks(tmp_path) -> None:
    store = _store(tmp_path)
    first, first_task, first_attempt = _planned_research_attempt(store, "ref-a")
    second, second_task, second_attempt = _planned_research_attempt(store, "ref-b")
    for prefix, task_ref, attempt_ref, receipt in (
        ("ref-a", first_task, first_attempt, first),
        ("ref-b", second_task, second_attempt, second),
    ):
        receipt = store.apply(
            ObserveSubmission(
                prefix + "-submit",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "command:" + prefix,
            )
        )
        receipt = store.apply(
            ObserveRun(
                prefix + "-run",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "command:" + prefix,
                "run:" + prefix,
            )
        )
        if prefix == "ref-a":
            first = receipt
        else:
            second = receipt

    first = store.apply(
        ObserveProviderEvidence(
            "ref-a-provider",
            first_task,
            first.task_version,
            first_attempt,
            "run:ref-a",
            "provider-evidence:globally-shared",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as provider_conflict:
        store.apply(
            ObserveProviderEvidence(
                "ref-b-provider-conflict",
                second_task,
                second.task_version,
                second_attempt,
                "run:ref-b",
                "provider-evidence:globally-shared",
            )
        )
    assert provider_conflict.value.code == "workflow_binding_conflict"

    first = store.apply(
        LinkResult(
            "ref-a-result",
            first_task,
            first.task_version,
            first_attempt,
            "run:ref-a",
            "result:globally-shared",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as result_conflict:
        store.apply(
            LinkResult(
                "ref-b-result-conflict",
                second_task,
                second.task_version,
                second_attempt,
                "run:ref-b",
                "result:globally-shared",
            )
        )
    assert result_conflict.value.code == "workflow_binding_conflict"

    first = store.apply(
        EnterDomainGate(
            "ref-a-gate",
            first_task,
            first.task_version,
            first_attempt,
            "gate:globally-shared",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as gate_conflict:
        store.apply(
            EnterDomainGate(
                "ref-b-gate-conflict",
                second_task,
                second.task_version,
                second_attempt,
                "gate:globally-shared",
            )
        )
    assert gate_conflict.value.code == "workflow_binding_conflict"


def test_global_bindings_survive_projection_rebuild_and_backup_restore(
    tmp_path,
) -> None:
    store = _store(tmp_path / "source")
    first, first_task, first_attempt = _planned_research_attempt(store, "persist-a")
    second, second_task, second_attempt = _planned_research_attempt(store, "persist-b")
    store.apply(
        ObserveSubmission(
            "persist-a-submit",
            first_task,
            first.task_version,
            first_attempt,
            "command:persisted",
        )
    )
    rebuilt = store.rebuild_projection()
    assert rebuilt["binding_counts"]["command_refs"] > 0

    with pytest.raises(WorkflowAuthorityError) as rebuilt_conflict:
        store.apply(
            ObserveSubmission(
                "persist-b-after-rebuild",
                second_task,
                second.task_version,
                second_attempt,
                "command:persisted",
            )
        )
    assert rebuilt_conflict.value.code == "workflow_binding_conflict"

    backup_path = tmp_path / "bindings-backup.json"
    store.backup(backup_path)
    restored = _store(tmp_path / "restored")
    restored.restore(backup_path)
    with pytest.raises(WorkflowAuthorityError) as restored_conflict:
        restored.apply(
            ObserveSubmission(
                "persist-b-after-restore",
                second_task,
                second.task_version,
                second_attempt,
                "command:persisted",
            )
        )
    assert restored_conflict.value.code == "workflow_binding_conflict"


def test_candidate_ref_cannot_be_rebound_to_a_different_manifest(tmp_path) -> None:
    store = _store(tmp_path)
    _planned_research_attempt(
        store,
        "candidate-a",
        requires_formula_confirmation=True,
        candidate_ref="candidate:globally-shared",
        manifest_digest="7" * 64,
    )

    with pytest.raises(WorkflowAuthorityError) as conflict:
        _planned_research_attempt(
            store,
            "candidate-b",
            requires_formula_confirmation=True,
            candidate_ref="candidate:globally-shared",
            manifest_digest="8" * 64,
        )

    assert conflict.value.code == "workflow_binding_conflict"


def test_terminal_gate_and_final_receipt_evidence_fail_closed(tmp_path) -> None:
    store = _store(tmp_path)
    receipt, task_ref, attempt_ref = _running_research(store)
    receipt = store.apply(
        EnterDomainGate(
            "op-domain-enter",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "gate:gate3",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as pending_gate:
        store.apply(
            CompleteAttempt(
                "op-complete-too-soon",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "completed",
                "run:research",
                "provider-evidence:research",
            )
        )
    assert pending_gate.value.code == "workflow_binding_conflict"

    receipt = store.apply(
        ResolveDomainGate(
            "op-domain-pass",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "gate:gate3",
            "passed",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as fake_receipt:
        store.apply(
            ObserveGate3(
                "op-fake-final-receipt",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "run:research",
                "gate:gate3",
                "candidate:one",
                "9" * 64,
                "result:never-observed",
                "1" * 40,
            )
        )
    assert fake_receipt.value.code in (
        "workflow_journal_corrupt",
        "workflow_binding_conflict",
    )

    receipt = store.apply(
        LinkResult(
            "op-final-result",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:research",
            "result:final",
        )
    )
    receipt = store.apply(
        ObserveGate3(
            "op-exact-gate3",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:research",
            "gate:gate3",
            "candidate:one",
            "9" * 64,
            "result:final",
            "1" * 40,
        )
    )
    receipt = store.apply(
        CompleteAttempt(
            "op-attempt-complete",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "completed",
            "run:research",
            "provider-evidence:research",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as mismatch:
        store.apply(
            CompleteTask(
                "op-task-wrong-outcome",
                task_ref,
                receipt.task_version,
                "failed",
            )
        )
    assert mismatch.value.code == "workflow_binding_conflict"


def test_formula_research_cannot_complete_without_result_and_exact_gate3(
    tmp_path,
) -> None:
    no_result = _store(tmp_path / "no-result")
    receipt, task_ref, attempt_ref = _running_research(no_result)
    with pytest.raises(WorkflowAuthorityError) as missing_result:
        no_result.apply(
            CompleteAttempt(
                "op-complete-without-result",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "completed",
                "run:research",
                "provider-evidence:research",
            )
        )
    assert missing_result.value.code in (
        "workflow_binding_conflict",
        "workflow_plan_conflict",
    )

    no_gate = _store(tmp_path / "no-gate")
    receipt, task_ref, attempt_ref = _running_research(no_gate)
    receipt = no_gate.apply(
        LinkResult(
            "op-result-without-gate",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:research",
            "result:without-gate3",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as missing_gate3:
        no_gate.apply(
            CompleteAttempt(
                "op-complete-without-gate3",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "completed",
                "run:research",
                "provider-evidence:research",
            )
        )
    assert missing_gate3.value.code == "workflow_binding_conflict"


def test_non_formula_research_still_requires_an_exact_result(tmp_path) -> None:
    store = _store(tmp_path)
    receipt, task_ref, attempt_ref = _planned_research_attempt(
        store,
        "generic",
        requires_formula_confirmation=False,
    )
    receipt = store.apply(
        ObserveSubmission(
            "generic-submit",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:generic",
        )
    )
    receipt = store.apply(
        ObserveRun(
            "generic-run",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:generic",
            "run:generic",
        )
    )
    receipt = store.apply(
        ObserveProviderEvidence(
            "generic-provider",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:generic",
            "provider-evidence:generic",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as missing_result:
        store.apply(
            CompleteAttempt(
                "generic-complete",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "completed",
                "run:generic",
                "provider-evidence:generic",
            )
        )
    assert missing_result.value.code == "workflow_plan_conflict"


def test_plan_attempt_cannot_complete_the_task_before_confirmed_research(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    receipt = _start_with_run(store)
    task_ref = receipt.task_ref
    attempt_ref = receipt.attempt_ref
    assert attempt_ref is not None
    receipt = store.apply(
        ObserveProviderEvidence(
            "op-plan-provider",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:plan-source",
            "provider-evidence:plan",
        )
    )
    receipt = store.apply(
        ProposePlan(
            "op-unconfirmed-plan",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
            "run:plan-source",
            True,
        )
    )
    receipt = store.apply(
        RequestPlanConfirmation(
            "op-unconfirmed-request",
            task_ref,
            receipt.task_version,
            1,
            PLAN,
        )
    )
    receipt = store.apply(
        CompleteAttempt(
            "op-plan-only-complete",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "completed",
            "run:plan-source",
            "provider-evidence:plan",
        )
    )

    with pytest.raises(WorkflowAuthorityError) as bypass:
        store.apply(
            CompleteTask(
                "op-plan-only-task-complete",
                task_ref,
                receipt.task_version,
                "completed",
                "run:plan-source",
                "provider-evidence:plan",
            )
        )

    assert bypass.value.code == "workflow_plan_conflict"
    snapshot = store.snapshot(task_ref)
    assert snapshot.state == "awaiting_plan_confirmation"
    assert snapshot.plan_confirmation_note_digest is None
    assert snapshot.gate1_ref is None


def test_completed_stop_observation_requires_existing_completion_evidence(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    receipt = _start(store)
    task_ref = receipt.task_ref
    attempt_ref = receipt.attempt_ref
    assert attempt_ref is not None
    receipt = store.apply(
        ObserveSubmission(
            "op-stop-race-submit",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:stop-race",
        )
    )
    receipt = store.apply(
        ObserveRun(
            "op-stop-race-run",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:stop-race",
            "run:stop-race",
        )
    )
    receipt = store.apply(
        RequestStop(
            "op-stop-race-request",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:stop-race",
            "command:stop-race-request",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as missing_evidence:
        store.apply(
            ObserveStop(
                "op-stop-race-completed",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "command:stop-race-request",
                "already_terminal",
                OBSERVATION,
                "completed",
            )
        )

    assert missing_evidence.value.code == "workflow_binding_conflict"
    attempt = store.snapshot(task_ref).attempts[0]
    assert attempt.state == "stop_requested"
    assert attempt.terminal_outcome is None


def test_reconcile_reason_requires_corresponding_existing_fact(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = _start(store)
    assert receipt.attempt_ref is not None
    with pytest.raises(WorkflowAuthorityError) as missing_run:
        store.apply(
            BeginReconcile(
                "op-fake-run-unknown",
                receipt.task_ref,
                receipt.task_version,
                receipt.attempt_ref,
                "run_outcome_unknown",
            )
        )
    assert missing_run.value.code == "workflow_binding_conflict"
    with pytest.raises(WorkflowAuthorityError) as missing_stop:
        store.apply(
            BeginReconcile(
                "op-fake-stop-unknown",
                receipt.task_ref,
                receipt.task_version,
                receipt.attempt_ref,
                "stop_outcome_unknown",
            )
        )
    assert missing_stop.value.code == "workflow_binding_conflict"


def test_journal_commit_before_projection_failure_recovers_exact_receipt(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path)
    command = StartResearch(
        "op-commit-ack-loss", WORKSPACE, SESSION, PAYLOAD_A, EXPIRES
    )
    original_write = store._write_projection

    def fail_projection(_root_fd, _projection) -> None:
        raise WorkflowAuthorityError("workflow_storage_unavailable")

    monkeypatch.setattr(store, "_write_projection", fail_projection)
    with pytest.raises(WorkflowAuthorityError) as lost_ack:
        store.apply(command)
    assert lost_ack.value.code == "workflow_storage_unavailable"
    assert store.journal_path.read_text().count("\n") == 1

    monkeypatch.setattr(store, "_write_projection", original_write)
    recovered = store.apply(command)
    assert recovered.replayed is True
    assert recovered.task_version == 1
    assert store.reverse_audit()["status"] == "consistent"
    assert store.reverse_audit()["event_count"] == 1


def test_projection_quota_is_checked_before_any_journal_append(
    tmp_path, monkeypatch
) -> None:
    baseline = _store(tmp_path / "baseline")
    baseline.apply(
        StartResearch("op-quota", WORKSPACE, SESSION, PAYLOAD_A, EXPIRES)
    )
    exact_projection_size = baseline.projection_path.stat().st_size

    monkeypatch.setattr(
        workflow_authority_module,
        "_MAX_PROJECTION_BYTES",
        exact_projection_size,
    )
    exact = _store(tmp_path / "exact")
    exact.apply(
        StartResearch("op-quota", WORKSPACE, SESSION, PAYLOAD_A, EXPIRES)
    )
    assert exact.projection_path.stat().st_size == exact_projection_size
    assert exact.reverse_audit()["status"] == "consistent"

    monkeypatch.setattr(
        workflow_authority_module,
        "_MAX_PROJECTION_BYTES",
        exact_projection_size - 1,
    )
    overflow = _store(tmp_path / "overflow")
    with pytest.raises(WorkflowAuthorityError) as quota:
        overflow.apply(
            StartResearch(
                "op-quota", WORKSPACE, SESSION, PAYLOAD_A, EXPIRES
            )
        )

    assert quota.value.code == "workflow_projection_quota"
    assert not overflow.journal_path.exists()
    assert not overflow.projection_path.exists()


def test_expected_version_cas_and_continue_require_latest_terminal_attempt(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = _start(store)
    assert receipt.attempt_ref is not None

    with pytest.raises(WorkflowAuthorityError) as stale:
        store.apply(
            ProposePlan(
                "op-stale",
                receipt.task_ref,
                999,
                1,
                PLAN,
                "run:missing",
                False,
            )
        )
    assert stale.value.code == "workflow_stale_version"
    with pytest.raises(WorkflowAuthorityError) as active:
        store.apply(
            ContinueResearch(
                "op-too-soon",
                receipt.task_ref,
                receipt.task_version,
                PAYLOAD_B,
                EXPIRES,
            )
        )
    assert active.value.code in (
        "workflow_invalid_transition",
        "workflow_attempt_not_terminal",
    )
    assert store.reverse_audit()["event_count"] == 1

    terminal = store.apply(
        ObserveSubmission(
            "op-first-submission",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "command:first",
        )
    )
    terminal = store.apply(
        BeginReconcile(
            "op-first-reconcile",
            receipt.task_ref,
            terminal.task_version,
            receipt.attempt_ref,
            "run_outcome_unknown",
        )
    )
    terminal = store.apply(
        ResolveReconcile(
            "op-first-failed",
            receipt.task_ref,
            terminal.task_version,
            receipt.attempt_ref,
            "terminal",
            OBSERVATION,
            "failed",
        )
    )
    with pytest.raises(WorkflowAuthorityError) as draft_retry:
        store.apply(
            ContinueResearch(
                "op-retry-draft-task",
                receipt.task_ref,
                terminal.task_version,
                PAYLOAD_B,
                EXPIRES,
            )
        )
    assert draft_retry.value.code == "workflow_invalid_transition"


def test_plan_revision_is_explicit_and_requires_the_next_exact_version(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = _start_with_run(store)
    receipt = store.apply(
        ProposePlan(
            "op-plan-v1",
            receipt.task_ref,
            receipt.task_version,
            1,
            PLAN,
            "run:plan-source",
            False,
        )
    )
    receipt = store.apply(
        ObserveProviderEvidence(
            "op-plan-evidence",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "run:plan-source",
            "provider-evidence:plan-source",
        )
    )
    receipt = store.apply(
        CompleteAttempt(
            "op-plan-terminal",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "completed",
            "run:plan-source",
            "provider-evidence:plan-source",
        )
    )
    revised_digest = "f" * 64
    revised = store.apply(
        RevisePlan(
            "op-plan-v2",
            receipt.task_ref,
            receipt.task_version,
            2,
            revised_digest,
            "run:plan-source",
            True,
        )
    )
    snapshot = store.snapshot(receipt.task_ref)
    assert revised.task_version == receipt.task_version + 1
    assert snapshot.state == "plan_proposed"
    assert snapshot.plan_version == 2
    assert snapshot.plan_digest == revised_digest

    with pytest.raises(WorkflowAuthorityError) as skipped:
        store.apply(
            RevisePlan(
                "op-plan-v4",
                receipt.task_ref,
                revised.task_version,
                4,
                "1" * 64,
                "run:plan-source",
                False,
            )
        )
    assert skipped.value.code == "workflow_plan_conflict"


def test_reconcile_and_stop_unknown_outcomes_remain_explicit(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = _start(store)
    task_ref = receipt.task_ref
    attempt_ref = receipt.attempt_ref
    assert attempt_ref is not None
    receipt = store.apply(
        ObserveSubmission(
            "op-submit", task_ref, receipt.task_version, attempt_ref, "command:one"
        )
    )
    receipt = store.apply(
        BeginReconcile(
            "op-reconcile",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run_outcome_unknown",
        )
    )
    assert store.snapshot(task_ref).attempts[0].state == "reconciling"
    receipt = store.apply(
        ResolveReconcile(
            "op-reconcile-terminal",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "terminal",
            OBSERVATION,
            "failed",
        )
    )
    assert store.snapshot(task_ref).attempts[0].terminal_outcome == "failed"

    discovered = _store(tmp_path / "discovered")
    receipt = _start(discovered)
    task_ref = receipt.task_ref
    attempt_ref = receipt.attempt_ref
    assert attempt_ref is not None
    receipt = discovered.apply(
        BeginReconcile(
            "op-submission-unknown",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "submission_outcome_unknown",
        )
    )
    receipt = discovered.apply(
        ObserveSubmission(
            "op-submission-discovered",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:discovered",
        )
    )
    discovered.apply(
        ObserveRun(
            "op-run-discovered",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:discovered",
            "run:discovered",
        )
    )
    assert discovered.snapshot(task_ref).attempts[0].state == "running"

    second = _store(tmp_path / "second")
    receipt = _start(second)
    task_ref = receipt.task_ref
    attempt_ref = receipt.attempt_ref
    assert attempt_ref is not None
    receipt = second.apply(
        ObserveSubmission(
            "op-submit", task_ref, receipt.task_version, attempt_ref, "command:one"
        )
    )
    receipt = second.apply(
        ObserveRun(
            "op-run",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:one",
            "run:one",
        )
    )
    receipt = second.apply(
        RequestStop(
            "op-stop",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:one",
            "command:stop-one",
        )
    )
    receipt = second.apply(
        ObserveStop(
            "op-stop-unknown",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:stop-one",
            "outcome_unknown",
            OBSERVATION,
        )
    )
    attempt = second.snapshot(task_ref).attempts[0]
    assert attempt.state == "reconciling"
    assert attempt.stop_outcome == "outcome_unknown"
    assert attempt.stop_observation_digest == OBSERVATION
    assert attempt.reconcile_reason == "stop_outcome_unknown"


def test_expired_intent_is_terminal_and_cannot_be_forged_early(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = _start(store)
    assert receipt.attempt_ref is not None
    evidence = ExpiryTombstoneEvidence(
        owner_user_id="owner-local-1",
        workspace_ref=WORKSPACE,
        managed_session_ref=SESSION,
        attempt_ref=receipt.attempt_ref,
        payload_ref=PAYLOAD_A,
        tombstone_event_ref="event:" + "1" * 64,
        tombstone_digest="2" * 64,
    )
    with pytest.raises(WorkflowAuthorityError) as early:
        store.consume_expiry_tombstones((evidence,), limit=1)
    assert early.value.code == "workflow_intent_not_expired"

    expired_store = WorkflowAuthority(
        store.root,
        "owner-local-1",
        now=lambda: "2026-07-21T01:00:00Z",
    )
    expired_store.consume_expiry_tombstones((evidence,), limit=1)
    snapshot = expired_store.snapshot(receipt.task_ref)
    assert snapshot.state == "terminal"
    assert snapshot.attempts[0].terminal_outcome == "intent_expired"
    assert snapshot.attempts[0].payload_tombstone_event_ref == (
        "event:" + "1" * 64
    )
    assert snapshot.attempts[0].payload_tombstone_digest == "2" * 64

    with pytest.raises(WorkflowAuthorityError) as stale_start:
        expired_store.apply(
            StartResearch(
                "op-already-expired",
                WORKSPACE,
                SESSION,
                PAYLOAD_B,
                "2026-07-20T01:00:00Z",
            )
        )
    assert stale_start.value.code == "workflow_intent_expired"


@pytest.mark.parametrize(
    "attempt_state",
    ("submitted", "running", "reconciling", "stop_requested"),
)
def test_expiry_cannot_orphan_an_attempt_with_possible_external_side_effects(
    tmp_path,
    attempt_state,
) -> None:
    store = _store(tmp_path / attempt_state)
    receipt = _start(store)
    task_ref = receipt.task_ref
    attempt_ref = receipt.attempt_ref
    assert attempt_ref is not None
    receipt = store.apply(
        ObserveSubmission(
            "expiry-submit",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:expiry",
        )
    )
    if attempt_state == "reconciling":
        receipt = store.apply(
            BeginReconcile(
                "expiry-reconcile",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "run_outcome_unknown",
            )
        )
    elif attempt_state in ("running", "stop_requested"):
        receipt = store.apply(
            ObserveRun(
                "expiry-run",
                task_ref,
                receipt.task_version,
                attempt_ref,
                "command:expiry",
                "run:expiry",
            )
        )
        if attempt_state == "stop_requested":
            receipt = store.apply(
                RequestStop(
                    "expiry-stop",
                    task_ref,
                    receipt.task_version,
                    attempt_ref,
                    "run:expiry",
                    "command:expiry-stop",
                )
            )

    expired = WorkflowAuthority(
        store.root,
        "owner-local-1",
        now=lambda: "2026-07-21T01:00:00Z",
    )
    before = expired.snapshot(task_ref)
    report = expired.consume_expiry_tombstones(
        (
            ExpiryTombstoneEvidence(
                owner_user_id="owner-local-1",
                workspace_ref=WORKSPACE,
                managed_session_ref=SESSION,
                attempt_ref=attempt_ref,
                payload_ref=PAYLOAD_A,
                tombstone_event_ref="event:" + "3" * 64,
                tombstone_digest="4" * 64,
            ),
        ),
        limit=1,
    )
    snapshot = expired.snapshot(task_ref)
    assert report.consumed_count == 1
    assert report.replayed_count == 0
    assert snapshot.version == before.version + 1
    assert snapshot.state == before.state
    assert snapshot.terminal_outcome == before.terminal_outcome
    assert snapshot.attempts[0].state == before.attempts[0].state
    assert (
        snapshot.attempts[0].terminal_outcome
        == before.attempts[0].terminal_outcome
    )
    assert (
        snapshot.attempts[0].payload_tombstone_event_ref
        == "event:" + "3" * 64
    )
    assert snapshot.attempts[0].payload_tombstone_digest == "4" * 64
    assert expired.events(task_ref).events[-1].event_type == (
        "payload_tombstone_observed"
    )


def test_tombstone_event_cannot_be_replayed_for_a_different_payload(tmp_path) -> None:
    store = _store(tmp_path)
    first = _start(store)
    second = store.apply(
        StartResearch(
            "op-second-payload",
            "workspace:second",
            "session:second",
            PAYLOAD_B,
            EXPIRES,
        )
    )
    assert first.attempt_ref is not None
    assert second.attempt_ref is not None
    expired = WorkflowAuthority(
        store.root,
        "owner-local-1",
        now=lambda: "2026-07-21T01:00:00Z",
    )
    tombstone_event_ref = "event:" + "3" * 64
    tombstone_digest = "4" * 64
    expired.consume_expiry_tombstones(
        (
            ExpiryTombstoneEvidence(
                owner_user_id="owner-local-1",
                workspace_ref=WORKSPACE,
                managed_session_ref=SESSION,
                attempt_ref=first.attempt_ref,
                payload_ref=PAYLOAD_A,
                tombstone_event_ref=tombstone_event_ref,
                tombstone_digest=tombstone_digest,
            ),
        ),
        limit=1,
    )

    with pytest.raises(WorkflowAuthorityError) as replayed_tombstone:
        expired.consume_expiry_tombstones(
            (
                ExpiryTombstoneEvidence(
                    owner_user_id="owner-local-1",
                    workspace_ref="workspace:second",
                    managed_session_ref="session:second",
                    attempt_ref=second.attempt_ref,
                    payload_ref=PAYLOAD_B,
                    tombstone_event_ref=tombstone_event_ref,
                    tombstone_digest=tombstone_digest,
                ),
            ),
            limit=1,
        )

    assert replayed_tombstone.value.code == "workflow_binding_conflict"
    assert expired.snapshot(second.task_ref).state == "draft"


def test_bounded_expiry_consumer_is_scoped_cas_and_exactly_idempotent(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    first = _start(store)
    second = store.apply(
        StartResearch(
            "op-expiry-second",
            "workspace:second",
            "session:second",
            PAYLOAD_B,
            EXPIRES,
        )
    )
    assert first.attempt_ref is not None
    assert second.attempt_ref is not None
    expired = WorkflowAuthority(
        store.root,
        "owner-local-1",
        now=lambda: "2026-07-21T01:00:00Z",
    )
    first_evidence = ExpiryTombstoneEvidence(
        owner_user_id="owner-local-1",
        workspace_ref=WORKSPACE,
        managed_session_ref=SESSION,
        attempt_ref=first.attempt_ref,
        payload_ref=PAYLOAD_A,
        tombstone_event_ref="event:" + "5" * 64,
        tombstone_digest="6" * 64,
    )
    second_evidence = ExpiryTombstoneEvidence(
        owner_user_id="owner-local-1",
        workspace_ref="workspace:second",
        managed_session_ref="session:second",
        attempt_ref=second.attempt_ref,
        payload_ref=PAYLOAD_B,
        tombstone_event_ref="event:" + "7" * 64,
        tombstone_digest="8" * 64,
    )

    report = expired.consume_expiry_tombstones(
        (first_evidence, second_evidence), limit=2
    )

    assert report.consumed_count == 2
    assert report.replayed_count == 0
    assert len(report.receipts) == 2
    assert all(receipt.event_id.startswith("event:") for receipt in report.receipts)
    assert all(len(receipt.operation_digest) == 64 for receipt in report.receipts)
    first_attempt = expired.snapshot(first.task_ref).attempts[0]
    assert first_attempt.payload_tombstone_event_ref == (
        first_evidence.tombstone_event_ref
    )
    assert first_attempt.payload_tombstone_digest == first_evidence.tombstone_digest

    replay = expired.consume_expiry_tombstones((first_evidence,), limit=1)
    assert replay.consumed_count == 0
    assert replay.replayed_count == 1
    assert replay.receipts[0].event_id == report.receipts[0].event_id
    assert replay.receipts[0].operation_digest == report.receipts[0].operation_digest
    assert replay.receipts[0].replayed is True


def test_expiry_consumer_rejects_scope_unknown_attempt_and_batch_rebind_before_write(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    receipt = _start(store)
    assert receipt.attempt_ref is not None
    expired = WorkflowAuthority(
        store.root,
        "owner-local-1",
        now=lambda: "2026-07-21T01:00:00Z",
    )

    def evidence(**overrides):
        fields = {
            "owner_user_id": "owner-local-1",
            "workspace_ref": WORKSPACE,
            "managed_session_ref": SESSION,
            "attempt_ref": receipt.attempt_ref,
            "payload_ref": PAYLOAD_A,
            "tombstone_event_ref": "event:" + "9" * 64,
            "tombstone_digest": "a" * 64,
        }
        fields.update(overrides)
        return ExpiryTombstoneEvidence(**fields)

    before = expired.reverse_audit()["event_count"]
    for invalid in (
        evidence(workspace_ref="workspace:wrong"),
        evidence(managed_session_ref="session:wrong"),
        evidence(attempt_ref="attempt:" + "f" * 64),
        evidence(payload_ref=PAYLOAD_B),
    ):
        with pytest.raises(WorkflowAuthorityError):
            expired.consume_expiry_tombstones((invalid,), limit=1)
        assert expired.reverse_audit()["event_count"] == before

    with pytest.raises(WorkflowAuthorityError) as oversized:
        expired.consume_expiry_tombstones(
            (evidence(), evidence(tombstone_event_ref="event:" + "b" * 64)),
            limit=1,
        )
    assert oversized.value.code == "workflow_batch_quota"
    assert expired.reverse_audit()["event_count"] == before

    with pytest.raises(WorkflowAuthorityError) as rebound:
        expired.consume_expiry_tombstones(
            (
                evidence(),
                evidence(
                    payload_ref=PAYLOAD_B,
                    tombstone_digest="c" * 64,
                ),
            ),
            limit=2,
        )
    assert rebound.value.code == "workflow_binding_conflict"
    assert expired.reverse_audit()["event_count"] == before


def test_journal_projection_and_events_never_store_body_fields_or_notes(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = _start_with_run(store)
    receipt = store.apply(
        ProposePlan(
            "op-plan",
            receipt.task_ref,
            receipt.task_version,
            1,
            PLAN,
            "run:plan-source",
            False,
        )
    )
    receipt = store.apply(
        RequestPlanConfirmation(
            "op-request", receipt.task_ref, receipt.task_version, 1, PLAN
        )
    )
    secret_note = "reviewed-secret-note-value"
    store.apply(
        ConfirmPlan(
            "op-confirm",
            receipt.task_ref,
            receipt.task_version,
            1,
            PLAN,
            secret_note,
        )
    )

    persisted = store.journal_path.read_text() + store.projection_path.read_text()
    public = json.dumps(
        [dict(event.data) for event in store.events(receipt.task_ref).events]
    )
    assert secret_note not in persisted
    assert secret_note not in public
    for forbidden_key in (
        '"prompt"',
        '"plan_body"',
        '"provider"',
        '"model"',
        '"assertion"',
        '"backtest_body"',
    ):
        assert forbidden_key not in persisted
        assert forbidden_key not in public


def test_event_paging_is_stable_and_projection_deletion_rebuilds(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = _start_with_run(store)
    receipt = store.apply(
        ProposePlan(
            "op-plan",
            receipt.task_ref,
            receipt.task_version,
            1,
            PLAN,
            "run:plan-source",
            False,
        )
    )
    store.apply(
        RequestPlanConfirmation(
            "op-request", receipt.task_ref, receipt.task_version, 1, PLAN
        )
    )

    first_page = store.events(receipt.task_ref, limit=3)
    second_page = store.events(
        receipt.task_ref,
        after_event_id=first_page.next_after_event_id,
        limit=3,
    )
    assert first_page.has_more is True
    assert len(first_page.events) == 3
    assert len(second_page.events) == 2
    assert not second_page.has_more
    assert all(
        event.event_id.startswith("event:")
        for event in first_page.events + second_page.events
    )
    assert first_page.next_after_event_id == first_page.events[-1].event_id
    assert second_page.next_after_event_id == second_page.events[-1].event_id
    assert len({event.event_id for event in first_page.events + second_page.events}) == 5
    empty_page = store.events(
        receipt.task_ref,
        after_event_id=second_page.next_after_event_id,
        limit=2,
    )
    assert empty_page.events == ()
    assert empty_page.next_after_event_id == second_page.next_after_event_id

    store.projection_path.unlink()
    assert store.reverse_audit()["status"] == "projection_missing"
    assert store.snapshot(receipt.task_ref).version == 5
    assert store.reverse_audit()["status"] == "consistent"


def test_hash_chain_tampering_fails_closed_and_never_repairs_journal(tmp_path) -> None:
    store = _store(tmp_path)
    receipt = _start(store)
    original = store.journal_path.read_bytes()
    record = json.loads(original)
    record["data"]["payload_digest"] = "f" * 64
    store.journal_path.write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    )
    os.chmod(store.journal_path, 0o600)

    with pytest.raises(WorkflowAuthorityError) as corrupt:
        store.snapshot(receipt.task_ref)
    assert corrupt.value.code == "workflow_journal_corrupt"
    assert store.journal_path.read_bytes() != original


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX flock")
def test_two_processes_append_without_lost_updates(tmp_path) -> None:
    root = str(tmp_path / "shared-authority")
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=_apply_concurrent, args=(root, "op-a", queue)),
        context.Process(target=_apply_concurrent, args=(root, "op-b", queue)),
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
    results = [queue.get(timeout=2), queue.get(timeout=2)]

    assert all(process.exitcode == 0 for process in processes)
    assert sorted(result[0] for result in results) == ["ok", "ok"]
    audit = WorkflowAuthority(
        Path(root), "owner-local-1", now=lambda: NOW
    ).reverse_audit()
    assert audit["status"] == "consistent"
    assert audit["event_count"] == 2
    assert audit["task_count"] == 2


def test_owner_only_modes_are_enforced(tmp_path) -> None:
    store = _store(tmp_path)
    _start(store)
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    for path in (store.lock_path, store.journal_path, store.projection_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    os.chmod(store.root, 0o755)
    with pytest.raises(WorkflowAuthorityError) as insecure:
        store.reverse_audit()
    assert insecure.value.code == "workflow_storage_insecure"


def test_symlinked_root_parent_and_hardlinked_authority_files_fail_closed(
    tmp_path,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    linked = WorkflowAuthority(
        linked_parent / "authority",
        "owner-local-1",
        now=lambda: NOW,
    )
    with pytest.raises(WorkflowAuthorityError) as symlink_error:
        linked.apply(
            StartResearch("op", WORKSPACE, SESSION, PAYLOAD_A, EXPIRES)
        )
    assert symlink_error.value.code == "workflow_storage_insecure"
    assert not (real_parent / "authority").exists()

    store = _store(tmp_path / "hardlink")
    receipt = _start(store)
    journal_link = tmp_path / "journal-link"
    os.link(store.journal_path, journal_link)
    with pytest.raises(WorkflowAuthorityError) as hardlink_error:
        store.snapshot(receipt.task_ref)
    assert hardlink_error.value.code == "workflow_storage_insecure"


def test_filesystem_root_is_rejected_without_io() -> None:
    with pytest.raises(ValueError):
        WorkflowAuthority(Path("/"), "owner-local-1", now=lambda: NOW)
