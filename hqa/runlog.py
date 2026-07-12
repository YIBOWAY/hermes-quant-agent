from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_jsonl(record: dict[str, Any], path: Path) -> None:
    line = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )
    # Validate encoding before opening the append-only artifact. Otherwise a
    # lone surrogate can leave behind a misleading zero-byte file.
    (line + "\n").encode("utf-8", errors="strict")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
