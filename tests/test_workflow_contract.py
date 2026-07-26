from __future__ import annotations

import pytest

import hqa.workflow_contract as workflow_contract_module
from hqa.workflow_contract import (
    BindResearchClaim,
    COMMAND_TYPES,
    ConfirmFormula,
    ConfirmPlan,
    CompleteAttempt,
    ContinueResearch,
    ExpiryTombstoneEvidence,
    ObserveProviderEvidence,
    StartResearch,
    WorkflowContractError,
    canonical_command_digest,
    command_to_document,
    parse_workflow_command_document,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
PAYLOAD_A = "payload:sha256:" + DIGEST_A


def test_start_and_continue_require_exact_content_addressed_payload_refs() -> None:
    start = StartResearch(
        operation_id="op-start",
        workspace_ref="workspace:local",
        managed_session_ref="session:managed",
        payload_ref=PAYLOAD_A,
        intent_expires_at="2026-07-20T01:02:03Z",
    )
    continued = ContinueResearch(
        operation_id="op-continue",
        task_ref="task:one",
        expected_version=1,
        payload_ref=PAYLOAD_A,
        intent_expires_at="2026-07-20T09:02:03+08:00",
    )

    assert start.intent_expires_at == "2026-07-20T01:02:03.000000Z"
    assert continued.intent_expires_at == "2026-07-20T01:02:03.000000Z"
    assert command_to_document(start) == {
        "schema_version": 2,
        "kind": "workflow.start_research",
        "operation_id": "op-start",
        "workspace_ref": "workspace:local",
        "managed_session_ref": "session:managed",
        "payload_ref": PAYLOAD_A,
        "intent_expires_at": "2026-07-20T01:02:03.000000Z",
    }
    assert parse_workflow_command_document(command_to_document(start)) == start

    for invalid in (
        "payload:" + DIGEST_A,
        "payload:sha256:" + "A" * 64,
        "payload:sha256:" + DIGEST_A + "x",
        "hqa-payload:sha256:" + DIGEST_A,
    ):
        with pytest.raises(WorkflowContractError):
            StartResearch(
                "op-invalid",
                "workspace:local",
                "session:managed",
                invalid,
                "2026-07-20T01:02:03Z",
            )


def test_research_claim_binding_is_content_addressed_and_closed() -> None:
    command = BindResearchClaim(
        "op-bind-claim",
        "task:one",
        1,
        "attempt:one",
        PAYLOAD_A,
        DIGEST_B,
    )

    document = command_to_document(command)
    assert document == {
        "schema_version": 2,
        "kind": "workflow.bind_research_claim",
        "operation_id": "op-bind-claim",
        "task_ref": "task:one",
        "expected_version": 1,
        "attempt_ref": "attempt:one",
        "payload_ref": PAYLOAD_A,
        "research_claim_digest": DIGEST_B,
    }
    assert parse_workflow_command_document(document) == command
    with pytest.raises(WorkflowContractError):
        BindResearchClaim(
            "op-bind-claim",
            "task:one",
            1,
            "attempt:one",
            PAYLOAD_A,
            "B" * 64,
        )


def test_existing_task_commands_require_positive_expected_version_and_exact_refs() -> None:
    with pytest.raises(WorkflowContractError) as stale:
        ContinueResearch(
            "op",
            "task:one",
            0,
            PAYLOAD_A,
            "2026-07-20T01:02:03Z",
        )
    with pytest.raises(WorkflowContractError) as wrong_task:
        ContinueResearch(
            "op",
            "attempt:one",
            1,
            PAYLOAD_A,
            "2026-07-20T01:02:03Z",
        )
    with pytest.raises(WorkflowContractError) as provider_ref:
        ObserveProviderEvidence(
            "op",
            "task:one",
            1,
            "attempt:one",
            "run:one",
            "provider:one",
        )

    assert stale.value.field == "expected_version"
    assert wrong_task.value.field == "task_ref"
    assert provider_ref.value.field == "provider_evidence_ref"


def test_human_confirmation_notes_are_nonempty_bounded_and_digest_sensitive() -> None:
    first = ConfirmPlan(
        "op-confirm",
        "task:one",
        4,
        1,
        DIGEST_A,
        "I reviewed exact plan version 1.",
    )
    second = ConfirmPlan(
        "op-confirm",
        "task:one",
        4,
        1,
        DIGEST_A,
        "I reviewed exact plan version 1 again.",
    )

    assert canonical_command_digest(first) != canonical_command_digest(second)
    for invalid_note in ("", "   ", "contains\nnewline", "x" * 2_001):
        with pytest.raises(WorkflowContractError):
            ConfirmFormula(
                "op-formula",
                "task:one",
                5,
                "gate:gate1-one",
                DIGEST_B,
                invalid_note,
            )


def test_command_union_is_closed_and_contains_no_ordinary_conversation_command() -> None:
    with pytest.raises(TypeError):
        command_to_document(  # type: ignore[arg-type]
            {
                "kind": "conversation.turn",
                "prompt": "must never enter the workflow authority",
            }
        )

    document = command_to_document(
        StartResearch(
            "op-exact",
            "workspace:local",
            "session:managed",
            PAYLOAD_A,
            "2026-07-20T01:02:03Z",
        )
    )
    document["prompt"] = "forbidden second schema"
    with pytest.raises(WorkflowContractError) as extra:
        parse_workflow_command_document(document)
    assert extra.value.field == "fields"


def test_completed_attempt_requires_exact_run_and_provider_evidence() -> None:
    with pytest.raises(WorkflowContractError):
        CompleteAttempt(
            "op-complete",
            "task:one",
            1,
            "attempt:one",
            "completed",
        )
    with pytest.raises(WorkflowContractError):
        CompleteAttempt(
            "op-fake-failure",
            "task:one",
            1,
            "attempt:one",
            "failed",
        )


def test_tombstone_event_refs_are_exact_stable_event_ids() -> None:
    with pytest.raises(WorkflowContractError) as short_event:
        ExpiryTombstoneEvidence(
            owner_user_id="owner-local-1",
            workspace_ref="workspace:local",
            managed_session_ref="session:managed",
            attempt_ref="attempt:one",
            payload_ref=PAYLOAD_A,
            tombstone_event_ref="event:not-a-stable-id",
            tombstone_digest=DIGEST_B,
        )
    assert short_event.value.field == "tombstone_event_ref"


@pytest.mark.parametrize(
    ("class_name", "kind"),
    (
        ("ExpireIntent", "workflow.expire_intent"),
        ("ObservePayloadTombstone", "workflow.observe_payload_tombstone"),
    ),
)
def test_expiry_mutations_are_not_public_workflow_commands(
    class_name: str,
    kind: str,
) -> None:
    assert not hasattr(workflow_contract_module, class_name)
    assert class_name not in workflow_contract_module.__all__
    assert class_name not in {command_type.__name__ for command_type in COMMAND_TYPES}
    with pytest.raises(WorkflowContractError) as rejected:
        parse_workflow_command_document(
            {
                "schema_version": 2,
                "kind": kind,
                "operation_id": "op-forged-expiry",
                "task_ref": "task:one",
                "expected_version": 1,
                "attempt_ref": "attempt:one",
                "payload_ref": PAYLOAD_A,
                "tombstone_event_ref": "event:" + "c" * 64,
                "tombstone_digest": DIGEST_B,
            }
        )
    assert rejected.value.code == "unknown_command"


def test_expiry_tombstone_evidence_is_owner_scoped_and_exact() -> None:
    evidence = ExpiryTombstoneEvidence(
        owner_user_id="owner-local-1",
        workspace_ref="workspace:local",
        managed_session_ref="session:managed",
        attempt_ref="attempt:one",
        payload_ref=PAYLOAD_A,
        tombstone_event_ref="event:" + "c" * 64,
        tombstone_digest=DIGEST_B,
    )

    assert evidence.attempt_ref == "attempt:one"
    with pytest.raises(WorkflowContractError) as wrong_owner:
        ExpiryTombstoneEvidence(
            owner_user_id="other owner",
            workspace_ref=evidence.workspace_ref,
            managed_session_ref=evidence.managed_session_ref,
            attempt_ref=evidence.attempt_ref,
            payload_ref=evidence.payload_ref,
            tombstone_event_ref=evidence.tombstone_event_ref,
            tombstone_digest=evidence.tombstone_digest,
        )
    assert wrong_owner.value.field == "owner_user_id"
