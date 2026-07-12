from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Callable, Optional

from hqa import config, factor_repro, quant_cli, reviewlog, runlog

_SAFETY_RE = re.compile(r"^safety\.([a-z_]+)=(\S+)", re.MULTILINE)


def _normalize_safety_value(value: object) -> str:
    """Normalize doctor safety values to lowercase strings (JSON bools → true/false)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


def parse_safety(doctor_output: str) -> dict[str, str]:
    """Parse safety invariants from doctor output.

    JSON-first (D-22 / audit F1): prefer the trailing JSON payload's ``safety``
    object so a pure-JSON doctor path does not false-alarm. Fall back to the
    historical ``safety.key=value`` text lines for older/mixed outputs.
    """
    payload = factor_repro.parse_json_payload(doctor_output)
    if payload is not None:
        safety_obj = payload.get("safety")
        if isinstance(safety_obj, dict):
            return {
                str(key): _normalize_safety_value(val)
                for key, val in safety_obj.items()
            }
    return {key: val for key, val in _SAFETY_RE.findall(doctor_output)}


def evaluate(
    safety: dict[str, str],
    exit_code: int,
    expected: Optional[dict[str, str]] = None,
) -> tuple[bool, list[str], str]:
    """Evaluate doctor result.

    Returns ``(alert, deviations, channel)`` where channel is one of:
    ``none`` | ``infra`` | ``safety`` | ``mixed``.

    Infra vs safety split (audit F1): a non-zero doctor exit with *no* parsed
    safety keys is treated as infrastructure failure only — missing keys are
    not also reported as safety-baseline breaches (that was the historical
    false-alarm path).
    """
    expected = expected or config.EXPECTED_SAFETY
    infra: list[str] = []
    safety_devs: list[str] = []

    if exit_code != 0:
        infra.append(f"doctor exited {exit_code}")

    # Pure infra: doctor failed and emitted nothing parseable as safety.
    if exit_code != 0 and not safety:
        deviations = [f"[INFRA] {d}" for d in infra]
        return True, deviations, "infra"

    for key, want in expected.items():
        got = safety.get(key)
        if got is None:
            safety_devs.append(f"{key} missing (expected {want})")
        elif got != want:
            safety_devs.append(f"{key}={got} (expected {want})")

    if infra and safety_devs:
        deviations = [f"[INFRA] {d}" for d in infra] + [f"[SAFETY] {d}" for d in safety_devs]
        return True, deviations, "mixed"
    if infra:
        deviations = [f"[INFRA] {d}" for d in infra]
        return True, deviations, "infra"
    if safety_devs:
        deviations = [f"[SAFETY] {d}" for d in safety_devs]
        return True, deviations, "safety"
    return False, [], "none"


def build_alert_message(deviations: list[str], ts: str, channel: str = "safety") -> str:
    if channel == "infra":
        tag = "[INFRA]"
    elif channel == "mixed":
        tag = "[SAFETY][INFRA]"
    else:
        tag = "[SAFETY]"
    lines = [f"[HQA]{tag} safety-invariant watchdog {ts}"]
    lines += [f"  - {d}" for d in deviations]
    if channel == "infra":
        lines.append(
            "  action: doctor/platform infra failed. Do not treat this as a confirmed "
            "safety-baseline breach until doctor recovers; re-check when platform is healthy."
        )
    else:
        lines.append(
            "  action: STOP. Do not run any execution path until the safety baseline is restored."
        )
    return "\n".join(lines)


def run(
    run_doctor: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
    review_dir: Optional[Path] = None,
) -> tuple[bool, str]:
    exit_code, output = run_doctor()
    safety = parse_safety(output)
    alert, deviations, channel = evaluate(safety, exit_code)
    ts = now_iso()
    runlog.append_jsonl(
        {
            "ts": ts,
            "job": "doctor-watchdog",
            "doctor_exit": exit_code,
            "alert": alert,
            "channel": channel,
            "safety": safety,
            "deviations": deviations,
        },
        log_path,
    )
    if alert and review_dir is not None:
        kind = "infra" if channel == "infra" else "alert"
        event = (
            "doctor-infra failure"
            if channel == "infra"
            else "safety-invariant deviation"
        )
        reviewlog.new_draft(
            kind=kind,
            event=event,
            data={"deviations": deviations, "safety": safety, "channel": channel},
            source="doctor-watchdog",
            ts=ts,
            review_dir=review_dir,
            fingerprint=f"{ts[:10]}:{channel}:" + ";".join(sorted(deviations)),
        )
    return alert, (build_alert_message(deviations, ts, channel) if alert else "")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA safety-invariant watchdog ([SILENT] unless deviation)")
    parser.add_argument("--log", default=str(config.LOG_DIR / "doctor_watchdog.jsonl"))
    parser.add_argument("--review-dir", default=str(config.REVIEW_DIR))
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    try:
        alert, message = run(quant_cli.run_doctor, runlog.utc_now_iso, log_path, Path(args.review_dir))
    except Exception as exc:  # unattended job: surface as alert, never crash the scheduler
        ts = runlog.utc_now_iso()
        runlog.append_jsonl(
            {
                "ts": ts,
                "job": "doctor-watchdog",
                "alert": True,
                "channel": "infra",
                "error": repr(exc),
            },
            log_path,
        )
        print(f"[HQA][INFRA] watchdog failed to run {ts}: {exc!r}")
        return 0
    if alert:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
