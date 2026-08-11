from __future__ import annotations

import copy
import json
import math
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from hqa import (
    config,
    portfolio_risk,
    quant_cli,
    reviewlog,
    runlog,
    signals,
    weekly_review,
)
from hqa.hermes_artifacts import HermesArtifactFeed
from hqa.market_foresight import MarketForesightPublisher
from hqa.notifications import (
    NotificationOutbox,
    NotificationSendResult,
)
from hqa.opportunities import OpportunityTracker
from hqa.opportunity_observations import (
    OpportunityObservationError,
    OpportunityObservationSync,
)
from hqa.predictions import PredictionLedger
from hqa.research_automation import ResearchAutomation, build_automation_status


_NOTIFICATION_FIELDS = {
    "planned",
    "delivered",
    "queued",
    "fallback_persisted",
    "delivery_unknown",
    "suppressed",
}
_WEEKLY_SIGNAL_SCHEMA_FIELDS = {
    "signal_records",
    "opportunity_recorded_count",
    "opportunity_record_errors",
}
_LEGACY_SIGNAL_BASE_FIELDS = {
    "ts",
    "job",
    "scan_exit",
    "factor_exit",
    "n_candidates",
    "score_summary",
    "factor_lab",
    "thresholds",
    "has_signal",
    "signals",
}
_LEGACY_SIGNAL_EXTENDED_FIELDS = _LEGACY_SIGNAL_BASE_FIELDS | {
    "factor_lab_skipped",
    "mode",
    "run_date",
    "artifact_missing",
}


def _empty_notifications() -> dict[str, int]:
    return {
        "planned": 0,
        "delivered": 0,
        "queued": 0,
        "fallback_persisted": 0,
        "delivery_unknown": 0,
        "suppressed": 0,
    }


def _validate_notifications(summary: Any) -> dict[str, int]:
    if (
        not isinstance(summary, dict)
        or set(summary) != _NOTIFICATION_FIELDS
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in summary.values()
        )
        or sum(summary[field] for field in _NOTIFICATION_FIELDS - {"planned"})
        > summary["planned"]
    ):
        raise ValueError("notification summary is invalid")
    return copy.deepcopy(summary)


