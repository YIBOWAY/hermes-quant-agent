from __future__ import annotations

import json
import re
from typing import Optional

_CANDIDATE_RE = re.compile(r"candidate_id=(\S+)")
_METRIC_KEYS = ("sharpe", "total_return", "max_drawdown")


def parse_candidate_id(output: str) -> Optional[str]:
    match = _CANDIDATE_RE.search(output)
    return match.group(1) if match else None


def parse_experiment_summary(output: str) -> dict[str, str]:
    for line in output.splitlines():
        if "experiment_id=" in line:
            return {
                key: value
                for key, _, value in (token.partition("=") for token in line.split() if "=" in token)
            }
    return {}


def extract_best_run_metrics(agent_summary_json: str) -> dict[str, float]:
    data = json.loads(agent_summary_json)
    best_id = data.get("best_run_id")
    for run in data.get("runs", []):
        if run.get("run_id") == best_id:
            return {key: run[key] for key in _METRIC_KEYS if key in run}
    return {}
