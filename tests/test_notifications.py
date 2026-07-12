from __future__ import annotations

import fcntl
import json
import os
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from hqa import notifications as notifications_module
from hqa.notifications import (
    NotificationOutbox,
    NotificationOutboxError,
    NotificationSendResult,
)


NOW = "2026-07-12T04:00:00Z"


def test_local_notification_is_durable_and_idempotent(tmp_path):
    outbox_path = tmp_path / "notifications" / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    request = {
        "request_id": "weekly:2026-W28",
        "target": "local",
        "message": "Weekly research review is ready.",
    }

    first = outbox.enqueue(request)
    second = outbox.enqueue(request)

    assert first == second
    assert first["status"] == "delivered"
    assert first["attempt_count"] == 0
    assert first["notification_id"].startswith("ntf_")
    assert outbox.list() == [first]
    assert len(outbox_path.read_text(encoding="utf-8").splitlines()) == 1
    assert stat.S_IMODE(outbox_path.stat().st_mode) == 0o600
    event = json.loads(outbox_path.read_text(encoding="utf-8"))
    assert event["message"] == request["message"]


def test_remote_notification_is_pending_until_drain_delivers_it(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    request = {
        "request_id": "daily-close:2026-07-12",
        "target": "discord:research-alerts",
        "message": "Daily close artifacts are ready.",
    }
    calls = []

    pending = outbox.enqueue(request)

    assert pending["status"] == "pending"

    def send(target, message, timeout_seconds):
        calls.append((target, message, timeout_seconds))
        return NotificationSendResult.delivered()

    report = outbox.drain(send, limit=1)

    assert calls == [(request["target"], request["message"], 15.0)]
    assert report["processed_count"] == 1
    assert report["delivered_count"] == 1
    receipt = outbox.list()[0]
    assert receipt["status"] == "delivered"
    assert receipt["attempt_count"] == 1
    assert receipt["reason_code"] is None
    assert len(outbox_path.read_text(encoding="utf-8").splitlines()) == 3


def test_known_remote_failure_retries_only_until_dead_letter(tmp_path):
    outbox = NotificationOutbox(
        tmp_path / "outbox.jsonl",
        now=lambda: NOW,
        max_attempts=2,
    )
    outbox.enqueue(
        {
            "request_id": "risk:degraded:2026-07-12",
            "target": "discord:risk-alerts",
            "message": "Risk source is degraded; local fallback is available.",
        }
    )
    calls = []

    def unavailable(target, message, timeout_seconds):
        calls.append((target, message, timeout_seconds))
        return NotificationSendResult.known_failure("remote_unavailable")

    first = outbox.drain(unavailable, limit=1)
    second = outbox.drain(unavailable, limit=1)
    third = outbox.drain(unavailable, limit=1)

    assert first["retryable_count"] == 1
    assert first["results"][0]["reason_code"] == "remote_unavailable"
    assert first["status"] == "retryable"
    assert second["dead_letter_count"] == 1
    assert second["status"] == "degraded"
    assert second["results"][0]["attempt_count"] == 2
    assert third["processed_count"] == 0
    assert third["status"] == "degraded"
    assert len(calls) == 2


def test_remote_timeout_is_unknown_and_never_automatically_retried(tmp_path):
    outbox = NotificationOutbox(
        tmp_path / "outbox.jsonl",
        now=lambda: NOW,
        remote_timeout_seconds=0.03,
    )
    release = threading.Event()
    calls = []

    def slow_send(target, message, timeout_seconds):
        calls.append((target, message, timeout_seconds))
        release.wait(1)
        return NotificationSendResult.delivered()

    request = {
        "request_id": "freshness:degraded:abc123",
        "target": "discord:ops",
        "message": "Freshness monitor is degraded.",
    }
    started = time.monotonic()
    first = outbox.deliver(request, slow_send)
    elapsed = time.monotonic() - started
    release.set()
    second = outbox.deliver(request, slow_send)

    assert elapsed < 0.25
    assert first == second
    assert first["status"] == "delivery_unknown"
    assert first["reason_code"] == "remote_timeout"
    assert len(calls) == 1


def test_remote_exception_is_sanitized_as_unknown(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)

    def crashes(target, message, timeout_seconds):
        raise RuntimeError("Authorization: Bearer do-not-persist-this-token")

    receipt = outbox.deliver(
        {
            "request_id": "weekly:exception",
            "target": "discord:weekly",
            "message": "Weekly review is ready.",
        },
        crashes,
    )

    assert receipt["status"] == "delivery_unknown"
    assert receipt["reason_code"] == "remote_delivery_ambiguous"
    assert "do-not-persist" not in repr(receipt)
    assert "do-not-persist" not in outbox_path.read_text(encoding="utf-8")


def test_duplicate_json_key_fails_closed(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": "local:corrupt",
            "target": "local",
            "message": "Local durable notification.",
        }
    )
    raw = outbox_path.read_text(encoding="utf-8")
    outbox_path.write_text(
        raw.replace(
            '"status":"delivered"',
            '"status":"pending","status":"delivered"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(NotificationOutboxError) as error:
        outbox.list()

    assert error.value.code == "notification_outbox_corrupt"


def test_future_receipt_fails_closed(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    NotificationOutbox(outbox_path, now=lambda: NOW).enqueue(
        {
            "request_id": "local:future",
            "target": "local",
            "message": "Future receipts cannot be trusted.",
        }
    )
    reader = NotificationOutbox(
        outbox_path,
        now=lambda: "2026-07-12T03:59:59Z",
    )

    with pytest.raises(NotificationOutboxError) as error:
        reader.list()

    assert error.value.code == "notification_outbox_corrupt"


def test_unknown_stored_field_fails_closed(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": "local:unknown-field",
            "target": "local",
            "message": "Strict event schema.",
        }
    )
    event = json.loads(outbox_path.read_text(encoding="utf-8"))
    event["unexpected"] = "must not be ignored"
    outbox_path.write_text(
        json.dumps(event, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(NotificationOutboxError) as error:
        outbox.list()

    assert error.value.code == "notification_outbox_corrupt"


def test_invalid_adapter_result_becomes_unknown_without_corrupting_outbox(tmp_path):
    outbox = NotificationOutbox(tmp_path / "outbox.jsonl", now=lambda: NOW)

    receipt = outbox.deliver(
        {
            "request_id": "remote:invalid-result",
            "target": "discord:ops",
            "message": "Adapter results are strictly validated.",
        },
        lambda target, message, timeout: NotificationSendResult(
            "delivered", "contradictory_reason"
        ),
    )

    assert receipt["status"] == "delivery_unknown"
    assert receipt["reason_code"] == "remote_result_unknown"
    assert outbox.list() == [receipt]


def test_concurrent_duplicate_delivery_invokes_sender_once(tmp_path):
    outbox = NotificationOutbox(
        tmp_path / "outbox.jsonl",
        now=lambda: NOW,
        remote_timeout_seconds=0.5,
    )
    request = {
        "request_id": "weekly:concurrent",
        "target": "discord:weekly",
        "message": "One remote delivery for concurrent callers.",
    }
    send_started = threading.Event()
    release = threading.Event()
    calls = []

    def send(target, message, timeout_seconds):
        calls.append((target, message, timeout_seconds))
        send_started.set()
        release.wait(1)
        return NotificationSendResult.delivered()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(outbox.deliver, request, send)
        assert send_started.wait(0.5)
        second_future = pool.submit(outbox.deliver, request, send)
        time.sleep(0.03)
        release.set()
        first = first_future.result(timeout=1)
        second = second_future.result(timeout=1)

    assert len(calls) == 1
    assert first == second
    assert first["status"] == "delivered"
    assert outbox.list() == [first]


def test_insecure_outbox_permissions_fail_closed(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": "local:permissions",
            "target": "local",
            "message": "This fallback must remain private.",
        }
    )
    outbox_path.chmod(0o644)

    with pytest.raises(NotificationOutboxError) as error:
        outbox.list()

    assert error.value.code == "notification_outbox_insecure"


def test_remote_timeout_must_be_finite_and_positive(tmp_path):
    with pytest.raises(ValueError, match="remote_timeout_seconds"):
        NotificationOutbox(
            tmp_path / "outbox.jsonl",
            now=lambda: NOW,
            remote_timeout_seconds=0,
        )


def test_cross_process_lock_wait_is_bounded(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    writer = NotificationOutbox(outbox_path, now=lambda: NOW)
    writer.enqueue(
        {
            "request_id": "local:lock",
            "target": "local",
            "message": "The lock wait is bounded.",
        }
    )
    lock_fd = (tmp_path / ".outbox.jsonl.lock").open("r+")
    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
    reader = NotificationOutbox(
        outbox_path,
        now=lambda: NOW,
        lock_timeout_seconds=0.03,
    )

    try:
        with pytest.raises(NotificationOutboxError) as error:
            reader.list()
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()

    assert error.value.code == "notification_outbox_busy"
    assert error.value.retryable is True


@pytest.mark.parametrize(
    "changed",
    [
        {"target": "discord:ops", "message": "Original intent."},
        {"target": "local", "message": "Changed intent."},
    ],
)
def test_request_id_reuse_with_changed_intent_fails_closed(tmp_path, changed):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": "immutable:intent",
            "target": "local",
            "message": "Original intent.",
        }
    )

    with pytest.raises(NotificationOutboxError) as error:
        outbox.enqueue({"request_id": "immutable:intent", **changed})

    assert error.value.code == "notification_idempotency_conflict"
    assert len(outbox_path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize("corruption", ["torn", "nonfinite"])
def test_torn_or_nonfinite_outbox_fails_closed(tmp_path, corruption):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": f"local:{corruption}",
            "target": "local",
            "message": "Strict finite JSONL.",
        }
    )
    raw = outbox_path.read_text(encoding="utf-8")
    if corruption == "torn":
        outbox_path.write_text(raw.rstrip("\n"), encoding="utf-8")
    else:
        outbox_path.write_text(
            raw.replace('"status":"delivered"', '"poison":NaN,"status":"delivered"'),
            encoding="utf-8",
        )

    with pytest.raises(NotificationOutboxError) as error:
        outbox.list()

    assert error.value.code == "notification_outbox_corrupt"


def test_request_cannot_smuggle_a_secret_field_into_the_outbox(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)

    with pytest.raises(NotificationOutboxError) as error:
        outbox.enqueue(
            {
                "request_id": "remote:secret",
                "target": "discord:ops",
                "message": "No credentials belong in notification intent.",
                "token": "do-not-persist",
            }
        )

    assert error.value.code == "notification_invalid_request"
    assert not outbox_path.exists()


def test_missing_ledger_with_existing_lock_fails_closed(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": "local:disappeared",
            "target": "local",
            "message": "A disappeared durable receipt must be visible.",
        }
    )
    outbox_path.unlink()

    with pytest.raises(NotificationOutboxError) as error:
        outbox.list()

    assert error.value.code == "notification_outbox_corrupt"


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow required")
def test_outbox_and_lock_symlinks_fail_closed(tmp_path):
    real_path = tmp_path / "real.jsonl"
    writer = NotificationOutbox(real_path, now=lambda: NOW)
    writer.enqueue(
        {
            "request_id": "local:real",
            "target": "local",
            "message": "Symlinks are not trusted outbox files.",
        }
    )
    alias_path = tmp_path / "alias.jsonl"
    alias_path.symlink_to(real_path)
    alias_lock = tmp_path / ".alias.jsonl.lock"
    alias_lock.symlink_to(tmp_path / ".real.jsonl.lock")

    with pytest.raises(NotificationOutboxError) as error:
        NotificationOutbox(alias_path, now=lambda: NOW).list()

    assert error.value.code == "notification_outbox_insecure"