def _observed_utc(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("observed time must be timezone-aware text")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed time must be timezone-aware")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finite_optional_number(value: Any) -> bool:
    return value is None or (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _legacy_signal_success(row: Any) -> bool:
    if not isinstance(row, dict) or frozenset(row) not in {
        frozenset(_LEGACY_SIGNAL_BASE_FIELDS),
        frozenset(_LEGACY_SIGNAL_EXTENDED_FIELDS),
    }:
        return False
    try:
        if _observed_utc(row["ts"]) != row["ts"]:
            return False
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    if (
        row["job"] != "signal-watchdog"
        or any(
            isinstance(row[field], bool) or not isinstance(row[field], int)
            for field in ("scan_exit", "factor_exit", "n_candidates")
        )
        or row["n_candidates"] < 0
        or type(row["has_signal"]) is not bool
        or not isinstance(row["signals"], list)
        or any(not isinstance(signal, str) for signal in row["signals"])
        or row["has_signal"] != bool(row["signals"])
    ):
        return False
    factor_lab = row["factor_lab"]
    if (
        not isinstance(factor_lab, dict)
        or frozenset(factor_lab)
        not in {
            frozenset(),
            frozenset({"symbol", "cross_rows", "timing_rows"}),
        }
        or any(not isinstance(value, str) for value in factor_lab.values())
    ):
        return False
    thresholds = row["thresholds"]
    if (
        not isinstance(thresholds, dict)
        or set(thresholds) != {"min_score", "min_iv_rank"}
        or any(not _finite_optional_number(value) for value in thresholds.values())
    ):
        return False
    summary = row["score_summary"]
    if (
        not isinstance(summary, dict)
        or set(summary)
        != {"count", "iv_rank_known", "score_max", "score_p50", "score_p90"}
        or any(
            isinstance(summary[field], bool) or not isinstance(summary[field], int)
            for field in ("count", "iv_rank_known")
        )
        or not 0 <= summary["iv_rank_known"] <= summary["count"]
        or summary["count"] != row["n_candidates"]
        or any(
            not _finite_optional_number(summary[field])
            for field in ("score_max", "score_p50", "score_p90")
        )
    ):
        return False
    if set(row) == _LEGACY_SIGNAL_EXTENDED_FIELDS:
        run_date = row["run_date"]
        if (
            type(row["factor_lab_skipped"]) is not bool
            or type(row["artifact_missing"]) is not bool
            or not isinstance(row["mode"], str)
            or row["mode"] not in {"collect", "alert"}
            or (
                run_date is not None
                and (
                    not isinstance(run_date, str)
                    or re.fullmatch(r"\d{4}-\d{2}-\d{2}", run_date) is None
                )
            )
        ):
            return False
    return True


def _weekly_signal_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        if isinstance(row, dict) and set(row).intersection(
            _WEEKLY_SIGNAL_SCHEMA_FIELDS
        ):
            selected.append(row)
        elif not _legacy_signal_success(row):
            selected.append(row)
    return selected


@dataclass(frozen=True)
class Full9HPaths:
    log_dir: Path
    review_dir: Path
    prediction_dir: Path
    opportunity_dir: Path
    foresight_dir: Path
    scan_dir: Path
    thresholds_path: Path
    automation_dir: Path
    outbox_path: Path
    feed_path: Path
    weekly_projection_path: Path
    opportunity_projection_path: Path
    automation_projection_path: Path

    @classmethod
    def from_config(cls) -> "Full9HPaths":
        return cls(
            log_dir=config.LOG_DIR,
            review_dir=config.REVIEW_DIR,
            prediction_dir=config.PREDICTION_DIR,
            opportunity_dir=config.OPPORTUNITY_DIR,
            foresight_dir=config.MARKET_FORESIGHT_DIR,
            scan_dir=config.OPTIONS_SCAN_DIR,
            thresholds_path=config.SIGNAL_THRESHOLDS_PATH,
            automation_dir=config.AUTOMATION_DIR,
            outbox_path=config.NOTIFICATION_OUTBOX_PATH,
            feed_path=config.HERMES_ARTIFACT_FEED_PATH,
            weekly_projection_path=config.WEEKLY_REVIEW_PROJECTION_PATH,
            opportunity_projection_path=config.OPPORTUNITY_SUMMARY_PROJECTION_PATH,
            automation_projection_path=config.AUTOMATION_STATUS_PROJECTION_PATH,
        )


def _strict_json(text: str) -> Any:
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
        text,
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], bool]:
    if not path.exists():
        return [], False
    rows: list[dict[str, Any]] = []
    invalid = False
    try:
        raw = path.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            return [], True
        text = raw.decode("utf-8", errors="strict")
        for line in text[:-1].split("\n"):
            if not line:
                invalid = True
                continue
            try:
                row = _strict_json(line)
                if not isinstance(row, dict):
                    raise ValueError("row is not an object")
                rows.append(row)
            except (TypeError, ValueError):
                invalid = True
    except (OSError, UnicodeError):
        return [], True
    return rows, invalid


