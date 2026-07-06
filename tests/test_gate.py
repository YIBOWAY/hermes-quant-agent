from __future__ import annotations

from hqa import gate

GOOD = {
    "backtest_run_id": "bt-123",
    "risk_envelope": {"per_order_max_notional": 1000, "symbol_whitelist": ["NVDA"], "daily_loss_cap": 200},
    "kill_switch_enabled": True,
    "review_on_drawdown": True,
    "paper_days_completed": 30,
}


def test_check_strategy_all_pass():
    passed, results = gate.check_strategy(GOOD)
    assert passed is True
    assert all(r["passed"] for r in results)
    assert len(results) == 5
    assert {r["criterion"] for r in results} == {
        "backtest_baseline", "risk_envelope", "kill_switch_hook", "review_hook", "paper_month",
    }


def test_check_strategy_missing_envelope_key_fails():
    cfg = dict(GOOD, risk_envelope={"per_order_max_notional": 1000})
    passed, results = gate.check_strategy(cfg)
    assert passed is False
    env = next(r for r in results if r["criterion"] == "risk_envelope")
    assert env["passed"] is False
    assert "symbol_whitelist" in env["detail"]


def test_check_strategy_missing_hooks_fail():
    cfg = dict(GOOD, kill_switch_enabled=False, review_on_drawdown=False)
    passed, results = gate.check_strategy(cfg)
    assert passed is False
    failed = {r["criterion"] for r in results if not r["passed"]}
    assert failed == {"kill_switch_hook", "review_hook"}


def test_check_strategy_paper_days_exactly_30_passes():
    passed, results = gate.check_strategy(dict(GOOD, paper_days_completed=30))
    assert passed is True
    pm = next(r for r in results if r["criterion"] == "paper_month")
    assert pm["passed"] is True


def test_check_strategy_paper_days_29_fails():
    cfg = dict(GOOD, paper_days_completed=29)
    passed, results = gate.check_strategy(cfg)
    assert passed is False
    pm = next(r for r in results if r["criterion"] == "paper_month")
    assert pm["passed"] is False
    assert "30" in pm["detail"]


def test_check_strategy_paper_days_absent_fails():
    cfg = dict(GOOD)
    del cfg["paper_days_completed"]
    passed, results = gate.check_strategy(cfg)
    assert passed is False
    pm = next(r for r in results if r["criterion"] == "paper_month")
    assert pm["passed"] is False
