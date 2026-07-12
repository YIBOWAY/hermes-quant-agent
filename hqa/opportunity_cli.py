from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional

from hqa import config, quant_cli, runlog, signals
from hqa.opportunities import OpportunityLedgerError, OpportunityTracker


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
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        document = json.loads(
            output,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid JSON",
            retryable=True,
            exit_code=1,
        ) from exc
    if not isinstance(document, dict):
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid JSON",
            retryable=True,
            exit_code=1,
        )
    if (
        document.get("schema_version") != 1
        or not isinstance(document.get("read_status"), str)
        or document.get("read_status") not in {"available", "empty", "degraded"}
        or isinstance(document.get("returned_count"), bool)
        or not isinstance(document.get("returned_count"), int)
        or not isinstance(document.get("truncated"), bool)
        or not isinstance(document.get("observations"), list)
        or not isinstance(document.get("errors"), list)
    ):
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid schema",
            retryable=True,
            exit_code=1,
        )
    return document


def _run_platform_observations(**kwargs: Any) -> dict[str, Any]:
    try:
        exit_code, output = quant_cli.run_paper_strategy_observations(**kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        raise _OpportunityCliError(
            "opportunity_platform_unavailable",
            "paper-strategy observations command failed",
            retryable=True,
            exit_code=1,
        ) from exc
    if exit_code != 0:
        raise _OpportunityCliError(
            "opportunity_platform_unavailable",
            "paper-strategy observations command failed",
            retryable=True,
            exit_code=1,
        )
    return _parse_platform_observations(output)


def _validate_action_snapshot(
    document: dict[str, Any],
    *,
    platform_signal_id: str,
    platform_execution_id: str,
    limit: int,
) -> Optional[dict[str, Any]]:
    expected_fields = {
        "schema_version",
        "snapshot_at",
        "read_status",
        "query",
        "returned_count",
        "truncated",
        "ops_quality",
        "observations",
        "errors",
    }
    expected_query = {
        "from_date": None,
        "to_date": None,
        "signal_id": platform_signal_id,
        "limit": limit,
    }
    expected_quality_fields = {
        "pending_sleeve_count",
        "pending_journal_count",
        "corrupt_journal_count",
        "recovery_required_count",
    }
    query = document.get("query")
    quality = document.get("ops_quality")
    observations = document["observations"]
    if (
        set(document) != expected_fields
        or query != expected_query
        or not isinstance(quality, dict)
        or set(quality) != expected_quality_fields
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in quality.values()
        )
        or document["returned_count"] != len(observations)
        or (document["read_status"] == "empty" and observations)
        or (document["read_status"] == "available" and not observations)
    ):
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid action schema",
            retryable=True,
            exit_code=1,
        )
    _parse_utc_timestamp(
        document["snapshot_at"],
        field="platform snapshot_at",
    )
    if any(quality.values()) or document["errors"] != []:
        raise _OpportunityCliError(
            "opportunity_platform_observation_incomplete",
            "platform observation quality is incomplete",
            retryable=True,
            exit_code=1,
        )
    if document["read_status"] == "empty":
        return None
    if len(observations) != 1:
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid action identities",
            retryable=True,
            exit_code=1,
        )
    observation = observations[0]
    if (
        not isinstance(observation, dict)
        or not isinstance(observation.get("signal"), dict)
        or observation["signal"].get("signal_id") != platform_signal_id
        or not isinstance(observation.get("executions"), list)
        or len(observation["executions"]) > 1
    ):
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid action identities",
            retryable=True,
            exit_code=1,
        )
    execution_ids: set[str] = set()
    match = None
    for execution in observation["executions"]:
        if (
            not isinstance(execution, dict)
            or not isinstance(execution.get("execution_id"), str)
            or not execution["execution_id"]
            or execution.get("signal_id") != platform_signal_id
            or execution["execution_id"] in execution_ids
        ):
            raise _OpportunityCliError(
                "opportunity_platform_observation_invalid",
                "paper-strategy observations returned invalid action identities",
                retryable=True,
                exit_code=1,
            )
        execution_ids.add(execution["execution_id"])
        if execution["execution_id"] == platform_execution_id:
            match = execution
    return match


