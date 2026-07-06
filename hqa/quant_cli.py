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
) -> tuple[int, str]:
    bin_path = bin_path or config.QUANT_SYSTEM_BIN
    cwd = cwd or config.AIQP_DIR
    proc = subprocess.run(
        [str(bin_path), *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout


def run_doctor(bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["doctor"], bin_path=bin_path, cwd=cwd)


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
        ["agent", "propose-factor", "--goal", goal, "--universe", universe, "--source-file", source_file],
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
        ["agent", "review", "--candidate-id", candidate_id, "--decision", decision, "--note", note],
        bin_path=bin_path,
        cwd=cwd,
    )


def run_experiment_config(
    config_path: str,
    provider: str = "tiingo",
    include_approved: bool = True,
    bin_path: Optional[Path] = None,
    cwd: Optional[Path] = None,
    timeout: int = 900,
) -> tuple[int, str]:
    args = ["experiment", "run-config", "--config", config_path, "--provider", provider]
    if include_approved:
        args.append("--include-approved-candidates")
    return _run(args, bin_path=bin_path, cwd=cwd, timeout=timeout)
