# Phase 1a-0 — Platform Wiring (Real-Data Spine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two platform-side dead ends that block Scenes A/B on real data — wire `--provider` through `experiment run-config`, and give approved candidate factors a loader into the `FactorRegistry` — then stand up the ops prerequisites and a one-week futu scan-distribution collection that Phase 1a-1 thresholds will be derived from.

**Architecture:** Tasks 1–3 modify **ai-quant-platform** (repo `/Users/sunyibo/programs/ai-quant-platform`, its own git + `.venv/bin/pytest`): a new `agent/promotion.py` module becomes the first consumer of `SafetyGate.allow_promotion` (exec-loads *human-approved* candidate factor sources into a registry), and `experiment run-config` gains `--provider` / `--include-approved-candidates` passthrough into the already-existing `run_experiment(provider=..., data_source=...)` seam. Task 4 adds a Hermes-side collection wrapper (`options daily-task --provider futu`). Task 5 is a human-gated ops runbook (keys, OpenD, collection cron, threshold review).

**Tech Stack:** Platform: Python 3.11+/typer/pydantic/pandas, tests via `./.venv/bin/pytest`. Hermes: bash wrapper only (no new `hqa` code). Futu OpenD local gateway · Tiingo EOD REST.

## Global Constraints

- **Safety red line unchanged:** no trading-chain calls anywhere in this phase. `run-config` is research/backtest only; the loader only *reads* candidates and only when a human-created `approved.lock` exists. **No code path may create or bypass an approval lock** (`SafetyGate` stays observation-only).
- **Candidate code execution is gated:** `exec` of candidate factor source is allowed **only** for candidates where `SafetyGate.allow_promotion(candidate_id)` is true, and only after a static forbidden-import check (`socket`, `subprocess`, `urllib`, `requests`, `http`, `os`). This is defense-in-depth behind the human review gate, not a sandbox.
- **Backward compatibility:** `experiment run-config` defaults stay `--provider sample`, `--include-approved-candidates` off — existing behavior and tests unchanged.
- **Credentials:** `QS_TIINGO_API_TOKEN` / `QS_OPENAI_API_KEY` are typed by the human into the platform `.env`; never pasted into chat, never committed, never in LLM context.
- **Platform test convention:** run `./.venv/bin/python -m pytest -q` from the platform repo root (the `python -m pytest` form is required — some test modules use `from tests...` / `from scripts...` imports that only resolve with the repo root on `sys.path`; the bare `./.venv/bin/pytest` console-script fails to collect them). Record the baseline count before Task 1 and require baseline+new at the end (platform suite is large — never skip the full run). Note: the platform `main` baseline carries 3 pre-existing, unrelated failures (a Python 3.12 `FakeThread(name=...)` signature mismatch in `test_api_options_radar.py`, and a frontend schema-export drift in `test_frontend_backend_response_type_exports.py`) plus 2 skipped; these predate Phase 1a-0 and are out of scope — acceptance is "baseline + new, no NEW failures", not literal zero failures.
- **Hermes repo baseline:** Phase 0b executed → `42 passed, 1 skipped` (the skip is `test_run_doctor_integration_real`, gated to manual because it needs a working `quant-system` environment). Task 4 modifies `tests/test_install.py` (wrapper list grows to 3); the adversarial-review remediation added one regression-guard test, so post-1a-0 the Hermes count is `43 passed, 1 skipped`.
- **Absolute paths:** platform = `/Users/sunyibo/programs/ai-quant-platform`; Hermes repo = `/Users/sunyibo/programs/Hermes-quant-agent`; CLI = `<platform>/ai-quant/bin/quant-system`.

---

## File Structure

```
ai-quant-platform/                                  (Tasks 1–3, platform git)
  src/quant_system/
    cli.py                       # MODIFY: run-config gains --provider / --include-approved-candidates
    agent/promotion.py           # NEW: load_approved_factor_candidates(registry, candidates_dir)
    experiments/runner.py        # MODIFY: thread factor_registry through to _create_factors
  tests/
    test_cli_experiment_provider.py   # NEW
    test_agent_promotion.py           # NEW

Hermes-quant-agent/                                 (Task 4, Hermes git)
  scripts/hermes/hqa-options-collect.sh   # NEW: daily futu scan collection wrapper
  tests/test_install.py                   # MODIFY: 3 wrappers expected
```

