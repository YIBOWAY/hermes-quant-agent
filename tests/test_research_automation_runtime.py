from __future__ import annotations

import json

import pytest

from hqa import research_automation, research_automation_runtime


AS_OF = "2026-07-12T01:05:00Z"


def _notifications(**updates: int) -> dict[str, int]:
    summary = {
        "planned": 0,
        "delivered": 0,
        "queued": 0,
        "fallback_persisted": 0,
        "delivery_unknown": 0,
        "suppressed": 0,
    }
    summary.update(updates)
    return summary


def _paths(tmp_path):
    return research_automation_runtime.Full9HPaths(
        log_dir=tmp_path / "logs",
        review_dir=tmp_path / "review",
        prediction_dir=tmp_path / "predictions",
        opportunity_dir=tmp_path / "opportunities",
        foresight_dir=tmp_path / "foresight",
        scan_dir=tmp_path / "scans",
        thresholds_path=tmp_path / "thresholds.json",
        automation_dir=tmp_path / "automation",
        outbox_path=tmp_path / "automation" / "outbox.jsonl",
        feed_path=tmp_path / "feed" / "manifest.v1.json",
        weekly_projection_path=tmp_path / "feed" / "projections" / "weekly.json",
        opportunity_projection_path=tmp_path
        / "feed"
        / "projections"
        / "opportunity.json",
        automation_projection_path=tmp_path
        / "feed"
        / "projections"
        / "automation.json",
    )


def _candidate() -> dict:
    return {
        "ticker": "NVDA",
        "strategy": "sell_put",
        "global_score": 91.5,
        "iv_rank": 0.88,
        "run_date": "2026-07-10",
        "candidate": {
            "symbol": "US.NVDA260717P150000",
            "underlying": "US.NVDA",
        },
    }


def _legacy_signal_row(*, extended: bool = False) -> dict:
    row = {
        "ts": "2026-07-10T00:00:00Z",
        "job": "signal-watchdog",
        "scan_exit": 0,
        "factor_exit": 0,
        "n_candidates": 0,
        "score_summary": {
            "count": 0,
            "iv_rank_known": 0,
            "score_max": None,
            "score_p50": None,
            "score_p90": None,
        },
        "factor_lab": {},
        "thresholds": {"min_score": 150.0, "min_iv_rank": None},
        "has_signal": False,
        "signals": [],
    }
    if extended:
        row.update(
            {
                "factor_lab_skipped": True,
                "mode": "alert",
                "run_date": "2026-07-10",
                "artifact_missing": True,
            }
        )
    return row


def test_signal_catchup_uses_latest_existing_scan_and_is_idempotent(tmp_path) -> None:
    paths = _paths(tmp_path)
    paths.scan_dir.mkdir()
    (paths.scan_dir / "2026-07-10.jsonl").write_text(
        json.dumps(_candidate()) + "\n",
        encoding="utf-8",
    )
    paths.thresholds_path.write_text(
        json.dumps({"min_score": 90, "min_iv_rank": None}),
        encoding="utf-8",
    )
    observations = []
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: AS_OF,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
        run_observations=lambda **kwargs: observations.append(kwargs) or (1, ""),
        notification_target="local",
    )

    first = services.signal_catchup(AS_OF)
    second = services.signal_catchup(AS_OF)

    assert first["status"] == "available"
    assert first["source_date"] == "2026-07-10"
    assert first["signal_count"] == 1
    assert second["signal_count"] == 1
    states = services.opportunity_tracker.list()
    assert len(states) == 1
    assert states[0]["resolution"] == "not_actionable"
    assert len((paths.opportunity_dir / "entries.jsonl").read_text().splitlines()) == 1

    coverage = services.opportunity_coverage(AS_OF)

    assert coverage["status"] == "empty"
    assert coverage["processed_count"] == 0
    assert observations == []


def test_signal_catchup_skips_unreadable_newest_scan(tmp_path) -> None:
    paths = _paths(tmp_path)
    paths.scan_dir.mkdir()
    # Newest date is empty/torn and must not fail the step.
    (paths.scan_dir / "2026-07-11.jsonl").write_bytes(b"")
    (paths.scan_dir / "2026-07-10.jsonl").write_text(
        json.dumps(_candidate()) + "\n",
        encoding="utf-8",
    )
    paths.thresholds_path.write_text(
        json.dumps({"min_score": 90, "min_iv_rank": None}),
        encoding="utf-8",
    )
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: AS_OF,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
        run_observations=lambda **kwargs: (1, ""),
        notification_target="local",
    )

    result = services.signal_catchup(AS_OF)

    assert result["status"] == "available"
    assert result["source_date"] == "2026-07-10"
    assert result["signal_count"] == 1
    assert result["skipped_unreadable_source_dates"] == ["2026-07-11"]


