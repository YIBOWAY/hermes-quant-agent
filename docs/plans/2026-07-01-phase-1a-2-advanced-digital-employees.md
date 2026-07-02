# Phase 1a-2 — Advanced Digital Employees Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the advanced research employees — the Scene-B paper-factor reproduction pipeline (real LLM translation + mandatory human gates + real-data backtest), an options-radar summary, and an AI-HOT alerts watchdog — all proposal-only, nothing auto-promoted.

**Architecture:** Extend `hqa/` (Phases 0a/0b/1a-0/1a-1). New modules: `factor_repro` (parsers for the `agent propose-factor --llm openai` → human `agent review` → `experiment run-config --provider tiingo --include-approved-candidates` chain shipped by 1a-0), `factor_repro_cli` (the human-gated Scene-B CLI), `options_radar` (structured scan summary, futu), `aihot_alerts` (`[SILENT]` news watchdog reusing `hqa.aihot`). The safety-critical property: **no code path auto-approves a factor translation** — approval is a separate, human-only CLI invocation, and the Scene-B backtest runs on real EOD history (Tiingo), never on synthetic sample data.

**Tech Stack:** Python 3.9.6 (stdlib only) · `pytest` in `.venv` · platform `quant-system` CLI (`agent propose-factor --llm openai`/`list-candidates`/`review`, `experiment run-config --provider tiingo --include-approved-candidates`, `options daily-scan --provider futu`).

## Global Constraints

- **Proposal-only, TWO human gates (Scene B, D-5):** gate 1 — the paper→goal distillation is confirmed by the human in the Hermes session before `propose` runs; gate 2 — the LLM/automation may `propose` and `backtest`, but MUST NOT `approve` a factor translation (`agent review --decision approve` is human-only). Backtest results land in the review pool + Discord; promotion is a human decision.
- **Real-data policy (D-14, needs 1a-0):** Scene-B proposes with `--llm openai` (`QS_OPENAI_API_KEY` in the platform `.env`; the `stub` LLM appears only inside unit tests) and backtests via `experiment run-config --provider tiingo --include-approved-candidates` on real EOD history (`QS_TIINGO_API_TOKEN`). `backtest run-sample` is NOT used — it is hardwired to synthetic data.
- **Read-only trading boundary:** only `agent propose-factor/list-candidates/review`, `experiment run-config` (research backtest), `options daily-scan` are invoked. `agent review` writes only an approval lock (no trade). No order/account/rebalance.
- **Silent contract:** the AI-HOT alerts watchdog prints only when notable items exist; always logs; always exits 0.
- **AI HOT access (D-6):** reuse `hqa.aihot` (standalone public API, browser UA).
- **Python 3.9 compat:** every module starts with `from __future__ import annotations`.
- **Baseline before this phase:** `61 passed, 1 skipped` (after Phase 1a-1).

---

## File Structure

```
hqa/
  quant_cli.py         # + run_propose_factor(llm), run_list_candidates, run_agent_review, run_experiment_config
  factor_repro.py      # NEW: parse_candidate_id(), parse_experiment_summary(), extract_best_run_metrics()
  factor_repro_cli.py  # NEW: hqa-factor-repro propose|approve|backtest (human gates)
  options_radar.py     # NEW: build_radar_summary(), run(), main()  (futu)
  aihot_alerts.py      # NEW: select_notable(), run(), main()
scripts/hermes/
  hqa-options-radar.sh     # NEW wrapper
  hqa-aihot-alerts.sh      # NEW wrapper
tests/
  test_quant_cli.py         # MODIFY
  test_factor_repro.py      # NEW
  test_factor_repro_cli.py  # NEW
  test_options_radar.py     # NEW
  test_aihot_alerts.py      # NEW
  test_install.py           # MODIFY: 7 wrappers now
```

---

### Task 1: quant_cli — Scene-B chain wrappers

**Files:** Modify `hqa/quant_cli.py`, `tests/test_quant_cli.py`

