from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from hqa.intent_payload_crypto import CryptoFailure, DeterministicCryptoFake
from hqa.intent_payloads import IntentPayloadStore


REPO = Path(__file__).resolve().parent.parent
WRAPPER = REPO / "scripts" / "hermes" / "hqa-intent-payload-reconcile.sh"


def _research_request(kind: str, client_intent_id: str) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "kind": kind,
        "owner_id": "owner-1",
        "workspace_id": "workspace:managed-1",
        "session_id": "session:managed-1",
        "client_intent_id": client_intent_id,
        "provider_policy": {"route": "managed-default"},
        "prompt": "private retention prompt",
        "ttl_days": 1,
    }


def _finish_planning_attempt(workflow, accepted: dict[str, object], prefix: str):
    from hqa.workflow_contract import (
        CompleteAttempt,
        ConfirmPlan,
        ObserveProviderEvidence,
        ObserveRun,
        ObserveSubmission,
        ProposePlan,
        RequestPlanConfirmation,
    )

    task_ref = accepted["task_ref"]
    attempt_ref = accepted["attempt_ref"]
    receipt = workflow.apply(
        ObserveSubmission(
            prefix + "-submit",
            task_ref,
            accepted["task_version"],
            attempt_ref,
            "command:" + prefix,
        )
    )
    receipt = workflow.apply(
        ObserveRun(
            prefix + "-run",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:" + prefix,
            "run:" + prefix,
        )
    )
    receipt = workflow.apply(
        ObserveProviderEvidence(
            prefix + "-provider",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:" + prefix,
            "provider-evidence:" + prefix,
        )
    )
    plan_digest = "d" * 64
    receipt = workflow.apply(
        ProposePlan(
            prefix + "-plan",
            task_ref,
            receipt.task_version,
            1,
            plan_digest,
            "run:" + prefix,
            False,
        )
    )
    receipt = workflow.apply(
        RequestPlanConfirmation(
            prefix + "-request-plan",
            task_ref,
            receipt.task_version,
            1,
            plan_digest,
        )
    )
    receipt = workflow.apply(
        CompleteAttempt(
            prefix + "-complete-plan",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "completed",
            "run:" + prefix,
            "provider-evidence:" + prefix,
        )
    )
    return workflow.apply(
        ConfirmPlan(
            prefix + "-confirm-plan",
            task_ref,
            receipt.task_version,
            1,
            plan_digest,
            "Reviewed exact plan.",
        )
    )


def _finish_research_task(workflow, continued: dict[str, object], prefix: str):
    from hqa.workflow_contract import (
        CompleteAttempt,
        CompleteTask,
        LinkResult,
        ObserveProviderEvidence,
        ObserveRun,
        ObserveSubmission,
    )

    task_ref = continued["task_ref"]
    attempt_ref = continued["attempt_ref"]
    receipt = workflow.apply(
        ObserveSubmission(
            prefix + "-submit",
            task_ref,
            continued["task_version"],
            attempt_ref,
            "command:" + prefix,
        )
    )
    receipt = workflow.apply(
        ObserveRun(
            prefix + "-run",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "command:" + prefix,
            "run:" + prefix,
        )
    )
    receipt = workflow.apply(
        ObserveProviderEvidence(
            prefix + "-provider",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:" + prefix,
            "provider-evidence:" + prefix,
        )
    )
    receipt = workflow.apply(
        LinkResult(
            prefix + "-result",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "run:" + prefix,
            "result:" + prefix,
        )
    )
    receipt = workflow.apply(
        CompleteAttempt(
            prefix + "-complete-attempt",
            task_ref,
            receipt.task_version,
            attempt_ref,
            "completed",
            "run:" + prefix,
            "provider-evidence:" + prefix,
        )
    )
    return workflow.apply(
        CompleteTask(
            prefix + "-complete-task",
            task_ref,
            receipt.task_version,
            "completed",
            "run:" + prefix,
            "provider-evidence:" + prefix,
        )
    )


