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

# Pure-JSON doctor output (platform already emits this as the last line; may
# someday be the only line). Bools must normalize to lowercase strings.
DOCTOR_JSON_ONLY = json.dumps(
    {
        "environment": "local",
        "ok": True,
        "safety": {
            "dry_run": True,
            "kill_switch": True,
            "live_trading_enabled": False,
            "paper_trading": True,
        },
    }
)

DOCTOR_TEXT_PLUS_JSON = DOCTOR_SAMPLE.rstrip() + "\n" + DOCTOR_JSON_ONLY + "\n"


def test_parse_safety_extracts_four_invariants_from_text():
    safety = dw.parse_safety(DOCTOR_SAMPLE)
    assert safety == {
        "dry_run": "true",
        "paper_trading": "true",
        "live_trading_enabled": "false",
        "kill_switch": "true",
    }


def test_parse_safety_json_first_pure_json_no_false_alarm():
    safety = dw.parse_safety(DOCTOR_JSON_ONLY)
    assert safety == {
        "dry_run": "true",
        "paper_trading": "true",
        "live_trading_enabled": "false",
        "kill_switch": "true",
    }
    alert, deviations, channel = dw.evaluate(safety, exit_code=0)
    assert alert is False
    assert deviations == []
    assert channel == "none"


def test_parse_safety_json_first_prefers_trailing_json_over_stale_text():
    # Text claims live=true but trailing JSON is nominal — JSON wins (audit F1).
    stale_text = DOCTOR_SAMPLE.replace(
        "live_trading_enabled=false", "live_trading_enabled=true"
    )
    mixed = stale_text.rstrip() + "\n" + DOCTOR_JSON_ONLY + "\n"
    safety = dw.parse_safety(mixed)
    assert safety["live_trading_enabled"] == "false"


def test_evaluate_nominal_is_silent():
    safety = dw.parse_safety(DOCTOR_SAMPLE)
    alert, deviations, channel = dw.evaluate(safety, exit_code=0)
    assert alert is False
    assert deviations == []
    assert channel == "none"


def test_evaluate_flags_live_trading_enabled_as_safety():
    safety = dw.parse_safety(
        DOCTOR_SAMPLE.replace("live_trading_enabled=false", "live_trading_enabled=true")
    )
    alert, deviations, channel = dw.evaluate(safety, exit_code=0)
    assert alert is True
    assert channel == "safety"
    assert any("live_trading_enabled=true" in d for d in deviations)
    assert any(d.startswith("[SAFETY]") for d in deviations)


def test_evaluate_nonzero_exit_with_empty_safety_is_infra_only():
    # Classic false-alarm path: doctor crashed → no safety lines → used to
    # also report every key as "missing". Now pure infra.
    alert, deviations, channel = dw.evaluate({}, exit_code=1)
    assert alert is True
    assert channel == "infra"
    assert any("doctor exited 1" in d for d in deviations)
    assert not any("missing" in d for d in deviations)
    assert all(d.startswith("[INFRA]") for d in deviations)


def test_evaluate_nonzero_exit_with_parsed_safety_is_mixed_or_infra():
    safety = dw.parse_safety(DOCTOR_SAMPLE)
    alert, deviations, channel = dw.evaluate(safety, exit_code=1)
    assert alert is True
    assert channel == "infra"  # safety keys ok; only exit is bad
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
    assert record["channel"] == "none"
    assert record["safety"]["live_trading_enabled"] == "false"


def test_run_json_only_nominal_is_silent(tmp_path):
    log_path = tmp_path / "wd.jsonl"
    alert, message = dw.run(
        run_doctor=lambda: (0, DOCTOR_JSON_ONLY),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert alert is False
    assert message == ""
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["channel"] == "none"
    assert record["safety"]["dry_run"] == "true"


def test_run_deviation_returns_safety_alert_message(tmp_path):
    log_path = tmp_path / "wd.jsonl"
    flipped = DOCTOR_SAMPLE.replace("kill_switch=true", "kill_switch=false")
    alert, message = dw.run(
        run_doctor=lambda: (0, flipped),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert alert is True
    assert "kill_switch=false" in message
    assert "[SAFETY]" in message
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["alert"] is True
    assert record["channel"] == "safety"


def test_run_infra_failure_uses_infra_tag(tmp_path):
    log_path = tmp_path / "wd.jsonl"
    alert, message = dw.run(
        run_doctor=lambda: (1, "Traceback: boom\n"),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert alert is True
    assert "[INFRA]" in message
    assert "missing" not in message
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["channel"] == "infra"


def test_main_nominal_emits_empty_stdout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dw.quant_cli, "run_doctor", lambda *a, **k: (0, DOCTOR_SAMPLE))
    rc = dw.main(["--log", str(tmp_path / "wd.jsonl")])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_main_survives_exception_and_returns_zero(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("doctor blew up")

    monkeypatch.setattr(dw.quant_cli, "run_doctor", boom)
    log_path = tmp_path / "wd.jsonl"
    rc = dw.main(["--log", str(log_path)])
    assert rc == 0
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "doctor-watchdog"
    assert "error" in record
    assert record.get("channel") == "infra"


def test_run_alert_autodrafts_review_entry(tmp_path):
    from hqa import reviewlog

    log_path = tmp_path / "wd.jsonl"
    review_dir = tmp_path / "review"
    flipped = DOCTOR_SAMPLE.replace("live_trading_enabled=false", "live_trading_enabled=true")
    dw.run(
        run_doctor=lambda: (0, flipped),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
        review_dir=review_dir,
    )
    entries = reviewlog.load_entries(review_dir)
    assert len(entries) == 1
    assert entries[0]["kind"] == "alert"
    assert entries[0]["status"] == "draft"
    for f in reviewlog.HUMAN_FIELDS:
        assert entries[0][f] == ""


def test_run_infra_autodrafts_infra_kind(tmp_path):
    from hqa import reviewlog

    review_dir = tmp_path / "review"
    dw.run(
        run_doctor=lambda: (1, "crash"),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=tmp_path / "wd.jsonl",
        review_dir=review_dir,
    )
    entries = reviewlog.load_entries(review_dir)
    assert len(entries) == 1
    assert entries[0]["kind"] == "infra"
    assert entries[0]["event"] == "doctor-infra failure"


def test_run_alert_autodraft_is_idempotent_same_day(tmp_path):
    from hqa import reviewlog

    review_dir = tmp_path / "review"
    flipped = DOCTOR_SAMPLE.replace("kill_switch=true", "kill_switch=false")
    for _ in range(3):
        dw.run(
            run_doctor=lambda: (0, flipped),
            now_iso=lambda: "2026-07-01T00:00:00Z",
            log_path=tmp_path / "wd.jsonl",
            review_dir=review_dir,
        )
    assert len(reviewlog.load_entries(review_dir)) == 1


def test_run_nominal_does_not_draft(tmp_path):
    from hqa import reviewlog

    review_dir = tmp_path / "review"
    dw.run(
        run_doctor=lambda: (0, DOCTOR_SAMPLE),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=tmp_path / "wd.jsonl",
        review_dir=review_dir,
    )
    assert reviewlog.load_entries(review_dir) == []


def test_run_text_plus_json_nominal(tmp_path):
    log_path = tmp_path / "wd.jsonl"
    alert, message = dw.run(
        run_doctor=lambda: (0, DOCTOR_TEXT_PLUS_JSON),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert alert is False
    assert message == ""