**Interfaces:**
- Produces (all `-> tuple[int, str]`, merged streams, `cwd=AIQP_DIR`):
  - `run_propose_factor(goal, universe="SPY,QQQ", llm="openai")` → `agent propose-factor --goal <goal> --universe <u> --llm <llm>` (real runs use openai; tests inject fakes)
  - `run_list_candidates()` → `agent list-candidates`
  - `run_agent_review(candidate_id, decision, note)` → `agent review --candidate-id <id> --decision <approve|reject> --note <note>`
  - `run_experiment_config(config_path, provider="tiingo", include_approved=True)` → `experiment run-config --config <path> --provider <p> [--include-approved-candidates]` (1a-0 wiring)

- [ ] **Step 1: Write the failing test** — append to `tests/test_quant_cli.py`:

```python
def test_run_propose_factor_argv(monkeypatch):
    seen = {}
    monkeypatch.setattr(quant_cli.subprocess, "run",
                        lambda argv, **k: seen.update(argv=argv) or _FakeProc(0, "candidate_id=factor-x-1 status=pending"))
    code, out = quant_cli.run_propose_factor("momentum 20d", "SPY,QQQ")
    assert code == 0
    assert seen["argv"][1:] == ["agent", "propose-factor", "--goal", "momentum 20d",
                                "--universe", "SPY,QQQ", "--llm", "openai"]


def test_run_agent_review_argv(monkeypatch):
    seen = {}
    monkeypatch.setattr(quant_cli.subprocess, "run",
                        lambda argv, **k: seen.update(argv=argv) or _FakeProc(0, "ok"))
    quant_cli.run_agent_review("factor-x-1", "approve", "translation confirmed")
    assert seen["argv"][1:] == ["agent", "review", "--candidate-id", "factor-x-1",
                                "--decision", "approve", "--note", "translation confirmed"]


def test_run_experiment_config_argv(monkeypatch):
    seen = {}
    monkeypatch.setattr(quant_cli.subprocess, "run",
                        lambda argv, **k: seen.update(argv=argv) or _FakeProc(0, "experiment_id=e-1"))
    quant_cli.run_experiment_config("/tmp/exp.json", provider="tiingo")
    assert seen["argv"][1:] == ["experiment", "run-config", "--config", "/tmp/exp.json",
                                "--provider", "tiingo", "--include-approved-candidates"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_quant_cli.py -q`
Expected: FAIL — `AttributeError: module 'hqa.quant_cli' has no attribute 'run_propose_factor'`.

- [ ] **Step 3: Add to `hqa/quant_cli.py`:**

```python
def run_propose_factor(goal: str, universe: str = "SPY,QQQ", llm: str = "openai", bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["agent", "propose-factor", "--goal", goal, "--universe", universe, "--llm", llm], bin_path=bin_path, cwd=cwd)


def run_list_candidates(bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["agent", "list-candidates"], bin_path=bin_path, cwd=cwd)


def run_agent_review(candidate_id: str, decision: str, note: str, bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["agent", "review", "--candidate-id", candidate_id, "--decision", decision, "--note", note], bin_path=bin_path, cwd=cwd)


def run_experiment_config(config_path: str, provider: str = "tiingo", include_approved: bool = True, bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    args = ["experiment", "run-config", "--config", config_path, "--provider", provider]
    if include_approved:
        args.append("--include-approved-candidates")
    return _run(args, bin_path=bin_path, cwd=cwd)
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_quant_cli.py -q`
Expected: PASS — `8 passed` (5 prior + 3 new).

- [ ] **Step 5: Commit**

```bash
git add hqa/quant_cli.py tests/test_quant_cli.py
git commit -q -m "feat: quant_cli Scene-B chain wrappers (propose/review/run-config)"
```

---

### Task 2: factor_repro — candidate + experiment parsers

**Files:** Create `hqa/factor_repro.py`, `tests/test_factor_repro.py`

**Interfaces:**
- Produces: `parse_candidate_id(output: str) -> Optional[str]`; `parse_experiment_summary(output: str) -> dict[str, str]` (the `experiment_id=... best_run_id=... agent_summary=... report=...` line); `extract_best_run_metrics(agent_summary_json: str) -> dict[str, float]` (`sharpe`, `total_return`, `max_drawdown` of the best run).

- [ ] **Step 1: Write the failing test**

Create `tests/test_factor_repro.py`:

