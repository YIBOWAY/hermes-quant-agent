from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from hqa import research_automation


AS_OF = "2026-07-12T01:00:00Z"


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.enqueued: list[dict] = []
        self.block: threading.Event | None = None
        self.release: threading.Event | None = None
        self.fail_step: str | None = None
        self.crash_step: str | None = None
        self.notification_state = "delivered"

    def _step(self, name: str, result: dict | None = None) -> dict:
        self.calls.append(name)
        if self.block is not None and name == "signal_catchup":
            self.block.set()
            assert self.release is not None
            self.release.wait(timeout=5)
        if self.fail_step == name:
            raise RuntimeError("sensitive /private/path token=secret")
        if self.crash_step == name:
            self.crash_step = None
            raise KeyboardInterrupt("simulated process interruption")
        return result or {"status": "available"}

    def signal_catchup(self, as_of: str) -> dict:
        return self._step("signal_catchup", {"status": "empty", "signal_count": 0})

    def portfolio_risk(self, as_of: str) -> dict:
        return self._step("portfolio_risk")

    def prediction_reconcile(self, as_of: str) -> dict:
        return self._step(
            "prediction_reconcile",
            {
                "status": "available",
                "processed_count": 1,
                "results": [{"status": "scored"}],
            },
        )

    def opportunity_coverage(self, as_of: str) -> dict:
        return self._step(
            "opportunity_coverage", {"status": "empty", "processed_count": 0}
        )

    def opportunity_reconcile(self, as_of: str) -> dict:
        return self._step(
            "opportunity_reconcile", {"status": "available", "missed_count": 0}
        )

    def weekly_projection(self, as_of: str) -> dict:
        return self._step("weekly_projection")

    def opportunity_projection(self, as_of: str) -> dict:
        return self._step("opportunity_projection")

    def automation_projection(
        self,
        job: str,
        as_of: str,
        run_id: str,
        steps: list[dict],
        notifications: dict[str, int],
    ) -> dict:
        assert set(notifications) == {
            "planned",
            "delivered",
            "queued",
            "fallback_persisted",
            "delivery_unknown",
            "suppressed",
        }
        return self._step("automation_projection")

    def feed_refresh(self, as_of: str) -> dict:
        return self._step("feed_refresh")

    def notification_enqueue(self, request: dict) -> dict:
        self.calls.append("notification_enqueue")
        self.enqueued.append(request)
        return {"state": self.notification_state}

    def notification_drain(self, as_of: str) -> dict:
        return self._step(
            "notification_drain", {"status": "available", "delivered_count": 0}
        )


def _runner(tmp_path, services: FakeServices, times: list[str] | None = None):
    sequence = iter(times or ["2026-07-12T01:00:01Z", "2026-07-12T01:00:02Z"] * 10)
    return research_automation.ResearchAutomation(
        tmp_path / "automation",
        services=services,
        now=lambda: next(sequence),
        notification_target="local",
    )


def test_daily_close_runs_all_readonly_steps_once_and_replays(tmp_path) -> None:
    services = FakeServices()
    runner = _runner(tmp_path, services)

    first = runner.run(job="daily_close", request_id="daily:2026-07-12", as_of=AS_OF)
    replay = runner.run(job="daily_close", request_id="daily:2026-07-12", as_of=AS_OF)

    assert first["status"] == "available"
    assert first["replayed"] is False
    assert replay == {**first, "replayed": True}
    assert services.calls == [
        "signal_catchup",
        "portfolio_risk",
        "prediction_reconcile",
        "opportunity_coverage",
        "opportunity_reconcile",
        "opportunity_projection",
        "notification_enqueue",
        "automation_projection",
        "feed_refresh",
    ]
    assert first["notifications"]["planned"] == 1
    assert first["notifications"]["delivered"] == 1
    assert services.enqueued[0]["target"] == "local"
    assert "scored=1" in services.enqueued[0]["message"]
    rows = [
        json.loads(line)
        for line in (tmp_path / "automation" / "runs.jsonl").read_text().splitlines()
    ]
    assert rows == [first]
    assert (tmp_path / "automation" / "runs.jsonl").stat().st_mode & 0o777 == 0o600


