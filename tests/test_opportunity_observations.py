from __future__ import annotations

import copy
import json

import pytest

from hqa.opportunities import OpportunityTracker
from hqa.opportunity_observations import (
    OpportunityObservationError,
    OpportunityObservationSync,
)
from hqa.signals import build_signal_records


def _eligible_signal() -> dict:
    candidate = {
        "ticker": "AAPL",
        "strategy": "covered_call",
        "global_score": 175.9234,
        "iv_rank": 78.12,
        "run_date": "2026-07-10",
        "candidate": {
            "symbol": "US.AAPL260731C315000",
            "underlying": "US.AAPL",
        },
    }
    signal = build_signal_records(
        [candidate],
        min_score=150,
        min_iv_rank=None,
        source_date="2026-07-10",
        observed_at="2026-07-10T18:00:39Z",
    )[0]
    eligible = copy.deepcopy(signal)
    eligible["eligibility"] = {
        "status": "eligible",
        "route": "paper_strategy_execution",
        "reason_code": None,
        "deadline_at": "2026-07-12T14:30:00Z",
    }
    return eligible


def _store_signal(tmp_path):
    opportunity_dir = tmp_path / "opportunities"
    signal = _eligible_signal()
    OpportunityTracker(
        opportunity_dir,
        now=lambda: "2026-07-12T01:00:00Z",
    ).record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    return opportunity_dir, signal


def _store_not_actionable_signal(tmp_path):
    opportunity_dir = tmp_path / "opportunities"
    signal = build_signal_records(
        [
            {
                "ticker": "AAPL",
                "strategy": "covered_call",
                "global_score": 175.9234,
                "iv_rank": 78.12,
                "run_date": "2026-07-10",
                "candidate": {
                    "symbol": "US.AAPL260731C315000",
                    "underlying": "US.AAPL",
                },
            }
        ],
        min_score=150,
        min_iv_rank=None,
        source_date="2026-07-10",
        observed_at="2026-07-10T18:00:39Z",
    )[0]
    OpportunityTracker(
        opportunity_dir,
        now=lambda: "2026-07-12T01:00:00Z",
    ).record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    return opportunity_dir, signal


def _coverage_document() -> dict:
    return {
        "schema_version": 1,
        "snapshot_at": "2026-07-13T01:02:03Z",
        "read_status": "empty",
        "query": {
            "from_date": "2026-07-10",
            "to_date": "2026-07-13",
            "signal_id": None,
            "limit": 200,
        },
        "returned_count": 0,
        "truncated": False,
        "ops_quality": {
            "pending_sleeve_count": 0,
            "pending_journal_count": 0,
            "corrupt_journal_count": 0,
            "recovery_required_count": 0,
        },
        "observations": [],
        "errors": [],
    }


def _action_document() -> dict:
    return {
        "schema_version": 1,
        "snapshot_at": "2026-07-13T01:02:03Z",
        "read_status": "available",
        "query": {
            "from_date": None,
            "to_date": None,
            "signal_id": "platform-signal-1",
            "limit": 200,
        },
        "returned_count": 1,
        "truncated": False,
        "ops_quality": {
            "pending_sleeve_count": 0,
            "pending_journal_count": 0,
            "corrupt_journal_count": 0,
            "recovery_required_count": 0,
        },
        "observations": [
            {
                "signal": {"signal_id": "platform-signal-1"},
                "executions": [
                    {
                        "execution_id": "platform-execution-1",
                        "signal_id": "platform-signal-1",
                        "created_at": "2026-07-12T12:00:00Z",
                        "updated_at": "2026-07-12T12:05:00Z",
                        "status": "pending",
                    }
                ],
            }
        ],
        "errors": [],
    }


