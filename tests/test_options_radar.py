from __future__ import annotations

import json

from hqa import options_radar as orad

SCAN_OUT = "run_date=2026-07-01 universe_size=100 scanned_tickers=100 failed_tickers=0 candidates=1000 data=x meta=y"


def test_build_radar_summary_has_counts():
    text = orad.build_radar_summary(
        {"universe_size": "100", "scanned": "100", "failed": "0", "candidates": "1000"},
        "2026-07-01T00:00:00Z",
        provider="futu",
    )
    assert "Options radar" in text
    assert "provider=futu" in text
    assert "candidates=1000" in text
    assert "proposal-only" in text.lower()


def test_run_logs_and_returns_summary(tmp_path):
    log_path = tmp_path / "or.jsonl"
    text = orad.run(
        run_scan=lambda: (0, SCAN_OUT),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
        provider="futu",
    )
    assert "candidates=1000" in text
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["job"] == "options-radar"
    assert record["provider"] == "futu"
    assert record["options"]["candidates"] == "1000"


def test_main_reads_meta_by_default_without_running_scan(monkeypatch, capsys, tmp_path):
    meta = {
        "run_date": "2026-07-03",
        "universe_size": 2,
        "scanned_tickers": 2,
        "failed_tickers": [],
        "candidate_count": 5,
    }
    (tmp_path / "2026-07-03_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def fail_scan(provider):
        raise AssertionError("fresh scan should require explicit --scan")

    monkeypatch.setattr(orad.quant_cli, "run_options_scan", fail_scan)
    monkeypatch.setattr(orad.runlog, "utc_now_iso", lambda: "2026-07-03T00:00:00Z")
    rc = orad.main(
        [
            "--date",
            "2026-07-03",
            "--scan-dir",
            str(tmp_path),
            "--log",
            str(tmp_path / "options_radar.jsonl"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "candidates=5" in out


def test_main_scan_flag_runs_fresh_scan(monkeypatch, capsys, tmp_path):
    seen = {}
    monkeypatch.setattr(
        orad.quant_cli,
        "run_options_scan",
        lambda provider: seen.update(provider=provider) or (0, SCAN_OUT),
    )
    monkeypatch.setattr(orad.runlog, "utc_now_iso", lambda: "2026-07-03T00:00:00Z")
    rc = orad.main(["--scan", "--provider", "futu", "--log", str(tmp_path / "options_radar.jsonl")])
    assert rc == 0
    assert seen == {"provider": "futu"}
    assert "candidates=1000" in capsys.readouterr().out