---

### Task 1: Platform — `experiment run-config` provider passthrough

**Files:**
- Modify: `src/quant_system/cli.py` (`run_config_experiment_command`, lines ~646–662)
- Test: `tests/test_cli_experiment_provider.py` (new)

**Interfaces:**
- Consumes (all already exist — verified): `build_ohlcv_provider(settings, *, requested: str | None) -> tuple[HistoricalDataProvider, str]` (`quant_system.data.provider_factory`); `run_experiment(config, *, output_dir=None, provider=None, data_source="sample")`; `reload_settings()` (already imported/used by `refresh-lab`).
- Produces: `quant-system experiment run-config --config <json> [--provider sample|futu|tiingo]` — provider instance + source label reach `run_experiment`; `agent_summary.json` gets `data.source=<label>`.

- [ ] **Step 0: Record the platform baseline**

Run: `cd /Users/sunyibo/programs/ai-quant-platform && ./.venv/bin/pytest -q 2>&1 | tail -1`
Note the exact `N passed` figure; final acceptance requires N + new tests.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_experiment_provider.py`:

```python
from __future__ import annotations

import json

from typer.testing import CliRunner

import quant_system.cli as cli_module
from quant_system.cli import app

runner = CliRunner()

_CONFIG = {
    "experiment_name": "wiring-test",
    "symbols": ["SPY"],
    "start": "2024-01-02",
    "end": "2024-02-15",
    "factor_blend": {"factors": [{"factor_id": "momentum"}]},
}


def _write_config(tmp_path):
    path = tmp_path / "exp.json"
    path.write_text(json.dumps(_CONFIG), encoding="utf-8")
    return path


def test_run_config_passes_provider_to_run_experiment(tmp_path, monkeypatch):
    sentinel = object()
    captured = {}

    monkeypatch.setattr(
        cli_module, "build_ohlcv_provider", lambda settings, *, requested: (sentinel, requested)
    )

    def fake_run_experiment(config, *, output_dir=None, provider=None, data_source="sample", **kwargs):
        captured.update(provider=provider, data_source=data_source)

        class _R:
            experiment_id = "e-1"
            run_count = 1
            best_run_id = "run-1"
            config_path = tmp_path / "c"
            runs_path = tmp_path / "r"
            folds_path = tmp_path / "f"
            agent_summary_path = tmp_path / "a.json"
            report_path = tmp_path / "rep.md"

        return _R()

    monkeypatch.setattr(cli_module, "run_experiment", fake_run_experiment)

    result = runner.invoke(
        app, ["experiment", "run-config", "--config", str(_write_config(tmp_path)), "--provider", "tiingo"]
    )
    assert result.exit_code == 0, result.output
    assert captured["provider"] is sentinel
    assert captured["data_source"] == "tiingo"


def test_run_config_defaults_to_sample(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cli_module, "build_ohlcv_provider", lambda settings, *, requested: (object(), requested)
    )

    def fake_run_experiment(config, **kwargs):
        captured.update(kwargs)

        class _R:
            experiment_id = "e-1"
            run_count = 1
            best_run_id = None
            config_path = tmp_path / "c"
            runs_path = tmp_path / "r"
            folds_path = tmp_path / "f"
            agent_summary_path = tmp_path / "a.json"
            report_path = tmp_path / "rep.md"

        return _R()

    monkeypatch.setattr(cli_module, "run_experiment", fake_run_experiment)

    result = runner.invoke(app, ["experiment", "run-config", "--config", str(_write_config(tmp_path))])
    assert result.exit_code == 0, result.output
    assert captured["data_source"] == "sample"
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_cli_experiment_provider.py -q`
Expected: FAIL — `AttributeError: module 'quant_system.cli' has no attribute 'build_ohlcv_provider'` (or unexpected-option error for `--provider`).

- [ ] **Step 3: Modify `src/quant_system/cli.py`.**

Add to imports (near the other `quant_system.data` imports):

```python
from quant_system.data.provider_factory import build_ohlcv_provider
```

Replace `run_config_experiment_command` with:

```python
@experiment_app.command("run-config")
def run_config_experiment_command(
    config_path: Annotated[
        str,
        typer.Option("--config", help="Path to an experiment JSON config file."),
    ],
    output_dir: Annotated[
        str | None,
        typer.Option(
            help="Override output directory. Defaults to QS_DATA_DIR/QS_REPORTS_DIR settings.",
        ),
    ] = None,
    provider: Annotated[
        Literal["sample", "futu", "tiingo"],
        typer.Option("--provider", help="OHLCV data provider for the experiment."),
    ] = "sample",
) -> None:
    """Run a Phase 4 experiment from a JSON config file."""
    config = load_experiment_config(config_path)
    settings = reload_settings()
    provider_instance, data_source = build_ohlcv_provider(settings, requested=provider)
    result = run_experiment(
        config,
        output_dir=output_dir,
        provider=provider_instance,
        data_source=data_source,
    )
    _emit_experiment_summary(result)