def test_request_reuse_with_changed_intent_fails_closed(tmp_path) -> None:
    services = FakeServices()
    runner = _runner(tmp_path, services)
    runner.run(job="freshness", request_id="same", as_of=AS_OF)

    with pytest.raises(research_automation.AutomationError) as error:
        runner.run(
            job="weekly",
            request_id="same",
            as_of="2026-07-12T02:00:00Z",
        )

    assert error.value.code == "automation_idempotency_conflict"


def test_failed_step_degrades_but_later_projection_and_feed_continue(tmp_path) -> None:
    services = FakeServices()
    services.fail_step = "prediction_reconcile"
    runner = _runner(tmp_path, services)

    receipt = runner.run(job="daily_close", request_id="degraded", as_of=AS_OF)

    assert receipt["status"] == "degraded"
    failed = next(
        step for step in receipt["steps"] if step["name"] == "prediction_reconcile"
    )
    assert failed["status"] == "failed"
    assert failed["error"] == {
        "code": "automation_prediction_reconcile_failed",
        "retryable": True,
    }
    serialized = json.dumps(receipt)
    assert "sensitive" not in serialized
    assert "private/path" not in serialized
    assert "automation_projection" in services.calls
    assert "feed_refresh" in services.calls


def test_concurrent_trigger_returns_skipped_busy_without_duplicate_work(
    tmp_path,
) -> None:
    services = FakeServices()
    services.block = threading.Event()
    services.release = threading.Event()
    runner = _runner(
        tmp_path,
        services,
        times=["2026-07-12T01:00:01Z", "2026-07-12T01:00:02Z"] * 20,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            runner.run,
            job="daily_close",
            request_id="concurrent-a",
            as_of=AS_OF,
        )
        assert services.block.wait(timeout=5)
        second = runner.run(
            job="daily_close",
            request_id="concurrent-b",
            as_of=AS_OF,
        )
        services.release.set()
        completed = first.result(timeout=5)

    assert completed["status"] == "available"
    assert second["status"] == "skipped_busy"
    assert services.calls.count("signal_catchup") == 1
    busy_files = list((tmp_path / "automation" / "busy").glob("*.json"))
    assert len(busy_files) == 1
    assert busy_files[0].stat().st_mode & 0o777 == 0o600

    retried = runner.run(
        job="daily_close",
        request_id="concurrent-b",
        as_of=AS_OF,
    )

    assert retried["status"] == "available"
    assert services.calls.count("signal_catchup") == 2


def test_weekly_always_enqueues_once_and_drain_never_reads_market(tmp_path) -> None:
    services = FakeServices()
    runner = _runner(tmp_path, services)

    weekly = runner.run(job="weekly", request_id="week-28", as_of=AS_OF)
    services.calls.clear()
    drained = runner.run(job="notification_drain", request_id="drain-1", as_of=AS_OF)

    assert weekly["notifications"]["planned"] == 1
    assert services.enqueued[0]["request_id"].endswith(":weekly")
    assert drained["status"] == "available"
    assert services.calls == [
        "notification_drain",
        "automation_projection",
        "feed_refresh",
    ]


def test_queued_notification_is_available_and_final_projection_sees_queue(
    tmp_path,
) -> None:
    services = FakeServices()
    services.notification_state = "queued"
    projection_notifications = []

    def capture_projection(job, as_of, run_id, steps, notifications):
        services.calls.append("automation_projection")
        projection_notifications.append(dict(notifications))
        return {"status": "available"}

    services.automation_projection = capture_projection
    receipt = _runner(tmp_path, services).run(
        job="weekly",
        request_id="queued-weekly",
        as_of=AS_OF,
    )

    assert receipt["status"] == "available"
    assert receipt["notifications"]["queued"] == 1
    assert projection_notifications[-1]["queued"] == 1
    assert services.calls[-3:] == [
        "notification_enqueue",
        "automation_projection",
        "feed_refresh",
    ]


