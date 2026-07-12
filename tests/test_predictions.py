from __future__ import annotations

import json
import errno
from contextlib import contextmanager
from multiprocessing import get_context
from pathlib import Path

import pytest

from hqa import predictions


def _history_payload(*, start: str, end: str, rows: list[dict]) -> str:
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
                    "row_count": len(rows),
                    "first_date": rows[0]["date"],
                    "last_date": rows[-1]["date"],
                    "rows": rows,
                }
            ],
        }
    )


def _concurrent_create_worker(arguments: tuple[str, int]) -> str:
    prediction_dir, index = arguments
    ledger = predictions.PredictionLedger(
        Path(prediction_dir),
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    return ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
            "request_id": f"concurrent-{index}",
        }
    )["id"]


def _concurrent_score_worker(prediction_dir, barrier, queue) -> None:
    try:

        def run_history(symbols, start, end):
            barrier.wait(timeout=10)
            return 0, _history_payload(
                start=start,
                end=end,
                rows=[
                    {"date": "2026-07-10", "close": 100.0},
                    {"date": "2026-07-14", "close": 110.0},
                ],
            )

        ledger = predictions.PredictionLedger(
            Path(prediction_dir),
            run_history=run_history,
            now=lambda: "2026-07-16T04:00:00Z",
        )
        queue.put(ledger.reconcile_due()["results"])
    except Exception as exc:  # pragma: no cover - surfaced in the parent assertion
        queue.put({"error": repr(exc)})


def test_create_records_one_open_prediction_from_completed_futu_session(
    tmp_path,
) -> None:
    calls = []

    def run_history(symbols, start, end):
        calls.append((symbols, start, end))
        return 0, _history_payload(
            start=start,
            end=end,
            rows=[
                {"date": "2026-07-09", "close": 310.66},
                {"date": "2026-07-10", "close": 313.39},
            ],
        )

    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: "2026-07-11T04:00:00Z",
    )

    created = ledger.create(
        {
            "symbol": "aapl",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "range_low": 320.0,
            "range_high": 340.0,
            "falsifier": "The first eligible close is below 300.",
            "rationale": "Earnings revision momentum.",
        }
    )

    assert calls == [(["AAPL"], "2026-06-30", "2026-07-10")]
    assert created["id"] == "2026-07-11-001"
    assert created["status"] == "open"
    assert created["entry_price"]["session_date"] == "2026-07-10"
    assert created["entry_price"]["close"] == pytest.approx(313.39)
    assert created["range_return_low"] == pytest.approx(320.0 / 313.39 - 1.0)
    assert created["range_return_high"] == pytest.approx(340.0 / 313.39 - 1.0)
    assert ledger.list() == [created]
    assert len((tmp_path / "entries.jsonl").read_text().splitlines()) == 1


def test_prepare_returns_strict_completed_session_evidence_without_ledger_write(
    tmp_path,
) -> None:
    calls = []

    def run_history(symbols, start, end):
        calls.append((symbols, start, end))
        return 0, _history_payload(
            start=start,
            end=end,
            rows=[{"date": "2026-07-10", "close": 313.39}],
        )

    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: "2026-07-11T04:00:00Z",
    )

    prepared = ledger.prepare(
        {
            "symbol": "aapl",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 300.",
            "request_id": "hermes-turn-9f-1",
        }
    )

    assert calls == [(["AAPL"], "2026-06-30", "2026-07-10")]
    assert prepared["status"] == "prepared"
    assert prepared["request_id"] == "hermes-turn-9f-1"
    assert prepared["prediction_request"]["symbol"] == "AAPL"
    assert prepared["entry_price"]["session_date"] == "2026-07-10"
    assert prepared["entry_price"]["provider"] == "futu"
    assert prepared["entry_price"]["adjustment"] == "qfq"
    assert not (tmp_path / "entries.jsonl").exists()
    assert not (tmp_path / ".ledger.lock").exists()


def test_repeating_the_same_create_intent_is_idempotent(tmp_path) -> None:
    calls = []

    def run_history(symbols, start, end):
        calls.append((symbols, start, end))
        return 0, _history_payload(
            start=start,
            end=end,
            rows=[{"date": "2026-07-10", "close": 313.39}],
        )

    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: "2026-07-11T04:00:00Z",
    )
    request = {
        "symbol": "AAPL",
        "direction": "up",
        "horizon_date": "2026-07-17",
        "confidence": 0.7,
        "falsifier": "The first eligible close is below 300.",
    }

    first = ledger.create(request)
    second = ledger.create(dict(request))

    assert second == first
    assert len(calls) == 1
    assert len((tmp_path / "entries.jsonl").read_text().splitlines()) == 1


