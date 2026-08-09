from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from hqa import paper_research_cli
from hqa.workflow_authority import WorkflowAuthority
from hqa.workflow_contract import (
    BindCandidateManifest,
    ConfirmFormula,
    ObserveGate3,
    ResolveDomainGate,
    StartResearch,
)


EXPIRES = "2026-07-30T00:00:00.000000Z"
PLAN_DIGEST = "1" * 64
SOURCE_DIGEST = "2" * 64
CANDIDATE_DIGEST = "3" * 64
BASE_COMMIT = "4" * 40
CONFIRMATION_ID = "gate1-" + "5" * 32
FINAL_RECEIPT = "backtest-" + "6" * 32
PROMOTION_ID = "promo-" + "7" * 32 + "-r10"
REVIEWED_COMMIT = "8" * 40
WORKSPACE_ID = "workspace-root"
PLATFORM_SESSION_ID = "managed-paper-session"
HERMES_SESSION_ID = "web_managed_paper_session"
PLAN_COMMAND_ID = "10000000-0000-4000-8000-000000000001"
GATE1_COMMAND_ID = "10000000-0000-4000-8000-000000000002"
GATE2_COMMAND_ID = "10000000-0000-4000-8000-000000000003"
GATE3_COMMAND_ID = "10000000-0000-4000-8000-000000000004"


class _Registry:
    def __init__(self) -> None:
        self.gates: dict[str, dict] = {}
        self.register_calls: list[dict] = []
        self.completion_calls: list[dict] = []

    def register(self, document):
        payload = dict(document)
        self.register_calls.append(payload)
        current = self.gates.get(payload["gate_id"])
        if current is not None:
            return dict(current)
        gate = {**payload, "status": "pending"}
        self.gates[payload["gate_id"]] = gate
        return dict(gate)

    def show(self, gate_id):
        gate = self.gates.get(gate_id)
        if gate is None:
            raise paper_research_cli._RegistryError(
                "paper_gate_not_found",
                retryable=False,
                not_found=True,
            )
        return dict(gate)

    def list(self, workspace_id):
        return [
            dict(gate)
            for gate in self.gates.values()
            if gate["workspace_id"] == workspace_id
        ]

    def complete(self, document):
        payload = dict(document)
        self.completion_calls.append(payload)
        completion = {
            "completion_evidence": payload["completion_evidence"],
            "gate_id": payload["gate_id"],
            "hqa_completion_receipt_digest": payload["hqa_completion_receipt_digest"],
            "hqa_completion_receipt_ref": payload["hqa_completion_receipt_ref"],
            "reviewed_commit": payload["completion_evidence"]["reviewed_commit"],
            "status": "completed",
            "workspace_id": payload["workspace_id"],
        }
        gate = self.gates[payload["gate_id"]]
        previous = gate.get("completion")
        if previous is not None:
            assert previous == completion
            return dict(completion)
        gate.update(
            completion=dict(completion),
            expected_status="completed",
            hqa_completion_receipt_digest=payload["hqa_completion_receipt_digest"],
            hqa_completion_receipt_ref=payload["hqa_completion_receipt_ref"],
            human_git_commit_required=False,
            reviewed_commit=payload["completion_evidence"]["reviewed_commit"],
            status="completed",
        )
        return dict(completion)


def _authority(tmp_path: Path) -> WorkflowAuthority:
    return WorkflowAuthority(
        tmp_path / "workflow-authority",
        "owner-test",
        now=lambda: "2026-07-24T00:00:00.000000Z",
    )