def test_projection_feed_and_local_notification_are_real_but_read_only(
    tmp_path,
) -> None:
    paths = _paths(tmp_path)
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: AS_OF,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
        run_observations=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "empty opportunity store must not read platform observations"
            )
        ),
        notification_target="local",
    )

    weekly = services.weekly_projection(AS_OF)
    opportunity = services.opportunity_projection(AS_OF)
    automation = services.automation_projection(
        "freshness",
        AS_OF,
        "run:freshness",
        [],
        _notifications(),
    )
    feed = services.feed_refresh(AS_OF)
    notification = services.notification_enqueue(
        {"request_id": "local:test", "target": "local", "message": "ready"}
    )
    drained = services.notification_drain(AS_OF)

    assert weekly["status"] == "available"
    assert opportunity["status"] == "available"
    assert automation["status"] == "available"
    assert automation["overall_status"] == "degraded"
    assert feed["schema_version"] == "1.1"
    assert {source["kind"] for source in feed["sources"]} == {
        "portfolio_risk",
        "prediction",
        "market_foresight",
        "weekly_review",
        "opportunity_summary",
        "automation_status",
    }
    assert notification["state"] == "delivered"
    assert drained["status"] == "available"
    assert drained["processed_count"] == 0


def test_projection_uses_current_run_notification_truth(tmp_path) -> None:
    paths = _paths(tmp_path)
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: AS_OF,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
        notification_target="local",
    )

    projection = services.automation_projection(
        "weekly",
        AS_OF,
        "run:weekly-local",
        [],
        _notifications(planned=1, delivered=1),
    )

    weekly = next(
        job
        for job in projection["artifact"]["data"]["jobs"]
        if job["job_id"] == "weekly"
    )
    assert weekly["notification_status"] == "delivered"


def test_notification_drain_caps_each_run_below_the_schedule_gap(tmp_path) -> None:
    paths = _paths(tmp_path)
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: AS_OF,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
    )
    limits = []

    def capture_drain(send_adapter, *, limit):
        limits.append(limit)
        return {"status": "available", "processed_count": 0}

    services.outbox.drain = capture_drain

    result = services.notification_drain(AS_OF)

    assert result["status"] == "available"
    assert limits == [5]


def test_drain_overlays_pending_retryable_and_delivered_outbox_truth(tmp_path) -> None:
    paths = _paths(tmp_path)
    outcomes = iter(
        [
            research_automation_runtime.NotificationSendResult.known_failure(
                "remote_unavailable"
            ),
            research_automation_runtime.NotificationSendResult.delivered(),
        ]
    )
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: AS_OF,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
        send_adapter=lambda target, message, timeout: next(outcomes),
        notification_target="discord:research",
    )
    services.weekly_projection = lambda as_of: {"status": "available"}
    services.opportunity_projection = lambda as_of: {"status": "available"}
    services.feed_refresh = lambda as_of: {"status": "available"}
    runner = research_automation.ResearchAutomation(
        paths.automation_dir,
        services=services,
        now=lambda: AS_OF,
        notification_target="discord:research",
    )

    weekly_receipt = runner.run(
        job="weekly",
        request_id="weekly:remote",
        as_of=AS_OF,
    )
    pending_projection = json.loads(
        paths.automation_projection_path.read_text(encoding="utf-8")
    )

    assert weekly_receipt["status"] == "available"
    assert weekly_receipt["notifications"] == _notifications(planned=1, queued=1)
    assert next(
        job
        for job in pending_projection["data"]["jobs"]
        if job["job_id"] == "weekly"
    )["notification_status"] == "queued"

    runner.run(job="notification_drain", request_id="drain:retry", as_of=AS_OF)
    retry_projection = json.loads(
        paths.automation_projection_path.read_text(encoding="utf-8")
    )

    assert next(
        job
        for job in retry_projection["data"]["jobs"]
        if job["job_id"] == "weekly"
    )["notification_status"] == "queued"

    runner.run(job="notification_drain", request_id="drain:deliver", as_of=AS_OF)
    delivered_projection = json.loads(
        paths.automation_projection_path.read_text(encoding="utf-8")
    )

    assert next(
        job
        for job in delivered_projection["data"]["jobs"]
        if job["job_id"] == "weekly"
    )["notification_status"] == "delivered"