def test_empty_retention_pass_is_silent_and_does_not_invoke_crypto(
    tmp_path: Path,
) -> None:
    helper = tmp_path / "secure" / "hqa-intent-payload-crypto"
    helper.parent.mkdir(mode=0o700)
    helper.write_text("#!/bin/bash\nexit 97\n", encoding="utf-8")
    helper.chmod(0o700)
    environment = dict(
        os.environ,
        HQA_INTENT_PAYLOAD_DIR=str(tmp_path / "intent-payloads-v2"),
        HQA_INTENT_PAYLOAD_CRYPTO_HELPER=str(helper),
    )

    result = subprocess.run(
        [sys.executable, "-m", "hqa.intent_retention_cli"],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


def test_retention_wrapper_is_a_fixed_no_agent_adapter() -> None:
    body = WRAPPER.read_text(encoding="utf-8")

    assert "cd __HQA_REPO_DIR__" in body
    assert "exec python3 -m hqa.intent_retention_cli" in body
    assert '"$#" -ne 0' in body
    assert '"$@"' not in body
    assert "hermes " not in body
    assert "quant-system" not in body


@pytest.mark.parametrize(
    ("crypto_code", "expected_status", "retryable"),
    (
        ("crypto_helper_timeout", 1, True),
        ("keychain_unavailable", 1, True),
        ("crypto_helper_insecure", 2, False),
        ("crypto_platform_unsupported", 2, False),
        ("key_corrupt", 2, False),
    ),
)
def test_retention_crypto_errors_have_stable_retry_classification(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    crypto_code: str,
    expected_status: int,
    retryable: bool,
) -> None:
    import json

    import hqa.intent_retention_cli as retention_cli

    def fail_store():
        raise CryptoFailure(crypto_code, "redacted")

    monkeypatch.setattr(retention_cli, "_store", fail_store)

    assert retention_cli.main([]) == expected_status
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["error"]["code"] == crypto_code
    assert emitted["error"]["retryable"] is retryable


def test_retention_bridges_exact_research_tombstone_and_acknowledges_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    import hqa.intent_retention_cli as retention_cli
    from hqa.intent_workflow import IntentWorkflowCoordinator
    from hqa.workflow_authority import WorkflowAuthority

    clock = ["2026-07-19T12:00:00.000000Z"]
    payloads = IntentPayloadStore(
        tmp_path / "intent-payloads-v2",
        crypto=DeterministicCryptoFake(key=b"r" * 32),
        now=lambda: clock[0],
    )
    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: clock[0],
    )
    accepted = IntentWorkflowCoordinator(
        payload_store=payloads,
        workflow_authority=workflow,
    ).start_research(
        {
            "schema_version": "2.0",
            "kind": "research_start",
            "owner_id": "owner-1",
            "workspace_id": "workspace:managed-1",
            "session_id": "session:managed-1",
            "client_intent_id": "retention-research-1",
            "provider_policy": {"route": "managed-default"},
            "prompt": "private retention prompt",
            "ttl_days": 1,
        },
        operation_id="operation-retention-start-1",
    )
    clock[0] = "2026-07-21T12:00:00.000000Z"
    monkeypatch.setattr(retention_cli, "_store", lambda: payloads)
    monkeypatch.setattr(retention_cli, "_authority", lambda: workflow, raising=False)

    assert retention_cli.main([]) == 0

    emitted = json.loads(capsys.readouterr().out)
    assert emitted == {
        "acknowledged_count": 1,
        "expired_count": 1,
        "pending_tombstone_count": 0,
        "remaining_due": 0,
        "status": "retention_applied",
    }
    snapshot = workflow.snapshot(accepted["task_ref"])
    assert snapshot.state == "terminal"
    assert snapshot.attempts[0].terminal_outcome == "intent_expired"
    assert payloads.reconcile_expired()["tombstones"] == []
    assert "private retention prompt" not in json.dumps(emitted)


def test_retention_retry_after_workflow_commit_before_payload_ack_converges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    import hqa.intent_retention_cli as retention_cli
    from hqa.intent_workflow import IntentWorkflowCoordinator
    from hqa.workflow_authority import WorkflowAuthority

    class FailFirstAck:
        def __init__(self, delegate: IntentPayloadStore) -> None:
            self.delegate = delegate
            self.failed = False

        def reconcile_expired(self, *, limit: int):
            return self.delegate.reconcile_expired(limit=limit)

        def acknowledge_expiry(self, **arguments: object):
            if not self.failed:
                self.failed = True
                raise OSError("simulated ack-loss crash")
            return self.delegate.acknowledge_expiry(**arguments)

    clock = ["2026-07-19T12:00:00.000000Z"]
    payloads = IntentPayloadStore(
        tmp_path / "intent-payloads-v2",
        crypto=DeterministicCryptoFake(key=b"s" * 32),
        now=lambda: clock[0],
    )
    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: clock[0],
    )
    accepted = IntentWorkflowCoordinator(
        payload_store=payloads,
        workflow_authority=workflow,
    ).start_research(
        {
            "schema_version": "2.0",
            "kind": "research_start",
            "owner_id": "owner-1",
            "workspace_id": "workspace:managed-1",
            "session_id": "session:managed-1",
            "client_intent_id": "retention-ack-loss-1",
            "provider_policy": {"route": "managed-default"},
            "prompt": "private ack-loss prompt",
            "ttl_days": 1,
        },
        operation_id="operation-retention-ack-loss-1",
    )
    clock[0] = "2026-07-21T12:00:00.000000Z"
    failing = FailFirstAck(payloads)
    monkeypatch.setattr(retention_cli, "_store", lambda: failing)
    monkeypatch.setattr(retention_cli, "_authority", lambda: workflow)

    assert retention_cli.main([]) == 1
    first_error = json.loads(capsys.readouterr().out)
    assert first_error["error"]["retryable"] is True
    first_audit = workflow.reverse_audit()
    assert first_audit["event_count"] == 2
    assert len(payloads.reconcile_expired()["tombstones"]) == 1

    assert retention_cli.main([]) == 0
    recovered = json.loads(capsys.readouterr().out)
    assert recovered["acknowledged_count"] == 1
    assert recovered["expired_count"] == 0
    assert recovered["pending_tombstone_count"] == 0
    assert workflow.reverse_audit() == first_audit
    assert payloads.reconcile_expired()["tombstones"] == []
    assert workflow.snapshot(accepted["task_ref"]).attempts[
        0
    ].payload_tombstone_event_ref