def _call(
    monkeypatch,
    capsys,
    *,
    operation: str,
    request: dict,
    authority: WorkflowAuthority,
    registry: _Registry,
    promotion_status_reader=lambda _promotion_id: (1, ""),
) -> tuple[int, dict]:
    monkeypatch.setenv(
        "HERMES_PLATFORM_COMMAND_ID",
        request.get("command_id", PLAN_COMMAND_ID),
    )
    monkeypatch.setenv(
        "HERMES_PLATFORM_SESSION_ID",
        request.get("platform_session_id", PLATFORM_SESSION_ID),
    )
    monkeypatch.setenv(
        "HERMES_PLATFORM_RUN_ID",
        request.get("hermes_run_id", "hermes-current-run"),
    )
    monkeypatch.setenv(
        "HERMES_PLATFORM_MANAGED_SESSION_ID",
        HERMES_SESSION_ID,
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )
    code = paper_research_cli.main(
        [operation],
        authority_factory=lambda: authority,
        registry=registry,
        promotion_status_reader=promotion_status_reader,
    )
    return code, json.loads(capsys.readouterr().out)


def test_complete_metadata_only_two_attempt_paper_flow(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload1 = "payload:sha256:" + "a" * 64
    payload2 = "payload:sha256:" + "b" * 64

    code, started = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request={
            "operation_id": "paper-plan-flow",
            "workspace_id": WORKSPACE_ID,
            "platform_session_id": PLATFORM_SESSION_ID,
            "payload_ref": payload1,
            "intent_expires_at": EXPIRES,
            "command_id": PLAN_COMMAND_ID,
            "hermes_run_id": "hermes-plan-run",
            "hqa_run_ref": "run:paper-plan",
            "provider_evidence_ref": "provider-evidence:paper-plan",
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
        },
        authority=authority,
        registry=registry,
    )
    assert code == 0
    assert started["workflow_state"] == "awaiting_plan_confirmation"
    task_ref = started["task_ref"]
    plan_attempt_ref = started["attempt_ref"]

    code, confirmed = _call(
        monkeypatch,
        capsys,
        operation="confirm-plan",
        request={
            "operation_id": "paper-confirm-plan",
            "task_ref": task_ref,
            "expected_task_version": started["task_version"],
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
            "confirmation_note": "I reviewed the exact paper plan.",
        },
        authority=authority,
        registry=registry,
    )
    assert code == 0
    assert confirmed["workflow_state"] == "awaiting_formula_confirmation"

    gate1_request = {
        "operation_id": "paper-open-gate1",
        "gate_id": "paper-gate1",
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "task_ref": task_ref,
        "expected_task_version": confirmed["task_version"],
        "attempt_ref": plan_attempt_ref,
        "command_id": GATE1_COMMAND_ID,
        "hermes_run_id": "hermes-gate1-run",
        "hqa_gate_ref": "gate:paper-gate1",
        "source_file_ref": "/tmp/paper_factor.py",
        "universe": "US ETFs",
        "reviewed_source_sha256": SOURCE_DIGEST,
    }
    code, gate1_opened = _call(
        monkeypatch,
        capsys,
        operation="open-gate1",
        request=gate1_request,
        authority=authority,
        registry=registry,
    )
    assert code == 0
    assert gate1_opened["gate"]["attempt_ref"] == plan_attempt_ref
    assert gate1_opened["gate"]["hqa_run_ref"] is None

    gate1_receipt = authority.apply(
        ConfirmFormula(
            "browser-gate1-confirm",
            task_ref,
            confirmed["task_version"],
            "gate:paper-gate1",
            SOURCE_DIGEST,
            "Reviewed exact formula bytes.",
        )
    )
    registry.gates["paper-gate1"].update(
        status="confirmed",
        gate1_confirmation_id=CONFIRMATION_ID,
        hqa_receipt_ref="hqa-paper-gate:pgate-" + "1" * 32,
        hqa_receipt_digest="9" * 64,
    )

    gate2_request = {
        "operation_id": "paper-open-gate2",
        "gate_id": "paper-gate2",
        "parent_gate_id": "paper-gate1",
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "task_ref": task_ref,
        "expected_task_version": gate1_receipt.task_version,
        "attempt_ref": plan_attempt_ref,
        "command_id": GATE2_COMMAND_ID,
        "hermes_run_id": "hermes-gate2-run",
        "hqa_gate_ref": "gate:paper-gate1",
        "reviewed_source_sha256": SOURCE_DIGEST,
        "gate1_confirmation_id": CONFIRMATION_ID,
        "candidate_id": "paper-factor",
        "expected_digest": CANDIDATE_DIGEST,
        "expected_status": "pending",
    }
    code, gate2_opened = _call(
        monkeypatch,
        capsys,
        operation="open-gate2",
        request=gate2_request,
        authority=authority,
        registry=registry,
    )
    assert code == 0
    assert gate2_opened["gate"]["attempt_ref"] == plan_attempt_ref

    gate2_receipt = authority.apply(
        BindCandidateManifest(
            "browser-gate2-bind",
            task_ref,
            gate1_receipt.task_version,
            "gate:paper-gate1",
            "candidate:paper-factor",
            CANDIDATE_DIGEST,
        )
    )
    registry.gates["paper-gate2"].update(
        status="reviewed",
        hqa_receipt_ref="hqa-paper-gate:pgate-" + "2" * 32,
        hqa_receipt_digest="a" * 64,
    )

    gate3_request = {
        "operation_id": "paper-open-gate3",
        "gate_id": "paper-gate3",
        "parent_gate_id": "paper-gate2",
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "task_ref": task_ref,
        "expected_task_version": gate2_receipt.task_version,
        "payload_ref": payload2,
        "intent_expires_at": EXPIRES,
        "command_id": GATE3_COMMAND_ID,
        "hermes_run_id": "hermes-final-run",
        "hqa_run_ref": "run:paper-final",
        "provider_evidence_ref": "provider-evidence:futu-final",
        "result_ref": f"result:{FINAL_RECEIPT}",
        "hqa_gate_ref": "gate:paper-gate3",
        "reviewed_source_sha256": SOURCE_DIGEST,
        "gate1_confirmation_id": CONFIRMATION_ID,
        "candidate_id": "paper-factor",
        "expected_digest": CANDIDATE_DIGEST,
        "final_backtest_receipt_id": FINAL_RECEIPT,
        "base_commit": BASE_COMMIT,
    }
    register = registry.register
    failed_once = False

    def fail_first_gate3_registration(document):
        nonlocal failed_once
        if document["gate_kind"] == "gate3" and not failed_once:
            failed_once = True
            raise paper_research_cli._RegistryError(
                "paper_research_platform_outcome_unknown",
                retryable=False,
                outcome_unknown=True,
            )
        return register(document)

    registry.register = fail_first_gate3_registration
    code, unknown = _call(
        monkeypatch,
        capsys,
        operation="open-gate3",
        request=gate3_request,
        authority=authority,
        registry=registry,
    )
    assert code == 1
    assert unknown["error"]["code"] == ("paper_research_platform_outcome_unknown")
    assert authority.snapshot(task_ref).state == "awaiting_domain_gate"

    registry.register = register
    code, gate3_opened = _call(
        monkeypatch,
        capsys,
        operation="open-gate3",
        request=gate3_request,
        authority=authority,
        registry=registry,
    )
    assert code == 0
    final_attempt_ref = gate3_opened["gate"]["attempt_ref"]
    assert final_attempt_ref != plan_attempt_ref
    assert gate3_opened["gate"]["expected_task_version"] == (
        gate2_receipt.task_version + 6
    )

    gate3_version = gate3_opened["gate"]["expected_task_version"]
    resolved = authority.apply(
        ResolveDomainGate(
            "browser-gate3-resolve",
            task_ref,
            gate3_version,
            final_attempt_ref,
            "gate:paper-gate3",
            "passed",
        )
    )
    observed = authority.apply(
        ObserveGate3(
            "browser-gate3-observe",
            task_ref,
            resolved.task_version,
            final_attempt_ref,
            "run:paper-final",
            "gate:paper-gate3",
            "candidate:paper-factor",
            CANDIDATE_DIGEST,
            f"result:{FINAL_RECEIPT}",
            BASE_COMMIT,
        )
    )
    registry.gates["paper-gate3"].update(
        status="prepared",
        promotion_id=PROMOTION_ID,
        worktree="/tmp/paper-promotion",
        patch="/tmp/paper-promotion.patch",
        manifest="/tmp/paper-promotion.json",
        human_git_commit_required=True,
        auto_commit=False,
        reviewed_commit=None,
    )

    def promotion_status(promotion_id: str):
        assert promotion_id == PROMOTION_ID
        return (
            0,
            json.dumps(
                {
                    "promotion_id": PROMOTION_ID,
                    "status": "reviewed",
                    "reviewed_commit": REVIEWED_COMMIT,
                    "reason": "reviewed",
                    "manifest_sha256": "c" * 64,
                    "patch_sha256": "d" * 64,
                    "candidate_id": "paper-factor",
                    "candidate_digest": CANDIDATE_DIGEST,
                    "final_backtest_receipt_id": FINAL_RECEIPT,
                    "base_commit": BASE_COMMIT,
                    "scoped_paths": [
                        "src/quant_system/factors/library/promoted/paper_factor.py",
                        "src/quant_system/factors/library/promoted/__init__.py",
                        "tests/factors/test_paper_factor.py",
                    ],
                },
                sort_keys=True,
            ),
        )

    complete = registry.complete
    completion_timed_out = False

    def complete_after_apply_then_timeout(document):
        nonlocal completion_timed_out
        result = complete(document)
        if not completion_timed_out:
            completion_timed_out = True
            raise paper_research_cli._RegistryError(
                "paper_research_platform_outcome_unknown",
                retryable=False,
                outcome_unknown=True,
            )
        return result

    registry.complete = complete_after_apply_then_timeout
    completion_request = {
        "operation_id": "paper-complete-after-human",
        "gate_id": "paper-gate3",
        "workspace_id": WORKSPACE_ID,
        "task_ref": task_ref,
        "expected_task_version": observed.task_version,
        "attempt_ref": final_attempt_ref,
        "hqa_run_ref": "run:paper-final",
        "provider_evidence_ref": "provider-evidence:futu-final",
        "reviewed_commit": REVIEWED_COMMIT,
    }
    code, completion_unknown = _call(
        monkeypatch,
        capsys,
        operation="complete-after-human-commit",
        request=completion_request,
        authority=authority,
        registry=registry,
        promotion_status_reader=promotion_status,
    )
    assert code == 1
    assert completion_unknown["error"]["code"] == (
        "paper_research_platform_outcome_unknown"
    )
    assert completion_unknown["error"]["retryable"] is False
    first_completion_registration = registry.completion_calls[-1]

    # The HQA Task is already terminal, so recovery must replay the same
    # content-addressed receipt instead of inventing a new completion. An
    # unrelated Task may append while the Platform timeout is reconciled; the
    # completed Task's audit identity must remain stable.
    authority.apply(
        StartResearch(
            "unrelated-concurrent-task",
            "workspace:unrelated",
            "session:unrelated",
            "payload:sha256:" + "e" * 64,
            EXPIRES,
        )
    )
    code, completed = _call(
        monkeypatch,
        capsys,
        operation="complete-after-human-commit",
        request=completion_request,
        authority=authority,
        registry=registry,
        promotion_status_reader=promotion_status,
    )
    assert code == 0
    assert completed["workflow_state"] == "terminal"
    assert completed["terminal_outcome"] == "completed"
    completion_evidence = completed["completion_evidence"]
    assert completion_evidence["attempt_ref"] == final_attempt_ref
    assert completion_evidence["attempt_terminal_outcome"] == "completed"
    assert completion_evidence["task_terminal_outcome"] == "completed"
    assert completion_evidence["domain_gate_outcome"] == "passed"
    assert completion_evidence["task_status"] == "completed"
    assert completion_evidence["attempt_status"] == "completed"
    assert completion_evidence["hqa_run_ref"] == "run:paper-final"
    assert completion_evidence["domain_gate_ref"] == "gate:paper-gate3"
    assert completion_evidence["promotion_id"] == PROMOTION_ID
    assert completion_evidence["reviewed_commit"] == REVIEWED_COMMIT
    assert completion_evidence["workflow_audit_status"] == "consistent"
    assert completion_evidence["workflow_audit_ref"].startswith("workflow-audit:")
    assert completion_evidence["workflow_audit_ref"] == (
        "workflow-audit:" + completion_evidence["workflow_audit_digest"]
    )
    assert len(completion_evidence["workflow_audit_digest"]) == 64
    assert completed["hqa_completion_receipt_ref"].startswith("hqa-paper-completion:")
    assert completed["hqa_completion_receipt_digest"] == (
        paper_research_cli.hashlib.sha256(
            paper_research_cli._canonical_bytes(completion_evidence)
        ).hexdigest()
    )
    assert registry.completion_calls[-1] == {
        "completion_evidence": completion_evidence,
        "gate_id": "paper-gate3",
        "hqa_completion_receipt_digest": (completed["hqa_completion_receipt_digest"]),
        "hqa_completion_receipt_ref": (completed["hqa_completion_receipt_ref"]),
        "workspace_id": WORKSPACE_ID,
    }
    assert registry.completion_calls[-1] == first_completion_registration
    snapshot = authority.snapshot(task_ref)
    assert len(snapshot.attempts) == 2
    assert snapshot.attempts[0].attempt_ref == plan_attempt_ref
    assert snapshot.attempts[1].attempt_ref == final_attempt_ref
    assert snapshot.attempts[1].domain_gate_outcome == "passed"
    assert snapshot.attempts[1].gate3_bindings[0].final_receipt_ref == (
        f"result:{FINAL_RECEIPT}"
    )

    # Content-addressed completion evidence is stable on an exact replay.
    code, replayed = _call(
        monkeypatch,
        capsys,
        operation="complete-after-human-commit",
        request=completion_request,
        authority=authority,
        registry=registry,
        promotion_status_reader=promotion_status,
    )
    assert code == 0
    assert replayed["replayed"] is True
    assert (
        replayed["hqa_completion_receipt_ref"]
        == (completed["hqa_completion_receipt_ref"])
    )
    assert (
        replayed["hqa_completion_receipt_digest"]
        == (completed["hqa_completion_receipt_digest"])
    )


