from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from hqa import config, quant_cli, runlog, signals
from hqa.opportunities import OpportunityLedgerError, OpportunityTracker
from hqa.opportunity_observations import (
    OpportunityObservationError,
    OpportunityObservationSync,
    parse_platform_observations,
)


class _CliArgumentError(ValueError):
    pass


class _OpportunityCliError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        exit_code: int,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.exit_code = exit_code


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


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="hqa-opportunity")
    sub = parser.add_subparsers(dest="command", required=True)
    sync_signals = sub.add_parser("sync-signals")
    sync_signals.add_argument("--date", required=True)
    sync_signals.add_argument("--scan-dir", default=str(config.OPTIONS_SCAN_DIR))
    sync_signals.add_argument(
        "--thresholds",
        default=str(config.SIGNAL_THRESHOLDS_PATH),
    )
    sync_signals.add_argument(
        "--opportunity-dir",
        default=str(config.OPPORTUNITY_DIR),
    )
    decide = sub.add_parser("decide")
    decide.add_argument("--signal-id", required=True)
    decide.add_argument(
        "--decision",
        required=True,
        choices=("act", "decline", "defer"),
    )
    decide.add_argument("--actor", required=True)
    decide.add_argument("--reason", required=True)
    decide.add_argument("--decided-at")
    decide.add_argument("--revisit-at")
    decide.add_argument("--request-id", required=True)
    decide.add_argument(
        "--opportunity-dir",
        default=str(config.OPPORTUNITY_DIR),
    )
    list_opportunities = sub.add_parser("list")
    list_opportunities.add_argument("--status")
    list_opportunities.add_argument("--since")
    list_opportunities.add_argument("--limit", type=int, default=100)
    list_opportunities.add_argument("--cursor")
    list_opportunities.add_argument(
        "--opportunity-dir",
        default=str(config.OPPORTUNITY_DIR),
    )
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--as-of")
    reconcile.add_argument("--limit", type=int, default=50)
    reconcile.add_argument("--cursor")
    reconcile.add_argument(
        "--opportunity-dir",
        default=str(config.OPPORTUNITY_DIR),
    )
    record_action = sub.add_parser("record-action")
    record_action.add_argument("--signal-id", required=True)
    record_action.add_argument("--platform-signal-id", required=True)
    record_action.add_argument("--platform-execution-id", required=True)
    record_action.add_argument("--actor", required=True)
    record_action.add_argument("--limit", type=int, default=200)
    record_action.add_argument(
        "--opportunity-dir",
        default=str(config.OPPORTUNITY_DIR),
    )
    sync_actions = sub.add_parser("sync-actions")
    sync_actions.add_argument("--signal-id", required=True)
    sync_actions.add_argument("--from-date")
    sync_actions.add_argument("--to-date")
    sync_actions.add_argument("--covered-through", required=True)
    sync_actions.add_argument("--limit", type=int, default=200)
    sync_actions.add_argument(
        "--opportunity-dir",
        default=str(config.OPPORTUNITY_DIR),
    )
    return parser