def test_reconcile_scores_with_entry_and_outcome_from_one_qfq_payload(
    tmp_path,
) -> None:
    now = ["2026-07-11T04:00:00Z"]
    calls = []

    def run_history(symbols, start, end):
        calls.append((symbols, start, end))
        if len(calls) == 1:
            rows = [{"date": "2026-07-10", "close": 100.0}]
        else:
            rows = [
                {"date": "2026-07-10", "close": 50.0},
                {"date": "2026-07-14", "close": 55.0},
                {"date": "2026-07-15", "close": 60.0},
            ]
        return 0, _history_payload(start=start, end=end, rows=rows)

    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: now[0],
    )
    created = ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-14",
            "confidence": 0.7,
            "range_low": 105.0,
            "range_high": 115.0,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    now[0] = "2026-07-16T04:00:00Z"

    report = ledger.reconcile_due()
    scored = ledger.list()[0]

    assert calls[-1] == (["AAPL"], "2026-07-10", "2026-07-15")
    assert report["results"] == [
        {
            "id": created["id"],
            "status": "scored",
            "outcome_session_date": "2026-07-14",
        }
    ]
    assert scored["status"] == "scored"
    assert scored["scoring_entry_close"] == 50.0
    assert scored["outcome_close"] == 55.0
    assert scored["outcome_return"] == pytest.approx(0.1)
    assert scored["direction_correct"] is True
    assert scored["direction_brier"] == pytest.approx(0.09)
    assert scored["range_hit"] is True
    assert len((tmp_path / "entries.jsonl").read_text().splitlines()) == 2


def test_list_fails_closed_when_created_event_domain_fields_are_tampered(
    tmp_path,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    path = tmp_path / "entries.jsonl"
    event = json.loads(path.read_text())
    event["confidence"] = 7.0
    path.write_text(json.dumps(event) + "\n")

    with pytest.raises(
        predictions.PredictionLedgerError,
        match="confidence",
    ) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_corrupt"


def test_reconcile_propagates_ledger_corruption_found_during_score_commit(
    tmp_path,
) -> None:
    call_count = 0

    def run_history(symbols, start, end):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            with (tmp_path / "entries.jsonl").open("a") as handle:
                handle.write("torn-tail")
            rows = [
                {"date": "2026-07-10", "close": 100.0},
                {"date": "2026-07-14", "close": 110.0},
            ]
        else:
            rows = [{"date": "2026-07-10", "close": 100.0}]
        return 0, _history_payload(
            start=start,
            end=end,
            rows=rows,
        )

    now = ["2026-07-11T04:00:00Z"]
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: now[0],
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-14",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    now[0] = "2026-07-16T04:00:00Z"

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.reconcile_due()

    assert exc_info.value.code == "prediction_ledger_corrupt"


def test_list_rejects_a_score_timestamp_before_its_outcome_was_complete(
    tmp_path,
) -> None:
    now = ["2026-07-11T04:00:00Z"]

    def run_history(symbols, start, end):
        rows = [{"date": "2026-07-10", "close": 100.0}]
        if end >= "2026-07-14":
            rows.append({"date": "2026-07-14", "close": 110.0})
        return 0, _history_payload(start=start, end=end, rows=rows)

    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: now[0],
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-14",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    now[0] = "2026-07-16T04:00:00Z"
    ledger.reconcile_due()
    path = tmp_path / "entries.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    events[1]["scored_at"] = "2026-07-14T12:00:00Z"
    path.write_text("".join(json.dumps(event) + "\n" for event in events))

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_corrupt"
    assert "completed-session cutoff" in exc_info.value.message


def test_concurrent_creates_allocate_unique_contiguous_ids(tmp_path) -> None:
    context = get_context("fork")
    arguments = [(str(tmp_path), index) for index in range(16)]

    with context.Pool(processes=8) as pool:
        ids = pool.map(_concurrent_create_worker, arguments)

    assert len(set(ids)) == 16
    assert sorted(ids) == [f"2026-07-11-{index:03d}" for index in range(1, 17)]
    lines = (tmp_path / "entries.jsonl").read_text().splitlines()
    assert len(lines) == 16
    assert all(isinstance(json.loads(line), dict) for line in lines)


def test_concurrent_reconcile_appends_exactly_one_score_event(tmp_path) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-14",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    context = get_context("fork")
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [
        context.Process(
            target=_concurrent_score_worker,
            args=(str(tmp_path), barrier, queue),
        )
        for _ in range(2)
    ]

    for process in processes:
        process.start()
    results = [queue.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)

    assert all(process.exitcode == 0 for process in processes)
    assert {result[0]["status"] for result in results} == {
        "already_scored",
        "scored",
    }
    events = [
        json.loads(line)
        for line in (tmp_path / "entries.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events].count("prediction_scored") == 1


def test_list_rejects_noncanonical_created_fields(tmp_path) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    path = tmp_path / "entries.jsonl"
    event = json.loads(path.read_text())
    event["symbol"] = "aapl"
    path.write_text(json.dumps(event) + "\n")

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_corrupt"
    assert "canonical" in exc_info.value.message


def test_list_rejects_duplicate_request_id_events(tmp_path) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
            "request_id": "source-turn-1",
        }
    )
    path = tmp_path / "entries.jsonl"
    event = json.loads(path.read_text())
    duplicate = dict(event)
    duplicate["id"] = "2026-07-11-002"
    path.write_text(json.dumps(event) + "\n" + json.dumps(duplicate) + "\n")

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_corrupt"
    assert "duplicate prediction request_id" in exc_info.value.message


def test_create_rejects_nonfinite_derived_range_before_creating_ledger(
    tmp_path,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 1e-308}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.create(
            {
                "symbol": "AAPL",
                "direction": "up",
                "horizon_date": "2026-07-17",
                "confidence": 0.7,
                "range_low": 1e307,
                "range_high": 1e308,
                "falsifier": "The first eligible close is below the anchor.",
            }
        )

    assert exc_info.value.code == "prediction_invalid_request"
    assert not (tmp_path / "entries.jsonl").exists()


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1.0, 0.0])
def test_constructor_rejects_nonfinite_or_nonpositive_lock_timeout(
    tmp_path,
    timeout,
) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        predictions.PredictionLedger(
            tmp_path,
            run_history=lambda symbols, start, end: (1, ""),
            now=lambda: "2026-07-11T04:00:00Z",
            lock_timeout_seconds=timeout,
        )