def test_existing_ledger_with_missing_lock_is_not_silently_repaired(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    request = {
        "request_id": "local:lost-lock",
        "target": "local",
        "message": "The stable lock is part of durable state.",
    }
    outbox.enqueue(request)
    (tmp_path / ".outbox.jsonl.lock").unlink()

    with pytest.raises(NotificationOutboxError) as error:
        outbox.enqueue(request)

    assert error.value.code == "notification_outbox_corrupt"
    assert not (tmp_path / ".outbox.jsonl.lock").exists()


@pytest.mark.parametrize("empty_data_created", [False, True])
def test_orphaned_first_initialization_lock_can_recover(
    tmp_path,
    empty_data_created,
):
    outbox_path = tmp_path / "outbox.jsonl"
    lock_path = tmp_path / ".outbox.jsonl.lock"
    lock_path.touch(mode=0o600)
    if empty_data_created:
        outbox_path.touch(mode=0o600)
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)

    assert outbox.list() == []
    assert outbox_path.exists() is empty_data_created

    receipt = outbox.enqueue(
        {
            "request_id": "local:recover-initialization",
            "target": "local",
            "message": "Recover the interrupted first initialization.",
        }
    )

    assert receipt["status"] == "delivered"
    assert outbox.list() == [receipt]


def test_drain_reports_delivery_unknown_as_degraded(tmp_path):
    outbox = NotificationOutbox(tmp_path / "outbox.jsonl", now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": "remote:unknown-report",
            "target": "discord:ops",
            "message": "Unknown delivery must degrade the drain report.",
        }
    )

    report = outbox.drain(
        lambda target, message, timeout: NotificationSendResult.unknown(),
        limit=1,
    )

    assert report["status"] == "degraded"
    assert report["delivery_unknown_count"] == 1


