from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

MACHINE_FIELDS = ("event", "data", "source")
HUMAN_FIELDS = ("judgment", "basis", "result", "failure_point", "next_rule")


def _entries_path(review_dir: Path) -> Path:
    return review_dir / "entries.jsonl"


def load_entries(review_dir: Path) -> list[dict[str, Any]]:
    path = _entries_path(review_dir)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_entries(entries: list[dict[str, Any]], review_dir: Path) -> None:
    path = _entries_path(review_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def new_draft(
    kind: str,
    event: str,
    data: dict[str, Any],
    source: str,
    ts: str,
    review_dir: Path,
    fingerprint: Optional[str] = None,
) -> str:
    entries = load_entries(review_dir)
    if fingerprint is not None:
        for entry in entries:
            if entry.get("fingerprint") == fingerprint:
                return entry["id"]
    day = ts[:10]
    seq = sum(1 for e in entries if e["id"].startswith(day)) + 1
    entry_id = f"{day}-{seq:03d}"
    record = {
        "id": entry_id,
        "ts": ts,
        "kind": kind,
        "status": "draft",
        "fingerprint": fingerprint,
        "event": event,
        "data": data,
        "source": source,
        "judgment": "",
        "basis": "",
        "result": "",
        "failure_point": "",
        "next_rule": "",
    }
    entries.append(record)
    _write_entries(entries, review_dir)
    return entry_id
