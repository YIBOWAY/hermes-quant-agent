from __future__ import annotations

import pytest

from hqa import aihot

SAMPLE = """{
  "count": 2, "hasNext": true, "nextCursor": "x",
  "items": [
    {"id": "a", "title": "Meta 出售算力", "title_en": "Meta compute",
     "url": "https://techcrunch.com/x", "permalink": "p", "source": "TechCrunch",
     "publishedAt": "2026-07-01T13:43:07.000Z", "summary": "...", "category": "industry", "score": 72, "selected": true},
    {"id": "b", "title": "Cloudflare AI 流量", "title_en": "CF",
     "url": "https://blog.cloudflare.com/y", "permalink": "p2", "source": "Cloudflare Blog",
     "publishedAt": "2026-07-01T13:00:00.000Z", "summary": "...", "category": "ai-products", "score": 58, "selected": true}
  ]
}"""


def test_parse_items_extracts_whitelisted_fields():
    items = aihot.parse_items(SAMPLE)
    assert len(items) == 2
    assert items[0] == {
        "title": "Meta 出售算力", "source": "TechCrunch",
        "url": "https://techcrunch.com/x", "publishedAt": "2026-07-01T13:43:07.000Z",
        "category": "industry", "score": 72,
    }
    # never leaks unlisted fields
    assert "summary" not in items[0]


def test_parse_items_empty_payload():
    assert aihot.parse_items('{"items": []}') == []


@pytest.mark.skipif(True, reason="network; flip to run a live smoke test manually")
def test_fetch_items_live_smoke():
    payload = aihot.fetch_items(take=2)
    assert '"items"' in payload
