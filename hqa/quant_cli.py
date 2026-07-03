from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from hqa import config


def _run(args: list[str], bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    bin_path = bin_path or config.QUANT_SYSTEM_BIN
    cwd = cwd or config.AIQP_DIR
    proc = subprocess.run(
        [str(bin_path), *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=300,
    )
    return proc.returncode, proc.stdout


def run_doctor(bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["doctor"], bin_path=bin_path, cwd=cwd)


def run_options_sample_scan(bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["options", "daily-scan", "--provider", "sample"], bin_path=bin_path, cwd=cwd)


def run_options_scan(provider: str = "futu", bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["options", "daily-scan", "--provider", provider], bin_path=bin_path, cwd=cwd)


def run_factor_lab(provider: str = "futu", bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["factor", "refresh-lab", "--provider", provider], bin_path=bin_path, cwd=cwd)