def test_drain_reports_known_failure_as_retryable(tmp_path):
    outbox = NotificationOutbox(
        tmp_path / "outbox.jsonl",
        now=lambda: NOW,
        max_attempts=2,
    )
    outbox.enqueue(
        {
            "request_id": "remote:retryable-report",
            "target": "discord:ops",
            "message": "Known failure remains queued for a bounded retry.",
        }
    )

    report = outbox.drain(
        lambda target, message, timeout: NotificationSendResult.known_failure(
            "remote_unavailable"
        ),
        limit=1,
    )

    assert report["status"] == "retryable"
    assert report["retryable_count"] == 1


def test_drain_reports_unprocessed_pending_notifications_as_queued(tmp_path):
    outbox = NotificationOutbox(tmp_path / "outbox.jsonl", now=lambda: NOW)
    for index in range(2):
        outbox.enqueue(
            {
                "request_id": f"remote:queued-report:{index}",
                "target": "discord:ops",
                "message": f"Queued notification {index}.",
            }
        )

    report = outbox.drain(
        lambda target, message, timeout: NotificationSendResult.delivered(),
        limit=1,
    )

    assert report["processed_count"] == 1
    assert report["delivered_count"] == 1
    assert report["status"] == "queued"
    assert report["queued_count"] == 1


