from __future__ import annotations

import json

import pytest

from hqa import research_automation_cli
from hqa.research_automation import AutomationError


def test_request_id_uses_stable_shanghai_schedule_slot() -> None:
    as_of = "2026-07-12T01:05:00Z"

    assert research_automation_cli.request_id_for("daily_close", as_of) == (
        "daily_close:2026-07-12"
    )
    assert research_automation_cli.request_id_for("weekly", as_of) == "weekly:2026-W28"
    assert research_automation_cli.request_id_for("freshness", as_of) == (
        "freshness:2026-07-12T08"
    )
    assert research_automation_cli.request_id_for("notification_drain", as_of) == (
        "notification_drain:2026-07-12T08:52"
    )


def test_automatic_daily_retry_uses_the_same_primary_schedule_intent(
    monkeypatch,
) -> None:
    calls = []
    clock = iter(("2026-07-11T00:15:09Z", "2026-07-11T00:25:42Z"))

    class Runner:
        def run(self, **kwargs):
            calls.append(kwargs)
            return {"status": "available"}

    monkeypatch.setattr(
        research_automation_cli.runlog,
        "utc_now_iso",
        lambda: next(clock),
    )
    monkeypatch.setattr(research_automation_cli, "_runtime", lambda: Runner())

    assert research_automation_cli.main(["daily_close"]) == 0
    assert research_automation_cli.main(["daily_close"]) == 0
    assert calls == [
        {
            "job": "daily_close",
            "request_id": "daily_close:2026-07-11",
            "as_of": "2026-07-11T00:15:00Z",
        },
        {
            "job": "daily_close",
            "request_id": "daily_close:2026-07-11",
            "as_of": "2026-07-11T00:15:00Z",
        },
    ]


def test_automatic_weekly_retry_uses_the_same_primary_schedule_intent(
    monkeypatch,
) -> None:
    calls = []
    clock = iter(("2026-07-12T01:00:11Z", "2026-07-12T01:10:37Z"))

    class Runner:
        def run(self, **kwargs):
            calls.append(kwargs)
            return {"status": "available"}

    monkeypatch.setattr(
        research_automation_cli.runlog,
        "utc_now_iso",
        lambda: next(clock),
    )
    monkeypatch.setattr(research_automation_cli, "_runtime", lambda: Runner())

    assert research_automation_cli.main(["weekly"]) == 0
    assert research_automation_cli.main(["weekly"]) == 0
    assert calls == [
        {
            "job": "weekly",
            "request_id": "weekly:2026-W28",
            "as_of": "2026-07-12T01:00:00Z",
        },
        {
            "job": "weekly",
            "request_id": "weekly:2026-W28",
            "as_of": "2026-07-12T01:00:00Z",
        },
    ]


def test_automatic_freshness_uses_the_even_hour_schedule_instant(monkeypatch) -> None:
    calls = []

    class Runner:
        def run(self, **kwargs):
            calls.append(kwargs)
            return {"status": "available"}

    monkeypatch.setattr(
        research_automation_cli.runlog,
        "utc_now_iso",
        lambda: "2026-07-12T00:17:31Z",
    )
    monkeypatch.setattr(research_automation_cli, "_runtime", lambda: Runner())

    assert research_automation_cli.main(["freshness"]) == 0
    assert calls == [
        {
            "job": "freshness",
            "request_id": "freshness:2026-07-12T08",
            "as_of": "2026-07-12T00:17:00Z",
        }
    ]


def test_automatic_notification_drain_uses_latest_non_future_schedule_instant(
    monkeypatch,
) -> None:
    calls = []

    class Runner:
        def run(self, **kwargs):
            calls.append(kwargs)
            return {"status": "available"}

    monkeypatch.setattr(
        research_automation_cli.runlog,
        "utc_now_iso",
        lambda: "2026-07-12T01:05:59Z",
    )
    monkeypatch.setattr(research_automation_cli, "_runtime", lambda: Runner())

    assert research_automation_cli.main(["notification_drain"]) == 0
    assert calls == [
        {
            "job": "notification_drain",
            "request_id": "notification_drain:2026-07-12T08:52",
            "as_of": "2026-07-12T00:52:00Z",
        }
    ]


