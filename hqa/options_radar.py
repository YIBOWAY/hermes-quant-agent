from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from hqa import config, quant_cli, runlog
from hqa.premarket_digest import meta_as_summary, parse_scan_summary


def build_radar_summary(scan: dict[str, str], ts: str, provider: str = "futu") -> str:
    if not scan:
        return f"[HQA] Options radar {ts}: provider={provider} scan summary unavailable"
    return (
        f"[HQA] Options radar {ts}\n"
        f"  provider={provider} universe={scan.get('universe_size', '?')} "
        f"scanned={scan.get('scanned', '?')} failed={scan.get('failed', '?')} "
        f"candidates={scan.get('candidates', '?')}\n"
        "  Scope: read-only options research. Proposal-only."
    )


def run(
    run_scan: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
    provider: str = "futu",
) -> str:
    scan_exit, scan_out = run_scan()
    scan = parse_scan_summary(scan_out)
    ts = now_iso()
    runlog.append_jsonl(
        {
            "ts": ts,
            "job": "options-radar",
            "provider": provider,
            "scan_exit": scan_exit,
            "options": scan,
        },
        log_path,
    )
    return build_radar_summary(scan, ts, provider=provider)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA options radar summary (read-only)")
    parser.add_argument("--provider", default="futu")
    parser.add_argument("--log", default=str(config.LOG_DIR / "options_radar.jsonl"))
    parser.add_argument("--scan", action="store_true", help="run a fresh scan (default: read collect meta artifact)")
    parser.add_argument("--scan-dir", default=str(config.OPTIONS_SCAN_DIR))
    parser.add_argument("--date", default=None, help="scan run_date; defaults to today UTC")
    args = parser.parse_args(argv)

    log_path = Path(args.log)
    run_date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.scan:
        run_scan = lambda: quant_cli.run_options_scan(args.provider)  # noqa: E731
    else:
        run_scan = lambda: (0, meta_as_summary(Path(args.scan_dir), run_date))  # noqa: E731

    try:
        summary = run(run_scan, runlog.utc_now_iso, log_path, provider=args.provider)
    except Exception as exc:  # unattended job: report failure line, never crash the scheduler
        ts = runlog.utc_now_iso()
        runlog.append_jsonl({"ts": ts, "job": "options-radar", "error": repr(exc)}, log_path)
        print(f"[HQA] Options radar {ts}: FAILED ({exc!r})")
        return 0
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
