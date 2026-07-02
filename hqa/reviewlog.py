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


def confirm(
    entry_id: str,
    review_dir: Path,
    *,
    judgment: str,
    basis: str,
    result: str,
    failure_point: str,
    next_rule: str,
) -> bool:
    entries = load_entries(review_dir)
    found = False
    for entry in entries:
        if entry["id"] == entry_id:
            entry.update(
                judgment=judgment,
                basis=basis,
                result=result,
                failure_point=failure_point,
                next_rule=next_rule,
                status="confirmed",
            )
            found = True
            break
    if found:
        _write_entries(entries, review_dir)
    return found


def list_entries(review_dir: Path, status: Optional[str] = None) -> list[dict[str, Any]]:
    entries = load_entries(review_dir)
    if status is not None:
        entries = [e for e in entries if e.get("status") == status]
    return entries


def render_markdown(review_dir: Path) -> str:
    entries = sorted(load_entries(review_dir), key=lambda e: e["ts"], reverse=True)
    lines = ["# Review Log", ""]
    for e in entries:
        lines.append(f"## {e['id']} · {e['kind']} · {e['status']} · {e['ts']}")
        lines.append(f"- event: {e.get('event', '')}")
        lines.append(f"- data: {e.get('data', '')}")
        for f in HUMAN_FIELDS:
            lines.append(f"- {f}: {e.get(f, '')}")
        lines.append("")
    return "\n".join(lines)


def write_markdown(review_dir: Path) -> Path:
    path = review_dir / "entries.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(review_dir), encoding="utf-8")
    return path
