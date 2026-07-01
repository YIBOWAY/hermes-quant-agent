# Phase 0a — Read-only Digital Employee Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the first read-only Hermes digital employee — a `[SILENT]` safety-invariant watchdog and a daily pre-market digest — that orchestrates the local `ai-quant-platform` without ever touching the trading chain.

**Architecture:** All logic lives in a version-controlled Python package `hqa/` (stdlib only, dependency-injected so it is trivially unit-testable). Hermes cron cannot execute repo scripts directly — it requires physical files under `~/.hermes/scripts/` and blocks symlinks/absolute paths via a `.resolve()` escape check (empirically confirmed). So a thin bash wrapper is *copied* into `~/.hermes/scripts/` by an installer; each wrapper `cd`s into the repo and `exec`s `python3 -m hqa.<module>`. Jobs run with `--no-agent` (no LLM, deterministic) and `--deliver local`; the watchdog prints to stdout only on a deviation (silent otherwise), while both jobs always append a timestamped JSONL run record.

**Tech Stack:** Python 3.9.6 (system, standard library only at runtime) · `pytest` in a project `.venv` (dev/test only) · bash wrappers · Hermes `cron` (`--no-agent --script --deliver local --workdir`) · `ai-quant-platform` `quant-system` CLI (`doctor`, `options daily-scan --provider sample`).

## Global Constraints

Every task's requirements implicitly include this section.

