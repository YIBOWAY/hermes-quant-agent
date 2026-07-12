from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from hqa import historical_risk


def _dates(count: int) -> list[str]:
    start = date(2026, 1, 1)
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def _closes(returns: list[float], initial: float = 100.0) -> list[float]:
    values = [initial]
    for value in returns:
        values.append(values[-1] * (1.0 + value))
    return values


def _payload(series_values: dict[str, list[float]]) -> dict:
    dates = _dates(max(len(values) for values in series_values.values()))
    series = []
    for symbol, values in series_values.items():
        rows = [
            {"date": dates[index], "close": close}
            for index, close in enumerate(values)
        ]
        series.append(
            {
                "symbol": symbol,
                "row_count": len(rows),
                "first_date": rows[0]["date"],
                "last_date": rows[-1]["date"],
                "rows": rows,
            }
        )
    return {
        "schema_version": "1.0",
        "provider": "futu",
        "source": "futu",
        "interval": "1d",
        "adjustment": "qfq",
        "start": dates[0],
        "end": dates[-1],
        "fetched_at": "2026-07-10T16:00:00+00:00",
        "symbols": list(series_values),
        "series": series,
    }


def _known_payload(return_count: int = 60) -> dict:
    benchmark_returns = [0.01 if index % 2 else -0.005 for index in range(return_count)]
    return _payload(
        {
            "AAPL": _closes([2.0 * value for value in benchmark_returns]),
            "MSFT": _closes([-value for value in benchmark_returns]),
            "SPY": _closes(benchmark_returns),
        }
    )


def test_parse_price_snapshot_requires_one_complete_strict_document() -> None:
    payload = _known_payload()

    parsed = historical_risk.parse_price_snapshot(
        json.dumps(payload, indent=2),
        expected_symbols=["AAPL", "MSFT", "SPY"],
    )

    assert parsed["symbols"] == ["AAPL", "MSFT", "SPY"]
    with pytest.raises(historical_risk.HistoricalPriceContractError):
        historical_risk.parse_price_snapshot(
            json.dumps(payload) + "\nprovider noise",
            expected_symbols=["AAPL", "MSFT", "SPY"],
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(provider="sample"),
        lambda payload: payload.update(adjustment="raw"),
        lambda payload: payload["symbols"].pop(),
        lambda payload: payload["series"][0]["rows"].append(
            payload["series"][0]["rows"][0]
        ),
        lambda payload: payload["series"][0]["rows"][0].update(close=0.0),
        lambda payload: payload["series"][0]["rows"][0].update(close=10**400),
        lambda payload: payload["series"][0].update(row_count=999),
        lambda payload: payload["series"][0].update(row_count=61.0),
    ],
)
def test_parse_price_snapshot_rejects_provenance_and_series_drift(mutate) -> None:
    payload = _known_payload()
    mutate(payload)

    with pytest.raises(historical_risk.HistoricalPriceContractError) as excinfo:
        historical_risk.parse_price_snapshot(
            json.dumps(payload),
            expected_symbols=["AAPL", "MSFT", "SPY"],
        )

    assert excinfo.value.code == "historical_prices_snapshot_invalid"


def test_global_date_inner_join_computes_known_beta_and_correlation() -> None:
    payload = _known_payload()

    result = historical_risk.analyze_price_history(
        payload,
        position_symbols=["AAPL", "MSFT"],
        benchmark="SPY",
        minimum_aligned_returns=60,
        history_end_policy="previous_utc_calendar_date",
    )

    risk = result["historical_risk"]
    assert risk["status"] == "available"
    assert risk["alignment"] == "global_date_inner_join_before_returns"
    assert risk["aligned_price_count"] == 61
    assert risk["aligned_return_count"] == 60
    assert risk["first_return_date"] == _dates(61)[1]
    assert risk["last_return_date"] == _dates(61)[-1]
    betas = {row["symbol"]: row for row in risk["betas"]}
    assert betas["AAPL"]["value"] == pytest.approx(2.0)
    assert betas["MSFT"]["value"] == pytest.approx(-1.0)
    assert all(row["aligned_return_count"] == 60 for row in betas.values())
    assert risk["correlations"] == [
        {
            "left": "AAPL",
            "right": "MSFT",
            "status": "available",
            "value": pytest.approx(-1.0),
            "aligned_return_count": 60,
            "first_return_date": _dates(61)[1],
            "last_return_date": _dates(61)[-1],
            "reason": None,
        }
    ]
    assert result["history_source"]["payload_sha256"]
    assert "rows" not in result["history_source"]


def test_missing_one_common_date_can_make_global_sample_insufficient() -> None:
    payload = _known_payload()
    payload["series"][0]["rows"].pop(30)
    payload["series"][0]["row_count"] -= 1

    result = historical_risk.analyze_price_history(
        payload,
        position_symbols=["AAPL", "MSFT"],
        benchmark="SPY",
        minimum_aligned_returns=60,
        history_end_policy="previous_utc_calendar_date",
    )

    assert result["historical_risk"]["status"] == "unavailable"
    assert result["historical_risk"]["aligned_return_count"] == 59
    assert result["historical_risk"]["correlations_status"] == "unavailable"
    assert result["historical_risk"]["reason"] == "insufficient_aligned_returns"


def test_constant_benchmark_degrades_beta_without_inventing_zero() -> None:
    payload = _known_payload()
    spy = next(row for row in payload["series"] if row["symbol"] == "SPY")
    for row in spy["rows"]:
        row["close"] = 100.0

    result = historical_risk.analyze_price_history(
        payload,
        position_symbols=["AAPL", "MSFT"],
        benchmark="SPY",
        minimum_aligned_returns=60,
        history_end_policy="previous_utc_calendar_date",
    )

    assert result["historical_risk"]["status"] == "degraded"
    assert all(row["value"] is None for row in result["historical_risk"]["betas"])
    assert all(
        row["reason"] == "benchmark_zero_variance"
        for row in result["historical_risk"]["betas"]
    )


def test_single_position_has_beta_but_correlation_is_not_applicable() -> None:
    payload = _known_payload()
    payload["symbols"] = ["AAPL", "SPY"]
    payload["series"] = [
        row for row in payload["series"] if row["symbol"] in {"AAPL", "SPY"}
    ]

    result = historical_risk.analyze_price_history(
        payload,
        position_symbols=["AAPL"],
        benchmark="SPY",
        minimum_aligned_returns=60,
        history_end_policy="previous_utc_calendar_date",
    )

    risk = result["historical_risk"]
    assert risk["status"] == "available"
    assert risk["correlations_status"] == "not_applicable"
    assert risk["correlations"] == []
    assert risk["betas"][0]["value"] == pytest.approx(2.0)


def test_history_window_uses_previous_utc_date_and_400_calendar_days() -> None:
    assert historical_risk.history_window("2026-07-11T00:05:00+08:00") == (
        "2025-06-04",
        "2026-07-09",
    )


def test_extreme_relationship_overflow_is_unavailable_not_zero() -> None:
    metric = historical_risk._relationship(
        [1e308, -1e308] * 30,
        [1e308, -1e308] * 30,
        return_dates=_dates(60),
        kind="correlation",
    )

    assert metric["status"] == "unavailable"
    assert metric["value"] is None
    assert metric["reason"] == "historical_metric_non_finite"
