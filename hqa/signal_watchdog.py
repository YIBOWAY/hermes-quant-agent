from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from hqa import config, quant_cli, runlog, signals


def run(
    run_scan: Callable[[], tuple[int, str]],
    load_candidates: Callable[[], list[dict[str, Any]]],
    run_factor_lab: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
    min_score: Optional[float] = None,
    min_iv_rank: Optional[float] = None,
) -> tuple[bool, str]:
    scan_exit, _scan_out = run_scan()
    factor_exit, factor_out = run_factor_lab()
    candidates = load_candidates() if scan_exit == 0 else []
    has_signal, sigs = signals.evaluate_signals(candidates, min_score=min_score, min_iv_rank=min_iv_rank)
    ts = now_iso()
    runlog.append_jsonl(
        {
            "ts": ts,
            "job": "signal-watchdog",
            "scan_exit": scan_exit,
            "factor_exit": factor_exit,
            "n_candidates": len(candidates),
            "score_summary": signals.summarize_scores(candidates),
            "factor_lab": signals.parse_factor_lab(factor_out),
            "thresholds": {"min_score": min_score, "min_iv_rank": min_iv_rank},
            "has_signal": has_signal,
            "signals": sigs,
        },
        log_path,
    )
    if not has_signal:
        return False, ""
    message = f"[HQA] Scene-A signals {ts}\n" + "\n".join(f"  - {s}" for s in sigs)
    return True, message


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA Scene-A market-signal watchdog ([SILENT] unless signal)")
    parser.add_argument("--provider", default="futu")
    parser.add_argument("--scan", action="store_true", help="run a fresh scan first (default: consume collect artifacts, D-15)")
    parser.add_argument("--scan-dir", default=str(config.OPTIONS_SCAN_DIR))
    parser.add_argument("--date", default=None, help="scan run_date; defaults to today UTC")
    parser.add_argument("--min-score", type=float, default=None, help="unset = collect mode (D-15)")
    parser.add_argument("--min-iv-rank", type=float, default=None, help="unset = collect mode (D-15)")
    parser.add_argument("--log", default=str(config.LOG_DIR / "signal_watchdog.jsonl"))
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    run_date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.scan:
        run_scan = lambda: quant_cli.run_options_scan(args.provider)  # noqa: E731
    else:
        run_scan = lambda: (0, "")  # noqa: E731 — artifacts produced by hqa-options-collect (D-15)
    try:
        has_signal, message = run(
            run_scan=run_scan,
            load_candidates=lambda: signals.load_scan_candidates(Path(args.scan_dir), run_date),
            run_factor_lab=lambda: quant_cli.run_factor_lab(args.provider),
            now_iso=runlog.utc_now_iso,
            log_path=log_path,
            min_score=args.min_score,
            min_iv_rank=args.min_iv_rank,
        )
    except Exception as exc:  # unattended job: never crash the scheduler
        ts = runlog.utc_now_iso()
        runlog.append_jsonl({"ts": ts, "job": "signal-watchdog", "error": repr(exc)}, log_path)
        print(f"[HQA] signal watchdog failed to run {ts}: {exc!r}")
        return 0
    if has_signal:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
