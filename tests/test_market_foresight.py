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


def test_publish_creates_immutable_proposal_without_prediction_write(tmp_path) -> None:
    prediction_dir = tmp_path / "predictions"
    ledger = predictions.PredictionLedger(
        prediction_dir,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(start=start, end=end),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=ledger,
    )

    artifact = publisher.publish(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 300.",
            "rationale": "Hermes-authored earnings revision thesis.",
            "request_id": "hermes-turn-9f-1",
        }
    )

    assert artifact["schema_version"] == "1.0"
    assert artifact["kind"] == "market_foresight"
    assert artifact["status"] == "proposed"
    assert artifact["proposal_only"] is True
    assert artifact["requires_human_confirmation"] is True
    assert artifact["trading_allowed"] is False
    assert artifact["intent"]["symbol"] == "AAPL"
    assert artifact["evidence"]["entry_price"]["provider"] == "futu"
    assert artifact["evidence"]["entry_price"]["adjustment"] == "qfq"
    assert publisher.list() == [artifact]
    assert not (prediction_dir / "entries.jsonl").exists()
    assert not (prediction_dir / ".ledger.lock").exists()


def test_publish_same_request_and_intent_returns_existing_without_price_read(
    tmp_path,
) -> None:
    calls = []

    def run_history(symbols, start, end):
        calls.append((symbols, start, end))
        return 0, _history_payload(start=start, end=end)

    ledger = predictions.PredictionLedger(
        tmp_path / "predictions",
        run_history=run_history,
        now=lambda: "2026-07-11T04:00:00Z",
    )
    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=ledger,
    )
    request = {
        "symbol": "AAPL",
        "direction": "up",
        "horizon_date": "2026-07-17",
        "confidence": 0.7,
        "falsifier": "The first eligible close is below 300.",
        "request_id": "hermes-turn-9f-idempotent",
    }

    first = publisher.publish(request)
    second = publisher.publish(dict(request))

    assert second == first
    assert len(calls) == 1
    assert len(list((tmp_path / "foresight").glob("*.json"))) == 1


def test_publish_same_request_with_changed_intent_fails_closed(tmp_path) -> None:
    calls = []

    def run_history(symbols, start, end):
        calls.append((symbols, start, end))
        return 0, _history_payload(start=start, end=end)

    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=predictions.PredictionLedger(
            tmp_path / "predictions",
            run_history=run_history,
            now=lambda: "2026-07-11T04:00:00Z",
        ),
    )
    request = {
        "symbol": "AAPL",
        "direction": "up",
        "horizon_date": "2026-07-17",
        "confidence": 0.7,
        "falsifier": "The first eligible close is below 300.",
        "request_id": "hermes-turn-9f-conflict",
    }
    original = publisher.publish(request)

    with pytest.raises(market_foresight.MarketForesightError) as exc_info:
        publisher.publish({**request, "direction": "down"})

    assert exc_info.value.code == "market_foresight_idempotency_conflict"
    assert len(calls) == 1
    assert publisher.list() == [original]


def test_publish_unavailable_evidence_writes_no_candidate(tmp_path) -> None:
    foresight_dir = tmp_path / "foresight"
    publisher = market_foresight.MarketForesightPublisher(
        foresight_dir,
        prediction_ledger=predictions.PredictionLedger(
            tmp_path / "predictions",
            run_history=lambda symbols, start, end: (1, ""),
            now=lambda: "2026-07-11T04:00:00Z",
        ),
    )

    with pytest.raises(market_foresight.MarketForesightError) as exc_info:
        publisher.publish(
            {
                "symbol": "AAPL",
                "direction": "up",
                "horizon_date": "2026-07-17",
                "confidence": 0.7,
                "falsifier": "The first eligible close is below 300.",
                "request_id": "hermes-turn-9f-no-evidence",
            }
        )

    assert exc_info.value.code == "market_foresight_evidence_unavailable"
    assert exc_info.value.retryable is True
    assert not foresight_dir.exists()


