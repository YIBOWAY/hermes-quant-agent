from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from hqa import config, opportunities, quant_cli, runlog, signals


def run(
    run_scan: Callable[[], tuple[int, str]],
    load_candidates: Callable[[], list[dict[str, Any]]],
    run_factor_lab: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
    min_score: Optional[float] = None,
    min_iv_rank: Optional[float] = None,
    run_date: Optional[str] = None,
    refresh_lab: bool = False,
    record_signal: Optional[Callable[[dict[str, Any]], Any]] = None,
) -> tuple[bool, str]:
    scan_exit, _scan_out = run_scan()
    if refresh_lab:
        factor_exit, factor_out = run_factor_lab()
    else:
        factor_exit, factor_out = 0, ""  # skipped by default (audit F15 / PR-6)
    candidates = load_candidates() if scan_exit == 0 else []
    artifact_missing = scan_exit == 0 and len(candidates) == 0
    has_signal, sigs = signals.evaluate_signals(
        candidates, min_score=min_score, min_iv_rank=min_iv_rank
    )
    mode = (
        "collect"
        if min_score is None and min_iv_rank is None
        else "alert"
    )
    ts = now_iso()
    source_date = run_date or (
        str(candidates[0].get("run_date", "")) if candidates else ""
    )
    signal_records = signals.build_signal_records(
        candidates,
        min_score=min_score,
        min_iv_rank=min_iv_rank,
        source_date=source_date,
        observed_at=ts,
    )
    recorded_count = 0
    record_errors: list[str] = []
    if record_signal is not None:
        for record in signal_records:
            try:
                record_signal(record)
                recorded_count += 1
            except opportunities.OpportunityLedgerError as exc:
                record_errors.append(exc.code)
            except Exception:
                record_errors.append("opportunity_record_failed")
    runlog.append_jsonl(
        {
            "ts": ts,
            "job": "signal-watchdog",
            "scan_exit": scan_exit,
            "factor_exit": factor_exit,
            "factor_lab_skipped": not refresh_lab,
            "n_candidates": len(candidates),
            "score_summary": signals.summarize_scores(candidates),
            "factor_lab": signals.parse_factor_lab(factor_out),
            "thresholds": {"min_score": min_score, "min_iv_rank": min_iv_rank},
            "mode": mode,
            "run_date": run_date,
            "artifact_missing": artifact_missing,
            "has_signal": has_signal,
            "signals": sigs,
            "signal_records": signal_records,
            "opportunity_recorded_count": recorded_count,
            "opportunity_record_errors": record_errors,
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
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="override threshold; default loads data/_runtime/signal_thresholds.json (unset there = collect)",
    )
    parser.add_argument(
        "--min-iv-rank",
        type=float,
        default=None,
        help="override threshold; leave unset while iv_rank is null in scan artifacts",
    )
    parser.add_argument(
        "--thresholds",
        default=str(config.SIGNAL_THRESHOLDS_PATH),
        help="path to signal_thresholds.json",
    )
    parser.add_argument(
        "--refresh-lab",
        action="store_true",
        help="also run factor refresh-lab (default: skip; expensive and not needed for options signals)",
    )
    parser.add_argument("--log", default=str(config.LOG_DIR / "signal_watchdog.jsonl"))
    parser.add_argument(
        "--opportunity-dir",
        default=str(config.OPPORTUNITY_DIR),
        help="append structured signal observations to the 9G opportunity ledger",
    )
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    run_date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    loaded = config.load_signal_thresholds(Path(args.thresholds))
    min_score = args.min_score if args.min_score is not None else loaded["min_score"]
    min_iv_rank = args.min_iv_rank if args.min_iv_rank is not None else loaded["min_iv_rank"]

    if args.scan:
        run_scan = lambda: quant_cli.run_options_scan(args.provider)  # noqa: E731
    else:
        run_scan = lambda: (0, "")  # noqa: E731 — artifacts produced by hqa-options-collect (D-15)
    try:
        tracker = opportunities.OpportunityTracker(
            Path(args.opportunity_dir),
            now=runlog.utc_now_iso,
        )
        has_signal, message = run(
            run_scan=run_scan,
            load_candidates=lambda: signals.load_scan_candidates(Path(args.scan_dir), run_date),
            run_factor_lab=lambda: quant_cli.run_factor_lab(args.provider),
            now_iso=runlog.utc_now_iso,
            log_path=log_path,
            min_score=min_score,
            min_iv_rank=min_iv_rank,
            run_date=run_date,
            refresh_lab=args.refresh_lab,
            record_signal=lambda record: tracker.record(
                {
                    "event": "signal_observed",
                    "request_id": f"options-scan:{record['signal_id']}",
                    "payload": record,
                }
            ),
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
