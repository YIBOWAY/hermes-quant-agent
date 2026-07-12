from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from hqa import hermes_artifacts, market_foresight, predictions


def _history_payload(*, start: str, end: str) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "provider": "futu",
            "source": "futu",
            "interval": "1d",
            "adjustment": "qfq",
            "start": start,
            "end": end,
            "fetched_at": "2026-07-11T04:00:01+00:00",
            "symbols": ["AAPL"],
            "series": [
                {
                    "symbol": "AAPL",
                    "row_count": 1,
                    "first_date": "2026-07-10",
                    "last_date": "2026-07-10",
                    "rows": [{"date": "2026-07-10", "close": 313.39}],
                }
            ],
        }
    )


def _risk_artifact() -> dict:
    return {
        "schema_version": "2.0",
        "job": "portfolio-risk",
        "ts": "2026-07-11T03:00:00Z",
        "status": "available",
        "portfolio_state": "invested",
        "reason_codes": [],
        "account": {"account_id": "default", "base_currency": "USD"},
        "exposure": {
            "currency": "USD",
            "gross_value": 313.39,
            "gross_pct_equity": 0.01,
        },
        "concentration": {
            "largest_symbol": "AAPL",
            "top1_gross_pct": 1.0,
        },
        "price_quality": {"valuation_basis": "market"},
        "positions": [],
        "policy_evaluation": {"status": "not_evaluated", "thresholds": []},
        "limitations": ["no_risk_policy_thresholds_configured"],
        "error": None,
        "history_source": {"status": "available"},
        "historical_risk": {
            "status": "available",
            "benchmark": "SPY",
            "betas": [
                {
                    "aligned_return_count": 274,
                    "benchmark": "SPY",
                    "first_return_date": "2025-06-06",
                    "last_return_date": "2026-07-10",
                    "reason": None,
                    "status": "available",
                    "symbol": "AAPL",
                    "value": 0.85,
                }
            ],
        },
    }


def test_rebuild_projects_risk_prediction_and_foresight_to_one_feed(tmp_path) -> None:
    run_history = lambda symbols, start, end: (  # noqa: E731
        0,
        _history_payload(start=start, end=end),
    )
    ledger = predictions.PredictionLedger(
        tmp_path / "predictions",
        run_history=run_history,
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 300.",
            "request_id": "prediction-1",
        }
    )
    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=ledger,
    )
    publisher.publish(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-18",
            "confidence": 0.65,
            "falsifier": "The first eligible close is below 295.",
            "request_id": "foresight-1",
        }
    )
    risk_path = tmp_path / "logs" / "portfolio_risk.jsonl"
    risk_path.parent.mkdir(parents=True)
    risk_path.write_text(json.dumps(_risk_artifact()) + "\n", encoding="utf-8")
    feed_path = tmp_path / "artifacts" / "hermes-feed.v1.json"
    feed = hermes_artifacts.HermesArtifactFeed(
        feed_path,
        portfolio_risk_path=risk_path,
        prediction_ledger=ledger,
        foresight_publisher=publisher,
        now=lambda: "2026-07-11T05:00:00Z",
    )

    manifest = feed.rebuild()

    assert set(manifest) == {
        "schema_version",
        "read_status",
        "as_of",
        "items",
        "sources",
        "warnings",
    }
    assert manifest["schema_version"] == "1.0"
    assert manifest["read_status"] == "available"
    assert [item["kind"] for item in manifest["items"]] == [
        "market_foresight",
        "prediction",
        "portfolio_risk",
    ]
    assert all(
        set(item) == {"id", "kind", "occurred_at", "quality", "status", "data"}
        for item in manifest["items"]
    )
    assert {source["kind"] for source in manifest["sources"]} == {
        "portfolio_risk",
        "prediction",
        "market_foresight",
    }
    assert feed.read() == manifest
    assert json.loads(feed_path.read_text(encoding="utf-8")) == manifest
    assert not list(feed_path.parent.glob("*.tmp"))

    limited = feed.rebuild(limit=1)

    assert len(limited["items"]) == 1
    assert {source["status"] for source in limited["sources"]} == {"available"}
    assert feed.read() == limited