def test_list_rejects_noncanonical_timestamp_encoding(tmp_path) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    path = tmp_path / "entries.jsonl"
    event = json.loads(path.read_text())
    event["created_at"] = "2026-07-11T00:00:00-04:00"
    path.write_text(json.dumps(event) + "\n")

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list(since="2026-07-11T02:00:00Z")

    assert exc_info.value.code == "prediction_ledger_corrupt"
    assert "canonical UTC" in exc_info.value.message


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_unicode_line_separators_round_trip_inside_json_strings(
    tmp_path,
    separator,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    falsifier = f"first condition{separator}second condition"

    created = ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": falsifier,
        }
    )

    assert ledger.list()[0]["falsifier"] == created["falsifier"] == falsifier


def test_list_rejects_scoring_evidence_beyond_resolution_window(tmp_path) -> None:
    now = ["2026-07-11T04:00:00Z"]

    def run_history(symbols, start, end):
        rows = [{"date": "2026-07-10", "close": 100.0}]
        if end >= "2026-07-14":
            rows.append({"date": "2026-07-14", "close": 110.0})
        return 0, _history_payload(start=start, end=end, rows=rows)

    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: now[0],
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-14",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    now[0] = "2026-07-16T04:00:00Z"
    ledger.reconcile_due()
    path = tmp_path / "entries.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    events[1]["price_evidence"]["end"] = "2026-07-30"
    path.write_text("".join(json.dumps(event) + "\n" for event in events))

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_corrupt"
    assert "resolution window" in exc_info.value.message


def test_list_fails_closed_if_ledger_disappears_between_exists_and_open(
    tmp_path,
    monkeypatch,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )

    @contextmanager
    def vanished_ledger(**kwargs):
        yield None

    monkeypatch.setattr(ledger, "_locked", vanished_ledger)

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_io_error"


