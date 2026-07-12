from __future__ import annotations

import copy
import json

import pytest

from hqa import opportunity_cli as cli


def _candidate() -> dict:
    return {
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


def _eligible_signal() -> dict:
    signal = cli.signals.build_signal_records(
        [_candidate()],
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


def _store_eligible_signal(tmp_path):
    opportunity_dir = tmp_path / "opportunities"
    signal = _eligible_signal()
    cli.OpportunityTracker(
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


def _coverage_document(
    *,
    snapshot_at="2026-07-13T01:00:00Z",
    from_date=None,
    to_date=None,
    pending_sleeves=0,
):
    return {
        "schema_version": 1,
        "snapshot_at": snapshot_at,
        "read_status": "empty",
        "query": {
            "from_date": from_date,
            "to_date": to_date,
            "signal_id": None,
            "limit": 200,
        },
        "returned_count": 0,
        "truncated": False,
        "ops_quality": {
            "pending_sleeve_count": pending_sleeves,
            "pending_journal_count": 0,
            "corrupt_journal_count": 0,
            "recovery_required_count": 0,
        },
        "observations": [],
        "errors": [],
    }


def _record_action_document() -> dict:
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


def test_argparse_failure_is_one_strict_json_error_document(capsys) -> None:
    rc = cli.main(["decide", "--signal-id", "sig_missing_fields"])

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_invalid_arguments",
            "message": (
                "the following arguments are required: --decision, --actor, "
                "--reason, --request-id"
            ),
            "retryable": False,
        }
    }
    assert captured.out.count("\n") == 1


def test_sync_signals_consumes_existing_artifact_without_running_a_scan(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    scan_dir = tmp_path / "scans"
    scan_dir.mkdir()
    (scan_dir / "2026-07-10.jsonl").write_text(
        json.dumps(_candidate()) + "\n",
        encoding="utf-8",
    )
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(
        json.dumps({"min_score": 150, "min_iv_rank": None}),
        encoding="utf-8",
    )
    opportunity_dir = tmp_path / "opportunities"
    monkeypatch.setattr(cli.runlog, "utc_now_iso", lambda: "2026-07-12T01:02:03Z")

    rc = cli.main(
        [
            "sync-signals",
            "--date",
            "2026-07-10",
            "--scan-dir",
            str(scan_dir),
            "--thresholds",
            str(thresholds),
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert rc == 0
    assert captured.err == ""
    assert document["status"] == "available"
    assert document["source_date"] == "2026-07-10"
    assert document["candidate_count"] == 1
    assert document["signal_count"] == 1
    assert document["signals"][0]["resolution"] == "not_actionable"
    assert document["signals"][0]["signal"]["observed_at"] == "2026-07-12T01:02:03Z"
    assert captured.out.count("\n") == 1
    assert (
        len(
            (opportunity_dir / "entries.jsonl").read_text(encoding="utf-8").splitlines()
        )
        == 1
    )


def test_decide_records_an_auditable_human_decision(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir = tmp_path / "opportunities"
    signal = cli.signals.build_signal_records(
        [_candidate()],
        min_score=150,
        min_iv_rank=None,
        source_date="2026-07-10",
        observed_at="2026-07-10T18:00:39Z",
    )[0]
    tracker = cli.OpportunityTracker(
        opportunity_dir,
        now=lambda: "2026-07-12T01:00:00Z",
    )
    tracker.record(
        {
            "event": "signal_observed",
            "request_id": f"sync-signals:{signal['signal_id']}",
            "payload": signal,
        }
    )
    monkeypatch.setattr(cli.runlog, "utc_now_iso", lambda: "2026-07-12T02:00:00Z")

    rc = cli.main(
        [
            "decide",
            "--signal-id",
            signal["signal_id"],
            "--decision",
            "decline",
            "--actor",
            "human:sunyibo",
            "--reason",
            "The option route is not available in paper execution.",
            "--decided-at",
            "2026-07-12T01:30:00Z",
            "--request-id",
            "decision:aapl-covered-call:2026-07-12",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert rc == 0
    assert captured.err == ""
    assert document["signal_id"] == signal["signal_id"]
    assert document["resolution"] == "not_actionable"
    assert document["decision"]["actor"] == "human:sunyibo"
    assert document["decision"]["revisit_at"] is None
    assert document["decision"]["decision_id"].startswith("dec_")
    assert captured.out.count("\n") == 1


def test_list_reads_local_ledger_without_contacting_platform(capsys, tmp_path) -> None:
    rc = cli.main(
        [
            "list",
            "--status",
            "open",
            "--limit",
            "10",
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    assert json.loads(captured.out) == []
    assert captured.out.count("\n") == 1


def test_reconcile_returns_one_local_batch_document(capsys, tmp_path) -> None:
    rc = cli.main(
        [
            "reconcile",
            "--as-of",
            "2026-07-12T02:00:00Z",
            "--limit",
            "25",
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "schema_version": "1.0",
        "status": "available",
        "as_of": "2026-07-12T02:00:00Z",
        "processed_count": 0,
        "missed_count": 0,
        "next_cursor": None,
        "results": [],
    }
    assert captured.out.count("\n") == 1


def test_reconcile_rejects_noncanonical_cursor_as_one_json_error(capsys, tmp_path):
    rc = cli.main(
        [
            "reconcile",
            "--cursor",
            "zzz",
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_invalid_request",
            "message": "cursor must be a canonical signal_id",
            "retryable": False,
        }
    }


def test_record_action_verifies_explicit_platform_identities_before_linking(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir = tmp_path / "opportunities"
    signal = _eligible_signal()
    cli.OpportunityTracker(
        opportunity_dir,
        now=lambda: "2026-07-12T01:00:00Z",
    ).record(
        {
            "event": "signal_observed",
            "request_id": f"sync-signals:{signal['signal_id']}",
            "payload": signal,
        }
    )
    calls = []

    def run_observations(**kwargs):
        calls.append(kwargs)
        return 0, json.dumps(_record_action_document())

    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        run_observations,
    )
    monkeypatch.setattr(cli.runlog, "utc_now_iso", lambda: "2026-07-12T12:06:00Z")

    rc = cli.main(
        [
            "record-action",
            "--signal-id",
            signal["signal_id"],
            "--platform-signal-id",
            "platform-signal-1",
            "--platform-execution-id",
            "platform-execution-1",
            "--actor",
            "human:sunyibo",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert rc == 0
    assert captured.err == ""
    assert calls == [{"signal_id": "platform-signal-1", "limit": 200}]
    assert document["resolution"] == "acted"
    assert document["actions"][0]["platform_execution_id"] == ("platform-execution-1")
    assert document["actions"][0]["status"] == "pending"
    assert captured.out.count("\n") == 1


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("wrong_query", "opportunity_platform_observation_invalid"),
        ("wrong_count", "opportunity_platform_observation_invalid"),
        ("nonzero_quality", "opportunity_platform_observation_incomplete"),
        ("reported_error", "opportunity_platform_observation_incomplete"),
    ],
)
def test_record_action_rejects_untrustworthy_platform_envelope_without_linking(
    monkeypatch,
    capsys,
    tmp_path,
    mutation,
    error_code,
) -> None:
    opportunity_dir, signal = _store_eligible_signal(tmp_path)
    document = _record_action_document()
    if mutation == "wrong_query":
        document["query"]["signal_id"] = "another-platform-signal"
    elif mutation == "wrong_count":
        document["returned_count"] = 2
    elif mutation == "nonzero_quality":
        document["ops_quality"]["pending_sleeve_count"] = 1
    else:
        document["errors"] = [{"code": "recovery_required"}]
    before = (opportunity_dir / "entries.jsonl").read_bytes()
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (0, json.dumps(document)),
    )

    rc = cli.main(
        [
            "record-action",
            "--signal-id",
            signal["signal_id"],
            "--platform-signal-id",
            "platform-signal-1",
            "--platform-execution-id",
            "platform-execution-1",
            "--actor",
            "human:sunyibo",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out)["error"]["code"] == error_code
    assert (opportunity_dir / "entries.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    "duplicate",
    ["observation", "execution", "distinct-execution"],
)
def test_record_action_rejects_duplicate_platform_identities_without_linking(
    monkeypatch,
    capsys,
    tmp_path,
    duplicate,
) -> None:
    opportunity_dir, signal = _store_eligible_signal(tmp_path)
    document = _record_action_document()
    if duplicate == "observation":
        document["observations"].append(copy.deepcopy(document["observations"][0]))
        document["returned_count"] = 2
    elif duplicate == "execution":
        document["observations"][0]["executions"].append(
            copy.deepcopy(document["observations"][0]["executions"][0])
        )
    else:
        second = copy.deepcopy(document["observations"][0]["executions"][0])
        second["execution_id"] = "platform-execution-2"
        document["observations"][0]["executions"].append(second)
    before = (opportunity_dir / "entries.jsonl").read_bytes()
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (0, json.dumps(document)),
    )

    rc = cli.main(
        [
            "record-action",
            "--signal-id",
            signal["signal_id"],
            "--platform-signal-id",
            "platform-signal-1",
            "--platform-execution-id",
            "platform-execution-1",
            "--actor",
            "human:sunyibo",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out)["error"]["code"] == (
        "opportunity_platform_observation_invalid"
    )
    assert (opportunity_dir / "entries.jsonl").read_bytes() == before


def test_sync_actions_records_explicit_complete_untruncated_coverage(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir = tmp_path / "opportunities"
    signal = _eligible_signal()
    cli.OpportunityTracker(
        opportunity_dir,
        now=lambda: "2026-07-12T01:00:00Z",
    ).record(
        {
            "event": "signal_observed",
            "request_id": f"sync-signals:{signal['signal_id']}",
            "payload": signal,
        }
    )
    calls = []

    def run_observations(**kwargs):
        calls.append(kwargs)
        return 0, json.dumps(
            {
                "schema_version": 1,
                "snapshot_at": "2026-07-13T01:02:03Z",
                "read_status": "available",
                "query": {
                    "from_date": "2026-07-10",
                    "to_date": "2026-07-13",
                    "signal_id": None,
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
                        "signal": {
                            "signal_id": "unlinked-platform-signal",
                            "target_weights": {"AAPL": 1.0},
                        },
                        "executions": [
                            {
                                "execution_id": "unlinked-platform-execution",
                                "signal_id": "unlinked-platform-signal",
                            }
                        ],
                    }
                ],
                "errors": [],
            }
        )

    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        run_observations,
    )
    monkeypatch.setattr(cli.runlog, "utc_now_iso", lambda: "2026-07-13T01:02:03Z")

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            signal["signal_id"],
            "--from-date",
            "2026-07-10",
            "--to-date",
            "2026-07-13",
            "--covered-through",
            "2026-07-13T00:00:00Z",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert rc == 0
    assert captured.err == ""
    assert calls == [
        {
            "from_date": "2026-07-10",
            "to_date": "2026-07-13",
            "limit": 200,
        }
    ]
    assert document["coverage"] == {
        "signal_id": signal["signal_id"],
        "source": "paper_strategy_observations",
        "snapshot_id": document["coverage"]["snapshot_id"],
        "observed_at": "2026-07-13T01:02:03Z",
        "covered_through": "2026-07-13T00:00:00Z",
        "complete": True,
        "truncated": False,
        "coverage_event_id": document["coverage"]["coverage_event_id"],
    }
    assert document["coverage"]["snapshot_id"].startswith("pso_")
    assert document["actions"] == []
    assert captured.out.count("\n") == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "malformed-observation",
        "duplicate-signal",
        "mismatched-execution",
        "multiple-executions",
    ],
)
def test_sync_actions_rejects_malformed_platform_evidence_before_complete_coverage(
    monkeypatch,
    capsys,
    tmp_path,
    mutation,
) -> None:
    opportunity_dir, signal = _store_eligible_signal(tmp_path)
    document = _coverage_document(
        from_date="2026-07-10",
        to_date="2026-07-13",
    )
    document["read_status"] = "available"
    document["observations"] = [
        {
            "signal": {"signal_id": "platform-signal-1"},
            "executions": [
                {
                    "execution_id": "platform-execution-1",
                    "signal_id": "platform-signal-1",
                }
            ],
        }
    ]
    if mutation == "malformed-observation":
        document["observations"] = [{}]
    elif mutation == "duplicate-signal":
        document["observations"].append(copy.deepcopy(document["observations"][0]))
    elif mutation == "mismatched-execution":
        document["observations"][0]["executions"][0]["signal_id"] = (
            "another-platform-signal"
        )
    else:
        second = copy.deepcopy(document["observations"][0]["executions"][0])
        second["execution_id"] = "platform-execution-2"
        document["observations"][0]["executions"].append(second)
    document["returned_count"] = len(document["observations"])
    before = (opportunity_dir / "entries.jsonl").read_bytes()
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (0, json.dumps(document)),
    )

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            signal["signal_id"],
            "--from-date",
            "2026-07-10",
            "--to-date",
            "2026-07-13",
            "--covered-through",
            "2026-07-13T00:00:00Z",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out)["error"]["code"] == (
        "opportunity_platform_observation_invalid"
    )
    assert (opportunity_dir / "entries.jsonl").read_bytes() == before


def test_sync_actions_rejects_coverage_beyond_platform_snapshot(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_eligible_signal(tmp_path)
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (
            0,
            json.dumps(_coverage_document(snapshot_at="2026-07-13T00:00:00Z")),
        ),
    )

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            signal["signal_id"],
            "--covered-through",
            "2026-07-13T00:00:01Z",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    error = json.loads(capsys.readouterr().out)["error"]
    assert rc == 1
    assert error["code"] == "opportunity_platform_observation_incomplete"
    assert "watermark" in error["message"]
    assert len((opportunity_dir / "entries.jsonl").read_text().splitlines()) == 1


def test_sync_actions_rejects_query_that_starts_after_signal_source(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_eligible_signal(tmp_path)
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (
            0,
            json.dumps(
                _coverage_document(
                    from_date="2026-07-11",
                    to_date="2026-07-13",
                )
            ),
        ),
    )

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            signal["signal_id"],
            "--from-date",
            "2026-07-11",
            "--to-date",
            "2026-07-13",
            "--covered-through",
            "2026-07-13T00:00:00Z",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    error = json.loads(capsys.readouterr().out)["error"]
    assert rc == 1
    assert error["code"] == "opportunity_platform_observation_incomplete"
    assert "window" in error["message"]


def test_sync_actions_rejects_nonzero_quality_even_if_status_claims_empty(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_eligible_signal(tmp_path)
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (
            0,
            json.dumps(_coverage_document(pending_sleeves=1)),
        ),
    )

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            signal["signal_id"],
            "--covered-through",
            "2026-07-13T00:00:00Z",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    error = json.loads(capsys.readouterr().out)["error"]
    assert rc == 1
    assert error["code"] == "opportunity_platform_observation_incomplete"
    assert "quality" in error["message"]


def test_platform_observation_parser_rejects_duplicate_keys() -> None:
    payload = (
        '{"schema_version":1,"read_status":"empty","read_status":"available",'
        '"returned_count":0,"truncated":false,"observations":[],"errors":[]}'
    )

    with pytest.raises(cli._OpportunityCliError) as excinfo:
        cli._parse_platform_observations(payload)

    assert excinfo.value.code == "opportunity_platform_observation_invalid"


def test_unknown_signal_is_one_nonretryable_json_request_error(
    capsys,
    tmp_path,
) -> None:
    rc = cli.main(
        [
            "decide",
            "--signal-id",
            "sig_unknown",
            "--decision",
            "act",
            "--actor",
            "human:sunyibo",
            "--reason",
            "approved",
            "--request-id",
            "decision:unknown:act",
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_invalid_request",
            "message": "opportunity event references an unknown signal_id",
            "retryable": False,
        }
    }
    assert captured.out.count("\n") == 1


def test_record_action_rejects_unverified_explicit_ids_as_one_json_error(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir = tmp_path / "opportunities"
    signal = _eligible_signal()
    cli.OpportunityTracker(
        opportunity_dir,
        now=lambda: "2026-07-12T01:00:00Z",
    ).record(
        {
            "event": "signal_observed",
            "request_id": f"sync-signals:{signal['signal_id']}",
            "payload": signal,
        }
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (
            0,
            json.dumps(
                {
                    **_record_action_document(),
                    "read_status": "empty",
                    "query": {
                        "from_date": None,
                        "to_date": None,
                        "signal_id": "platform-signal-missing",
                        "limit": 200,
                    },
                    "returned_count": 0,
                    "observations": [],
                }
            ),
        ),
    )

    rc = cli.main(
        [
            "record-action",
            "--signal-id",
            signal["signal_id"],
            "--platform-signal-id",
            "platform-signal-missing",
            "--platform-execution-id",
            "platform-execution-missing",
            "--actor",
            "human:sunyibo",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_platform_identity_unverified",
            "message": (
                "platform signal_id and execution_id could not be verified together"
            ),
            "retryable": False,
        }
    }
    assert captured.out.count("\n") == 1
    assert (
        len(
            (opportunity_dir / "entries.jsonl").read_text(encoding="utf-8").splitlines()
        )
        == 1
    )


def test_sync_actions_rejects_truncated_evidence_without_recording_coverage(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir = tmp_path / "opportunities"
    signal = _eligible_signal()
    cli.OpportunityTracker(
        opportunity_dir,
        now=lambda: "2026-07-12T01:00:00Z",
    ).record(
        {
            "event": "signal_observed",
            "request_id": f"sync-signals:{signal['signal_id']}",
            "payload": signal,
        }
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (
            0,
            json.dumps(
                {
                    "schema_version": 1,
                    "read_status": "available",
                    "returned_count": 200,
                    "truncated": True,
                    "observations": [],
                    "errors": [],
                }
            ),
        ),
    )

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            signal["signal_id"],
            "--covered-through",
            "2026-07-13T00:00:00Z",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_platform_observation_incomplete",
            "message": (
                "platform observations must be available or empty and untruncated"
            ),
            "retryable": True,
        }
    }
    assert captured.out.count("\n") == 1
    assert (
        len(
            (opportunity_dir / "entries.jsonl").read_text(encoding="utf-8").splitlines()
        )
        == 1
    )


def test_sync_actions_requires_explicit_aware_coverage_timestamp_before_reading_platform(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    def unexpected_platform_call(**_kwargs):
        raise AssertionError("invalid coverage boundary must not call platform")

    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        unexpected_platform_call,
    )

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            "sig_example",
            "--covered-through",
            "2026-07-13T00:00:00",
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_invalid_arguments",
            "message": "--covered-through must be an aware UTC timestamp ending in Z",
            "retryable": False,
        }
    }
    assert captured.out.count("\n") == 1


def test_platform_command_failure_is_one_retryable_json_error(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_eligible_signal(tmp_path)
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (1, "platform diagnostic"),
    )

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            signal["signal_id"],
            "--covered-through",
            "2026-07-13T00:00:00Z",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_platform_unavailable",
            "message": "paper-strategy observations command failed",
            "retryable": True,
        }
    }
    assert captured.out.count("\n") == 1


def test_malformed_platform_output_is_one_retryable_json_error(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_eligible_signal(tmp_path)
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (0, "not-json\n"),
    )

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            signal["signal_id"],
            "--covered-through",
            "2026-07-13T00:00:00Z",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_platform_observation_invalid",
            "message": "paper-strategy observations returned invalid JSON",
            "retryable": True,
        }
    }
    assert captured.out.count("\n") == 1


