from __future__ import annotations

import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from hqa import opportunities, signals


def _signal_record(
    *,
    contract_symbol: str = "US.AAPL260731C315000",
    observed_at: str = "2026-07-10T18:00:39Z",
) -> dict:
    candidate = {
        "ticker": "AAPL",
        "strategy": "covered_call",
        "global_score": 175.9234,
        "iv_rank": 78.12,
        "run_date": "2026-07-10",
        "candidate": {
            "symbol": contract_symbol,
            "underlying": "US.AAPL",
        },
    }
    return signals.build_signal_records(
        [candidate],
        min_score=150.0,
        min_iv_rank=None,
        source_date="2026-07-10",
        observed_at=observed_at,
    )[0]


def _tracker(tmp_path, *, now: str = "2026-07-12T00:00:00Z"):
    return opportunities.OpportunityTracker(tmp_path, now=lambda: now)


def _append_forged_event(path, *, event_type, request_id, payload):
    def digest(value):
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    payload_sha256 = digest(payload)
    event = {
        "schema_version": "1.0",
        "event": event_type,
        "event_id": ("oev_" + digest([event_type, request_id, payload_sha256])[:24]),
        "request_id": request_id,
        "recorded_at": "2026-07-12T00:00:00Z",
        "payload_sha256": payload_sha256,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                event,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


def _eligible_signal() -> dict:
    signal = copy.deepcopy(_signal_record())
    signal["eligibility"] = {
        "status": "eligible",
        "route": "paper_strategy_execution",
        "reason_code": None,
        "deadline_at": "2026-07-11T14:30:00Z",
    }
    return signal


def test_recording_the_same_signal_request_is_idempotent(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _signal_record()
    command = {
        "event": "signal_observed",
        "request_id": f"watchdog:{signal['signal_id']}",
        "payload": signal,
    }

    first = tracker.record(command)
    repeated = tracker.record(command)

    assert first == repeated
    assert first["signal_id"] == signal["signal_id"]
    assert first["resolution"] == "not_actionable"
    assert tracker.list() == [first]
    assert (
        len((tmp_path / "entries.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    )


def test_repeated_watchdog_observation_keeps_one_signal_event(tmp_path):
    tracker = _tracker(tmp_path)
    initial = _signal_record(observed_at="2026-07-10T18:00:39Z")
    repeated = _signal_record(observed_at="2026-07-10T20:39:49Z")

    first_state = tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{initial['signal_id']}",
            "payload": initial,
        }
    )
    repeated_state = tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{repeated['signal_id']}",
            "payload": repeated,
        }
    )

    assert first_state == repeated_state
    assert repeated_state["signal"]["observed_at"] == "2026-07-10T18:00:39Z"
    assert (
        len((tmp_path / "entries.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    )


def test_pre_deadline_decline_is_an_auditable_terminal_decision(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )

    state = tracker.record(
        {
            "event": "decision_recorded",
            "request_id": "decision:aapl-covered-call:decline",
            "payload": {
                "signal_id": signal["signal_id"],
                "decision": "decline",
                "actor": "human:test",
                "reason": "risk budget unavailable",
                "decided_at": "2026-07-11T12:00:00Z",
                "revisit_at": None,
            },
        }
    )

    assert state["resolution"] == "declined"
    assert state["decision"]["decision_id"].startswith("dec_")
    assert state["decision"]["decision"] == "decline"


def test_timely_causally_linked_pending_execution_counts_as_acted(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )

    state = tracker.record(
        {
            "event": "action_observed",
            "request_id": "platform:strategy-exec-aapl-1:pending",
            "payload": {
                "signal_id": signal["signal_id"],
                "platform_signal_id": "signal-platform-aapl-1",
                "platform_execution_id": "strategy-exec-aapl-1",
                "status": "pending",
                "actor": "platform:paper-strategy",
                "occurred_at": "2026-07-11T12:30:00Z",
                "updated_at": "2026-07-11T12:30:00Z",
            },
        }
    )

    assert state["resolution"] == "acted"
    assert state["actions"][0]["action_id"].startswith("act_")
    assert state["actions"][0]["platform_execution_id"] == "strategy-exec-aapl-1"


@pytest.mark.parametrize("event_type", ["decision_recorded", "action_observed"])
def test_decision_and_action_cannot_predate_signal_source_date(
    tmp_path,
    event_type,
):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    if event_type == "decision_recorded":
        payload = {
            "signal_id": signal["signal_id"],
            "decision": "decline",
            "actor": "human:test",
            "reason": "impossible pre-source decision",
            "decided_at": "2026-07-09T23:59:59Z",
            "revisit_at": None,
        }
    else:
        payload = {
            "signal_id": signal["signal_id"],
            "platform_signal_id": "signal-platform-pre-source",
            "platform_execution_id": "strategy-exec-pre-source",
            "status": "filled",
            "actor": "platform:paper-strategy",
            "occurred_at": "2026-07-09T23:59:59Z",
            "updated_at": "2026-07-10T00:00:00Z",
        }
    before = (tmp_path / "entries.jsonl").read_bytes()

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": event_type,
                "request_id": f"pre-source:{event_type}",
                "payload": payload,
            }
        )

    assert excinfo.value.code == "opportunity_invalid_request"
    assert (tmp_path / "entries.jsonl").read_bytes() == before


@pytest.mark.parametrize("event_type", ["decision_recorded", "action_observed"])
def test_source_date_utc_boundary_is_a_valid_causal_lower_bound(
    tmp_path,
    event_type,
):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    if event_type == "decision_recorded":
        payload = {
            "signal_id": signal["signal_id"],
            "decision": "decline",
            "actor": "human:test",
            "reason": "source-date boundary fixture",
            "decided_at": "2026-07-10T00:00:00Z",
            "revisit_at": None,
        }
        expected_resolution = "declined"
    else:
        payload = {
            "signal_id": signal["signal_id"],
            "platform_signal_id": "signal-platform-source-boundary",
            "platform_execution_id": "strategy-exec-source-boundary",
            "status": "filled",
            "actor": "platform:paper-strategy",
            "occurred_at": "2026-07-10T00:00:00Z",
            "updated_at": "2026-07-10T00:00:00Z",
        }
        expected_resolution = "acted"

    state = tracker.record(
        {
            "event": event_type,
            "request_id": f"source-boundary:{event_type}",
            "payload": payload,
        }
    )

    assert state["resolution"] == expected_resolution


@pytest.mark.parametrize(
    "event_order", [("action", "decision"), ("decision", "action")]
)
def test_timely_action_wins_over_decision_regardless_of_event_order(
    tmp_path,
    event_order,
):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    commands = {
        "action": {
            "event": "action_observed",
            "request_id": "platform:strategy-exec-aapl-order:filled",
            "payload": {
                "signal_id": signal["signal_id"],
                "platform_signal_id": "signal-platform-aapl-order",
                "platform_execution_id": "strategy-exec-aapl-order",
                "status": "filled",
                "actor": "platform:paper-strategy",
                "occurred_at": "2026-07-11T12:30:00Z",
                "updated_at": "2026-07-11T12:35:00Z",
            },
        },
        "decision": {
            "event": "decision_recorded",
            "request_id": "decision:aapl-order:act",
            "payload": {
                "signal_id": signal["signal_id"],
                "decision": "act",
                "actor": "human:test",
                "reason": "approved before deadline",
                "decided_at": "2026-07-11T12:00:00Z",
                "revisit_at": None,
            },
        },
    }
    state = None
    for event_name in event_order:
        state = tracker.record(commands[event_name])
    assert state is not None
    assert state["resolution"] == "acted"
    tracker.record(
        {
            "event": "action_coverage_observed",
            "request_id": f"coverage:event-order:{'-'.join(event_order)}",
            "payload": {
                "signal_id": signal["signal_id"],
                "source": "paper_strategy_observations",
                "snapshot_id": f"snapshot-event-order-{'-'.join(event_order)}",
                "observed_at": "2026-07-12T00:00:00Z",
                "covered_through": "2026-07-12T00:00:00Z",
                "complete": True,
                "truncated": False,
            },
        }
    )

    result = tracker.reconcile_due(as_of="2026-07-12T00:00:00Z")

    assert result["missed_count"] == 0
    assert result["results"] == [{"signal_id": signal["signal_id"], "status": "acted"}]
    assert tracker.list()[0]["resolution"] == "acted"
    events = [
        json.loads(line)
        for line in (tmp_path / "entries.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all(event["event"] != "missed_assessed" for event in events)


def test_complete_coverage_produces_exactly_one_missed_assessment(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )
    tracker.record(
        {
            "event": "action_coverage_observed",
            "request_id": "coverage:paper-strategy:2026-07-12",
            "payload": {
                "signal_id": signal["signal_id"],
                "source": "platform_activity",
                "snapshot_id": "snapshot-2026-07-12",
                "observed_at": "2026-07-12T00:00:00Z",
                "covered_through": "2026-07-12T00:00:00Z",
                "complete": True,
                "truncated": False,
            },
        }
    )

    first = tracker.reconcile_due(as_of="2026-07-12T00:00:00Z")
    repeated = tracker.reconcile_due(as_of="2026-07-12T00:00:00Z")

    assert first["missed_count"] == 1
    assert first["results"] == [
        {
            "signal_id": signal["signal_id"],
            "status": "missed",
            "reason_code": "no_decision",
        }
    ]
    assert repeated["missed_count"] == 0
    state = tracker.list()[0]
    assert state["resolution"] == "missed"
    assert state["missed_assessment"]["reason_code"] == "no_decision"
    assert (
        len((tmp_path / "entries.jsonl").read_text(encoding="utf-8").splitlines()) == 3
    )


@pytest.mark.parametrize(
    ("now", "assessed_at", "coverage_event_id"),
    [
        ("2026-07-11T13:00:00Z", "2026-07-11T13:00:00Z", "oev_coverage"),
        ("2026-07-12T00:00:00Z", "2026-07-12T00:00:00Z", "oev_missing"),
        ("2026-07-12T00:00:00Z", "2026-07-12T00:00:00Z", None),
    ],
    ids=("before-deadline", "without-coverage", "null-coverage-event"),
)
def test_public_record_cannot_forge_missed_assessment(
    tmp_path,
    now,
    assessed_at,
    coverage_event_id,
):
    tracker = _tracker(tmp_path, now=now)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    before = (tmp_path / "entries.jsonl").read_bytes()

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "missed_assessed",
                "request_id": f"forged-miss:{coverage_event_id}",
                "payload": {
                    "signal_id": signal["signal_id"],
                    "assessed_at": assessed_at,
                    "deadline_at": signal["eligibility"]["deadline_at"],
                    "reason_code": "no_decision",
                    "coverage_event_id": coverage_event_id,
                },
            }
        )

    assert excinfo.value.code == "opportunity_invalid_request"
    assert excinfo.value.message == (
        "missed assessments may only be generated by reconcile_due"
    )
    assert (tmp_path / "entries.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    "scenario",
    [
        "assessed-before-deadline",
        "missing-coverage-event",
        "null-coverage-event",
        "reason-without-matching-decision",
    ],
)
def test_hash_consistent_forged_missed_assessment_is_corrupt(tmp_path, scenario):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    state = tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    if scenario in {"assessed-before-deadline", "reason-without-matching-decision"}:
        state = tracker.record(
            {
                "event": "action_coverage_observed",
                "request_id": f"coverage:forged-miss:{scenario}",
                "payload": {
                    "signal_id": signal["signal_id"],
                    "source": "paper_strategy_observations",
                    "snapshot_id": f"snapshot-forged-miss-{scenario}",
                    "observed_at": "2026-07-12T00:00:00Z",
                    "covered_through": "2026-07-12T00:00:00Z",
                    "complete": True,
                    "truncated": False,
                },
            }
        )
    coverage_event_id = (
        state["coverage"]["coverage_event_id"]
        if state["coverage"] is not None
        else "oev_missing"
    )
    if scenario == "null-coverage-event":
        coverage_event_id = None
    payload = {
        "signal_id": signal["signal_id"],
        "assessed_at": "2026-07-12T00:00:00Z",
        "deadline_at": signal["eligibility"]["deadline_at"],
        "reason_code": "no_decision",
        "coverage_event_id": coverage_event_id,
    }
    if scenario == "assessed-before-deadline":
        payload["assessed_at"] = "2026-07-11T13:00:00Z"
    if scenario == "reason-without-matching-decision":
        payload["reason_code"] = "act_without_action"
    _append_forged_event(
        tmp_path / "entries.jsonl",
        event_type="missed_assessed",
        request_id=f"forged-miss:{scenario}",
        payload=payload,
    )

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.list()

    assert excinfo.value.code == "opportunity_ledger_corrupt"


def test_expired_signal_without_complete_coverage_remains_unknown(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )

    result = tracker.reconcile_due(as_of="2026-07-12T00:00:00Z")

    assert result["missed_count"] == 0
    assert result["results"] == [
        {
            "signal_id": signal["signal_id"],
            "status": "expired_coverage_unknown",
        }
    ]
    assert tracker.list()[0]["resolution"] == "expired_coverage_unknown"
    assert (
        len((tmp_path / "entries.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    )


def test_action_status_revision_folds_pending_to_filled(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )
    base = {
        "signal_id": signal["signal_id"],
        "platform_signal_id": "signal-platform-aapl-1",
        "platform_execution_id": "strategy-exec-aapl-1",
        "status": "pending",
        "actor": "platform:paper-strategy",
        "occurred_at": "2026-07-11T12:30:00Z",
        "updated_at": "2026-07-11T12:30:00Z",
    }
    tracker.record(
        {
            "event": "action_observed",
            "request_id": "platform:strategy-exec-aapl-1:pending",
            "payload": base,
        }
    )

    state = tracker.record(
        {
            "event": "action_observed",
            "request_id": "platform:strategy-exec-aapl-1:filled",
            "payload": {
                **base,
                "status": "filled",
                "updated_at": "2026-07-11T14:00:00Z",
            },
        }
    )

    assert state["resolution"] == "acted"
    assert len(state["actions"]) == 1
    assert state["actions"][0]["status"] == "filled"


def test_backwards_action_transition_is_rejected_before_append(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )
    base = {
        "signal_id": signal["signal_id"],
        "platform_signal_id": "signal-platform-aapl-1",
        "platform_execution_id": "strategy-exec-aapl-1",
        "status": "filled",
        "actor": "platform:paper-strategy",
        "occurred_at": "2026-07-11T12:30:00Z",
        "updated_at": "2026-07-11T14:00:00Z",
    }
    tracker.record(
        {
            "event": "action_observed",
            "request_id": "platform:strategy-exec-aapl-1:filled",
            "payload": base,
        }
    )
    before = (tmp_path / "entries.jsonl").read_bytes()

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "action_observed",
                "request_id": "platform:strategy-exec-aapl-1:stale-pending",
                "payload": {
                    **base,
                    "status": "pending",
                    "updated_at": "2026-07-11T14:05:00Z",
                },
            }
        )

    assert excinfo.value.code == "opportunity_ledger_corrupt"
    assert (tmp_path / "entries.jsonl").read_bytes() == before


def test_one_platform_execution_cannot_be_linked_to_two_signals(tmp_path):
    tracker = _tracker(tmp_path)
    first = _eligible_signal()
    second = copy.deepcopy(_signal_record(contract_symbol="US.AAPL260807C315000"))
    second["eligibility"] = copy.deepcopy(first["eligibility"])
    for signal in (first, second):
        tracker.record(
            {
                "event": "signal_observed",
                "request_id": f"watchdog:{signal['signal_id']}",
                "payload": signal,
            }
        )
    action = {
        "platform_signal_id": "signal-platform-aapl-1",
        "platform_execution_id": "strategy-exec-aapl-1",
        "status": "pending",
        "actor": "platform:paper-strategy",
        "occurred_at": "2026-07-11T12:30:00Z",
        "updated_at": "2026-07-11T12:30:00Z",
    }
    tracker.record(
        {
            "event": "action_observed",
            "request_id": "link:first:strategy-exec-aapl-1",
            "payload": {"signal_id": first["signal_id"], **action},
        }
    )
    before = (tmp_path / "entries.jsonl").read_bytes()

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "action_observed",
                "request_id": "link:second:strategy-exec-aapl-1",
                "payload": {"signal_id": second["signal_id"], **action},
            }
        )

    assert excinfo.value.code == "opportunity_ledger_corrupt"
    assert (tmp_path / "entries.jsonl").read_bytes() == before


@pytest.mark.parametrize("decision", ["act", "defer"])
def test_decision_cannot_upgrade_a_not_actionable_signal(tmp_path, decision):
    tracker = _tracker(tmp_path)
    signal = _signal_record()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )

    state = tracker.record(
        {
            "event": "decision_recorded",
            "request_id": f"decision:not-actionable:{decision}",
            "payload": {
                "signal_id": signal["signal_id"],
                "decision": decision,
                "actor": "human:test",
                "reason": "record intent without changing route facts",
                "decided_at": "2026-07-11T12:00:00Z",
                "revisit_at": None,
            },
        }
    )

    assert state["resolution"] == "not_actionable"
    assert state["decision"]["decision"] == decision


