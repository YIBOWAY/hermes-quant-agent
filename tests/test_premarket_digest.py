from __future__ import annotations

import json

from hqa import premarket_digest as pd

DOCTOR_SAMPLE = """Quant System local health
safety.dry_run=true
safety.paper_trading=true
safety.live_trading_enabled=false
safety.kill_switch=true
"""

SCAN_SAMPLE = """dry_run=false provider=sample top=100 strategies=sell_put,covered_call output_dir=data/options_scans
market_regime=Unknown reason=no_vix_history
run_date=2026-07-01 universe_size=100 scanned_tickers=100 failed_tickers=0 candidates=1000 data=data/options_scans/2026-07-01.jsonl meta=data/options_scans/2026-07-01_meta.json
"""


def test_parse_scan_summary_extracts_counts():
    scan = pd.parse_scan_summary(SCAN_SAMPLE)
    assert scan == {
        "run_date": "2026-07-01",
        "universe_size": "100",
        "scanned": "100",
        "failed": "0",
        "candidates": "1000",
    }


def test_parse_scan_summary_missing_returns_empty():
    assert pd.parse_scan_summary("no summary here") == {}


def test_build_digest_nominal_mentions_counts_and_safety():
    from hqa.doctor_watchdog import parse_safety

    text = pd.build_digest(parse_safety(DOCTOR_SAMPLE), pd.parse_scan_summary(SCAN_SAMPLE), "2026-07-01T00:00:00Z")
    assert "NOMINAL" in text
    assert "candidates=1000" in text
    assert "read-only" in text.lower()


def test_build_digest_flags_safety_deviation():
    from hqa.doctor_watchdog import parse_safety

    bad = parse_safety(DOCTOR_SAMPLE.replace("dry_run=true", "dry_run=false"))
    text = pd.build_digest(bad, {}, "2026-07-01T00:00:00Z")
    assert "DEVIATION" in text


def test_run_writes_log_and_returns_digest(tmp_path):
    log_path = tmp_path / "digest.jsonl"
    text = pd.run(
        run_doctor=lambda: (0, DOCTOR_SAMPLE),
        run_scan=lambda: (0, SCAN_SAMPLE),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert "Pre-market digest" in text
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "premarket-digest"
    assert record["options"]["candidates"] == "1000"


def test_main_survives_exception_and_returns_zero(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("scan blew up")

    monkeypatch.setattr(pd.quant_cli, "run_doctor", boom)
    log_path = tmp_path / "digest.jsonl"
    rc = pd.main(["--log", str(log_path)])
    assert rc == 0
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "premarket-digest"
    assert "error" in record


def test_build_digest_includes_headlines_when_provided():
    from hqa.doctor_watchdog import parse_safety

    heads = [{"title": "Meta compute", "source": "TC", "url": "u", "publishedAt": "t", "category": "industry", "score": 72}]
    text = pd.build_digest(parse_safety(DOCTOR_SAMPLE), pd.parse_scan_summary(SCAN_SAMPLE), "2026-07-01T00:00:00Z", headlines=heads)
    assert "AI headlines" in text
    assert "Meta compute" in text


def test_run_with_aihot_logs_titles_not_payload(tmp_path):
    import json

    log_path = tmp_path / "d.jsonl"
    payload = '{"items":[{"title":"H1","source":"S","url":"u","publishedAt":"t","category":"c","score":9}]}'
    text = pd.run(
        run_doctor=lambda: (0, DOCTOR_SAMPLE),
        run_scan=lambda: (0, SCAN_SAMPLE),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
        run_aihot=lambda: payload,
    )
    assert "H1" in text
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["headlines"] == ["H1"]           # titles only
    assert "items" not in json.dumps(record)       # no raw payload persisted


def test_build_digest_degraded_label_on_futu_empty_scan():
    from hqa.doctor_watchdog import parse_safety

    text = pd.build_digest(parse_safety(DOCTOR_SAMPLE), {}, "2026-07-01T00:00:00Z", provider="futu")
    assert "Options radar (futu)" in text
    assert "DEGRADED" in text
