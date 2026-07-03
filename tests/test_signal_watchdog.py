from __future__ import annotations

import json

from hqa import signal_watchdog as sw

SCAN_OUT = "run_date=2026-07-01 universe_size=100 scanned_tickers=100 failed_tickers=0 candidates=2 data=x meta=y"
LAB_OUT = "universe=etf symbol=QQQ cross_rows=5 timing_rows=5"
CAND_HI = {"ticker": "NVDA", "strategy": "sell_put", "global_score": 91.5, "iv_rank": 0.88, "run_date": "2026-07-01"}
CAND_LO = {"ticker": "KO", "strategy": "covered_call", "global_score": 40.0, "iv_rank": 0.2, "run_date": "2026-07-01"}


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
    assert record["score_summary"]["count"] == 2


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
    assert record["score_summary"]["score_max"] == 91.5  # distribution captured for D-15 review


def test_main_collect_mode_emits_empty_stdout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sw.quant_cli, "run_options_scan", lambda *a, **k: (0, SCAN_OUT))
    monkeypatch.setattr(sw.quant_cli, "run_factor_lab", lambda *a, **k: (0, LAB_OUT))
    monkeypatch.setattr(sw.signals, "load_scan_candidates", lambda *a, **k: [CAND_HI])
    rc = sw.main(["--log", str(tmp_path / "sw.jsonl")])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_main_default_consumes_artifacts_never_scans(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not scan in artifact mode (D-15)")

    monkeypatch.setattr(sw.quant_cli, "run_options_scan", boom)
    monkeypatch.setattr(sw.quant_cli, "run_factor_lab", lambda *a, **k: (0, LAB_OUT))
    monkeypatch.setattr(sw.signals, "load_scan_candidates", lambda *a, **k: [CAND_HI])
    log_path = tmp_path / "sw.jsonl"
    rc = sw.main(["--log", str(log_path)])
    assert rc == 0
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["n_candidates"] == 1  # artifacts consumed, no subprocess scan


def test_main_survives_exception_and_returns_zero(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("scan blew up")

    monkeypatch.setattr(sw.quant_cli, "run_options_scan", boom)
    rc = sw.main(["--scan", "--log", str(tmp_path / "sw.jsonl")])
    assert rc == 0
