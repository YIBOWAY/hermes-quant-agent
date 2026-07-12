from __future__ import annotations

import copy
import errno
import fcntl
import json
import math
import os
import re
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo


_JOBS = {"daily_close", "freshness", "weekly", "notification_drain"}
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z")
_RECEIPT_FIELDS = {
    "schema_version",
    "run_id",
    "request_id",
    "job",
    "as_of",
    "started_at",
    "completed_at",
    "status",
    "replayed",
    "steps",
    "notifications",
}
_STEP_STATUSES = {
    "available",
    "empty",
    "degraded",
    "failed",
    "skipped",
    "queued",
    "retryable",
    "outcome_unknown",
}
_NOTIFICATION_FIELDS = {
    "planned",
    "delivered",
    "queued",
    "fallback_persisted",
    "delivery_unknown",
    "suppressed",
}
_RUN_STATE_FIELDS = {
    "schema_version",
    "run_id",
    "request_id",
    "job",
    "as_of",
    "started_at",
    "phase",
    "current_step",
    "steps",
    "results",
    "notifications",
    "receipt",
}
_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_JOB_POLICIES = (
    ("daily_close", "15,25 8 * * 2-6", 30 * 60 * 60),
    ("freshness", "17 */2 * * *", 3 * 60 * 60),
    ("weekly", "0,10 9 * * 0", 8 * 24 * 60 * 60),
    ("notification_drain", "7,22,37,52 * * * *", 30 * 60),
)


class AutomationError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _utc_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AutomationError("automation_invalid_request", f"{field} is required")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AutomationError(
            "automation_invalid_request", f"{field} must be timezone-aware"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AutomationError(
            "automation_invalid_request", f"{field} must be timezone-aware"
        )
    try:
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError) as exc:
        raise AutomationError(
            "automation_invalid_request", f"{field} is outside the supported range"
        ) from exc


def _strict_json(line: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        line,
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )


def _validate_tree(root: Any) -> None:
    stack = [root]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            value.encode("utf-8", errors="strict")
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite value")
        elif isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _run_id(job: str, request_id: str) -> str:
    digest = sha256(f"{job}\0{request_id}".encode("utf-8")).hexdigest()[:20]
    return f"hqa9h:{job}:{digest}"