def test_retention_consumes_same_task_multi_attempt_expiry_in_one_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    import hqa.intent_retention_cli as retention_cli
    from hqa.intent_workflow import IntentWorkflowCoordinator
    from hqa.workflow_authority import WorkflowAuthority

    clock = ["2026-07-19T12:00:00.000000Z"]
    payloads = IntentPayloadStore(
        tmp_path / "intent-payloads-v2",
        crypto=DeterministicCryptoFake(key=b"m" * 32),
        now=lambda: clock[0],
    )
    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: clock[0],
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=payloads,
        workflow_authority=workflow,
    )
    started = coordinator.start_research(
        _research_request("research_start", "retention-multi-start-1"),
        operation_id="retention-multi-start-1",
    )
    ready = _finish_planning_attempt(workflow, started, "retention-multi-plan")
    continued = coordinator.continue_research(
        _research_request("research_continue", "retention-multi-continue-1"),
        operation_id="retention-multi-continue-1",
        task_ref=started["task_ref"],
        expected_version=ready.task_version,
    )
    before_version = continued["task_version"]
    clock[0] = "2026-07-21T12:00:00.000000Z"
    monkeypatch.setattr(retention_cli, "_store", lambda: payloads)
    monkeypatch.setattr(retention_cli, "_authority", lambda: workflow)

    assert retention_cli.main([]) == 0

    emitted = json.loads(capsys.readouterr().out)
    assert emitted["acknowledged_count"] == 2
    assert emitted["expired_count"] == 2
    assert emitted["pending_tombstone_count"] == 0
    snapshot = workflow.snapshot(started["task_ref"])
    assert snapshot.version == before_version + 2
    assert snapshot.state == "terminal"
    assert snapshot.terminal_outcome == "intent_expired"
    assert [attempt.terminal_outcome for attempt in snapshot.attempts] == [
        "completed",
        "intent_expired",
    ]
    assert all(
        attempt.payload_tombstone_event_ref is not None
        for attempt in snapshot.attempts
    )
    assert {
        event.event_type
        for event in workflow.events(started["task_ref"]).events[-2:]
    } == {"payload_tombstone_observed", "intent_expired"}
    assert payloads.reconcile_expired()["tombstones"] == []


def test_retention_preserves_completed_task_and_attempt_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    import hqa.intent_retention_cli as retention_cli
    from hqa.intent_workflow import IntentWorkflowCoordinator
    from hqa.workflow_authority import WorkflowAuthority

    clock = ["2026-07-19T12:00:00.000000Z"]
    payloads = IntentPayloadStore(
        tmp_path / "intent-payloads-v2",
        crypto=DeterministicCryptoFake(key=b"t" * 32),
        now=lambda: clock[0],
    )
    workflow = WorkflowAuthority(
        tmp_path / "workflow-authority-v2",
        "owner-1",
        now=lambda: clock[0],
    )
    coordinator = IntentWorkflowCoordinator(
        payload_store=payloads,
        workflow_authority=workflow,
    )
    started = coordinator.start_research(
        _research_request("research_start", "retention-terminal-start-1"),
        operation_id="retention-terminal-start-1",
    )
    ready = _finish_planning_attempt(
        workflow, started, "retention-terminal-plan"
    )
    continued = coordinator.continue_research(
        _research_request("research_continue", "retention-terminal-continue-1"),
        operation_id="retention-terminal-continue-1",
        task_ref=started["task_ref"],
        expected_version=ready.task_version,
    )
    completed = _finish_research_task(
        workflow, continued, "retention-terminal-research"
    )
    before = workflow.snapshot(started["task_ref"])
    assert before.state == "terminal"
    assert before.terminal_outcome == "completed"
    clock[0] = "2026-07-21T12:00:00.000000Z"
    monkeypatch.setattr(retention_cli, "_store", lambda: payloads)
    monkeypatch.setattr(retention_cli, "_authority", lambda: workflow)

    assert retention_cli.main([]) == 0

    emitted = json.loads(capsys.readouterr().out)
    assert emitted["acknowledged_count"] == 2
    assert emitted["expired_count"] == 2
    assert emitted["pending_tombstone_count"] == 0
    after = workflow.snapshot(started["task_ref"])
    assert after.version == completed.task_version + 2
    assert after.state == "terminal"
    assert after.terminal_outcome == "completed"
    assert [attempt.terminal_outcome for attempt in after.attempts] == [
        "completed",
        "completed",
    ]
    assert all(
        attempt.payload_tombstone_event_ref is not None
        for attempt in after.attempts
    )
    assert {
        event.event_type
        for event in workflow.events(started["task_ref"]).events[-2:]
    } == {"payload_tombstone_observed"}
    assert payloads.reconcile_expired()["tombstones"] == []
