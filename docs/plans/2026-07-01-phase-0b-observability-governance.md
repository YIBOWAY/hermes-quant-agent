# Phase 0b — Observability & Governance Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Hermes-layer review/error-log system (the "记得你如何做错过" cognition store) and the broker-sim acceptance-gate checker — both read-only w.r.t. the trading chain.

**Architecture:** Extend the existing `hqa/` package (built in Phase 0a) with three concerns: a `reviewlog` store (JSONL authoritative + Markdown mirror, fixed schema, hybrid auto-draft/human-confirm), a `review_cli` for humans/cron, and a `gate` acceptance-checker. The Phase 0a safety watchdog is extended to auto-draft a review entry on alert (idempotent). No platform calls, no HTTP, no auth — stdlib only.

**Tech Stack:** Python 3.9.6 (stdlib only) · `pytest` in `.venv` · builds directly on the Phase 0a `hqa/` package.

## Global Constraints

- **Read-only red line:** No platform trading calls, no order/account/rebalance, no HTTP. `gate check` only *reads and judges* — it never promotes/releases anything (release is a human decision in Phase 2).
- **Human-judgment integrity (D-4):** The five human fields (`judgment`, `basis`, `result`, `failure_point`, `next_rule`) are NEVER written by any automated/LLM path. Auto-draft fills only machine fields and leaves human fields empty.
- **Layer separation (D-2):** The review store is Hermes-layer, dedicated, separate from the Phase 0a `logs/*.jsonl` run-logs and from the platform review pool.
- **Dual format (D-3):** `review/entries.jsonl` is authoritative; `review/entries.md` is a lossless render from it.
- **Python 3.9 compat:** every module starts with `from __future__ import annotations`.
- **Absolute paths:** repo = `/Users/sunyibo/programs/Hermes-quant-agent`.
- **Test toolchain:** `./.venv/bin/pytest -q` (use `-o addopts=""` for raw counts). Baseline before this phase: **25 passed**.

---

## File Structure

```
hqa/
  config.py            # + REVIEW_DIR
  reviewlog.py         # NEW: schema, load/new_draft/confirm/list/render (JSONL+MD)
  review_cli.py        # NEW: hqa-review draft|confirm|list|render
  gate.py              # NEW: check_strategy(cfg) -> (passed, results)
  gate_cli.py          # NEW: hqa-gate check <config.json>
  doctor_watchdog.py   # MODIFY: run() gains review_dir; auto-draft on alert (idempotent)
tests/
  test_reviewlog.py    # NEW
  test_review_cli.py   # NEW
  test_gate.py         # NEW
  test_gate_cli.py     # NEW
  test_doctor_watchdog.py  # MODIFY: + watchdog auto-draft tests
review/                # created at runtime (git-ignored)
  entries.jsonl
  entries.md
```

Add `review/` to `.gitignore` (like `logs/`).

---

### Task 1: config REVIEW_DIR + reviewlog core (schema, load, new_draft)

**Files:**
- Modify: `hqa/config.py`, `.gitignore`
- Create: `hqa/reviewlog.py`
- Test: `tests/test_reviewlog.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `hqa.config.REVIEW_DIR: Path` — `REPO_DIR/review` (override env `HQA_REVIEW_DIR`).
  - `hqa.reviewlog.MACHINE_FIELDS`, `HUMAN_FIELDS` (tuples).
  - `hqa.reviewlog.load_entries(review_dir: Path) -> list[dict]`.
  - `hqa.reviewlog.new_draft(kind, event, data, source, ts, review_dir, fingerprint=None) -> str` — appends a `status="draft"` record (machine fields set, human fields empty); if `fingerprint` matches an existing entry, returns that id without adding (idempotent).

- [ ] **Step 1: Write the failing test**

Create `tests/test_reviewlog.py`:

```python
from __future__ import annotations

import json

from hqa import reviewlog