def test_concurrent_changed_intents_publish_once_and_conflict_without_overwrite(
    tmp_path,
) -> None:
    barrier = threading.Barrier(2)

    def run_history(symbols, start, end):
        barrier.wait(timeout=5)
        return 0, _history_payload(start=start, end=end)

    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=predictions.PredictionLedger(
            tmp_path / "predictions",
            run_history=run_history,
            now=lambda: "2026-07-11T04:00:00Z",
        ),
    )
    base = {
        "symbol": "AAPL",
        "horizon_date": "2026-07-17",
        "confidence": 0.7,
        "falsifier": "The first eligible close is below 300.",
        "request_id": "hermes-turn-9f-concurrent-conflict",
    }

    def publish(direction):
        try:
            return "published", publisher.publish({**base, "direction": direction})
        except market_foresight.MarketForesightError as exc:
            return "error", exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, ("up", "down")))

    assert sorted(result[0] for result in results) == ["error", "published"]
    assert [result[1] for result in results if result[0] == "error"] == [
        "market_foresight_idempotency_conflict"
    ]
    artifacts = publisher.list()
    assert len(artifacts) == 1
    assert artifacts[0]["intent"]["direction"] in {"up", "down"}
    assert len(list((tmp_path / "foresight").glob("*.json"))) == 1
    assert not list((tmp_path / "foresight").glob("*.tmp"))


def test_same_intent_from_different_requests_has_unique_artifact_and_feed_ids(
    tmp_path,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path / "predictions",
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(start=start, end=end),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=ledger,
    )
    request = {
        "symbol": "AAPL",
        "direction": "up",
        "horizon_date": "2026-07-17",
        "confidence": 0.7,
        "falsifier": "The first eligible close is below 300.",
    }

    first = publisher.publish({**request, "request_id": "hermes-turn-one"})
    second = publisher.publish({**request, "request_id": "hermes-turn-two"})
    feed = hermes_artifacts.HermesArtifactFeed(
        tmp_path / "artifacts" / "manifest.v1.json",
        portfolio_risk_path=tmp_path / "missing-risk.jsonl",
        prediction_ledger=ledger,
        foresight_publisher=publisher,
        now=lambda: "2026-07-11T05:00:00Z",
    ).rebuild()

    assert first["intent_sha256"] == second["intent_sha256"]
    assert first["id"] != second["id"]
    feed_ids = [item["id"] for item in feed["items"]]
    assert len(feed_ids) == len(set(feed_ids)) == 2


@pytest.mark.parametrize(
    "corruption",
    [
        "duplicate_key",
        "non_finite",
        "unknown_field",
        "missing_field",
        "invalid_time",
        "unsafe_flag",
    ],
)
def test_list_rejects_corrupt_candidate_and_feed_marks_source_degraded(
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
    publisher = market_foresight.MarketForesightPublisher(
        tmp_path / "foresight",
        prediction_ledger=ledger,
    )
    publisher.publish(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 300.",
            "request_id": "hermes-turn-corrupt",
        }
    )
    path = next((tmp_path / "foresight").glob("*.json"))
    text = path.read_text(encoding="utf-8")
    if corruption == "duplicate_key":
        text = text.replace(
            '"schema_version":"1.0"',
            '"schema_version":"1.0","schema_version":"1.0"',
            1,
        )
    elif corruption == "non_finite":
        text = text.replace('"confidence":0.7', '"confidence":NaN', 1)
    else:
        document = json.loads(text)
        if corruption == "unknown_field":
            document["unexpected"] = True
        elif corruption == "missing_field":
            document.pop("trading_allowed")
        elif corruption == "invalid_time":
            document["occurred_at"] = "2026-07-11T04:00:00"
        else:
            document["proposal_only"] = False
        text = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(market_foresight.MarketForesightError) as exc_info:
        publisher.list()

    assert exc_info.value.code == "market_foresight_store_corrupt"
    manifest = hermes_artifacts.HermesArtifactFeed(
        tmp_path / "artifacts" / "manifest.v1.json",
        portfolio_risk_path=tmp_path / "missing-risk.jsonl",
        prediction_ledger=ledger,
        foresight_publisher=publisher,
        now=lambda: "2026-07-11T05:00:00Z",
    ).rebuild()
    assert manifest["read_status"] == "degraded"
    assert manifest["warnings"] == [
        {"source": "market_foresight", "code": "market_foresight_source_corrupt"}
    ]
