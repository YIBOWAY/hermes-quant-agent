from __future__ import annotations

import copy
import errno
import fcntl
import json
import math
import os
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterator, Optional


_SCHEMA_VERSION = "1.0"


class OpportunityLedgerError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _invalid(message: str) -> OpportunityLedgerError:
    return OpportunityLedgerError("opportunity_invalid_request", message)


def _corrupt(message: str) -> OpportunityLedgerError:
    return OpportunityLedgerError("opportunity_ledger_corrupt", message)


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


def _validate_json_tree(root: Any, *, max_depth: int = 100) -> None:
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > max_depth:
            raise _corrupt("opportunity event nesting exceeds supported depth")
        if isinstance(value, str):
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise _corrupt("opportunity event contains invalid unicode") from exc
        elif isinstance(value, float) and not math.isfinite(value):
            raise _corrupt("opportunity event contains a non-finite number")
        elif isinstance(value, dict):
            for key, item in value.items():
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
        elif isinstance(value, list):
            for item in value:
                stack.append((item, depth + 1))


def _canonical_json(value: Any) -> str:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        serialized.encode("utf-8", errors="strict")
        return serialized
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise _invalid("opportunity payload must be strict finite JSON") from exc


def _sha256(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_timestamp(value: Any, field: str, *, stored: bool = False) -> str:
    error = _corrupt if stored else _invalid
    if not isinstance(value, str) or not value:
        raise error(f"{field} must be a timezone-aware timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise error(f"{field} must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise error(f"{field} must be a timezone-aware timestamp")
    try:
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError) as exc:
        raise error(f"{field} falls outside the supported timestamp range") from exc


def _strict_date(value: Any, field: str, *, stored: bool = False) -> str:
    error = _corrupt if stored else _invalid
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise error(f"{field} must use strict YYYY-MM-DD")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise error(f"{field} must use strict YYYY-MM-DD") from exc


def _command_intent_sha256(event_type: str, payload: dict[str, Any]) -> str:
    intent = dict(payload)
    if event_type == "signal_observed":
        intent.pop("observed_at", None)
    return _sha256(intent)


def _validate_cursor(cursor: Optional[str]) -> None:
    if cursor is not None and (
        not isinstance(cursor, str) or re.fullmatch(r"sig_[0-9a-f]{24}", cursor) is None
    ):
        raise _invalid("cursor must be a canonical signal_id")


class OpportunityTracker:
    def __init__(
        self,
        opportunity_dir: Path,
        *,
        now: Callable[[], str],
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self.opportunity_dir = Path(opportunity_dir)
        self.entries_path = self.opportunity_dir / "entries.jsonl"
        self.lock_path = self.opportunity_dir / ".ledger.lock"
        self._now = now
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(float(lock_timeout_seconds))
            or float(lock_timeout_seconds) <= 0
        ):
            raise ValueError("lock_timeout_seconds must be finite and positive")
        self._lock_timeout_seconds = float(lock_timeout_seconds)

    def record(self, command: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(command, dict) or set(command) != {
            "event",
            "request_id",
            "payload",
        }:
            raise _invalid("opportunity command fields are invalid")
        event_type = command["event"]
        if event_type == "missed_assessed":
            raise _invalid("missed assessments may only be generated by reconcile_due")
        if event_type not in {
            "signal_observed",
            "decision_recorded",
            "action_observed",
            "action_coverage_observed",
        }:
            raise _invalid("unsupported opportunity event")
        request_id = command["request_id"]
        if not isinstance(request_id, str) or not request_id:
            raise _invalid("request_id is required")
        payload = self._normalize_payload(
            event_type,
            command["payload"],
            request_id=request_id,
        )
        self._validate_payload_schema(event_type, payload, stored=False)
        payload_sha256 = _sha256(payload)
        intent_sha256 = _command_intent_sha256(event_type, payload)
        try:
            with self._locked(exclusive=True, create=True) as fd:
                assert fd is not None
                events = self._read_events_fd(fd, allow_empty=True)
                for event in events:
                    if event["request_id"] != request_id:
                        continue
                    if (
                        event["event"] == event_type
                        and _command_intent_sha256(event["event"], event["payload"])
                        == intent_sha256
                    ):
                        return self._reduce(events)[payload["signal_id"]]
                    raise OpportunityLedgerError(
                        "opportunity_idempotency_conflict",
                        "request_id already belongs to a different opportunity intent",
                    )
                states = self._reduce(events)
                if (
                    event_type != "signal_observed"
                    and payload["signal_id"] not in states
                ):
                    raise _invalid("opportunity event references an unknown signal_id")
                if event_type != "signal_observed":
                    self._validate_causal_lower_bound(
                        states[payload["signal_id"]],
                        event_type,
                        payload,
                        stored=False,
                    )
                event = {
                    "schema_version": _SCHEMA_VERSION,
                    "event": event_type,
                    "event_id": (
                        f"oev_{_sha256([event_type, request_id, payload_sha256])[:24]}"
                    ),
                    "request_id": request_id,
                    "recorded_at": _utc_timestamp(self._now(), "event.recorded_at"),
                    "payload_sha256": payload_sha256,
                    "payload": payload,
                }
                try:
                    _validate_json_tree(event)
                except OpportunityLedgerError as exc:
                    raise _invalid(
                        "opportunity event must be valid UTF-8 finite JSON"
                    ) from exc
                next_states = self._reduce([*events, event])
                self._append_event(fd, event)
                return next_states[payload["signal_id"]]
        except OpportunityLedgerError:
            raise
        except OSError as exc:
            raise OpportunityLedgerError(
                "opportunity_ledger_io_error",
                f"opportunity ledger write failed: {type(exc).__name__}",
                retryable=True,
            ) from exc

    @staticmethod
    def _normalize_payload(
        event_type: str,
        raw_payload: Any,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        if not isinstance(raw_payload, dict):
            raise _invalid("opportunity event payload must be an object")
        payload = copy.deepcopy(raw_payload)
        signal_id = payload.get("signal_id")
        if not isinstance(signal_id, str) or not signal_id:
            raise _invalid(f"{event_type} requires signal_id")
        if event_type == "signal_observed":
            payload["observed_at"] = _utc_timestamp(
                payload.get("observed_at"), "signal.observed_at"
            )
            source = payload.get("source")
            if isinstance(source, dict):
                source["date"] = _strict_date(source.get("date"), "signal.source.date")
            eligibility = payload.get("eligibility")
            if (
                isinstance(eligibility, dict)
                and eligibility.get("deadline_at") is not None
            ):
                eligibility["deadline_at"] = _utc_timestamp(
                    eligibility["deadline_at"], "signal.eligibility.deadline_at"
                )
            return payload
        if event_type == "decision_recorded":
            required = {
                "signal_id",
                "decision",
                "actor",
                "reason",
                "decided_at",
                "revisit_at",
            }
            if set(payload) != required:
                raise _invalid("decision_recorded fields are invalid")
            if payload["decision"] not in {"act", "decline", "defer"}:
                raise _invalid("decision must be act, decline, or defer")
            if not all(
                isinstance(payload[field], str) and payload[field].strip()
                for field in ("actor", "reason")
            ):
                raise _invalid("decision actor and reason are required")
            payload["decided_at"] = _utc_timestamp(
                payload["decided_at"], "decision.decided_at"
            )
            if payload["revisit_at"] is not None:
                payload["revisit_at"] = _utc_timestamp(
                    payload["revisit_at"], "decision.revisit_at"
                )
            if payload["decision"] != "defer" and payload["revisit_at"] is not None:
                raise _invalid("only a deferred decision may set revisit_at")
            if (
                payload["revisit_at"] is not None
                and payload["revisit_at"] < payload["decided_at"]
            ):
                raise _invalid("decision revisit_at cannot precede decided_at")
            payload["decision_id"] = (
                f"dec_{_sha256([signal_id, request_id, payload])[:24]}"
            )
            return payload
        if event_type == "action_observed":
            required = {
                "signal_id",
                "platform_signal_id",
                "platform_execution_id",
                "status",
                "actor",
                "occurred_at",
                "updated_at",
            }
            if set(payload) != required:
                raise _invalid("action_observed fields are invalid")
            if payload["status"] not in {
                "pending",
                "partially_filled",
                "filled",
                "blocked",
                "failed",
                "cancelled",
                "missed_window",
                "skipped",
            }:
                raise _invalid("action status is invalid")
            payload["occurred_at"] = _utc_timestamp(
                payload["occurred_at"], "action.occurred_at"
            )
            payload["updated_at"] = _utc_timestamp(
                payload["updated_at"], "action.updated_at"
            )
            if payload["updated_at"] < payload["occurred_at"]:
                raise _invalid("action updated_at cannot precede occurred_at")
            if not all(
                isinstance(payload[field], str) and payload[field].strip()
                for field in (
                    "platform_signal_id",
                    "platform_execution_id",
                    "actor",
                )
            ):
                raise _invalid("action platform identities and actor are required")
            external_id = payload["platform_execution_id"]
            if not isinstance(external_id, str) or not external_id:
                external_id = payload["platform_signal_id"]
            if not isinstance(external_id, str) or not external_id:
                raise _invalid("action requires a durable platform identity")
            payload["action_id"] = f"act_{_sha256(['platform', external_id])[:24]}"
            return payload
        if event_type == "action_coverage_observed":
            required = {
                "signal_id",
                "source",
                "snapshot_id",
                "observed_at",
                "covered_through",
                "complete",
                "truncated",
            }
            if set(payload) != required:
                raise _invalid("action_coverage_observed fields are invalid")
            if not isinstance(payload["complete"], bool) or not isinstance(
                payload["truncated"], bool
            ):
                raise _invalid("coverage flags must be booleans")
            if not all(
                isinstance(payload[field], str) and payload[field].strip()
                for field in ("source", "snapshot_id")
            ):
                raise _invalid("coverage source and snapshot_id are required")
            payload["observed_at"] = _utc_timestamp(
                payload["observed_at"], "coverage.observed_at"
            )
            payload["covered_through"] = _utc_timestamp(
                payload["covered_through"], "coverage.covered_through"
            )
            if payload["covered_through"] > payload["observed_at"]:
                raise _invalid("coverage cannot extend beyond its observation time")
            return payload
        if event_type == "missed_assessed":
            required = {
                "signal_id",
                "assessed_at",
                "deadline_at",
                "reason_code",
                "coverage_event_id",
            }
            if set(payload) != required:
                raise _invalid("missed_assessed fields are invalid")
            if payload["reason_code"] not in {
                "no_decision",
                "act_without_action",
                "defer_expired",
            }:
                raise _invalid("missed assessment reason is invalid")
            payload["assessed_at"] = _utc_timestamp(
                payload["assessed_at"], "missed.assessed_at"
            )
            payload["deadline_at"] = _utc_timestamp(
                payload["deadline_at"], "missed.deadline_at"
            )
            return payload
        return payload

    def list(
        self,
        *,
        status: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 200
        ):
            raise _invalid("limit must be an integer in [1, 200]")
        allowed_statuses = {
            "open",
            "deferred",
            "acted",
            "action_failed",
            "declined",
            "missed",
            "not_actionable",
            "unknown",
            "expired_coverage_unknown",
        }
        if status is not None and status not in allowed_statuses:
            raise _invalid("status filter is invalid")
        since_value = _utc_timestamp(since, "list.since") if since is not None else None
        _validate_cursor(cursor)
        as_of = _utc_timestamp(self._now(), "list.as_of")
        states = sorted(
            self._load_states().values(),
            key=lambda state: state["signal_id"],
        )
        self._project_expired_coverage(states, as_of=as_of)
        if since_value is not None:
            states = [
                state
                for state in states
                if state["signal"]["observed_at"] >= since_value
            ]
        if cursor is not None:
            states = [state for state in states if state["signal_id"] > cursor]
        if status is not None:
            states = [state for state in states if state["resolution"] == status]
        return states[:limit]

    @staticmethod
    def _project_expired_coverage(
        states: list[dict[str, Any]],
        *,
        as_of: str,
    ) -> None:
        for state in states:
            if state["resolution"] in {
                "acted",
                "action_failed",
                "declined",
                "missed",
                "not_actionable",
                "unknown",
            }:
                continue
            eligibility = state["signal"]["eligibility"]
            deadline = eligibility.get("deadline_at")
            coverage = state["coverage"]
            if (
                eligibility.get("status") == "eligible"
                and isinstance(deadline, str)
                and as_of > deadline
                and (
                    coverage is None
                    or not coverage["complete"]
                    or coverage["truncated"]
                    or coverage["covered_through"] < deadline
                )
            ):
                state["resolution"] = "expired_coverage_unknown"

    def reconcile_due(
        self,
        *,
        as_of: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 50
        ):
            raise _invalid("limit must be an integer in [1, 50]")
        _validate_cursor(cursor)
        as_of_value = _utc_timestamp(as_of or self._now(), "reconcile.as_of")
        try:
            with self._locked(exclusive=True, create=False) as fd:
                if fd is None:
                    return self._reconcile_result(as_of_value, [], 0, None)
                events = self._read_events_fd(fd, allow_empty=False)
                states = sorted(
                    self._reduce(events).values(),
                    key=lambda state: state["signal_id"],
                )
                self._project_expired_coverage(states, as_of=as_of_value)
                due = [
                    state
                    for state in states
                    if state["signal"]["eligibility"].get("status") == "eligible"
                    and isinstance(
                        state["signal"]["eligibility"].get("deadline_at"), str
                    )
                    and as_of_value > state["signal"]["eligibility"]["deadline_at"]
                    and (cursor is None or state["signal_id"] > cursor)
                ]
                selected = due[:limit]
                results: list[dict[str, Any]] = []
                missed_count = 0
                for state in selected:
                    if state["missed_assessment"] is not None:
                        results.append(
                            {
                                "signal_id": state["signal_id"],
                                "status": "already_assessed",
                            }
                        )
                        continue
                    action_resolution = self._timely_action_resolution(state)
                    if action_resolution is not None:
                        results.append(
                            {
                                "signal_id": state["signal_id"],
                                "status": action_resolution,
                            }
                        )
                        continue
                    if state["resolution"] in {"acted", "action_failed", "declined"}:
                        results.append(
                            {
                                "signal_id": state["signal_id"],
                                "status": state["resolution"],
                            }
                        )
                        continue
                    deadline = state["signal"]["eligibility"]["deadline_at"]
                    coverage = state["coverage"]
                    if (
                        coverage is None
                        or not coverage["complete"]
                        or coverage["truncated"]
                        or coverage["covered_through"] < deadline
                    ):
                        results.append(
                            {
                                "signal_id": state["signal_id"],
                                "status": "expired_coverage_unknown",
                            }
                        )
                        continue
                    decision = state["decision"]
                    reason_code = "no_decision"
                    if (
                        decision is not None
                        and decision["decided_at"] <= deadline
                        and decision["decision"] == "act"
                    ):
                        reason_code = "act_without_action"
                    elif (
                        decision is not None
                        and decision["decided_at"] <= deadline
                        and decision["decision"] == "defer"
                    ):
                        reason_code = "defer_expired"
                    request_id = f"reconcile:{state['signal_id']}:{deadline}"
                    payload = self._normalize_payload(
                        "missed_assessed",
                        {
                            "signal_id": state["signal_id"],
                            "assessed_at": as_of_value,
                            "deadline_at": deadline,
                            "reason_code": reason_code,
                            "coverage_event_id": coverage["coverage_event_id"],
                        },
                        request_id=request_id,
                    )
                    self._validate_payload_schema(
                        "missed_assessed", payload, stored=False
                    )
                    payload_sha256 = _sha256(payload)
                    event = {
                        "schema_version": _SCHEMA_VERSION,
                        "event": "missed_assessed",
                        "event_id": (
                            "oev_"
                            + _sha256(["missed_assessed", request_id, payload_sha256])[
                                :24
                            ]
                        ),
                        "request_id": request_id,
                        "recorded_at": _utc_timestamp(self._now(), "event.recorded_at"),
                        "payload_sha256": payload_sha256,
                        "payload": payload,
                    }
                    self._reduce([*events, event])
                    self._append_event(fd, event)
                    events.append(event)
                    missed_count += 1
                    results.append(
                        {
                            "signal_id": state["signal_id"],
                            "status": "missed",
                            "reason_code": reason_code,
                        }
                    )
                next_cursor = None
                if len(due) > len(selected) and selected:
                    next_cursor = selected[-1]["signal_id"]
                return self._reconcile_result(
                    as_of_value,
                    results,
                    missed_count,
                    next_cursor,
                )
        except OpportunityLedgerError:
            raise
        except OSError as exc:
            raise OpportunityLedgerError(
                "opportunity_ledger_io_error",
                f"opportunity ledger reconcile failed: {type(exc).__name__}",
                retryable=True,
            ) from exc

    @staticmethod
    def _reconcile_result(
        as_of: str,
        results: list[dict[str, Any]],
        missed_count: int,
        next_cursor: Optional[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "status": "available",
            "as_of": as_of,
            "processed_count": len(results),
            "missed_count": missed_count,
            "next_cursor": next_cursor,
            "results": results,
        }

    def _load_states(self) -> dict[str, dict[str, Any]]:
        try:
            with self._locked(exclusive=False, create=False) as fd:
                if fd is None:
                    return {}
                return self._reduce(self._read_events_fd(fd, allow_empty=False))
        except OpportunityLedgerError:
            raise
        except OSError as exc:
            raise OpportunityLedgerError(
                "opportunity_ledger_io_error",
                f"opportunity ledger read failed: {type(exc).__name__}",
                retryable=True,
            ) from exc

    @contextmanager
    def _locked(
        self,
        *,
        exclusive: bool,
        create: bool,
    ) -> Iterator[Optional[int]]:
        if not create and not self.entries_path.exists():
            yield None
            return
        if create:
            directory_existed = self.opportunity_dir.exists()
            self.opportunity_dir.mkdir(parents=True, exist_ok=True)
            if not directory_existed:
                self._fsync_directory(self.opportunity_dir.parent)
            lock_existed = self.lock_path.exists()
            lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            if not lock_existed:
                self._fsync_directory(self.opportunity_dir)
        else:
            try:
                lock_fd = os.open(self.lock_path, os.O_RDONLY)
            except FileNotFoundError as exc:
                raise _corrupt("opportunity ledger lock file is missing") from exc
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + self._lock_timeout_seconds
        fd: Optional[int] = None
        try:
            while True:
                try:
                    fcntl.flock(lock_fd, operation | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise OpportunityLedgerError(
                            "opportunity_ledger_busy",
                            "opportunity ledger lock timed out",
                            retryable=True,
                        ) from exc
                    time.sleep(0.01)
            if create:
                flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
            elif exclusive:
                flags = os.O_RDWR | os.O_APPEND
            else:
                flags = os.O_RDONLY
            entries_existed = self.entries_path.exists()
            try:
                fd = os.open(self.entries_path, flags, 0o600)
            except FileNotFoundError:
                yield None
                return
            if create and not entries_existed:
                self._fsync_directory(self.opportunity_dir)
            yield fd
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _read_events_fd(fd: int, *, allow_empty: bool) -> list[dict[str, Any]]:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        if not raw:
            if allow_empty:
                return []
            raise _corrupt("opportunity ledger exists but is empty")
        if not raw.endswith(b"\n"):
            raise _corrupt("opportunity ledger has a torn final line")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _corrupt("opportunity ledger is not valid UTF-8") from exc
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(text[:-1].split("\n"), start=1):
            if not line:
                raise _corrupt(f"opportunity ledger line {line_number} is blank")
            try:
                event = json.loads(
                    line,
                    object_pairs_hook=_object_without_duplicate_keys,
                    parse_constant=_reject_json_constant,
                )
            except OpportunityLedgerError:
                raise
            except (json.JSONDecodeError, ValueError) as exc:
                raise _corrupt(
                    f"opportunity ledger line {line_number} is invalid JSON"
                ) from exc
            if not isinstance(event, dict):
                raise _corrupt(
                    f"opportunity ledger line {line_number} is not an object"
                )
            OpportunityTracker._validate_stored_event(event)
            events.append(event)
        return events

    @staticmethod
    def _validate_stored_event(event: dict[str, Any]) -> None:
        expected_fields = {
            "schema_version",
            "event",
            "event_id",
            "request_id",
            "recorded_at",
            "payload_sha256",
            "payload",
        }
        if set(event) != expected_fields:
            raise _corrupt("opportunity event envelope fields are invalid")
        if event["schema_version"] != _SCHEMA_VERSION:
            raise _corrupt("opportunity event schema version is unsupported")
        if event["event"] not in {
            "signal_observed",
            "decision_recorded",
            "action_observed",
            "action_coverage_observed",
            "missed_assessed",
        }:
            raise _corrupt("opportunity event type is invalid")
        if not isinstance(event["request_id"], str) or not event["request_id"]:
            raise _corrupt("opportunity event request_id is invalid")
        if not isinstance(event["payload"], dict):
            raise _corrupt("opportunity event payload is invalid")
        if (
            _utc_timestamp(event["recorded_at"], "event.recorded_at", stored=True)
            != event["recorded_at"]
        ):
            raise _corrupt("opportunity event recorded_at is not canonical UTC")
        _validate_json_tree(event)
        actual_payload_sha256 = _sha256(event["payload"])
        if (
            not isinstance(event["payload_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", event["payload_sha256"]) is None
            or event["payload_sha256"] != actual_payload_sha256
        ):
            raise _corrupt("opportunity event payload hash does not match")
        expected_event_id = (
            "oev_"
            + _sha256([event["event"], event["request_id"], event["payload_sha256"]])[
                :24
            ]
        )
        if event["event_id"] != expected_event_id:
            raise _corrupt("opportunity event identity does not match payload")
        normalized_input = copy.deepcopy(event["payload"])
        if event["event"] == "decision_recorded":
            normalized_input.pop("decision_id", None)
        if event["event"] == "action_observed":
            normalized_input.pop("action_id", None)
        try:
            normalized = OpportunityTracker._normalize_payload(
                event["event"],
                normalized_input,
                request_id=event["request_id"],
            )
        except OpportunityLedgerError as exc:
            raise _corrupt("opportunity stored payload values are invalid") from exc
        if normalized != event["payload"]:
            raise _corrupt("opportunity stored payload is not canonical")
        OpportunityTracker._validate_payload_schema(
            event["event"],
            event["payload"],
            stored=True,
        )

    @staticmethod
    def _validate_payload_schema(
        event_type: str,
        payload: dict[str, Any],
        *,
        stored: bool,
    ) -> None:
        fields = {
            "signal_observed": {
                "schema_version",
                "signal_id",
                "observed_at",
                "source",
                "instrument",
                "strategy",
                "score",
                "iv_rank",
                "policy",
                "eligibility",
            },
            "decision_recorded": {
                "signal_id",
                "decision",
                "actor",
                "reason",
                "decided_at",
                "revisit_at",
                "decision_id",
            },
            "action_observed": {
                "signal_id",
                "platform_signal_id",
                "platform_execution_id",
                "status",
                "actor",
                "occurred_at",
                "updated_at",
                "action_id",
            },
            "action_coverage_observed": {
                "signal_id",
                "source",
                "snapshot_id",
                "observed_at",
                "covered_through",
                "complete",
                "truncated",
            },
            "missed_assessed": {
                "signal_id",
                "assessed_at",
                "deadline_at",
                "reason_code",
                "coverage_event_id",
            },
        }[event_type]
        nested_fields = {
            "source": {"kind", "date", "row_sha256"},
            "instrument": {"asset_class", "contract_symbol", "underlying"},
            "policy": {"min_score", "min_iv_rank", "sha256"},
            "eligibility": {"status", "route", "reason_code", "deadline_at"},
        }
        valid = set(payload) == fields
        if event_type == "signal_observed" and valid:
            valid = all(
                isinstance(payload.get(name), dict) and set(payload[name]) == expected
                for name, expected in nested_fields.items()
            )
        if event_type == "signal_observed" and valid:
            source = payload["source"]
            instrument = payload["instrument"]
            policy = payload["policy"]
            eligibility = payload["eligibility"]
            numeric_values = (payload["score"], payload["iv_rank"])
            policy_values = (policy["min_score"], policy["min_iv_rank"])
            valid = (
                payload["schema_version"] == _SCHEMA_VERSION
                and source["kind"] == "options_scan"
                and isinstance(source["date"], str)
                and re.fullmatch(r"[0-9a-f]{64}", str(source["row_sha256"])) is not None
                and instrument["asset_class"] == "option"
                and (
                    instrument["contract_symbol"] is None
                    or (
                        isinstance(instrument["contract_symbol"], str)
                        and bool(instrument["contract_symbol"].strip())
                    )
                )
                and (
                    instrument["underlying"] is None
                    or (
                        isinstance(instrument["underlying"], str)
                        and bool(instrument["underlying"].strip())
                    )
                )
                and isinstance(payload["strategy"], str)
                and bool(payload["strategy"].strip())
                and all(
                    value is None
                    or (
                        not isinstance(value, bool)
                        and isinstance(value, (int, float))
                        and math.isfinite(float(value))
                    )
                    for value in numeric_values
                )
                and all(
                    value is None
                    or (
                        not isinstance(value, bool)
                        and isinstance(value, (int, float))
                        and math.isfinite(float(value))
                    )
                    for value in policy_values
                )
                and eligibility["status"] in {"eligible", "not_actionable", "unknown"}
            )
            if valid:
                if eligibility["status"] == "eligible":
                    valid = (
                        eligibility["route"] == "paper_strategy_execution"
                        and isinstance(eligibility["deadline_at"], str)
                        and eligibility["deadline_at"] >= f"{source['date']}T00:00:00Z"
                        and eligibility["reason_code"] is None
                    )
                else:
                    valid = (
                        eligibility["route"] is None
                        and eligibility["deadline_at"] is None
                        and isinstance(eligibility["reason_code"], str)
                        and bool(eligibility["reason_code"].strip())
                    )
            if valid:
                try:
                    expected_policy_sha256 = _sha256(
                        {
                            "min_score": policy["min_score"],
                            "min_iv_rank": policy["min_iv_rank"],
                        }
                    )
                    identity = {
                        "schema_version": _SCHEMA_VERSION,
                        "source_kind": source["kind"],
                        "source_date": source["date"],
                        "source_row_sha256": source["row_sha256"],
                        "contract_symbol": instrument["contract_symbol"],
                        "policy_sha256": policy["sha256"],
                    }
                    expected_signal_id = f"sig_{_sha256(identity)[:24]}"
                    valid = (
                        policy["sha256"] == expected_policy_sha256
                        and payload["signal_id"] == expected_signal_id
                    )
                except OpportunityLedgerError:
                    valid = False
        if valid:
            return
        error = "opportunity event payload fields are invalid"
        if stored:
            raise _corrupt(error)
        raise _invalid(error)

    @staticmethod
    def _append_event(fd: int, event: dict[str, Any]) -> None:
        _validate_json_tree(event)
        encoded = (_canonical_json(event) + "\n").encode("utf-8", errors="strict")
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("opportunity ledger write made no progress")
            view = view[written:]
        os.fsync(fd)

    @staticmethod
    def _timely_action_resolution(state: dict[str, Any]) -> Optional[str]:
        eligibility = state["signal"]["eligibility"]
        deadline = eligibility.get("deadline_at")
        if eligibility.get("status") != "eligible" or not isinstance(deadline, str):
            return None
        timely_actions = [
            action
            for action in state["actions"]
            if action["occurred_at"] <= deadline
            and bool(action.get("platform_execution_id"))
        ]
        if any(
            action["status"] in {"pending", "partially_filled", "filled"}
            for action in timely_actions
        ):
            return "acted"
        if timely_actions:
            return "action_failed"
        return None

    @staticmethod
    def _validate_causal_lower_bound(
        state: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
        *,
        stored: bool,
    ) -> None:
        timestamp_field = {
            "decision_recorded": "decided_at",
            "action_observed": "occurred_at",
        }.get(event_type)
        if timestamp_field is None:
            return
        source_date = state["signal"]["source"]["date"]
        source_utc_floor = f"{source_date}T00:00:00Z"
        if payload[timestamp_field] < source_utc_floor:
            error = _corrupt if stored else _invalid
            raise error(f"{event_type} cannot predate the signal source UTC date")

    @staticmethod
    def _resolution_from_facts(state: dict[str, Any]) -> str:
        eligibility = state["signal"]["eligibility"]
        eligibility_status = eligibility["status"]
        if eligibility_status in {"not_actionable", "unknown"}:
            return eligibility_status
        if state["missed_assessment"] is not None:
            return "missed"
        action_resolution = OpportunityTracker._timely_action_resolution(state)
        if action_resolution is not None:
            return action_resolution
        decision = state["decision"]
        deadline = eligibility["deadline_at"]
        if decision is None or decision["decided_at"] > deadline:
            return "open"
        if decision["decision"] == "decline":
            return "declined"
        if decision["decision"] == "defer":
            return "deferred"
        return "open"

    @staticmethod
    def _validate_missed_assessment(
        state: dict[str, Any],
        assessment: dict[str, Any],
        coverage_events: dict[str, dict[str, Any]],
    ) -> None:
        eligibility = state["signal"]["eligibility"]
        deadline = eligibility.get("deadline_at")
        if (
            eligibility.get("status") != "eligible"
            or not isinstance(deadline, str)
            or assessment["deadline_at"] != deadline
            or assessment["assessed_at"] <= deadline
        ):
            raise _corrupt("missed assessment has an invalid action window")
        coverage_event_id = assessment.get("coverage_event_id")
        coverage = (
            coverage_events.get(coverage_event_id)
            if isinstance(coverage_event_id, str)
            else None
        )
        if (
            coverage is None
            or not coverage["complete"]
            or coverage["truncated"]
            or coverage["covered_through"] < deadline
            or coverage["observed_at"] > assessment["assessed_at"]
        ):
            raise _corrupt("missed assessment lacks complete referenced coverage")
        if OpportunityTracker._timely_action_resolution(state) is not None:
            raise _corrupt("missed assessment contradicts a timely action")
        decision = state["decision"]
        timely_decision = (
            decision
            if decision is not None and decision["decided_at"] <= deadline
            else None
        )
        if timely_decision is not None and timely_decision["decision"] == "decline":
            raise _corrupt("missed assessment contradicts a timely decline")
        expected_reason = "no_decision"
        if timely_decision is not None and timely_decision["decision"] == "act":
            expected_reason = "act_without_action"
        elif timely_decision is not None and timely_decision["decision"] == "defer":
            expected_reason = "defer_expired"
        if assessment["reason_code"] != expected_reason:
            raise _corrupt("missed assessment reason contradicts decision facts")

    @staticmethod
    def _reduce(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        coverage_facts: dict[str, dict[str, dict[str, Any]]] = {}
        action_owners: dict[str, str] = {}
        event_ids: set[str] = set()
        request_ids: set[str] = set()
        for event in events:
            if event["event_id"] in event_ids:
                raise _corrupt("opportunity event identity is duplicated")
            if event["request_id"] in request_ids:
                raise _corrupt("opportunity request identity is duplicated")
            event_ids.add(event["event_id"])
            request_ids.add(event["request_id"])
            payload = event["payload"]
            signal_id = payload["signal_id"]
            if event["event"] == "signal_observed":
                if signal_id in states:
                    existing = dict(states[signal_id]["signal"])
                    incoming = dict(payload)
                    existing.pop("observed_at", None)
                    incoming.pop("observed_at", None)
                    if existing != incoming:
                        raise _corrupt("signal_id is reused with a different payload")
                    continue
                eligibility = payload["eligibility"]["status"]
                resolution = (
                    eligibility
                    if eligibility in {"not_actionable", "unknown"}
                    else "open"
                )
                states[signal_id] = {
                    "signal_id": signal_id,
                    "signal": payload,
                    "resolution": resolution,
                    "decision": None,
                    "actions": [],
                    "coverage": None,
                    "missed_assessment": None,
                }
                continue
            state = states.get(signal_id)
            if state is None:
                raise _corrupt(f"orphan {event['event']} event")
            OpportunityTracker._validate_causal_lower_bound(
                state,
                event["event"],
                payload,
                stored=True,
            )
            if event["event"] == "decision_recorded":
                if state["decision"] is not None:
                    raise _corrupt("opportunity has multiple decision events")
                state["decision"] = payload
                if state["missed_assessment"] is not None:
                    state["resolution"] = "missed"
                    continue
                eligibility_status = state["signal"]["eligibility"]["status"]
                if eligibility_status in {"not_actionable", "unknown"}:
                    state["resolution"] = eligibility_status
                    continue
                deadline = state["signal"]["eligibility"]["deadline_at"]
                if payload["decided_at"] > deadline:
                    continue
                if payload["decision"] == "decline":
                    state["resolution"] = "declined"
                elif payload["decision"] == "defer":
                    state["resolution"] = "deferred"
                else:
                    state["resolution"] = "open"
                continue
            if event["event"] == "action_observed":
                owner = action_owners.get(payload["action_id"])
                if owner is not None and owner != signal_id:
                    raise _corrupt("one external action is linked to multiple signals")
                action_owners[payload["action_id"]] = signal_id
                existing_index = next(
                    (
                        index
                        for index, action in enumerate(state["actions"])
                        if action["action_id"] == payload["action_id"]
                    ),
                    None,
                )
                if existing_index is None:
                    state["actions"].append(payload)
                else:
                    existing_action = state["actions"][existing_index]
                    immutable_action_fields = {
                        "signal_id",
                        "platform_signal_id",
                        "platform_execution_id",
                        "actor",
                        "occurred_at",
                        "action_id",
                    }
                    if any(
                        payload[field] != existing_action[field]
                        for field in immutable_action_fields
                    ):
                        raise _corrupt(
                            "action identity fields changed across revisions"
                        )
                    if payload["updated_at"] < existing_action["updated_at"]:
                        raise _corrupt("action updated_at moves backwards")
                    allowed_next = {
                        "pending": {
                            "pending",
                            "partially_filled",
                            "filled",
                            "blocked",
                            "failed",
                            "cancelled",
                            "missed_window",
                            "skipped",
                        },
                        "partially_filled": {
                            "partially_filled",
                            "filled",
                            "blocked",
                            "failed",
                            "cancelled",
                            "missed_window",
                            "skipped",
                        },
                        "filled": {"filled"},
                        "blocked": {"blocked"},
                        "failed": {"failed"},
                        "cancelled": {"cancelled"},
                        "missed_window": {"missed_window"},
                        "skipped": {"skipped"},
                    }
                    if payload["status"] not in allowed_next[existing_action["status"]]:
                        raise _corrupt("action status transition moves backwards")
                    state["actions"][existing_index] = payload
                deadline = state["signal"]["eligibility"].get("deadline_at")
                timely = (
                    isinstance(deadline, str)
                    and payload["occurred_at"] <= deadline
                    and payload.get("platform_execution_id")
                )
                if timely and state["missed_assessment"] is None:
                    state["resolution"] = (
                        "acted"
                        if payload["status"]
                        in {"pending", "partially_filled", "filled"}
                        else "action_failed"
                    )
                continue
            if event["event"] == "action_coverage_observed":
                existing_coverage = state["coverage"]
                if existing_coverage is not None and (
                    payload["observed_at"] < existing_coverage["observed_at"]
                    or payload["covered_through"] < existing_coverage["covered_through"]
                    or (existing_coverage["complete"] and not payload["complete"])
                    or (not existing_coverage["truncated"] and payload["truncated"])
                ):
                    raise _corrupt("action coverage watermark moves backwards")
                coverage = {
                    **payload,
                    "coverage_event_id": event["event_id"],
                }
                state["coverage"] = coverage
                coverage_facts.setdefault(signal_id, {})[event["event_id"]] = coverage
                continue
            if event["event"] == "missed_assessed":
                if state["missed_assessment"] is not None:
                    raise _corrupt("signal has multiple missed assessments")
                OpportunityTracker._validate_missed_assessment(
                    state,
                    payload,
                    coverage_facts.get(signal_id, {}),
                )
                state["missed_assessment"] = payload
                state["resolution"] = "missed"
        for state in states.values():
            state["resolution"] = OpportunityTracker._resolution_from_facts(state)
        return states
