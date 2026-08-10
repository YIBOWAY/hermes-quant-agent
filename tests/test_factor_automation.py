from __future__ import annotations

from pathlib import Path

import pytest

from hqa.factor_automation import (
    AutomaticPaperLandResult,
    CandidateReceipt,
    FactorAutomationDisabled,
    FactorAutomationError,
    FactorAutomationRequest,
    FinalBacktestReceipt,
    MachineApprovalReceipt,
    PlatformFactorAutomationSlice2Port,
    run_to_paper_land,
    run_to_final_backtest,
)
from hqa.factor_automation_policy import (
    FactorAutomationEvidence,
    load_factor_automation_policy,
)


def _policy():
    return load_factor_automation_policy(
        Path(__file__).parents[1] / "config" / "factor_automation_policy.v1.json"
    )


def test_automation_gate1_authority_is_separate_from_human_gate() -> None:
    from hqa import config

    assert config.FACTOR_AUTOMATION_GATE1_DIR != config.FACTOR_GATE1_DIR


def _request(tmp_path: Path) -> FactorAutomationRequest:
    return FactorAutomationRequest(
        automation_id="automation-0123456789abcdef",
        intake_receipt_id="paper-intake-receipt:sha256:" + ("a" * 64),
        intake_contract_digest="b" * 64,
        source_file_ref=str(tmp_path / "factor.py"),
        source_sha256="c" * 64,
        goal="reproduce exact paper factor",
        universe=("SPY", "QQQ"),
        provider="futu",
        start="2021-01-01",
        end="2025-12-31",
        policy_evidence=FactorAutomationEvidence(
            universe=("SPY", "QQQ"),
            sample_rows=756,
            out_of_sample_rows=126,
            data_coverage_ratio=0.995,
            transaction_cost_bps=10.0,
            max_drawdown=-0.12,
            turnover=1.2,
            lookahead_static_check_passed=True,
        ),
    )


class _Port:
    def __init__(self, request: FactorAutomationRequest, policy_digest: str) -> None:
        self.request = request
        self.policy_digest = policy_digest
        self.calls: list[str] = []
        self.drift_final = False

    def propose(self, request: FactorAutomationRequest) -> CandidateReceipt:
        self.calls.append("propose")
        assert request == self.request
        return CandidateReceipt(
            candidate_id="candidate-1",
            manifest_digest="d" * 64,
            source_sha256=request.source_sha256,
            status="pending",
        )

    def machine_approve(
        self,
        *,
        candidate_id: str,
        expected_manifest_digest: str,
        policy_digest: str,
        note: str,
    ) -> MachineApprovalReceipt:
        self.calls.append("machine_approve")
        assert note.startswith("auto:")
        assert policy_digest == self.policy_digest
        return MachineApprovalReceipt(
            candidate_id=candidate_id,
            manifest_digest=expected_manifest_digest,
            reviewer="auto",
            registration="auto_promote",
            policy_digest=policy_digest,
            intake_contract_digest=self.request.intake_contract_digest,
            status="approved",
        )

    def final_backtest(
        self,
        *,
        request: FactorAutomationRequest,
        candidate: CandidateReceipt,
        approval: MachineApprovalReceipt,
    ) -> FinalBacktestReceipt:
        self.calls.append("final_backtest")
        return FinalBacktestReceipt(
            receipt_id="backtest-" + ("e" * 32),
            candidate_id=candidate.candidate_id,
            manifest_digest=("f" * 64 if self.drift_final else candidate.manifest_digest),
            source_sha256=request.source_sha256,
            intake_receipt_id=request.intake_receipt_id,
            policy_digest=approval.policy_digest,
            provider=request.provider,
            final=True,
        )


def test_slice2_machine_approval_fixture_is_disabled_by_default(tmp_path: Path) -> None:
    request = _request(tmp_path)
    port = _Port(request, _policy().policy_digest)

    with pytest.raises(FactorAutomationDisabled):
        run_to_final_backtest(request=request, policy=_policy(), port=port)

    assert port.calls == []


def test_slice2_repeatable_pipeline_stops_at_exact_final_receipt(tmp_path: Path) -> None:
    request = _request(tmp_path)
    loaded = _policy()
    port = _Port(request, loaded.policy_digest)

    result = run_to_final_backtest(
        request=request,
        policy=loaded,
        port=port,
        allow_acceptance_machine_approval=True,
    )

    assert port.calls == ["propose", "machine_approve", "final_backtest"]
    assert result.state == "final_backtest_ready"
    assert result.promotion_performed is False
    assert result.candidate.status == "pending"
    assert result.approval.reviewer == "auto"
    assert result.final_backtest.final is True
    assert result.policy_decision.accepted is True