def test_rebuild_marks_corrupt_source_degraded_and_keeps_healthy_items(tmp_path) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path / "predictions",
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(start=start, end=end),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 300.",
        }
    )
    risk_path = tmp_path / "portfolio_risk.jsonl"
    risk_path.write_text("{corrupt\n", encoding="utf-8")
    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=ledger,
    )
    feed = hermes_artifacts.HermesArtifactFeed(
        tmp_path / "artifacts" / "manifest.v1.json",
        portfolio_risk_path=risk_path,
        prediction_ledger=ledger,
        foresight_publisher=publisher,
        now=lambda: "2026-07-11T05:00:00Z",
    )

    manifest = feed.rebuild()

    assert manifest["read_status"] == "degraded"
    assert [item["kind"] for item in manifest["items"]] == ["prediction"]
    assert manifest["warnings"] == [
        {"source": "portfolio_risk", "code": "portfolio_risk_source_corrupt"}
    ]
    source = next(
        row for row in manifest["sources"] if row["kind"] == "portfolio_risk"
    )
    assert source == {
        "kind": "portfolio_risk",
        "status": "degraded",
        "latest_at": None,
        "reason_code": "portfolio_risk_source_corrupt",
    }


def test_concurrent_rebuilds_use_unique_temps_and_leave_matching_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path / "predictions",
        run_history=lambda symbols, start, end: (1, ""),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=ledger,
    )
    feed_path = tmp_path / "artifacts" / "manifest.v1.json"
    feed = hermes_artifacts.HermesArtifactFeed(
        feed_path,
        portfolio_risk_path=tmp_path / "missing-risk.jsonl",
        prediction_ledger=ledger,
        foresight_publisher=publisher,
        now=lambda: "2026-07-11T05:00:00Z",
    )
    barrier = threading.Barrier(2)
    real_replace = hermes_artifacts.os.replace

    def synchronized_replace(source, destination):
        barrier.wait(timeout=5)
        return real_replace(source, destination)

    monkeypatch.setattr(hermes_artifacts.os, "replace", synchronized_replace)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: feed.rebuild(), range(2)))

    assert results[0] == results[1]
    assert feed.read() == results[0]
    assert json.loads(feed_path.read_text(encoding="utf-8")) == results[0]
    assert not list(feed_path.parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "corruption",
    [
        "invalid_status",
        "non_finite",
        "missing_field",
        "unknown_field",
        "nested_beta_unknown_field",
        "nested_beta_non_finite",
        "nested_beta_invalid_date",
        "oversized_account_id",
        "too_many_limitations",
        "oversized_beta_symbol",
        "negative_gross_value",
        "oversized_top1_ratio",
    ],
)
def test_invalid_risk_contract_degrades_only_risk_and_keeps_healthy_sources(
    tmp_path,
    corruption,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path / "predictions",
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(start=start, end=end),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "close below 300",
            "request_id": "prediction-risk-corruption",
        }
    )
    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=ledger,
    )
    publisher.publish(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-18",
            "confidence": 0.65,
            "falsifier": "close below 295",
            "request_id": "foresight-risk-corruption",
        }
    )
    artifact = _risk_artifact()
    if corruption == "invalid_status":
        artifact["status"] = "garbage"
    elif corruption == "non_finite":
        artifact["exposure"]["gross_value"] = float("nan")
    elif corruption == "missing_field":
        artifact.pop("account")
    elif corruption == "unknown_field":
        artifact["unexpected"] = True
    elif corruption == "nested_beta_unknown_field":
        artifact["historical_risk"]["betas"][0]["private_path"] = (
            "/Users/private/risk.json"
        )
    elif corruption == "nested_beta_non_finite":
        artifact["historical_risk"]["betas"][0]["value"] = float("inf")
    elif corruption == "nested_beta_invalid_date":
        artifact["historical_risk"]["betas"][0]["first_return_date"] = (
            "2026-7-1"
        )
    elif corruption == "oversized_account_id":
        artifact["account"]["account_id"] = "a" * 129
    elif corruption == "too_many_limitations":
        artifact["limitations"] = [f"limit-{index}" for index in range(101)]
    elif corruption == "oversized_beta_symbol":
        artifact["historical_risk"]["betas"][0]["symbol"] = "A" * 17
    elif corruption == "negative_gross_value":
        artifact["exposure"]["gross_value"] = -1.0
    else:
        artifact["concentration"]["top1_gross_pct"] = 2.0
    risk_path = tmp_path / "portfolio_risk.jsonl"
    risk_path.write_text(json.dumps(artifact) + "\n", encoding="utf-8")
    feed = hermes_artifacts.HermesArtifactFeed(
        tmp_path / "artifacts" / "manifest.v1.json",
        portfolio_risk_path=risk_path,
        prediction_ledger=ledger,
        foresight_publisher=publisher,
        now=lambda: "2026-07-11T05:00:00Z",
    )

    manifest = feed.rebuild()

    assert manifest["read_status"] == "degraded"
    assert {item["kind"] for item in manifest["items"]} == {
        "prediction",
        "market_foresight",
    }
    assert manifest["warnings"] == [
        {"source": "portfolio_risk", "code": "portfolio_risk_source_corrupt"}
    ]
    risk_source = next(
        source for source in manifest["sources"] if source["kind"] == "portfolio_risk"
    )
    assert risk_source["status"] == "degraded"


