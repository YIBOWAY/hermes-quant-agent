from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Optional

from hqa import config, reviewlog, runlog


def load_runlog(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_report(alerts: list[dict], signals_fired: list[dict], reviews: list[dict], ts: str) -> str:
    lines = [
        f"[HQA] Weekly review {ts}",
        f"- safety alerts: {len(alerts)}",
        f"- signals fired: {len(signals_fired)}",
        f"- review entries: {len(reviews)}",
    ]
    for r in reviews:
        lines.append(f"  · {r.get('id', '?')} [{r.get('status', '?')}] {r.get('event', '')} → next: {r.get('next_rule', '')}")
    lines.append("Scope: read-only weekly summary. Proposal-only.")
    return "\n".join(lines)


def run(review_dir: Path, log_dir: Path, now_iso: Callable[[], str]) -> str:
    reviews = reviewlog.list_entries(review_dir)
    watchdog = load_runlog(log_dir / "doctor_watchdog.jsonl")
    signal = load_runlog(log_dir / "signal_watchdog.jsonl")
    alerts = [r for r in watchdog if r.get("alert")]
    signals_fired = [r for r in signal if r.get("has_signal")]
    return build_report(alerts, signals_fired, reviews, now_iso())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA weekly review (read-only, proposal-only)")
    parser.add_argument("--review-dir", default=str(config.REVIEW_DIR))
    parser.add_argument("--log-dir", default=str(config.LOG_DIR))
    args = parser.parse_args(argv)
    try:
        report = run(Path(args.review_dir), Path(args.log_dir), runlog.utc_now_iso)
    except Exception as exc:
        ts = runlog.utc_now_iso()
        print(f"[HQA] Weekly review {ts}: FAILED ({exc!r})")
        return 0
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