def test_record_action_does_not_link_from_degraded_or_truncated_platform_evidence(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir = tmp_path / "opportunities"
    signal = _eligible_signal()
    cli.OpportunityTracker(
        opportunity_dir,
        now=lambda: "2026-07-12T01:00:00Z",
    ).record(
        {
            "event": "signal_observed",
            "request_id": f"sync-signals:{signal['signal_id']}",
            "payload": signal,
        }
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (
            0,
            json.dumps(
                {
                    "schema_version": 1,
                    "read_status": "degraded",
                    "returned_count": 1,
                    "truncated": False,
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
                    "errors": [{"code": "recovery_required"}],
                }
            ),
        ),
    )

    rc = cli.main(
        [
            "record-action",
            "--signal-id",
            signal["signal_id"],
            "--platform-signal-id",
            "platform-signal-1",
            "--platform-execution-id",
            "platform-execution-1",
            "--actor",
            "human:sunyibo",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert json.loads(captured.out)["error"] == {
        "code": "opportunity_platform_observation_incomplete",
        "message": "platform observations must be available and untruncated",
        "retryable": True,
    }
    assert (
        len(
            (opportunity_dir / "entries.jsonl").read_text(encoding="utf-8").splitlines()
        )
        == 1
    )


def test_record_action_rejects_invalid_platform_schema_as_one_json_error(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        lambda **_kwargs: (
            0,
            json.dumps(
                {
                    "schema_version": 1,
                    "read_status": "available",
                    "truncated": False,
                    "observations": "not-a-list",
                }
            ),
        ),
    )

    rc = cli.main(
        [
            "record-action",
            "--signal-id",
            "sig_example",
            "--platform-signal-id",
            "platform-signal-1",
            "--platform-execution-id",
            "platform-execution-1",
            "--actor",
            "human:sunyibo",
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_platform_observation_invalid",
            "message": "paper-strategy observations returned invalid schema",
            "retryable": True,
        }
    }
    assert captured.out.count("\n") == 1


def test_sync_signals_maps_corrupt_artifact_to_one_retryable_json_error(
    capsys,
    tmp_path,
) -> None:
    scan_dir = tmp_path / "scans"
    scan_dir.mkdir()
    (scan_dir / "2026-07-10.jsonl").write_text("{broken\n", encoding="utf-8")

    rc = cli.main(
        [
            "sync-signals",
            "--date",
            "2026-07-10",
            "--scan-dir",
            str(scan_dir),
            "--thresholds",
            str(tmp_path / "thresholds.json"),
            "--opportunity-dir",
            str(tmp_path / "opportunities"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_signal_source_unavailable",
            "message": "signal artifact could not be read",
            "retryable": True,
        }
    }
    assert captured.out.count("\n") == 1


def test_platform_invocation_exception_is_one_retryable_json_error(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    opportunity_dir, signal = _store_eligible_signal(tmp_path)

    def unavailable(**_kwargs):
        raise OSError("platform binary unavailable")

    monkeypatch.setattr(
        cli.quant_cli,
        "run_paper_strategy_observations",
        unavailable,
    )

    rc = cli.main(
        [
            "sync-actions",
            "--signal-id",
            signal["signal_id"],
            "--covered-through",
            "2026-07-13T00:00:00Z",
            "--opportunity-dir",
            str(opportunity_dir),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {
            "code": "opportunity_platform_unavailable",
            "message": "paper-strategy observations command failed",
            "retryable": True,
        }
    }
    assert captured.out.count("\n") == 1