```

(`Literal` is already imported by `cli.py` for `refresh-lab`; verify, otherwise add `from typing import Literal`.)

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_cli_experiment_provider.py -q`
Expected: PASS — `2 passed`.

- [ ] **Step 5: Commit (platform repo)**

```bash
cd /Users/sunyibo/programs/ai-quant-platform
git add src/quant_system/cli.py tests/test_cli_experiment_provider.py
git commit -q -m "feat(experiment): wire --provider through run-config to run_experiment"
```

---

### Task 2: Platform — approved-candidate factor loader (`agent/promotion.py`)

**Files:**
- Create: `src/quant_system/agent/promotion.py`
- Test: `tests/test_agent_promotion.py` (new)

**Interfaces:**
- Consumes: `SafetyGate(candidates_dir).allow_promotion(candidate_id) -> bool`; `FactorRegistry.register(cls)` (raises `ValueError` on duplicate id); `BaseFactor`; candidate layout written by `CandidatePool.write_candidate` (`<candidates_dir>/<candidate_id>/factor.py.candidate` + `metadata.json`; `approved.lock` created only by human `agent review`).
- Produces: `load_approved_factor_candidates(registry: FactorRegistry, *, candidates_dir: str | Path) -> list[str]` — loads **approved-only** factor candidates into `registry`, returns newly registered `factor_id`s; skips unapproved/duplicate; raises `CandidateLoadError` on forbidden imports.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_promotion.py`:

```python
from __future__ import annotations

import pytest

from quant_system.agent.promotion import CandidateLoadError, load_approved_factor_candidates
from quant_system.factors.registry import build_default_factor_registry

_FACTOR_SRC = '''
from quant_system.factors.base import BaseFactor, FactorMetadata


class WiringTestFactor(BaseFactor):
    factor_id = "wiring_test_factor"
    factor_name = "Wiring Test Factor"
    factor_version = "0.1.0-candidate"
    description = "test candidate"

    @property
    def metadata(self) -> FactorMetadata:
        return FactorMetadata(
            factor_id=self.factor_id,
            factor_name=self.factor_name,
            factor_version=self.factor_version,
            description=self.description,
        )

    def _compute_values(self, ohlcv):
        return ohlcv["close"] * 0.0
'''


def _write_candidate(root, candidate_id, source, approved):
    cdir = root / candidate_id
    cdir.mkdir(parents=True)
    (cdir / "factor.py.candidate").write_text(source, encoding="utf-8")
    (cdir / "metadata.json").write_text("{}", encoding="utf-8")
    if approved:
        (cdir / "approved.lock").write_text("{}", encoding="utf-8")


def test_loads_only_approved_candidates(tmp_path):
    _write_candidate(tmp_path, "cand-approved", _FACTOR_SRC, approved=True)
    _write_candidate(tmp_path, "cand-pending", _FACTOR_SRC.replace("wiring_test_factor", "other_id"), approved=False)
    registry = build_default_factor_registry()
    loaded = load_approved_factor_candidates(registry, candidates_dir=tmp_path)
    assert loaded == ["wiring_test_factor"]
    assert registry.create("wiring_test_factor") is not None
    with pytest.raises(KeyError):
        registry.create("other_id")


