from __future__ import annotations

import json
import re
from typing import Optional

_CANDIDATE_RE = re.compile(r"candidate_id=(\S+)")
_METRIC_KEYS = ("sharpe", "total_return", "max_drawdown")


def parse_json_payload(output: str) -> Optional[dict]:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None
    return None


def parse_candidate_id(output: str) -> Optional[str]:
    payload = parse_json_payload(output)
    if payload is not None:
        candidate_id = payload.get("candidate_id")
        if candidate_id is not None:
            return str(candidate_id)
    match = _CANDIDATE_RE.search(output)
    return match.group(1) if match else None


def parse_experiment_summary(output: str) -> dict[str, str]:
    payload = parse_json_payload(output)
    if payload is not None and "experiment_id" in payload:
        # Drop null values instead of stringifying them: a JSON null best_run_id
        # would otherwise become the string "None", defeating the CLI's
        # summary.get("best_run_id", "?") fallback (F7). The regex path below
        # never emits a null, so absence keeps both paths consistent.
        return {
            key: str(value) for key, value in payload.items() if value is not None
        }
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