def hermes_send_adapter(
    target: str,
    message: str,
    timeout_seconds: float,
) -> NotificationSendResult:
    """No-LLM Hermes transport with an explicit subprocess deadline."""

    try:
        result = subprocess.run(
            ["hermes", "send", "--json", "--to", target, message],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return NotificationSendResult.known_failure("remote_unavailable")
    except subprocess.TimeoutExpired:
        return NotificationSendResult.unknown()
    except (OSError, subprocess.SubprocessError):
        return NotificationSendResult.unknown()
    if result.returncode != 0:
        return NotificationSendResult.known_failure("remote_transport_failed")
    try:
        document = _strict_json(result.stdout)
    except (TypeError, ValueError):
        return NotificationSendResult.unknown()
    if not isinstance(document, (dict, list)):
        return NotificationSendResult.unknown()
    if isinstance(document, dict) and document.get("error"):
        return NotificationSendResult.known_failure("remote_rejected")
    return NotificationSendResult.delivered()


class Full9HServices:
    """Concrete read-only domain adapters hidden behind ResearchAutomation."""

    def __init__(
        self,
        paths: Full9HPaths,
        *,
        now: Callable[[], str] = runlog.utc_now_iso,
        run_snapshot: Callable[
            [str], tuple[int, str]
        ] = quant_cli.run_paper_account_snapshot,
        run_history: Callable[
            [list[str], str, str], tuple[int, str]
        ] = quant_cli.run_historical_prices,
        run_observations: Callable[..., tuple[int, str]] = (
            quant_cli.run_paper_strategy_observations
        ),
        send_adapter: Callable[
            [str, str, float], NotificationSendResult
        ] = hermes_send_adapter,
        notification_target: str = "local",
    ) -> None:
        self.paths = paths
        self._now = now
        self._run_snapshot = run_snapshot
        self._run_history = run_history
        self._send_adapter = send_adapter
        self.notification_target = notification_target
        self.prediction_ledger = PredictionLedger(
            paths.prediction_dir,
            run_history=run_history,
            now=now,
        )
        self.opportunity_tracker = OpportunityTracker(paths.opportunity_dir, now=now)
        self._observation_sync = OpportunityObservationSync(
            paths.opportunity_dir,
            run_observations=run_observations,
            now=now,
        )
        self.foresight_publisher = MarketForesightPublisher(
            paths.foresight_dir,
            prediction_ledger=self.prediction_ledger,
        )
        self.outbox = NotificationOutbox(paths.outbox_path, now=now)

    def signal_catchup(self, as_of: str) -> dict[str, Any]:
        as_of_date = (
            datetime.fromisoformat(
                as_of[:-1] + "+00:00" if as_of.endswith("Z") else as_of
            )
            .astimezone(timezone.utc)
            .date()
        )
        available: list[str] = []
        if self.paths.scan_dir.exists():
            for path in self.paths.scan_dir.glob("*.jsonl"):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.jsonl", path.name) is None:
                    continue
                source_date = path.stem
                try:
                    parsed = datetime.strptime(source_date, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if parsed <= as_of_date:
                    available.append(source_date)
        # Newest first. Empty/torn scan files must not fail the whole daily_close
        # cycle when an older readable artifact is available.
        skipped_unreadable: list[str] = []
        for source_date in sorted(available, reverse=True):
            try:
                candidates = signals.load_scan_candidates(
                    self.paths.scan_dir, source_date
                )
            except ValueError:
                skipped_unreadable.append(source_date)
                continue
            thresholds = config.load_signal_thresholds(self.paths.thresholds_path)
            records = signals.build_signal_records(
                candidates,
                min_score=thresholds["min_score"],
                min_iv_rank=thresholds["min_iv_rank"],
                source_date=source_date,
                observed_at=as_of,
            )
            for record in records:
                self.opportunity_tracker.record(
                    {
                        "event": "signal_observed",
                        "request_id": f"options-scan:{record['signal_id']}",
                        "payload": record,
                    }
                )
            result: dict[str, Any] = {
                "status": "available" if records else "empty",
                "source_date": source_date,
                "candidate_count": len(candidates),
                "signal_count": len(records),
            }
            if skipped_unreadable:
                result["skipped_unreadable_source_dates"] = skipped_unreadable
            return result
        empty: dict[str, Any] = {
            "status": "empty",
            "source_date": None,
            "candidate_count": 0,
            "signal_count": 0,
        }
        if skipped_unreadable:
            empty["skipped_unreadable_source_dates"] = skipped_unreadable
        return empty

    def portfolio_risk(self, as_of: str) -> dict[str, Any]:
        log_path = self.paths.log_dir / "portfolio_risk.jsonl"
        portfolio_risk.run(
            self._run_snapshot,
            self._now,
            log_path,
            run_history=self._run_history,
        )
        rows, invalid = _read_jsonl(log_path)
        if invalid or not rows:
            return {"status": "degraded", "artifact_count": 0}
        status = rows[-1].get("status")
        return {
            "status": (
                "available" if status in {"available", "not_applicable"} else "degraded"
            ),
            "artifact_count": 1,
        }

    def prediction_reconcile(self, as_of: str) -> dict[str, Any]:
        return self.prediction_ledger.reconcile_due(as_of=as_of, limit=5)

    def _opportunities(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            page = self.opportunity_tracker.list(limit=200, cursor=cursor)
            rows.extend(page)
            if len(page) < 200:
                return rows
            cursor = page[-1]["signal_id"]

    def opportunity_coverage(self, as_of: str) -> dict[str, Any]:
        eligible = []
        for state in self._opportunities():
            eligibility = state["signal"]["eligibility"]
            deadline = eligibility.get("deadline_at")
            if (
                eligibility.get("status") == "eligible"
                and isinstance(deadline, str)
                and as_of > deadline
                and state["resolution"]
                not in {
                    "acted",
                    "action_failed",
                    "declined",
                    "missed",
                    "not_actionable",
                    "unknown",
                }
            ):
                eligible.append(state)
        results: list[dict[str, Any]] = []
        degraded = False
        for state in eligible[:5]:
            signal = state["signal"]
            try:
                updated = self._observation_sync.sync_coverage(
                    state["signal_id"],
                    covered_through=as_of,
                    from_date=signal["source"]["date"],
                    to_date=as_of[:10],
                    limit=200,
                )
                results.append(
                    {
                        "signal_id": state["signal_id"],
                        "status": updated["resolution"],
                    }
                )
            except OpportunityObservationError as exc:
                degraded = True
                results.append(
                    {
                        "signal_id": state["signal_id"],
                        "status": "unavailable",
                        "reason_code": exc.code,
                    }
                )
        return {
            "status": "degraded" if degraded else ("available" if results else "empty"),
            "due_count": len(eligible),
            "processed_count": len(results),
            "remaining_due_count": max(0, len(eligible) - len(results)),
            "results": results,
        }

    def opportunity_reconcile(self, as_of: str) -> dict[str, Any]:
        return self.opportunity_tracker.reconcile_due(as_of=as_of, limit=50)

    def weekly_projection(self, as_of: str) -> dict[str, Any]:
        safety, safety_invalid = _read_jsonl(
            self.paths.log_dir / "doctor_watchdog.jsonl"
        )
        signal_rows, signal_invalid = _read_jsonl(
            self.paths.log_dir / "signal_watchdog.jsonl"
        )
        signal_rows = _weekly_signal_rows(signal_rows)
        try:
            reviews: list[dict[str, Any]] = reviewlog.list_entries(
                self.paths.review_dir
            )
        except Exception:
            reviews = [{}]
        try:
            predictions: list[dict[str, Any]] = self.prediction_ledger.list()
        except Exception:
            predictions = [{}]
        try:
            opportunities = self._opportunities()
        except Exception:
            opportunities = [{}]
        if safety_invalid:
            safety.append({})
        if signal_invalid:
            signal_rows.append({})
        artifact = weekly_review.build_weekly_artifact(
            as_of=as_of,
            reviews=reviews,
            safety_runs=safety,
            signal_runs=signal_rows,
            predictions=predictions,
            opportunities=opportunities,
        )
        weekly_review.write_projection(self.paths.weekly_projection_path, artifact)
        return {
            "status": artifact["status"],
            "weekly_count": 1,
            "artifact": artifact,
        }

    def opportunity_projection(self, as_of: str) -> dict[str, Any]:
        try:
            opportunities = self._opportunities()
        except Exception:
            opportunities = [{}]
        artifact = weekly_review.build_opportunity_summary(
            as_of=as_of,
            opportunities=opportunities,
        )
        weekly_review.write_projection(
            self.paths.opportunity_projection_path,
            artifact,
        )
        return {
            "status": artifact["status"],
            "opportunity_count": artifact["data"]["total_count"],
            "artifact": artifact,
        }

    def automation_projection(
        self,
        job: str,
        as_of: str,
        run_id: str,
        steps: list[dict[str, Any]],
        notifications: dict[str, int],
    ) -> dict[str, Any]:
        observed_at = _observed_utc(self._now())
        reader = ResearchAutomation(
            self.paths.automation_dir,
            services=self,
            now=self._now,
            notification_target=self.notification_target,
        )
        receipts = [
            receipt for receipt in reader.list_receipts() if receipt["run_id"] != run_id
        ]
        provisional_notifications = _validate_notifications(notifications)
        provisional_status = "available"
        if any(
            step.get("status")
            in {"degraded", "failed", "retryable", "outcome_unknown"}
            for step in steps
        ) or any(
            provisional_notifications[field] > 0
            for field in {"fallback_persisted", "delivery_unknown"}
        ):
            provisional_status = "degraded"
        provisional = {
            "schema_version": "1.0",
            "run_id": run_id,
            "request_id": f"provisional:{run_id}",
            "job": job,
            "as_of": as_of,
            "started_at": observed_at,
            "completed_at": observed_at,
            "status": provisional_status,
            "replayed": False,
            "steps": steps,
            "notifications": provisional_notifications,
        }
        receipts.append(provisional)
        receipts = self._overlay_notification_truth(receipts)
        prior_overall = None
        if self.paths.automation_projection_path.exists():
            try:
                prior = _strict_json(
                    self.paths.automation_projection_path.read_text(encoding="utf-8")
                )
                prior_overall = prior["data"]["overall_status"]
            except (OSError, TypeError, ValueError, KeyError):
                prior_overall = None
        artifact = build_automation_status(as_of=observed_at, receipts=receipts)
        current_overall = artifact["data"]["overall_status"]
        transition = None
        if prior_overall != current_overall:
            transition = "recovered" if current_overall == "fresh" else "degraded"
        weekly_review.write_projection(
            self.paths.automation_projection_path,
            artifact,
        )
        return {
            # A monitor that accurately reports degradation completed its job.
            "status": "available",
            "overall_status": current_overall,
            "transition": transition,
            "artifact": artifact,
        }

    def _overlay_notification_truth(
        self,
        receipts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        notifications = self.outbox.list()
        overlaid = copy.deepcopy(receipts)
        for receipt in overlaid:
            prefix = f"{receipt['run_id']}:"
            matching = [
                notification
                for notification in notifications
                if notification.get("request_id", "").startswith(prefix)
            ]
            if not matching:
                continue
            summary = _empty_notifications()
            summary["planned"] = len(matching)
            for notification in matching:
                status = notification["status"]
                if status == "delivered":
                    summary["delivered"] += 1
                elif status in {"pending", "retryable"}:
                    summary["queued"] += 1
                elif status == "dead_letter":
                    summary["fallback_persisted"] += 1
                else:
                    summary["delivery_unknown"] += 1
            receipt["notifications"] = summary
        return overlaid

    def feed_refresh(self, as_of: str) -> dict[str, Any]:
        observed_at = _observed_utc(self._now())
        feed = HermesArtifactFeed(
            self.paths.feed_path,
            portfolio_risk_path=self.paths.log_dir / "portfolio_risk.jsonl",
            prediction_ledger=self.prediction_ledger,
            foresight_publisher=self.foresight_publisher,
            weekly_review_path=self.paths.weekly_projection_path,
            opportunity_summary_path=self.paths.opportunity_projection_path,
            automation_status_path=self.paths.automation_projection_path,
            now=lambda: observed_at,
        )
        return feed.rebuild(limit=50)

    def notification_enqueue(self, request: dict[str, Any]) -> dict[str, Any]:
        receipt = self.outbox.enqueue(request)
        status = receipt["status"]
        if status == "delivered":
            state = "delivered"
        elif status in {"pending", "retryable"}:
            state = "queued"
        elif status == "dead_letter":
            state = "fallback_persisted"
        else:
            state = "delivery_unknown"
        return {"state": state, "notification_id": receipt["notification_id"]}

    def notification_drain(self, as_of: str) -> dict[str, Any]:
        return self.outbox.drain(self._send_adapter, limit=5)