def test_new_draft_writes_machine_fields_and_empty_human_fields(tmp_path):
    entry_id = reviewlog.new_draft(
        kind="manual", event="missed NVDA breakout", data={"rid": "r1"},
        source="manual", ts="2026-07-01T00:00:00Z", review_dir=tmp_path,
    )
    entries = reviewlog.load_entries(tmp_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["id"] == entry_id
    assert e["status"] == "draft"
    assert e["event"] == "missed NVDA breakout"
    assert e["data"] == {"rid": "r1"}
    for f in reviewlog.HUMAN_FIELDS:
        assert e[f] == ""


def test_new_draft_sequential_ids_same_day(tmp_path):
    a = reviewlog.new_draft("manual", "e1", {}, "s", "2026-07-01T01:00:00Z", tmp_path)
    b = reviewlog.new_draft("manual", "e2", {}, "s", "2026-07-01T02:00:00Z", tmp_path)
    assert a == "2026-07-01-001"
    assert b == "2026-07-01-002"


def test_new_draft_is_idempotent_by_fingerprint(tmp_path):
    fp = "2026-07-01:kill_switch=false"
    id1 = reviewlog.new_draft("alert", "e", {}, "wd", "2026-07-01T01:00:00Z", tmp_path, fingerprint=fp)
    id2 = reviewlog.new_draft("alert", "e", {}, "wd", "2026-07-01T02:00:00Z", tmp_path, fingerprint=fp)
    assert id1 == id2
    assert len(reviewlog.load_entries(tmp_path)) == 1


def test_load_entries_missing_returns_empty(tmp_path):
    assert reviewlog.load_entries(tmp_path / "nope") == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_reviewlog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.reviewlog'`.

- [ ] **Step 3: Write minimal implementation**

Add to `hqa/config.py` (after `LOG_DIR`):

```python
REVIEW_DIR = Path(os.environ.get("HQA_REVIEW_DIR", str(REPO_DIR / "review")))
```

Add to `.gitignore`:

```gitignore
review/entries.jsonl
review/entries.md
```

Create `hqa/reviewlog.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

MACHINE_FIELDS = ("event", "data", "source")
HUMAN_FIELDS = ("judgment", "basis", "result", "failure_point", "next_rule")


def _entries_path(review_dir: Path) -> Path:
    return review_dir / "entries.jsonl"


def load_entries(review_dir: Path) -> list[dict[str, Any]]:
    path = _entries_path(review_dir)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_entries(entries: list[dict[str, Any]], review_dir: Path) -> None:
    path = _entries_path(review_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def new_draft(
    kind: str,
    event: str,
    data: dict[str, Any],
    source: str,
    ts: str,
    review_dir: Path,
    fingerprint: Optional[str] = None,
) -> str:
    entries = load_entries(review_dir)
    if fingerprint is not None:
        for entry in entries:
            if entry.get("fingerprint") == fingerprint:
                return entry["id"]
    day = ts[:10]
    seq = sum(1 for e in entries if e["id"].startswith(day)) + 1
    entry_id = f"{day}-{seq:03d}"
    record = {
        "id": entry_id,
        "ts": ts,
        "kind": kind,
        "status": "draft",
        "fingerprint": fingerprint,
        "event": event,
        "data": data,
        "source": source,
        "judgment": "",
        "basis": "",
        "result": "",
        "failure_point": "",
        "next_rule": "",
    }
    entries.append(record)
    _write_entries(entries, review_dir)
    return entry_id
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_reviewlog.py -q`
Expected: PASS — `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/config.py hqa/reviewlog.py tests/test_reviewlog.py .gitignore
git commit -q -m "feat: review-log store core (schema, new_draft, idempotency)"
```

---

### Task 2: reviewlog confirm + list + Markdown render

**Files:**
- Modify: `hqa/reviewlog.py`, `tests/test_reviewlog.py`

**Interfaces:**
- Produces:
  - `confirm(entry_id, review_dir, *, judgment, basis, result, failure_point, next_rule) -> bool` — fills human fields, sets `status="confirmed"`; returns False if id not found.
  - `list_entries(review_dir, status=None) -> list[dict]`.
  - `render_markdown(review_dir) -> str` and `write_markdown(review_dir) -> Path` (newest first).

- [ ] **Step 1: Write the failing test** — append to `tests/test_reviewlog.py`:

```python
def test_confirm_fills_human_fields_and_status(tmp_path):
    entry_id = reviewlog.new_draft("manual", "e", {}, "s", "2026-07-01T00:00:00Z", tmp_path)
    ok = reviewlog.confirm(
        entry_id, tmp_path,
        judgment="entered too early", basis="RSI not confirmed",
        result="-2%", failure_point="ignored volume", next_rule="wait for volume confirm",
    )
    assert ok is True
    e = reviewlog.load_entries(tmp_path)[0]
    assert e["status"] == "confirmed"
    assert e["judgment"] == "entered too early"
    assert e["next_rule"] == "wait for volume confirm"


def test_confirm_missing_id_returns_false(tmp_path):
    reviewlog.new_draft("manual", "e", {}, "s", "2026-07-01T00:00:00Z", tmp_path)
    assert reviewlog.confirm("nope", tmp_path, judgment="", basis="", result="", failure_point="", next_rule="") is False


def test_list_entries_filters_by_status(tmp_path):
    a = reviewlog.new_draft("manual", "e1", {}, "s", "2026-07-01T00:00:00Z", tmp_path)
    reviewlog.new_draft("manual", "e2", {}, "s", "2026-07-01T01:00:00Z", tmp_path)
    reviewlog.confirm(a, tmp_path, judgment="j", basis="b", result="r", failure_point="f", next_rule="n")
    assert len(reviewlog.list_entries(tmp_path, status="draft")) == 1
    assert len(reviewlog.list_entries(tmp_path, status="confirmed")) == 1
    assert len(reviewlog.list_entries(tmp_path)) == 2


def test_write_markdown_is_rebuilt_from_jsonl(tmp_path):
    reviewlog.new_draft("alert", "safety deviation", {"k": "v"}, "wd", "2026-07-01T00:00:00Z", tmp_path)
    path = reviewlog.write_markdown(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "# Review Log" in text
    assert "safety deviation" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_reviewlog.py -q`
Expected: FAIL — `AttributeError: module 'hqa.reviewlog' has no attribute 'confirm'`.

- [ ] **Step 3: Add to `hqa/reviewlog.py`:**

```python
def confirm(
    entry_id: str,
    review_dir: Path,
    *,
    judgment: str,
    basis: str,
    result: str,
    failure_point: str,
    next_rule: str,
) -> bool:
    entries = load_entries(review_dir)
    found = False
    for entry in entries:
        if entry["id"] == entry_id:
            entry.update(
                judgment=judgment,
                basis=basis,
                result=result,
                failure_point=failure_point,
                next_rule=next_rule,
                status="confirmed",
            )
            found = True
            break
    if found:
        _write_entries(entries, review_dir)
    return found


def list_entries(review_dir: Path, status: Optional[str] = None) -> list[dict[str, Any]]:
    entries = load_entries(review_dir)
    if status is not None:
        entries = [e for e in entries if e.get("status") == status]
    return entries


def render_markdown(review_dir: Path) -> str:
    entries = sorted(load_entries(review_dir), key=lambda e: e["ts"], reverse=True)
    lines = ["# Review Log", ""]
    for e in entries:
        lines.append(f"## {e['id']} · {e['kind']} · {e['status']} · {e['ts']}")
        lines.append(f"- event: {e.get('event', '')}")
        lines.append(f"- data: {e.get('data', '')}")
        for f in HUMAN_FIELDS:
            lines.append(f"- {f}: {e.get(f, '')}")
        lines.append("")
    return "\n".join(lines)


def write_markdown(review_dir: Path) -> Path:
    path = review_dir / "entries.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(review_dir), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_reviewlog.py -q`
Expected: PASS — `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/reviewlog.py tests/test_reviewlog.py
git commit -q -m "feat: review-log confirm, list, and Markdown mirror"
```

---

### Task 3: review_cli (draft / confirm / list / render)

**Files:**
- Create: `hqa/review_cli.py`
- Test: `tests/test_review_cli.py`

**Interfaces:**
- Consumes: `hqa.reviewlog`, `hqa.runlog.utc_now_iso`, `hqa.config.REVIEW_DIR`.
- Produces: `hqa.review_cli.main(argv=None) -> int` with subcommands `draft|confirm|list|render`, each accepting `--review-dir` (default `config.REVIEW_DIR`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_review_cli.py`:

```python
from __future__ import annotations

from hqa import review_cli, reviewlog


def test_cli_draft_then_confirm_roundtrip(tmp_path, capsys):
    rc = review_cli.main(["draft", "--kind", "manual", "--event", "bad exit",
                          "--data", "rid=r9", "--review-dir", str(tmp_path)])
    assert rc == 0
    entry_id = capsys.readouterr().out.strip()
    assert entry_id == "2026-07-01-001" or entry_id.endswith("-001")

    rc = review_cli.main(["confirm", entry_id, "--judgment", "too early",
                          "--next-rule", "wait", "--review-dir", str(tmp_path)])
    assert rc == 0
    e = reviewlog.load_entries(tmp_path)[0]
    assert e["status"] == "confirmed"
    assert e["judgment"] == "too early"
    assert e["data"] == {"rid": "r9"}


def test_cli_confirm_unknown_id_returns_1(tmp_path, capsys):
    rc = review_cli.main(["confirm", "missing", "--review-dir", str(tmp_path)])
    assert rc == 1


def test_cli_render_writes_markdown(tmp_path, capsys):
    review_cli.main(["draft", "--event", "e", "--review-dir", str(tmp_path)])
    rc = review_cli.main(["render", "--review-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "entries.md").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_review_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.review_cli'`.

- [ ] **Step 3: Create `hqa/review_cli.py`:**

```python
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from hqa import config, reviewlog, runlog


def _parse_kv(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        key, _, value = item.partition("=")
        out[key] = value
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="hqa-review")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_draft = sub.add_parser("draft")
    p_draft.add_argument("--kind", default="manual")
    p_draft.add_argument("--event", required=True)
    p_draft.add_argument("--data", action="append", default=[])
    p_draft.add_argument("--source", default="manual")
    p_draft.add_argument("--review-dir", default=str(config.REVIEW_DIR))

    p_confirm = sub.add_parser("confirm")
    p_confirm.add_argument("id")
    for field in ("judgment", "basis", "result", "failure-point", "next-rule"):
        p_confirm.add_argument(f"--{field}", default="")
    p_confirm.add_argument("--review-dir", default=str(config.REVIEW_DIR))

    p_list = sub.add_parser("list")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--review-dir", default=str(config.REVIEW_DIR))

    p_render = sub.add_parser("render")
    p_render.add_argument("--review-dir", default=str(config.REVIEW_DIR))

    args = parser.parse_args(argv)
    review_dir = Path(args.review_dir)

    if args.cmd == "draft":
        entry_id = reviewlog.new_draft(
            kind=args.kind, event=args.event, data=_parse_kv(args.data),
            source=args.source, ts=runlog.utc_now_iso(), review_dir=review_dir,
        )
        reviewlog.write_markdown(review_dir)
        print(entry_id)
        return 0

    if args.cmd == "confirm":
        ok = reviewlog.confirm(
            args.id, review_dir,
            judgment=args.judgment, basis=args.basis, result=args.result,
            failure_point=args.failure_point, next_rule=args.next_rule,
        )
        if not ok:
            print(f"not found: {args.id}")
            return 1
        reviewlog.write_markdown(review_dir)
        print(f"confirmed: {args.id}")
        return 0

    if args.cmd == "list":
        for e in reviewlog.list_entries(review_dir, status=args.status):
            print(f"{e['id']}\t{e['status']}\t{e['kind']}\t{e.get('event', '')}")
        return 0

    if args.cmd == "render":
        path = reviewlog.write_markdown(review_dir)
        print(str(path))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_review_cli.py -q`
Expected: PASS — `3 passed`. (Note: the first test's id assertion tolerates any `-001` suffix since it uses the real UTC date.)

- [ ] **Step 5: Commit**

```bash
git add hqa/review_cli.py tests/test_review_cli.py
git commit -q -m "feat: hqa-review CLI (draft/confirm/list/render)"
```

---

### Task 4: Watchdog auto-draft on alert (idempotent integration)

**Files:**
- Modify: `hqa/doctor_watchdog.py`, `tests/test_doctor_watchdog.py`

**Interfaces:**
- Modified: `run(run_doctor, now_iso, log_path, review_dir=None) -> tuple[bool, str]` — new optional `review_dir`; when set AND `alert` is true, calls `reviewlog.new_draft(kind="alert", ...)` with a per-day+deviations fingerprint (idempotent). Human fields stay empty.
- Modified: `main()` gains `--review-dir` (default `config.REVIEW_DIR`) and passes it to `run()`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_doctor_watchdog.py`:

```python
def test_run_alert_autodrafts_review_entry(tmp_path):
    from hqa import reviewlog

    log_path = tmp_path / "wd.jsonl"
    review_dir = tmp_path / "review"
    flipped = DOCTOR_SAMPLE.replace("live_trading_enabled=false", "live_trading_enabled=true")
    dw.run(
        run_doctor=lambda: (0, flipped),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=log_path,
        review_dir=review_dir,
    )
    entries = reviewlog.load_entries(review_dir)
    assert len(entries) == 1
    assert entries[0]["kind"] == "alert"
    assert entries[0]["status"] == "draft"
    for f in reviewlog.HUMAN_FIELDS:
        assert entries[0][f] == ""


def test_run_alert_autodraft_is_idempotent_same_day(tmp_path):
    from hqa import reviewlog

    review_dir = tmp_path / "review"
    flipped = DOCTOR_SAMPLE.replace("kill_switch=true", "kill_switch=false")
    for _ in range(3):
        dw.run(
            run_doctor=lambda: (0, flipped),
            now_iso=lambda: "2026-07-01T00:00:00Z",
            log_path=tmp_path / "wd.jsonl",
            review_dir=review_dir,
        )
    assert len(reviewlog.load_entries(review_dir)) == 1


def test_run_nominal_does_not_draft(tmp_path):
    from hqa import reviewlog

    review_dir = tmp_path / "review"
    dw.run(
        run_doctor=lambda: (0, DOCTOR_SAMPLE),
        now_iso=lambda: "2026-07-01T00:00:00Z",
        log_path=tmp_path / "wd.jsonl",
        review_dir=review_dir,
    )
    assert reviewlog.load_entries(review_dir) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_doctor_watchdog.py -q`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'review_dir'`.

- [ ] **Step 3: Modify `hqa/doctor_watchdog.py`.**

Add `reviewlog` to the import line:

```python
from hqa import config, quant_cli, reviewlog, runlog
```

Replace the `run(...)` function with:

```python
def run(
    run_doctor: Callable[[], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
    review_dir: Optional[Path] = None,
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
    if alert and review_dir is not None:
        reviewlog.new_draft(
            kind="alert",
            event="safety-invariant deviation",
            data={"deviations": deviations, "safety": safety},
            source="doctor-watchdog",
            ts=ts,
            review_dir=review_dir,
            fingerprint=f"{ts[:10]}:" + ";".join(sorted(deviations)),
        )
    return alert, (build_alert_message(deviations, ts) if alert else "")
```

In `main()`, add the `--review-dir` argument and pass it through:

```python
    parser.add_argument("--log", default=str(config.LOG_DIR / "doctor_watchdog.jsonl"))
    parser.add_argument("--review-dir", default=str(config.REVIEW_DIR))
    args = parser.parse_args(argv)
    log_path = Path(args.log)
    try:
        alert, message = run(quant_cli.run_doctor, runlog.utc_now_iso, log_path, Path(args.review_dir))
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_doctor_watchdog.py -q`
Expected: PASS — `9 passed` (6 original + 3 new). The existing `run()` tests still pass because `review_dir` defaults to `None` (no draft).

- [ ] **Step 5: Commit**

```bash
git add hqa/doctor_watchdog.py tests/test_doctor_watchdog.py
git commit -q -m "feat: watchdog auto-drafts a review entry on alert (idempotent)"
```

---

### Task 5: gate.check_strategy (acceptance-gate checker)

**Files:**
- Create: `hqa/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Produces: `hqa.gate.check_strategy(cfg: dict) -> tuple[bool, list[dict]]` — evaluates a fixed criteria set; each result is `{"criterion", "passed", "detail"}`; overall is AND of all. Pure, read-only.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gate.py`:

```python
from __future__ import annotations

from hqa import gate

GOOD = {
    "backtest_run_id": "bt-123",
    "risk_envelope": {"per_order_max_notional": 1000, "symbol_whitelist": ["NVDA"], "daily_loss_cap": 200},
    "kill_switch_enabled": True,
    "review_on_drawdown": True,
}


def test_check_strategy_all_pass():
    passed, results = gate.check_strategy(GOOD)
    assert passed is True
    assert all(r["passed"] for r in results)
    assert {r["criterion"] for r in results} == {
        "backtest_baseline", "risk_envelope", "kill_switch_hook", "review_hook",
    }


def test_check_strategy_missing_envelope_key_fails():
    cfg = dict(GOOD, risk_envelope={"per_order_max_notional": 1000})
    passed, results = gate.check_strategy(cfg)
    assert passed is False
    env = next(r for r in results if r["criterion"] == "risk_envelope")
    assert env["passed"] is False
    assert "symbol_whitelist" in env["detail"]


def test_check_strategy_missing_hooks_fail():
    cfg = dict(GOOD, kill_switch_enabled=False, review_on_drawdown=False)
    passed, results = gate.check_strategy(cfg)
    assert passed is False
    failed = {r["criterion"] for r in results if not r["passed"]}
    assert failed == {"kill_switch_hook", "review_hook"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.gate'`.

- [ ] **Step 3: Create `hqa/gate.py`:**

```python
from __future__ import annotations

from typing import Any

REQUIRED_ENVELOPE_KEYS = ("per_order_max_notional", "symbol_whitelist", "daily_loss_cap")


def check_strategy(cfg: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []

    def add(criterion: str, passed: bool, detail: str) -> None:
        results.append({"criterion": criterion, "passed": passed, "detail": detail})

    has_baseline = bool(cfg.get("backtest_run_id")) or ("sharpe" in cfg)
    add("backtest_baseline", has_baseline, "needs backtest_run_id or sharpe")

    envelope = cfg.get("risk_envelope") or {}
    missing = [k for k in REQUIRED_ENVELOPE_KEYS if k not in envelope]
    add("risk_envelope", not missing, f"missing: {missing}" if missing else "ok")

    add("kill_switch_hook", cfg.get("kill_switch_enabled") is True, "needs kill_switch_enabled=true")
    add("review_hook", cfg.get("review_on_drawdown") is True, "needs review_on_drawdown=true")

    passed = all(r["passed"] for r in results)
    return passed, results
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/pytest tests/test_gate.py -q`
Expected: PASS — `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add hqa/gate.py tests/test_gate.py
git commit -q -m "feat: broker-sim acceptance-gate checker (read-only)"
```

---

### Task 6: gate_cli + full-suite green

**Files:**
- Create: `hqa/gate_cli.py`
- Test: `tests/test_gate_cli.py`

**Interfaces:**
- Produces: `hqa.gate_cli.main(argv=None) -> int` — `check <config.json>` prints per-criterion PASS/FAIL + OVERALL; always returns 0 (report-only, never gates).

- [ ] **Step 1: Write the failing test**

Create `tests/test_gate_cli.py`:

```python
from __future__ import annotations

import json

from hqa import gate_cli


def test_gate_cli_reports_and_never_gates(tmp_path, capsys):
    cfg = {"kill_switch_enabled": False}
    path = tmp_path / "strat.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    rc = gate_cli.main(["check", str(path)])
    assert rc == 0  # report-only, never non-zero
    out = capsys.readouterr().out
    assert "OVERALL: FAIL" in out
    assert "kill_switch_hook" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_gate_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hqa.gate_cli'`.

- [ ] **Step 3: Create `hqa/gate_cli.py`:**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from hqa import gate


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="hqa-gate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("config", help="path to strategy config JSON")
    args = parser.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    passed, results = gate.check_strategy(cfg)
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {r['criterion']}: {r['detail']}")
    print(f"OVERALL: {'PASS' if passed else 'FAIL'}")
    return 0
```

- [ ] **Step 4: Run to verify it passes + full suite green**

Run: `./.venv/bin/pytest tests/test_gate_cli.py -q`
Expected: PASS — `1 passed`.

Run: `./.venv/bin/pytest -q -o addopts=""`
Expected: PASS — `43 passed` (25 baseline + 18 new: 4 reviewlog-T1 + 4 reviewlog-T2 + 3 review_cli + 3 watchdog + 3 gate + 1 gate_cli).

- [ ] **Step 5: Commit**

```bash
git add hqa/gate_cli.py tests/test_gate_cli.py
git commit -q -m "feat: hqa-gate CLI (report-only acceptance check)"
```

---

## Phase 0b Acceptance (maps to spec §1.3)

- [ ] JSONL is authoritative; `entries.md` is losslessly rebuilt by `render`/`write_markdown`.
- [ ] The five human fields are never written by any automated path (auto-draft leaves them `""`; only `confirm` sets them).
- [ ] Watchdog auto-drafts exactly one entry per (day, deviation-set) — idempotent — and nominal runs draft nothing.
- [ ] `gate check` is read-only and report-only (exit 0 even on FAIL; never promotes).
- [ ] No platform trading calls, no HTTP, no auth introduced.
- [ ] `./.venv/bin/pytest -q` is green.

---

## Self-Review

**1. Spec coverage (spec §1):** review-log store (Tasks 1–2) ✓; JSONL+MD dual (Task 2) ✓; hybrid auto-draft/human-confirm (Tasks 1,4 draft machine-only; Task 2 `confirm` human-only) ✓; triggers manual (Task 3) + alert (Task 4) ✓; CLI (Task 3) ✓; acceptance-gate checker (Tasks 5–6) ✓. Weekly-review trigger is a Phase 1a consumer (reads this store) — correctly out of 0b scope.

**2. Placeholder scan:** No TBD/TODO; every code + test step is complete; every run step has an exact command and expected result.

**3. Type consistency:** `new_draft(...) -> str` used identically in Task 1 (define), Task 3 (CLI), Task 4 (watchdog). `confirm(...) -> bool` consistent Task 2/3. `check_strategy(cfg) -> (bool, list[dict])` consistent Task 5/6. `run(..., review_dir=None)` optional param keeps Phase 0a `run()` call sites valid.

**4. Human-judgment integrity:** Verified no automated path writes `HUMAN_FIELDS` — `new_draft` sets them to `""`, watchdog uses `new_draft`, only `confirm` (human CLI) sets them. Enforced by tests `test_new_draft_writes_...empty_human_fields` and `test_run_alert_autodrafts_review_entry`.
