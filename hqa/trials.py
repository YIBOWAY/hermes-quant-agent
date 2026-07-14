from __future__ import annotations

import json
from pathlib import Path

# D-21 ①: per-factor trial counter — backtest credibility decays with iteration.

OVERFIT_THRESHOLD = 3

_WARNING_TEMPLATE = (
    "OVERFIT WARNING: trial {n} for {factor_id} — 回测结果可信度随迭代次数下降；"
    "参考 D-21/复盘库，考虑 holdout --final 或收手"
)


def append_trial(factor_id: str, record: dict, log_path: Path) -> None:
    """Append one trial record for factor_id to the JSONL log."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(record)
    entry["factor_id"] = factor_id
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def count_trials(factor_id: str, log_path: Path) -> int:
    """Count trials recorded for factor_id; missing log counts as 0."""
    log_path = Path(log_path)
    if not log_path.exists():
        return 0
    count = 0
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, RecursionError, ValueError):
                continue
            if isinstance(entry, dict) and entry.get("factor_id") == factor_id:
                count += 1
    return count


def overfit_warning(factor_id: str, n: int, threshold: int = OVERFIT_THRESHOLD) -> str:
    """Return the D-21 overfit warning once n reaches threshold; "" before."""
    if n < threshold:
        return ""
    return _WARNING_TEMPLATE.format(n=n, factor_id=factor_id)