```python
from __future__ import annotations

import json

from hqa import factor_repro as fr

PROPOSE_OUT = "candidate_id=factor-momentum_20d_reversal-323b045e4b status=pending path=data/agent_run/... metadata=..."
SUMMARY_OUT = (
    "approved_candidates_loaded=wiring_test_factor\n"
    "experiment_id=factor-repro-20260702T000000Z run_count=1 best_run_id=run-001 "
    "config=/x/config.json runs=/x/runs.parquet folds=/x/folds.parquet "
    "agent_summary=/x/agent_summary.json report=/x/report.md"
)
AGENT_SUMMARY = json.dumps({
    "best_run_id": "run-001",
    "runs": [
        {"run_id": "run-001", "sharpe": 1.42, "total_return": 0.183, "max_drawdown": 0.061},
        {"run_id": "run-002", "sharpe": 0.7, "total_return": 0.05, "max_drawdown": 0.09},
    ],
})


def test_parse_candidate_id():
    assert fr.parse_candidate_id(PROPOSE_OUT) == "factor-momentum_20d_reversal-323b045e4b"


def test_parse_candidate_id_missing_returns_none():
    assert fr.parse_candidate_id("no id here") is None


def test_parse_experiment_summary():
    s = fr.parse_experiment_summary(SUMMARY_OUT)
    assert s["experiment_id"] == "factor-repro-20260702T000000Z"
    assert s["best_run_id"] == "run-001"
    assert s["agent_summary"] == "/x/agent_summary.json"


def test_extract_best_run_metrics():
    m = fr.extract_best_run_metrics(AGENT_SUMMARY)
    assert m == {"sharpe": 1.42, "total_return": 0.183, "max_drawdown": 0.061}
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_factor_repro.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.factor_repro'`.

- [ ] **Step 3: Create `hqa/factor_repro.py`:**

```python
from __future__ import annotations

import json
import re
from typing import Optional

_CANDIDATE_RE = re.compile(r"candidate_id=(\S+)")
_METRIC_KEYS = ("sharpe", "total_return", "max_drawdown")


def parse_candidate_id(output: str) -> Optional[str]:
    match = _CANDIDATE_RE.search(output)
    return match.group(1) if match else None


def parse_experiment_summary(output: str) -> dict[str, str]:
    for line in output.splitlines():
        if "experiment_id=" in line:
            return {
                key: value
                for key, _, value in (tok.partition("=") for tok in line.split() if "=" in tok)
            }
    return {}


def extract_best_run_metrics(agent_summary_json: str) -> dict[str, float]:
    data = json.loads(agent_summary_json)
    best_id = data.get("best_run_id")
    for run in data.get("runs", []):
        if run.get("run_id") == best_id:
            return {key: run[key] for key in _METRIC_KEYS if key in run}
    return {}
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_factor_repro.py -q`
Expected: PASS — `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/factor_repro.py tests/test_factor_repro.py
git commit -q -m "feat: Scene-B candidate-id and experiment-summary parsers"
```

---

### Task 3: factor_repro_cli — human-gated Scene-B CLI

**Files:** Create `hqa/factor_repro_cli.py`, `tests/test_factor_repro_cli.py`

**Interfaces:**
- Produces: `main(argv=None) -> int` with subcommands:
  - `propose --goal <text> [--universe SPY,QQQ]` → runs propose-factor (`--llm openai` via the Task-1 default), prints candidate_id + an explicit "HUMAN GATE" reminder. (Gate 1 — the paper→goal distillation — happens in the Hermes session BEFORE this command; see the runbook.)
  - `approve --candidate-id <id> --note <text>` → runs `agent review --decision approve` — **human-only translation gate (gate 2)**.
  - `backtest --factor-id <id> --symbol S [--symbol S] --start <> --end <> [--provider tiingo] [--config-out <path>]` → writes an experiment config referencing the approved candidate factor, runs `experiment run-config --provider <p> --include-approved-candidates` (1a-0), reads the platform `agent_summary.json`, prints best-run metrics + "proposal-only".
- There is deliberately **no** subcommand that chains propose→approve→backtest automatically.

- [ ] **Step 1: Write the failing test**