def test_duplicate_registration_is_skipped_idempotently(tmp_path):
    _write_candidate(tmp_path, "cand-a", _FACTOR_SRC, approved=True)
    registry = build_default_factor_registry()
    assert load_approved_factor_candidates(registry, candidates_dir=tmp_path) == ["wiring_test_factor"]
    assert load_approved_factor_candidates(registry, candidates_dir=tmp_path) == []


def test_forbidden_import_raises(tmp_path):
    bad = "import subprocess\n" + _FACTOR_SRC
    _write_candidate(tmp_path, "cand-bad", bad, approved=True)
    registry = build_default_factor_registry()
    with pytest.raises(CandidateLoadError):
        load_approved_factor_candidates(registry, candidates_dir=tmp_path)


def test_missing_dir_returns_empty(tmp_path):
    registry = build_default_factor_registry()
    assert load_approved_factor_candidates(registry, candidates_dir=tmp_path / "nope") == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_agent_promotion.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'quant_system.agent.promotion'`.

- [ ] **Step 3: Create `src/quant_system/agent/promotion.py`:**

```python
"""First consumer of the SafetyGate: load human-approved candidate factors.

The gate stays observation-only — this module NEVER creates approval locks;
it only loads factor sources for candidates a human has already approved via
``quant-system agent review --decision approve``.
"""

from __future__ import annotations

from pathlib import Path

from quant_system.agent.safety import SafetyGate
from quant_system.factors.base import BaseFactor
from quant_system.factors.registry import FactorRegistry

_FORBIDDEN_SNIPPETS = (
    "import socket",
    "import subprocess",
    "import urllib",
    "import requests",
    "import http",
    "import os",
    "from socket",
    "from subprocess",
    "from urllib",
    "from requests",
    "from http",
    "from os",
)


class CandidateLoadError(RuntimeError):
    """A candidate factor source failed the static safety check."""


def load_approved_factor_candidates(
    registry: FactorRegistry,
    *,
    candidates_dir: str | Path,
) -> list[str]:
    root = Path(candidates_dir)
    if not root.exists():
        return []
    gate = SafetyGate(root)
    loaded: list[str] = []
    for candidate_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        source_path = candidate_dir / "factor.py.candidate"
        if not source_path.exists():
            continue
        if not gate.allow_promotion(candidate_dir.name):
            continue
        source = source_path.read_text(encoding="utf-8")
        lowered = source.lower()
        for snippet in _FORBIDDEN_SNIPPETS:
            if snippet in lowered:
                raise CandidateLoadError(
                    f"candidate {candidate_dir.name!r} contains forbidden code: {snippet!r}"
                )
        namespace: dict[str, object] = {}
        # Human-approved candidate (approved.lock verified above); static check passed.
        exec(compile(source, str(source_path), "exec"), namespace)  # noqa: S102
        for value in namespace.values():
            if isinstance(value, type) and issubclass(value, BaseFactor) and value is not BaseFactor:
                try:
                    registry.register(value)
                except ValueError:
                    continue  # already registered — idempotent reload
                loaded.append(value.factor_id)
    return loaded
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_agent_promotion.py -q`
Expected: PASS — `4 passed`.

- [ ] **Step 5: Commit (platform repo)**

```bash
git add src/quant_system/agent/promotion.py tests/test_agent_promotion.py
git commit -q -m "feat(agent): approved-candidate factor loader (first SafetyGate consumer)"
```

---

### Task 3: Platform — thread `factor_registry` into experiments + CLI flag

**Files:**
- Modify: `src/quant_system/experiments/runner.py` (`run_experiment`, `_run_combination`, `_run_single_backtest`, `_create_factors`)
- Modify: `src/quant_system/cli.py` (`run_config_experiment_command` from Task 1)
- Test: extend `tests/test_agent_promotion.py`

**Interfaces:**
- Produces: `run_experiment(config, *, output_dir=None, provider=None, data_source="sample", factor_registry: FactorRegistry | None = None)` — `None` keeps today's `build_default_factor_registry()` behavior; `quant-system experiment run-config ... --include-approved-candidates` loads approved candidates into the registry before running and echoes `approved_candidates_loaded=<ids|none>`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_agent_promotion.py`:

