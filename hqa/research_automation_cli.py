from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from hqa import config, runlog
from hqa.research_automation import AutomationError, ResearchAutomation
from hqa.research_automation_runtime import Full9HPaths, Full9HServices


_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_NOTIFICATION_DRAIN_MINUTES = (7, 22, 37, 52)


class _CliArgumentError(ValueError):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CliArgumentError(message)


def _emit(document: Any) -> None:
    serialized = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    serialized.encode("utf-8", errors="strict")
    sys.stdout.write(serialized + "\n")


def _parse_as_of(as_of: str) -> datetime:
    if not isinstance(as_of, str) or not as_of:
        raise AutomationError("automation_invalid_request", "as_of is required")
    text = as_of[:-1] + "+00:00" if as_of.endswith("Z") else as_of
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AutomationError(
            "automation_invalid_request", "as_of must be timezone-aware"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AutomationError(
            "automation_invalid_request", "as_of must be timezone-aware"
        )
    return parsed.astimezone(_LOCAL_TIMEZONE)


def _notification_drain_slot(local: datetime) -> datetime:
    eligible_minutes = [
        minute for minute in _NOTIFICATION_DRAIN_MINUTES if minute <= local.minute
    ]
    if eligible_minutes:
        return local.replace(
            minute=max(eligible_minutes),
            second=0,
            microsecond=0,
        )
    previous_hour = local - timedelta(hours=1)
    return previous_hour.replace(
        minute=_NOTIFICATION_DRAIN_MINUTES[-1],
        second=0,
        microsecond=0,
    )


def request_id_for(job: str, as_of: str) -> str:
    local = _parse_as_of(as_of)
    if job == "daily_close":
        slot = local.strftime("%Y-%m-%d")
    elif job == "weekly":
        year, week, _ = local.isocalendar()
        slot = f"{year:04d}-W{week:02d}"
    elif job == "freshness":
        hour = local.hour - local.hour % 2
        slot = f"{local:%Y-%m-%d}T{hour:02d}"
    elif job == "notification_drain":
        local = _notification_drain_slot(local)
        slot = f"{local:%Y-%m-%dT%H:%M}"
    else:
        raise AutomationError("automation_invalid_request", "job is invalid")
    return f"{job}:{slot}"


def _automatic_as_of(job: str, observed_at: str) -> str:
    observed = _parse_as_of(observed_at)
    local = observed
    if job == "daily_close":
        local = local.replace(hour=8, minute=15, second=0, microsecond=0)
        while local > observed or local.isoweekday() not in range(2, 7):
            local -= timedelta(days=1)
    elif job == "weekly":
        local = local - timedelta(days=local.isoweekday() % 7)
        local = local.replace(hour=9, minute=0, second=0, microsecond=0)
        if local > observed:
            local -= timedelta(days=7)
    elif job == "freshness":
        hour = local.hour - local.hour % 2
        local = local.replace(hour=hour, minute=17, second=0, microsecond=0)
        if local > observed:
            local -= timedelta(hours=2)
    elif job == "notification_drain":
        local = _notification_drain_slot(local)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="hqa-full-9h")
    parser.add_argument(
        "job",
        choices=("daily_close", "freshness", "weekly", "notification_drain"),
    )
    parser.add_argument("--as-of")
    parser.add_argument("--request-id")
    return parser


def _runtime() -> ResearchAutomation:
    paths = Full9HPaths.from_config()
    services = Full9HServices(
        paths,
        now=runlog.utc_now_iso,
        notification_target=config.FULL9H_NOTIFY_TARGET,
    )
    return ResearchAutomation(
        paths.automation_dir,
        services=services,
        now=runlog.utc_now_iso,
        notification_target=config.FULL9H_NOTIFY_TARGET,
    )


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _CliArgumentError as exc:
        _emit(
            {
                "error": {
                    "code": "automation_invalid_arguments",
                    "message": str(exc),
                    "retryable": False,
                }
            }
        )
        return 2
    observed_at = args.as_of or runlog.utc_now_iso()
    as_of = (
        _automatic_as_of(args.job, observed_at)
        if args.as_of is None and args.request_id is None
        else observed_at
    )
    try:
        request_id = args.request_id or request_id_for(args.job, as_of)
        receipt = _runtime().run(
            job=args.job,
            request_id=request_id,
            as_of=as_of,
        )
    except AutomationError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            }
        )
        return (
            2
            if exc.code
            in {
                "automation_invalid_request",
                "automation_idempotency_conflict",
            }
            else 1
        )
    except Exception as exc:
        _emit(
            {
                "error": {
                    "code": "automation_runtime_failed",
                    "message": f"full-9H runtime failed: {type(exc).__name__}",
                    "retryable": True,
                }
            }
        )
        return 1
    _emit(receipt)
    return 0 if receipt.get("status") == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