def test_finalizing_state_retries_only_receipt_append_after_failure(
    tmp_path,
    monkeypatch,
) -> None:
    services = FakeServices()
    runner = _runner(tmp_path, services)
    original = runner._append_receipt
    attempts = 0

    def fail_once(receipt):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated disk full")
        return original(receipt)

    monkeypatch.setattr(runner, "_append_receipt", fail_once)
    with pytest.raises(OSError):
        runner.run(job="weekly", request_id="durable-weekly", as_of=AS_OF)
    calls_after_failure = list(services.calls)

    recovered = runner.run(job="weekly", request_id="durable-weekly", as_of=AS_OF)

    assert recovered["status"] == "available"
    assert services.calls == calls_after_failure
    assert attempts == 2


def test_interrupted_step_is_outcome_unknown_and_is_not_repeated(tmp_path) -> None:
    services = FakeServices()
    services.crash_step = "weekly_projection"
    runner = _runner(tmp_path, services)

    with pytest.raises(KeyboardInterrupt):
        runner.run(job="weekly", request_id="interrupted-weekly", as_of=AS_OF)
    recovered = runner.run(
        job="weekly",
        request_id="interrupted-weekly",
        as_of=AS_OF,
    )

    assert services.calls.count("weekly_projection") == 1
    interrupted = next(
        step for step in recovered["steps"] if step["name"] == "weekly_projection"
    )
    assert interrupted["status"] == "outcome_unknown"
    assert interrupted["error"]["retryable"] is False