def test_delayed_daily_catchup_then_weekly_uses_observed_publication_time(
    tmp_path,
) -> None:
    paths = _paths(tmp_path)
    observed_at = "2026-07-12T09:19:00Z"
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: observed_at,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
        notification_target="local",
    )
    services.signal_catchup = lambda as_of: {
        "status": "empty",
        "signal_count": 0,
    }
    services.portfolio_risk = lambda as_of: {"status": "available"}
    services.prediction_reconcile = lambda as_of: {
        "status": "empty",
        "processed_count": 0,
        "results": [],
    }
    services.opportunity_coverage = lambda as_of: {
        "status": "empty",
        "processed_count": 0,
    }
    services.opportunity_reconcile = lambda as_of: {
        "status": "available",
        "missed_count": 0,
    }
    runner = research_automation.ResearchAutomation(
        paths.automation_dir,
        services=services,
        now=lambda: observed_at,
        notification_target="local",
    )

    daily = runner.run(
        job="daily_close",
        request_id="daily_close:2026-07-11",
        as_of="2026-07-11T00:15:00Z",
    )
    weekly = runner.run(
        job="weekly",
        request_id="weekly:2026-W28",
        as_of="2026-07-12T01:00:00Z",
    )
    automation = json.loads(
        paths.automation_projection_path.read_text(encoding="utf-8")
    )
    feed = json.loads(paths.feed_path.read_text(encoding="utf-8"))

    assert daily["as_of"] == "2026-07-11T00:15:00Z"
    assert daily["completed_at"] == observed_at
    assert weekly["as_of"] == "2026-07-12T01:00:00Z"
    assert weekly["status"] == "available"
    assert automation["generated_at"] == observed_at
    assert automation["data"]["checked_at"] == observed_at
    weekly_status = next(
        job
        for job in automation["data"]["jobs"]
        if job["job_id"] == "weekly"
    )
    assert weekly_status["last_attempt_at"] == observed_at
    assert feed["schema_version"] == "1.1"
    assert feed["read_status"] == "available"
    assert feed["as_of"] == observed_at
    assert all(item["occurred_at"] <= feed["as_of"] for item in feed["items"])


def test_observed_projection_clock_does_not_hide_a_truly_stale_job(tmp_path) -> None:
    paths = _paths(tmp_path)
    clock = ["2026-07-01T00:17:00Z"]
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: clock[0],
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
        notification_target="local",
    )
    services.opportunity_projection = lambda as_of: {"status": "available"}
    services.feed_refresh = lambda as_of: {"status": "available"}
    runner = research_automation.ResearchAutomation(
        paths.automation_dir,
        services=services,
        now=lambda: clock[0],
        notification_target="local",
    )
    runner.run(
        job="freshness",
        request_id="freshness:2026-07-01T08",
        as_of="2026-07-01T00:17:00Z",
    )
    clock[0] = "2026-07-12T09:19:00Z"

    projection = services.automation_projection(
        "weekly",
        "2026-07-12T01:00:00Z",
        "provisional-current-weekly",
        [],
        _notifications(),
    )

    freshness = next(
        job
        for job in projection["artifact"]["data"]["jobs"]
        if job["job_id"] == "freshness"
    )
    assert projection["artifact"]["generated_at"] == clock[0]
    assert freshness["status"] == "stale"
    assert freshness["reason_code"] == "freshness_budget_exceeded"


@pytest.mark.parametrize(
    "legacy_row",
    [_legacy_signal_row(), _legacy_signal_row(extended=True)],
    ids=["base", "extended"],
)
def test_weekly_projection_skips_pre_opportunity_legacy_signal_rows(
    tmp_path,
    legacy_row,
) -> None:
    paths = _paths(tmp_path)
    paths.log_dir.mkdir()
    (paths.log_dir / "signal_watchdog.jsonl").write_text(
        json.dumps(legacy_row) + "\n",
        encoding="utf-8",
    )
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: AS_OF,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
    )
    services._opportunities = lambda: [
        {
            "signal_id": "authoritative-signal",
            "signal": {"observed_at": "2026-07-10T00:00:00Z"},
            "resolution": "open",
            "missed_assessment": None,
        }
    ]

    result = services.weekly_projection(AS_OF)

    assert result["status"] == "available"
    assert result["artifact"]["reason_codes"] == []
    assert result["artifact"]["data"]["unique_signal_count"] == 1


@pytest.mark.parametrize(
    "invalid_row",
    [
        {
            "ts": "2026-07-10T00:00:00Z",
            "job": "signal-watchdog",
            "error": "scan failed",
        },
        {**_legacy_signal_row(), "unknown_field": "must-not-be-hidden"},
        {**_legacy_signal_row(), "n_candidates": "0"},
    ],
    ids=["error", "unknown-field", "wrong-type"],
)
def test_weekly_projection_does_not_hide_unknown_or_failed_legacy_rows(
    tmp_path,
    invalid_row,
) -> None:
    paths = _paths(tmp_path)
    paths.log_dir.mkdir()
    (paths.log_dir / "signal_watchdog.jsonl").write_text(
        json.dumps(invalid_row) + "\n",
        encoding="utf-8",
    )
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: AS_OF,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
    )

    result = services.weekly_projection(AS_OF)

    assert result["status"] == "degraded"
    assert result["artifact"]["reason_codes"] == ["weekly_signal_source_invalid"]


def test_weekly_projection_rejects_partial_new_signal_schema(tmp_path) -> None:
    paths = _paths(tmp_path)
    paths.log_dir.mkdir()
    (paths.log_dir / "signal_watchdog.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-07-10T00:00:00Z",
                "status": "ok",
                "opportunity_recorded_count": 1,
                "opportunity_record_errors": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    services = research_automation_runtime.Full9HServices(
        paths,
        now=lambda: AS_OF,
        run_snapshot=lambda account: (1, "unavailable"),
        run_history=lambda symbols, start, end: (1, "unavailable"),
    )

    result = services.weekly_projection(AS_OF)

    assert result["status"] == "degraded"
    assert result["artifact"]["reason_codes"] == ["weekly_signal_source_invalid"]
