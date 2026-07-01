# Phase 1a-1 — Core Digital Employees Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the core read-only research employees — an AI-HOT news client, an upgraded pre-market digest, a Scene-A market-signal watchdog, and a weekly review report — all proposal-only, never touching the trading chain.

**Architecture:** Extend the `hqa/` package (Phases 0a/0b). New modules: `aihot` (stdlib `urllib` client for the public AI HOT REST API), `signals` (Scene-A signal parsing/evaluation), `signal_watchdog` (`[SILENT]` market-signal job, distinct from the 0a safety watchdog), and `weekly_review` (aggregates the 0b review-log + 0a/1a run-logs). The pre-market digest gains an AI-HOT headlines section. Delivery uses Hermes cron `--deliver` (Discord with local fallback).

**Tech Stack:** Python 3.9.6 (stdlib only — `urllib` for HTTP) · `pytest` in `.venv` · platform `quant-system` CLI (`options daily-scan`, `factor refresh-lab`) run with `cwd=<ai-quant-platform>`.

## Global Constraints

- **Read-only / proposal-only:** only `options daily-scan` and `factor refresh-lab` are invoked (both read-only research); no order/account/rebalance/backtest-execution; no platform HTTP; no auth.
- **Two watchdogs are distinct:** 0a `doctor_watchdog` watches `safety.*` invariants; this phase's `signal_watchdog` watches *market signals*. They must not be conflated.
- **AI HOT access (D-6):** standalone public REST API `https://aihot.virxact.com/api/public/items?mode=selected` — anonymous but a browser `User-Agent` header is REQUIRED (else 403). No platform HTTP.
- **Silent contract:** the signal watchdog prints to stdout ONLY when a signal fires; always appends a JSONL run record; always exits 0.
- **Hermetic tests:** network + subprocess are dependency-injected; unit tests use canned fixtures; real-network/real-CLI tests are `skipif`-guarded.
- **Python 3.9 compat:** every module starts with `from __future__ import annotations`.
- **Baseline before this phase:** `43 passed` (after Phase 0b).

---

## File Structure

```
hqa/
  quant_cli.py         # + run_options_scan(provider), run_factor_lab()
  aihot.py             # NEW: fetch_items(), parse_items()
  premarket_digest.py  # MODIFY: optional AI-HOT headlines section
  signals.py           # NEW: parse_factor_lab(), evaluate_signals()
  signal_watchdog.py   # NEW: Scene-A [SILENT] market-signal watchdog
  weekly_review.py     # NEW: aggregate review-log + run-logs
scripts/hermes/
  hqa-signal-watchdog.sh   # NEW wrapper
  hqa-weekly-review.sh     # NEW wrapper
tests/
  test_quant_cli.py    # MODIFY: + new wrappers
  test_aihot.py            # NEW
  test_premarket_digest.py # MODIFY: + headlines
  test_signals.py          # NEW
  test_signal_watchdog.py  # NEW
  test_weekly_review.py    # NEW
  test_install.py          # MODIFY: 4 wrappers now
```

---

### Task 1: quant_cli — options-scan(provider) + factor-lab wrappers

**Files:** Modify `hqa/quant_cli.py`, `tests/test_quant_cli.py`

**Interfaces:**
- Produces: `run_options_scan(provider: str = "sample", ...) -> tuple[int, str]` (runs `options daily-scan --provider <provider>`); `run_factor_lab(...) -> tuple[int, str]` (runs `factor refresh-lab`). Both merge streams, `cwd=AIQP_DIR`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_quant_cli.py`:

```python
def test_run_options_scan_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "candidates=1000\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_options_scan("sample")
    assert code == 0
    assert seen["argv"][1:] == ["options", "daily-scan", "--provider", "sample"]