def _sync_signals(args: argparse.Namespace) -> dict[str, Any]:
    try:
        candidates = signals.load_scan_candidates(Path(args.scan_dir), args.date)
        thresholds = config.load_signal_thresholds(Path(args.thresholds))
        observed_at = runlog.utc_now_iso()
        records = signals.build_signal_records(
            candidates,
            min_score=thresholds["min_score"],
            min_iv_rank=thresholds["min_iv_rank"],
            source_date=args.date,
            observed_at=observed_at,
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise _OpportunityCliError(
            "opportunity_signal_source_unavailable",
            "signal artifact could not be read",
            retryable=True,
            exit_code=1,
        ) from exc
    tracker = OpportunityTracker(Path(args.opportunity_dir), now=runlog.utc_now_iso)
    states = [
        tracker.record(
            {
                "event": "signal_observed",
                "request_id": f"options-scan:{record['signal_id']}",
                "payload": record,
            }
        )
        for record in records
    ]
    return {
        "schema_version": "1.0",
        "status": "available" if records else "empty",
        "source_date": args.date,
        "candidate_count": len(candidates),
        "signal_count": len(records),
        "signals": states,
    }


def _decide(args: argparse.Namespace) -> dict[str, Any]:
    tracker = OpportunityTracker(Path(args.opportunity_dir), now=runlog.utc_now_iso)
    return tracker.record(
        {
            "event": "decision_recorded",
            "request_id": args.request_id,
            "payload": {
                "signal_id": args.signal_id,
                "decision": args.decision,
                "actor": args.actor,
                "reason": args.reason,
                "decided_at": args.decided_at or runlog.utc_now_iso(),
                "revisit_at": args.revisit_at,
            },
        }
    )


def _list(args: argparse.Namespace) -> list[dict[str, Any]]:
    tracker = OpportunityTracker(Path(args.opportunity_dir), now=runlog.utc_now_iso)
    return tracker.list(
        status=args.status,
        since=args.since,
        limit=args.limit,
        cursor=args.cursor,
    )


def _reconcile(args: argparse.Namespace) -> dict[str, Any]:
    tracker = OpportunityTracker(Path(args.opportunity_dir), now=runlog.utc_now_iso)
    return tracker.reconcile_due(
        as_of=args.as_of,
        limit=args.limit,
        cursor=args.cursor,
    )


def _parse_platform_observations(output: str) -> dict[str, Any]:
    try:
        return parse_platform_observations(output)
    except OpportunityObservationError as exc:
        raise _OpportunityCliError(
            exc.code,
            exc.message,
            retryable=exc.retryable,
            exit_code=1,
        ) from exc


def _record_action(args: argparse.Namespace) -> dict[str, Any]:
    sync = OpportunityObservationSync(
        Path(args.opportunity_dir),
        run_observations=quant_cli.run_paper_strategy_observations,
        now=runlog.utc_now_iso,
    )
    return sync.record_action(
        args.signal_id,
        platform_signal_id=args.platform_signal_id,
        platform_execution_id=args.platform_execution_id,
        actor=args.actor,
        limit=args.limit,
    )


def _sync_actions(args: argparse.Namespace) -> dict[str, Any]:
    sync = OpportunityObservationSync(
        Path(args.opportunity_dir),
        run_observations=quant_cli.run_paper_strategy_observations,
        now=runlog.utc_now_iso,
    )
    return sync.sync_coverage(
        args.signal_id,
        covered_through=args.covered_through,
        from_date=args.from_date,
        to_date=args.to_date,
        limit=args.limit,
    )


def _execute(args: argparse.Namespace) -> Any:
    if args.command == "sync-signals":
        return _sync_signals(args)
    if args.command == "decide":
        return _decide(args)
    if args.command == "list":
        return _list(args)
    if args.command == "reconcile":
        return _reconcile(args)
    if args.command == "record-action":
        return _record_action(args)
    if args.command == "sync-actions":
        return _sync_actions(args)
    raise AssertionError(f"unsupported command: {args.command}")


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _CliArgumentError as exc:
        _emit(
            {
                "error": {
                    "code": "opportunity_invalid_arguments",
                    "message": str(exc),
                    "retryable": False,
                }
            }
        )
        return 2
    try:
        document = _execute(args)
    except OpportunityLedgerError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            }
        )
        if exc.code in {
            "opportunity_invalid_request",
            "opportunity_idempotency_conflict",
        }:
            return 2
        return 1
    except _OpportunityCliError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            }
        )
        return exc.exit_code
    except OpportunityObservationError as exc:
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
                "opportunity_invalid_arguments",
                "opportunity_invalid_request",
                "opportunity_platform_identity_unverified",
            }
            else 1
        )
    _emit(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
