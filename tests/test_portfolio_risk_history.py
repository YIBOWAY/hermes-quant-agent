from __future__ import annotations

import json

import pytest

from hqa import portfolio_risk
from tests.test_historical_risk import _closes, _payload
from tests.test_portfolio_risk import _position, _snapshot


def _history_payload() -> dict:
    returns = [0.01 if index % 2 else -0.005 for index in range(60)]
    payload = _payload(
        {
            "AAPL": _closes([1.5 * value for value in returns]),
            "SPY": _closes(returns),
        }
    )
    payload["start"] = "2025-06-04"
    payload["end"] = "2026-07-09"
    return payload


def test_invested_run_adds_v2_history_once_and_keeps_one_artifact(tmp_path) -> None:
    snapshot = _snapshot([_position("AAPL", 10_000.0)], cash=90_000.0)
    history = _history_payload()
    history_calls = []
    log_path = tmp_path / "portfolio_risk.jsonl"

    def run_history(symbols, start, end):
        history_calls.append((symbols, start, end))
        return 0, json.dumps(history)

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-11T00:05:00+08:00",
        log_path,
        run_history=run_history,
    )
    rows = log_path.read_text(encoding="utf-8").splitlines()
    artifact = json.loads(rows[0])

    assert len(rows) == 1
    assert history_calls == [(["AAPL", "SPY"], "2025-06-04", "2026-07-09")]
    assert artifact["schema_version"] == "2.0"
    assert artifact["status"] == "available"
    assert artifact["exposure"]["gross_value"] == pytest.approx(10_000.0)
    assert artifact["history_source"]["provider"] == "futu"
    assert artifact["historical_risk"]["status"] == "available"
    assert artifact["historical_risk"]["betas"][0]["value"] == pytest.approx(1.5)
    assert "historical_risk_metrics_not_computed" not in artifact["limitations"]
    assert "current_snapshot_only" not in artifact["limitations"]
    assert "current_exposure_uses_single_snapshot" in artifact["limitations"]
    assert "60 aligned daily returns" in report
    assert "Beta vs SPY: AAPL 1.50" in report
    assert "not forecasts or trading recommendations" in report


@pytest.mark.parametrize(
    "snapshot",
    [
        _snapshot(account_exists=False),
        _snapshot(),
    ],
)
def test_missing_and_cash_only_never_call_history(snapshot, tmp_path) -> None:
    history_calls = []
    log_path = tmp_path / "portfolio_risk.jsonl"

    portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-11T00:05:00+08:00",
        log_path,
        run_history=lambda *args: history_calls.append(args) or (0, "unexpected"),
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert history_calls == []
    assert artifact["schema_version"] == "2.0"
    assert artifact["historical_risk"]["status"] == "not_applicable"


def test_history_failure_degrades_but_preserves_current_snapshot_facts(tmp_path) -> None:
    snapshot = _snapshot([_position("AAPL", 10_000.0)], cash=90_000.0)
    error = {
        "error": {
            "code": "historical_prices_provider_error",
            "provider": "futu",
            "provider_code": "opend_unavailable",
            "message": "Futu OpenD is unavailable",
        }
    }
    log_path = tmp_path / "portfolio_risk.jsonl"

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-11T00:05:00+08:00",
        log_path,
        run_history=lambda *_args: (1, json.dumps(error)),
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert artifact["status"] == "degraded"
    assert artifact["exposure"]["gross_value"] == pytest.approx(10_000.0)
    assert artifact["history_source"]["status"] == "unavailable"
    assert artifact["history_source"]["error"] == error["error"]
    assert artifact["historical_risk"]["status"] == "unavailable"
    assert "historical_prices_provider_error" in artifact["reason_codes"]
    assert "Futu OpenD is unavailable" in report
    assert "No sample, cached-local, Tiingo, or Longbridge data was substituted" in report


def test_invalid_history_json_degrades_without_becoming_account_unavailable(
    tmp_path,
) -> None:
    snapshot = _snapshot([_position("AAPL", 10_000.0)], cash=90_000.0)
    log_path = tmp_path / "portfolio_risk.jsonl"

    portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-11T00:05:00+08:00",
        log_path,
        run_history=lambda *_args: (0, "not-json"),
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert artifact["status"] == "degraded"
    assert artifact["account"]["account_exists"] is True
    assert artifact["historical_risk"]["status"] == "unavailable"
    assert artifact["history_source"]["error"]["code"] == (
        "historical_prices_snapshot_invalid"
    )


