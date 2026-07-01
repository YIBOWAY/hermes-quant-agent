from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Callable, Optional

from hqa import config, quant_cli, runlog

_SAFETY_RE = re.compile(r"^safety\.([a-z_]+)=(\S+)", re.MULTILINE)


def parse_safety(doctor_output: str) -> dict[str, str]:
    return {key: val for key, val in _SAFETY_RE.findall(doctor_output)}


def evaluate(
    safety: dict[str, str],
    exit_code: int,
    expected: Optional[dict[str, str]] = None,
) -> tuple[bool, list[str]]:
    expected = expected or config.EXPECTED_SAFETY
    deviations: list[str] = []
    if exit_code != 0:
        deviations.append(f"doctor exited {exit_code}")
    for key, want in expected.items():
        got = safety.get(key)
        if got is None:
            deviations.append(f"{key} missing (expected {want})")
        elif got != want:
            deviations.append(f"{key}={got} (expected {want})")
    return (len(deviations) > 0, deviations)


def build_alert_message(deviations: list[str], ts: str) -> str:
    lines = [f"[HQA][ALERT] safety-invariant watchdog {ts}"]
    lines += [f"  - {d}" for d in deviations]
    lines.append("  action: STOP. Do not run any execution path until the safety baseline is restored.")
    return "\n".join(lines)


def run(
    run_doctor: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
) -> tuple[bool, str]:
    exit_code, output = run_doctor()
    safety = parse_safety(output)
    alert, deviations = evaluate(safety, exit_code)
    ts = now_iso()
    runlog.append_jsonl(
        {
            "ts": ts,
            "job": "doctor-watchdog",
            "doctor_exit": exit_code,
            "alert": alert,
            "safety": safety,
            "deviations": deviations,
        },
        log_path,
    )
    return alert, (build_alert_message(deviations, ts) if alert else "")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA safety-invariant watchdog ([SILENT] unless deviation)")
    parser.add_argument("--log", default=str(config.LOG_DIR / "doctor_watchdog.jsonl"))
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    try:
        alert, message = run(quant_cli.run_doctor, runlog.utc_now_iso, log_path)
    except Exception as exc:  # unattended job: surface as alert, never crash the scheduler
        ts = runlog.utc_now_iso()
        runlog.append_jsonl({"ts": ts, "job": "doctor-watchdog", "alert": True, "error": repr(exc)}, log_path)
        print(f"[HQA][ALERT] watchdog failed to run {ts}: {exc!r}")
        return 0
    if alert:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