def _record_action(args: argparse.Namespace) -> dict[str, Any]:
    document = _run_platform_observations(
        signal_id=args.platform_signal_id,
        limit=args.limit,
    )
    if (
        document.get("read_status") not in {"available", "empty"}
        or document.get("truncated") is not False
    ):
        raise _OpportunityCliError(
            "opportunity_platform_observation_incomplete",
            "platform observations must be available and untruncated",
            retryable=True,
            exit_code=1,
        )
    execution = _validate_action_snapshot(
        document,
        platform_signal_id=args.platform_signal_id,
        platform_execution_id=args.platform_execution_id,
        limit=args.limit,
    )
    if execution is None:
        raise _OpportunityCliError(
            "opportunity_platform_identity_unverified",
            "platform signal_id and execution_id could not be verified together",
            retryable=False,
            exit_code=2,
        )
    if not all(
        isinstance(execution.get(field), str) and execution[field]
        for field in ("status", "created_at", "updated_at")
    ):
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid schema",
            retryable=True,
            exit_code=1,
        )
    tracker = OpportunityTracker(Path(args.opportunity_dir), now=runlog.utc_now_iso)
    return tracker.record(
        {
            "event": "action_observed",
            "request_id": (
                f"record-action:{args.signal_id}:{args.platform_signal_id}:"
                f"{args.platform_execution_id}:{execution['updated_at']}"
            ),
            "payload": {
                "signal_id": args.signal_id,
                "platform_signal_id": args.platform_signal_id,
                "platform_execution_id": args.platform_execution_id,
                "status": execution["status"],
                "actor": args.actor,
                "occurred_at": execution["created_at"],
                "updated_at": execution["updated_at"],
            },
        }
    )


def _strict_json_sha256(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode("utf-8", errors="strict")).hexdigest()


def _require_utc_timestamp(value: str, *, flag: str) -> str:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError):
        parsed = None
    if (
        not isinstance(value, str)
        or "T" not in value
        or not value.endswith("Z")
        or parsed is None
        or parsed.utcoffset() != timedelta(0)
    ):
        raise _OpportunityCliError(
            "opportunity_invalid_arguments",
            f"{flag} must be an aware UTC timestamp ending in Z",
            retryable=False,
            exit_code=2,
        )
    return value


def _parse_utc_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            f"{field} must be a UTC timestamp ending in Z",
            retryable=True,
            exit_code=1,
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            f"{field} must be a UTC timestamp ending in Z",
            retryable=True,
            exit_code=1,
        ) from exc
    if parsed.utcoffset() != timedelta(0):
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            f"{field} must be a UTC timestamp ending in Z",
            retryable=True,
            exit_code=1,
        )
    return parsed


def _find_signal_state(
    tracker: OpportunityTracker,
    signal_id: str,
) -> dict[str, Any]:
    cursor: Optional[str] = None
    while True:
        page = tracker.list(limit=200, cursor=cursor)
        for state in page:
            if state["signal_id"] == signal_id:
                return state
        if len(page) < 200:
            break
        cursor = page[-1]["signal_id"]
    raise _OpportunityCliError(
        "opportunity_invalid_request",
        "opportunity signal_id is unknown",
        retryable=False,
        exit_code=2,
    )


def _validate_coverage_observations(
    observations: list[Any],
    *,
    limit: int,
) -> None:
    if len(observations) > limit:
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid coverage identities",
            retryable=True,
            exit_code=1,
        )
    signal_ids: set[str] = set()
    execution_ids: set[str] = set()
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or not isinstance(observation.get("signal"), dict)
            or not isinstance(observation["signal"].get("signal_id"), str)
            or not observation["signal"]["signal_id"]
            or observation["signal"]["signal_id"] in signal_ids
            or not isinstance(observation.get("executions"), list)
            or len(observation["executions"]) > 1
        ):
            raise _OpportunityCliError(
                "opportunity_platform_observation_invalid",
                "paper-strategy observations returned invalid coverage identities",
                retryable=True,
                exit_code=1,
            )
        signal_id = observation["signal"]["signal_id"]
        signal_ids.add(signal_id)
        for execution in observation["executions"]:
            if (
                not isinstance(execution, dict)
                or not isinstance(execution.get("execution_id"), str)
                or not execution["execution_id"]
                or execution["execution_id"] in execution_ids
                or execution.get("signal_id") != signal_id
            ):
                raise _OpportunityCliError(
                    "opportunity_platform_observation_invalid",
                    "paper-strategy observations returned invalid coverage identities",
                    retryable=True,
                    exit_code=1,
                )
            execution_ids.add(execution["execution_id"])