def test_concurrent_identical_signal_commands_append_once(tmp_path):
    signal = _signal_record()
    command = {
        "event": "signal_observed",
        "request_id": f"watchdog:{signal['signal_id']}",
        "payload": signal,
    }
    workers = 12
    barrier = threading.Barrier(workers)

    def record_once(_index):
        tracker = _tracker(tmp_path)
        barrier.wait()
        return tracker.record(command)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        states = list(pool.map(record_once, range(workers)))

    assert len({state["signal_id"] for state in states}) == 1
    assert (
        len((tmp_path / "entries.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    )
    assert _tracker(tmp_path).list() == [states[0]]


def test_torn_ledger_fails_closed_and_blocks_append(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _signal_record()
    command = {
        "event": "signal_observed",
        "request_id": f"watchdog:{signal['signal_id']}",
        "payload": signal,
    }
    tracker.record(command)
    path = tmp_path / "entries.jsonl"
    path.write_bytes(path.read_bytes().removesuffix(b"\n"))
    before = path.read_bytes()

    with pytest.raises(opportunities.OpportunityLedgerError) as read_error:
        tracker.list()
    with pytest.raises(opportunities.OpportunityLedgerError) as write_error:
        tracker.record(
            {
                **command,
                "request_id": "watchdog:new-request-on-corrupt-ledger",
            }
        )

    assert read_error.value.code == "opportunity_ledger_corrupt"
    assert write_error.value.code == "opportunity_ledger_corrupt"
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_key", "non_finite", "payload_hash", "unknown_envelope_field"],
)
def test_strict_event_corruption_is_rejected(tmp_path, mutation):
    tracker = _tracker(tmp_path)
    signal = _signal_record()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )
    path = tmp_path / "entries.jsonl"
    line = path.read_text(encoding="utf-8").rstrip("\n")
    if mutation == "duplicate_key":
        line = line.replace(
            '"schema_version":"1.0"',
            '"schema_version":"1.0","schema_version":"1.0"',
            1,
        )
    elif mutation == "non_finite":
        line = line.replace('"score":175.9234', '"score":NaN', 1)
    elif mutation == "payload_hash":
        line = line.replace('"score":175.9234', '"score":175.0', 1)
    else:
        line = line.replace("{", '{"unexpected":true,', 1)
    path.write_text(line + "\n", encoding="utf-8")

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.list()

    assert excinfo.value.code == "opportunity_ledger_corrupt"


def test_hash_consistent_unknown_payload_field_is_still_corrupt(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _signal_record()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )
    path = tmp_path / "entries.jsonl"
    event = json.loads(path.read_text(encoding="utf-8"))
    event["payload"]["unexpected"] = True

    def digest(value):
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    event["payload_sha256"] = digest(event["payload"])
    event["event_id"] = (
        "oev_"
        + digest([event["event"], event["request_id"], event["payload_sha256"]])[:24]
    )
    path.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.list()

    assert excinfo.value.code == "opportunity_ledger_corrupt"


def test_naive_event_timestamp_is_rejected_before_append(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )
    before = (tmp_path / "entries.jsonl").read_bytes()

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "decision_recorded",
                "request_id": "decision:naive-time",
                "payload": {
                    "signal_id": signal["signal_id"],
                    "decision": "decline",
                    "actor": "human:test",
                    "reason": "invalid timestamp fixture",
                    "decided_at": "2026-07-11T12:00:00",
                    "revisit_at": None,
                },
            }
        )

    assert excinfo.value.code == "opportunity_invalid_request"
    assert (tmp_path / "entries.jsonl").read_bytes() == before


