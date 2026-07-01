from __future__ import annotations

import json

from hqa import doctor_watchdog as dw

DOCTOR_SAMPLE = """Quant System local health
environment=local
safety.dry_run=true
safety.paper_trading=true
safety.live_trading_enabled=false
safety.kill_switch=true
data.default_provider=futu
runtime.log=data/_runtime/logs/backend.jsonl
"""


def test_parse_safety_extracts_four_invariants():
    safety = dw.parse_safety(DOCTOR_SAMPLE)
    assert safety == {
        "dry_run": "true",
        "paper_trading": "true",
        "live_trading_enabled": "false",
        "kill_switch": "true",
    }


def test_evaluate_nominal_is_silent():
    safety = dw.parse_safety(DOCTOR_SAMPLE)
    alert, deviations = dw.evaluate(safety, exit_code=0)
    assert alert is False
    assert deviations == []


def test_evaluate_flags_live_trading_enabled():
    safety = dw.parse_safety(DOCTOR_SAMPLE.replace("live_trading_enabled=false", "live_trading_enabled=true"))
    alert, deviations = dw.evaluate(safety, exit_code=0)
    assert alert is True
    assert any("live_trading_enabled=true" in d for d in deviations)


def test_evaluate_flags_nonzero_exit():
    safety = dw.parse_safety(DOCTOR_SAMPLE)
    alert, deviations = dw.evaluate(safety, exit_code=1)
    assert alert is True
    assert any("doctor exited 1" in d for d in deviations)


def test_run_nominal_writes_log_and_stays_silent(tmp_path):
    log_path = tmp_path / "wd.jsonl"
    alert, message = dw.run(
        run_doctor=lambda: (0, DOCTOR_SAMPLE),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert alert is False
    assert message == ""
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "doctor-watchdog"
    assert record["alert"] is False
    assert record["safety"]["live_trading_enabled"] == "false"


def test_run_deviation_returns_alert_message(tmp_path):
    log_path = tmp_path / "wd.jsonl"
    flipped = DOCTOR_SAMPLE.replace("kill_switch=true", "kill_switch=false")
    alert, message = dw.run(
        run_doctor=lambda: (0, flipped),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert alert is True
    assert "kill_switch=false" in message
    assert "[HQA][ALERT]" in message
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["alert"] is True
