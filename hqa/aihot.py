from __future__ import annotations

import json
import urllib.request
from typing import Any, Optional

BASE_URL = "https://aihot.virxact.com"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_ITEM_FIELDS = ("title", "source", "url", "publishedAt", "category", "score")


def parse_items(payload: str) -> list[dict[str, Any]]:
    data = json.loads(payload)
    return [{k: item.get(k) for k in _ITEM_FIELDS} for item in data.get("items", [])]


def fetch_items(
    since: Optional[str] = None,
    take: int = 20,
    base_url: str = BASE_URL,
    ua: str = BROWSER_UA,
    timeout: int = 20,
) -> str:
    url = f"{base_url}/api/public/items?mode=selected&take={int(take)}"
    if since:
        url += f"&since={since}"
    request = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https host, GET only)
        return response.read().decode("utf-8")
