from __future__ import annotations

from typing import Any

REQUIRED_ENVELOPE_KEYS = ("per_order_max_notional", "symbol_whitelist", "daily_loss_cap")


def check_strategy(cfg: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []

    def add(criterion: str, passed: bool, detail: str) -> None:
        results.append({"criterion": criterion, "passed": passed, "detail": detail})

    has_baseline = bool(cfg.get("backtest_run_id")) or ("sharpe" in cfg)
    add("backtest_baseline", has_baseline, "needs backtest_run_id or sharpe")

    envelope = cfg.get("risk_envelope") or {}
    missing = [k for k in REQUIRED_ENVELOPE_KEYS if k not in envelope]
    add("risk_envelope", not missing, f"missing: {missing}" if missing else "ok")

    add("kill_switch_hook", cfg.get("kill_switch_enabled") is True, "needs kill_switch_enabled=true")
    add("review_hook", cfg.get("review_on_drawdown") is True, "needs review_on_drawdown=true")
    add("paper_month", cfg.get("paper_days_completed", 0) >= 30, "needs paper_days_completed >= 30 (D-21)")

    passed = all(r["passed"] for r in results)
    return passed, results