@pytest.mark.parametrize(
    ("job", "observed_at", "expected_as_of", "expected_request_id"),
    [
        (
            "daily_close",
            "2026-07-14T00:14:59Z",  # Tuesday 08:14:59 CST, before primary slot.
            "2026-07-11T00:15:00Z",
            "daily_close:2026-07-11",
        ),
        (
            "daily_close",
            "2026-07-13T04:00:00Z",  # Monday has no daily-close slot.
            "2026-07-11T00:15:00Z",
            "daily_close:2026-07-11",
        ),
        (
            "daily_close",
            "2026-07-14T00:25:00Z",
            "2026-07-14T00:15:00Z",
            "daily_close:2026-07-14",
        ),
        (
            "weekly",
            "2026-07-12T00:59:59Z",  # Sunday 08:59:59 CST.
            "2026-07-05T01:00:00Z",
            "weekly:2026-W27",
        ),
        (
            "weekly",
            "2026-07-13T04:00:00Z",  # Monday maps to the prior Sunday.
            "2026-07-12T01:00:00Z",
            "weekly:2026-W28",
        ),
        (
            "weekly",
            "2026-07-12T01:10:00Z",
            "2026-07-12T01:00:00Z",
            "weekly:2026-W28",
        ),
        (
            "freshness",
            "2026-07-12T00:16:59Z",  # 08:16:59 CST, before :17.
            "2026-07-11T22:17:00Z",
            "freshness:2026-07-12T06",
        ),
        (
            "freshness",
            "2026-07-12T00:17:01Z",
            "2026-07-12T00:17:00Z",
            "freshness:2026-07-12T08",
        ),
    ],
)
def test_automatic_jobs_use_latest_non_future_primary_slot(
    monkeypatch,
    job,
    observed_at,
    expected_as_of,
    expected_request_id,
) -> None:
    calls = []

    class Runner:
        def run(self, **kwargs):
            calls.append(kwargs)
            return {"status": "available"}

    monkeypatch.setattr(
        research_automation_cli.runlog,
        "utc_now_iso",
        lambda: observed_at,
    )
    monkeypatch.setattr(research_automation_cli, "_runtime", lambda: Runner())

    assert research_automation_cli.main([job]) == 0
    assert calls == [
        {
            "job": job,
            "request_id": expected_request_id,
            "as_of": expected_as_of,
        }
    ]


def test_main_emits_one_strict_json_document_and_maps_degraded_to_one(
    monkeypatch,
    capsys,
) -> None:
    calls = []

    class Runner:
        def run(self, **kwargs):
            calls.append(kwargs)
            return {"status": "degraded", "reason": None}

    monkeypatch.setattr(research_automation_cli, "_runtime", lambda: Runner())

    rc = research_automation_cli.main(["freshness", "--as-of", "2026-07-12T01:05:00Z"])

    assert rc == 1
    assert calls == [
        {
            "job": "freshness",
            "request_id": "freshness:2026-07-12T08",
            "as_of": "2026-07-12T01:05:00Z",
        }
    ]
    assert json.loads(capsys.readouterr().out) == {"reason": None, "status": "degraded"}


def test_main_preserves_explicit_request_id_and_as_of(monkeypatch) -> None:
    calls = []

    class Runner:
        def run(self, **kwargs):
            calls.append(kwargs)
            return {"status": "available"}

    monkeypatch.setattr(research_automation_cli, "_runtime", lambda: Runner())

    assert (
        research_automation_cli.main(
            [
                "weekly",
                "--as-of",
                "2026-07-12T09:10:37+08:00",
                "--request-id",
                "manual-weekly-retry",
            ]
        )
        == 0
    )
    assert calls == [
        {
            "job": "weekly",
            "request_id": "manual-weekly-retry",
            "as_of": "2026-07-12T09:10:37+08:00",
        }
    ]


def test_main_sanitizes_stable_errors(monkeypatch, capsys) -> None:
    class Runner:
        def run(self, **kwargs):
            raise AutomationError(
                "automation_idempotency_conflict", "safe", retryable=False
            )

    monkeypatch.setattr(research_automation_cli, "_runtime", lambda: Runner())

    rc = research_automation_cli.main(
        [
            "weekly",
            "--as-of",
            "2026-07-12T01:05:00Z",
            "--request-id",
            "conflict",
        ]
    )

    assert rc == 2
    assert json.loads(capsys.readouterr().out) == {
        "error": {
            "code": "automation_idempotency_conflict",
            "message": "safe",
            "retryable": False,
        }
    }
