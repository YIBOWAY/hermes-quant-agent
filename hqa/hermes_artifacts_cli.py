from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from hqa import config, quant_cli, runlog
from hqa.hermes_artifacts import HermesArtifactFeed, HermesArtifactFeedError
from hqa.market_foresight import MarketForesightPublisher
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


def _runtime() -> HermesArtifactFeed:
    ledger = PredictionLedger(
        config.PREDICTION_DIR,
        run_history=quant_cli.run_historical_prices,
        now=runlog.utc_now_iso,
    )
    publisher = MarketForesightPublisher(
        config.MARKET_FORESIGHT_DIR,
        prediction_ledger=ledger,
    )
    return HermesArtifactFeed(
        config.HERMES_ARTIFACT_FEED_PATH,
        portfolio_risk_path=config.LOG_DIR / "portfolio_risk.jsonl",
        prediction_ledger=ledger,
        foresight_publisher=publisher,
        now=runlog.utc_now_iso,
    )


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="hqa-artifacts")
    sub = parser.add_subparsers(dest="command", required=True)
    refresh = sub.add_parser("refresh")
    refresh.add_argument("--limit", type=int, default=50)
    sub.add_parser("show")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _CliArgumentError as exc:
        _emit(
            {
                "error": {
                    "code": "hermes_artifact_invalid_arguments",
                    "message": str(exc),
                    "retryable": False,
                }
            }
        )
        return 2
    try:
        feed = _runtime()
        document = (
            feed.rebuild(limit=args.limit) if args.command == "refresh" else feed.read()
        )
    except HermesArtifactFeedError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": False,
                }
            }
        )
        return 2 if exc.code == "hermes_artifact_invalid_request" else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _emit(
            {
                "error": {
                    "code": "hermes_artifact_feed_unavailable",
                    "message": f"Hermes artifact feed failed: {type(exc).__name__}",
                    "retryable": True,
                }
            }
        )
        return 1
    _emit(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