def test_invalid_unicode_is_rejected_atomically_before_append(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    initial = tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    before = (tmp_path / "entries.jsonl").read_bytes()

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "decision_recorded",
                "request_id": "decision:invalid-unicode",
                "payload": {
                    "signal_id": signal["signal_id"],
                    "decision": "decline",
                    "actor": "human:test",
                    "reason": "bad-\ud800",
                    "decided_at": "2026-07-11T12:00:00Z",
                    "revisit_at": None,
                },
            }
        )

    assert excinfo.value.code == "opportunity_invalid_request"
    assert (tmp_path / "entries.jsonl").read_bytes() == before
    states = tracker.list()
    assert len(states) == 1
    assert states[0]["signal_id"] == initial["signal_id"]
    assert states[0]["decision"] is None


def test_concurrent_reconcile_reports_and_writes_one_new_missed_assessment(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )
    tracker.record(
        {
            "event": "action_coverage_observed",
            "request_id": "coverage:concurrent-reconcile",
            "payload": {
                "signal_id": signal["signal_id"],
                "source": "paper_strategy_observations",
                "snapshot_id": "snapshot-concurrent-reconcile",
                "observed_at": "2026-07-12T00:00:00Z",
                "covered_through": "2026-07-12T00:00:00Z",
                "complete": True,
                "truncated": False,
            },
        }
    )
    barrier = threading.Barrier(2)

    def reconcile_once(_index):
        candidate = _tracker(tmp_path)
        barrier.wait()
        return candidate.reconcile_due(as_of="2026-07-12T00:00:00Z")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reconcile_once, range(2)))

    assert sum(result["missed_count"] for result in results) == 1
    events = [
        json.loads(line)
        for line in (tmp_path / "entries.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert sum(event["event"] == "missed_assessed" for event in events) == 1


def test_platform_skipped_execution_is_an_action_failure_not_inaction(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )

    state = tracker.record(
        {
            "event": "action_observed",
            "request_id": "platform:strategy-exec-aapl-1:skipped",
            "payload": {
                "signal_id": signal["signal_id"],
                "platform_signal_id": "signal-platform-aapl-1",
                "platform_execution_id": "strategy-exec-aapl-1",
                "status": "skipped",
                "actor": "platform:paper-strategy",
                "occurred_at": "2026-07-11T12:30:00Z",
                "updated_at": "2026-07-11T14:00:00Z",
            },
        }
    )

    assert state["resolution"] == "action_failed"
    assert state["actions"][0]["status"] == "skipped"


def test_action_evidence_cannot_upgrade_not_actionable_eligibility(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _signal_record()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"watchdog:{signal['signal_id']}",
            "payload": signal,
        }
    )

    state = tracker.record(
        {
            "event": "action_observed",
            "request_id": "incorrect-link:strategy-exec-aapl-1",
            "payload": {
                "signal_id": signal["signal_id"],
                "platform_signal_id": "signal-platform-aapl-1",
                "platform_execution_id": "strategy-exec-aapl-1",
                "status": "filled",
                "actor": "human:test",
                "occurred_at": "2026-07-10T19:00:00Z",
                "updated_at": "2026-07-10T19:05:00Z",
            },
        }
    )

    assert state["resolution"] == "not_actionable"
    assert len(state["actions"]) == 1


def test_list_applies_since_cursor_status_and_limit(tmp_path):
    tracker = _tracker(tmp_path)
    old = _signal_record(observed_at="2026-07-10T18:00:39Z")
    new = _signal_record(
        contract_symbol="US.AAPL260807C315000",
        observed_at="2026-07-12T01:00:00Z",
    )
    for signal in (old, new):
        tracker.record(
            {
                "event": "signal_observed",
                "request_id": f"watchdog:{signal['signal_id']}",
                "payload": signal,
            }
        )
    ordered = tracker.list()
    first_id = ordered[0]["signal_id"]

    assert tracker.list(since="2026-07-11T00:00:00Z") == [
        next(state for state in ordered if state["signal_id"] == new["signal_id"])
    ]
    assert all(state["signal_id"] > first_id for state in tracker.list(cursor=first_id))
    assert len(tracker.list(limit=1)) == 1
    assert len(tracker.list(status="not_actionable")) == 2


@pytest.mark.parametrize("tamper", ["signal_id", "policy_sha256"])
def test_signal_identity_and_policy_digest_are_verified_before_append(tmp_path, tamper):
    tracker = _tracker(tmp_path)
    signal = copy.deepcopy(_signal_record())
    if tamper == "signal_id":
        signal["signal_id"] = "sig_000000000000000000000000"
    else:
        signal["policy"]["sha256"] = "0" * 64

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "signal_observed",
                "request_id": f"watchdog:{signal['signal_id']}",
                "payload": signal,
            }
        )

    assert excinfo.value.code == "opportunity_invalid_request"
    assert not (tmp_path / "entries.jsonl").exists()


