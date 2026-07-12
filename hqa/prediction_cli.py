from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from hqa import config, quant_cli, runlog
from hqa.predictions import PredictionLedger, PredictionLedgerError


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


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="hqa-prediction")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--symbol", required=True)
    create.add_argument("--subject")
    create.add_argument("--direction", required=True)
    create.add_argument("--horizon-date", required=True)
    create.add_argument("--confidence", required=True, type=float)
    create.add_argument("--range-low", type=float)
    create.add_argument("--range-high", type=float)
    create.add_argument("--flat-threshold-pct", type=float, default=0.005)
    create.add_argument("--falsifier", required=True)
    create.add_argument("--rationale")
    create.add_argument("--request-id")
    create.add_argument("--prediction-dir", default=str(config.PREDICTION_DIR))

    list_predictions = sub.add_parser("list")
    list_predictions.add_argument("--status")
    list_predictions.add_argument("--since")
    list_predictions.add_argument(
        "--prediction-dir",
        default=str(config.PREDICTION_DIR),
    )

    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--as-of")
    reconcile.add_argument("--limit", type=int, default=25)
    reconcile.add_argument("--cursor")
    reconcile.add_argument(
        "--prediction-dir",
        default=str(config.PREDICTION_DIR),
    )
    return parser


def _execute(args: argparse.Namespace) -> tuple[int, Any]:
    ledger = PredictionLedger(
        Path(args.prediction_dir),
        run_history=quant_cli.run_historical_prices,
        now=runlog.utc_now_iso,
    )
    if args.command == "create":
        request = {
            "symbol": args.symbol,
            "direction": args.direction,
            "horizon_date": args.horizon_date,
            "confidence": args.confidence,
            "flat_threshold_pct": args.flat_threshold_pct,
            "falsifier": args.falsifier,
        }
        for field in (
            "subject",
            "range_low",
            "range_high",
            "rationale",
            "request_id",
        ):
            value = getattr(args, field)
            if value is not None:
                request[field] = value
        return 0, ledger.create(request)
    if args.command == "list":
        return 0, ledger.list(status=args.status, since=args.since)
    report = ledger.reconcile_due(
        as_of=args.as_of,
        limit=args.limit,
        cursor=args.cursor,
    )
    return (1 if report.get("status") == "degraded" else 0), report


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _CliArgumentError as exc:
        _emit(
            {
                "error": {
                    "code": "prediction_invalid_arguments",
                    "message": str(exc),
                    "retryable": False,
                }
            }
        )
        return 2
    try:
        exit_code, document = _execute(args)
    except PredictionLedgerError as exc:
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
            "prediction_invalid_request",
            "prediction_idempotency_conflict",
        }:
            return 2
        return 1
    _emit(document)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