@pytest.mark.parametrize(
    "corruption",
    [
        "invalid_quality",
        "private_data_field",
        "invalid_sources",
        "invalid_warnings",
        "duplicate_id",
        "aggregate_status_mismatch",
    ],
)
def test_read_rejects_invalid_manifest_contract(tmp_path, corruption) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path / "predictions",
        run_history=lambda symbols, start, end: (1, ""),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=ledger,
    )
    feed_path = tmp_path / "artifacts" / "manifest.v1.json"
    feed_path.parent.mkdir(parents=True)
    item = {
        "id": "prediction:pred-20260711-0001",
        "kind": "prediction",
        "occurred_at": "2026-07-11T04:00:00Z",
        "quality": "available",
        "status": "open",
        "data": {
            "prediction_id": "pred-20260711-0001",
            "state": "open",
            "symbol": "AAPL",
            "direction": "up",
            "confidence": 0.7,
            "horizon_date": "2026-07-18",
            "rationale": "bounded rationale",
            "outcome_return": None,
            "direction_brier": None,
        },
    }
    manifest = {
        "schema_version": "1.0",
        "read_status": "available",
        "as_of": "2026-07-11T05:00:00Z",
        "items": [item],
        "sources": [
            {
                "kind": "portfolio_risk",
                "status": "empty",
                "latest_at": None,
                "reason_code": None,
            },
            {
                "kind": "prediction",
                "status": "available",
                "latest_at": "2026-07-11T04:00:00Z",
                "reason_code": None,
            },
            {
                "kind": "market_foresight",
                "status": "empty",
                "latest_at": None,
                "reason_code": None,
            },
        ],
        "warnings": [],
    }
    if corruption == "invalid_quality":
        item["quality"] = "garbage"
    elif corruption == "private_data_field":
        item["data"]["private_path"] = "/Users/private/prediction.json"
    elif corruption == "invalid_sources":
        manifest["sources"] = "not-a-list"
    elif corruption == "invalid_warnings":
        manifest["warnings"] = {"source": "prediction", "code": "bad"}
    elif corruption == "duplicate_id":
        manifest["items"].append(dict(item))
    else:
        manifest["read_status"] = "empty"
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    feed = hermes_artifacts.HermesArtifactFeed(
        feed_path,
        portfolio_risk_path=tmp_path / "missing-risk.jsonl",
        prediction_ledger=ledger,
        foresight_publisher=publisher,
        now=lambda: "2026-07-11T05:00:00Z",
    )

    with pytest.raises(hermes_artifacts.HermesArtifactFeedError) as excinfo:
        feed.read()

    assert excinfo.value.code == "hermes_artifact_feed_corrupt"
