from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable, Optional

from hqa import aihot, config, runlog


def select_notable(
    items: list[dict[str, Any]],
    min_score: int = 70,
    categories: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        score = item.get("score") or 0
        if score >= min_score and (categories is None or item.get("category") in categories):
            result.append(item)
    return result


def run(
    run_aihot: Callable[[], str],
    now_iso: Callable[[], str],
    log_path: Path,
    min_score: int = 70,
    categories: Optional[list[str]] = None,
) -> tuple[bool, str]:
    items = aihot.parse_items(run_aihot())
    notable = select_notable(items, min_score=min_score, categories=categories)
    ts = now_iso()
    runlog.append_jsonl(
        {
            "ts": ts,
            "job": "aihot-alerts",
            "min_score": min_score,
            "categories": categories,
            "notable": [item.get("title") for item in notable],
        },
        log_path,
    )
    if not notable:
        return False, ""
    lines = [f"[HQA] AI HOT alerts {ts}"]
    for item in notable[:8]:
        lines.append(
            f"  - [{item.get('category', '?')}/{item.get('score', '?')}] "
            f"{item.get('title', '?')} ({item.get('source', '?')})"
        )
    return True, "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA AI-HOT alerts watchdog ([SILENT] unless notable)")
    parser.add_argument("--min-score", type=int, default=70)
    parser.add_argument("--category", action="append", dest="categories", default=None)
    parser.add_argument("--log", default=str(config.LOG_DIR / "aihot_alerts.jsonl"))
    args = parser.parse_args(argv)

    log_path = Path(args.log)
    try:
        has_alert, message = run(
            lambda: aihot.fetch_items(take=50),
            runlog.utc_now_iso,
            log_path,
            min_score=args.min_score,
            categories=args.categories,
        )
    except Exception as exc:  # unattended job: never crash the scheduler
        ts = runlog.utc_now_iso()
        runlog.append_jsonl({"ts": ts, "job": "aihot-alerts", "error": repr(exc)}, log_path)
        print(f"[HQA] AI HOT alerts failed to run {ts}: {exc!r}")
        return 0
    if has_alert:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