```python
def test_run_experiment_accepts_candidate_factor_registry(tmp_path):
    from quant_system.experiments.config import load_experiment_config
    from quant_system.experiments.runner import run_experiment
    import json

    _write_candidate(tmp_path / "cands", "cand-a", _FACTOR_SRC, approved=True)
    registry = build_default_factor_registry()
    load_approved_factor_candidates(registry, candidates_dir=tmp_path / "cands")

    config_payload = {
        "experiment_name": "candidate-e2e",
        "symbols": ["SPY", "QQQ"],
        "start": "2024-01-02",
        "end": "2024-03-15",
        "factor_blend": {"factors": [{"factor_id": "wiring_test_factor"}, {"factor_id": "momentum"}]},
    }
    config_file = tmp_path / "exp.json"
    config_file.write_text(json.dumps(config_payload), encoding="utf-8")

    result = run_experiment(
        load_experiment_config(config_file),
        output_dir=tmp_path / "out",
        factor_registry=registry,
    )
    assert result.run_count >= 1
    assert result.agent_summary_path.exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_agent_promotion.py -q`
Expected: FAIL — `TypeError: run_experiment() got an unexpected keyword argument 'factor_registry'`.

- [ ] **Step 3: Modify `src/quant_system/experiments/runner.py`.**

1. `run_experiment(...)` signature gains `factor_registry: FactorRegistry | None = None` (import `FactorRegistry` from `quant_system.factors.registry`); pass `factor_registry=factor_registry` into every `_run_combination(...)` call.
2. `_run_combination(...)` and `_run_single_backtest(...)` each gain the keyword `factor_registry: FactorRegistry | None = None` and pass it down.
3. `_create_factors(config, *, lookback, registry: FactorRegistry | None = None)`:

```python
def _create_factors(config: ExperimentConfig, *, lookback: int, registry: FactorRegistry | None = None):
    active_registry = registry or build_default_factor_registry()
    return [
        active_registry.create(factor.factor_id, lookback=lookback)
        for factor in config.factor_blend.factors
    ]
```

4. In `src/quant_system/cli.py`, extend the Task-1 command with:

```python
    include_approved_candidates: Annotated[
        bool,
        typer.Option(
            "--include-approved-candidates",
            help="Load human-approved agent candidate factors into the registry.",
        ),
    ] = False,
```

and before `run_experiment`:

```python
    factor_registry = None
    if include_approved_candidates:
        factor_registry = build_default_factor_registry()
        candidates_dir = Path(settings.data.data_dir) / "agent" / "candidates"
        loaded = load_approved_factor_candidates(factor_registry, candidates_dir=candidates_dir)
        typer.echo(f"approved_candidates_loaded={','.join(loaded) or '<none>'}")
```

then pass `factor_registry=factor_registry` to `run_experiment`. Add imports: `load_approved_factor_candidates` (from `quant_system.agent.promotion`), `build_default_factor_registry` (from `quant_system.factors.registry`; check — `cli.py` may already import it), `Path` (already imported).

- [ ] **Step 4: Run to verify it passes + platform full suite**

Run: `./.venv/bin/pytest tests/test_agent_promotion.py tests/test_cli_experiment_provider.py -q`
Expected: PASS — `7 passed`.

Run: `./.venv/bin/pytest -q 2>&1 | tail -1`
Expected: baseline (Task 1 Step 0) + 7, no failures.

- [ ] **Step 5: Commit (platform repo)**

```bash
git add src/quant_system/experiments/runner.py src/quant_system/cli.py tests/test_agent_promotion.py
git commit -q -m "feat(experiment): factor_registry injection + --include-approved-candidates"
```

---

### Task 4: Hermes — futu scan-collection wrapper

**Files:**
- Create: `scripts/hermes/hqa-options-collect.sh`
- Modify: `tests/test_install.py`
- **Implementation deviation (recorded by adversarial review):** `scripts/install.sh` was ALSO modified — against this plan's original "no installer change" note — to substitute a new `__HQA_PLATFORM_DIR__` placeholder (resolved from `HQA_AIQP_DIR`, matching `hqa/config.py`) in addition to `__HQA_REPO_DIR__`. This made the collect wrapper portable instead of hardcoding `/Users/sunyibo/...`, consistent with the existing `__HQA_REPO_DIR__` convention. The deviation is strictly better than the plan's hardcoded-paths prescription and was committed in `167f407`; a regression-guard test now locks in that both placeholders are substituted at deploy time.