def test_sync_coverage_records_only_complete_bounded_platform_evidence(
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_signal(tmp_path)
    calls = []

    def run_observations(**kwargs):
        calls.append(kwargs)
        return 0, json.dumps(_coverage_document())

    sync = OpportunityObservationSync(
        opportunity_dir,
        run_observations=run_observations,
        now=lambda: "2026-07-13T01:02:03Z",
    )

    state = sync.sync_coverage(
        signal["signal_id"],
        covered_through="2026-07-13T00:00:00Z",
        from_date="2026-07-10",
        to_date="2026-07-13",
    )

    assert calls == [
        {
            "from_date": "2026-07-10",
            "to_date": "2026-07-13",
            "limit": 200,
        }
    ]
    assert state["coverage"] == {
        "signal_id": signal["signal_id"],
        "source": "paper_strategy_observations",
        "snapshot_id": state["coverage"]["snapshot_id"],
        "observed_at": "2026-07-13T01:02:03Z",
        "covered_through": "2026-07-13T00:00:00Z",
        "complete": True,
        "truncated": False,
        "coverage_event_id": state["coverage"]["coverage_event_id"],
    }
    assert state["actions"] == []


def test_record_action_requires_exact_platform_signal_and_execution_evidence(
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_signal(tmp_path)
    calls = []

    def run_observations(**kwargs):
        calls.append(kwargs)
        return 0, json.dumps(_action_document())

    sync = OpportunityObservationSync(
        opportunity_dir,
        run_observations=run_observations,
        now=lambda: "2026-07-12T12:06:00Z",
    )

    state = sync.record_action(
        signal["signal_id"],
        platform_signal_id="platform-signal-1",
        platform_execution_id="platform-execution-1",
        actor="human:sunyibo",
    )

    assert calls == [{"signal_id": "platform-signal-1", "limit": 200}]
    assert state["resolution"] == "acted"
    assert state["actions"] == [
        {
            "signal_id": signal["signal_id"],
            "platform_signal_id": "platform-signal-1",
            "platform_execution_id": "platform-execution-1",
            "status": "pending",
            "actor": "human:sunyibo",
            "occurred_at": "2026-07-12T12:00:00Z",
            "updated_at": "2026-07-12T12:05:00Z",
            "action_id": state["actions"][0]["action_id"],
        }
    ]


def test_sync_coverage_skips_not_actionable_without_reading_platform(tmp_path) -> None:
    opportunity_dir, signal = _store_not_actionable_signal(tmp_path)
    before = (opportunity_dir / "entries.jsonl").read_bytes()

    def must_not_run(**_kwargs):
        raise AssertionError("not_actionable must not read platform observations")

    sync = OpportunityObservationSync(
        opportunity_dir,
        run_observations=must_not_run,
        now=lambda: "2026-07-13T01:02:03Z",
    )

    state = sync.sync_coverage(
        signal["signal_id"],
        covered_through="2026-07-13T00:00:00Z",
    )

    assert state["resolution"] == "not_actionable"
    assert state["coverage"] is None
    assert (opportunity_dir / "entries.jsonl").read_bytes() == before


def test_sync_coverage_rejects_unknown_envelope_fields_before_append(tmp_path) -> None:
    opportunity_dir, signal = _store_signal(tmp_path)
    document = _coverage_document()
    document["untrusted_extension"] = {"complete": True}
    before = (opportunity_dir / "entries.jsonl").read_bytes()
    sync = OpportunityObservationSync(
        opportunity_dir,
        run_observations=lambda **_kwargs: (0, json.dumps(document)),
        now=lambda: "2026-07-13T01:02:03Z",
    )

    with pytest.raises(OpportunityObservationError) as excinfo:
        sync.sync_coverage(
            signal["signal_id"],
            covered_through="2026-07-13T00:00:00Z",
            from_date="2026-07-10",
            to_date="2026-07-13",
        )

    assert excinfo.value.code == "opportunity_platform_observation_invalid"
    assert (opportunity_dir / "entries.jsonl").read_bytes() == before


def test_sync_coverage_rejects_unbounded_limit_without_reading_platform(
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_signal(tmp_path)
    before = (opportunity_dir / "entries.jsonl").read_bytes()

    def must_not_run(**_kwargs):
        raise AssertionError("an unbounded query must not reach the platform")

    sync = OpportunityObservationSync(
        opportunity_dir,
        run_observations=must_not_run,
        now=lambda: "2026-07-13T01:02:03Z",
    )

    with pytest.raises(OpportunityObservationError) as excinfo:
        sync.sync_coverage(
            signal["signal_id"],
            covered_through="2026-07-13T00:00:00Z",
            limit=201,
        )

    assert excinfo.value.code == "opportunity_invalid_arguments"
    assert excinfo.value.retryable is False
    assert (opportunity_dir / "entries.jsonl").read_bytes() == before


def test_record_action_rejects_unbounded_limit_without_reading_platform(
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_signal(tmp_path)

    def must_not_run(**_kwargs):
        raise AssertionError("an unbounded query must not reach the platform")

    sync = OpportunityObservationSync(
        opportunity_dir,
        run_observations=must_not_run,
        now=lambda: "2026-07-13T01:02:03Z",
    )

    with pytest.raises(OpportunityObservationError) as excinfo:
        sync.record_action(
            signal["signal_id"],
            platform_signal_id="platform-signal-1",
            platform_execution_id="platform-execution-1",
            actor="human:sunyibo",
            limit=201,
        )

    assert excinfo.value.code == "opportunity_invalid_arguments"


def test_sync_coverage_rejects_noncanonical_query_date_before_platform(
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_signal(tmp_path)

    def must_not_run(**_kwargs):
        raise AssertionError("an invalid date must not reach the platform")

    sync = OpportunityObservationSync(
        opportunity_dir,
        run_observations=must_not_run,
        now=lambda: "2026-07-13T01:02:03Z",
    )

    with pytest.raises(OpportunityObservationError) as excinfo:
        sync.sync_coverage(
            signal["signal_id"],
            covered_through="2026-07-13T00:00:00Z",
            from_date="2026-7-10",
            to_date="2026-07-13",
        )

    assert excinfo.value.code == "opportunity_invalid_arguments"
