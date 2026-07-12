from __future__ import annotations

import json

from hqa import signal_watchdog as sw

SCAN_OUT = "run_date=2026-07-01 universe_size=100 scanned_tickers=100 failed_tickers=0 candidates=2 data=x meta=y"
LAB_OUT = "universe=etf symbol=QQQ cross_rows=5 timing_rows=5"
CAND_HI = {"ticker": "NVDA", "strategy": "sell_put", "global_score": 91.5, "iv_rank": 0.88, "run_date": "2026-07-01"}
CAND_LO = {"ticker": "KO", "strategy": "covered_call", "global_score": 40.0, "iv_rank": 0.2, "run_date": "2026-07-01"}
CAND_CONTRACT = {
    "ticker": "NVDA",
    "strategy": "sell_put",
    "global_score": 91.5,
    "iv_rank": 0.88,
    "run_date": "2026-07-01",
    "candidate": {
        "symbol": "US.NVDA260717P150000",
        "underlying": "US.NVDA",
    },
}


def test_run_with_thresholds_fires_and_logs(tmp_path):
    log_path = tmp_path / "sw.jsonl"
    has_signal, message = sw.run(
        run_scan=lambda: (0, SCAN_OUT),
        load_candidates=lambda: [CAND_HI, CAND_LO],
        run_factor_lab=lambda: (0, LAB_OUT),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
        min_score=90.0,
        min_iv_rank=0.8,
    )
    assert has_signal is True
    assert "NVDA" in message
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "signal-watchdog"
    assert record["has_signal"] is True
    assert record["mode"] == "alert"
    assert record["score_summary"]["count"] == 2


def test_run_records_structured_signals_without_changing_alert_delivery(tmp_path):
    log_path = tmp_path / "sw.jsonl"
    observed = []

    has_signal, message = sw.run(
        run_scan=lambda: (0, SCAN_OUT),
        load_candidates=lambda: [CAND_HI, CAND_LO],
        run_factor_lab=lambda: (0, LAB_OUT),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
        min_score=90.0,
        record_signal=lambda record: observed.append(record),
    )

    assert has_signal is True
    assert "NVDA" in message
    assert [record["instrument"]["underlying"] for record in observed] == ["NVDA"]
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["opportunity_recorded_count"] == 1
    assert log["opportunity_record_errors"] == []


def test_run_surfaces_ledger_failure_without_suppressing_a_signal(tmp_path):
    log_path = tmp_path / "sw.jsonl"

    def fail_record(_record):
        raise sw.opportunities.OpportunityLedgerError(
            "opportunity_ledger_corrupt",
            "corrupt fixture",
        )

    has_signal, message = sw.run(
        run_scan=lambda: (0, SCAN_OUT),
        load_candidates=lambda: [CAND_HI],
        run_factor_lab=lambda: (0, LAB_OUT),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
        min_score=90.0,
        record_signal=fail_record,
    )

    assert has_signal is True
    assert "NVDA" in message
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["opportunity_recorded_count"] == 0
    assert log["opportunity_record_errors"] == ["opportunity_ledger_corrupt"]