def test_strict_request_rejects_unknown_field(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    code, document = _call(
        monkeypatch,
        capsys,
        operation="confirm-plan",
        request={
            "operation_id": "bad-request",
            "task_ref": "task:missing",
            "expected_task_version": 1,
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
            "confirmation_note": "reviewed",
            "unexpected": True,
        },
        authority=authority,
        registry=registry,
    )
    assert code == 2
    assert document["error"]["code"] == "paper_research_invalid_request"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"operation_id":"one","operation_id":"two"}',
        b'{"operation_id":NaN}',
    ],
)
def test_strict_request_rejects_duplicate_keys_and_nonfinite_numbers(
    raw,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"),
    )
    assert (
        paper_research_cli.main(
            ["start-plan"],
            authority_factory=lambda: authority,
            registry=_Registry(),
        )
        == 2
    )
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "paper_research_invalid_request"
    )
    assert not authority.root.exists()


def test_runtime_selector_substitution_and_missing_env_fail_closed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    request = {
        "operation_id": "runtime-selector-mismatch",
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": "substituted-platform-session",
        "payload_ref": "payload:sha256:" + "a" * 64,
        "intent_expires_at": EXPIRES,
        "command_id": PLAN_COMMAND_ID,
        "hermes_run_id": "hermes-plan-run",
        "hqa_run_ref": "run:paper-plan",
        "provider_evidence_ref": "provider-evidence:paper-plan",
        "plan_version": 1,
        "plan_digest": PLAN_DIGEST,
    }
    monkeypatch.setenv("HERMES_PLATFORM_COMMAND_ID", PLAN_COMMAND_ID)
    monkeypatch.setenv("HERMES_PLATFORM_SESSION_ID", PLATFORM_SESSION_ID)
    monkeypatch.setenv("HERMES_PLATFORM_RUN_ID", "hermes-plan-run")
    monkeypatch.setenv(
        "HERMES_PLATFORM_MANAGED_SESSION_ID",
        HERMES_SESSION_ID,
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )
    assert (
        paper_research_cli.main(
            ["start-plan"],
            authority_factory=lambda: authority,
            registry=registry,
        )
        == 2
    )
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "paper_research_invalid_request"
    )
    assert not authority.root.exists()

    request["platform_session_id"] = PLATFORM_SESSION_ID
    monkeypatch.delenv("HERMES_PLATFORM_MANAGED_SESSION_ID")
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )
    assert (
        paper_research_cli.main(
            ["start-plan"],
            authority_factory=lambda: authority,
            registry=registry,
        )
        == 2
    )
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "paper_research_invalid_request"
    )
    assert not authority.root.exists()


