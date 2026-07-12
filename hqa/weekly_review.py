from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from hqa import config, reviewlog, runlog


_RESOLUTIONS = (
    "open",
    "deferred",
    "acted",
    "action_failed",
    "declined",
    "missed",
    "expired_coverage_unknown",
    "not_actionable",
    "unknown",
)
_MISSED_REASONS = ("no_decision", "act_without_action", "defer_expired")
_DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _utc_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be timezone-aware text")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: Any) -> str:
    return _utc_datetime(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bounded_reason_codes(values: set[str]) -> list[str]:
    return sorted(values)[:20]


def _window(as_of: str) -> tuple[datetime, datetime, str, str, str]:
    end = _utc_datetime(as_of)
    start = end - timedelta(days=7)
    local_end = end.astimezone(_DISPLAY_TIMEZONE)
    year, week, _ = local_end.isocalendar()
    return (
        start,
        end,
        start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        f"{year:04d}-W{week:02d}",
    )


def _row_in_window(
    value: Any,
    *,
    start: datetime,
    end: datetime,
) -> bool:
    parsed = _utc_datetime(value)
    return start <= parsed < end


def _artifact(
    *,
    kind: str,
    generated_at: str,
    reason_codes: set[str],
    data: dict[str, Any],
) -> dict[str, Any]:
    reasons = _bounded_reason_codes(reason_codes)
    if kind == "weekly_review":
        data["limitations"] = reasons
    document = {
        "schema_version": "1.0",
        "kind": kind,
        "generated_at": generated_at,
        "status": "degraded" if reasons else "available",
        "reason_codes": reasons,
        "data": data,
    }
    json.dumps(document, ensure_ascii=False, allow_nan=False)
    return document


def build_weekly_artifact(
    *,
    as_of: str,
    reviews: list[dict[str, Any]],
    safety_runs: list[dict[str, Any]],
    signal_runs: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the strict, bounded seven-day weekly projection.

    Inputs are folded public states or source rows. A malformed row degrades
    only its source and is excluded; it never leaks an exception or a NaN into
    the cross-repository feed.
    """

    start, end, start_text, end_text, week_id = _window(as_of)
    reasons: set[str] = set()
    review_draft_count = 0
    review_confirmed_count = 0
    for row in reviews:
        try:
            if not isinstance(row, dict) or not _row_in_window(
                row.get("ts"), start=start, end=end
            ):
                if not isinstance(row, dict):
                    raise ValueError("review row is not an object")
                continue
            status = row.get("status")
            if status == "draft":
                review_draft_count += 1
            elif status == "confirmed":
                review_confirmed_count += 1
            else:
                raise ValueError("review status is invalid")
        except (TypeError, ValueError, OverflowError, OSError):
            reasons.add("weekly_review_source_invalid")

    safety_alert_count = 0
    for row in safety_runs:
        try:
            if not isinstance(row, dict) or not _row_in_window(
                row.get("ts"), start=start, end=end
            ):
                if not isinstance(row, dict):
                    raise ValueError("safety row is not an object")
                continue
            if type(row.get("alert")) is not bool:
                raise ValueError("safety alert is invalid")
            safety_alert_count += int(row["alert"])
        except (TypeError, ValueError, OverflowError, OSError):
            reasons.add("weekly_safety_source_invalid")

    signal_ids: set[str] = set()
    for row in signal_runs:
        try:
            if not isinstance(row, dict) or not _row_in_window(
                row.get("ts"), start=start, end=end
            ):
                if not isinstance(row, dict):
                    raise ValueError("signal row is not an object")
                continue
            records = row.get("signal_records")
            if not isinstance(records, list):
                raise ValueError("signal records are invalid")
            for record in records:
                signal_id = record.get("signal_id") if isinstance(record, dict) else None
                if not isinstance(signal_id, str) or not signal_id:
                    raise ValueError("signal identity is invalid")
                signal_ids.add(signal_id)
        except (TypeError, ValueError, OverflowError, OSError):
            reasons.add("weekly_signal_source_invalid")

    prediction_created_count = 0
    scored_briers: list[float] = []
    prediction_hit_count = 0
    for row in predictions:
        try:
            if not isinstance(row, dict):
                raise ValueError("prediction row is not an object")
            if _row_in_window(row.get("created_at"), start=start, end=end):
                prediction_created_count += 1
            if row.get("status") == "scored" and _row_in_window(
                row.get("scored_at"), start=start, end=end
            ):
                correct = row.get("direction_correct")
                brier = row.get("direction_brier")
                if (
                    type(correct) is not bool
                    or isinstance(brier, bool)
                    or not isinstance(brier, (int, float))
                    or not math.isfinite(float(brier))
                    or not 0 <= float(brier) <= 1
                ):
                    raise ValueError("prediction score is invalid")
                prediction_hit_count += int(correct)
                scored_briers.append(float(brier))
        except (TypeError, ValueError, OverflowError, OSError):
            reasons.add("weekly_prediction_source_invalid")

    opportunity_observed_count = 0
    opportunity_missed_count = 0
    opportunity_coverage_unknown_count = 0
    for row in opportunities:
        try:
            if not isinstance(row, dict):
                raise ValueError("opportunity row is not an object")
            signal = row.get("signal")
            if not isinstance(signal, dict):
                raise ValueError("opportunity signal is invalid")
            observed_in_window = _row_in_window(
                signal.get("observed_at"), start=start, end=end
            )
            if observed_in_window:
                opportunity_observed_count += 1
                signal_id = row.get("signal_id")
                if not isinstance(signal_id, str) or not signal_id:
                    raise ValueError("opportunity identity is invalid")
                signal_ids.add(signal_id)
                if row.get("resolution") == "expired_coverage_unknown":
                    opportunity_coverage_unknown_count += 1
            missed = row.get("missed_assessment")
            if missed is not None:
                if not isinstance(missed, dict):
                    raise ValueError("missed assessment is invalid")
                if _row_in_window(missed.get("assessed_at"), start=start, end=end):
                    if missed.get("reason_code") not in _MISSED_REASONS:
                        raise ValueError("missed reason is invalid")
                    opportunity_missed_count += 1
        except (TypeError, ValueError, OverflowError, OSError):
            reasons.add("weekly_opportunity_source_invalid")

    data = {
        "week_id": week_id,
        "period_start": start_text,
        "period_end": end_text,
        "safety_alert_count": safety_alert_count,
        "unique_signal_count": len(signal_ids),
        "review_draft_count": review_draft_count,
        "review_confirmed_count": review_confirmed_count,
        "prediction_created_count": prediction_created_count,
        "prediction_scored_count": len(scored_briers),
        "prediction_hit_count": prediction_hit_count,
        "mean_direction_brier": (
            None if not scored_briers else sum(scored_briers) / len(scored_briers)
        ),
        "opportunity_observed_count": opportunity_observed_count,
        "opportunity_missed_count": opportunity_missed_count,
        "opportunity_coverage_unknown_count": opportunity_coverage_unknown_count,
        "limitations": [],
        "proposal_only": True,
        "trading_allowed": False,
    }
    return _artifact(
        kind="weekly_review",
        generated_at=end_text,
        reason_codes=reasons,
        data=data,
    )


def build_opportunity_summary(
    *,
    as_of: str,
    opportunities: list[dict[str, Any]],
) -> dict[str, Any]:
    start, end, start_text, end_text, _ = _window(as_of)
    reasons: set[str] = set()
    resolution_counts = {resolution: 0 for resolution in _RESOLUTIONS}
    miss_reason_counts = {reason: 0 for reason in _MISSED_REASONS}
    for row in opportunities:
        try:
            if not isinstance(row, dict):
                raise ValueError("opportunity row is not an object")
            signal = row.get("signal")
            if not isinstance(signal, dict) or not _row_in_window(
                signal.get("observed_at"), start=start, end=end
            ):
                if not isinstance(signal, dict):
                    raise ValueError("opportunity signal is invalid")
                continue
            resolution = row.get("resolution")
            if resolution not in resolution_counts:
                raise ValueError("opportunity resolution is invalid")
            missed = row.get("missed_assessment")
            if resolution == "missed":
                if not isinstance(missed, dict) or missed.get("reason_code") not in miss_reason_counts:
                    raise ValueError("missed opportunity reason is invalid")
                miss_reason_counts[missed["reason_code"]] += 1
            elif missed is not None:
                raise ValueError("non-missed opportunity has a missed assessment")
            resolution_counts[resolution] += 1
        except (TypeError, ValueError, OverflowError, OSError):
            reasons.add("opportunity_summary_source_invalid")
    data = {
        "window_start": start_text,
        "window_end": end_text,
        "total_count": sum(resolution_counts.values()),
        "resolution_counts": resolution_counts,
        "miss_reason_counts": miss_reason_counts,
        "proposal_only": True,
        "trading_allowed": False,
    }
    return _artifact(
        kind="opportunity_summary",
        generated_at=end_text,
        reason_codes=reasons,
        data=data,
    )


def write_projection(path: Path, document: dict[str, Any]) -> None:
    serialized = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload = (serialized + "\n").encode("utf-8", errors="strict")
    path = Path(path)
    directory_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not directory_existed:
        os.chmod(path.parent, 0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def load_runlog(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _since_iso(now: str, days: int) -> str:
    now_dt = _parse_ts(now)
    if now_dt is None:
        return now
    return (now_dt - timedelta(days=days)).isoformat().replace("+00:00", "Z")


def _filter_since(rows: list[dict[str, Any]], since: str) -> list[dict[str, Any]]:
    since_dt = _parse_ts(since)
    if since_dt is None:
        return rows
    filtered: list[dict[str, Any]] = []
    for row in rows:
        row_dt = _parse_ts(str(row.get("ts", "")))
        if row_dt is None or row_dt >= since_dt:
            filtered.append(row)
    return filtered


def build_report(alerts: list[dict], signals_fired: list[dict], reviews: list[dict], ts: str) -> str:
    lines = [
        f"[HQA] Weekly review {ts}",
        f"- safety alerts: {len(alerts)}",
        f"- signals fired: {len(signals_fired)}",
        f"- review entries: {len(reviews)}",
    ]
    for r in reviews:
        lines.append(f"  · {r.get('id', '?')} [{r.get('status', '?')}] {r.get('event', '')} → next: {r.get('next_rule', '')}")
    lines.append("Scope: read-only weekly summary. Proposal-only.")
    return "\n".join(lines)


def run(review_dir: Path, log_dir: Path, now_iso: Callable[[], str], days: int = 7) -> str:
    ts = now_iso()
    since = _since_iso(ts, days)
    reviews = reviewlog.list_entries(review_dir, since=since)
    watchdog = _filter_since(load_runlog(log_dir / "doctor_watchdog.jsonl"), since)
    signal = _filter_since(load_runlog(log_dir / "signal_watchdog.jsonl"), since)
    alerts = [r for r in watchdog if r.get("alert")]
    signals_fired = [r for r in signal if r.get("has_signal")]
    return build_report(alerts, signals_fired, reviews, ts)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA weekly review (read-only, proposal-only)")
    parser.add_argument("--review-dir", default=str(config.REVIEW_DIR))
    parser.add_argument("--log-dir", default=str(config.LOG_DIR))
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        report = run(Path(args.review_dir), Path(args.log_dir), runlog.utc_now_iso, days=args.days)
    except Exception as exc:
        ts = runlog.utc_now_iso()
        print(f"[HQA] Weekly review {ts}: FAILED ({exc!r})")
        return 0
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
