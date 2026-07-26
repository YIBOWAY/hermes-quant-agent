from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys

from hqa import paper_gate_cli
from hqa.workflow_authority import WorkflowAuthority
from hqa.workflow_contract import (
    CompleteAttempt,
    ConfirmPlan,
    ObserveProviderEvidence,
    ObserveRun,
    ObserveSubmission,
    ProposePlan,
    RequestPlanConfirmation,
    StartResearch,
)

MANAGED_SESSION_REF = "session:managed"


class _ConfirmFormulaAuthority:
    def __init__(self, *, replayed: bool = False) -> None:
        self.command = None
        self.commands = []
        self.replayed = replayed

    def snapshot(self, task_ref: str):
        assert task_ref == "task:paper-task-1"
        return type(
            "Snapshot",
            (),
            {
                "managed_session_ref": MANAGED_SESSION_REF,
                "version": 7,
            },
        )()

    def apply(self, command):
        self.command = command
        self.commands.append(command)
        return type(
            "Receipt",
            (),
            {
                "operation_id": command.operation_id,
                "operation_digest": "a" * 64,
                "event_id": "event:" + "b" * 64,
                "task_ref": command.task_ref,
                "task_version": 7 + len(self.commands),
                "attempt_ref": "attempt:paper-attempt-2",
                "replayed": self.replayed,
            },
        )()


