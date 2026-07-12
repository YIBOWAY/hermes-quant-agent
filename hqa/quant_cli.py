from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from hqa import config


def _run(
    args: list[str],
    bin_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
    timeout: int = 300,
    merge_stderr: bool = True,
) -> tuple[int, str]:
    bin_path = bin_path or config.QUANT_SYSTEM_BIN
    cwd = cwd or config.AIQP_DIR
    proc = subprocess.run(
        [str(bin_path), *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    output = proc.stdout
    if not merge_stderr and proc.returncode != 0 and not output.strip():
        output = proc.stderr or ""
    return proc.returncode, output


def run_doctor(bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["doctor", "--json"], bin_path=bin_path, cwd=cwd)


def run_paper_account_snapshot(
    account_id: str = "default",
    bin_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> tuple[int, str]:
    """Read the platform's unified paper snapshot with parseable JSON stdout."""
    return _run(
        [
            "paper",
            "account-show",
            "--account",
            account_id,
            "--format",
            "json",
        ],
        bin_path=bin_path,
        cwd=cwd,
        merge_stderr=False,
    )


def run_historical_prices(
    symbols: list[str],
    start: str,
    end: str,
    provider: str = "futu",
    adjustment: str = "qfq",
    bin_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> tuple[int, str]:
    """Read strict multi-symbol daily history with parseable JSON stdout."""
    args = ["data", "prices"]
    for symbol in symbols:
        args.extend(["--symbol", symbol])
    args.extend(
        [
            "--start",
            start,
            "--end",
            end,
            "--provider",
            provider,
            "--adjustment",
            adjustment,
            "--format",
            "json",
        ]
    )
    return _run(
        args,
        bin_path=bin_path,
        cwd=cwd,
        merge_stderr=False,
    )


def run_paper_strategy_observations(
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    signal_id: Optional[str] = None,
    limit: int = 200,
    bin_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> tuple[int, str]:
    """Read bounded paper-strategy signal/execution facts as clean JSON."""
    args = ["paper", "strategies", "observations"]
    if from_date is not None:
        args.extend(["--from-date", from_date])
    if to_date is not None:
        args.extend(["--to-date", to_date])
    if signal_id is not None:
        args.extend(["--signal-id", signal_id])
    args.extend(["--limit", str(limit), "--format", "json"])
    return _run(
        args,
        bin_path=bin_path,
        cwd=cwd,
        merge_stderr=False,
    )


def run_options_sample_scan(bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["options", "daily-scan", "--provider", "sample"], bin_path=bin_path, cwd=cwd)


def run_options_scan(
    provider: str = "futu",
    bin_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
    timeout: int = 3600,
) -> tuple[int, str]:
    return _run(["options", "daily-scan", "--provider", provider], bin_path=bin_path, cwd=cwd, timeout=timeout)


def run_factor_lab(provider: str = "futu", bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["factor", "refresh-lab", "--provider", provider], bin_path=bin_path, cwd=cwd)


def run_propose_factor(
    goal: str,
    source_file: str,
    universe: str = "SPY,QQQ",
    bin_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> tuple[int, str]:
    return _run(
        ["agent", "propose-factor", "--goal", goal, "--universe", universe, "--source-file", source_file, "--json"],
        bin_path=bin_path,
        cwd=cwd,
    )


def run_list_candidates(bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["agent", "list-candidates"], bin_path=bin_path, cwd=cwd)


def run_agent_review(
    candidate_id: str,
    decision: str,
    note: str,
    bin_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> tuple[int, str]:
    return _run(
        ["agent", "review", "--candidate-id", candidate_id, "--decision", decision, "--note", note, "--json"],
        bin_path=bin_path,
        cwd=cwd,
    )


def run_experiment_config(
    config_path: str,
    provider: str = "futu",
    include_approved: bool = True,
    bin_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
    timeout: int = 900,
) -> tuple[int, str]:
    # Default futu: platform tiingo.token is often unset; pass --provider tiingo
    # explicitly only when a Tiingo token is configured (audit PR-2).
    args = ["experiment", "run-config", "--config", config_path, "--provider", provider]
    if include_approved:
        args.append("--include-approved-candidates")
    args.append("--json")
    return _run(args, bin_path=bin_path, cwd=cwd, timeout=timeout)
