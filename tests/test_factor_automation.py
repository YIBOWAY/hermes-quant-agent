from __future__ import annotations

from pathlib import Path

import pytest

from hqa.factor_automation import (
    CandidateReceipt,
    FactorAutomationDisabled,
    FactorAutomationError,
    FactorAutomationRequest,
    FinalBacktestReceipt,
    MachineApprovalReceipt,
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