def _validate_coverage_snapshot(
    document: dict[str, Any],
    *,
    args: argparse.Namespace,
    state: dict[str, Any],
    covered_through: str,
) -> str:
    snapshot_at = document.get("snapshot_at")
    snapshot_time = _parse_utc_timestamp(
        snapshot_at,
        field="platform snapshot_at",
    )
    covered_time = _parse_utc_timestamp(
        covered_through,
        field="covered_through",
    )
    query = document.get("query")
    quality = document.get("ops_quality")
    expected_quality_fields = {
        "pending_sleeve_count",
        "pending_journal_count",
        "corrupt_journal_count",
        "recovery_required_count",
    }
    if (
        not isinstance(query, dict)
        or set(query) != {"from_date", "to_date", "signal_id", "limit"}
        or query.get("from_date") != args.from_date
        or query.get("to_date") != args.to_date
        or query.get("signal_id") is not None
        or query.get("limit") != args.limit
        or not isinstance(quality, dict)
        or set(quality) != expected_quality_fields
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in quality.values()
        )
        or document.get("returned_count") != len(document["observations"])
        or document.get("errors") != []
        or (document["read_status"] == "empty" and document["observations"])
        or (document["read_status"] == "available" and not document["observations"])
    ):
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid coverage schema",
            retryable=True,
            exit_code=1,
        )
    if any(quality.values()):
        raise _OpportunityCliError(
            "opportunity_platform_observation_incomplete",
            "platform observation quality is incomplete",
            retryable=True,
            exit_code=1,
        )
    _validate_coverage_observations(
        document["observations"],
        limit=args.limit,
    )
    if covered_time > snapshot_time:
        raise _OpportunityCliError(
            "opportunity_platform_observation_incomplete",
            "coverage cannot extend beyond the platform snapshot watermark",
            retryable=True,
            exit_code=1,
        )
    source_date = state["signal"]["source"]["date"]
    deadline_at = state["signal"]["eligibility"].get("deadline_at")
    deadline_date = deadline_at[:10] if isinstance(deadline_at, str) else source_date
    try:
        normalized_source = date.fromisoformat(source_date).isoformat()
        normalized_deadline = date.fromisoformat(deadline_date).isoformat()
    except ValueError as exc:
        raise _OpportunityCliError(
            "opportunity_platform_observation_invalid",
            "opportunity source/deadline date is invalid",
            retryable=False,
            exit_code=1,
        ) from exc
    if (args.from_date is not None and args.from_date > normalized_source) or (
        args.to_date is not None and args.to_date < normalized_deadline
    ):
        raise _OpportunityCliError(
            "opportunity_platform_observation_incomplete",
            "platform observation query does not cover the opportunity window",
            retryable=True,
            exit_code=1,
        )
    return str(snapshot_at)


def _sync_actions(args: argparse.Namespace) -> dict[str, Any]:
    covered_through = _require_utc_timestamp(
        args.covered_through,
        flag="--covered-through",
    )
    tracker = OpportunityTracker(Path(args.opportunity_dir), now=runlog.utc_now_iso)
    state = _find_signal_state(tracker, args.signal_id)
    document = _run_platform_observations(
        from_date=args.from_date,
        to_date=args.to_date,
        limit=args.limit,
    )
    if (
        document.get("read_status") not in {"available", "empty"}
        or document.get("truncated") is not False
    ):
        raise _OpportunityCliError(
            "opportunity_platform_observation_incomplete",
            "platform observations must be available or empty and untruncated",
            retryable=True,
            exit_code=1,
        )
    snapshot_at = _validate_coverage_snapshot(
        document,
        args=args,
        state=state,
        covered_through=covered_through,
    )
    snapshot_id = f"pso_{_strict_json_sha256(document)[:24]}"
    return tracker.record(
        {
            "event": "action_coverage_observed",
            "request_id": (
                f"sync-actions:{args.signal_id}:{snapshot_id}:{covered_through}"
            ),
            "payload": {
                "signal_id": args.signal_id,
                "source": "paper_strategy_observations",
                "snapshot_id": snapshot_id,
                "observed_at": snapshot_at,
                "covered_through": covered_through,
                "complete": True,
                "truncated": False,
            },
        }
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
    _emit(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