**Interfaces:**
- Consumes: `scripts/install.sh` `hqa-*.sh` glob (auto-picks new wrappers; now also substitutes `__HQA_PLATFORM_DIR__` — see deviation note above).
- Produces: wrapper running `quant-system options daily-task --provider futu` with `cwd=<platform>` — refreshes universe/earnings/VIX then scans real chains, appending artifacts to platform `data/options_scans/{date}.jsonl` + `_meta.json`. Phase 1a-1's watchdog and the Task-5 threshold review both read these artifacts.

- [ ] **Step 1: Update the failing test** — in `tests/test_install.py` change the expected wrapper list to:

```python
    names = sorted(p.name for p in dest.glob("hqa-*.sh"))
    assert names == [
        "hqa-doctor-watchdog.sh",
        "hqa-options-collect.sh",
        "hqa-premarket-digest.sh",
    ]
```

and extend the escape-check loop to the same three names.

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/sunyibo/programs/Hermes-quant-agent && ./.venv/bin/pytest tests/test_install.py -q`
Expected: FAIL — glob finds only 2 wrappers.

- [ ] **Step 3: Create `scripts/hermes/hqa-options-collect.sh`:**

```bash
#!/bin/bash
# HQA options scan collection (real futu chains; requires OpenD running).
set -euo pipefail
cd /Users/sunyibo/programs/ai-quant-platform
exec /Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/quant-system \
  options daily-task --provider futu "$@"
```

`chmod +x scripts/hermes/hqa-options-collect.sh`

- [ ] **Step 4: Run to verify it passes + full Hermes suite**

Run: `./.venv/bin/pytest tests/test_install.py -q` → PASS.
Run: `./.venv/bin/pytest -q -o addopts=""` → `43 passed` (0b baseline; test_install modified, not added).

- [ ] **Step 5: Commit (Hermes repo)**

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent
git add scripts/hermes/hqa-options-collect.sh tests/test_install.py
git commit -q -m "feat: futu options-scan collection wrapper"
```

---

### Task 5: Ops runbook — keys, OpenD, collection cron, threshold review (HUMAN-GATED)

**Files:** none (runbook). Every step below **requires user confirmation** before execution; credential values are typed by the human directly, never through the agent.

- [ ] **Step 1: Configure platform credentials (human types values)**

In `/Users/sunyibo/programs/ai-quant-platform/.env` set: `QS_TIINGO_API_TOKEN=<human>`, `QS_OPENAI_API_KEY=<human>` (model override optional: `QS_OPENAI_MODEL`). Verify with `quant-system config show` (keys must appear masked).

- [ ] **Step 2: OpenD availability during US market hours**

- Start Futu OpenD locally (default `127.0.0.1:11111`); keep it running Beijing ~21:00–04:30 on trading days (install-futu-opend skill can assist).
- Keep the Mac awake in that window (`caffeinate -s` in a login session, Amphetamine, or Energy Saver schedule).
- Smoke check: `quant-system options daily-scan --provider futu --top 5` during market hours exits 0 and reports `candidates>0`.

- [ ] **Step 3: Deploy + schedule the collection cron (user confirms)**

```bash
bash /Users/sunyibo/programs/Hermes-quant-agent/scripts/install.sh
# Once per trading day, mid-session (Beijing 23:00, Mon–Fri):
hermes cron create '0 23 * * 1-5' --name hqa-options-collect \
  --script hqa-options-collect.sh --no-agent --deliver local \
  --workdir /Users/sunyibo/programs/Hermes-quant-agent
hermes cron list
```

Rollback: `hermes cron delete hqa-options-collect`.

> **Ops resolution (2026-07-03, verified):** the default Hermes cron script timeout (120s)
> killed the first collect run and left a stale `options_radar_scan.lock` blocking later
> scans. Fixes applied: (a) `~/.hermes/config.yaml` → `cron.script_timeout_seconds: 3600`;
> (b) wrapper capped at `--top 100` — futu rate limit ≈33s/symbol → 100 symbols ≈56min
> fits the timeout (full 516-symbol universe ≈4.8h does not; top-100 distribution is
> sufficient for D-15 statistics); (c) stale-lock removal is part of failure recovery — if a
> collect run dies, check `pgrep -fl daily-task` and remove
> `<platform>/data/options_scans/options_radar_scan.lock` before the next run.
> End-to-end smoke verified with OpenD up: `--top 5` → `candidates=42, completed` in 167s.
> Gateway must be running (`hermes cron status`) or no cron fires.

