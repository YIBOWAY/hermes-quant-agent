from __future__ import annotations

import json

from hqa import factor_repro as fr

PROPOSE_OUT = "candidate_id=factor-momentum_20d_reversal-323b045e4b status=pending path=data/agent_run/... metadata=..."
SUMMARY_OUT = (
    "approved_candidates_loaded=wiring_test_factor\n"
    "experiment_id=factor-repro-20260702T000000Z run_count=1 best_run_id=run-001 "
    "config=/x/config.json runs=/x/runs.parquet folds=/x/folds.parquet "
    "agent_summary=/x/agent_summary.json report=/x/report.md"
)
AGENT_SUMMARY = json.dumps(
    {
        "best_run_id": "run-001",
        "runs": [
            {"run_id": "run-001", "sharpe": 1.42, "total_return": 0.183, "max_drawdown": 0.061},
            {"run_id": "run-002", "sharpe": 0.7, "total_return": 0.05, "max_drawdown": 0.09},
        ],
    }
)


def test_parse_candidate_id():
    assert fr.parse_candidate_id(PROPOSE_OUT) == "factor-momentum_20d_reversal-323b045e4b"


def test_parse_candidate_id_missing_returns_none():
    assert fr.parse_candidate_id("no id here") is None


def test_parse_experiment_summary():
    summary = fr.parse_experiment_summary(SUMMARY_OUT)
    assert summary["experiment_id"] == "factor-repro-20260702T000000Z"
    assert summary["best_run_id"] == "run-001"
    assert summary["agent_summary"] == "/x/agent_summary.json"


def test_parse_experiment_summary_missing_returns_empty_dict():
    assert fr.parse_experiment_summary("no experiment summary") == {}


def test_extract_best_run_metrics():
    metrics = fr.extract_best_run_metrics(AGENT_SUMMARY)
    assert metrics == {"sharpe": 1.42, "total_return": 0.183, "max_drawdown": 0.061}


def test_extract_best_run_metrics_missing_best_returns_empty_dict():
    assert fr.extract_best_run_metrics(json.dumps({"best_run_id": "missing", "runs": []})) == {}


def test_parse_json_payload_last_line():
    output = "some log line\n" + json.dumps({"candidate_id": "factor-x-1", "status": "pending"})
    assert fr.parse_json_payload(output) == {"candidate_id": "factor-x-1", "status": "pending"}


def test_parse_json_payload_returns_none_for_non_json():
    assert fr.parse_json_payload("no id here") is None


def test_parse_json_payload_ignores_trailing_blank_lines():
    output = json.dumps({"a": 1}) + "\n\n"
    assert fr.parse_json_payload(output) == {"a": 1}


def test_parse_candidate_id_from_json():
    output = "human readable line\n" + json.dumps({"candidate_id": "factor-x-json"})
    assert fr.parse_candidate_id(output) == "factor-x-json"


def test_parse_candidate_id_legacy_fallback_still_works():
    assert fr.parse_candidate_id(PROPOSE_OUT) == "factor-momentum_20d_reversal-323b045e4b"


def test_parse_experiment_summary_from_json():
    payload = {
        "experiment_id": "factor-repro-json-20260703T000000Z",
        "best_run_id": "run-002",
        "agent_summary": "/y/agent_summary.json",
    }
    output = "some banner\n" + json.dumps(payload)
    summary = fr.parse_experiment_summary(output)
    assert summary["experiment_id"] == "factor-repro-json-20260703T000000Z"
    assert summary["best_run_id"] == "run-002"
    assert summary["agent_summary"] == "/y/agent_summary.json"


def test_parse_experiment_summary_legacy_fallback_still_works():
    summary = fr.parse_experiment_summary(SUMMARY_OUT)
    assert summary["experiment_id"] == "factor-repro-20260702T000000Z"
    assert summary["best_run_id"] == "run-001"
    assert summary["agent_summary"] == "/x/agent_summary.json"
