from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from hqa import config, quant_cli, runlog
from hqa.hermes_artifacts import HermesArtifactFeed, HermesArtifactFeedError
from hqa.market_foresight import MarketForesightError, MarketForesightPublisher
from hqa.predictions import PredictionLedger


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


def _runtime() -> tuple[MarketForesightPublisher, HermesArtifactFeed]:
    ledger = PredictionLedger(
        config.PREDICTION_DIR,
        run_history=quant_cli.run_historical_prices,
        now=runlog.utc_now_iso,
    )
    publisher = MarketForesightPublisher(
        config.MARKET_FORESIGHT_DIR,
        prediction_ledger=ledger,
    )
    feed = HermesArtifactFeed(
        config.HERMES_ARTIFACT_FEED_PATH,
        portfolio_risk_path=config.LOG_DIR / "portfolio_risk.jsonl",
        prediction_ledger=ledger,
        foresight_publisher=publisher,
        now=runlog.utc_now_iso,
    )
    return publisher, feed


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="hqa-market-foresight")
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose")
    propose.add_argument("--symbol", required=True)
    propose.add_argument("--subject")
    propose.add_argument("--direction", required=True)
    propose.add_argument("--horizon-date", required=True)
    propose.add_argument("--confidence", required=True, type=float)
    propose.add_argument("--range-low", type=float)
    propose.add_argument("--range-high", type=float)
    propose.add_argument("--flat-threshold-pct", type=float, default=0.005)
    propose.add_argument("--falsifier", required=True)
    propose.add_argument("--rationale")
    propose.add_argument("--request-id", required=True)
    sub.add_parser("list")
    return parser


def _execute(args: argparse.Namespace) -> Any:
    publisher, feed = _runtime()
    if args.command == "list":
        return publisher.list()
    request = {
        "symbol": args.symbol,
        "direction": args.direction,
        "horizon_date": args.horizon_date,
        "confidence": args.confidence,
        "flat_threshold_pct": args.flat_threshold_pct,
        "falsifier": args.falsifier,
        "request_id": args.request_id,
    }
    for field in ("subject", "range_low", "range_high", "rationale"):
        value = getattr(args, field)
        if value is not None:
            request[field] = value
    artifact = publisher.publish(request)
    feed.rebuild()
    return artifact


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _CliArgumentError as exc:
        _emit(
            {
                "error": {
                    "code": "market_foresight_invalid_arguments",
                    "message": str(exc),
                    "retryable": False,
                }
            }
        )
        return 2
    try:
        document = _execute(args)
    except MarketForesightError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            }
        )
        return 2 if exc.code.endswith(("invalid_request", "idempotency_conflict")) else 1
    except HermesArtifactFeedError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": True,
                }
            }
        )
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _emit(
            {
                "error": {
                    "code": "market_foresight_store_unavailable",
                    "message": f"market-foresight store failed: {type(exc).__name__}",
                    "retryable": True,
                }
            }
        )
        return 1
    _emit(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