def test_run_factor_lab_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "cross_rows=5 timing_rows=5\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_factor_lab()
    assert code == 0
    assert seen["argv"][1:] == ["factor", "refresh-lab"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_quant_cli.py -q`
Expected: FAIL — `AttributeError: module 'hqa.quant_cli' has no attribute 'run_options_scan'`.

- [ ] **Step 3: Add to `hqa/quant_cli.py`** (after `run_options_sample_scan`):

```python
def run_options_scan(provider: str = "sample", bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["options", "daily-scan", "--provider", provider], bin_path=bin_path, cwd=cwd)


def run_factor_lab(bin_path: Optional[Path] = None, cwd: Optional[Path] = None) -> tuple[int, str]:
    return _run(["factor", "refresh-lab"], bin_path=bin_path, cwd=cwd)
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_quant_cli.py -q`
Expected: PASS — `5 passed` (3 original + 2 new).

- [ ] **Step 5: Commit**

```bash
git add hqa/quant_cli.py tests/test_quant_cli.py
git commit -q -m "feat: quant_cli options-scan(provider) and factor-lab wrappers"
```

---

### Task 2: aihot — AI HOT REST client

**Files:** Create `hqa/aihot.py`, `tests/test_aihot.py`

**Interfaces:**
- Produces: `parse_items(payload: str) -> list[dict]` (extract `title/source/url/publishedAt/category/score` from each item); `fetch_items(since=None, take=20, base_url=BASE_URL, ua=BROWSER_UA, timeout=20) -> str` (GET `/api/public/items?mode=selected` with the required browser UA).

- [ ] **Step 1: Write the failing test**

Create `tests/test_aihot.py`:

```python
from __future__ import annotations

import pytest

from hqa import aihot

SAMPLE = """{
  "count": 2, "hasNext": true, "nextCursor": "x",
  "items": [
    {"id": "a", "title": "Meta 出售算力", "title_en": "Meta compute",
     "url": "https://techcrunch.com/x", "permalink": "p", "source": "TechCrunch",
     "publishedAt": "2026-07-01T13:43:07.000Z", "summary": "...", "category": "industry", "score": 72, "selected": true},
    {"id": "b", "title": "Cloudflare AI 流量", "title_en": "CF",
     "url": "https://blog.cloudflare.com/y", "permalink": "p2", "source": "Cloudflare Blog",
     "publishedAt": "2026-07-01T13:00:00.000Z", "summary": "...", "category": "ai-products", "score": 58, "selected": true}
  ]
}"""


def test_parse_items_extracts_whitelisted_fields():
    items = aihot.parse_items(SAMPLE)
    assert len(items) == 2
    assert items[0] == {
        "title": "Meta 出售算力", "source": "TechCrunch",
        "url": "https://techcrunch.com/x", "publishedAt": "2026-07-01T13:43:07.000Z",
        "category": "industry", "score": 72,
    }
    # never leaks unlisted fields
    assert "summary" not in items[0]


def test_parse_items_empty_payload():
    assert aihot.parse_items('{"items": []}') == []


@pytest.mark.skipif(True, reason="network; flip to run a live smoke test manually")
def test_fetch_items_live_smoke():
    payload = aihot.fetch_items(take=2)
    assert '"items"' in payload
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_aihot.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.aihot'`.

- [ ] **Step 3: Create `hqa/aihot.py`:**

```python
from __future__ import annotations

import json
import urllib.request
from typing import Any, Optional

BASE_URL = "https://aihot.virxact.com"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_ITEM_FIELDS = ("title", "source", "url", "publishedAt", "category", "score")


def parse_items(payload: str) -> list[dict[str, Any]]:
    data = json.loads(payload)
    return [{k: item.get(k) for k in _ITEM_FIELDS} for item in data.get("items", [])]


def fetch_items(
    since: Optional[str] = None,
    take: int = 20,
    base_url: str = BASE_URL,
    ua: str = BROWSER_UA,
    timeout: int = 20,
) -> str:
    url = f"{base_url}/api/public/items?mode=selected&take={int(take)}"
    if since:
        url += f"&since={since}"
    request = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https host, GET only)
        return response.read().decode("utf-8")
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_aihot.py -q`
Expected: PASS — `2 passed, 1 skipped`.

- [ ] **Step 5: Commit**

```bash
git add hqa/aihot.py tests/test_aihot.py
git commit -q -m "feat: AI HOT REST client (stdlib urllib, browser UA)"
```

---

### Task 3: Pre-market digest — AI-HOT headlines section

**Files:** Modify `hqa/premarket_digest.py`, `tests/test_premarket_digest.py`

**Interfaces:**
- Modified: `build_digest(safety, scan, ts, headlines=None)` — when `headlines` (a list of item dicts) is provided, append a "Top AI headlines" section; when `None`, unchanged.
- Modified: `run(run_doctor, run_scan, now_iso, log_path, run_aihot=None)` — when `run_aihot` is provided, fetch+parse headlines and include them; logs only headline titles (parsed), never raw payload.

- [ ] **Step 1: Write the failing test** — append to `tests/test_premarket_digest.py`:

```python
def test_build_digest_includes_headlines_when_provided():
    from hqa.doctor_watchdog import parse_safety

    heads = [{"title": "Meta compute", "source": "TC", "url": "u", "publishedAt": "t", "category": "industry", "score": 72}]
    text = pd.build_digest(parse_safety(DOCTOR_SAMPLE), pd.parse_scan_summary(SCAN_SAMPLE), "2026-07-01T00:00:00Z", headlines=heads)
    assert "AI headlines" in text
    assert "Meta compute" in text


def test_run_with_aihot_logs_titles_not_payload(tmp_path):
    import json

    log_path = tmp_path / "d.jsonl"
    payload = '{"items":[{"title":"H1","source":"S","url":"u","publishedAt":"t","category":"c","score":9}]}'
    text = pd.run(
        run_doctor=lambda: (0, DOCTOR_SAMPLE),
        run_scan=lambda: (0, SCAN_SAMPLE),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
        run_aihot=lambda: payload,
    )
    assert "H1" in text
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["headlines"] == ["H1"]           # titles only
    assert "items" not in json.dumps(record)       # no raw payload persisted
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_premarket_digest.py -q`
Expected: FAIL — `TypeError: build_digest() got an unexpected keyword argument 'headlines'`.

- [ ] **Step 3: Modify `hqa/premarket_digest.py`.**

Add import at top: `from hqa import aihot` (add to the existing `from hqa import ...` line).

Replace `build_digest` with:

```python
def build_digest(safety: dict[str, str], scan: dict[str, str], ts: str, headlines: Optional[list[dict]] = None) -> str:
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
    if headlines:
        lines.append("Top AI headlines:")
        for h in headlines[:5]:
            lines.append(f"  - [{h.get('category', '?')}] {h.get('title', '?')} ({h.get('source', '?')})")
    lines.append("Scope: read-only research digest. No trading action taken.")
    return "\n".join(lines)
```

Replace `run(...)` with:

```python
def run(
    run_doctor: Callable[[], tuple[int, str]],
    run_scan: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
    run_aihot: Optional[Callable[[], str]] = None,
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
            "safety": safety,
            "options": scan,
            "headlines": [h.get("title") for h in headlines],
        },
        log_path,
    )
    return build_digest(safety, scan, ts, headlines=headlines or None)
```

Update `main()` to pass `run_aihot=aihot.fetch_items`:

```python
        digest = run(
            quant_cli.run_doctor,
            quant_cli.run_options_sample_scan,
            runlog.utc_now_iso,
            log_path,
            run_aihot=aihot.fetch_items,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_premarket_digest.py -q`
Expected: PASS — `7 passed` (5 original still green because `headlines`/`run_aihot` default to no-op + 2 new).

- [ ] **Step 5: Commit**

```bash
git add hqa/premarket_digest.py tests/test_premarket_digest.py
git commit -q -m "feat: digest AI-HOT headlines section (titles-only logging)"
```

---

### Task 4: signals — Scene-A parsing + evaluation

**Files:** Create `hqa/signals.py`, `tests/test_signals.py`

**Interfaces:**
- Produces: `parse_factor_lab(output: str) -> dict[str, str]` (extract `symbol/cross_rows/timing_rows`); `evaluate_signals(scan: dict, factor_lab: dict, min_candidates: int = 1) -> tuple[bool, list[str]]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_signals.py`:

```python
from __future__ import annotations

from hqa import signals

FACTOR_LAB = "cache_status=recomputed cache_path=x universe=etf symbol=QQQ benchmark=QQQ cross_rows=5 timing_rows=5"
SCAN = {"run_date": "2026-07-01", "universe_size": "100", "scanned": "100", "failed": "0", "candidates": "1000"}


def test_parse_factor_lab():
    lab = signals.parse_factor_lab(FACTOR_LAB)
    assert lab == {"symbol": "QQQ", "cross_rows": "5", "timing_rows": "5"}


def test_evaluate_signals_fires_on_candidates_and_cross():
    has_signal, sigs = signals.evaluate_signals(SCAN, signals.parse_factor_lab(FACTOR_LAB))
    assert has_signal is True
    assert any("options radar" in s for s in sigs)
    assert any("factor lab" in s for s in sigs)


def test_evaluate_signals_silent_when_flat():
    has_signal, sigs = signals.evaluate_signals({"candidates": "0"}, {"cross_rows": "0"})
    assert has_signal is False
    assert sigs == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_signals.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.signals'`.

- [ ] **Step 3: Create `hqa/signals.py`:**

```python
from __future__ import annotations

import re
from typing import Any

_FACTOR_LAB_RE = re.compile(
    r"symbol=(?P<symbol>\S+).*?cross_rows=(?P<cross_rows>\d+).*?timing_rows=(?P<timing_rows>\d+)",
    re.DOTALL,
)


def parse_factor_lab(output: str) -> dict[str, str]:
    match = _FACTOR_LAB_RE.search(output)
    return match.groupdict() if match else {}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def evaluate_signals(scan: dict[str, Any], factor_lab: dict[str, Any], min_candidates: int = 1) -> tuple[bool, list[str]]:
    signals: list[str] = []
    if _as_int(scan.get("candidates")) >= min_candidates:
        signals.append(
            f"options radar: {scan.get('candidates')} candidates (universe {scan.get('universe_size', '?')})"
        )
    if _as_int(factor_lab.get("cross_rows")) > 0:
        signals.append(
            f"factor lab: {factor_lab.get('cross_rows')} cross signals on {factor_lab.get('symbol', '?')}"
        )
    return (len(signals) > 0, signals)
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_signals.py -q`
Expected: PASS — `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/signals.py tests/test_signals.py
git commit -q -m "feat: Scene-A signal parsing and evaluation"
```

---

### Task 5: signal_watchdog — Scene-A `[SILENT]` market-signal job

**Files:** Create `hqa/signal_watchdog.py`, `tests/test_signal_watchdog.py`

**Interfaces:**
- Produces: `run(run_scan, run_factor_lab, now_iso, log_path) -> tuple[bool, str]` (writes JSONL; returns `(has_signal, message)`, message empty when silent); `main(argv=None) -> int` (prints only on signal; always returns 0).

- [ ] **Step 1: Write the failing test**

Create `tests/test_signal_watchdog.py`:

```python
from __future__ import annotations

import json

from hqa import signal_watchdog as sw

SCAN_OUT = "run_date=2026-07-01 universe_size=100 scanned_tickers=100 failed_tickers=0 candidates=1000 data=x meta=y"
FLAT_SCAN = "run_date=2026-07-01 universe_size=100 scanned_tickers=100 failed_tickers=0 candidates=0 data=x meta=y"
LAB_OUT = "universe=etf symbol=QQQ cross_rows=5 timing_rows=5"
FLAT_LAB = "universe=etf symbol=QQQ cross_rows=0 timing_rows=0"


def test_run_signal_prints_and_logs(tmp_path):
    log_path = tmp_path / "sw.jsonl"
    has_signal, message = sw.run(
        run_scan=lambda: (0, SCAN_OUT),
        run_factor_lab=lambda: (0, LAB_OUT),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert has_signal is True
    assert "options radar" in message
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["job"] == "signal-watchdog"
    assert record["has_signal"] is True


def test_run_flat_is_silent(tmp_path):
    log_path = tmp_path / "sw.jsonl"
    has_signal, message = sw.run(
        run_scan=lambda: (0, FLAT_SCAN),
        run_factor_lab=lambda: (0, FLAT_LAB),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
    )
    assert has_signal is False
    assert message == ""
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["has_signal"] is False


def test_main_flat_emits_empty_stdout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sw.quant_cli, "run_options_scan", lambda *a, **k: (0, FLAT_SCAN))
    monkeypatch.setattr(sw.quant_cli, "run_factor_lab", lambda *a, **k: (0, FLAT_LAB))
    rc = sw.main(["--log", str(tmp_path / "sw.jsonl")])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_main_survives_exception_and_returns_zero(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("scan blew up")

    monkeypatch.setattr(sw.quant_cli, "run_options_scan", boom)
    rc = sw.main(["--log", str(tmp_path / "sw.jsonl")])
    assert rc == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_signal_watchdog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.signal_watchdog'`.

- [ ] **Step 3: Create `hqa/signal_watchdog.py`:**

```python
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable, Optional

from hqa import config, quant_cli, runlog, signals
from hqa.premarket_digest import parse_scan_summary


def run(
    run_scan: Callable[[], tuple[int, str]],
    run_factor_lab: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
) -> tuple[bool, str]:
    scan_exit, scan_out = run_scan()
    factor_exit, factor_out = run_factor_lab()
    scan = parse_scan_summary(scan_out)
    factor_lab = signals.parse_factor_lab(factor_out)
    has_signal, sigs = signals.evaluate_signals(scan, factor_lab)
    ts = now_iso()
    runlog.append_jsonl(
        {
            "ts": ts,
            "job": "signal-watchdog",
            "scan_exit": scan_exit,
            "factor_exit": factor_exit,
            "has_signal": has_signal,
            "signals": sigs,
        },
        log_path,
    )
    if not has_signal:
        return False, ""
    message = f"[HQA] Scene-A signals {ts}\n" + "\n".join(f"  - {s}" for s in sigs)
    return True, message


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA Scene-A market-signal watchdog ([SILENT] unless signal)")
    parser.add_argument("--provider", default="sample")
    parser.add_argument("--log", default=str(config.LOG_DIR / "signal_watchdog.jsonl"))
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    try:
        has_signal, message = run(
            lambda: quant_cli.run_options_scan(args.provider),
            quant_cli.run_factor_lab,
            runlog.utc_now_iso,
            log_path,
        )
    except Exception as exc:  # unattended job: never crash the scheduler
        ts = runlog.utc_now_iso()
        runlog.append_jsonl({"ts": ts, "job": "signal-watchdog", "error": repr(exc)}, log_path)
        print(f"[HQA] signal watchdog failed to run {ts}: {exc!r}")
        return 0
    if has_signal:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_signal_watchdog.py -q`
Expected: PASS — `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/signal_watchdog.py tests/test_signal_watchdog.py
git commit -q -m "feat: Scene-A market-signal watchdog (silent unless signal)"
```

---

### Task 6: weekly_review — aggregate review-log + run-logs

**Files:** Create `hqa/weekly_review.py`, `tests/test_weekly_review.py`

**Interfaces:**
- Produces: `load_runlog(path: Path) -> list[dict]`; `build_report(alerts: list, signals_fired: list, reviews: list, ts: str) -> str`; `run(review_dir, log_dir, now_iso) -> str`; `main(argv=None) -> int` (always prints report, returns 0).

- [ ] **Step 1: Write the failing test**

Create `tests/test_weekly_review.py`:

```python
from __future__ import annotations

from hqa import reviewlog, weekly_review as wr


def test_build_report_counts_sections():
    text = wr.build_report(
        alerts=[{"ts": "t"}],
        signals_fired=[{"ts": "t"}, {"ts": "t"}],
        reviews=[{"id": "2026-07-01-001", "status": "confirmed", "event": "bad exit", "next_rule": "wait"}],
        ts="2026-07-01T00:00:00Z",
    )
    assert "Weekly review" in text
    assert "safety alerts: 1" in text
    assert "signals fired: 2" in text
    assert "bad exit" in text


def test_run_reads_review_and_run_logs(tmp_path):
    review_dir = tmp_path / "review"
    reviewlog.new_draft("manual", "missed NVDA", {}, "manual", "2026-07-01T00:00:00Z", review_dir)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "doctor_watchdog.jsonl").write_text('{"job":"doctor-watchdog","alert":true}\n', encoding="utf-8")
    (log_dir / "signal_watchdog.jsonl").write_text('{"job":"signal-watchdog","has_signal":true}\n', encoding="utf-8")
    text = wr.run(review_dir=review_dir, log_dir=log_dir, now_iso=lambda: "2026-07-08T00:00:00Z")
    assert "safety alerts: 1" in text
    assert "signals fired: 1" in text
    assert "missed NVDA" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_weekly_review.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.weekly_review'`.

- [ ] **Step 3: Create `hqa/weekly_review.py`:**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Optional

from hqa import config, reviewlog, runlog


def load_runlog(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_report(alerts: list[dict], signals_fired: list[dict], reviews: list[dict], ts: str) -> str:
    lines = [
        f"[HQA] Weekly review {ts}",
        f"- safety alerts: {len(alerts)}",
        f"- signals fired: {len(signals_fired)}",
        f"- review entries: {len(reviews)}",
    ]
    for r in reviews:
        lines.append(f"  · {r.get('id', '?')} [{r.get('status', '?')}] {r.get('event', '')} → next: {r.get('next_rule', '')}")
    lines.append("Scope: read-only weekly summary. Proposal-only.")
    return "\n".join(lines)


def run(review_dir: Path, log_dir: Path, now_iso: Callable[[], str]) -> str:
    reviews = reviewlog.list_entries(review_dir)
    watchdog = load_runlog(log_dir / "doctor_watchdog.jsonl")
    signal = load_runlog(log_dir / "signal_watchdog.jsonl")
    alerts = [r for r in watchdog if r.get("alert")]
    signals_fired = [r for r in signal if r.get("has_signal")]
    return build_report(alerts, signals_fired, reviews, now_iso())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HQA weekly review (read-only, proposal-only)")
    parser.add_argument("--review-dir", default=str(config.REVIEW_DIR))
    parser.add_argument("--log-dir", default=str(config.LOG_DIR))
    args = parser.parse_args(argv)
    try:
        report = run(Path(args.review_dir), Path(args.log_dir), runlog.utc_now_iso)
    except Exception as exc:
        ts = runlog.utc_now_iso()
        print(f"[HQA] Weekly review {ts}: FAILED ({exc!r})")
        return 0
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_weekly_review.py -q`
Expected: PASS — `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/weekly_review.py tests/test_weekly_review.py
git commit -q -m "feat: weekly review aggregating review-log and run-logs"
```

---

### Task 7: Deploy wrappers + cron (Discord with local fallback)

**Files:** Create `scripts/hermes/hqa-signal-watchdog.sh`, `scripts/hermes/hqa-weekly-review.sh`; Modify `tests/test_install.py`

**Interfaces:** Consumes `scripts/install.sh` (its `hqa-*.sh` glob auto-picks the new wrappers). No installer code change.

- [ ] **Step 1: Update the failing test** — in `tests/test_install.py`, change the expected wrapper set:

```python
    names = sorted(p.name for p in dest.glob("hqa-*.sh"))
    assert names == [
        "hqa-doctor-watchdog.sh",
        "hqa-premarket-digest.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ]
```

And extend the escape-check loop names:

```python
    for name in ("hqa-doctor-watchdog.sh", "hqa-premarket-digest.sh", "hqa-signal-watchdog.sh", "hqa-weekly-review.sh"):
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_install.py -q`
Expected: FAIL — the glob finds only 2 wrappers, so the `names == [...4...]` assertion fails.

- [ ] **Step 3: Create the two wrappers.**

`scripts/hermes/hqa-signal-watchdog.sh`:

```bash
#!/bin/bash
# HQA Scene-A market-signal watchdog wrapper.
set -euo pipefail
cd /Users/sunyibo/programs/Hermes-quant-agent
exec /usr/bin/env python3 -m hqa.signal_watchdog "$@"
```

`scripts/hermes/hqa-weekly-review.sh`:

```bash
#!/bin/bash
# HQA weekly review wrapper.
set -euo pipefail
cd /Users/sunyibo/programs/Hermes-quant-agent
exec /usr/bin/env python3 -m hqa.weekly_review "$@"
```

- [ ] **Step 4: Run to verify it passes + full suite**

Run: `./.venv/bin/pytest tests/test_install.py -q`
Expected: PASS — `3 passed` (2 original updated + 1 negative escape-check).

Run: `./.venv/bin/pytest -q -o addopts=""`
Expected: PASS — `58 passed, 1 skipped` (43 baseline + 15 new: 2 quant_cli + 2 aihot + 2 digest + 3 signals + 4 signal_watchdog + 2 weekly_review; test_install stays 3 tests, modified not added; the 1 skipped is the aihot live smoke test).

- [ ] **Step 5: Commit**

```bash
git add scripts/hermes/hqa-signal-watchdog.sh scripts/hermes/hqa-weekly-review.sh tests/test_install.py
git commit -q -m "feat: signal-watchdog + weekly-review wrappers"
```

- [ ] **Step 6: Deploy runbook (requires user confirmation before creating cron jobs)**

Deploy wrappers, then schedule. Discord channels are optional — replace `<CH_...>` with real channel IDs, or use `--deliver local` if Discord is not yet configured (D-7 fallback).

```bash
bash /Users/sunyibo/programs/Hermes-quant-agent/scripts/install.sh

# Scene-A signal watchdog: every 30 min during US market hours (Beijing ~21:30–04:00; adjust for DST)
hermes cron create '*/30 21-23,0-4 * * *' --name hqa-signal-watchdog \
  --script hqa-signal-watchdog.sh --no-agent \
  --deliver discord:<CH_INTRADAY>  --workdir /Users/sunyibo/programs/Hermes-quant-agent

# Weekly review: Sunday 09:00 Beijing
hermes cron create '0 9 * * 0' --name hqa-weekly-review \
  --script hqa-weekly-review.sh --no-agent \
  --deliver discord:<CH_REVIEW>  --workdir /Users/sunyibo/programs/Hermes-quant-agent

hermes cron list
```

Rollback: `hermes cron delete hqa-signal-watchdog` / `hermes cron delete hqa-weekly-review`.

---

## Phase 1a-1 Acceptance (maps to spec §2.1/§2.5)

- [ ] Read-only / proposal-only: only `options daily-scan` + `factor refresh-lab` invoked; no trading calls.
- [ ] Signal watchdog is `[SILENT]` — empty stdout unless a signal fires; every run appends a JSONL record.
- [ ] Digest headlines come from the standalone AI HOT API (browser UA); only titles are persisted (no raw payload).
- [ ] Weekly review reads the 0b review-log + 0a/1a run-logs and summarizes; proposal-only.
- [ ] Discord delivery falls back to `local` when channels are unconfigured.
- [ ] `./.venv/bin/pytest -q` green.

---

## Self-Review

**1. Spec coverage (spec §2, 1a-1 subset):** digest upgrade w/ AI-HOT news (Task 3) ✓; Scene-A signal watchdog distinct from safety watchdog (Task 5) ✓; weekly review reading review-log + run-logs (Task 6) ✓; AI-HOT via standalone API (Task 2, D-6) ✓; Discord + local fallback (Task 7, D-7) ✓. Options-radar *depth*, AI-HOT *alerts* employee, and Scene B are deferred to 1a-2 (correct per D-5).

**2. Placeholder scan:** No TBD/TODO; all code + tests complete; the only `<CH_...>` tokens are in the human deploy runbook (user-supplied channel IDs), explicitly with a local fallback — not a code placeholder.

**3. Type consistency:** `run_options_scan(provider)` / `run_factor_lab()` return `tuple[int, str]` (Task 1) used in Task 5. `parse_items -> list[dict]` (Task 2) used in Task 3. `parse_factor_lab -> dict` / `evaluate_signals -> (bool, list[str])` (Task 4) used in Task 5. `build_digest(..., headlines=None)` / `run(..., run_aihot=None)` optional params keep Phase 0a digest tests valid.

**4. Read-only + silent invariants:** signal watchdog `main()` prints only on signal (test `test_main_flat_emits_empty_stdout`) and never crashes (test `test_main_survives_exception_and_returns_zero`); digest logs titles only (test `test_run_with_aihot_logs_titles_not_payload`).