def test_registration_timeout_is_unknown_and_never_reported_retryable(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload = "payload:sha256:" + "a" * 64
    code, started = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request={
            "operation_id": "timeout-start",
            "workspace_id": WORKSPACE_ID,
            "platform_session_id": PLATFORM_SESSION_ID,
            "payload_ref": payload,
            "intent_expires_at": EXPIRES,
            "command_id": PLAN_COMMAND_ID,
            "hermes_run_id": "hermes-plan-run",
            "hqa_run_ref": "run:paper-plan",
            "provider_evidence_ref": "provider-evidence:paper-plan",
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
        },
        authority=authority,
        registry=registry,
    )
    assert code == 0
    code, confirmed = _call(
        monkeypatch,
        capsys,
        operation="confirm-plan",
        request={
            "operation_id": "timeout-confirm",
            "task_ref": started["task_ref"],
            "expected_task_version": started["task_version"],
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
            "confirmation_note": "reviewed exact plan",
        },
        authority=authority,
        registry=registry,
    )
    assert code == 0

    class _TimeoutRegistry(_Registry):
        def register(self, document):
            raise paper_research_cli._RegistryError(
                "paper_research_platform_outcome_unknown",
                retryable=False,
                outcome_unknown=True,
            )

    code, failed = _call(
        monkeypatch,
        capsys,
        operation="open-gate1",
        request={
            "operation_id": "timeout-gate1",
            "gate_id": "timeout-gate1",
            "workspace_id": WORKSPACE_ID,
            "platform_session_id": PLATFORM_SESSION_ID,
            "task_ref": started["task_ref"],
            "expected_task_version": confirmed["task_version"],
            "attempt_ref": started["attempt_ref"],
            "command_id": GATE1_COMMAND_ID,
            "hermes_run_id": "hermes-gate1-run",
            "hqa_gate_ref": "gate:timeout-gate1",
            "source_file_ref": "/tmp/paper_factor.py",
            "universe": "US ETFs",
            "reviewed_source_sha256": SOURCE_DIGEST,
        },
        authority=authority,
        registry=_TimeoutRegistry(),
    )
    assert code == 1
    assert failed["error"] == {
        "code": "paper_research_platform_outcome_unknown",
        "message": "paper research operation did not advance exactly",
        "retryable": False,
    }


