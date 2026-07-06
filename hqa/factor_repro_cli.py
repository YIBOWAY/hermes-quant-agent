from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from hqa import config, factor_repro, quant_cli


def _write_experiment_config(path: Path, factor_id: str, symbols: list[str], start: str, end: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    experiment = {
        "experiment_name": f"factor-repro-{factor_id}",
        "symbols": symbols,
        "start": start,
        "end": end,
        "factor_blend": {"factors": [{"factor_id": factor_id}]},
    }
    path.write_text(json.dumps(experiment, indent=2, sort_keys=True), encoding="utf-8")


def _default_config_path(factor_id: str) -> Path:
    return config.REPO_DIR / "data" / "_runtime" / "experiments" / f"{factor_id}.json"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hqa-factor-repro",
        description="Scene-B factor reproduction (proposal-only, human-gated)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_propose = sub.add_parser("propose")
    p_propose.add_argument("--goal", required=True)
    p_propose.add_argument(
        "--source-file",
        required=True,
        dest="source_file",
        help="factor code generated in the Hermes session (D-19)",
    )
    p_propose.add_argument("--universe", default="SPY,QQQ")

    p_approve = sub.add_parser("approve")
    p_approve.add_argument("--candidate-id", required=True)
    p_approve.add_argument("--note", required=True)

    p_backtest = sub.add_parser("backtest")
    p_backtest.add_argument("--factor-id", required=True, help="factor_id of the APPROVED candidate")
    p_backtest.add_argument("--symbol", action="append", required=True, dest="symbols")
    p_backtest.add_argument("--start", required=True)
    p_backtest.add_argument("--end", required=True)
    p_backtest.add_argument("--provider", default="tiingo")
    p_backtest.add_argument("--config-out", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "propose":
        code, out = quant_cli.run_propose_factor(args.goal, args.source_file, args.universe)
        candidate_id = factor_repro.parse_candidate_id(out)
        print(f"candidate_id={candidate_id or '?'}")
        print("HUMAN GATE: inspect the generated candidate factor and confirm the translation is correct.")
        print("Run: hqa-factor-repro approve --candidate-id <id> --note <translation-review-note>")
        if not candidate_id:
            print(out.strip())
            return 1
        return 0 if code == 0 else 1

    if args.cmd == "approve":
        # Human-only translation gate (gate 2). Scheduled automation must not call this.
        code, out = quant_cli.run_agent_review(args.candidate_id, "approve", args.note)
        print(out.strip() or f"approved: {args.candidate_id}")
        return 0 if code == 0 else 1

    if args.cmd == "backtest":
        config_out = Path(args.config_out) if args.config_out else _default_config_path(args.factor_id)
        _write_experiment_config(config_out, args.factor_id, args.symbols, args.start, args.end)
        code, out = quant_cli.run_experiment_config(
            str(config_out),
            provider=args.provider,
            include_approved=True,
        )
        summary = factor_repro.parse_experiment_summary(out)
        metrics: dict[str, float] = {}
        summary_path = summary.get("agent_summary")
        if summary_path:
            path = Path(summary_path)
            if not path.is_absolute():
                path = config.AIQP_DIR / path
            try:
                metrics = factor_repro.extract_best_run_metrics(path.read_text(encoding="utf-8"))
            except OSError:
                metrics = {}
        print(f"experiment_id={summary.get('experiment_id', '?')} best_run_id={summary.get('best_run_id', '?')}")
        for key in ("sharpe", "total_return", "max_drawdown"):
            print(f"{key}={metrics.get(key, '?')}")
        print(f"report={summary.get('report', '?')}")
        print("Results are proposal-only; promotion to the review pool is a human decision.")
        return 0 if code == 0 else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