- **Read-only red line (Phase 0a):** MUST NOT call paper-account mutating APIs, backtest / rebalance / strategy-sleeve execution, or any real trading API. Allowed platform calls are exactly `quant-system doctor` and `quant-system options daily-scan --provider sample` (the sample scan writes only research artifacts under the platform's own `data/options_scans/`, never the trading chain).
- **Safety baseline that must stay true** (any deviation ⇒ alert): `safety.dry_run=true`, `safety.paper_trading=true`, `safety.live_trading_enabled=false`, `safety.kill_switch=true`.
- **Runtime deps:** system `python3` (3.9.6), **standard library only**. No third-party runtime packages.
- **Python 3.9 compat:** every `hqa/*.py` module starts with `from __future__ import annotations` (enables `X | None`, `tuple[...]`, `dict[...]` annotations on 3.9).
- **Script deployment rule (verified):** Hermes cron scripts MUST physically reside in `~/.hermes/scripts/`. Symlinks and absolute repo paths are **blocked** (`cron/scheduler.py` resolves the path and requires `path.relative_to(scripts_dir)`). Deploy by **copying** a thin wrapper.
- **Subprocess cwd:** every `quant-system` invocation runs with `cwd=<ai-quant-platform>` so the platform resolves its own config/data dirs (matches manual runs).
- **Observability:** every job run appends one timestamped JSONL record; the watchdog stays silent (empty stdout) unless a deviation or error occurs.
- **Absolute paths:** repo = `/Users/sunyibo/programs/Hermes-quant-agent`; platform = `/Users/sunyibo/programs/ai-quant-platform`; CLI = `/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/quant-system`.

**Phase 0a defaults (adjustable later, resolves design-doc §12 open items):** notification channel = `local` (no Discord/messaging platform is configured yet); watchdog cadence = every 30 min; digest = daily 08:00 local; options universe = platform `sample` provider. **AI News / macro calendar are intentionally deferred** — they are HTTP-only (no CLI surface), so they belong to the later API/auth phase, not Phase 0a.

---

## File Structure

```
Hermes-quant-agent/
  hqa/
    __init__.py            # empty package marker
    config.py              # absolute paths, safety baseline, env overrides
    runlog.py              # utc_now_iso(), append_jsonl(record, path)
    quant_cli.py           # run_doctor(), run_options_sample_scan() -> (exit, merged_output)
    doctor_watchdog.py     # parse_safety / evaluate / build_alert_message / run / main
    premarket_digest.py    # parse_scan_summary / build_digest / run / main
  scripts/
    hermes/
      hqa-doctor-watchdog.sh    # thin wrapper -> python3 -m hqa.doctor_watchdog
      hqa-premarket-digest.sh   # thin wrapper -> python3 -m hqa.premarket_digest
    install.sh                  # copies wrappers into ~/.hermes/scripts/ (+x)
  tests/
    conftest.py            # (empty) ensures repo root import + pytest rootdir
    test_config.py
    test_runlog.py
    test_quant_cli.py
    test_doctor_watchdog.py
    test_premarket_digest.py
    test_install.py
  logs/
    .gitkeep               # runtime *.jsonl are git-ignored
  docs/
    design/hermes_quant_agent_plan.md   # (exists) design spec
    plans/2026-07-01-phase-0a-readonly-digital-employee.md  # this plan
  pyproject.toml           # pytest config (testpaths, pythonpath)
  .gitignore
  README.md
```

Responsibilities are split so each file holds one concern and the pure functions (parse/evaluate/build) never touch subprocess, filesystem, or env — those live only in `quant_cli.py`, `runlog.py`, and each module's `main()`.

---

### Task 1: Project scaffold + config module

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `README.md`, `hqa/__init__.py`, `hqa/config.py`, `tests/conftest.py`, `logs/.gitkeep`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `hqa.config.REPO_DIR: Path` — repo root (`.../Hermes-quant-agent`).
  - `hqa.config.AIQP_DIR: Path` — `/Users/sunyibo/programs/ai-quant-platform` (override env `HQA_AIQP_DIR`).
  - `hqa.config.QUANT_SYSTEM_BIN: Path` — `AIQP_DIR/ai-quant/bin/quant-system` (override env `HQA_QUANT_SYSTEM_BIN`).
  - `hqa.config.LOG_DIR: Path` — `REPO_DIR/logs` (override env `HQA_LOG_DIR`).
  - `hqa.config.EXPECTED_SAFETY: dict[str, str]` — `{"dry_run":"true","paper_trading":"true","live_trading_enabled":"false","kill_switch":"true"}`.

- [ ] **Step 1: Scaffold the repo (dirs, git, venv, pytest, static files)**

Run:

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent
mkdir -p hqa scripts/hermes tests logs
git init -q 2>/dev/null || true
python3 -m venv .venv
./.venv/bin/python -m pip install -q --upgrade pip pytest
touch hqa/__init__.py tests/conftest.py logs/.gitkeep
```

Create `.gitignore`:

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
logs/*.jsonl
data/
.DS_Store
```

Create `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-q"
```

Create `README.md`:

```markdown
# Hermes-quant-agent

Hermes orchestration layer for the local `ai-quant-platform`. Phase 0a ships two
read-only digital employees that never touch the trading chain:

- **Safety watchdog** (`hqa.doctor_watchdog`) — `[SILENT]`; alerts only if a
  `safety.*` invariant deviates or `quant-system doctor` fails.
- **Pre-market digest** (`hqa.premarket_digest`) — daily summary of platform
  safety status + `options daily-scan --provider sample`.

Logic lives in `hqa/` (Python 3.9, stdlib only). Hermes cron runs thin wrappers
copied into `~/.hermes/scripts/` by `scripts/install.sh`.

Tests: `./.venv/bin/pytest`

See `docs/plans/2026-07-01-phase-0a-readonly-digital-employee.md`.
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_config.py`:

```python
from __future__ import annotations

import importlib
from pathlib import Path

import hqa.config as config


def test_repo_and_platform_paths():
    assert config.REPO_DIR.name == "Hermes-quant-agent"
    assert config.AIQP_DIR == Path("/Users/sunyibo/programs/ai-quant-platform")
    assert config.QUANT_SYSTEM_BIN == config.AIQP_DIR / "ai-quant" / "bin" / "quant-system"
    assert config.LOG_DIR == config.REPO_DIR / "logs"


def test_expected_safety_baseline():
    assert config.EXPECTED_SAFETY == {
        "dry_run": "true",
        "paper_trading": "true",
        "live_trading_enabled": "false",
        "kill_switch": "true",
    }


def test_log_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HQA_LOG_DIR", str(tmp_path / "mylogs"))
    try:
        importlib.reload(config)
        assert config.LOG_DIR == tmp_path / "mylogs"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.config'` (or `AttributeError` on `config.REPO_DIR`).

- [ ] **Step 4: Write the minimal implementation**

Create `hqa/config.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
AIQP_DIR = Path(os.environ.get("HQA_AIQP_DIR", "/Users/sunyibo/programs/ai-quant-platform"))
QUANT_SYSTEM_BIN = Path(
    os.environ.get("HQA_QUANT_SYSTEM_BIN", str(AIQP_DIR / "ai-quant" / "bin" / "quant-system"))
)
LOG_DIR = Path(os.environ.get("HQA_LOG_DIR", str(REPO_DIR / "logs")))

# Nominal safety baseline. Any deviation from these values is an alert.
EXPECTED_SAFETY = {
    "dry_run": "true",
    "paper_trading": "true",
    "live_trading_enabled": "false",
    "kill_switch": "true",
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_config.py -q`
Expected: PASS — `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore pyproject.toml README.md hqa/__init__.py hqa/config.py tests/conftest.py tests/test_config.py logs/.gitkeep
git commit -q -m "feat: scaffold hqa package and config module"
```

---

### Task 2: Run-log JSONL writer

**Files:**
- Create: `hqa/runlog.py`
- Test: `tests/test_runlog.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `hqa.runlog.utc_now_iso() -> str` — `"YYYY-MM-DDTHH:MM:SSZ"` (UTC).
  - `hqa.runlog.append_jsonl(record: dict, path: Path) -> None` — creates parent dir, appends one JSON line (sorted keys, `ensure_ascii=False`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_runlog.py`:

```python
from __future__ import annotations

import json
import re

from hqa import runlog


def test_utc_now_iso_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", runlog.utc_now_iso())


def test_append_creates_parent_and_writes_valid_json(tmp_path):
    path = tmp_path / "nested" / "run.jsonl"
    runlog.append_jsonl({"job": "x", "n": 1}, path)
    runlog.append_jsonl({"job": "x", "n": 2}, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["n"] == 1
    assert json.loads(lines[1])["n"] == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_runlog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.runlog'`.

- [ ] **Step 3: Write the minimal implementation**

Create `hqa/runlog.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_jsonl(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_runlog.py -q`
Expected: PASS — `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/runlog.py tests/test_runlog.py
git commit -q -m "feat: add JSONL run-log writer"
```

---

### Task 3: quant-system CLI wrappers

**Files:**
- Create: `hqa/quant_cli.py`
- Test: `tests/test_quant_cli.py`

**Interfaces:**
- Consumes: `hqa.config.QUANT_SYSTEM_BIN`, `hqa.config.AIQP_DIR`.
- Produces:
  - `hqa.quant_cli.run_doctor() -> tuple[int, str]` — `(exit_code, merged_stdout_stderr)`.
  - `hqa.quant_cli.run_options_sample_scan() -> tuple[int, str]` — same shape; runs `options daily-scan --provider sample`.
  - Both accept optional `bin_path: Path` and `cwd: Path` kwargs (for tests); both merge stderr into stdout and run with `cwd=AIQP_DIR`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_quant_cli.py`:

```python
from __future__ import annotations

import subprocess

import pytest

from hqa import config, quant_cli


class _FakeProc:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


def test_run_doctor_invokes_cli_with_cwd(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(0, "safety.dry_run=true\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_doctor()
    assert code == 0
    assert "safety.dry_run=true" in out
    assert seen["argv"][0].endswith("quant-system")
    assert seen["argv"][1] == "doctor"
    assert seen["kwargs"]["cwd"] == str(config.AIQP_DIR)
    assert seen["kwargs"]["stderr"] is subprocess.STDOUT


def test_run_options_sample_scan_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "candidates=1000\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_options_sample_scan()
    assert code == 0 and "candidates=1000" in out
    assert seen["argv"][1:] == ["options", "daily-scan", "--provider", "sample"]


@pytest.mark.skipif(
    not config.QUANT_SYSTEM_BIN.exists(), reason="quant-system binary not present"
)
def test_run_doctor_integration_real():
    code, out = quant_cli.run_doctor()
    assert code == 0
    assert "safety.dry_run=" in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_quant_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.quant_cli'`.

- [ ] **Step 3: Write the minimal implementation**

Create `hqa/quant_cli.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_quant_cli.py -q`
Expected: PASS — `3 passed` (the integration test runs because the binary exists on this machine).

- [ ] **Step 5: Commit**

```bash
git add hqa/quant_cli.py tests/test_quant_cli.py
git commit -q -m "feat: add quant-system doctor and sample-scan wrappers"
```

---

### Task 4: Doctor safety-invariant watchdog

**Files:**
- Create: `hqa/doctor_watchdog.py`
- Test: `tests/test_doctor_watchdog.py`

**Interfaces:**
- Consumes: `hqa.config.EXPECTED_SAFETY`, `hqa.quant_cli.run_doctor`, `hqa.runlog.append_jsonl`, `hqa.runlog.utc_now_iso`.
- Produces:
  - `parse_safety(doctor_output: str) -> dict[str, str]` — every `safety.KEY=VAL` line.
  - `evaluate(safety: dict[str, str], exit_code: int, expected: dict[str, str] | None = None) -> tuple[bool, list[str]]` — `(alert, deviations)`.
  - `build_alert_message(deviations: list[str], ts: str) -> str`.
  - `run(run_doctor, now_iso, log_path: Path) -> tuple[bool, str]` — writes JSONL, returns `(alert, message)` (message empty when no alert).
  - `main(argv: list[str] | None = None) -> int` — prints message only on alert; always returns `0`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_doctor_watchdog.py`:

```python
from __future__ import annotations

import json

from hqa import doctor_watchdog as dw

DOCTOR_SAMPLE = """Quant System local health
environment=local
safety.dry_run=true
safety.paper_trading=true
safety.live_trading_enabled=false
safety.kill_switch=true
data.default_provider=futu
runtime.log=data/_runtime/logs/backend.jsonl
"""


def test_parse_safety_extracts_four_invariants():
    safety = dw.parse_safety(DOCTOR_SAMPLE)
    assert safety == {
        "dry_run": "true",
        "paper_trading": "true",
        "live_trading_enabled": "false",
        "kill_switch": "true",
    }


def test_evaluate_nominal_is_silent():
    safety = dw.parse_safety(DOCTOR_SAMPLE)
    alert, deviations = dw.evaluate(safety, exit_code=0)
    assert alert is False
    assert deviations == []


def test_evaluate_flags_live_trading_enabled():
    safety = dw.parse_safety(DOCTOR_SAMPLE.replace("live_trading_enabled=false", "live_trading_enabled=true"))
    alert, deviations = dw.evaluate(safety, exit_code=0)
    assert alert is True
    assert any("live_trading_enabled=true" in d for d in deviations)


def test_evaluate_flags_nonzero_exit():
    safety = dw.parse_safety(DOCTOR_SAMPLE)
    alert, deviations = dw.evaluate(safety, exit_code=1)
    assert alert is True
    assert any("doctor exited 1" in d for d in deviations)


def test_run_nominal_writes_log_and_stays_silent(tmp_path):
    log_path = tmp_path / "wd.jsonl"
    alert, message = dw.run(
        run_doctor=lambda: (0, DOCTOR_SAMPLE),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert alert is False
    assert message == ""
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "doctor-watchdog"
    assert record["alert"] is False
    assert record["safety"]["live_trading_enabled"] == "false"


def test_run_deviation_returns_alert_message(tmp_path):
    log_path = tmp_path / "wd.jsonl"
    flipped = DOCTOR_SAMPLE.replace("kill_switch=true", "kill_switch=false")
    alert, message = dw.run(
        run_doctor=lambda: (0, flipped),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert alert is True
    assert "kill_switch=false" in message
    assert "[HQA][ALERT]" in message
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["alert"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_doctor_watchdog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.doctor_watchdog'`.

- [ ] **Step 3: Write the minimal implementation**

Create `hqa/doctor_watchdog.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_doctor_watchdog.py -q`
Expected: PASS — `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/doctor_watchdog.py tests/test_doctor_watchdog.py
git commit -q -m "feat: add read-only safety-invariant watchdog"
```

---

### Task 5: Pre-market digest

**Files:**
- Create: `hqa/premarket_digest.py`
- Test: `tests/test_premarket_digest.py`

**Interfaces:**
- Consumes: `hqa.config.EXPECTED_SAFETY`, `hqa.quant_cli.run_doctor`, `hqa.quant_cli.run_options_sample_scan`, `hqa.doctor_watchdog.parse_safety`, `hqa.runlog.*`.
- Produces:
  - `parse_scan_summary(scan_output: str) -> dict[str, str]` — keys `run_date`, `universe_size`, `scanned`, `failed`, `candidates` (empty dict if no summary line).
  - `build_digest(safety: dict[str, str], scan: dict[str, str], ts: str) -> str`.
  - `run(run_doctor, run_scan, now_iso, log_path: Path) -> str` — writes JSONL, returns digest text.
  - `main(argv: list[str] | None = None) -> int` — always prints the digest; always returns `0`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_premarket_digest.py`:

```python
from __future__ import annotations

import json

from hqa import premarket_digest as pd

DOCTOR_SAMPLE = """Quant System local health
safety.dry_run=true
safety.paper_trading=true
safety.live_trading_enabled=false
safety.kill_switch=true
"""

SCAN_SAMPLE = """dry_run=false provider=sample top=100 strategies=sell_put,covered_call output_dir=data/options_scans
market_regime=Unknown reason=no_vix_history
run_date=2026-07-01 universe_size=100 scanned_tickers=100 failed_tickers=0 candidates=1000 data=data/options_scans/2026-07-01.jsonl meta=data/options_scans/2026-07-01_meta.json
"""


def test_parse_scan_summary_extracts_counts():
    scan = pd.parse_scan_summary(SCAN_SAMPLE)
    assert scan == {
        "run_date": "2026-07-01",
        "universe_size": "100",
        "scanned": "100",
        "failed": "0",
        "candidates": "1000",
    }


def test_parse_scan_summary_missing_returns_empty():
    assert pd.parse_scan_summary("no summary here") == {}


def test_build_digest_nominal_mentions_counts_and_safety():
    from hqa.doctor_watchdog import parse_safety

    text = pd.build_digest(parse_safety(DOCTOR_SAMPLE), pd.parse_scan_summary(SCAN_SAMPLE), "2026-07-01T00:00:00Z")
    assert "NOMINAL" in text
    assert "candidates=1000" in text
    assert "read-only" in text.lower()


def test_build_digest_flags_safety_deviation():
    from hqa.doctor_watchdog import parse_safety

    bad = parse_safety(DOCTOR_SAMPLE.replace("dry_run=true", "dry_run=false"))
    text = pd.build_digest(bad, {}, "2026-07-01T00:00:00Z")
    assert "DEVIATION" in text


def test_run_writes_log_and_returns_digest(tmp_path):
    log_path = tmp_path / "digest.jsonl"
    text = pd.run(
        run_doctor=lambda: (0, DOCTOR_SAMPLE),
        run_scan=lambda: (0, SCAN_SAMPLE),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert "Pre-market digest" in text
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "premarket-digest"
    assert record["options"]["candidates"] == "1000"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_premarket_digest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.premarket_digest'`.

- [ ] **Step 3: Write the minimal implementation**

Create `hqa/premarket_digest.py`:

```python
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Callable, Optional

from hqa import config, quant_cli, runlog
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


def build_digest(safety: dict[str, str], scan: dict[str, str], ts: str) -> str:
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
            f"Options radar (sample): run_date={scan.get('run_date', '?')}, "
            f"universe={scan.get('universe_size', '?')}, scanned={scan.get('scanned', '?')}, "
            f"failed={scan.get('failed', '?')}, candidates={scan.get('candidates', '?')}"
        )
    else:
        lines.append("Options radar (sample): summary unavailable (no summary line in scan output)")
    lines.append("Scope: read-only research digest. No trading action taken.")
    return "\n".join(lines)


def run(
    run_doctor: Callable[[], tuple[int, str]],
    run_scan: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
) -> str:
    doctor_exit, doctor_out = run_doctor()
    scan_exit, scan_out = run_scan()
    safety = parse_safety(doctor_out)
    scan = parse_scan_summary(scan_out)
    ts = now_iso()
    runlog.append_jsonl(
        {
            "ts": ts,
            "job": "premarket-digest",
            "doctor_exit": doctor_exit,
            "scan_exit": scan_exit,
            "safety": safety,
            "options": scan,
        },
        log_path,
    )
    return build_digest(safety, scan, ts)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA pre-market digest (daily, always delivered)")
    parser.add_argument("--log", default=str(config.LOG_DIR / "premarket_digest.jsonl"))
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    try:
        digest = run(
            quant_cli.run_doctor,
            quant_cli.run_options_sample_scan,
            runlog.utc_now_iso,
            log_path,
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_premarket_digest.py -q`
Expected: PASS — `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/premarket_digest.py tests/test_premarket_digest.py
git commit -q -m "feat: add read-only pre-market digest"
```

---

### Task 6: Deploy wrappers + installer

**Files:**
- Create: `scripts/hermes/hqa-doctor-watchdog.sh`, `scripts/hermes/hqa-premarket-digest.sh`, `scripts/install.sh`
- Test: `tests/test_install.py`

**Interfaces:**
- Consumes: the `hqa.doctor_watchdog` / `hqa.premarket_digest` module entry points from Tasks 4–5.
- Produces: physical wrapper files under `${HERMES_HOME:-$HOME/.hermes}/scripts/` (copied, executable) that `cd` into the repo and `exec python3 -m hqa.<module>`. These satisfy Hermes' `path.relative_to(scripts_dir)` escape check (a symlink or absolute repo path would be **blocked**).

- [ ] **Step 1: Write the failing test**

Create `tests/test_install.py`:

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _install(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = dict(os.environ, HOME=str(fake_home), HERMES_HOME=str(fake_home / ".hermes"))
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    return fake_home / ".hermes" / "scripts"


def test_install_copies_physical_executable_wrappers(tmp_path):
    dest = _install(tmp_path)
    names = sorted(p.name for p in dest.glob("hqa-*.sh"))
    assert names == ["hqa-doctor-watchdog.sh", "hqa-premarket-digest.sh"]
    for wrapper in dest.glob("hqa-*.sh"):
        assert not wrapper.is_symlink()            # physical file (symlink would be blocked)
        assert os.access(wrapper, os.X_OK)         # executable
        assert "python3 -m hqa." in wrapper.read_text()


def test_wrappers_pass_hermes_escape_check(tmp_path):
    # Replicate cron/scheduler.py: script must resolve INSIDE the scripts dir.
    dest = _install(tmp_path)
    scripts_dir_resolved = dest.resolve()
    for name in ("hqa-doctor-watchdog.sh", "hqa-premarket-digest.sh"):
        resolved = (scripts_dir_resolved / name).resolve()
        # raises ValueError (⇒ test failure) if the path escapes the scripts dir
        resolved.relative_to(scripts_dir_resolved)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_install.py -q`
Expected: FAIL — `install.sh` does not exist yet, so `bash` returns non-zero and the assert fires (`No such file or directory`).

- [ ] **Step 3: Write the wrappers and installer**

Create `scripts/hermes/hqa-doctor-watchdog.sh`:

```bash
#!/bin/bash
# HQA safety-invariant watchdog wrapper (deployed into ~/.hermes/scripts/).
# Thin wrapper: Hermes blocks symlinks/abs paths, so this physical file cd's
# into the repo and exec's the version-controlled Python module.
set -euo pipefail
cd /Users/sunyibo/programs/Hermes-quant-agent
exec /usr/bin/env python3 -m hqa.doctor_watchdog "$@"
```

Create `scripts/hermes/hqa-premarket-digest.sh`:

```bash
#!/bin/bash
# HQA pre-market digest wrapper (deployed into ~/.hermes/scripts/).
set -euo pipefail
cd /Users/sunyibo/programs/Hermes-quant-agent
exec /usr/bin/env python3 -m hqa.premarket_digest "$@"
```

Create `scripts/install.sh`:

```bash
#!/bin/bash
# Deploy HQA cron wrappers into ~/.hermes/scripts/.
# Hermes requires scripts to physically reside there; symlinks and absolute
# paths are rejected by the scheduler's escape check, so we COPY the wrappers.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${HERMES_HOME:-$HOME/.hermes}/scripts"
mkdir -p "$DEST"
for src in "$REPO_DIR"/scripts/hermes/hqa-*.sh; do
  name="$(basename "$src")"
  cp "$src" "$DEST/$name"
  chmod +x "$DEST/$name"
  echo "installed: $DEST/$name"
done
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_install.py -q`
Expected: PASS — `2 passed`.

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/pytest -q`
Expected: PASS — `21 passed` (3 + 2 + 3 + 6 + 5 + 2).

- [ ] **Step 6: Commit**

```bash
git add scripts/hermes/hqa-doctor-watchdog.sh scripts/hermes/hqa-premarket-digest.sh scripts/install.sh tests/test_install.py
git commit -q -m "feat: add cron wrappers and installer"
```

---

### Task 7: Deploy and schedule via Hermes cron (runbook)

> **Requires user confirmation before Step 3** — `hermes cron create` registers real scheduled jobs on the user's machine. They are read-only and fully reversible (`hermes cron delete`), but confirm the cadence/timing first (design-doc §12).

**Files:**
- Modify: none (deployment + verification only).

**Interfaces:**
- Consumes: `scripts/install.sh` (Task 6) and the two module entry points (Tasks 4–5).
- Produces: two live Hermes cron jobs (`hqa-safety-watchdog`, `hqa-premarket-digest`) plus JSONL evidence under `logs/`.

- [ ] **Step 1: Deploy the wrappers**

Run:

```bash
bash /Users/sunyibo/programs/Hermes-quant-agent/scripts/install.sh
```

Expected output:

```
installed: /Users/sunyibo/.hermes/scripts/hqa-doctor-watchdog.sh
installed: /Users/sunyibo/.hermes/scripts/hqa-premarket-digest.sh
```

- [ ] **Step 2: Smoke-test the wrappers by hand (no cron yet)**

Run:

```bash
~/.hermes/scripts/hqa-doctor-watchdog.sh ; echo "watchdog-exit=$?"
~/.hermes/scripts/hqa-premarket-digest.sh ; echo "digest-exit=$?"
tail -n 1 /Users/sunyibo/programs/Hermes-quant-agent/logs/doctor_watchdog.jsonl
tail -n 1 /Users/sunyibo/programs/Hermes-quant-agent/logs/premarket_digest.jsonl
```

Expected:
- Watchdog prints **nothing** (safety baseline nominal) and `watchdog-exit=0`.
- Digest prints a `[HQA] Pre-market digest ...` block with `Safety baseline: NOMINAL` and an `Options radar (sample): ... candidates=1000` line, then `digest-exit=0`.
- Each `tail` shows one JSONL record whose `"alert"` is `false` (watchdog) / whose `"options"` contains `"candidates": "1000"` (digest).

- [ ] **Step 3: Schedule the jobs (after user confirmation)**

Run:

```bash
hermes cron create '30m' \
  --name hqa-safety-watchdog \
  --script hqa-doctor-watchdog.sh --no-agent \
  --deliver local \
  --workdir /Users/sunyibo/programs/Hermes-quant-agent

hermes cron create '0 8 * * *' \
  --name hqa-premarket-digest \
  --script hqa-premarket-digest.sh --no-agent \
  --deliver local \
  --workdir /Users/sunyibo/programs/Hermes-quant-agent
```

- [ ] **Step 4: Verify the jobs are registered and fire**

Run:

```bash
hermes cron list
hermes cron tick        # runs any due jobs once and exits
```

Expected: `hermes cron list` shows both jobs with `Mode: no-agent`. After `tick`, the digest job (if due) delivers its block to the `local` channel and the watchdog stays silent unless a `safety.*` invariant deviates. New JSONL lines are appended under `logs/`.

- [ ] **Step 5: Record the rollback command (no execution)**

Rollback if needed:

```bash
# hermes cron delete hqa-safety-watchdog
# hermes cron delete hqa-premarket-digest
```

- [ ] **Step 6: Commit the runbook note**

```bash
git add docs/plans/2026-07-01-phase-0a-readonly-digital-employee.md
git commit -q -m "docs: mark Phase 0a deploy runbook complete"
```

---

## Phase 0a Acceptance (maps to design-doc §10 / §11)

- [ ] Does not trigger paper-account mutating APIs, backtest, rebalance, or strategy-sleeve execution.
- [ ] Does not access any real trading API.
- [ ] Watchdog is `[SILENT]` — no output unless a `safety.*` invariant deviates or `doctor` fails.
- [ ] Every run emits a timestamped JSONL record with data source (`doctor` / `sample scan`), safety status, and a "read-only" scope note.
- [ ] Only `quant-system doctor` and `quant-system options daily-scan --provider sample` are invoked; both run with `cwd=<ai-quant-platform>`.
- [ ] `./.venv/bin/pytest -q` is green (`21 passed`).

---

## Self-Review

**1. Spec coverage (design doc §10 Phase 0a / §11):**
- "建脚本目录和运行日志目录" → Task 1 (`scripts/`, `logs/`). ✓
- "用绝对路径调用 quant-system doctor" → Task 3 (`QUANT_SYSTEM_BIN` absolute, `cwd=AIQP_DIR`). ✓
- "第一个 [SILENT] watchdog" → Task 4. ✓
- "每日盘前 digest（本地平台状态 + 期权 radar 摘要 + 安全状态）" → Task 5. ✓
- "AI News" → **explicitly deferred** (HTTP-only, no CLI surface) — documented in the header, not silently dropped. ✓
- "结构化日志供 memory/复盘读取" → Task 2 JSONL, written by Tasks 4–5. ✓
- "hermes cron create --workdir ..." → Task 7. ✓
- "先本地日志，必要时再接 Discord" (§12) → `--deliver local` default, Discord deferred. ✓

**2. Placeholder scan:** No `TBD`/`TODO`/"add error handling"/"write tests for the above". Every code step shows complete code; every run step shows the exact command and expected output. The only non-code content (Task 7) is a deploy runbook with exact commands and expected stdout. ✓

**3. Type consistency:** `run_doctor` / `run_options_sample_scan` return `tuple[int, str]` everywhere (Task 3 defines, Tasks 4–5 consume via injection). `parse_safety` returns `dict[str, str]` (Task 4) and is reused in Task 5. `evaluate` returns `(bool, list[str])`, consumed by `build_alert_message` + `run`. `run()` signatures match their `main()` call sites. `append_jsonl(record, path)` argument order is identical across all call sites. Wrapper filenames (`hqa-doctor-watchdog.sh`, `hqa-premarket-digest.sh`) are identical in Task 6 files, the installer glob, and the Task 7 `--script` flags. ✓