- [ ] **Step 4: After ≥4 trading days — distribution review (threshold decision, D-15)**

```bash
cd /Users/sunyibo/programs/ai-quant-platform && python3 - <<'EOF'
import json, glob, statistics
rows = [json.loads(l) for f in sorted(glob.glob("data/options_scans/*.jsonl"))
        for l in open(f, encoding="utf-8") if l.strip()]
scores = sorted(r["global_score"] for r in rows if r.get("global_score") is not None)
ivs = sorted(r["iv_rank"] for r in rows if r.get("iv_rank") is not None)
pct = lambda xs, p: xs[int(p / 100 * (len(xs) - 1))] if xs else None
print(f"n={len(rows)} days={len(set(r['run_date'] for r in rows))}")
print("global_score p50/p80/p90/p95:", [pct(scores, p) for p in (50, 80, 90, 95)])
print("iv_rank      p50/p80/p90/p95:", [pct(ivs, p) for p in (50, 80, 90, 95)])
EOF
```

Choose `--min-score` / `--min-iv-rank` (recommended starting point: p90 of each — alerts ≈ top-decile setups only), then **record the decision in the 0b review log**:

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent
python3 -m hqa.review_cli draft --kind manual --event "Scene-A thresholds chosen" \
  --data min_score=<X> --data min_iv_rank=<Y> --data basis_days=<N>
python3 -m hqa.review_cli confirm <id> --judgment "top-decile alerts only" \
  --basis "p90 of <N>-day futu scan distribution" --result "thresholds set" \
  --failure-point "" --next-rule "revisit after 2 weeks of live alerts"
```

This decision unblocks Phase 1a-1's signal watchdog leaving collect-only mode.

---

## Phase 1a-0 Acceptance

- [x] Platform: `experiment run-config --provider tiingo|futu` reaches `run_experiment` (agent_summary `data.source` reflects it, asserted by `test_api_experiments.py`); default `sample` behavior unchanged.
- [x] Platform: approved-only candidate loading proven by tests (pending candidates never load; forbidden imports raise; reload idempotent); e2e test runs an experiment blending a candidate factor with `momentum`; walk-forward threading locked by an additional test. **Adversarial-review hardening:** the original substring blocklist was replaced by an AST import-allowlist + restricted `__builtins__` (guarded `__import__`) after review reproduced a load-time RCE via `importlib`/`__import__`/`eval`; `--include-approved-candidates` was fixed to read the agent CLI's real candidates dir (`data/agent_run/agent/candidates`).
- [x] No code path creates/bypasses approval locks; `SafetyGate` untouched.
- [x] Platform full suite: baseline + new tests pass, no NEW failures (3 pre-existing unrelated failures on `main` predate this phase — see Global Constraints).
- [x] Hermes: 3 wrappers installed; `43 passed, 1 skipped` (skip is the manual `quant-system` integration test).
- [ ] Ops: keys masked in `config show`; futu smoke scan `candidates>0`; collection cron running; after ≥4 trading days a confirmed review entry records the thresholds. **(human-gated, Task 5 — pending user execution)**

## Self-Review

**1. Dead-end closure:** run-config→provider (Task 1) and approved-candidate→registry (Tasks 2–3) directly close the two verified platform dead ends; Task-3 e2e test proves the Scene-B chain propose→approve→registry→experiment is closed.
**2. Safety:** loader consumes but never writes locks; exec gated by human approval + AST import-allowlist + restricted `__builtins__` (hardened post-review from a bypassable substring denylist); run-config default unchanged; no trading calls.
**3. Placeholder scan:** `<human>`/`<X>`/`<Y>`/`<N>`/`<id>` appear only in the human ops runbook (Task 5), by design.
**4. Type consistency:** `build_ohlcv_provider -> tuple[provider, str]` matches CLI unpack; `FactorRegistry.register` ValueError-on-duplicate handled as idempotent skip; `run_experiment(factor_registry=None)` default preserves existing callers.