Create `tests/test_factor_repro_cli.py`:

```python
from __future__ import annotations

from hqa import factor_repro_cli as cli


def test_propose_prints_candidate_id_and_human_gate(monkeypatch, capsys):
    monkeypatch.setattr(cli.quant_cli, "run_propose_factor",
                        lambda goal, universe="SPY,QQQ": (0, "candidate_id=factor-x-1 status=pending"))
    rc = cli.main(["propose", "--goal", "momentum 20d reversal"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "factor-x-1" in out
    assert "HUMAN GATE" in out  # reminds a human must inspect & approve the translation


def test_approve_invokes_agent_review_approve(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli.quant_cli, "run_agent_review",
                        lambda cid, decision, note: seen.update(cid=cid, decision=decision, note=note) or (0, "ok"))
    rc = cli.main(["approve", "--candidate-id", "factor-x-1", "--note", "translation confirmed"])
    assert rc == 0
    assert seen == {"cid": "factor-x-1", "decision": "approve", "note": "translation confirmed"}


def test_backtest_builds_config_runs_experiment_and_prints_metrics(monkeypatch, capsys, tmp_path):
    import json

    summary_file = tmp_path / "agent_summary.json"
    summary_file.write_text(json.dumps({
        "best_run_id": "run-001",
        "runs": [{"run_id": "run-001", "sharpe": 1.42, "total_return": 0.183, "max_drawdown": 0.061}],
    }), encoding="utf-8")
    seen = {}

    def fake_run_experiment_config(config_path, provider="tiingo", include_approved=True):
        seen.update(config_path=config_path, provider=provider)
        return (0, f"experiment_id=e-1 run_count=1 best_run_id=run-001 config=/x runs=/x folds=/x "
                   f"agent_summary={summary_file} report=/x/report.md")

    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", fake_run_experiment_config)
    config_out = tmp_path / "exp.json"
    rc = cli.main(["backtest", "--factor-id", "wiring_test_factor", "--symbol", "SPY", "--symbol", "QQQ",
                   "--start", "2024-01-02", "--end", "2025-06-30", "--config-out", str(config_out)])
    assert rc == 0
    written = json.loads(config_out.read_text(encoding="utf-8"))
    assert written["factor_blend"]["factors"] == [{"factor_id": "wiring_test_factor"}]
    assert written["symbols"] == ["SPY", "QQQ"]
    assert seen["provider"] == "tiingo"
    out = capsys.readouterr().out
    assert "sharpe=1.42" in out
    assert "proposal-only" in out.lower()


def test_no_auto_pipeline_subcommand():
    import pytest
    # There must be no 'auto'/'pipeline' command that bypasses the human gate.
    with pytest.raises(SystemExit):
        cli.main(["auto"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_factor_repro_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.factor_repro_cli'`.

