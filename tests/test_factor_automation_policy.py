from __future__ import annotations

import json
from pathlib import Path

import pytest

from hqa.factor_automation_policy import (
    FactorAutomationEvidence,
    FactorAutomationPolicyError,
    evaluate_factor_automation_policy,
    load_factor_automation_policy,
)


def _policy_path() -> Path:
    return Path(__file__).parents[1] / "config" / "factor_automation_policy.v1.json"


def test_committed_policy_is_strict_versioned_and_content_addressed() -> None:
    loaded = load_factor_automation_policy(_policy_path())

    assert loaded.policy.schema_version == "hqa.factor_automation_policy/v1"
    assert loaded.policy.default_universe == ("SPY", "QQQ")
    assert set(loaded.policy.default_universe) <= set(
        loaded.policy.universe_allowlist
    )
    assert len(loaded.policy_digest) == 64


def test_policy_acceptance_binds_every_machine_review_input() -> None:
    loaded = load_factor_automation_policy(_policy_path())
    decision = evaluate_factor_automation_policy(
        loaded,
        FactorAutomationEvidence(
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

    assert decision.accepted is True
    assert decision.reasons == ()
    assert decision.policy_digest == loaded.policy_digest
    assert decision.universe == ("SPY", "QQQ")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("sample_rows", 100, "sample_rows_below_minimum"),
        ("out_of_sample_rows", 10, "out_of_sample_rows_below_minimum"),
        ("data_coverage_ratio", 0.5, "data_coverage_below_minimum"),
        ("transaction_cost_bps", 0.0, "transaction_cost_assumption_too_low"),
        ("max_drawdown", -0.5, "max_drawdown_exceeded"),
        ("turnover", 20.0, "turnover_exceeded"),
        ("lookahead_static_check_passed", False, "lookahead_static_check_failed"),
    ],
)
def test_policy_fails_closed_on_each_required_metric(
    field: str,
    value: object,
    reason: str,
) -> None:
    loaded = load_factor_automation_policy(_policy_path())
    values = {
        "universe": ("SPY", "QQQ"),
        "sample_rows": 756,
        "out_of_sample_rows": 126,
        "data_coverage_ratio": 0.995,
        "transaction_cost_bps": 10.0,
        "max_drawdown": -0.12,
        "turnover": 1.2,
        "lookahead_static_check_passed": True,
    }
    values[field] = value

    decision = evaluate_factor_automation_policy(
        loaded,
        FactorAutomationEvidence(**values),
    )

    assert decision.accepted is False
    assert reason in decision.reasons


def test_policy_rejects_unpersisted_universe_and_schema_drift(tmp_path: Path) -> None:
    loaded = load_factor_automation_policy(_policy_path())
    decision = evaluate_factor_automation_policy(
        loaded,
        FactorAutomationEvidence(
            universe=("SPY", "MADE_UP"),
            sample_rows=756,
            out_of_sample_rows=126,
            data_coverage_ratio=1.0,
            transaction_cost_bps=10.0,
            max_drawdown=-0.1,
            turnover=1.0,
            lookahead_static_check_passed=True,
        ),
    )
    assert decision.accepted is False
    assert "universe_not_allowlisted" in decision.reasons

    drifted = json.loads(_policy_path().read_text(encoding="utf-8"))
    drifted["unexpected"] = True
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(drifted), encoding="utf-8")
    with pytest.raises(FactorAutomationPolicyError, match="schema"):
        load_factor_automation_policy(path)