def test_reconcile_cursor_prevents_unavailable_old_rows_from_starving_newer_rows(
    tmp_path,
) -> None:
    now = ["2026-07-11T04:00:00Z"]
    scoring = [False]
    score_calls = [0]

    def run_history(symbols, start, end):
        if scoring[0]:
            score_calls[0] += 1
            if score_calls[0] <= 25:
                return 1, ""
            rows = [
                {"date": "2026-07-10", "close": 100.0},
                {"date": "2026-07-14", "close": 110.0},
            ]
        else:
            rows = [{"date": "2026-07-10", "close": 100.0}]
        return 0, _history_payload(start=start, end=end, rows=rows)

    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: now[0],
    )
    for index in range(26):
        ledger.create(
            {
                "symbol": "AAPL",
                "direction": "up",
                "horizon_date": "2026-07-14",
                "confidence": 0.7,
                "falsifier": "The first eligible close is below 95.",
                "request_id": f"batch-{index:02d}",
            }
        )
    scoring[0] = True
    now[0] = "2026-07-16T04:00:00Z"

    first = ledger.reconcile_due(limit=25)
    second = ledger.reconcile_due(limit=25, cursor=first["next_cursor"])

    assert first["processed_count"] == 25
    assert first["next_cursor"] is not None
    assert second["results"] == [
        {
            "id": "2026-07-11-026",
            "status": "scored",
            "outcome_session_date": "2026-07-14",
        }
    ]
    assert second["remaining_due_count"] == 25
    assert second["next_cursor"] is None


def test_public_validation_never_leaks_type_errors(tmp_path) -> None:
    calls = []
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: calls.append(1) or (1, ""),
        now=lambda: "2026-07-11T04:00:00Z",
    )

    with pytest.raises(predictions.PredictionLedgerError) as direction_error:
        ledger.create(
            {
                "symbol": "AAPL",
                "direction": [],
                "horizon_date": "2026-07-17",
                "confidence": 0.7,
                "falsifier": "invalid",
            }
        )
    with pytest.raises(predictions.PredictionLedgerError) as status_error:
        ledger.list(status=[])
    with pytest.raises(predictions.PredictionLedgerError) as key_error:
        ledger.create({1: "unknown"})
    with pytest.raises(predictions.PredictionLedgerError) as as_of_error:
        ledger.reconcile_due(as_of=[])
    with pytest.raises(predictions.PredictionLedgerError) as overflow_error:
        ledger.reconcile_due(as_of="0001-01-01T00:00:00+14:00")

    assert direction_error.value.code == "prediction_invalid_request"
    assert status_error.value.code == "prediction_invalid_request"
    assert key_error.value.code == "prediction_invalid_request"
    assert as_of_error.value.code == "prediction_invalid_request"
    assert overflow_error.value.code == "prediction_invalid_request"
    assert calls == []


