from __future__ import annotations

import argparse
import re
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


def build_digest(
    safety: dict[str, str],
    scan: dict[str, str],
    ts: str,
    headlines: Optional[list[dict]] = None,
    provider: str = "sample",
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
        note = "summary unavailable (no summary line in scan output)"
        if provider != "sample":
            note += " — DEGRADED: is OpenD running?"
        lines.append(f"Options radar ({provider}): {note}")
    if headlines:
        lines.append("Top AI headlines:")
        for h in headlines[:5]:
            lines.append(f"  - [{h.get('category', '?')}] {h.get('title', '?')} ({h.get('source', '?')})")
    lines.append("Scope: read-only research digest. No trading action taken.")
    return "\n".join(lines)


def run(
    run_doctor: Callable[[], tuple[int, str]],
    run_scan: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
    run_aihot: Optional[Callable[[], str]] = None,
    provider: str = "sample",
) -> str:
    doctor_exit, doctor_out = run_doctor()
    scan_exit, scan_out = run_scan()
    safety = parse_safety(doctor_out)
    scan = parse_scan_summary(scan_out)
    headlines: list[dict] = []
    if run_aihot is not None:
        try:
            headlines = aihot.parse_items(run_aihot())
        except Exception:
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
            "headlines": [h.get("title") for h in headlines],
        },
        log_path,
    )
    return build_digest(safety, scan, ts, headlines=headlines or None, provider=provider)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA pre-market digest (daily, always delivered)")
    parser.add_argument("--log", default=str(config.LOG_DIR / "premarket_digest.jsonl"))
    parser.add_argument("--provider", default="futu")
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    try:
        digest = run(
            quant_cli.run_doctor,
            lambda: quant_cli.run_options_scan(args.provider),
            runlog.utc_now_iso,
            log_path,
            run_aihot=aihot.fetch_items,
            provider=args.provider,
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