def test_invalid_minimum_is_rejected_before_calling_history_provider(tmp_path) -> None:
    snapshot = _snapshot([_position("AAPL", 10_000.0)], cash=90_000.0)
    history_calls = []
    log_path = tmp_path / "portfolio_risk.jsonl"

    portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-11T00:05:00+08:00",
        log_path,
        run_history=lambda *args: history_calls.append(args) or (0, "unexpected"),
        minimum_aligned_returns=1,
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert history_calls == []
    assert artifact["status"] == "degraded"
    assert artifact["exposure"]["gross_value"] == pytest.approx(10_000.0)
    assert artifact["historical_risk"]["status"] == "unavailable"
    assert artifact["historical_risk"]["reason"] == (
        "historical_risk_invalid_configuration"
    )


def _provider_error(provider: str = "futu", message: str = "network interrupted") -> dict:
    return {
        "error": {
            "code": "historical_prices_provider_error",
            "provider": provider,
            "provider_code": "provider_query_failed",
            "message": message,
        }
    }


def test_primary_retry_recovers_transient_failure_without_fallback(tmp_path) -> None:
    snapshot = _snapshot([_position("AAPL", 10_000.0)], cash=90_000.0)
    history = _history_payload()
    calls: list[tuple] = []
    sleeps: list[float] = []
    log_path = tmp_path / "portfolio_risk.jsonl"

    def flaky_history(symbols, start, end):
        calls.append((symbols, start, end))
        if len(calls) == 1:
            return 1, json.dumps(_provider_error())
        return 0, json.dumps(history)

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-11T00:05:00+08:00",
        log_path,
        run_history=flaky_history,
        history_retry_sleep=sleeps.append,
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert len(calls) == 2
    assert sleeps == [2.0]
    assert artifact["status"] == "available"
    assert artifact["history_source"]["provider"] == "futu"
    assert "fallback" not in artifact["history_source"]
    assert "history_provider_fallback_used" not in artifact["reason_codes"]
    assert "Historical source: Futu QFQ daily" in report


def test_fallback_serves_history_with_explicit_provenance(tmp_path) -> None:
    snapshot = _snapshot([_position("AAPL", 10_000.0)], cash=90_000.0)
    tiingo_history = _history_payload()
    tiingo_history["provider"] = "tiingo"
    tiingo_history["source"] = "tiingo"
    fallback_calls: list[tuple] = []
    log_path = tmp_path / "portfolio_risk.jsonl"

    def failing_futu(_symbols, _start, _end):
        return 1, json.dumps(_provider_error(message="Futu request failed: 网络中断"))

    def tiingo_history_runner(symbols, start, end):
        fallback_calls.append((symbols, start, end))
        return 0, json.dumps(tiingo_history)

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-11T00:05:00+08:00",
        log_path,
        run_history=failing_futu,
        run_history_fallback=tiingo_history_runner,
        history_fallback_provider="tiingo",
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert fallback_calls == [(["AAPL", "SPY"], "2025-06-04", "2026-07-09")]
    assert artifact["status"] == "available"
    assert artifact["history_source"]["provider"] == "tiingo"
    assert artifact["history_source"]["source"] == "tiingo"
    fallback = artifact["history_source"]["fallback"]
    assert fallback["primary_provider"] == "futu"
    assert fallback["primary_error"]["code"] == "historical_prices_provider_error"
    assert "history_provider_fallback_used" in artifact["reason_codes"]
    assert "history_from_fallback_provider_tiingo" in artifact["limitations"]
    assert artifact["historical_risk"]["status"] == "available"
    assert "Historical source: Tiingo QFQ daily" in report
    assert "Tiingo data was substituted with explicit provenance" in report


def test_fallback_failure_keeps_honest_degrade_with_both_receipts(tmp_path) -> None:
    snapshot = _snapshot([_position("AAPL", 10_000.0)], cash=90_000.0)
    log_path = tmp_path / "portfolio_risk.jsonl"

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-11T00:05:00+08:00",
        log_path,
        run_history=lambda *_args: (1, json.dumps(_provider_error())),
        run_history_fallback=lambda *_args: (
            1,
            json.dumps(_provider_error(provider="tiingo", message="tiingo 401")),
        ),
        history_fallback_provider="tiingo",
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert artifact["status"] == "degraded"
    assert artifact["history_source"]["error"]["provider"] == "futu"
    assert artifact["history_source"]["fallback_error"]["provider"] == "tiingo"
    assert "historical_prices_provider_error" in artifact["reason_codes"]
    assert "history_fallback_failed" in artifact["reason_codes"]
    assert "Tiingo fallback also failed" in report
    assert "no data was substituted" in report


def test_report_explains_unavailable_beta_reason(tmp_path) -> None:
    snapshot = _snapshot([_position("AAPL", 10_000.0)], cash=90_000.0)
    history = _history_payload()
    spy = next(row for row in history["series"] if row["symbol"] == "SPY")
    for row in spy["rows"]:
        row["close"] = 100.0

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-11T00:05:00+08:00",
        tmp_path / "portfolio_risk.jsonl",
        run_history=lambda *_args: (0, json.dumps(history)),
    )

    assert "Beta unavailable vs SPY: AAPL (benchmark_zero_variance)." in report