def test_malformed_created_field_type_is_reported_as_ledger_corruption(
    tmp_path,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    path = tmp_path / "entries.jsonl"
    event = json.loads(path.read_text())
    event["direction"] = []
    path.write_text(json.dumps(event) + "\n")

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_corrupt"


def test_nonfinite_scoring_arithmetic_degrades_one_row_and_continues_batch(
    tmp_path,
) -> None:
    now = ["2026-07-11T04:00:00Z"]
    scoring = [False]
    scoring_calls = [0]

    def run_history(symbols, start, end):
        if not scoring[0]:
            rows = [{"date": "2026-07-10", "close": 100.0}]
        else:
            scoring_calls[0] += 1
            if scoring_calls[0] == 1:
                rows = [
                    {"date": "2026-07-10", "close": 5e-324},
                    {"date": "2026-07-14", "close": 1e308},
                ]
            else:
                rows = [
                    {"date": "2026-07-10", "close": 100.0},
                    {"date": "2026-07-14", "close": 110.0},
                ]
        return 0, _history_payload(start=start, end=end, rows=rows)

    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: now[0],
    )
    request = {
        "symbol": "AAPL",
        "direction": "up",
        "horizon_date": "2026-07-14",
        "confidence": 0.7,
        "falsifier": "The first eligible close is below 95.",
    }
    ledger.create({**request, "request_id": "score-overflow"})
    ledger.create({**request, "request_id": "score-normal"})
    scoring[0] = True
    now[0] = "2026-07-16T04:00:00Z"

    report = ledger.reconcile_due()

    assert report["status"] == "degraded"
    assert report["results"][0]["status"] == "unavailable"
    assert report["results"][0]["reason"] == "prediction_scoring_evidence_invalid"
    assert report["results"][1]["status"] == "scored"
    assert [row["status"] for row in ledger.list()] == ["open", "scored"]
    assert len((tmp_path / "entries.jsonl").read_text().splitlines()) == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", True),
        ("revision", 1.0),
        ("id", "2026-07-11-000"),
        ("id", "2026-07-11-0001"),
    ],
)
def test_list_rejects_noncanonical_revision_and_id(
    tmp_path,
    field,
    value,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    path = tmp_path / "entries.jsonl"
    event = json.loads(path.read_text())
    event[field] = value
    path.write_text(json.dumps(event) + "\n")

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_corrupt"


def test_partial_append_is_rolled_back_and_safe_to_retry(
    tmp_path,
    monkeypatch,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    request = {
        "symbol": "AAPL",
        "direction": "up",
        "horizon_date": "2026-07-17",
        "confidence": 0.7,
        "falsifier": "The first eligible close is below 95.",
    }
    real_write = predictions.os.write
    writes = [0]

    def short_write_then_enospc(fd, payload):
        writes[0] += 1
        if writes[0] == 1:
            return real_write(fd, payload[:32])
        raise OSError(errno.ENOSPC, "disk full")

    with monkeypatch.context() as patcher:
        patcher.setattr(predictions.os, "write", short_write_then_enospc)
        with pytest.raises(predictions.PredictionLedgerError) as exc_info:
            ledger.create(request)

    assert exc_info.value.code == "prediction_ledger_io_error"
    assert exc_info.value.retryable is True
    assert not (tmp_path / "entries.jsonl").exists()

    created = ledger.create(request)

    assert ledger.list() == [created]
    assert len((tmp_path / "entries.jsonl").read_text().splitlines()) == 1


def test_lock_contention_returns_a_finite_retryable_busy_error(tmp_path) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
        lock_timeout_seconds=0.02,
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )

    with (tmp_path / ".ledger.lock").open("r+") as lock_file:
        predictions.fcntl.flock(lock_file.fileno(), predictions.fcntl.LOCK_EX)
        with pytest.raises(predictions.PredictionLedgerError) as exc_info:
            ledger.list()
        predictions.fcntl.flock(lock_file.fileno(), predictions.fcntl.LOCK_UN)

    assert exc_info.value.code == "prediction_ledger_busy"
    assert exc_info.value.retryable is True


def test_not_ready_stays_open_and_scored_rerun_does_not_read_prices(
    tmp_path,
) -> None:
    now = ["2026-07-11T04:00:00Z"]
    outcome_available = [False]
    calls = []

    def run_history(symbols, start, end):
        calls.append((symbols, start, end))
        rows = [{"date": "2026-07-10", "close": 100.0}]
        if outcome_available[0]:
            rows.append({"date": "2026-07-14", "close": 110.0})
        return 0, _history_payload(start=start, end=end, rows=rows)

    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=run_history,
        now=lambda: now[0],
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-14",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    now[0] = "2026-07-16T04:00:00Z"

    not_ready = ledger.reconcile_due()

    assert not_ready["results"][0]["status"] == "not_ready"
    assert ledger.list()[0]["status"] == "open"
    assert len((tmp_path / "entries.jsonl").read_text().splitlines()) == 1

    outcome_available[0] = True
    scored = ledger.reconcile_due()
    calls_after_score = len(calls)
    repeated = ledger.reconcile_due()

    assert scored["results"][0]["status"] == "scored"
    assert repeated["results"] == []
    assert len(calls) == calls_after_score
    assert len((tmp_path / "entries.jsonl").read_text().splitlines()) == 2


def test_list_maps_exists_permission_failure_to_stable_io_error(
    tmp_path,
    monkeypatch,
) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (1, ""),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    original_exists = Path.exists

    def denied_exists(path):
        if path == ledger.entries_path:
            raise PermissionError("denied")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", denied_exists)

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_io_error"
    assert exc_info.value.retryable is True


def test_list_does_not_recreate_a_missing_ledger_lock(tmp_path) -> None:
    ledger = predictions.PredictionLedger(
        tmp_path,
        run_history=lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
        now=lambda: "2026-07-11T04:00:00Z",
    )
    ledger.create(
        {
            "symbol": "AAPL",
            "direction": "up",
            "horizon_date": "2026-07-17",
            "confidence": 0.7,
            "falsifier": "The first eligible close is below 95.",
        }
    )
    before = (tmp_path / "entries.jsonl").read_bytes()
    (tmp_path / ".ledger.lock").unlink()

    with pytest.raises(predictions.PredictionLedgerError) as exc_info:
        ledger.list()

    assert exc_info.value.code == "prediction_ledger_corrupt"
    assert not (tmp_path / ".ledger.lock").exists()
    assert (tmp_path / "entries.jsonl").read_bytes() == before
