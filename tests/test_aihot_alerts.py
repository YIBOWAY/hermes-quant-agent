from __future__ import annotations

import json

from hqa import aihot_alerts as aa

PAYLOAD = (
    '{"items":['
    '{"title":"big","source":"S","url":"u","publishedAt":"t","category":"industry","score":90},'
    '{"title":"small","source":"S","url":"u2","publishedAt":"t","category":"industry","score":30}]}'
)


def test_select_notable_filters_by_score():
    from hqa import aihot

    items = aihot.parse_items(PAYLOAD)
    notable = aa.select_notable(items, min_score=70)
    assert [i["title"] for i in notable] == ["big"]


def test_select_notable_can_filter_categories():
    from hqa import aihot

    items = aihot.parse_items(PAYLOAD)
    assert aa.select_notable(items, min_score=70, categories=["ai-products"]) == []


def test_run_alerts_when_notable(tmp_path):
    log_path = tmp_path / "aa.jsonl"
    has_alert, message = aa.run(
        run_aihot=lambda: PAYLOAD,
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert has_alert is True
    assert "big" in message
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["job"] == "aihot-alerts"
    assert record["notable"] == ["big"]


def test_run_silent_when_nothing_notable(tmp_path):
    payload = '{"items":[{"title":"small","source":"S","url":"u","publishedAt":"t","category":"c","score":10}]}'
    has_alert, message = aa.run(
        run_aihot=lambda: payload,
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=tmp_path / "aa.jsonl",
    )
    assert has_alert is False
    assert message == ""


def test_main_prints_nothing_when_silent(monkeypatch, capsys, tmp_path):
    payload = '{"items":[{"title":"small","source":"S","url":"u","publishedAt":"t","category":"c","score":10}]}'
    monkeypatch.setattr(aa.aihot, "fetch_items", lambda take=50: payload)
    monkeypatch.setattr(aa.runlog, "utc_now_iso", lambda: "2026-07-01T00:00:00Z")
    rc = aa.main(["--min-score", "70", "--log", str(tmp_path / "aa.jsonl")])
    assert rc == 0
    assert capsys.readouterr().out == ""
