from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

_FACTOR_LAB_RE = re.compile(
    r"symbol=(?P<symbol>\S+).*?cross_rows=(?P<cross_rows>\d+).*?timing_rows=(?P<timing_rows>\d+)",
    re.DOTALL,
)


def parse_factor_lab(output: str) -> dict[str, str]:
    match = _FACTOR_LAB_RE.search(output)
    return match.groupdict() if match else {}


def load_scan_candidates(scan_dir: Path, run_date: str) -> list[dict[str, Any]]:
    path = Path(scan_dir) / f"{run_date}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _percentile(sorted_values: list[float], pct: float) -> Optional[float]:
    if not sorted_values:
        return None
    return sorted_values[int(pct / 100 * (len(sorted_values) - 1))]


def summarize_scores(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    scores = sorted(float(c["global_score"]) for c in candidates if c.get("global_score") is not None)
    iv_known = [c for c in candidates if c.get("iv_rank") is not None]
    return {
        "count": len(candidates),
        "score_max": scores[-1] if scores else None,
        "score_p50": _percentile(scores, 50),
        "score_p90": _percentile(scores, 90),
        "iv_rank_known": len(iv_known),
    }


def evaluate_signals(
    candidates: list[dict[str, Any]],
    min_score: Optional[float] = None,
    min_iv_rank: Optional[float] = None,
) -> tuple[bool, list[str]]:
    if min_score is None and min_iv_rank is None:
        return (False, [])  # collect mode (D-15): thresholds not yet set
    fired: list[str] = []
    for c in candidates:
        score = c.get("global_score")
        iv_rank = c.get("iv_rank")
        if min_score is not None and (score is None or float(score) < min_score):
            continue
        if min_iv_rank is not None and (iv_rank is None or float(iv_rank) < min_iv_rank):
            continue
        fired.append(f"{c.get('ticker', '?')} {c.get('strategy', '?')}: score={score} iv_rank={iv_rank}")
    return (len(fired) > 0, fired)