def test_completion_refuses_unreviewed_or_different_commit(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    # Unit-level guard for the exact status seam: a syntactically valid status
    # must still be the reviewed commit supplied by the human.
    status = {
        "promotion_id": PROMOTION_ID,
        "status": "awaiting_human_commit",
        "reviewed_commit": None,
        "reason": "uncommitted: worktree HEAD still equals base",
        "manifest_sha256": "a" * 64,
        "patch_sha256": "b" * 64,
        "candidate_id": "paper-factor",
        "candidate_digest": CANDIDATE_DIGEST,
        "final_backtest_receipt_id": FINAL_RECEIPT,
        "base_commit": BASE_COMMIT,
        "scoped_paths": ["one"],
    }
    observed = paper_research_cli._promotion_status(
        PROMOTION_ID,
        reader=lambda _promotion_id: (0, json.dumps(status)),
    )
    assert observed["reviewed_commit"] is None

    invalid = dict(status)
    invalid.pop("reason")
    with pytest.raises(
        paper_research_cli._OperationError,
        match="paper_research_promotion_status_invalid",
    ):
        paper_research_cli._promotion_status(
            PROMOTION_ID,
            reader=lambda _promotion_id: (0, json.dumps(invalid)),
        )


def test_subprocess_registry_uses_fixed_cli_and_strict_json_stdin(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel-must-not-cross")
    monkeypatch.setenv("FUTU_API_SECRET", "sentinel-must-not-cross")
    monkeypatch.setenv("DATABASE_URL", "sentinel-must-not-cross")
    monkeypatch.setenv(
        "HERMES_PLATFORM_COMMAND_ID",
        "sentinel-must-not-cross",
    )
    monkeypatch.setenv(
        "QS_DATABASE_URL",
        "postgresql://paper-registry@127.0.0.1/quantplatform",
    )
    monkeypatch.setenv("QS_DATABASE_ENABLED", "true")
    monkeypatch.setenv("QS_DATABASE_AUTO_MIGRATE", "true")
    executable = tmp_path / "fake-quant-system"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "assert sys.argv[1:] == ['hermes', 'paper-gate', 'register']\n"
        "for key in ('OPENAI_API_KEY', 'FUTU_API_SECRET', 'DATABASE_URL', "
        "'HERMES_PLATFORM_COMMAND_ID'):\n"
        "    assert key not in os.environ\n"
        "assert os.environ['QS_DATABASE_ENABLED'] == 'true'\n"
        "assert os.environ['QS_DATABASE_URL'] == "
        "'postgresql://paper-registry@127.0.0.1/quantplatform'\n"
        "assert os.environ['QS_DATABASE_AUTO_MIGRATE'] == 'false'\n"
        "request = json.load(sys.stdin)\n"
        "assert request['command_id'] == "
        f"{GATE1_COMMAND_ID!r}\n"
        "response = {\n"
        "  'contract': 'agent-v0.2-paper-gate-cli/v1',\n"
        "  'operation': 'register',\n"
        "  'ok': True,\n"
        "  'gate': {**request, 'status': 'pending'},\n"
        "}\n"
        "print(json.dumps(response, sort_keys=True, separators=(',', ':')))\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    registry = paper_research_cli.SubprocessPaperGateRegistry(
        executable=executable,
        cwd=tmp_path,
        timeout_seconds=2,
    )
    registration = paper_research_cli._registration(
        gate_id="paper-gate-subprocess",
        gate_kind="gate1",
        workspace_id=WORKSPACE_ID,
        task_ref="task:paper-subprocess",
        expected_task_version=7,
        platform_session_id=PLATFORM_SESSION_ID,
        attempt_ref="attempt:paper-subprocess-1",
        hqa_gate_ref="gate:paper-subprocess",
        command_id=GATE1_COMMAND_ID,
        hermes_run_id="hermes-run-subprocess",
        hermes_session_id=HERMES_SESSION_ID,
        hqa_run_ref=None,
        parent_gate_id=None,
        source_file_ref="/tmp/paper.py",
        universe="US ETFs",
        reviewed_source_sha256=SOURCE_DIGEST,
        gate1_confirmation_id=None,
        candidate_id=None,
        expected_digest=None,
        expected_status=None,
        final_backtest_receipt_id=None,
        base_commit=None,
    )
    assert registry.register(registration) == {
        **registration,
        "status": "pending",
    }