def test_eligible_deadline_cannot_predate_signal_source_utc_date(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    signal["eligibility"]["deadline_at"] = "2026-07-09T23:59:59Z"

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "signal_observed",
                "request_id": f"options-scan:{signal['signal_id']}",
                "payload": signal,
            }
        )

    assert excinfo.value.code == "opportunity_invalid_request"
    assert not (tmp_path / "entries.jsonl").exists()


def test_signal_source_utc_boundary_is_a_valid_eligible_deadline(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    signal["eligibility"]["deadline_at"] = "2026-07-10T00:00:00Z"

    state = tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )

    assert state["resolution"] == "open"
    assert state["signal"]["eligibility"]["deadline_at"] == ("2026-07-10T00:00:00Z")


def test_late_decline_does_not_erase_a_covered_action_window_miss(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    tracker.record(
        {
            "event": "decision_recorded",
            "request_id": "decision:late-decline",
            "payload": {
                "signal_id": signal["signal_id"],
                "decision": "decline",
                "actor": "human:test",
                "reason": "recorded only after the window closed",
                "decided_at": "2026-07-11T15:00:00Z",
                "revisit_at": None,
            },
        }
    )
    tracker.record(
        {
            "event": "action_coverage_observed",
            "request_id": "coverage:late-decline",
            "payload": {
                "signal_id": signal["signal_id"],
                "source": "paper_strategy_observations",
                "snapshot_id": "snapshot-late-decline",
                "observed_at": "2026-07-12T00:00:00Z",
                "covered_through": "2026-07-12T00:00:00Z",
                "complete": True,
                "truncated": False,
            },
        }
    )

    result = tracker.reconcile_due(as_of="2026-07-12T00:00:00Z")

    assert result["missed_count"] == 1
    assert result["results"][0]["reason_code"] == "no_decision"
    assert tracker.list()[0]["resolution"] == "missed"


def test_backfilled_timely_action_remains_visible_without_erasing_recorded_miss(
    tmp_path,
):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    tracker.record(
        {
            "event": "action_coverage_observed",
            "request_id": "coverage:before-backfill",
            "payload": {
                "signal_id": signal["signal_id"],
                "source": "paper_strategy_observations",
                "snapshot_id": "snapshot-before-backfill",
                "observed_at": "2026-07-12T00:00:00Z",
                "covered_through": "2026-07-12T00:00:00Z",
                "complete": True,
                "truncated": False,
            },
        }
    )
    assert tracker.reconcile_due(as_of="2026-07-12T00:00:00Z")["missed_count"] == 1

    state = tracker.record(
        {
            "event": "action_observed",
            "request_id": "action:backfilled-after-miss",
            "payload": {
                "signal_id": signal["signal_id"],
                "platform_signal_id": "signal-platform-backfill",
                "platform_execution_id": "strategy-exec-backfill",
                "status": "filled",
                "actor": "platform:paper-strategy",
                "occurred_at": "2026-07-11T12:30:00Z",
                "updated_at": "2026-07-12T01:00:00Z",
            },
        }
    )

    assert state["resolution"] == "missed"
    assert state["actions"][0]["platform_execution_id"] == "strategy-exec-backfill"
    assert tracker.list()[0]["resolution"] == "missed"


def test_second_decision_is_rejected_without_changing_the_first(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    tracker.record(
        {
            "event": "decision_recorded",
            "request_id": "decision:first",
            "payload": {
                "signal_id": signal["signal_id"],
                "decision": "defer",
                "actor": "human:test",
                "reason": "wait for evidence",
                "decided_at": "2026-07-11T12:00:00Z",
                "revisit_at": "2026-07-11T13:00:00Z",
            },
        }
    )
    before = (tmp_path / "entries.jsonl").read_bytes()

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "decision_recorded",
                "request_id": "decision:second",
                "payload": {
                    "signal_id": signal["signal_id"],
                    "decision": "decline",
                    "actor": "human:test",
                    "reason": "conflicting rewrite",
                    "decided_at": "2026-07-11T12:30:00Z",
                    "revisit_at": None,
                },
            }
        )

    assert excinfo.value.code == "opportunity_ledger_corrupt"
    assert (tmp_path / "entries.jsonl").read_bytes() == before