def test_receipt_append_handles_partial_os_write(tmp_path, monkeypatch) -> None:
    services = FakeServices()
    runner = _runner(tmp_path, services)
    real_write = research_automation.os.write

    def partial_write(fd, payload):
        size = max(1, len(payload) // 2)
        return real_write(fd, payload[:size])

    monkeypatch.setattr(research_automation.os, "write", partial_write)

    receipt = runner.run(job="weekly", request_id="partial-write", as_of=AS_OF)

    assert runner.latest("weekly") == receipt


def test_corrupt_receipt_store_fails_closed(tmp_path) -> None:
    automation = tmp_path / "automation"
    automation.mkdir(mode=0o700)
    receipt_path = automation / "runs.jsonl"
    receipt_path.write_text(
        '{"run_id":"a","run_id":"b"}\n', encoding="utf-8"
    )
    receipt_path.chmod(0o600)
    runner = _runner(tmp_path, FakeServices())

    with pytest.raises(research_automation.AutomationError) as error:
        runner.latest("daily_close")

    assert error.value.code == "automation_receipt_corrupt"


def test_complete_receipt_without_commit_newline_fails_closed(tmp_path) -> None:
    services = FakeServices()
    runner = _runner(tmp_path, services)
    runner.run(job="weekly", request_id="torn-after-body", as_of=AS_OF)
    receipt_path = tmp_path / "automation" / "runs.jsonl"
    committed = receipt_path.read_bytes()
    assert committed.endswith(b"\n")
    receipt_path.write_bytes(committed[:-1])

    with pytest.raises(research_automation.AutomationError) as error:
        runner.latest("weekly")

    assert error.value.code == "automation_receipt_corrupt"


def test_receipt_store_rejects_empty_audit_record(tmp_path) -> None:
    runner = _runner(tmp_path, FakeServices())
    runner.run(job="weekly", request_id="blank-record", as_of=AS_OF)
    receipt_path = tmp_path / "automation" / "runs.jsonl"
    receipt_path.write_bytes(receipt_path.read_bytes() + b"\n")

    with pytest.raises(research_automation.AutomationError) as error:
        runner.latest("weekly")

    assert error.value.code == "automation_receipt_corrupt"


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow required")
def test_automation_directory_symlink_fails_closed_before_domain_work(tmp_path) -> None:
    real_directory = tmp_path / "real-automation"
    real_directory.mkdir(mode=0o700)
    alias = tmp_path / "automation-alias"
    alias.symlink_to(real_directory, target_is_directory=True)
    services = FakeServices()
    runner = research_automation.ResearchAutomation(
        alias,
        services=services,
        now=lambda: AS_OF,
    )

    with pytest.raises(research_automation.AutomationError) as error:
        runner.run(job="weekly", request_id="directory-symlink", as_of=AS_OF)

    assert error.value.code == "automation_storage_insecure"
    assert services.calls == []


def test_insecure_automation_directory_mode_fails_closed(tmp_path) -> None:
    automation = tmp_path / "automation"
    automation.mkdir(mode=0o700)
    automation.chmod(0o755)
    services = FakeServices()
    runner = research_automation.ResearchAutomation(
        automation,
        services=services,
        now=lambda: AS_OF,
    )

    with pytest.raises(research_automation.AutomationError) as error:
        runner.run(job="weekly", request_id="directory-mode", as_of=AS_OF)

    assert error.value.code == "automation_storage_insecure"
    assert services.calls == []


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow required")
@pytest.mark.parametrize("filename", [".run.lock", "runs.jsonl"])
def test_lock_and_receipt_symlinks_fail_closed_without_touching_target(
    tmp_path,
    filename,
) -> None:
    automation = tmp_path / "automation"
    automation.mkdir(mode=0o700)
    target = tmp_path / f"outside-{filename.lstrip('.')}"
    target.write_bytes(b"do-not-touch\n")
    target.chmod(0o600)
    (automation / filename).symlink_to(target)
    services = FakeServices()
    runner = research_automation.ResearchAutomation(
        automation,
        services=services,
        now=lambda: AS_OF,
    )

    with pytest.raises(research_automation.AutomationError) as error:
        runner.run(job="weekly", request_id=f"symlink-{filename}", as_of=AS_OF)

    assert error.value.code == "automation_storage_insecure"
    assert target.read_bytes() == b"do-not-touch\n"
    assert services.calls == []


@pytest.mark.parametrize("filename", [".run.lock", "runs.jsonl"])
def test_insecure_lock_and_receipt_modes_fail_closed(tmp_path, filename) -> None:
    automation = tmp_path / "automation"
    automation.mkdir(mode=0o700)
    (automation / filename).write_bytes(b"")
    (automation / filename).chmod(0o644)
    services = FakeServices()
    runner = research_automation.ResearchAutomation(
        automation,
        services=services,
        now=lambda: AS_OF,
    )

    with pytest.raises(research_automation.AutomationError) as error:
        runner.run(job="weekly", request_id=f"mode-{filename}", as_of=AS_OF)

    assert error.value.code == "automation_storage_insecure"
    assert services.calls == []


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow required")
@pytest.mark.parametrize("unsafe_kind", ["symlink", "mode"])
def test_existing_unsafe_run_state_fails_closed(tmp_path, unsafe_kind) -> None:
    automation = tmp_path / "automation"
    automation.mkdir(mode=0o700)
    state_directory = automation / "state"
    state_directory.mkdir(mode=0o700)
    services = FakeServices()
    runner = research_automation.ResearchAutomation(
        automation,
        services=services,
        now=lambda: AS_OF,
    )
    state_path = runner._state_path("unsafe-state")
    if unsafe_kind == "symlink":
        outside = tmp_path / "outside-state.json"
        outside.write_text("{}\n", encoding="utf-8")
        outside.chmod(0o600)
        state_path.symlink_to(outside)
    else:
        state_path.write_text("{}\n", encoding="utf-8")
        state_path.chmod(0o644)

    with pytest.raises(research_automation.AutomationError) as error:
        runner.run(job="weekly", request_id="unsafe-state", as_of=AS_OF)

    assert error.value.code == "automation_storage_insecure"
    assert services.calls == []


def test_lock_path_replacement_allows_only_the_stable_inode_runner(
    tmp_path,
    monkeypatch,
) -> None:
    automation = tmp_path / "automation"
    services = FakeServices()
    runner = research_automation.ResearchAutomation(
        automation,
        services=services,
        now=lambda: AS_OF,
    )
    lock_path = automation / ".run.lock"
    real_open = research_automation.os.open
    lock_opened = threading.Event()
    release = threading.Event()
    main_thread = threading.current_thread()

    def observed_open(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is None:
            fd = real_open(path, flags, mode)
        else:
            fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if (
            threading.current_thread() is not main_thread
            and os.fspath(path) == os.fspath(lock_path)
        ):
            lock_opened.set()
            release.wait(timeout=2)
        return fd

    monkeypatch.setattr(research_automation.os, "open", observed_open)
    with ThreadPoolExecutor(max_workers=1) as pool:
        displaced_runner = pool.submit(
            runner.run,
            job="weekly",
            request_id="stable-lock-inode",
            as_of=AS_OF,
        )
        assert lock_opened.wait(timeout=1)
        displaced_path = automation / ".run.lock.displaced"
        lock_path.rename(displaced_path)
        lock_path.write_bytes(b"")
        lock_path.chmod(0o600)

        winner = runner.run(
            job="weekly",
            request_id="stable-lock-inode",
            as_of=AS_OF,
        )
        release.set()

        with pytest.raises(research_automation.AutomationError) as error:
            displaced_runner.result(timeout=2)

    assert winner["status"] == "available"
    assert error.value.code == "automation_storage_insecure"
    assert services.calls.count("weekly_projection") == 1


def _receipt(job: str, completed_at: str, status: str = "available") -> dict:
    return {
        "schema_version": "1.0",
        "run_id": f"run:{job}:{completed_at}",
        "request_id": f"request:{job}:{completed_at}",
        "job": job,
        "as_of": completed_at,
        "started_at": completed_at,
        "completed_at": completed_at,
        "status": status,
        "replayed": False,
        "steps": [],
        "notifications": {
            "planned": 0,
            "delivered": 0,
            "queued": 0,
            "fallback_persisted": 0,
            "delivery_unknown": 0,
            "suppressed": 0,
        },
    }


def test_automation_status_is_per_job_and_schedule_aware_over_weekend() -> None:
    receipts = [
        _receipt("daily_close", "2026-07-11T00:15:00Z"),  # Saturday 08:15 CST
        _receipt("freshness", "2026-07-12T00:17:00Z"),
        _receipt("weekly", "2026-07-12T01:00:00Z"),
        _receipt("notification_drain", "2026-07-12T00:45:00Z"),
    ]

    artifact = research_automation.build_automation_status(
        as_of="2026-07-12T01:05:00Z",
        receipts=receipts,
    )

    assert artifact["kind"] == "automation_status"
    assert artifact["status"] == "available"
    data = artifact["data"]
    assert set(data) == {
        "checked_at",
        "overall_status",
        "jobs",
        "proposal_only",
        "trading_allowed",
    }
    assert data["overall_status"] == "fresh"
    assert len(data["jobs"]) == 4
    daily = next(row for row in data["jobs"] if row["job_id"] == "daily_close")
    weekly = next(row for row in data["jobs"] if row["job_id"] == "weekly")
    drain = next(
        row for row in data["jobs"] if row["job_id"] == "notification_drain"
    )
    assert daily["status"] == "fresh"
    assert daily["fresh_until"] == "2026-07-14T03:15:00Z"
    assert daily["expected_schedule"] == "15,25 8 * * 2-6"
    assert weekly["expected_schedule"] == "0,10 9 * * 0"
    assert drain["expected_schedule"] == "7,22,37,52 * * * *"
    assert daily["timezone"] == "Asia/Shanghai"


def test_automation_status_marks_failed_stale_and_never_run_honestly() -> None:
    failed = _receipt("freshness", "2026-07-12T00:30:00Z", "degraded")
    old = _receipt("daily_close", "2026-07-08T00:15:00Z")
    failed["notifications"]["delivery_unknown"] = 1

    artifact = research_automation.build_automation_status(
        as_of="2026-07-12T05:00:00Z",
        receipts=[old, failed],
    )

    jobs = {row["job_id"]: row for row in artifact["data"]["jobs"]}
    assert artifact["status"] == "degraded"
    assert artifact["data"]["overall_status"] == "degraded"
    assert jobs["daily_close"]["status"] == "stale"
    assert jobs["daily_close"]["reason_code"] == "freshness_budget_exceeded"
    assert jobs["freshness"]["status"] == "failed"
    assert jobs["freshness"]["notification_status"] == "delivery_unknown"
    assert jobs["weekly"]["status"] == "never_run"
    assert jobs["weekly"]["last_attempt_at"] is None
    assert jobs["notification_drain"]["status"] == "never_run"
