from __future__ import annotations

import json

from hqa import reviewlog


def test_new_draft_writes_machine_fields_and_empty_human_fields(tmp_path):
    entry_id = reviewlog.new_draft(
        kind="manual", event="missed NVDA breakout", data={"rid": "r1"},
        source="manual", ts="2026-07-01T00:00:00Z", review_dir=tmp_path,
    )
    entries = reviewlog.load_entries(tmp_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["id"] == entry_id
    assert e["status"] == "draft"
    assert e["event"] == "missed NVDA breakout"
    assert e["data"] == {"rid": "r1"}
    for f in reviewlog.HUMAN_FIELDS:
        assert e[f] == ""


def test_new_draft_sequential_ids_same_day(tmp_path):
    a = reviewlog.new_draft("manual", "e1", {}, "s", "2026-07-01T01:00:00Z", tmp_path)
    b = reviewlog.new_draft("manual", "e2", {}, "s", "2026-07-01T02:00:00Z", tmp_path)
    assert a == "2026-07-01-001"
    assert b == "2026-07-01-002"


def test_new_draft_is_idempotent_by_fingerprint(tmp_path):
    fp = "2026-07-01:kill_switch=false"
    id1 = reviewlog.new_draft("alert", "e", {}, "wd", "2026-07-01T01:00:00Z", tmp_path, fingerprint=fp)
    id2 = reviewlog.new_draft("alert", "e", {}, "wd", "2026-07-01T02:00:00Z", tmp_path, fingerprint=fp)
    assert id1 == id2
    assert len(reviewlog.load_entries(tmp_path)) == 1


def test_load_entries_missing_returns_empty(tmp_path):
    assert reviewlog.load_entries(tmp_path / "nope") == []