def test_platform_port_records_machine_gate1_and_exact_platform_lineage(tmp_path: Path) -> None:
    loaded = _policy()
    source = tmp_path / "generated.py"
    source.write_text(
        "from quant_system.factors.base import BaseFactor\n"
        "class ExactFactor(BaseFactor):\n"
        "    factor_id = 'exact_factor'\n",
        encoding="utf-8",
    )
    import hashlib
    request = FactorAutomationRequest(
        **{
            **_request(tmp_path).__dict__,
            "source_file_ref": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    )
    seen: list[tuple[str, object]] = []

    def propose(goal, staged, universe):
        seen.append(("propose", (goal, staged, universe)))
        return 0, (
            '{"candidate_id":"candidate-1","manifest_digest":"'
            + ("d" * 64)
            + '","source_sha256":"'
            + request.source_sha256
            + '","status":"pending"}\n'
        )

    def approve(**kwargs):
        seen.append(("approve", kwargs))
        return 0, (
            '{"candidate_id":"candidate-1","decision":"approve",'
            '"registration":"auto_promote","manifest_digest":"'
            + ("d" * 64)
            + '","reviewer":"auto","policy_digest":"'
            + loaded.policy_digest
            + '","intake_contract_digest":"'
            + request.intake_contract_digest
            + '"}\n'
        )

    def backtest(_argv):
        seen.append(("backtest", tuple(_argv)))
        return 0, "final_backtest_receipt=backtest-" + ("e" * 32) + "\n"

    def verify_final(**kwargs):
        seen.append(("verify_final", kwargs))
        return {"factor_id": "exact_factor"}

    port = PlatformFactorAutomationSlice2Port(
        policy_digest=loaded.policy_digest,
        gate_dir=tmp_path / "gate1",
        experiment_output_dir=tmp_path / "experiments",
        propose_runner=propose,
        auto_review_runner=approve,
        backtest_runner=backtest,
        final_receipt_verifier=verify_final,
    )
    result = run_to_final_backtest(
        request=request,
        policy=loaded,
        port=port,
        allow_acceptance_machine_approval=True,
    )

    assert result.state == "final_backtest_ready"
    assert [name for name, _ in seen] == [
        "propose",
        "approve",
        "backtest",
        "verify_final",
    ]
    automation_gate = tmp_path / "gate1" / request.automation_id
    assert any((automation_gate / "bindings").glob("binding-*.json"))

    def refuse_duplicate_propose(*_args):
        raise AssertionError("crash recovery must reuse the exact candidate")

    resumed = PlatformFactorAutomationSlice2Port(
        policy_digest=loaded.policy_digest,
        gate_dir=tmp_path / "gate1",
        experiment_output_dir=tmp_path / "experiments",
        propose_runner=refuse_duplicate_propose,
        auto_review_runner=approve,
        backtest_runner=backtest,
        final_receipt_verifier=verify_final,
    ).propose(request)
    assert resumed == result.candidate


class _PromotionPort:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def prepare_commit_land(self, **kwargs) -> AutomaticPaperLandResult:
        self.calls.append("prepare_commit_land")
        return AutomaticPaperLandResult(
            state="landed",
            promotion_id="promo-" + ("a" * 32),
            base_commit="b" * 40,
            reviewed_commit="c" * 40,
            local_head="c" * 40,
            pushed=False,
            promotion_scope="paper_only",
        )


def test_full_paper_land_requires_both_hqa_flags_before_slice2_mutation(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    loaded = _policy()
    slice2 = _Port(request, loaded.policy_digest)
    promotion = _PromotionPort()

    with pytest.raises(FactorAutomationDisabled):
        run_to_paper_land(
            request=request,
            policy=loaded,
            slice2_port=slice2,
            promotion_port=promotion,
            base_commit="b" * 40,
            hqa_mode_enabled=True,
            hqa_auto_land_enabled=False,
        )

    assert slice2.calls == []
    assert promotion.calls == []


def test_full_paper_land_is_two_phase_and_never_pushes(tmp_path: Path) -> None:
    request = _request(tmp_path)
    loaded = _policy()
    slice2 = _Port(request, loaded.policy_digest)
    promotion = _PromotionPort()

    result = run_to_paper_land(
        request=request,
        policy=loaded,
        slice2_port=slice2,
        promotion_port=promotion,
        base_commit="b" * 40,
        hqa_mode_enabled=True,
        hqa_auto_land_enabled=True,
    )

    assert result.land.state == "landed"
    assert result.land.pushed is False
    assert result.land.promotion_scope == "paper_only"
    assert slice2.calls == ["propose", "machine_approve", "final_backtest"]
    assert promotion.calls == ["prepare_commit_land"]


def test_pipeline_policy_failure_makes_no_candidate_mutation(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request = FactorAutomationRequest(
        **{
            **request.__dict__,
            "policy_evidence": FactorAutomationEvidence(
                **{
                    **request.policy_evidence.__dict__,
                    "lookahead_static_check_passed": False,
                }
            ),
        }
    )
    loaded = _policy()
    port = _Port(request, loaded.policy_digest)

    with pytest.raises(FactorAutomationError, match="policy_refused"):
        run_to_final_backtest(
            request=request,
            policy=loaded,
            port=port,
            allow_acceptance_machine_approval=True,
        )

    assert port.calls == []


def test_pipeline_rejects_final_receipt_lineage_drift(tmp_path: Path) -> None:
    request = _request(tmp_path)
    loaded = _policy()
    port = _Port(request, loaded.policy_digest)
    port.drift_final = True

    with pytest.raises(FactorAutomationError, match="final_backtest_receipt_drift"):
        run_to_final_backtest(
            request=request,
            policy=loaded,
            port=port,
            allow_acceptance_machine_approval=True,
        )
