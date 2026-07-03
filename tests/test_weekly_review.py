from __future__ import annotations

from hqa import reviewlog, weekly_review as wr


def test_build_report_counts_sections():
    text = wr.build_report(
        alerts=[{"ts": "t"}],
        signals_fired=[{"ts": "t"}, {"ts": "t"}],
        reviews=[{"id": "2026-07-01-001", "status": "confirmed", "event": "bad exit", "next_rule": "wait"}],
        ts="2026-07-01T00:00:00Z",
    )
    assert "Weekly review" in text
    assert "safety alerts: 1" in text
    assert "signals fired: 2" in text
    assert "bad exit" in text


def test_run_reads_review_and_run_logs(tmp_path):
    review_dir = tmp_path / "review"
    reviewlog.new_draft("manual", "missed NVDA", {}, "manual", "2026-07-01T00:00:00Z", review_dir)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "doctor_watchdog.jsonl").write_text('{"job":"doctor-watchdog","alert":true}\n', encoding="utf-8")
    (log_dir / "signal_watchdog.jsonl").write_text('{"job":"signal-watchdog","has_signal":true}\n', encoding="utf-8")
    text = wr.run(review_dir=review_dir, log_dir=log_dir, now_iso=lambda: "2026-07-08T00:00:00Z")
    assert "safety alerts: 1" in text
    assert "signals fired: 1" in text
    assert "missed NVDA" in text