- [ ] **Step 3: Create `hqa/factor_repro_cli.py`:**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from hqa import config, factor_repro, quant_cli


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="hqa-factor-repro", description="Scene-B factor reproduction (proposal-only, human-gated)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_propose = sub.add_parser("propose")
    p_propose.add_argument("--goal", required=True)
    p_propose.add_argument("--universe", default="SPY,QQQ")

    p_approve = sub.add_parser("approve")
    p_approve.add_argument("--candidate-id", required=True)
    p_approve.add_argument("--note", required=True)

    p_backtest = sub.add_parser("backtest")
    p_backtest.add_argument("--factor-id", required=True, help="factor_id of the APPROVED candidate")
    p_backtest.add_argument("--symbol", action="append", required=True, dest="symbols")
    p_backtest.add_argument("--start", required=True)
    p_backtest.add_argument("--end", required=True)
    p_backtest.add_argument("--provider", default="tiingo")
    p_backtest.add_argument("--config-out", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "propose":
        _, out = quant_cli.run_propose_factor(args.goal, args.universe)
        candidate_id = factor_repro.parse_candidate_id(out)
        print(f"candidate_id={candidate_id}")
        print("HUMAN GATE: inspect the generated candidate factor and confirm the translation is correct")
        print("            before approving. Run: hqa-factor-repro approve --candidate-id <id> --note <...>")
        return 0

    if args.cmd == "approve":
        # Human-only translation gate (gate 2). Automation must never call this.
        code, out = quant_cli.run_agent_review(args.candidate_id, "approve", args.note)
        print(out.strip() or f"approved: {args.candidate_id}")
        return 0 if code == 0 else 1

    if args.cmd == "backtest":
        config_out = Path(args.config_out) if args.config_out else (
            config.REPO_DIR / "data" / "_runtime" / "experiments" / f"{args.factor_id}.json"
        )
        config_out.parent.mkdir(parents=True, exist_ok=True)
        experiment = {
            "experiment_name": f"factor-repro-{args.factor_id}",
            "symbols": args.symbols,
            "start": args.start,
            "end": args.end,
            "factor_blend": {"factors": [{"factor_id": args.factor_id}]},
        }
        config_out.write_text(json.dumps(experiment, indent=2), encoding="utf-8")
        code, out = quant_cli.run_experiment_config(str(config_out), provider=args.provider)
        summary = factor_repro.parse_experiment_summary(out)
        metrics: dict[str, float] = {}
        summary_path = summary.get("agent_summary")
        if summary_path:
            path = Path(summary_path)
            if not path.is_absolute():
                path = config.AIQP_DIR / path
            try:
                metrics = factor_repro.extract_best_run_metrics(path.read_text(encoding="utf-8"))
            except OSError:
                metrics = {}
        print(f"experiment_id={summary.get('experiment_id', '?')} best_run_id={summary.get('best_run_id', '?')}")
        for key in ("sharpe", "total_return", "max_drawdown"):
            print(f"{key}={metrics.get(key, '?')}")
        print(f"report={summary.get('report', '?')}")
        print("Results are proposal-only; promotion to the review pool is a human decision.")
        return 0 if code == 0 else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_factor_repro_cli.py -q`
Expected: PASS — `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/factor_repro_cli.py tests/test_factor_repro_cli.py
git commit -q -m "feat: human-gated Scene-B factor-reproduction CLI"
```

---

### Task 4: options_radar — structured scan summary

**Files:** Create `hqa/options_radar.py`, `tests/test_options_radar.py`

**Interfaces:**
- Produces: `build_radar_summary(scan: dict, ts: str) -> str`; `run(run_scan, now_iso, log_path) -> str`; `main(argv=None) -> int` (always prints, returns 0; `--provider` defaults to `futu` per D-14). Delivered to `#期权radar`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_options_radar.py`:

```python
from __future__ import annotations

import json

from hqa import options_radar as orad

SCAN_OUT = "run_date=2026-07-01 universe_size=100 scanned_tickers=100 failed_tickers=0 candidates=1000 data=x meta=y"


def test_build_radar_summary_has_counts():
    text = orad.build_radar_summary({"universe_size": "100", "scanned": "100", "failed": "0", "candidates": "1000"}, "2026-07-01T00:00:00Z")
    assert "Options radar" in text
    assert "candidates=1000" in text
    assert "proposal-only" in text.lower()


def test_run_logs_and_returns_summary(tmp_path):
    log_path = tmp_path / "or.jsonl"
    text = orad.run(run_scan=lambda: (0, SCAN_OUT), now_iso=lambda: "2026-07-01T00:00:00Z", log_path=log_path)
    assert "candidates=1000" in text
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "options-radar"
    assert record["options"]["candidates"] == "1000"
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_options_radar.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.options_radar'`.

- [ ] **Step 3: Create `hqa/options_radar.py`:**

```python
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable, Optional

from hqa import config, quant_cli, runlog
from hqa.premarket_digest import parse_scan_summary


def build_radar_summary(scan: dict[str, str], ts: str) -> str:
    if not scan:
        return f"[HQA] Options radar {ts}: scan summary unavailable"
    return (
        f"[HQA] Options radar {ts}\n"
        f"  universe={scan.get('universe_size', '?')} scanned={scan.get('scanned', '?')} "
        f"failed={scan.get('failed', '?')} candidates={scan.get('candidates', '?')}\n"
        f"  Scope: read-only options research. Proposal-only."
    )


def run(run_scan: Callable[[], tuple[int, str]], now_iso: Callable[[], str], log_path: Path) -> str:
    scan_exit, scan_out = run_scan()
    scan = parse_scan_summary(scan_out)
    ts = now_iso()
    runlog.append_jsonl({"ts": ts, "job": "options-radar", "scan_exit": scan_exit, "options": scan}, log_path)
    return build_radar_summary(scan, ts)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA options radar summary (read-only)")
    parser.add_argument("--provider", default="futu")
    parser.add_argument("--log", default=str(config.LOG_DIR / "options_radar.jsonl"))
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    try:
        summary = run(lambda: quant_cli.run_options_scan(args.provider), runlog.utc_now_iso, log_path)
    except Exception as exc:
        ts = runlog.utc_now_iso()
        print(f"[HQA] Options radar {ts}: FAILED ({exc!r})")
        return 0
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_options_radar.py -q`
Expected: PASS — `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/options_radar.py tests/test_options_radar.py
git commit -q -m "feat: options-radar structured summary employee"
```

---

### Task 5: aihot_alerts — `[SILENT]` AI-HOT alerts watchdog

**Files:** Create `hqa/aihot_alerts.py`, `tests/test_aihot_alerts.py`

**Interfaces:**
- Produces: `select_notable(items: list[dict], min_score=70, categories=None) -> list[dict]`; `run(run_aihot, now_iso, log_path, min_score=70) -> tuple[bool, str]`; `main(argv=None) -> int` (prints only when notable; returns 0).

- [ ] **Step 1: Write the failing test**

Create `tests/test_aihot_alerts.py`:

```python
from __future__ import annotations

import json

from hqa import aihot_alerts as aa

PAYLOAD = ('{"items":['
           '{"title":"big","source":"S","url":"u","publishedAt":"t","category":"industry","score":90},'
           '{"title":"small","source":"S","url":"u2","publishedAt":"t","category":"industry","score":30}]}')


def test_select_notable_filters_by_score():
    from hqa import aihot
    items = aihot.parse_items(PAYLOAD)
    notable = aa.select_notable(items, min_score=70)
    assert [i["title"] for i in notable] == ["big"]


def test_run_alerts_when_notable(tmp_path):
    log_path = tmp_path / "aa.jsonl"
    has_alert, message = aa.run(run_aihot=lambda: PAYLOAD, now_iso=lambda: "2026-07-01T00:00:00Z", log_path=log_path)
    assert has_alert is True
    assert "big" in message
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "aihot-alerts"
    assert record["notable"] == ["big"]


def test_run_silent_when_nothing_notable(tmp_path):
    payload = '{"items":[{"title":"small","source":"S","url":"u","publishedAt":"t","category":"c","score":10}]}'
    has_alert, message = aa.run(run_aihot=lambda: payload, now_iso=lambda: "2026-07-01T00:00:00Z", log_path=tmp_path / "aa.jsonl")
    assert has_alert is False
    assert message == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_aihot_alerts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.aihot_alerts'`.

- [ ] **Step 3: Create `hqa/aihot_alerts.py`:**

```python
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable, Optional

from hqa import aihot, config, runlog


def select_notable(items: list[dict[str, Any]], min_score: int = 70, categories: Optional[list[str]] = None) -> list[dict[str, Any]]:
    result = []
    for item in items:
        score = item.get("score") or 0
        if score >= min_score and (categories is None or item.get("category") in categories):
            result.append(item)
    return result


def run(
    run_aihot: Callable[[], str],
    now_iso: Callable[[], str],
    log_path: Path,
    min_score: int = 70,
) -> tuple[bool, str]:
    items = aihot.parse_items(run_aihot())
    notable = select_notable(items, min_score=min_score)
    ts = now_iso()
    runlog.append_jsonl(
        {"ts": ts, "job": "aihot-alerts", "notable": [i.get("title") for i in notable]},
        log_path,
    )
    if not notable:
        return False, ""
    lines = [f"[HQA] AI HOT alerts {ts}"]
    for i in notable[:8]:
        lines.append(f"  - [{i.get('category', '?')}·{i.get('score', '?')}] {i.get('title', '?')} ({i.get('source', '?')})")
    return True, "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA AI-HOT alerts watchdog ([SILENT] unless notable)")
    parser.add_argument("--min-score", type=int, default=70)
    parser.add_argument("--log", default=str(config.LOG_DIR / "aihot_alerts.jsonl"))
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    try:
        has_alert, message = run(
            lambda: aihot.fetch_items(take=50),
            runlog.utc_now_iso,
            log_path,
            min_score=args.min_score,
        )
    except Exception as exc:  # unattended job: never crash the scheduler
        ts = runlog.utc_now_iso()
        runlog.append_jsonl({"ts": ts, "job": "aihot-alerts", "error": repr(exc)}, log_path)
        print(f"[HQA] AI HOT alerts failed to run {ts}: {exc!r}")
        return 0
    if has_alert:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_aihot_alerts.py -q`
Expected: PASS — `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/aihot_alerts.py tests/test_aihot_alerts.py
git commit -q -m "feat: AI-HOT alerts watchdog (silent unless notable)"
```

---

### Task 6: Deploy wrappers + cron + full suite

**Files:** Create `scripts/hermes/hqa-options-radar.sh`, `scripts/hermes/hqa-aihot-alerts.sh`; Modify `tests/test_install.py`

- [ ] **Step 1: Update `tests/test_install.py`** — the wrapper set is now seven:

```python
    names = sorted(p.name for p in dest.glob("hqa-*.sh"))
    assert names == [
        "hqa-aihot-alerts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-options-collect.sh",
        "hqa-options-radar.sh",
        "hqa-premarket-digest.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ]
```

And extend the escape-check loop to the same seven names.

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_install.py -q`
Expected: FAIL — the glob finds only 5 wrappers.

- [ ] **Step 3: Create the two wrappers.**

`scripts/hermes/hqa-options-radar.sh`:

```bash
#!/bin/bash
# HQA options-radar summary wrapper.
set -euo pipefail
cd /Users/sunyibo/programs/Hermes-quant-agent
exec /usr/bin/env python3 -m hqa.options_radar "$@"
```

`scripts/hermes/hqa-aihot-alerts.sh`:

```bash
#!/bin/bash
# HQA AI-HOT alerts watchdog wrapper.
set -euo pipefail
cd /Users/sunyibo/programs/Hermes-quant-agent
exec /usr/bin/env python3 -m hqa.aihot_alerts "$@"
```

- [ ] **Step 4: Run to verify it passes + full suite**

Run: `./.venv/bin/pytest tests/test_install.py -q`
Expected: PASS — `3 passed`.

Run: `./.venv/bin/pytest -q -o addopts=""`
Expected: PASS — `77 passed, 1 skipped` (61 baseline + 16 new: 3 quant_cli + 4 factor_repro + 4 factor_repro_cli + 2 options_radar + 3 aihot_alerts; test_install stays 3 tests, modified not added).

- [ ] **Step 5: Commit**

```bash
git add scripts/hermes/hqa-options-radar.sh scripts/hermes/hqa-aihot-alerts.sh tests/test_install.py
git commit -q -m "feat: options-radar + aihot-alerts wrappers"
```

- [ ] **Step 6: Deploy runbook (requires user confirmation before creating cron jobs)**

```bash
bash /Users/sunyibo/programs/Hermes-quant-agent/scripts/install.sh

# Options radar: daily after the scan, Beijing 21:00 (pre-US-open); to #期权radar
hermes cron create '0 21 * * *' --name hqa-options-radar \
  --script hqa-options-radar.sh --no-agent \
  --deliver discord:<CH_OPTIONS>  --workdir /Users/sunyibo/programs/Hermes-quant-agent

# AI-HOT alerts: every 2h; [SILENT] unless notable; to a news channel
hermes cron create 'every 2h' --name hqa-aihot-alerts \
  --script hqa-aihot-alerts.sh --no-agent \
  --deliver discord:<CH_NEWS>  --workdir /Users/sunyibo/programs/Hermes-quant-agent

hermes cron list
```

The Scene-B factor-reproduction flow is **human-run on demand** (not scheduled). Prerequisites: Phase 1a-0 executed; `QS_OPENAI_API_KEY` + `QS_TIINGO_API_TOKEN` configured in the platform `.env`.

```text
GATE 1 — paper→goal distillation (in the Hermes chat session):
  1. You send the paper (PDF/link/formula) to Hermes.
  2. Hermes drafts: (a) a one-paragraph factor definition in plain math/pseudocode,
     (b) the --goal string for propose-factor.
  3. YOU confirm the distillation matches the paper (or correct it).
     If Hermes cannot state the factor unambiguously it must answer
     "需人工补充定义" — never guess.
```

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent
# LLM translation (openai) — produces an inert candidate + audit log:
python3 -m hqa.factor_repro_cli propose --goal "<confirmed goal string>"

# GATE 2 — read the generated code before approving:
#   cat /Users/sunyibo/programs/ai-quant-platform/data/agent/candidates/<id>/factor.py.candidate
#   note the factor_id defined inside — you need it for the backtest step
python3 -m hqa.factor_repro_cli approve --candidate-id <id> --note "translation confirmed"

# Real-data backtest (Tiingo EOD, 1a-0 wiring; longer window = more meaningful stats):
python3 -m hqa.factor_repro_cli backtest --factor-id <factor_id> \
  --symbol SPY --symbol QQQ --start 2024-01-02 --end 2026-06-30
```

Sanity rule: a **plausible** sharpe (roughly |sharpe| < 4) is expected on real data; an absurd value (e.g. >10) usually means data or translation problems — open a 0b review entry instead of celebrating.

Rollback: `hermes cron delete hqa-options-radar` / `hermes cron delete hqa-aihot-alerts`.

---

## Phase 1a-2 Acceptance (maps to spec §2.1/§2.5, Scene B)

- [ ] Scene B runs distill (gate 1, in-session) → propose (`--llm openai`) → **human approve (gate 2)** → real-data backtest (`run-config --provider tiingo --include-approved-candidates`) → report; no code path auto-approves; results are proposal-only.
- [ ] `hqa-factor-repro` has no auto/pipeline subcommand that bypasses the human gates (test `test_no_auto_pipeline_subcommand`).
- [ ] The backtest step never invokes `backtest run-sample` / synthetic data; metrics come from the platform `agent_summary.json` of a real-provider experiment.
- [ ] Options radar delivers a structured, read-only summary (futu) to `#期权radar`.
- [ ] AI-HOT alerts is `[SILENT]` unless notable (score ≥ threshold); always logs; always exits 0.
- [ ] Only `agent propose-factor/list-candidates/review`, `experiment run-config`, `options daily-scan` invoked; no order/account/rebalance.
- [ ] `./.venv/bin/pytest -q` green.

---

## Self-Review

**1. Spec coverage (spec §2, 1a-2 subset):** options-radar summary (Task 4, futu) ✓; AI-HOT alerts employee (Task 5, D-6) ✓; Scene-B factor reproduction with real LLM + real-data backtest and two human gates (Tasks 1–3, D-5/D-14) ✓. KOL/social monitoring correctly absent (D-6 deferred).

**2. Placeholder scan:** No TBD/TODO; all code + tests complete; `<CH_...>`, `<id>`, `<factor_id>`, `<confirmed goal string>` are human-supplied runbook values with explicit surrounding instructions, not code placeholders.

**3. Type consistency:** Scene-B wrappers `run_propose_factor(goal, universe, llm)/run_agent_review/run_experiment_config -> tuple[int,str]` (Task 1) consumed in Task 3. `parse_candidate_id -> Optional[str]` / `parse_experiment_summary -> dict[str,str]` / `extract_best_run_metrics -> dict[str,float]` (Task 2) consumed in Task 3. `run_options_scan` (from 1a-1, futu default) reused in Task 4. `aihot.parse_items` (1a-1) reused in Task 5.

**4. Human-gate integrity:** Verified `approve` is a discrete human-only subcommand; `propose` prints a HUMAN GATE reminder; gate 1 (distillation confirm) is written into the runbook protocol; no chaining command exists (enforced by `test_no_auto_pipeline_subcommand`). Backtest output is labeled proposal-only and sourced from a real-data experiment.