def test_run_collect_mode_is_silent_but_logs_distribution(tmp_path):
    log_path = tmp_path / "sw.jsonl"
    has_signal, message = sw.run(
        run_scan=lambda: (0, SCAN_OUT),
        load_candidates=lambda: [CAND_HI, CAND_LO],
        run_factor_lab=lambda: (0, LAB_OUT),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert has_signal is False
    assert message == ""
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["has_signal"] is False
    assert record["mode"] == "collect"
    assert record["score_summary"]["score_max"] == 91.5  # distribution captured for D-15 review


def test_run_keeps_text_alert_and_logs_structured_signal_records(tmp_path):
    log_path = tmp_path / "sw.jsonl"
    has_signal, message = sw.run(
        run_scan=lambda: (0, SCAN_OUT),
        load_candidates=lambda: [CAND_CONTRACT],
        run_factor_lab=lambda: (0, LAB_OUT),
        now_iso=lambda: "2026-07-01T15:00:00Z",
        log_path=log_path,
        min_score=90.0,
        run_date="2026-07-01",
    )

    assert has_signal is True
    assert "NVDA sell_put" in message
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(record["signals"]) == 1
    assert len(record["signal_records"]) == 1
    structured = record["signal_records"][0]
    assert structured["instrument"]["contract_symbol"] == "US.NVDA260717P150000"
    assert structured["observed_at"] == "2026-07-01T15:00:00Z"


def test_run_logs_artifact_missing_when_no_candidates(tmp_path):
    log_path = tmp_path / "sw.jsonl"
    has_signal, message = sw.run(
        run_scan=lambda: (0, ""),
        load_candidates=lambda: [],
        run_factor_lab=lambda: (0, ""),
        now_iso=lambda: "2026-07-09T00:00:00Z",
        log_path=log_path,
        min_score=150.0,
        run_date="2026-07-09",
    )
    assert has_signal is False
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["artifact_missing"] is True
    assert record["n_candidates"] == 0
    assert record["mode"] == "alert"


def test_main_collect_mode_with_empty_thresholds_file(tmp_path, monkeypatch, capsys):
    # Force collect: point at a missing thresholds file and no CLI overrides.
    monkeypatch.setattr(sw.quant_cli, "run_options_scan", lambda *a, **k: (0, SCAN_OUT))
    monkeypatch.setattr(sw.quant_cli, "run_factor_lab", lambda *a, **k: (0, LAB_OUT))
    monkeypatch.setattr(sw.signals, "load_scan_candidates", lambda *a, **k: [CAND_HI])
    missing = tmp_path / "no_thresholds.json"
    rc = sw.main(
        [
            "--log",
            str(tmp_path / "sw.jsonl"),
            "--thresholds",
            str(missing),
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )
    assert rc == 0
    assert capsys.readouterr().out == ""
    record = json.loads((tmp_path / "sw.jsonl").read_text().splitlines()[0])
    assert record["mode"] == "collect"
    assert record["factor_lab_skipped"] is True  # default: no refresh-lab


def test_main_loads_thresholds_and_can_fire(tmp_path, monkeypatch, capsys):
    thr = tmp_path / "signal_thresholds.json"
    thr.write_text(json.dumps({"min_score": 90, "min_iv_rank": None}), encoding="utf-8")
    monkeypatch.setattr(sw.quant_cli, "run_options_scan", lambda *a, **k: (0, SCAN_OUT))
    monkeypatch.setattr(sw.signals, "load_scan_candidates", lambda *a, **k: [CAND_HI, CAND_LO])
    # score-only threshold: CAND_HI 91.5 fires, CAND_LO 40 does not; iv_rank not required
    rc = sw.main(
        [
            "--log",
            str(tmp_path / "sw.jsonl"),
            "--thresholds",
            str(thr),
            "--date",
            "2026-07-01",
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "NVDA" in out
    record = json.loads((tmp_path / "sw.jsonl").read_text().splitlines()[0])
    assert record["mode"] == "alert"
    assert record["thresholds"]["min_score"] == 90.0
    assert record["thresholds"]["min_iv_rank"] is None


def test_main_default_consumes_artifacts_never_scans(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not scan in artifact mode (D-15)")

    monkeypatch.setattr(sw.quant_cli, "run_options_scan", boom)
    monkeypatch.setattr(sw.quant_cli, "run_factor_lab", boom)  # must not refresh-lab either by default
    monkeypatch.setattr(sw.signals, "load_scan_candidates", lambda *a, **k: [CAND_HI])
    log_path = tmp_path / "sw.jsonl"
    missing = tmp_path / "no_thr.json"
    rc = sw.main(
        [
            "--log",
            str(log_path),
            "--thresholds",
            str(missing),
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )
    assert rc == 0
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["n_candidates"] == 1  # artifacts consumed, no subprocess scan
    assert record["factor_lab_skipped"] is True


def test_main_survives_exception_and_returns_zero(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("scan blew up")

    monkeypatch.setattr(sw.quant_cli, "run_options_scan", boom)
    rc = sw.main(
        [
            "--scan",
            "--log",
            str(tmp_path / "sw.jsonl"),
            "--thresholds",
            str(tmp_path / "x.json"),
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )
    assert rc == 0