def test_confirm_formula_writes_exact_workflow_authority_fact(
    monkeypatch, capsys
) -> None:
    authority = _ConfirmFormulaAuthority()
    prepare_calls = []

    def prepare(**kwargs):
        prepare_calls.append(kwargs)
        return ("gate1-" + "c" * 32, "1" * 64, "/sealed/source.py")

    request = {
        "managed_session_ref": MANAGED_SESSION_REF,
        "operation_id": "gate1-action-1",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 7,
        "gate_ref": "gate:paper-gate-1",
        "reviewed_source_digest": "1" * 64,
        "confirmation_note": "I reviewed the exact source bytes.",
        "source_file": "/hqa/source/reversal.py",
        "universe": "US ETFs",
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    assert (
        paper_gate_cli.main(
            ["confirm-formula"],
            authority_factory=lambda: authority,
            gate1_preparer=prepare,
        )
        == 0
    )

    assert prepare_calls == [
        {
            "confirmation_note": request["confirmation_note"],
            "expected_source_digest": request["reviewed_source_digest"],
            "gate_dir": paper_gate_cli.config.FACTOR_GATE1_DIR,
            "goal": request["task_ref"],
            "source_file": request["source_file"],
            "universe": request["universe"],
        }
    ]
    assert authority.command is not None
    assert authority.command.task_ref == request["task_ref"]
    assert authority.command.expected_version == 7
    assert authority.command.gate_ref == request["gate_ref"]
    assert authority.command.reviewed_source_digest == request["reviewed_source_digest"]
    assert authority.command.confirmation_note == request["confirmation_note"]
    workflow_operation_id = authority.command.operation_id
    assert workflow_operation_id.startswith("paper-gate1-confirm-")
    assert request["operation_id"] not in workflow_operation_id
    document = json.loads(capsys.readouterr().out)
    assert document == {
        "attempt_ref": "attempt:paper-attempt-2",
        "event_id": "event:" + "b" * 64,
        "gate_ref": "gate:paper-gate-1",
        "gate1_confirmation_id": "gate1-" + "c" * 32,
        "hqa_receipt_digest": hashlib.sha256(
            json.dumps(
                {
                    "attempt_ref": "attempt:paper-attempt-2",
                    "event_id": "event:" + "b" * 64,
                    "gate_ref": "gate:paper-gate-1",
                    "gate1_confirmation_id": "gate1-" + "c" * 32,
                    "managed_session_ref": MANAGED_SESSION_REF,
                    "operation_digest": "a" * 64,
                    "operation_id": "gate1-action-1",
                    "replayed": False,
                    "reviewed_source_digest": "1" * 64,
                    "staged_source_ref": "/sealed/source.py",
                    "task_ref": "task:paper-task-1",
                    "task_version": 8,
                    "workflow_operation_id": workflow_operation_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "hqa_receipt_ref": "hqa-paper-gate:gate1-action-1",
        "managed_session_ref": MANAGED_SESSION_REF,
        "ok": True,
        "operation_digest": "a" * 64,
        "operation_id": "gate1-action-1",
        "replayed": False,
        "reviewed_source_digest": "1" * 64,
        "staged_source_ref": "/sealed/source.py",
        "task_ref": "task:paper-task-1",
        "task_version": 8,
        "workflow_operation_id": workflow_operation_id,
    }


def test_confirm_formula_rejects_source_digest_mismatch_before_workflow_write(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    source = tmp_path / "factor.py"
    source.write_text("class ExactFactor:\\n    pass\\n", encoding="utf-8")
    authority = _ConfirmFormulaAuthority()
    request = {
        "managed_session_ref": MANAGED_SESSION_REF,
        "operation_id": "gate1-action-mismatch",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 7,
        "gate_ref": "gate:paper-gate-mismatch",
        "reviewed_source_digest": "0" * 64,
        "confirmation_note": "Reviewed bytes.",
        "source_file": str(source),
        "universe": "US ETFs",
    }
    monkeypatch.setattr(paper_gate_cli.config, "FACTOR_GATE1_DIR", tmp_path / "gate1")
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    assert (
        paper_gate_cli.main(
            ["confirm-formula"],
            authority_factory=lambda: authority,
        )
        == 2
    )

    assert authority.command is None
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "paper_gate_invalid_request"


def test_managed_session_substitution_is_rejected_before_gate1_side_effect(
    monkeypatch,
    capsys,
) -> None:
    authority = _ConfirmFormulaAuthority()
    prepare_calls: list[dict[str, object]] = []
    request = {
        "managed_session_ref": "session:some-other-platform-session",
        "operation_id": "gate1-session-substitution",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 7,
        "gate_ref": "gate:paper-gate-1",
        "reviewed_source_digest": "1" * 64,
        "confirmation_note": "I reviewed the exact source bytes.",
        "source_file": "/hqa/source/reversal.py",
        "universe": "US ETFs",
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    def prepare(**kwargs):
        prepare_calls.append(kwargs)
        return ("gate1-" + "c" * 32, "1" * 64, "/sealed/source.py")

    assert (
        paper_gate_cli.main(
            ["confirm-formula"],
            authority_factory=lambda: authority,
            gate1_preparer=prepare,
        )
        == 2
    )
    assert prepare_calls == []
    assert authority.command is None
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "paper_gate_invalid_request"
    )


def test_approve_passes_human_cas_values_without_refetch(
    monkeypatch,
    capsys,
) -> None:
    calls: list[list[str]] = []
    authority = _ConfirmFormulaAuthority()
    binding_calls = []

    def factor_cli(argv):
        calls.append(list(argv))
        sys.stdout.write(
            json.dumps(
                {
                    "candidate_id": "factor-paper-1",
                    "decision": "approve",
                    "manifest_digest": "2" * 64,
                    "registration": "manual_required",
                }
            )
            + "\n"
        )
        return 0

    def check_candidate_binding(**kwargs):
        binding_calls.append(kwargs)

    request = {
        "managed_session_ref": MANAGED_SESSION_REF,
        "operation_id": "gate2-action-1",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 7,
        "gate_ref": "gate:paper-gate-1",
        "gate1_confirmation_id": "gate1-" + "a" * 32,
        "reviewed_source_digest": "1" * 64,
        "candidate_id": "factor-paper-1",
        "expected_digest": "2" * 64,
        "expected_status": "pending",
        "note": "Reviewed exact candidate source.",
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    assert (
        paper_gate_cli.main(
            ["approve"],
            authority_factory=lambda: authority,
            candidate_binding_checker=check_candidate_binding,
            factor_cli_main=factor_cli,
        )
        == 0
    )

    assert binding_calls == [
        {
            "candidate_id": "factor-paper-1",
            "confirmation_id": "gate1-" + "a" * 32,
            "gate_dir": paper_gate_cli.config.FACTOR_GATE1_DIR,
            "manifest_digest": "2" * 64,
            "source_digest": "1" * 64,
        }
    ]
    assert authority.command is not None
    assert authority.command.operation_id.startswith("paper-gate2-bind-")
    assert request["operation_id"] not in authority.command.operation_id
    assert authority.command.task_ref == "task:paper-task-1"
    assert authority.command.expected_version == 7
    assert authority.command.gate_ref == "gate:paper-gate-1"
    assert authority.command.candidate_ref == "candidate:factor-paper-1"
    assert authority.command.manifest_digest == "2" * 64
    assert calls == [
        [
            "approve",
            "--candidate-id",
            "factor-paper-1",
            "--expected-digest",
            "2" * 64,
            "--expected-status",
            "pending",
            "--note",
            "Reviewed exact candidate source.",
        ]
    ]
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is True
    assert document["operation_id"] == "gate2-action-1"
    assert document["candidate_id"] == "factor-paper-1"
    assert document["candidate_digest"] == "2" * 64
    assert document["decision"] == "approve"
    assert document["gate1_confirmation_id"] == "gate1-" + "a" * 32
    assert document["gate_ref"] == "gate:paper-gate-1"
    assert document["managed_session_ref"] == MANAGED_SESSION_REF
    assert document["attempt_ref"] == "attempt:paper-attempt-2"
    assert document["task_version"] == 8
    assert document["hqa_receipt_ref"] == "hqa-paper-gate:gate2-action-1"
    assert document["workflow_operation_id"] == authority.command.operation_id
    assert len(document["hqa_receipt_digest"]) == 64
    assert "note" not in document


def test_promote_uses_exact_final_receipt_and_returns_prepare_only_receipt(
    monkeypatch,
    capsys,
) -> None:
    calls: list[list[str]] = []
    authority = _ConfirmFormulaAuthority()

    def factor_cli(argv):
        calls.append(list(argv))
        sys.stdout.write(
            json.dumps(
                {
                    "promotion_id": "promo-" + "a" * 32,
                    "worktree": "/tmp/gate3-worktree",
                    "patch": "/tmp/gate3.patch",
                    "manifest": "/tmp/gate3-manifest.json",
                }
            )
            + "\n"
        )
        return 0

    request = {
        "managed_session_ref": MANAGED_SESSION_REF,
        "operation_id": "gate3-action-1",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 7,
        "attempt_ref": "attempt:paper-attempt-2",
        "run_ref": "run:paper-research",
        "gate_ref": "gate:paper-gate-3",
        "candidate_id": "factor-paper-1",
        "expected_digest": "2" * 64,
        "final_backtest_receipt_id": "backtest-" + "3" * 32,
        "base_commit": "4" * 40,
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    assert (
        paper_gate_cli.main(
            ["promote"],
            authority_factory=lambda: authority,
            factor_cli_main=factor_cli,
        )
        == 0
    )

    assert len(authority.commands) == 2
    resolution, observation = authority.commands
    assert resolution.operation_id.startswith("paper-gate3-resolve-")
    assert request["operation_id"] not in resolution.operation_id
    assert resolution.task_ref == "task:paper-task-1"
    assert resolution.expected_version == 7
    assert resolution.attempt_ref == "attempt:paper-attempt-2"
    assert resolution.gate_ref == "gate:paper-gate-3"
    assert resolution.outcome == "passed"
    assert observation.operation_id.startswith("paper-gate3-observe-")
    assert request["operation_id"] not in observation.operation_id
    assert observation.task_ref == "task:paper-task-1"
    assert observation.expected_version == 8
    assert observation.attempt_ref == "attempt:paper-attempt-2"
    assert observation.run_ref == "run:paper-research"
    assert observation.gate_ref == "gate:paper-gate-3"
    assert observation.final_receipt_ref == "result:backtest-" + "3" * 32
    assert calls == [
        [
            "promote",
            "--candidate-id",
            "factor-paper-1",
            "--expected-digest",
            "2" * 64,
            "--final-backtest-receipt",
            "backtest-" + "3" * 32,
            "--base-commit",
            "4" * 40,
        ]
    ]
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is True
    assert document["operation_id"] == "gate3-action-1"
    assert document["candidate_id"] == "factor-paper-1"
    assert document["candidate_digest"] == "2" * 64
    assert document["final_backtest_receipt_id"] == "backtest-" + "3" * 32
    assert document["base_commit"] == "4" * 40
    assert document["attempt_ref"] == "attempt:paper-attempt-2"
    assert document["task_version"] == 9
    assert document["run_ref"] == "run:paper-research"
    assert document["gate_ref"] == "gate:paper-gate-3"
    assert document["managed_session_ref"] == MANAGED_SESSION_REF
    assert document["promotion_id"] == "promo-" + "a" * 32
    assert document["promotion_status"] == "awaiting_human_commit"
    assert document["human_git_commit_required"] is True
    assert document["auto_commit"] is False
    assert document["worktree"] == "/tmp/gate3-worktree"
    assert document["patch"] == "/tmp/gate3.patch"
    assert document["manifest"] == "/tmp/gate3-manifest.json"
    assert document["workflow_operation_id"] == observation.operation_id
    assert document["workflow_gate_resolution_event_id"] == ("event:" + "b" * 64)
    assert len(document["hqa_receipt_digest"]) == 64
    assert "completion_evidence" not in document
    assert "hqa_completion_receipt_ref" not in document
    assert "hqa_completion_receipt_digest" not in document


def test_approve_reconciles_exact_status_after_mutation_receipt_loss(
    monkeypatch,
    capsys,
) -> None:
    authority = _ConfirmFormulaAuthority(replayed=True)
    factor_calls: list[list[str]] = []
    reconcile_calls: list[dict[str, str]] = []

    def factor_cli(argv):
        factor_calls.append(list(argv))
        sys.stdout.write("not-json\n")
        return 0

    def reconcile(**kwargs):
        reconcile_calls.append(kwargs)
        return {
            "candidate_id": "factor-paper-1",
            "decision": "approve",
            "manifest_digest": "2" * 64,
            "registration": "manual_required",
        }

    request = {
        "managed_session_ref": MANAGED_SESSION_REF,
        "operation_id": "gate2-recovery-action",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 7,
        "gate_ref": "gate:paper-gate-1",
        "gate1_confirmation_id": "gate1-" + "a" * 32,
        "reviewed_source_digest": "1" * 64,
        "candidate_id": "factor-paper-1",
        "expected_digest": "2" * 64,
        "expected_status": "pending",
        "note": "Reviewed exact candidate source.",
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    assert (
        paper_gate_cli.main(
            ["approve"],
            authority_factory=lambda: authority,
            candidate_binding_checker=lambda **_kwargs: None,
            factor_cli_main=factor_cli,
            candidate_approval_reconciler=reconcile,
        )
        == 0
    )
    assert len(factor_calls) == 1
    assert reconcile_calls == [
        {
            "candidate_id": "factor-paper-1",
            "expected_digest": "2" * 64,
            "note": "Reviewed exact candidate source.",
        }
    ]
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is True
    assert document["replayed"] is True
    assert document["operation_id"] == "gate2-recovery-action"
    assert document["managed_session_ref"] == MANAGED_SESSION_REF
    assert (
        document["review_note_digest"]
        == hashlib.sha256(request["note"].encode("utf-8")).hexdigest()
    )


def test_candidate_approval_reconciliation_rejects_different_note(
    monkeypatch,
    tmp_path: Path,
) -> None:
    agent_root = tmp_path / "agent-output"
    candidate = agent_root / "agent" / "candidates" / "factor-paper-1"
    candidate.mkdir(parents=True)
    source = candidate / "factor.py.candidate"
    source.write_text("class Factor:\n    pass\n", encoding="utf-8")
    (candidate / "approved.lock").write_bytes(
        paper_gate_cli.factor_repro._canonical_bytes(
            {
                "schema_version": "1.0",
                "candidate_id": "factor-paper-1",
                "decision": "approve",
                "manifest_digest": "2" * 64,
                "note": "Original human note.",
                "reviewer": "manual",
                "created_at": "2026-07-24T00:00:00Z",
            }
        )
    )
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(agent_root))
    monkeypatch.setattr(
        paper_gate_cli.quant_cli,
        "run_inspect_factor_candidate",
        lambda *_args, **_kwargs: (
            0,
            json.dumps(
                {
                    "candidate_id": "factor-paper-1",
                    "manifest_digest": "2" * 64,
                    "approval_binding": "approved",
                    "source_path": str(source),
                }
            ),
        ),
    )

    try:
        paper_gate_cli._reconcile_exact_candidate_approval(
            candidate_id="factor-paper-1",
            expected_digest="2" * 64,
            note="Replacement note.",
        )
    except Exception as exc:
        assert type(exc).__name__ == "_PaperGateOperationError"
        assert exc.code == "paper_gate_outcome_unknown"
    else:
        raise AssertionError("different approval note must not reconcile")


def test_promote_reconciles_before_mutation_when_workflow_operation_replays(
    monkeypatch,
    capsys,
) -> None:
    authority = _ConfirmFormulaAuthority(replayed=True)
    reconcile_calls: list[dict[str, str]] = []

    def no_second_promotion(_argv):
        raise AssertionError("recovery must not prepare a second promotion")

    def reconcile(**kwargs):
        reconcile_calls.append(kwargs)
        return {
            "promotion_id": "promo-" + "a" * 32,
            "worktree": "/tmp/gate3-worktree",
            "patch": "/tmp/gate3.patch",
            "manifest": "/tmp/gate3-manifest.json",
        }

    request = {
        "managed_session_ref": MANAGED_SESSION_REF,
        "operation_id": "gate3-recovery-action",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 7,
        "attempt_ref": "attempt:paper-attempt-2",
        "run_ref": "run:paper-research",
        "gate_ref": "gate:immutable-domain-gate",
        "candidate_id": "factor-paper-1",
        "expected_digest": "2" * 64,
        "final_backtest_receipt_id": "backtest-" + "3" * 32,
        "base_commit": "4" * 40,
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    assert (
        paper_gate_cli.main(
            ["promote"],
            authority_factory=lambda: authority,
            factor_cli_main=no_second_promotion,
            promotion_reconciler=reconcile,
        )
        == 0
    )
    assert reconcile_calls == [
        {
            "base_commit": "4" * 40,
            "candidate_id": "factor-paper-1",
            "expected_digest": "2" * 64,
            "final_backtest_receipt_id": "backtest-" + "3" * 32,
        }
    ]
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is True
    assert document["replayed"] is True
    assert document["gate_ref"] == "gate:immutable-domain-gate"
    assert document["managed_session_ref"] == MANAGED_SESSION_REF


def test_stable_workflow_operation_ignores_outer_platform_action_id() -> None:
    binding = {
        "confirmation_note_digest": "a" * 64,
        "task_ref": "task:paper-task-1",
        "expected_task_version": 7,
        "gate_ref": "gate:immutable-gate",
        "gate1_confirmation_id": "gate1-" + "b" * 32,
        "managed_session_ref": MANAGED_SESSION_REF,
        "reviewed_source_digest": "c" * 64,
        "universe": "US ETFs",
    }
    first = paper_gate_cli._stable_workflow_operation_id(
        "gate1-confirm",
        binding,
    )
    second = paper_gate_cli._stable_workflow_operation_id(
        "gate1-confirm",
        dict(binding),
    )
    assert first == second
    assert first.startswith("paper-gate1-confirm-")
    for key, replacement in (
        ("gate1_confirmation_id", "gate1-" + "d" * 32),
        ("managed_session_ref", "session:managed-other"),
        ("universe", "Global equities"),
        ("reviewed_source_digest", "e" * 64),
        ("task_ref", "task:paper-task-2"),
    ):
        changed = dict(binding)
        changed[key] = replacement
        assert (
            paper_gate_cli._stable_workflow_operation_id(
                "gate1-confirm",
                changed,
            )
            != first
        )


def test_approve_rejects_unproven_candidate_before_any_mutation(
    monkeypatch,
    capsys,
) -> None:
    authority = _ConfirmFormulaAuthority()
    factor_calls: list[list[str]] = []

    def missing_binding(**_kwargs):
        raise ValueError("exact Gate 1 candidate binding missing")

    def factor_cli(argv):
        factor_calls.append(list(argv))
        return 0

    request = {
        "managed_session_ref": MANAGED_SESSION_REF,
        "operation_id": "gate2-unproven",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 7,
        "gate_ref": "gate:paper-gate-1",
        "gate1_confirmation_id": "gate1-" + "a" * 32,
        "reviewed_source_digest": "1" * 64,
        "candidate_id": "factor-unrelated",
        "expected_digest": "2" * 64,
        "expected_status": "pending",
        "note": "Review must not create provenance.",
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    assert (
        paper_gate_cli.main(
            ["approve"],
            authority_factory=lambda: authority,
            candidate_binding_checker=missing_binding,
            factor_cli_main=factor_cli,
        )
        == 2
    )
    assert authority.command is None
    assert factor_calls == []
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "paper_gate_invalid_request"
    )


def test_confirm_formula_real_authorities_need_no_provider(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(
        tmp_path / "workflow",
        "owner-paper-test",
        now=lambda: "2026-07-24T02:00:00.000000Z",
    )
    receipt = authority.apply(
        StartResearch(
            "paper-start",
            "workspace:local",
            "session:managed",
            "payload:sha256:" + "a" * 64,
            "2026-07-25T02:00:00.000000Z",
        )
    )
    assert receipt.attempt_ref is not None
    receipt = authority.apply(
        ObserveSubmission(
            "paper-submit",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "command:paper-plan",
        )
    )
    receipt = authority.apply(
        ObserveRun(
            "paper-run",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "command:paper-plan",
            "run:paper-plan",
        )
    )
    receipt = authority.apply(
        ObserveProviderEvidence(
            "paper-provider",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "run:paper-plan",
            "provider-evidence:paper-plan",
        )
    )
    receipt = authority.apply(
        ProposePlan(
            "paper-plan",
            receipt.task_ref,
            receipt.task_version,
            1,
            "b" * 64,
            "run:paper-plan",
            True,
        )
    )
    receipt = authority.apply(
        RequestPlanConfirmation(
            "paper-plan-request",
            receipt.task_ref,
            receipt.task_version,
            1,
            "b" * 64,
        )
    )
    receipt = authority.apply(
        CompleteAttempt(
            "paper-plan-complete",
            receipt.task_ref,
            receipt.task_version,
            receipt.attempt_ref,
            "completed",
            "run:paper-plan",
            "provider-evidence:paper-plan",
        )
    )
    receipt = authority.apply(
        ConfirmPlan(
            "paper-plan-confirm",
            receipt.task_ref,
            receipt.task_version,
            1,
            "b" * 64,
            "Reviewed exact plan.",
        )
    )
    source = tmp_path / "reversal.py"
    source.write_text("class ReversalFactor:\n    pass\n", encoding="utf-8")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(
        paper_gate_cli.config,
        "FACTOR_GATE1_DIR",
        tmp_path / "gate1",
    )
    request = {
        "managed_session_ref": MANAGED_SESSION_REF,
        "operation_id": "paper-real-gate1",
        "task_ref": receipt.task_ref,
        "expected_task_version": receipt.task_version,
        "gate_ref": "gate:paper-real",
        "reviewed_source_digest": source_digest,
        "confirmation_note": "I reviewed these exact bytes.",
        "source_file": str(source),
        "universe": "US ETFs",
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    assert (
        paper_gate_cli.main(
            ["confirm-formula"],
            authority_factory=lambda: authority,
        )
        == 0
    )
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is True
    assert document["reviewed_source_digest"] == source_digest
    assert document["gate1_confirmation_id"].startswith("gate1-")
    assert document["managed_session_ref"] == MANAGED_SESSION_REF
    assert Path(document["staged_source_ref"]).read_bytes() == source.read_bytes()
