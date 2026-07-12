from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from hqa import aihot, config, quant_cli, runlog
from hqa.doctor_watchdog import parse_safety

_SCAN_RE = re.compile(
    r"run_date=(?P<run_date>\S+).*?"
    r"universe_size=(?P<universe_size>\d+).*?"
    r"scanned_tickers=(?P<scanned>\d+).*?"
    r"failed_tickers=(?P<failed>\d+).*?"
    r"candidates=(?P<candidates>\d+)",
    re.DOTALL,
)


def parse_scan_summary(scan_output: str) -> dict[str, str]:
    match = _SCAN_RE.search(scan_output)
    return match.groupdict() if match else {}


def meta_as_summary(scan_dir: Path, run_date: str) -> str:
    """Render a collect-run meta artifact as a scan-summary line (D-15: consume, don't scan)."""
    path = Path(scan_dir) / f"{run_date}_meta.json"
    if not path.exists():
        return ""
    meta = json.loads(path.read_text(encoding="utf-8"))
    failed = meta.get("failed_tickers", [])
    failed_n = len(failed) if isinstance(failed, list) else failed
    return (
        f"run_date={meta.get('run_date', run_date)} universe_size={meta.get('universe_size', 0)} "
        f"scanned_tickers={meta.get('scanned_tickers', 0)} failed_tickers={failed_n} "
        f"candidates={meta.get('candidate_count', 0)}"
    )


def build_digest(
    safety: dict[str, str],
    scan: dict[str, str],
    ts: str,
    headlines: Optional[list[dict]] = None,
    aihot_error: Optional[str] = None,
    provider: str = "sample",
    run_date: Optional[str] = None,
    artifact_missing: bool = False,
) -> str:
    safe = all(safety.get(k) == v for k, v in config.EXPECTED_SAFETY.items())
    safety_state = "NOMINAL" if safe else "DEVIATION — CHECK WATCHDOG LOG"
    lines = [
        f"[HQA] Pre-market digest {ts}",
        (
            f"Safety baseline: {safety_state} "
            f"(dry_run={safety.get('dry_run', '?')}, paper_trading={safety.get('paper_trading', '?')}, "
            f"live={safety.get('live_trading_enabled', '?')}, kill_switch={safety.get('kill_switch', '?')})"
        ),
    ]
    if scan:
        lines.append(
            f"Options radar ({provider}): run_date={scan.get('run_date', '?')}, "
            f"universe={scan.get('universe_size', '?')}, scanned={scan.get('scanned', '?')}, "
            f"failed={scan.get('failed', '?')}, candidates={scan.get('candidates', '?')}"
        )
    else:
        date_hint = run_date or "?"
        if artifact_missing:
            note = f"DEGRADED: no scan artifact for {date_hint}"
        else:
            note = "summary unavailable (no summary line in scan output)"
            if provider != "sample":
                note += " — DEGRADED: is OpenD running?"
        lines.append(f"Options radar ({provider}): {note}")
    if headlines:
        lines.append("Top AI headlines:")
        for h in headlines[:5]:
            lines.append(f"  - [{h.get('category', '?')}] {h.get('title', '?')} ({h.get('source', '?')})")
    elif aihot_error:
        lines.append(f"AI HOT: DEGRADED ({aihot_error})")
    lines.append("Scope: read-only research digest. No trading action taken.")
    return "\n".join(lines)


def run(
    run_doctor: Callable[[], tuple[int, str]],
    run_scan: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
    run_aihot: Optional[Callable[[], str]] = None,
    provider: str = "sample",
    run_date: Optional[str] = None,
    artifact_missing: bool = False,
) -> str:
    doctor_exit, doctor_out = run_doctor()
    scan_exit, scan_out = run_scan()
    safety = parse_safety(doctor_out)
    scan = parse_scan_summary(scan_out)
    # Empty scan_out in artifact mode means the collect meta file was missing.
    missing = artifact_missing or (not scan and not (scan_out or "").strip())
    headlines: list[dict] = []
    aihot_error: Optional[str] = None
    if run_aihot is not None:
        try:
            headlines = aihot.parse_items(run_aihot())
        except Exception as exc:
            aihot_error = repr(exc)
            headlines = []
    ts = now_iso()
    runlog.append_jsonl(
        {
            "ts": ts,
            "job": "premarket-digest",
            "doctor_exit": doctor_exit,
            "scan_exit": scan_exit,
            "provider": provider,
            "safety": safety,
            "options": scan,
            "run_date": run_date,
            "artifact_missing": missing and not scan,
            "headlines": [h.get("title") for h in headlines],
            "aihot_error": aihot_error,
        },
        log_path,
    )
    return build_digest(
        safety,
        scan,
        ts,
        headlines=headlines or None,
        aihot_error=aihot_error,
        provider=provider,
        run_date=run_date,
        artifact_missing=missing and not scan,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA pre-market digest (daily, always delivered)")
    parser.add_argument("--log", default=str(config.LOG_DIR / "premarket_digest.jsonl"))
    parser.add_argument("--provider", default="futu")
    parser.add_argument("--scan", action="store_true", help="run a fresh scan (default: read collect meta artifact, D-15)")
    parser.add_argument("--scan-dir", default=str(config.OPTIONS_SCAN_DIR))
    parser.add_argument("--date", default=None, help="scan run_date; defaults to today UTC")
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    run_date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    artifact_missing = False
    if args.scan:
        run_scan = lambda: quant_cli.run_options_scan(args.provider)  # noqa: E731
    else:
        meta_line = meta_as_summary(Path(args.scan_dir), run_date)
        artifact_missing = not meta_line
        run_scan = lambda: (0, meta_line)  # noqa: E731
    try:
        digest = run(
            quant_cli.run_doctor,
            run_scan,
            runlog.utc_now_iso,
            log_path,
            run_aihot=aihot.fetch_items,
            provider=args.provider,
            run_date=run_date,
            artifact_missing=artifact_missing,
        )
    except Exception as exc:  # unattended job: report failure line, never crash the scheduler
        ts = runlog.utc_now_iso()
        runlog.append_jsonl({"ts": ts, "job": "premarket-digest", "error": repr(exc)}, log_path)
        print(f"[HQA] Pre-market digest {ts}: FAILED to build ({exc!r})")
        return 0
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
