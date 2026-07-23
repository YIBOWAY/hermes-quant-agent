from __future__ import annotations

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


def test_confirm_fills_human_fields_and_status(tmp_path):
    entry_id = reviewlog.new_draft("manual", "e", {}, "s", "2026-07-01T00:00:00Z", tmp_path)
    ok = reviewlog.confirm(
        entry_id, tmp_path,
        judgment="entered too early", basis="RSI not confirmed",
        result="-2%", failure_point="ignored volume", next_rule="wait for volume confirm",
    )
    assert ok is True
    e = reviewlog.load_entries(tmp_path)[0]
    assert e["status"] == "confirmed"
    assert e["judgment"] == "entered too early"
    assert e["next_rule"] == "wait for volume confirm"


def test_confirm_appends_revision_without_rewriting_jsonl(tmp_path):
    entry_id = reviewlog.new_draft("manual", "e", {}, "s", "2026-07-01T00:00:00Z", tmp_path)
    raw_before = (tmp_path / "entries.jsonl").read_text(encoding="utf-8").splitlines()

    ok = reviewlog.confirm(
        entry_id, tmp_path,
        judgment="j", basis="b", result="r", failure_point="f", next_rule="n",
    )

    assert ok is True
    raw_after = (tmp_path / "entries.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw_before) == 1
    assert len(raw_after) == 2
    entries = reviewlog.load_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["id"] == entry_id
    assert entries[0]["status"] == "confirmed"


def test_confirm_missing_id_returns_false(tmp_path):
    reviewlog.new_draft("manual", "e", {}, "s", "2026-07-01T00:00:00Z", tmp_path)
    assert reviewlog.confirm("nope", tmp_path, judgment="", basis="", result="", failure_point="", next_rule="") is False


def test_list_entries_filters_by_status(tmp_path):
    a = reviewlog.new_draft("manual", "e1", {}, "s", "2026-07-01T00:00:00Z", tmp_path)
    reviewlog.new_draft("manual", "e2", {}, "s", "2026-07-01T01:00:00Z", tmp_path)
    reviewlog.confirm(a, tmp_path, judgment="j", basis="b", result="r", failure_point="f", next_rule="n")
    assert len(reviewlog.list_entries(tmp_path, status="draft")) == 1
    assert len(reviewlog.list_entries(tmp_path, status="confirmed")) == 1
    assert len(reviewlog.list_entries(tmp_path)) == 2


def test_list_entries_filters_by_since_timestamp(tmp_path):
    reviewlog.new_draft("manual", "old", {}, "s", "2026-06-20T00:00:00Z", tmp_path)
    reviewlog.new_draft("manual", "new", {}, "s", "2026-07-03T00:00:00Z", tmp_path)

    entries = reviewlog.list_entries(tmp_path, since="2026-07-01T00:00:00Z")

    assert [e["event"] for e in entries] == ["new"]


def test_write_markdown_is_rebuilt_from_jsonl(tmp_path):
    reviewlog.new_draft("alert", "safety deviation", {"k": "v"}, "wd", "2026-07-01T00:00:00Z", tmp_path)
    path = reviewlog.write_markdown(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "# Review Log" in text
    assert "safety deviation" in text
