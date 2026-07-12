from __future__ import annotations

import json

from hqa import prediction_cli as cli


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


def test_create_outputs_one_json_prediction_document(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.setattr(cli.runlog, "utc_now_iso", lambda: "2026-07-11T04:00:00Z")
    monkeypatch.setattr(
        cli.quant_cli,
        "run_historical_prices",
        lambda symbols, start, end: (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        ),
    )

    rc = cli.main(
        [
            "create",
            "--symbol",
            "AAPL",
            "--subject",
            "苹果公司",
            "--direction",
            "up",
            "--horizon-date",
            "2026-07-17",
            "--confidence",
            "0.7",
            "--falsifier",
            "首个合资格收盘价低于 95。",
            "--prediction-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    document = json.loads(captured.out)
    assert document["id"] == "2026-07-11-001"
    assert document["status"] == "open"
    assert document["subject"] == "苹果公司"
    assert captured.out.count("\n") == 1


def test_list_outputs_one_json_array_without_reading_prices(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.setattr(cli.runlog, "utc_now_iso", lambda: "2026-07-11T04:00:00Z")
    calls = []

    def run_history(symbols, start, end):
        calls.append((symbols, start, end))
        return (
            0,
            _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            ),
        )

    monkeypatch.setattr(cli.quant_cli, "run_historical_prices", run_history)
    common = ["--prediction-dir", str(tmp_path)]
    assert (
        cli.main(
            [
                "create",
                "--symbol",
                "AAPL",
                "--direction",
                "up",
                "--horizon-date",
                "2026-07-17",
                "--confidence",
                "0.7",
                "--falsifier",
                "below 95",
                *common,
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert cli.main(["list", "--status", "open", *common]) == 0

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert captured.err == ""
    assert [row["id"] for row in document] == ["2026-07-11-001"]
    assert calls == [(["AAPL"], "2026-06-30", "2026-07-10")]
    assert captured.out.count("\n") == 1


def test_reconcile_outputs_one_json_report(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(cli.runlog, "utc_now_iso", lambda: "2026-07-11T04:00:00Z")
    calls = []

    def run_history(symbols, start, end):
        calls.append((symbols, start, end))
        rows = (
            [{"date": "2026-07-10", "close": 100.0}]
            if len(calls) == 1
            else [
                {"date": "2026-07-10", "close": 50.0},
                {"date": "2026-07-14", "close": 55.0},
            ]
        )
        return 0, _history_payload(start=start, end=end, rows=rows)

    monkeypatch.setattr(cli.quant_cli, "run_historical_prices", run_history)
    prediction_dir = ["--prediction-dir", str(tmp_path)]
    assert (
        cli.main(
            [
                "create",
                "--symbol",
                "AAPL",
                "--direction",
                "up",
                "--horizon-date",
                "2026-07-14",
                "--confidence",
                "0.7",
                "--falsifier",
                "below 95",
                *prediction_dir,
            ]
        )
        == 0
    )
    capsys.readouterr()

    rc = cli.main(
        [
            "reconcile",
            "--as-of",
            "2026-07-16T04:00:00Z",
            "--limit",
            "1",
            *prediction_dir,
        ]
    )

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert rc == 0
    assert captured.err == ""
    assert document["status"] == "available"
    assert document["results"] == [
        {
            "id": "2026-07-11-001",
            "outcome_session_date": "2026-07-14",
            "status": "scored",
        }
    ]
    assert captured.out.count("\n") == 1


def test_argparse_failure_is_one_json_error_document(capsys) -> None:
    rc = cli.main(["create", "--symbol", "AAPL"])

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    error = json.loads(captured.out)["error"]
    assert error["code"] == "prediction_invalid_arguments"
    assert error["retryable"] is False
    for flag in ("--direction", "--horizon-date", "--confidence", "--falsifier"):
        assert flag in error["message"]
    assert captured.out.count("\n") == 1


def test_invalid_prediction_is_json_error_and_does_not_call_futu(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    def unexpected_history(*args, **kwargs):
        raise AssertionError("invalid request must not read prices")

    monkeypatch.setattr(cli.quant_cli, "run_historical_prices", unexpected_history)

    rc = cli.main(
        [
            "create",
            "--symbol",
            "AAPL",
            "--direction",
            "sideways",
            "--horizon-date",
            "2026-07-17",
            "--confidence",
            "0.7",
            "--falsifier",
            "below 95",
            "--prediction-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "prediction_invalid_request",
            "message": "direction must be one of: down, flat, up",
            "retryable": False,
        }
    }
    assert not (tmp_path / "entries.jsonl").exists()


def test_operational_failure_is_one_retryable_json_error(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        cli.quant_cli,
        "run_historical_prices",
        lambda symbols, start, end: (1, ""),
    )

    rc = cli.main(
        [
            "create",
            "--symbol",
            "AAPL",
            "--direction",
            "up",
            "--horizon-date",
            "2026-07-17",
            "--confidence",
            "0.7",
            "--falsifier",
            "below 95",
            "--prediction-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "prediction_entry_price_unavailable",
            "message": "strict Futu entry history is unavailable",
            "retryable": True,
        }
    }
    assert captured.out.count("\n") == 1


def test_degraded_reconcile_outputs_report_and_returns_one(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.setattr(cli.runlog, "utc_now_iso", lambda: "2026-07-11T04:00:00Z")
    calls = 0

    def run_history(symbols, start, end):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 0, _history_payload(
                start=start,
                end=end,
                rows=[{"date": "2026-07-10", "close": 100.0}],
            )
        return 1, ""

    monkeypatch.setattr(cli.quant_cli, "run_historical_prices", run_history)
    prediction_dir = ["--prediction-dir", str(tmp_path)]
    assert (
        cli.main(
            [
                "create",
                "--symbol",
                "AAPL",
                "--direction",
                "up",
                "--horizon-date",
                "2026-07-14",
                "--confidence",
                "0.7",
                "--falsifier",
                "below 95",
                *prediction_dir,
            ]
        )
        == 0
    )
    capsys.readouterr()

    rc = cli.main(
        [
            "reconcile",
            "--as-of",
            "2026-07-16T04:00:00Z",
            *prediction_dir,
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert rc == 1
    assert captured.err == ""
    assert report["status"] == "degraded"
    assert report["results"][0]["status"] == "unavailable"
    assert report["results"][0]["reason"] == "prediction_history_unavailable"
    assert "error" not in report


def test_idempotency_conflict_is_a_usage_error_without_second_price_read(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    calls = 0

    def run_history(symbols, start, end):
        nonlocal calls
        calls += 1
        return 0, _history_payload(
            start=start,
            end=end,
            rows=[{"date": "2026-07-10", "close": 100.0}],
        )

    monkeypatch.setattr(cli.runlog, "utc_now_iso", lambda: "2026-07-11T04:00:00Z")
    monkeypatch.setattr(cli.quant_cli, "run_historical_prices", run_history)
    base = [
        "--symbol",
        "AAPL",
        "--horizon-date",
        "2026-07-17",
        "--confidence",
        "0.7",
        "--falsifier",
        "below 95",
        "--request-id",
        "hermes-turn-42",
        "--prediction-dir",
        str(tmp_path),
    ]
    assert cli.main(["create", "--direction", "up", *base]) == 0
    capsys.readouterr()

    rc = cli.main(["create", "--direction", "down", *base])

    captured = capsys.readouterr()
    error = json.loads(captured.out)["error"]
    assert rc == 2
    assert captured.err == ""
    assert error["code"] == "prediction_idempotency_conflict"
    assert error["retryable"] is False
    assert calls == 1


def test_list_uses_configured_prediction_directory_by_default(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.setattr(cli.config, "PREDICTION_DIR", tmp_path)

    rc = cli.main(["list"])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    assert json.loads(captured.out) == []


def test_invalid_unicode_is_rejected_before_stdout_serialization(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    def unexpected_history(*args, **kwargs):
        raise AssertionError("invalid unicode must not read prices")

    monkeypatch.setattr(cli.quant_cli, "run_historical_prices", unexpected_history)

    rc = cli.main(
        [
            "create",
            "--symbol",
            "AAPL",
            "--subject",
            "\ud800",
            "--direction",
            "up",
            "--horizon-date",
            "2026-07-17",
            "--confidence",
            "0.7",
            "--falsifier",
            "below 95",
            "--prediction-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    assert json.loads(captured.out)["error"] == {
        "code": "prediction_invalid_request",
        "message": "subject contains invalid unicode",
        "retryable": False,
    }


def test_reconcile_accepts_a_pagination_cursor(capsys, tmp_path) -> None:
    rc = cli.main(
        [
            "reconcile",
            "--as-of",
            "2026-07-16T04:00:00Z",
            "--cursor",
            "2026-07-14|2026-07-11-001",
            "--prediction-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert rc == 0
    assert captured.err == ""
    assert report["status"] == "available"
    assert report["processed_count"] == 0
