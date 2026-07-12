from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional


_SCHEMA_VERSION = "1.0"
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,159}")
_TARGET_RE = re.compile(r"discord:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_NOTIFICATION_ID_RE = re.compile(r"ntf_[0-9a-f]{24}")
_EVENT_ID_RE = re.compile(r"nev_[0-9a-f]{24}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_KNOWN_FAILURE_REASONS = {
    "remote_unavailable",
    "remote_rejected",
    "remote_rate_limited",
    "remote_transport_failed",
}
_UNKNOWN_REASONS = {
    "delivery_interrupted",
    "remote_timeout",
    "remote_delivery_ambiguous",
    "remote_result_unknown",
}
_LOCK_READY_MARKER = b"HQA_NOTIFICATION_OUTBOX_READY_V1\n"


class NotificationOutboxError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _corrupt(message: str) -> NotificationOutboxError:
    return NotificationOutboxError("notification_outbox_corrupt", message)


def _reject_json_constant(value: str) -> None:
    raise _corrupt(f"non-finite JSON number is not allowed: {value}")


def _object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _corrupt(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class NotificationSendResult:
    outcome: str
    reason_code: Optional[str] = None

    @classmethod
    def delivered(cls) -> "NotificationSendResult":
        return cls("delivered")

    @classmethod
    def known_failure(cls, reason_code: str) -> "NotificationSendResult":
        if reason_code not in _KNOWN_FAILURE_REASONS:
            raise ValueError("known failure reason_code is not supported")
        return cls("known_failure", reason_code)

    @classmethod
    def unknown(cls) -> "NotificationSendResult":
        return cls("delivery_unknown", "remote_result_unknown")

    def is_valid(self) -> bool:
        if self.outcome == "delivered":
            return self.reason_code is None
        if self.outcome == "known_failure":
            return self.reason_code in _KNOWN_FAILURE_REASONS
        if self.outcome == "delivery_unknown":
            return self.reason_code in {
                "remote_delivery_ambiguous",
                "remote_result_unknown",
            }
        return False


class NotificationOutbox:
    """Append-only source of notification intent and delivery truth."""

    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], str],
        remote_timeout_seconds: float = 15.0,
        max_attempts: int = 3,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._now = now
        if (
            isinstance(remote_timeout_seconds, bool)
            or not isinstance(remote_timeout_seconds, (int, float))
            or not math.isfinite(float(remote_timeout_seconds))
            or not 0 < float(remote_timeout_seconds) <= 15.0
        ):
            raise ValueError(
                "remote_timeout_seconds must be finite, positive, and at most 15"
            )
        self._remote_timeout_seconds = float(remote_timeout_seconds)
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= 10
        ):
            raise ValueError("max_attempts must be an integer from 1 to 10")
        self._max_attempts = max_attempts
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(float(lock_timeout_seconds))
            or not 0 < float(lock_timeout_seconds) <= 30.0
        ):
            raise ValueError(
                "lock_timeout_seconds must be finite, positive, and at most 30"
            )
        self._lock_timeout_seconds = float(lock_timeout_seconds)

    def enqueue(self, request: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_request(request)
        with self._locked(exclusive=True, create=True) as fd:
            assert fd is not None
            events = self._read_events(fd, allow_empty=True)
            receipts = self._fold(events)
            for receipt in receipts:
                if receipt["request_id"] != normalized["request_id"]:
                    continue
                if (
                    receipt["target"] == normalized["target"]
                    and receipt["message"] == normalized["message"]
                ):
                    return receipt
                raise NotificationOutboxError(
                    "notification_idempotency_conflict",
                    "request_id already belongs to a different notification intent",
                )

            notification_id = self._notification_id(normalized["request_id"])
            event = self._with_event_id(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "event": "notification_enqueued",
                    "notification_id": notification_id,
                    "request_id": normalized["request_id"],
                    "target": normalized["target"],
                    "message": normalized["message"],
                    "message_sha256": self._sha256_text(normalized["message"]),
                    "recorded_at": self._timestamp(self._now(), "recorded_at"),
                    "status": (
                        "delivered" if normalized["target"] == "local" else "pending"
                    ),
                }
            )
            self._append(fd, event)
            return self._fold(events + [event])[-1]

    def deliver(
        self,
        request: dict[str, Any],
        send_adapter: Optional[
            Callable[[str, str, float], NotificationSendResult]
        ] = None,
    ) -> dict[str, Any]:
        receipt = self.enqueue(request)
        if (
            receipt["status"] == "delivery_unknown"
            and receipt["reason_code"] == "delivery_interrupted"
        ):
            return self._wait_for_terminal(receipt["notification_id"])
        if receipt["status"] not in {"pending", "retryable"}:
            return receipt
        started = self._start_attempt(receipt["notification_id"])
        if started is None:
            current = next(
                item
                for item in self.list()
                if item["notification_id"] == receipt["notification_id"]
            )
            if (
                current["status"] == "delivery_unknown"
                and current["reason_code"] == "delivery_interrupted"
            ):
                return self._wait_for_terminal(receipt["notification_id"])
            return current
        if send_adapter is None:
            outcome = NotificationSendResult.known_failure("remote_unavailable")
        else:
            outcome = self._bounded_send(
                send_adapter,
                started["target"],
                started["message"],
            )
        return self._finish_attempt(
            receipt["notification_id"],
            started["attempt_count"],
            outcome,
        )

    def _wait_for_terminal(self, notification_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._remote_timeout_seconds
        while True:
            receipt = next(
                item
                for item in self.list()
                if item["notification_id"] == notification_id
            )
            if not (
                receipt["status"] == "delivery_unknown"
                and receipt["reason_code"] == "delivery_interrupted"
            ):
                return receipt
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return receipt
            time.sleep(min(0.01, remaining))

    def drain(
        self,
        send_adapter: Callable[[str, str, float], NotificationSendResult],
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise NotificationOutboxError(
                "notification_invalid_request", "limit must be an integer from 1 to 100"
            )
        candidates = [
            receipt["notification_id"]
            for receipt in self.list()
            if receipt["status"] in {"pending", "retryable"}
        ][:limit]
        results = []
        for notification_id in candidates:
            started = self._start_attempt(notification_id)
            if started is None:
                continue
            outcome = self._bounded_send(
                send_adapter,
                started["target"],
                started["message"],
            )
            results.append(
                self._finish_attempt(
                    notification_id,
                    started["attempt_count"],
                    outcome,
                )
            )
        folded = self.list()
        snapshot_counts = {
            status: sum(receipt["status"] == status for receipt in folded)
            for status in (
                "pending",
                "delivered",
                "retryable",
                "dead_letter",
                "delivery_unknown",
            )
        }
        if snapshot_counts["delivery_unknown"] or snapshot_counts["dead_letter"]:
            report_status = "degraded"
        elif snapshot_counts["retryable"]:
            report_status = "retryable"
        elif snapshot_counts["pending"]:
            report_status = "queued"
        else:
            report_status = "available"
        return {
            "schema_version": _SCHEMA_VERSION,
            "status": report_status,
            "processed_count": len(results),
            "queued_count": snapshot_counts["pending"],
            "delivered_count": snapshot_counts["delivered"],
            "retryable_count": snapshot_counts["retryable"],
            "dead_letter_count": snapshot_counts["dead_letter"],
            "delivery_unknown_count": snapshot_counts["delivery_unknown"],
            "results": results,
        }

    def list(self) -> list[dict[str, Any]]:
        with self._locked(exclusive=False, create=False) as fd:
            if fd is None:
                return []
            return self._fold(self._read_events(fd, allow_empty=False))

    def _start_attempt(self, notification_id: str) -> Optional[dict[str, Any]]:
        with self._locked(exclusive=True, create=False) as fd:
            if fd is None:
                return None
            events = self._read_events(fd, allow_empty=False)
            receipt = next(
                (
                    item
                    for item in self._fold(events)
                    if item["notification_id"] == notification_id
                ),
                None,
            )
            if receipt is None or receipt["status"] not in {"pending", "retryable"}:
                return None
            attempt_no = receipt["attempt_count"] + 1
            event = self._with_event_id(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "event": "delivery_attempt_started",
                    "notification_id": notification_id,
                    "request_id": receipt["request_id"],
                    "target": receipt["target"],
                    "message_sha256": receipt["message_sha256"],
                    "recorded_at": self._timestamp(self._now(), "recorded_at"),
                    "attempt_no": attempt_no,
                }
            )
            self._append(fd, event)
            return next(
                item
                for item in self._fold(events + [event])
                if item["notification_id"] == notification_id
            )

    def _finish_attempt(
        self,
        notification_id: str,
        attempt_no: int,
        outcome: NotificationSendResult,
    ) -> dict[str, Any]:
        with self._locked(exclusive=True, create=False) as fd:
            if fd is None:
                raise NotificationOutboxError(
                    "notification_outbox_corrupt", "notification outbox disappeared"
                )
            events = self._read_events(fd, allow_empty=False)
            receipt = next(
                item
                for item in self._fold(events)
                if item["notification_id"] == notification_id
            )
            status = outcome.outcome
            if status == "known_failure":
                status = (
                    "dead_letter" if attempt_no >= self._max_attempts else "retryable"
                )
            event = self._with_event_id(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "event": "delivery_outcome_recorded",
                    "notification_id": notification_id,
                    "request_id": receipt["request_id"],
                    "target": receipt["target"],
                    "message_sha256": receipt["message_sha256"],
                    "recorded_at": self._timestamp(self._now(), "recorded_at"),
                    "attempt_no": attempt_no,
                    "status": status,
                    "reason_code": outcome.reason_code,
                }
            )
            self._append(fd, event)
            return next(
                item
                for item in self._fold(events + [event])
                if item["notification_id"] == notification_id
            )

    def _bounded_send(
        self,
        send_adapter: Callable[[str, str, float], NotificationSendResult],
        target: str,
        message: str,
    ) -> NotificationSendResult:
        completed = threading.Event()
        result: list[NotificationSendResult] = []

        def invoke() -> None:
            try:
                value = send_adapter(target, message, self._remote_timeout_seconds)
                if isinstance(value, NotificationSendResult) and value.is_valid():
                    result.append(value)
                else:
                    result.append(NotificationSendResult.unknown())
            except BaseException:
                result.append(
                    NotificationSendResult(
                        "delivery_unknown", "remote_delivery_ambiguous"
                    )
                )
            finally:
                completed.set()

        worker = threading.Thread(target=invoke, daemon=True)
        try:
            worker.start()
            finished = completed.wait(self._remote_timeout_seconds)
        except BaseException:
            return NotificationSendResult("delivery_unknown", "delivery_interrupted")
        if not finished:
            return NotificationSendResult("delivery_unknown", "remote_timeout")
        return result[0]

    @staticmethod
    def _normalize_request(request: dict[str, Any]) -> dict[str, str]:
        if not isinstance(request, dict) or set(request) != {
            "request_id",
            "target",
            "message",
        }:
            raise NotificationOutboxError(
                "notification_invalid_request",
                "notification request fields are invalid",
            )
        if (
            not isinstance(request["request_id"], str)
            or _REQUEST_ID_RE.fullmatch(request["request_id"]) is None
        ):
            raise NotificationOutboxError(
                "notification_invalid_request", "request_id is invalid"
            )
        target = request["target"]
        if not isinstance(target, str) or not (
            target == "local" or _TARGET_RE.fullmatch(target) is not None
        ):
            raise NotificationOutboxError(
                "notification_invalid_request", "target is invalid"
            )
        if (
            not isinstance(request["message"], str)
            or not request["message"].strip()
            or len(request["message"]) > 16_384
        ):
            raise NotificationOutboxError(
                "notification_invalid_request", "message is required"
            )
        try:
            request["request_id"].encode("utf-8", errors="strict")
            target.encode("utf-8", errors="strict")
            request["message"].encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise NotificationOutboxError(
                "notification_invalid_request", "notification text is not valid UTF-8"
            ) from exc
        return {
            "request_id": request["request_id"],
            "target": target,
            "message": request["message"],
        }

    @staticmethod
    def _notification_id(request_id: str) -> str:
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        return f"ntf_{digest[:24]}"

    @staticmethod
    def _sha256_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _with_event_id(event: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            event,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            **event,
            "event_id": f"nev_{hashlib.sha256(body.encode()).hexdigest()[:24]}",
        }

    @staticmethod
    def _timestamp(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value:
            raise NotificationOutboxError(
                "notification_invalid_timestamp", f"{field} must be UTC"
            )
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise NotificationOutboxError(
                "notification_invalid_timestamp", f"{field} must be UTC"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise NotificationOutboxError(
                "notification_invalid_timestamp", f"{field} must be UTC"
            )
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _fold(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        receipts: dict[str, dict[str, Any]] = {}
        for event in events:
            notification_id = event["notification_id"]
            if event["event"] == "notification_enqueued":
                receipts[notification_id] = {
                    "schema_version": _SCHEMA_VERSION,
                    "notification_id": notification_id,
                    "request_id": event["request_id"],
                    "target": event["target"],
                    "message": event["message"],
                    "message_sha256": event["message_sha256"],
                    "requested_at": event["recorded_at"],
                    "last_attempt_at": None,
                    "completed_at": (
                        event["recorded_at"] if event["status"] == "delivered" else None
                    ),
                    "status": event["status"],
                    "attempt_count": 0,
                    "reason_code": None,
                }
                continue
            receipt = receipts[notification_id]
            if event["event"] == "delivery_attempt_started":
                receipt.update(
                    {
                        "last_attempt_at": event["recorded_at"],
                        "completed_at": event["recorded_at"],
                        "status": "delivery_unknown",
                        "attempt_count": event["attempt_no"],
                        "reason_code": "delivery_interrupted",
                    }
                )
            elif event["event"] == "delivery_outcome_recorded":
                receipt.update(
                    {
                        "completed_at": event["recorded_at"],
                        "status": event["status"],
                        "attempt_count": event["attempt_no"],
                        "reason_code": event["reason_code"],
                    }
                )
        return list(receipts.values())

    @classmethod
    def _validate_events(cls, events: list[dict[str, Any]]) -> None:
        states: dict[str, dict[str, Any]] = {}
        request_ids: set[str] = set()
        for line_number, event in enumerate(events, start=1):
            event_type = event.get("event")
            if event_type == "notification_enqueued":
                expected_fields = {
                    "schema_version",
                    "event",
                    "event_id",
                    "notification_id",
                    "request_id",
                    "target",
                    "message",
                    "message_sha256",
                    "recorded_at",
                    "status",
                }
            elif event_type == "delivery_attempt_started":
                expected_fields = {
                    "schema_version",
                    "event",
                    "event_id",
                    "notification_id",
                    "request_id",
                    "target",
                    "message_sha256",
                    "recorded_at",
                    "attempt_no",
                }
            elif event_type == "delivery_outcome_recorded":
                expected_fields = {
                    "schema_version",
                    "event",
                    "event_id",
                    "notification_id",
                    "request_id",
                    "target",
                    "message_sha256",
                    "recorded_at",
                    "attempt_no",
                    "status",
                    "reason_code",
                }
            else:
                raise _corrupt(
                    f"notification event line {line_number} has an unsupported type"
                )
            if set(event) != expected_fields:
                raise _corrupt(
                    f"notification event line {line_number} fields are invalid"
                )
            if event["schema_version"] != _SCHEMA_VERSION:
                raise _corrupt("notification event schema_version is unsupported")
            if (
                not isinstance(event["event_id"], str)
                or _EVENT_ID_RE.fullmatch(event["event_id"]) is None
            ):
                raise _corrupt("notification event_id is invalid")
            without_id = {
                key: value for key, value in event.items() if key != "event_id"
            }
            if cls._with_event_id(without_id)["event_id"] != event["event_id"]:
                raise _corrupt("notification event checksum does not match")
            notification_id = event["notification_id"]
            if (
                not isinstance(notification_id, str)
                or _NOTIFICATION_ID_RE.fullmatch(notification_id) is None
            ):
                raise _corrupt("notification_id is invalid")
            request_id = event["request_id"]
            target = event["target"]
            message_sha256 = event["message_sha256"]
            if (
                not isinstance(request_id, str)
                or _REQUEST_ID_RE.fullmatch(request_id) is None
                or notification_id != cls._notification_id(request_id)
            ):
                raise _corrupt("notification request identity is invalid")
            if not isinstance(target, str) or not (
                target == "local" or _TARGET_RE.fullmatch(target) is not None
            ):
                raise _corrupt("notification target is invalid")
            if (
                not isinstance(message_sha256, str)
                or _SHA256_RE.fullmatch(message_sha256) is None
            ):
                raise _corrupt("notification message checksum is invalid")

            if event_type == "notification_enqueued":
                message = event["message"]
                try:
                    cls._normalize_request(
                        {
                            "request_id": request_id,
                            "target": target,
                            "message": message,
                        }
                    )
                except NotificationOutboxError as exc:
                    raise _corrupt("stored notification intent is invalid") from exc
                if cls._sha256_text(message) != message_sha256:
                    raise _corrupt("notification message checksum does not match")
                expected_status = "delivered" if target == "local" else "pending"
                if event["status"] != expected_status:
                    raise _corrupt("notification initial status is invalid")
                if notification_id in states or request_id in request_ids:
                    raise _corrupt("notification intent is duplicated")
                request_ids.add(request_id)
                states[notification_id] = {
                    "request_id": request_id,
                    "target": target,
                    "message_sha256": message_sha256,
                    "status": expected_status,
                    "attempt_count": 0,
                    "open_attempt": None,
                    "last_recorded_at": event["recorded_at"],
                }
                continue

            state = states.get(notification_id)
            if state is None:
                raise _corrupt("notification delivery event has no intent")
            if (
                request_id != state["request_id"]
                or target != state["target"]
                or message_sha256 != state["message_sha256"]
            ):
                raise _corrupt("notification delivery intent changed")
            if event["recorded_at"] < state["last_recorded_at"]:
                raise _corrupt("notification event timestamps moved backwards")
            attempt_no = event["attempt_no"]
            if (
                isinstance(attempt_no, bool)
                or not isinstance(attempt_no, int)
                or not 1 <= attempt_no <= 10
            ):
                raise _corrupt("notification attempt_no is invalid")
            if event_type == "delivery_attempt_started":
                if state["status"] not in {"pending", "retryable"}:
                    raise _corrupt("notification attempt follows a terminal state")
                if attempt_no != state["attempt_count"] + 1:
                    raise _corrupt("notification attempts are not sequential")
                state.update(
                    {
                        "status": "delivery_unknown",
                        "attempt_count": attempt_no,
                        "open_attempt": attempt_no,
                        "last_recorded_at": event["recorded_at"],
                    }
                )
                continue

            if state["open_attempt"] != attempt_no:
                raise _corrupt("notification outcome has no matching attempt")
            status = event["status"]
            reason_code = event["reason_code"]
            if status == "delivered":
                valid_outcome = reason_code is None
            elif status in {"retryable", "dead_letter"}:
                valid_outcome = reason_code in _KNOWN_FAILURE_REASONS
            elif status == "delivery_unknown":
                valid_outcome = reason_code in _UNKNOWN_REASONS
            else:
                valid_outcome = False
            if not valid_outcome:
                raise _corrupt("notification delivery outcome is invalid")
            state.update(
                {
                    "status": status,
                    "open_attempt": None,
                    "last_recorded_at": event["recorded_at"],
                }
            )

    @contextmanager
    def _locked(self, *, exclusive: bool, create: bool) -> Iterator[Optional[int]]:
        path_exists = os.path.lexists(self.path)
        lock_exists = os.path.lexists(self.lock_path)
        if path_exists and not lock_exists:
            raise _corrupt("notification outbox exists without its stable lock")
        if not path_exists and not lock_exists and not create:
            yield None
            return
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if create or exclusive:
            lock_flags = os.O_RDWR
            if not path_exists and not lock_exists:
                lock_flags |= os.O_CREAT
        else:
            lock_flags = os.O_RDONLY
        lock_flags |= no_follow
        try:
            lock_fd = os.open(self.lock_path, lock_flags, 0o600)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise NotificationOutboxError(
                    "notification_outbox_insecure",
                    "notification lock must not be a symbolic link",
                ) from exc
            if exc.errno == errno.ENOENT:
                raise _corrupt("notification lock is missing") from exc
            raise NotificationOutboxError(
                "notification_outbox_io_error",
                "notification lock could not be opened",
                retryable=True,
            ) from exc
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fd: Optional[int] = None
        acquired = False
        try:
            self._assert_secure_fd(lock_fd, "notification lock")
            deadline = time.monotonic() + self._lock_timeout_seconds
            while True:
                try:
                    fcntl.flock(lock_fd, operation | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise NotificationOutboxError(
                            "notification_outbox_busy",
                            "notification outbox lock timed out",
                            retryable=True,
                        ) from exc
                    time.sleep(0.01)
            self._assert_path_identity(
                lock_fd,
                self.lock_path,
                "notification lock",
            )
            lock_ready = self._lock_is_ready(lock_fd)
            current_path_exists = os.path.lexists(self.path)
            if not current_path_exists:
                if lock_ready:
                    raise _corrupt(
                        "notification outbox is missing while its ready lock remains"
                    )
                if not create:
                    yield None
                    return
            if create:
                flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | no_follow
            elif exclusive:
                flags = os.O_RDWR | os.O_APPEND | no_follow
            else:
                flags = os.O_RDONLY | no_follow
            existed = self.path.exists()
            try:
                fd = os.open(self.path, flags, 0o600)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise NotificationOutboxError(
                        "notification_outbox_insecure",
                        "notification outbox must not be a symbolic link",
                    ) from exc
                if exc.errno == errno.ENOENT:
                    raise _corrupt("notification outbox disappeared") from exc
                raise NotificationOutboxError(
                    "notification_outbox_io_error",
                    "notification outbox could not be opened",
                    retryable=True,
                ) from exc
            self._assert_secure_fd(fd, "notification outbox")
            self._assert_path_identity(
                fd,
                self.path,
                "notification outbox",
            )
            if create and not existed:
                self._fsync_directory(self.path.parent)
            data_size = os.fstat(fd).st_size
            if lock_ready and data_size == 0:
                raise _corrupt("ready notification outbox is empty")
            if not lock_ready and data_size == 0 and not create:
                yield None
                return
            yield fd
            if (
                not lock_ready
                and (create or exclusive)
                and os.fstat(fd).st_size > 0
            ):
                self._mark_lock_ready(lock_fd)
        finally:
            if fd is not None:
                os.close(fd)
            try:
                if acquired:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    @staticmethod
    def _lock_is_ready(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, len(_LOCK_READY_MARKER) + 1)
        if raw == b"":
            return False
        if raw == _LOCK_READY_MARKER:
            return True
        raise _corrupt("notification lock state is invalid")

    @staticmethod
    def _mark_lock_ready(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        view = memoryview(_LOCK_READY_MARKER)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("notification lock write made no progress")
            view = view[written:]
        os.ftruncate(fd, len(_LOCK_READY_MARKER))
        os.fsync(fd)

    @staticmethod
    def _assert_secure_fd(fd: int, label: str) -> None:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
        ):
            raise NotificationOutboxError(
                "notification_outbox_insecure",
                f"{label} must be an owner-only regular file",
            )

    @staticmethod
    def _assert_path_identity(fd: int, path: Path, label: str) -> None:
        opened = os.fstat(fd)
        try:
            current = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise _corrupt(f"{label} path disappeared after open") from exc
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise _corrupt(f"{label} path identity changed after open")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _append(fd: int, event: dict[str, Any]) -> None:
        encoded = (
            json.dumps(
                event,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8", errors="strict")
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("notification outbox write made no progress")
            view = view[written:]
        os.fsync(fd)

    def _read_events(self, fd: int, *, allow_empty: bool) -> list[dict[str, Any]]:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks = []
        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        if not raw:
            if allow_empty:
                return []
            raise NotificationOutboxError(
                "notification_outbox_corrupt", "notification outbox is empty"
            )
        if not raw.endswith(b"\n"):
            raise NotificationOutboxError(
                "notification_outbox_corrupt", "notification outbox has a torn line"
            )
        try:
            text = raw.decode("utf-8", errors="strict")
            values = [
                json.loads(
                    line,
                    object_pairs_hook=_object_without_duplicate_keys,
                    parse_constant=_reject_json_constant,
                )
                for line in text[:-1].split("\n")
            ]
        except NotificationOutboxError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise NotificationOutboxError(
                "notification_outbox_corrupt", "notification outbox is invalid"
            ) from exc
        now_text = self._timestamp(self._now(), "now")
        now_value = datetime.fromisoformat(now_text[:-1] + "+00:00")
        for value in values:
            if not isinstance(value, dict):
                raise _corrupt("notification event must be a JSON object")
            recorded_at = value.get("recorded_at")
            try:
                normalized = self._timestamp(recorded_at, "recorded_at")
            except NotificationOutboxError as exc:
                raise _corrupt("notification recorded_at is invalid") from exc
            if normalized != recorded_at:
                raise _corrupt("notification recorded_at is not canonical UTC")
            stored_value = datetime.fromisoformat(normalized[:-1] + "+00:00")
            if stored_value > now_value:
                raise _corrupt("notification recorded_at is in the future")
        self._validate_events(values)
        return values