def test_coverage_watermark_cannot_move_backwards(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    base = {
        "signal_id": signal["signal_id"],
        "source": "paper_strategy_observations",
        "observed_at": "2026-07-12T00:00:00Z",
        "complete": True,
        "truncated": False,
    }
    tracker.record(
        {
            "event": "action_coverage_observed",
            "request_id": "coverage:newer",
            "payload": {
                **base,
                "snapshot_id": "snapshot-newer",
                "covered_through": "2026-07-12T00:00:00Z",
            },
        }
    )
    before = (tmp_path / "entries.jsonl").read_bytes()

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "action_coverage_observed",
                "request_id": "coverage:older",
                "payload": {
                    **base,
                    "snapshot_id": "snapshot-older",
                    "covered_through": "2026-07-11T23:00:00Z",
                },
            }
        )

    assert excinfo.value.code == "opportunity_ledger_corrupt"
    assert (tmp_path / "entries.jsonl").read_bytes() == before


def test_action_updated_at_cannot_precede_occurred_at(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.record(
            {
                "event": "action_observed",
                "request_id": "action:backwards-time",
                "payload": {
                    "signal_id": signal["signal_id"],
                    "platform_signal_id": "signal-platform-aapl-1",
                    "platform_execution_id": "strategy-exec-aapl-1",
                    "status": "filled",
                    "actor": "platform:paper-strategy",
                    "occurred_at": "2026-07-11T13:00:00Z",
                    "updated_at": "2026-07-11T12:59:59Z",
                },
            }
        )

    assert excinfo.value.code == "opportunity_invalid_request"


def test_hash_consistent_invalid_stored_decision_is_corrupt(tmp_path):
    tracker = _tracker(tmp_path)
    signal = _eligible_signal()
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"options-scan:{signal['signal_id']}",
            "payload": signal,
        }
    )
    tracker.record(
        {
            "event": "decision_recorded",
            "request_id": "decision:valid-before-tamper",
            "payload": {
                "signal_id": signal["signal_id"],
                "decision": "decline",
                "actor": "human:test",
                "reason": "valid fixture",
                "decided_at": "2026-07-11T12:00:00Z",
                "revisit_at": None,
            },
        }
    )
    path = tmp_path / "entries.jsonl"
    events = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    event = events[1]
    event["payload"]["decision"] = "fabricated"

    def digest(value):
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    event["payload_sha256"] = digest(event["payload"])
    event["event_id"] = (
        "oev_"
        + digest([event["event"], event["request_id"], event["payload_sha256"]])[:24]
    )
    path.write_text(
        "\n".join(json.dumps(item, sort_keys=True) for item in events) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(opportunities.OpportunityLedgerError) as excinfo:
        tracker.list()

    assert excinfo.value.code == "opportunity_ledger_corrupt"