def test_ready_lock_with_truncated_ledger_fails_closed_on_enqueue(tmp_path):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": "local:before-truncation",
            "target": "local",
            "message": "This receipt establishes a ready outbox.",
        }
    )
    outbox_path.write_bytes(b"")

    with pytest.raises(NotificationOutboxError) as error:
        outbox.enqueue(
            {
                "request_id": "local:must-not-rebuild",
                "target": "local",
                "message": "Do not rebuild a truncated ready ledger.",
            }
        )

    assert error.value.code == "notification_outbox_corrupt"
    assert outbox_path.read_bytes() == b""


def test_drain_status_counts_describe_the_full_folded_snapshot(tmp_path):
    outbox = NotificationOutbox(tmp_path / "outbox.jsonl", now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": "remote:terminal-unknown",
            "target": "discord:ops",
            "message": "Keep this unknown terminal state visible.",
        }
    )
    outbox.drain(
        lambda target, message, timeout: NotificationSendResult.unknown(),
        limit=1,
    )
    outbox.enqueue(
        {
            "request_id": "remote:later-success",
            "target": "discord:ops",
            "message": "This later delivery succeeds.",
        }
    )

    report = outbox.drain(
        lambda target, message, timeout: NotificationSendResult.delivered(),
        limit=1,
    )

    assert report["processed_count"] == 1
    assert report["status"] == "degraded"
    assert report["delivered_count"] == 1
    assert report["delivery_unknown_count"] == 1
    assert report["dead_letter_count"] == 0
    assert report["retryable_count"] == 0
    assert report["queued_count"] == 0


def test_lock_path_replacement_while_waiting_fails_closed(tmp_path, monkeypatch):
    outbox_path = tmp_path / "outbox.jsonl"
    lock_path = tmp_path / ".outbox.jsonl.lock"
    outbox = NotificationOutbox(
        outbox_path,
        now=lambda: NOW,
        lock_timeout_seconds=1,
    )
    outbox.enqueue(
        {
            "request_id": "local:lock-replacement",
            "target": "local",
            "message": "The stable lock inode must remain stable.",
        }
    )
    holder_fd = os.open(lock_path, os.O_RDWR)
    real_flock = fcntl.flock
    real_flock(holder_fd, fcntl.LOCK_EX)
    attempted = threading.Event()

    def observed_flock(fd, operation):
        if operation & fcntl.LOCK_NB:
            attempted.set()
        return real_flock(fd, operation)

    monkeypatch.setattr(notifications_module.fcntl, "flock", observed_flock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(outbox.list)
        try:
            assert attempted.wait(0.5)
            displaced = tmp_path / ".outbox.jsonl.lock.displaced"
            lock_path.rename(displaced)
            lock_path.write_bytes(displaced.read_bytes())
            lock_path.chmod(0o600)
        finally:
            real_flock(holder_fd, fcntl.LOCK_UN)
            os.close(holder_fd)

        with pytest.raises(NotificationOutboxError) as error:
            future.result(timeout=1)

    assert error.value.code == "notification_outbox_corrupt"


def test_data_path_replacement_after_open_fails_closed(tmp_path, monkeypatch):
    outbox_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(outbox_path, now=lambda: NOW)
    outbox.enqueue(
        {
            "request_id": "local:data-replacement",
            "target": "local",
            "message": "The ledger inode must remain stable after open.",
        }
    )
    original = outbox_path.read_bytes()
    real_open = os.open
    data_opened = threading.Event()
    release = threading.Event()
    main_thread = threading.current_thread()

    def observed_open(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is None:
            fd = real_open(path, flags, mode)
        else:
            fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if (
            threading.current_thread() is not main_thread
            and os.fspath(path) == os.fspath(outbox_path)
        ):
            data_opened.set()
            release.wait(1)
        return fd

    monkeypatch.setattr(notifications_module.os, "open", observed_open)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(outbox.list)
        assert data_opened.wait(0.5)
        displaced = tmp_path / "outbox.jsonl.displaced"
        outbox_path.rename(displaced)
        outbox_path.write_bytes(original)
        outbox_path.chmod(0o600)
        release.set()

        with pytest.raises(NotificationOutboxError) as error:
            future.result(timeout=1)

    assert error.value.code == "notification_outbox_corrupt"