def _counts(document: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, value in document.items():
        if (
            isinstance(key, str)
            and (key.endswith("_count") or key == "count")
            and not isinstance(value, bool)
            and isinstance(value, int)
            and value >= 0
        ):
            counts[key] = value
    results = document.get("results")
    if isinstance(results, list):
        counts["result_count"] = len(results)
        counts["scored_count"] = sum(
            1
            for result in results
            if isinstance(result, dict) and result.get("status") == "scored"
        )
    return dict(sorted(counts.items()))


def _next_daily_slot(last_success: datetime) -> datetime:
    local = last_success.astimezone(_LOCAL_TIMEZONE)
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        # Python Monday=0; the cron range Tue-Sat is 1..5.
        if day.weekday() not in {1, 2, 3, 4, 5}:
            continue
        candidate = datetime(
            day.year,
            day.month,
            day.day,
            8,
            15,
            tzinfo=_LOCAL_TIMEZONE,
        )
        if candidate > local:
            return candidate.astimezone(timezone.utc)
    raise AutomationError(
        "automation_status_invalid", "daily schedule is outside the supported range"
    )


def _fresh_until(job: str, last_success: datetime, budget: int) -> datetime:
    deadline = last_success + timedelta(seconds=budget)
    if job == "daily_close":
        next_slot = _next_daily_slot(last_success)
        if deadline < next_slot:
            # Keep weekends/closed days fresh, then allow one monitor cycle plus
            # jitter after the next real close-cycle slot.
            deadline = next_slot + timedelta(hours=3)
    return deadline


def _notification_status(receipt: dict[str, Any]) -> str:
    summary = receipt.get("notifications")
    if not isinstance(summary, dict):
        return "delivery_unknown"
    if (
        isinstance(summary.get("delivery_unknown"), int)
        and summary["delivery_unknown"] > 0
    ):
        return "delivery_unknown"
    if isinstance(summary.get("delivered"), int) and summary["delivered"] > 0:
        return "delivered"
    if isinstance(summary.get("queued"), int) and summary["queued"] > 0:
        return "queued"
    if (
        isinstance(summary.get("fallback_persisted"), int)
        and summary["fallback_persisted"] > 0
    ):
        return "fallback_persisted"
    return "not_required"


def _valid_notification_summary(summary: Any) -> bool:
    return (
        isinstance(summary, dict)
        and set(summary) == _NOTIFICATION_FIELDS
        and all(
            not isinstance(value, bool) and isinstance(value, int) and value >= 0
            for value in summary.values()
        )
        and sum(summary[field] for field in _NOTIFICATION_FIELDS - {"planned"})
        <= summary["planned"]
    )


def build_automation_status(
    *,
    as_of: str,
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fold durable run receipts into the strict per-job freshness artifact."""

    checked_text = _utc_text(as_of, "as_of")
    checked_at = _utc_datetime_for_status(checked_text)
    if not isinstance(receipts, list):
        raise AutomationError("automation_status_invalid", "receipts must be a list")
    by_job: dict[str, list[tuple[datetime, dict[str, Any]]]] = {
        job: [] for job in _JOBS
    }
    for receipt in receipts:
        if not isinstance(receipt, dict) or receipt.get("job") not in _JOBS:
            raise AutomationError("automation_status_invalid", "receipt job is invalid")
        completed = _utc_datetime_for_status(receipt.get("completed_at"))
        if completed > checked_at:
            raise AutomationError(
                "automation_status_invalid", "future receipt is not allowed"
            )
        if receipt.get("status") not in {"available", "degraded", "failed"}:
            raise AutomationError(
                "automation_status_invalid", "receipt status is invalid"
            )
        if not isinstance(receipt.get("run_id"), str) or not receipt["run_id"]:
            raise AutomationError(
                "automation_status_invalid", "receipt run_id is invalid"
            )
        by_job[receipt["job"]].append((completed, receipt))

    jobs: list[dict[str, Any]] = []
    for job, schedule, budget in _JOB_POLICIES:
        rows = sorted(by_job[job], key=lambda pair: pair[0])
        if not rows:
            jobs.append(
                {
                    "job_id": job,
                    "expected_schedule": schedule,
                    "timezone": "Asia/Shanghai",
                    "freshness_budget_seconds": budget,
                    "last_attempt_at": None,
                    "last_success_at": None,
                    "fresh_until": None,
                    "status": "never_run",
                    "reason_code": "never_run",
                    "last_run_id": None,
                    "notification_status": "not_required",
                }
            )
            continue
        latest_time, latest = rows[-1]
        successes = [pair for pair in rows if pair[1]["status"] == "available"]
        success_time: Optional[datetime] = successes[-1][0] if successes else None
        deadline = (
            None if success_time is None else _fresh_until(job, success_time, budget)
        )
        if latest["status"] in {"degraded", "failed"}:
            status = "failed"
            reason_code = "last_attempt_degraded"
        elif deadline is None:
            status = "failed"
            reason_code = "no_successful_run"
        elif checked_at > deadline:
            status = "stale"
            reason_code = "freshness_budget_exceeded"
        else:
            status = "fresh"
            reason_code = None
        jobs.append(
            {
                "job_id": job,
                "expected_schedule": schedule,
                "timezone": "Asia/Shanghai",
                "freshness_budget_seconds": budget,
                "last_attempt_at": latest_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last_success_at": (
                    None
                    if success_time is None
                    else success_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                ),
                "fresh_until": (
                    None
                    if deadline is None
                    else deadline.strftime("%Y-%m-%dT%H:%M:%SZ")
                ),
                "status": status,
                "reason_code": reason_code,
                "last_run_id": latest["run_id"],
                "notification_status": _notification_status(latest),
            }
        )
    overall_status = (
        "fresh" if all(row["status"] == "fresh" for row in jobs) else "degraded"
    )
    artifact = {
        "schema_version": "1.0",
        "kind": "automation_status",
        "generated_at": checked_text,
        "status": "available" if overall_status == "fresh" else "degraded",
        "reason_codes": (
            [] if overall_status == "fresh" else ["automation_jobs_degraded"]
        ),
        "data": {
            "checked_at": checked_text,
            "overall_status": overall_status,
            "jobs": jobs,
            "proposal_only": True,
            "trading_allowed": False,
        },
    }
    try:
        _validate_tree(artifact)
        json.dumps(artifact, ensure_ascii=False, allow_nan=False)
    except Exception as exc:
        raise AutomationError(
            "automation_status_invalid", "automation status is not strict JSON"
        ) from exc
    return artifact


def _utc_datetime_for_status(value: Any) -> datetime:
    try:
        canonical = _utc_text(value, "timestamp")
        return datetime.strptime(canonical, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except AutomationError as exc:
        raise AutomationError(
            "automation_status_invalid", "automation timestamp is invalid"
        ) from exc


class ResearchAutomation:
    """One-shot, read-only full-9H coordinator.

    Hermes owns cadence; this module owns ordering, isolation, process-level
    exclusion, receipts and notification intent. Domain services stay injected
    so the coordinator cannot reach execution or trading paths by accident.
    """

    def __init__(
        self,
        automation_dir: Path,
        *,
        services: Any,
        now: Callable[[], str],
        notification_target: str = "local",
    ) -> None:
        self.automation_dir = Path(automation_dir)
        self.receipts_path = self.automation_dir / "runs.jsonl"
        self.lock_path = self.automation_dir / ".run.lock"
        self._services = services
        self._now = now
        if not isinstance(notification_target, str) or not notification_target.strip():
            raise ValueError("notification_target must be non-empty text")
        self._notification_target = notification_target.strip()

    def run(
        self,
        *,
        job: str,
        request_id: str,
        as_of: str,
    ) -> dict[str, Any]:
        if job not in _JOBS:
            raise AutomationError(
                "automation_invalid_request",
                "job must be daily_close, freshness, weekly, or notification_drain",
            )
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            raise AutomationError(
                "automation_invalid_request", "request_id is not canonical"
            )
        canonical_as_of = _utc_text(as_of, "as_of")
        run_id = _run_id(job, request_id)
        self._prepare_directory()
        lock_fd = self._open_secure_file(
            self.lock_path,
            os.O_RDWR | os.O_CREAT,
            "automation lock",
        )
        acquired = False
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                self._assert_path_identity(
                    lock_fd,
                    self.lock_path,
                    "automation lock",
                )
                busy = self._busy_receipt(
                    job=job,
                    request_id=request_id,
                    run_id=run_id,
                    as_of=canonical_as_of,
                )
                self._write_busy_receipt(busy)
                return busy

            self._assert_path_identity(
                lock_fd,
                self.lock_path,
                "automation lock",
            )
            receipts = self._read_receipts()
            existing = next(
                (row for row in receipts if row["request_id"] == request_id),
                None,
            )
            if existing is not None:
                if existing["job"] != job or existing["as_of"] != canonical_as_of:
                    raise AutomationError(
                        "automation_idempotency_conflict",
                        "request_id already belongs to a different automation intent",
                    )
                state = self._load_state(request_id)
                if state is not None and state["phase"] != "completed":
                    state["phase"] = "completed"
                    state["receipt"] = existing
                    state["current_step"] = None
                    self._write_state(state)
                replay = copy.deepcopy(existing)
                replay["replayed"] = True
                return replay

            state = self._load_state(request_id)
            if state is None:
                state = self._new_state(
                    job=job,
                    request_id=request_id,
                    run_id=run_id,
                    as_of=canonical_as_of,
                )
                self._write_state(state)
            else:
                self._validate_state_intent(
                    state,
                    job=job,
                    request_id=request_id,
                    run_id=run_id,
                    as_of=canonical_as_of,
                )
            if state["phase"] in {"finalizing", "completed"}:
                return self._finish_finalizing(state, receipts)
            if state["current_step"] is not None:
                self._recover_interrupted_step(state)

            steps = state["steps"]
            results = state["results"]
            notifications = state["notifications"]
            for name, callback in self._core_callbacks(job, canonical_as_of):
                self._execute_step(state, name, callback)

            if job == "freshness":
                self._execute_step(
                    state,
                    "automation_pre_projection",
                    lambda: self._services.automation_projection(
                        job,
                        canonical_as_of,
                        run_id,
                        copy.deepcopy(steps),
                        copy.deepcopy(notifications),
                    ),
                )
            intent = self._notification_intent(
                job=job,
                run_id=run_id,
                as_of=canonical_as_of,
                steps=steps,
                results=results,
            )
            if intent is not None:
                if notifications["planned"] == 0:
                    notifications["planned"] = 1
                    self._write_state(state)
                self._execute_notification(state, intent)

            self._execute_step(
                state,
                "automation_projection",
                lambda: self._services.automation_projection(
                    job,
                    canonical_as_of,
                    run_id,
                    copy.deepcopy(steps),
                    copy.deepcopy(notifications),
                ),
            )
            self._execute_step(
                state,
                "feed_refresh",
                lambda: self._services.feed_refresh(canonical_as_of),
            )

            completed_at = _utc_text(self._now(), "completed_at")
            statuses = [step["status"] for step in steps]
            failed_count = sum(status == "failed" for status in statuses)
            degraded = failed_count > 0 or any(
                status
                in {"degraded", "queued", "retryable", "outcome_unknown"}
                for status in statuses
            )
            if steps and all(
                status in {"failed", "outcome_unknown"} for status in statuses
            ):
                status = "failed"
            else:
                status = "degraded" if degraded else "available"
            receipt = {
                "schema_version": "1.0",
                "run_id": run_id,
                "request_id": request_id,
                "job": job,
                "as_of": canonical_as_of,
                "started_at": state["started_at"],
                "completed_at": completed_at,
                "status": status,
                "replayed": False,
                "steps": steps,
                "notifications": notifications,
            }
            self._validate_receipt(receipt)
            state["phase"] = "finalizing"
            state["current_step"] = None
            state["receipt"] = receipt
            self._write_state(state)
            return self._finish_finalizing(state, receipts)
        finally:
            try:
                if acquired:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def latest(self, job: str) -> Optional[dict[str, Any]]:
        if job not in _JOBS:
            raise AutomationError("automation_invalid_request", "job is invalid")
        rows = [row for row in self._read_receipts() if row["job"] == job]
        return None if not rows else copy.deepcopy(rows[-1])

    def list_receipts(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._read_receipts())

    def _core_callbacks(
        self,
        job: str,
        as_of: str,
    ) -> list[tuple[str, Callable[[], dict[str, Any]]]]:
        service = self._services
        if job == "daily_close":
            callbacks: list[tuple[str, Callable[[], dict[str, Any]]]] = [
                ("signal_catchup", lambda: service.signal_catchup(as_of)),
                ("portfolio_risk", lambda: service.portfolio_risk(as_of)),
                ("prediction_reconcile", lambda: service.prediction_reconcile(as_of)),
                ("opportunity_coverage", lambda: service.opportunity_coverage(as_of)),
                ("opportunity_reconcile", lambda: service.opportunity_reconcile(as_of)),
                (
                    "opportunity_projection",
                    lambda: service.opportunity_projection(as_of),
                ),
            ]
        elif job == "weekly":
            callbacks = [
                ("weekly_projection", lambda: service.weekly_projection(as_of)),
                (
                    "opportunity_projection",
                    lambda: service.opportunity_projection(as_of),
                ),
            ]
        elif job == "freshness":
            # Local-only rebuild so a just-caught-up signal becomes visible on
            # the next monitor tick without waiting for the weekly job.
            callbacks = [
                (
                    "opportunity_projection",
                    lambda: service.opportunity_projection(as_of),
                ),
            ]
        else:
            callbacks = [
                ("notification_drain", lambda: service.notification_drain(as_of)),
            ]
        return callbacks

    def _new_state(
        self,
        *,
        job: str,
        request_id: str,
        run_id: str,
        as_of: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "run_id": run_id,
            "request_id": request_id,
            "job": job,
            "as_of": as_of,
            "started_at": _utc_text(self._now(), "started_at"),
            "phase": "running",
            "current_step": None,
            "steps": [],
            "results": {},
            "notifications": self._notification_summary(),
            "receipt": None,
        }

    def _execute_step(
        self,
        state: dict[str, Any],
        name: str,
        callback: Callable[[], dict[str, Any]],
    ) -> None:
        if any(step["name"] == name for step in state["steps"]):
            return
        state["current_step"] = name
        self._write_state(state)
        step, result = self._run_step(name, callback)
        state["steps"].append(step)
        state["results"][name] = result
        state["current_step"] = None
        self._write_state(state)

    def _execute_notification(
        self,
        state: dict[str, Any],
        intent: dict[str, str],
    ) -> None:
        name = "notification_enqueue"
        if any(step["name"] == name for step in state["steps"]):
            return
        state["current_step"] = name
        self._write_state(state)
        step, result = self._run_notification(intent)
        state["steps"].append(step)
        state["results"][name] = result
        self._fold_notification(state["notifications"], result)
        state["current_step"] = None
        self._write_state(state)

    def _recover_interrupted_step(self, state: dict[str, Any]) -> None:
        name = state["current_step"]
        if not isinstance(name, str) or not name:
            raise AutomationError(
                "automation_state_corrupt", "current_step is invalid"
            )
        state["steps"].append(
            {
                "name": name,
                "status": "outcome_unknown",
                "changed": False,
                "counts": {},
                "error": {
                    "code": f"automation_{name}_outcome_unknown",
                    "retryable": False,
                },
            }
        )
        state["results"][name] = {}
        if name == "notification_enqueue":
            state["notifications"]["delivery_unknown"] += 1
        state["current_step"] = None
        self._write_state(state)

    def _finish_finalizing(
        self,
        state: dict[str, Any],
        receipts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        receipt = state.get("receipt")
        if not isinstance(receipt, dict):
            raise AutomationError(
                "automation_state_corrupt", "finalizing state has no receipt"
            )
        self._validate_receipt(receipt)
        existing = next(
            (row for row in receipts if row["run_id"] == receipt["run_id"]),
            None,
        )
        if existing is None:
            self._append_receipt(receipt)
        elif existing != receipt:
            raise AutomationError(
                "automation_state_corrupt", "final receipt does not match run store"
            )
        state["phase"] = "completed"
        self._write_state(state)
        return copy.deepcopy(receipt)

    def _run_step(
        self,
        name: str,
        callback: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            result = callback()
            if not isinstance(result, dict):
                raise ValueError("step result must be an object")
            result_status = result.get("status", "available")
            if result_status not in _STEP_STATUSES:
                raise ValueError("step status is invalid")
            counts = _counts(result)
            step = {
                "name": name,
                "status": result_status,
                "changed": any(value > 0 for value in counts.values()),
                "counts": counts,
                "error": None,
            }
            return step, result
        except Exception:
            return (
                {
                    "name": name,
                    "status": "failed",
                    "changed": False,
                    "counts": {},
                    "error": {
                        "code": f"automation_{name}_failed",
                        "retryable": True,
                    },
                },
                {},
            )

    def _notification_intent(
        self,
        *,
        job: str,
        run_id: str,
        as_of: str,
        steps: list[dict[str, Any]],
        results: dict[str, dict[str, Any]],
    ) -> Optional[dict[str, str]]:
        topic: Optional[str] = None
        message: Optional[str] = None
        if job == "weekly":
            topic = "weekly"
            message = f"[HQA] weekly review as_of={as_of} run={run_id}"
        elif job == "daily_close":
            prediction = results.get("prediction_reconcile", {})
            scored = sum(
                1
                for row in prediction.get("results", [])
                if isinstance(row, dict) and row.get("status") == "scored"
            )
            missed = results.get("opportunity_reconcile", {}).get("missed_count", 0)
            degraded = any(step["status"] in {"degraded", "failed"} for step in steps)
            if scored or (isinstance(missed, int) and missed > 0) or degraded:
                topic = "daily"
                message = (
                    f"[HQA] daily close as_of={as_of} scored={scored} "
                    f"missed={missed if isinstance(missed, int) else 0} "
                    f"status={'degraded' if degraded else 'available'} run={run_id}"
                )
        elif job == "freshness":
            projection = results.get("automation_pre_projection", {})
            transition = projection.get("transition")
            if transition in {"degraded", "recovered"}:
                topic = f"freshness-{transition}"
                message = f"[HQA] freshness {transition} as_of={as_of} run={run_id}"
        if topic is None or message is None:
            return None
        return {
            "request_id": f"{run_id}:{topic}",
            "target": self._notification_target,
            "message": message,
        }

    def _run_notification(
        self,
        request: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            result = self._services.notification_enqueue(request)
            if not isinstance(result, dict) or not isinstance(result.get("state"), str):
                raise ValueError("notification receipt is invalid")
            state = result["state"]
            if state not in {
                "delivered",
                "queued",
                "fallback_persisted",
                "delivery_unknown",
            }:
                raise ValueError("notification state is invalid")
            status = "available" if state in {"delivered", "queued"} else "degraded"
            count_key = {
                "delivered": "notification_delivered_count",
                "queued": "notification_queued_count",
                "fallback_persisted": "notification_fallback_persisted_count",
                "delivery_unknown": "notification_delivery_unknown_count",
            }.get(state, "notification_delivery_unknown_count")
            return (
                {
                    "name": "notification_enqueue",
                    "status": status,
                    "changed": True,
                    "counts": {"notification_count": 1, count_key: 1},
                    "error": None,
                },
                result,
            )
        except Exception:
            return (
                {
                    "name": "notification_enqueue",
                    "status": "failed",
                    "changed": False,
                    "counts": {},
                    "error": {
                        "code": "automation_notification_enqueue_failed",
                        "retryable": True,
                    },
                },
                {"state": "delivery_unknown"},
            )

    @staticmethod
    def _notification_summary() -> dict[str, int]:
        return {
            "planned": 0,
            "delivered": 0,
            "queued": 0,
            "fallback_persisted": 0,
            "delivery_unknown": 0,
            "suppressed": 0,
        }

    @staticmethod
    def _fold_notification(summary: dict[str, int], receipt: dict[str, Any]) -> None:
        state = receipt.get("state")
        if state == "delivered":
            summary["delivered"] += 1
        elif state == "queued":
            summary["queued"] += 1
        elif state == "delivery_unknown":
            summary["delivery_unknown"] += 1
        else:
            summary["fallback_persisted"] += 1

    def _prepare_directory(self) -> None:
        self._prepare_private_directory(
            self.automation_dir,
            "automation directory",
        )

    def _state_path(self, request_id: str) -> Path:
        digest = sha256(request_id.encode("utf-8")).hexdigest()
        return self.automation_dir / "state" / f"{digest}.json"

    def _load_state(self, request_id: str) -> Optional[dict[str, Any]]:
        path = self._state_path(request_id)
        if not os.path.lexists(path):
            return None
        try:
            self._assert_secure_directory(path.parent, "automation state directory")
            raw = self._read_secure_file(
                path,
                "automation run state",
                max_size=4 * 1024 * 1024,
            )
            state = _strict_json(raw.decode("utf-8", errors="strict"))
            self._validate_state(state)
            return state
        except AutomationError:
            raise
        except Exception as exc:
            raise AutomationError(
                "automation_state_corrupt", "automation run state is unreadable"
            ) from exc

    def _write_state(self, state: dict[str, Any]) -> None:
        self._validate_state(state)
        self._write_atomic_private(self._state_path(state["request_id"]), state)

    def _write_busy_receipt(self, receipt: dict[str, Any]) -> None:
        digest = sha256(
            f"{receipt['run_id']}\0{receipt['as_of']}".encode("utf-8")
        ).hexdigest()
        path = self.automation_dir / "busy" / f"{digest}.json"
        self._write_atomic_private(path, receipt)

    @classmethod
    def _write_atomic_private(cls, path: Path, document: dict[str, Any]) -> None:
        payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8", errors="strict")
        cls._prepare_private_directory(path.parent, f"{path.parent.name} directory")
        cls._assert_existing_private_target(path, path.name)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            temporary_metadata = os.fstat(fd)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            cls._assert_existing_private_target(path, path.name)
            os.replace(temporary, path)
            cls._assert_replaced_identity(
                path,
                temporary_metadata,
                path.name,
            )
            cls._fsync_directory(path.parent, f"{path.parent.name} directory")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _assert_secure_metadata(metadata: os.stat_result, label: str) -> None:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
        ):
            raise AutomationError(
                "automation_storage_insecure",
                f"{label} must be an owner-only regular file",
            )

    @staticmethod
    def _assert_secure_directory(path: Path, label: str) -> None:
        try:
            metadata = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise AutomationError(
                "automation_storage_insecure",
                f"{label} is unavailable",
            ) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            raise AutomationError(
                "automation_storage_insecure",
                f"{label} must be an owner-only real directory",
            )

    @classmethod
    def _prepare_private_directory(cls, path: Path, label: str) -> None:
        if not os.path.lexists(path):
            try:
                path.mkdir(parents=True, mode=0o700)
            except FileExistsError:
                pass
            except OSError as exc:
                raise AutomationError(
                    "automation_storage_io_error",
                    f"{label} could not be created",
                    retryable=True,
                ) from exc
        cls._assert_secure_directory(path, label)

    @classmethod
    def _open_secure_file(cls, path: Path, flags: int, label: str) -> int:
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise AutomationError(
                "automation_storage_insecure",
                "secure no-follow file access is unavailable",
            )
        try:
            fd = os.open(path, flags | no_follow, 0o600)
        except OSError as exc:
            if exc.errno in {
                errno.ELOOP,
                errno.EISDIR,
                getattr(errno, "EMLINK", -1),
            }:
                raise AutomationError(
                    "automation_storage_insecure",
                    f"{label} must not be a symbolic link",
                ) from exc
            raise AutomationError(
                "automation_storage_io_error",
                f"{label} could not be opened",
                retryable=True,
            ) from exc
        try:
            cls._assert_secure_metadata(os.fstat(fd), label)
            cls._assert_path_identity(fd, path, label)
            return fd
        except BaseException:
            os.close(fd)
            raise

    @classmethod
    def _assert_path_identity(cls, fd: int, path: Path, label: str) -> None:
        opened = os.fstat(fd)
        try:
            current = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise AutomationError(
                "automation_storage_insecure",
                f"{label} path disappeared after open",
            ) from exc
        cls._assert_secure_metadata(current, label)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise AutomationError(
                "automation_storage_insecure",
                f"{label} path identity changed after open",
            )

    @classmethod
    def _read_secure_file(cls, path: Path, label: str, *, max_size: int) -> bytes:
        fd = cls._open_secure_file(path, os.O_RDONLY, label)
        try:
            if os.fstat(fd).st_size > max_size:
                raise ValueError(f"{label} exceeds size limit")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 65_536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_size:
                    raise ValueError(f"{label} exceeds size limit")
            cls._assert_path_identity(fd, path, label)
            return b"".join(chunks)
        finally:
            os.close(fd)

    @classmethod
    def _assert_existing_private_target(cls, path: Path, label: str) -> None:
        if not os.path.lexists(path):
            return
        fd = cls._open_secure_file(path, os.O_RDONLY, label)
        os.close(fd)

    @classmethod
    def _assert_replaced_identity(
        cls,
        path: Path,
        expected: os.stat_result,
        label: str,
    ) -> None:
        try:
            current = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise AutomationError(
                "automation_storage_insecure",
                f"{label} disappeared after atomic replace",
            ) from exc
        cls._assert_secure_metadata(current, label)
        if (expected.st_dev, expected.st_ino) != (current.st_dev, current.st_ino):
            raise AutomationError(
                "automation_storage_insecure",
                f"{label} identity changed during atomic replace",
            )

    @classmethod
    def _fsync_directory(cls, path: Path, label: str) -> None:
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise AutomationError(
                "automation_storage_insecure",
                "secure no-follow directory access is unavailable",
            )
        try:
            fd = os.open(path, os.O_RDONLY | no_follow)
        except OSError as exc:
            raise AutomationError(
                "automation_storage_io_error",
                f"{label} could not be opened",
                retryable=True,
            ) from exc
        try:
            opened = os.fstat(fd)
            cls._assert_secure_directory(path, label)
            current = os.stat(path, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise AutomationError(
                    "automation_storage_insecure",
                    f"{label} identity changed after open",
                )
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _validate_state_intent(
        state: dict[str, Any],
        *,
        job: str,
        request_id: str,
        run_id: str,
        as_of: str,
    ) -> None:
        if (
            state["job"] != job
            or state["request_id"] != request_id
            or state["run_id"] != run_id
            or state["as_of"] != as_of
        ):
            raise AutomationError(
                "automation_idempotency_conflict",
                "request_id already belongs to a different automation intent",
            )

    @staticmethod
    def _validate_state(state: Any) -> None:
        if not isinstance(state, dict) or set(state) != _RUN_STATE_FIELDS:
            raise AutomationError(
                "automation_state_corrupt", "automation run state fields are invalid"
            )
        if (
            state.get("schema_version") != "1.0"
            or state.get("job") not in _JOBS
            or state.get("phase") not in {"running", "finalizing", "completed"}
            or not isinstance(state.get("run_id"), str)
            or not state["run_id"]
            or not isinstance(state.get("request_id"), str)
            or _REQUEST_ID.fullmatch(state["request_id"]) is None
            or not isinstance(state.get("steps"), list)
            or not isinstance(state.get("results"), dict)
            or not _valid_notification_summary(state.get("notifications"))
        ):
            raise AutomationError(
                "automation_state_corrupt", "automation run state values are invalid"
            )
        for field in ("as_of", "started_at"):
            if state[field] != _utc_text(state[field], field):
                raise AutomationError(
                    "automation_state_corrupt", "run state timestamp is not canonical"
                )
        current_step = state["current_step"]
        if current_step is not None and (
            not isinstance(current_step, str) or not current_step
        ):
            raise AutomationError(
                "automation_state_corrupt", "run state current_step is invalid"
            )
        if state["phase"] == "running" and state["receipt"] is not None:
            raise AutomationError(
                "automation_state_corrupt", "running state cannot contain a receipt"
            )
        if state["phase"] in {"finalizing", "completed"} and not isinstance(
            state["receipt"], dict
        ):
            raise AutomationError(
                "automation_state_corrupt", "terminal state requires a receipt"
            )
        try:
            _validate_tree(state)
            json.dumps(state, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            raise AutomationError(
                "automation_state_corrupt", "automation state is not strict JSON"
            ) from exc

    def _read_receipts(self) -> list[dict[str, Any]]:
        if not os.path.lexists(self.automation_dir):
            return []
        self._assert_secure_directory(self.automation_dir, "automation directory")
        if not os.path.lexists(self.receipts_path):
            return []
        try:
            raw = self._read_secure_file(
                self.receipts_path,
                "automation receipt store",
                max_size=10 * 1024 * 1024,
            )
            if not raw:
                return []
            if not raw.endswith(b"\n"):
                raise ValueError("receipt file has an uncommitted trailing record")
            text = raw.decode("utf-8", errors="strict")
            rows: list[dict[str, Any]] = []
            for line in text[:-1].split("\n"):
                if not line:
                    raise ValueError("receipt file contains an empty audit record")
                row = _strict_json(line)
                self._validate_receipt(row)
                rows.append(row)
            return rows
        except AutomationError:
            raise
        except Exception as exc:
            raise AutomationError(
                "automation_receipt_corrupt",
                "automation receipt store is unreadable",
            ) from exc

    def _append_receipt(self, receipt: dict[str, Any]) -> None:
        self._prepare_directory()
        created = not os.path.lexists(self.receipts_path)
        payload = (
            json.dumps(
                receipt,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8", errors="strict")
        fd = self._open_secure_file(
            self.receipts_path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            "automation receipt store",
        )
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError("receipt append made no progress")
                remaining = remaining[written:]
            os.fsync(fd)
            self._assert_path_identity(fd, self.receipts_path, "automation receipt store")
            if created:
                self._fsync_directory(self.automation_dir, "automation directory")
        finally:
            os.close(fd)

    @staticmethod
    def _validate_receipt(receipt: Any) -> None:
        if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
            raise AutomationError(
                "automation_receipt_corrupt", "automation receipt fields are invalid"
            )
        if (
            receipt.get("schema_version") != "1.0"
            or receipt.get("job") not in _JOBS
            or receipt.get("status")
            not in {
                "available",
                "degraded",
                "failed",
            }
            or type(receipt.get("replayed")) is not bool
            or not isinstance(receipt.get("steps"), list)
            or not _valid_notification_summary(receipt.get("notifications"))
            or sum(
                receipt["notifications"][field]
                for field in _NOTIFICATION_FIELDS - {"planned"}
            )
            != receipt["notifications"]["planned"]
        ):
            raise AutomationError(
                "automation_receipt_corrupt", "automation receipt values are invalid"
            )
        for field in ("as_of", "started_at", "completed_at"):
            try:
                canonical = _utc_text(receipt.get(field), field)
            except AutomationError as exc:
                raise AutomationError(
                    "automation_receipt_corrupt",
                    "automation receipt timestamp is invalid",
                ) from exc
            if receipt[field] != canonical:
                raise AutomationError(
                    "automation_receipt_corrupt",
                    "automation receipt timestamp is not canonical",
                )
        try:
            _validate_tree(receipt)
            json.dumps(receipt, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            raise AutomationError(
                "automation_receipt_corrupt", "automation receipt is not strict JSON"
            ) from exc

    @staticmethod
    def _busy_receipt(
        *,
        job: str,
        request_id: str,
        run_id: str,
        as_of: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "run_id": run_id,
            "request_id": request_id,
            "job": job,
            "as_of": as_of,
            "started_at": as_of,
            "completed_at": as_of,
            "status": "skipped_busy",
            "replayed": False,
            "steps": [],
            "notifications": ResearchAutomation._notification_summary(),
        }
