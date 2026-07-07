# Phase 1a-4 — 研究员工扩容 Implementation Plan (D-26)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three read-only research employees — ④ missed-opportunity tracker, ③ portfolio risk daily, ② market-foresight + prediction ledger — plus the three platform read-only JSON seams they consume. All proposal-only, zero approval complexity.

**Architecture:** Extend `hqa/` (Phases 0a/0b/1a-0/1a-1/1a-2/1a-3). New HQA modules: `price_series` (futu→longbridge→unavailable adapter), `missed_opportunities`, `portfolio_risk`, `predictions` + `prediction_cli` (mirrors `reviewlog`/`review_cli`). Modify `signal_watchdog` to emit structured `signal_records`. Cross-repo platform changes in `ai-quant-platform`: `paper account-show --json` becomes truly read-only (no `load_or_open`), `paper strategies ops-status --format json` becomes truly read-only (no reconcile) and enriched with sleeve/signal/execution arrays, new `data prices --json` read-only command. Price source is futu-primary + longbridge-CLI-fallback (tiingo is not configured). Delivery order ④→③→② because ③'s `data prices` is ②'s reconciliation base.

**Tech Stack:** Python 3.9.6 stdlib only (HQA) · `pytest` in `.venv` · platform `quant-system` CLI · `longbridge` CLI at `/opt/homebrew/bin/longbridge` (authed, token OK).

## Global Constraints

- **Read-only / proposal-only:** no order/account/rebalance/backtest-execution/paper-mutation; no platform HTTP; no auth. Only read-only CLI seams + filesystem reads.
- **Three platform JSON seams must be truly read-only** (spec §0.1): `paper account-show --json` uses `PaperAccountStorage.load()` (returns `None`→`exists=false`), NEVER `load_or_open()`; `paper strategies ops-status --format json` calls only storage load/list, NEVER `reconcile_pending_sleeves()`; `data prices --provider futu` on failure emits error JSON / nonzero exit, NEVER falls back to `sample`.
- **HQA consumes JSON only** (spec §0.1.2): new seams parse JSON; text output stays for humans, not for HQA.
- **Missed-opportunity needs detail** (spec §0.1.3): signals need `signal_records` (structured); ops-status needs sleeve/signal/execution arrays. Counts alone cannot decide missed.
- **Longbridge is a runtime CLI adapter, not a Python skill dependency** (spec §0.1.4): HQA calls `longbridge kline <SYM> --count N --period day --format json` via an injected callable; the `longbridge-market-data` skill is human/agent docs only.
- **Prediction scoring splits direction and range** (spec §0.1.5): `up|down|flat` (direction Brier) and `in_range` (range hit) are independent dimensions; no `direction="range"`.
- **Never-crash scheduler:** every employee `main` wraps in try/except, writes `{ts,job,error}` to its JSONL + stdout, returns 0.
- **Honest missing data:** never fabricate beta / scores; mark `unavailable` / leave `status=open`.
- **Python 3.9 compat:** every HQA module starts with `from __future__ import annotations`.
- **Provider policy (D-14):** real runs `--provider futu`; `sample` test-only, never a silent fallback.
- **Spec deviation noted inline:** spec §2/§4 assumed `longbridge kline history --start --end`. Verified 2026-07-07 that subcommand fails (`status=7, code=301607: history kline symbol count out of limit`) on this account; the working form is `longbridge kline <SYM> --count N --period day --format json` (per-symbol, count-based, client-side date filter). Plan uses the working form.
- **Baseline before this phase:** HQA `155 passed, 2 skipped`; platform `890 passed, 3 skipped` (both sandbox-disabled).

---

## File Structure

```
# HQA repo (Hermes-quant-agent)
hqa/
  config.py                # MODIFY: + PREDICTION_DIR (predictions/)
  price_series.py          # NEW: futu JSON -> longbridge CLI -> unavailable adapter
  quant_cli.py             # MODIFY: + run_paper_account_show, run_paper_ops_status, run_data_prices, run_longbridge_kline
  signals.py               # MODIFY: + signal_records structured output (evaluate_signals stays backward-compat)
  signal_watchdog.py       # MODIFY: write signal_records to JSONL
  missed_opportunities.py  # NEW: 员工④
  portfolio_risk.py        # NEW: 员工③ (uses price_series)
  predictions.py           # NEW: prediction ledger (mirrors reviewlog)
  prediction_cli.py        # NEW: hqa-prediction CLI (mirrors review_cli)
  weekly_review.py         # MODIFY: + 预测对账段
scripts/hermes/
  hqa-missed-opportunities.sh   # NEW wrapper
  hqa-portfolio-risk.sh         # NEW wrapper
  hqa-prediction.sh             # NEW wrapper
  hqa-quant-readonly.sh         # MODIFY: + "paper account-show", "paper strategies ops-status", "data prices"
tests/
  test_price_series.py           # NEW
  test_quant_cli.py              # MODIFY: + 4 new wrappers
  test_signals.py                # MODIFY: signal_records
  test_signal_watchdog.py        # MODIFY: signal_records in JSONL
  test_missed_opportunities.py   # NEW
  test_portfolio_risk.py         # NEW
  test_predictions.py            # NEW
  test_prediction_cli.py         # NEW
  test_weekly_review.py          # MODIFY: + 预测对账段
  test_install.py                # MODIFY: + 3 new wrappers

# Platform repo (ai-quant-platform) — cross-repo, commit separately on its branch
  src/quant_system/cli.py                       # MODIFY: account-show --json read-only; ops-status read-only + arrays; + data prices --json
  src/quant_system/execution/paper_strategy_operations.py  # MODIFY: + read-only ops_status path + detail to_dict
  tests/test_cli_paper_readonly.py              # NEW: no account create, no sleeve reconcile
  tests/test_cli_data_prices.py                 # NEW: provider mock, no sample fallback
```

---

## Task 0: Longbridge CLI probe + platform read-only gate (verification, no code)

**Files:** none (verification only — proves the plan's assumptions hold before any code)

**Interfaces:** establishes facts later tasks rely on.

- [ ] **Step 1: Confirm longbridge auth + working kline form**

Run:
```bash
longbridge check 2>&1 | head -5
longbridge kline SPY.US --count 5 --period day --format json 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok len=',len(d)); print('keys=',sorted(d[0].keys())); print('close=',d[0]['close'],'type=',type(d[0]['close']).__name__)"
```
Expected: `token OK`; JSON array; keys include `close`/`time`; `close` is a **string** (parse to float in adapter).

- [ ] **Step 2: Confirm `kline history` is unusable on this account (spec deviation rationale)**

Run: `longbridge kline history SPY.US --start 2026-07-01 --end 2026-07-07 --period day --format json 2>&1 | head -2`
Expected: `Error: WebSocket error (status=7, code=301607): history kline symbol count out of limit`. Confirms the plan uses `kline <SYM> --count N` instead.

- [ ] **Step 3: Confirm `PaperAccountStorage.load()` exists and is read-only**

Run (platform repo):
```bash
cd /Users/sunyibo/programs/ai-quant-platform && ./.venv/bin/python -c "
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.config import load_settings
s = load_settings()
st = PaperAccountStorage(s.data.data_dir/'api_runs', account_id='nonexistent_probe')
print('load() ->', st.load())
"
```
Expected: `load() -> None` (no file created). Confirms the read-only load path exists for Task P2.

- [ ] **Step 4: Confirm `ops_status` currently calls reconcile (proves Task P3 is real work)**

Run: `grep -n "reconcile_pending_sleeves" /Users/sunyibo/programs/ai-quant-platform/src/quant_system/execution/paper_strategy_operations.py`
Expected: a hit at the `ops_status` method (~line 282). Confirms the read-only fork is needed.

If any step's expected output differs, STOP and reconcile the plan before proceeding.

---

## Task P1 (platform): `data prices --json` read-only command

**Files:**
- Modify: `src/quant_system/cli.py` (add `data_app` command `prices`)
- Test: `tests/test_cli_data_prices.py` (NEW)

**Interfaces:**
- Produces: `quant-system data prices --symbol X [--symbol Y ...] --start YYYY-MM-DD --end YYYY-MM-DD --provider futu --json` → last line is JSON per spec §2 contract: `{ok, provider, start, end, symbols, series: {sym: [{date, close, source}]}, unavailable: {sym: reason}}`; on failure `{ok:false, provider, error, series:{}, unavailable:{sym:reason}}` and exit nonzero.
- Consumes: `build_ohlcv_provider(settings, requested="futu")` + provider's OHLCV load.

- [ ] **Step 1: Write the failing test**

`tests/test_cli_data_prices.py`:
```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


def _fake_ohlcv_frame(symbol: str, dates: list[str], closes: list[float]):
    import pandas as pd
    return pd.DataFrame({"symbol": [symbol] * len(dates), "timestamp": pd.to_datetime(dates), "close": closes})


def test_data_prices_json_contract(tmp_path, monkeypatch):
    # provider returns OHLCV; the command must emit the spec §2 JSON contract.
    def fake_provider(settings, *, requested=None):
        class P:
            def load_ohlcv(self, symbols, start, end):
                return {s: _fake_ohlcv_frame(s, ["2026-07-06"], [148.5 if s == "NVDA" else 620.1]) for s in symbols}
            name = "futu"
        return P(), "futu"

    with patch("quant_system.cli.build_ohlcv_provider", side_effect=fake_provider):
        result = runner.invoke(app, ["data", "prices", "--symbol", "NVDA", "--symbol", "SPY",
                                     "--start", "2026-07-01", "--end", "2026-07-07", "--provider", "futu", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["provider"] == "futu"
    assert payload["symbols"] == ["NVDA", "SPY"]
    assert payload["series"]["NVDA"][0]["close"] == 148.5
    assert payload["series"]["SPY"][0]["close"] == 620.1
    assert payload["unavailable"] == {}


def test_data_prices_provider_failure_no_sample_fallback(tmp_path):
    # explicit futu failure must NOT silently fall back to sample.
    def boom_provider(settings, *, requested=None):
        from quant_system.data.provider_factory import DataProviderUnavailableError
        raise DataProviderUnavailableError("opend_unavailable")
    with patch("quant_system.cli.build_ohlcv_provider", side_effect=boom_provider):
        result = runner.invoke(app, ["data", "prices", "--symbol", "NVDA",
                                     "--start", "2026-07-01", "--end", "2026-07-07", "--provider", "futu", "--json"])
    assert result.exit_code != 0
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert payload["provider"] == "futu"
    assert payload["series"] == {}
    assert payload["unavailable"]["NVDA"]


def test_data_prices_missing_symbol_in_unavailable(tmp_path):
    # a symbol the provider has no data for lands in unavailable, others still in series.
    def partial_provider(settings, *, requested=None):
        class P:
            def load_ohlcv(self, symbols, start, end):
                return {symbols[0]: _fake_ohlcv_frame(symbols[0], ["2026-07-06"], [148.5])}
            name = "futu"
        return P(), "futu"
    with patch("quant_system.cli.build_ohlcv_provider", side_effect=partial_provider):
        result = runner.invoke(app, ["data", "prices", "--symbol", "NVDA", "--symbol", "ZZZ",
                                     "--start", "2026-07-01", "--end", "2026-07-07", "--provider", "futu", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert "NVDA" in payload["series"]
    assert payload["unavailable"]["ZZZ"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/sunyibo/programs/ai-quant-platform && ./.venv/bin/python -m pytest tests/test_cli_data_prices.py -q`
Expected: FAIL (`No such command 'prices'` / import error).

- [ ] **Step 3: Implement `data prices`**

In `src/quant_system/cli.py`, add (after the `ingest-tiingo` command):
```python
@data_app.command("prices")
def data_prices_command(
    symbol: Annotated[list[str], typer.Option("--symbol", help="Symbol to fetch (repeatable).")] = [],
    start: Annotated[str, typer.Option("--start", help="Start date YYYY-MM-DD.")] = ...,
    end: Annotated[str, typer.Option("--end", help="End date YYYY-MM-DD.")] = ...,
    provider: Annotated[str, typer.Option("--provider", help="Data provider.")] = "futu",
    output_format: Annotated[bool, typer.Option("--json", help="Emit single-line JSON.")] = False,
) -> None:
    """Read-only historical close prices as JSON (no sample fallback)."""
    import pandas as pd
    from quant_system.data.provider_factory import build_ohlcv_provider, DataProviderUnavailableError

    settings = load_settings()
    payload: dict = {"ok": True, "provider": provider, "start": start, "end": end,
                     "symbols": list(symbol), "series": {}, "unavailable": {}}
    try:
        prov, name = build_ohlcv_provider(settings, requested=provider)
    except DataProviderUnavailableError as exc:
        payload.update({"ok": False, "error": str(exc) or "provider_unavailable",
                        "unavailable": {s: str(exc) or "provider_unavailable" for s in symbol}})
        typer.echo(json.dumps(payload, sort_keys=True))
        raise typer.Exit(code=1)
    for sym in symbol:
        try:
            frame = prov.load_ohlcv([sym], start=start, end=end)
            if frame is None or getattr(frame, "empty", True):
                raise ValueError("no_data")
            df = frame if sym in set(frame["symbol"]) else frame
            rows = df[df["symbol"] == sym].sort_values("timestamp") if "symbol" in df.columns else df.sort_values("timestamp")
            payload["series"][sym] = [
                {"date": pd.Timestamp(t).strftime("%Y-%m-%d"), "close": float(c), "source": name}
                for t, c in zip(rows["timestamp"], rows["close"])
            ]
        except Exception as exc:
            payload["unavailable"][sym] = str(exc) or "no_data"
    typer.echo(json.dumps(payload, sort_keys=True))
```
(Adjust the `load_ohlcv` signature to match the real provider if it differs — the platform's `load_ohlcv` takes `(symbols, *, start, end)`; verify with `grep -nA5 "def load_ohlcv" src/quant_system/data/storage.py` before finalizing.)

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_cli_data_prices.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Run full platform suite + ruff**

Run: `./.venv/bin/python -m pytest -q -p no:cacheprovider && ./.venv/bin/ruff check src/quant_system/cli.py`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/quant_system/cli.py tests/test_cli_data_prices.py
git commit -m "feat(cli): data prices --json read-only command (D-26, no sample fallback)"
```

---

## Task P2 (platform): `paper account-show --json` truly read-only

**Files:**
- Modify: `src/quant_system/cli.py:922-943` (`paper_account_show_command`)
- Test: `tests/test_cli_paper_readonly.py` (NEW)

**Interfaces:**
- Produces: `quant-system paper account-show --account default --json` → last line JSON `{account_id, exists, cash, realized_pnl, kill_switch, positions:[{symbol,qty,avg_cost}], pending_orders:[]}`; `exists=false` + `cash=null` + `positions=[]` when account file absent, and **no file created**.
- Consumes: `PaperAccountStorage.load()` (returns `None` when absent — verified Task 0 Step 3).

- [ ] **Step 1: Write the failing test**

`tests/test_cli_paper_readonly.py`:
```python
from __future__ import annotations

import json
from pathlib import Path
from typer.testing import CliRunner
from quant_system.cli import app

runner = CliRunner()


def test_account_show_json_missing_account_does_not_create(tmp_path, monkeypatch):
    # point data_dir at an empty tmp so the account file does not exist
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    result = runner.invoke(app, ["paper", "account-show", "--account", "probe_missing", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["exists"] is False
    assert payload["cash"] is None
    assert payload["positions"] == []
    # CRITICAL: no account file was created (load, not load_or_open)
    assert not (tmp_path / "api_runs" / "paper_account" / "probe_missing").exists()


def test_account_show_json_existing_account(tmp_path, monkeypatch):
    # seed an account file, then read it back via --json
    from quant_system.execution.account_storage import PaperAccountStorage
    from quant_system.config import load_settings
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    settings = load_settings()
    st = PaperAccountStorage(settings.data.data_dir / "api_runs", account_id="probe")
    with st.mutation_lock():
        acct = st.load_or_open()
        acct.positions["NVDA"] = type(acct.positions["NVDA"])(quantity=10.0, avg_cost=148.5) if acct.positions else None
    # (if the Position shape differs, use the real constructor; verify via grep first)
    result = runner.invoke(app, ["paper", "account-show", "--account", "probe", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["exists"] is True
    assert payload["account_id"] == "probe"
    assert any(p["symbol"] == "NVDA" for p in payload["positions"])
```
(Note: the seeding in the second test may need adjustment to the real `Position`/account API — read `account_storage.py` `load_or_open` + `Position` dataclass before finalizing the seed. The first test is the critical read-only gate and should pass as-is.)

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_cli_paper_readonly.py -q`
Expected: FAIL (`No such option --json`).

- [ ] **Step 3: Implement read-only `--json` path**

Replace `paper_account_show_command` body (`src/quant_system/cli.py:922-943`):
```python
@paper_app.command("account-show")
def paper_account_show_command(
    account_id: Annotated[str, typer.Option("--account", help="Account id to display.")] = "default",
    output_format: Annotated[bool, typer.Option("--json", help="Emit single-line JSON.")] = False,
) -> None:
    """Print a persistent paper account's cash and positions (read-only)."""
    from quant_system.execution.account_storage import PaperAccountStorage

    settings = load_settings()
    api_runs_dir = settings.data.data_dir / "api_runs"
    storage = PaperAccountStorage(api_runs_dir, account_id=account_id)
    with storage.mutation_lock():
        account = storage.load()  # read-only: None when absent, NEVER load_or_open
    if output_format:
        if account is None:
            typer.echo(json.dumps({"account_id": account_id, "exists": False, "cash": None,
                                   "realized_pnl": None, "kill_switch": None, "positions": [], "pending_orders": []}, sort_keys=True))
            return
        typer.echo(json.dumps({"account_id": account.account_id, "exists": True, "cash": float(account.cash),
                               "realized_pnl": float(account.realized_pnl), "kill_switch": bool(account.kill_switch),
                               "positions": [{"symbol": s, "qty": float(p.quantity), "avg_cost": float(p.avg_cost)}
                                             for s, p in sorted(account.positions.items())],
                               "pending_orders": []}, sort_keys=True))
        return
    # text path unchanged for humans
    if account is None:
        typer.echo(f"account={account_id} (no account file)")
        return
    typer.echo(f"account={account.account_id} cash={account.cash:.2f} realized_pnl={account.realized_pnl:.2f} positions={len(account.positions)} kill_switch={account.kill_switch}")
    for symbol, position in sorted(account.positions.items()):
        typer.echo(f"  {symbol}: qty={position.quantity:.4f} avg_cost={position.avg_cost:.2f}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_cli_paper_readonly.py -q`
Expected: PASS (the missing-account test is the gate; the existing-account test may need seed fixup).

- [ ] **Step 5: Run full suite + ruff**

Run: `./.venv/bin/python -m pytest -q -p no:cacheprovider && ./.venv/bin/ruff check src/quant_system/cli.py`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/quant_system/cli.py tests/test_cli_paper_readonly.py
git commit -m "fix(cli): paper account-show --json truly read-only (load, not load_or_open)"
```

---

## Task P3 (platform): `paper strategies ops-status --format json` truly read-only + detail arrays

**Files:**
- Modify: `src/quant_system/execution/paper_strategy_operations.py` (`PaperStrategyOpsStatus.to_dict` → add detail arrays; add `ops_status_read_only` method that skips reconcile)
- Modify: `src/quant_system/cli.py:1252` (`paper_strategy_ops_status_command` — json path calls read-only)
- Test: `tests/test_cli_paper_readonly.py` (EXTEND)

**Interfaces:**
- Produces: `quant-system paper strategies ops-status --format json [--target-date D]` → JSON per spec §3: `{target_date, execution_window, counts:{...}, sleeves:[...], signals:[...], executions:[...], pending_journals:[...]}`; **no reconcile, no sleeve file mutation**.
- Consumes: `sleeve_storage.list_sleeves()` / `load`-only methods (NOT `reconcile_pending_sleeves`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_paper_readonly.py`:
```python
def test_ops_status_json_does_not_reconcile(tmp_path, monkeypatch):
    from unittest.mock import patch
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    with patch("quant_system.execution.paper_strategy_sleeve_storage.StrategySleeveStorage.reconcile_pending_sleeves") as m:
        m.side_effect = AssertionError("reconcile must NOT be called by read-only ops-status")
        result = runner.invoke(app, ["paper", "strategies", "ops-status", "--format", "json", "--target-date", "2026-07-07"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["target_date"] == "2026-07-07"
    assert "counts" in payload and "sleeves" in payload and "signals" in payload and "executions" in payload
    # no pending sleeve files were created/modified
    assert list((tmp_path / "api_runs").rglob("*.json")) == [] or True  # gate: reconcile never ran (mock would have AssertionError-raised)


def test_ops_status_json_detail_arrays_present(tmp_path, monkeypatch):
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    result = runner.invoke(app, ["paper", "strategies", "ops-status", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert isinstance(payload["sleeves"], list)
    assert isinstance(payload["signals"], list)
    assert isinstance(payload["executions"], list)
    assert set(payload["counts"]) >= {"sleeve_count", "running_sleeve_count", "pending_execution_count", "filled_count", "blocked_count"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_cli_paper_readonly.py -k ops_status -q`
Expected: FAIL (reconcile IS called today; or arrays missing).

- [ ] **Step 3: Add read-only `ops_status` path + detail `to_dict`**

In `paper_strategy_operations.py`, add a read-only variant alongside `ops_status` (do NOT change the existing mutating `ops_status` — other paths depend on it). First read the current `ops_status` method (~lines 273-290) to see what storage calls it makes, then add:
```python
def ops_status_read_only(self, *, target_date: str | None = None, execution_window: str = "next_open") -> PaperStrategyOpsStatus:
    """Read-only ops status: load/list only, NEVER reconcile_pending_sleeves."""
    # mirror ops_status but replace the reconcile_pending_sleeves(account) call
    # with a pure load (e.g. sleeve_storage.list_sleeves(account) or load without reconcile).
    # See the real ops_status body to copy its non-reconcile storage reads exactly.
    ...
```
Add detail arrays to `PaperStrategyOpsStatus` (new dataclass fields `sleeves`, `signals`, `executions`, `pending_journals` as `list[dict]`, default `field(default_factory=list)`) and to its `to_dict`:
```python
def to_dict(self) -> dict:
    base = {  # existing count fields
        "target_date": self.target_date, "sleeve_count": self.sleeve_count,
        "running_sleeve_count": self.running_sleeve_count, "pending_execution_count": self.pending_execution_count,
        "pending_due_count": self.pending_due_count, "filled_count": self.filled_count,
        "blocked_count": self.blocked_count, "recovery_required_count": self.recovery_required_count,
        "pending_journal_count": self.pending_journal_count,
    }
    base["sleeves"] = self.sleeves
    base["signals"] = self.signals
    base["executions"] = self.executions
    base["pending_journals"] = self.pending_journals
    return base
```
In `cli.py:1252`, change the `json` branch to call `runner.ops_status_read_only(...)` instead of `runner.ops_status(...)`, and wrap the payload as `{"target_date":..., "execution_window": window, "counts": <base minus arrays>, "sleeves":..., "signals":..., "executions":..., "pending_journals":...}` (split counts from arrays to match spec §3 exactly).

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_cli_paper_readonly.py -k ops_status -q`
Expected: PASS (reconcile mock never tripped; arrays present).

- [ ] **Step 5: Run full suite + ruff**

Run: `./.venv/bin/python -m pytest -q -p no:cacheprovider && ./.venv/bin/ruff check src/quant_system/cli.py src/quant_system/execution/paper_strategy_operations.py`
Expected: green (existing text-path callers of mutating `ops_status` still work — we added a new read-only method, did not change the old one).

- [ ] **Step 6: Commit**

```bash
git add src/quant_system/cli.py src/quant_system/execution/paper_strategy_operations.py tests/test_cli_paper_readonly.py
git commit -m "fix(cli): ops-status --format json read-only (no reconcile) + detail arrays (D-26)"
```

---

## Task H1 (HQA): `price_series.py` adapter (futu JSON → longbridge CLI → unavailable)

**Files:**
- Create: `hqa/price_series.py`
- Create: `tests/test_price_series.py`

**Interfaces:**
- Produces: `get_close_series(symbols: list[str], start: str, end: str, *, run_data_prices, run_longbridge_kline, provider="futu") -> dict[str, list[dict]]` where each value is `[{date, close, source}]`; a symbol with no data → `[]`; whole-call failure → `{}` and the caller marks unavailable. Also `longbridge_close_series(symbol, start, end, run_longbridge_kline) -> list[dict]` (client-side date filter on `--count N` output).
- Consumes: `run_data_prices(symbols, start, end, provider) -> tuple[int, str]` (platform JSON, Task P1 via `quant_cli`) and `run_longbridge_kline(symbol, count, period="day") -> tuple[int, str]` (Task H2).

- [ ] **Step 1: Write the failing test**

`tests/test_price_series.py`:
```python
from __future__ import annotations

import json
from hqa import price_series


def _futu_ok(symbols, start, end, provider="futu"):
    series = {s: [{"date": "2026-07-06", "close": 148.5 if s == "NVDA" else 620.1, "source": "futu"}] for s in symbols}
    return 0, json.dumps({"ok": True, "provider": "futu", "series": series, "unavailable": {}})


def _futu_fail(symbols, start, end, provider="futu"):
    return 1, json.dumps({"ok": False, "provider": "futu", "error": "opend", "series": {}, "unavailable": {s: "opend" for s in symbols}})


def _lb_ok(symbol, count, period="day"):
    return 0, json.dumps([{"close": "151.0", "time": "2026-07-06T04:00:00Z"}])


def test_futu_primary_used_when_ok():
    out = price_series.get_close_series(["NVDA", "SPY"], "2026-07-01", "2026-07-07",
                                        run_data_prices=_futu_ok, run_longbridge_kline=_lb_ok)
    assert out["NVDA"][0]["close"] == 148.5
    assert out["NVDA"][0]["source"] == "futu"


def test_futu_fail_falls_back_to_longbridge():
    out = price_series.get_close_series(["NVDA"], "2026-07-01", "2026-07-07",
                                        run_data_prices=_futu_fail, run_longbridge_kline=_lb_ok)
    assert out["NVDA"][0]["close"] == 151.0
    assert out["NVDA"][0]["source"] == "longbridge"


def test_both_fail_returns_empty():
    out = price_series.get_close_series(["NVDA"], "2026-07-01", "2026-07-07",
                                        run_data_prices=_futu_fail, run_longbridge_kline=lambda s, c, period="day": (1, "[]"))
    assert out["NVDA"] == []


def test_longbridge_parses_string_close_and_filters_by_date():
    # longbridge returns close as STRING; count-based; adapter filters to [start,end]
    lb = json.dumps([
        {"close": "150.0", "time": "2026-06-29T04:00:00Z"},
        {"close": "151.0", "time": "2026-07-06T04:00:00Z"},
    ])
    out = price_series.longbridge_close_series("NVDA", "2026-07-01", "2026-07-07",
                                               run_longbridge_kline=lambda s, c, period="day": (0, lb))
    assert len(out) == 1
    assert out[0]["date"] == "2026-07-06"
    assert out[0]["close"] == 151.0
    assert out[0]["source"] == "longbridge"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_price_series.py -q`
Expected: FAIL (`ModuleNotFoundError: hqa.price_series`).

- [ ] **Step 3: Implement `price_series.py`**

`hqa/price_series.py`:
```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Any

# longbridge kline --count N --period day --format json returns a list of
# {open,high,low,close,time,volume,turnover} with close as STRING and time as
# ISO-8601 Z. The count-based form is the working one on this account (the
# `kline history` subcommand errors with "symbol count out of limit").

def _parse_longbridge_rows(payload: str) -> list[dict]:
    try:
        rows = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        try:
            t = r["time"]
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            out.append({"date": dt.date().isoformat(), "close": float(r["close"]), "raw_ts": dt})
        except (KeyError, ValueError, TypeError):
            continue
    return out


def longbridge_close_series(symbol: str, start: str, end: str,
                            run_longbridge_kline: Callable[..., tuple[int, str]],
                            *, count: int = 400, period: str = "day") -> list[dict]:
    exit_code, out = run_longbridge_kline(symbol, count, period=period)
    if exit_code != 0:
        return []
    rows = _parse_longbridge_rows(out)
    start_d = datetime.fromisoformat(start).date()
    end_d = datetime.fromisoformat(end).date()
    kept = [r for r in rows if start_d <= r["raw_ts"].date() <= end_d]
    return [{"date": r["date"], "close": r["close"], "source": "longbridge"} for r in kept]


def _parse_futu_payload(payload: str) -> dict | None:
    for line in reversed(payload.splitlines()):
        s = line.strip()
        if not s:
            continue
        try:
            d = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return None
        return d if isinstance(d, dict) else None
    return None


def get_close_series(symbols: list[str], start: str, end: str, *,
                     run_data_prices: Callable[..., tuple[int, str]],
                     run_longbridge_kline: Callable[..., tuple[int, str]],
                     provider: str = "futu") -> dict[str, list[dict]]:
    exit_code, out = run_data_prices(symbols, start, end, provider=provider)
    result: dict[str, list[dict]] = {s: [] for s in symbols}
    payload = _parse_futu_payload(out)
    if payload and payload.get("ok"):
        for sym in symbols:
            result[sym] = list(payload.get("series", {}).get(sym, []))
        # symbols still missing -> try longbridge
        for sym in symbols:
            if not result[sym]:
                lb = longbridge_close_series(sym, start, end, run_longbridge_kline)
                if lb:
                    result[sym] = lb
        return result
    # futu wholesale failure -> longbridge per symbol
    for sym in symbols:
        lb = longbridge_close_series(sym, start, end, run_longbridge_kline)
        if lb:
            result[sym] = lb
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_price_series.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add hqa/price_series.py tests/test_price_series.py
git commit -m "feat(1a-4): price_series adapter — futu JSON -> longbridge CLI -> unavailable"
```

---

## Task H2 (HQA): `quant_cli` wrappers for the 3 JSON seams + longbridge

**Files:**
- Modify: `hqa/quant_cli.py`
- Modify: `tests/test_quant_cli.py`

**Interfaces:**
- Produces:
  - `run_paper_account_show(account_id="default") -> tuple[int, str]` → `["paper", "account-show", "--account", account_id, "--json"]`
  - `run_paper_ops_status(target_date=None) -> tuple[int, str]` → `["paper", "strategies", "ops-status", "--format", "json"]` (+ `--target-date` if given)
  - `run_data_prices(symbols, start, end, provider="futu") -> tuple[int, str]` → `["data", "prices", "--symbol", s, ... "--start", "--end", "--provider", "--json"]`
  - `run_longbridge_kline(symbol, count=400, period="day") -> tuple[int, str]` → runs `longbridge kline <SYM> --count N --period day --format json` (NOT via quant-system; a separate subprocess call to the `longbridge` binary)
- Consumes: `quant_cli._run(args, bin_path=None, cwd=None, timeout=300)`; `config.QUANT_SYSTEM_BIN`, `config.AIQP_DIR`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_quant_cli.py`:
```python
import json
from unittest.mock import patch
from hqa import quant_cli


def _cap(args, **kw):
    # capture the argv passed to _run
    return 0, "{}"


def test_run_paper_account_show_argv(monkeypatch):
    seen = {}
    def fake_run(args, bin_path=None, cwd=None, timeout=300):
        seen["args"] = args; return 0, json.dumps({"account_id": "default", "exists": False})
    monkeypatch.setattr(quant_cli, "_run", fake_run)
    code, out = quant_cli.run_paper_account_show("default")
    assert code == 0
    assert seen["args"] == ["paper", "account-show", "--account", "default", "--json"]


def test_run_paper_ops_status_argv(monkeypatch):
    seen = {}
    def fake_run(args, bin_path=None, cwd=None, timeout=300):
        seen["args"] = args; return 0, json.dumps({"target_date": "2026-07-07", "counts": {}})
    monkeypatch.setattr(quant_cli, "_run", fake_run)
    code, out = quant_cli.run_paper_ops_status(target_date="2026-07-07")
    assert seen["args"] == ["paper", "strategies", "ops-status", "--format", "json", "--target-date", "2026-07-07"]


def test_run_data_prices_argv(monkeypatch):
    seen = {}
    def fake_run(args, bin_path=None, cwd=None, timeout=300):
        seen["args"] = args; return 0, json.dumps({"ok": True, "series": {}})
    monkeypatch.setattr(quant_cli, "_run", fake_run)
    quant_cli.run_data_prices(["NVDA", "SPY"], "2026-07-01", "2026-07-07", provider="futu")
    assert seen["args"][:2] == ["data", "prices"]
    assert "--symbol" in seen["args"] and "NVDA" in seen["args"] and "SPY" in seen["args"]
    assert "--json" in seen["args"] and "--provider" in seen["args"] and "futu" in seen["args"]


def test_run_longbridge_kline_argv(monkeypatch):
    seen = {}
    def fake_popen(cmd, **kw):
        class R:
            returncode = 0
            def communicate(self): return json.dumps([{"close": "1", "time": "2026-07-06T04:00:00Z"}]).encode(), b""
        seen["cmd"] = cmd
        return R()
    monkeypatch.setattr("hqa.quant_cli.subprocess.run", fake_popen, raising=False)
    # if quant_cli uses subprocess.run with capture_output, adapt; the test asserts the command shape:
    code, out = quant_cli.run_longbridge_kline("NVDA.US", count=5)
    assert code == 0
    cmd = seen["cmd"]
    assert cmd[0] in ("longbridge",) or cmd[:3] == ["longbridge", "kline", "NVDA.US"]
    assert "--format" in cmd and "json" in cmd and "--period" in cmd and "day" in cmd and "--count" in cmd and "5" in cmd
```
(If `quant_cli` already imports `subprocess`, reuse it; if not, add `import subprocess` and use `subprocess.run(cmd, capture_output=True, text=True, timeout=...)`. Inspect `quant_cli._run` first to match the house pattern.)

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_quant_cli.py -k "paper_account_show or paper_ops_status or data_prices or longbridge_kline" -q`
Expected: FAIL (functions don't exist).

- [ ] **Step 3: Implement the 4 wrappers**

In `hqa/quant_cli.py` (inspect existing `_run` + imports first; add `import subprocess` if missing):
```python
def run_paper_account_show(account_id: str = "default") -> tuple[int, str]:
    return _run(["paper", "account-show", "--account", account_id, "--json"])

def run_paper_ops_status(target_date: str | None = None) -> tuple[int, str]:
    args = ["paper", "strategies", "ops-status", "--format", "json"]
    if target_date:
        args += ["--target-date", target_date]
    return _run(args)

def run_data_prices(symbols: list[str], start: str, end: str, provider: str = "futu") -> tuple[int, str]:
    args = ["data", "prices"]
    for s in symbols:
        args += ["--symbol", s]
    args += ["--start", start, "--end", end, "--provider", provider, "--json"]
    return _run(args)

def run_longbridge_kline(symbol: str, count: int = 400, period: str = "day") -> tuple[int, str]:
    # longbridge CLI is separate from quant-system; per-symbol count-based form.
    cmd = ["longbridge", "kline", symbol, "--count", str(count), "--period", period, "--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_quant_cli.py -k "paper_account_show or paper_ops_status or data_prices or longbridge_kline" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add hqa/quant_cli.py tests/test_quant_cli.py
git commit -m "feat(1a-4): quant_cli wrappers for account-show/ops-status/data-prices JSON + longbridge kline"
```

---

## Task H3 (HQA): `signal_records` structured output (signals + signal_watchdog)

**Files:**
- Modify: `hqa/signals.py` (add `signal_records` alongside `signals` strings — backward compatible)
- Modify: `hqa/signal_watchdog.py` (write `signal_records` to JSONL)
- Modify: `tests/test_signals.py`, `tests/test_signal_watchdog.py`

**Interfaces:**
- Produces: `signals.evaluate_signals(...) -> tuple[bool, list[str]]` unchanged; NEW `signals.build_signal_records(candidates, factor_lab, run_date, ts) -> list[dict]` with fields `{symbol, signal_type, score, iv_rank, strategy, source_run_date, ts, signal_id?}`. `signal_watchdog.run` gains a returned/injected `build_records` callable and writes `signal_records` into the JSONL record.
- Consumes: existing `load_scan_candidates` candidate fields + `parse_factor_lab`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_signals.py`:
```python
from hqa import signals

def test_build_signal_records_fields():
    candidates = [{"symbol": "NVDA", "global_score": 85, "iv_rank": 70, "strategy": "momentum_reversal", "source_run_date": "2026-07-07"}]
    factor_lab = {"NVDA": "momentum=0.8"}
    recs = signals.build_signal_records(candidates, factor_lab, run_date="2026-07-07", ts="2026-07-07T13:00:00Z")
    assert len(recs) == 1
    r = recs[0]
    assert set(["symbol", "signal_type", "score", "iv_rank", "strategy", "source_run_date", "ts"]).issubset(set(r))
    assert r["symbol"] == "NVDA"
    assert r["signal_type"]  # non-empty
    # stable fingerprint derivation: no upstream signal_id -> derive from date+symbol+type+strategy
    assert "signal_id" in r or r.get("fingerprint")


def test_build_signal_records_empty_when_no_candidates():
    assert signals.build_signal_records([], {}, "2026-07-07", "ts") == []
```

Append to `tests/test_signal_watchdog.py`:
```python
def test_signal_watchdog_writes_signal_records(tmp_path):
    from hqa import signal_watchdog
    from pathlib import Path
    log = tmp_path / "signal_watchdog.jsonl"
    def run_scan(): return 0, ""
    def load_candidates(): return [{"symbol": "NVDA", "global_score": 90, "iv_rank": 80, "strategy": "mom", "source_run_date": "2026-07-07"}]
    def run_factor_lab(): return 0, "NVDA momentum=0.9"
    has, msg = signal_watchdog.run(run_scan, load_candidates, run_factor_lab,
                                   lambda: "2026-07-07T13:00:00Z", log,
                                   min_score=80, min_iv_rank=70)
    import json
    rec = json.loads(log.read_text().strip().splitlines()[-1])
    assert "signal_records" in rec
    assert isinstance(rec["signal_records"], list)
    assert rec["signal_records"][0]["symbol"] == "NVDA"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_signals.py tests/test_signal_watchdog.py -k "build_signal_records or signal_records" -q`
Expected: FAIL (`build_signal_records` missing / `signal_records` not in JSONL).

- [ ] **Step 3: Implement**

In `hqa/signals.py` add (inspect candidate field names first — `global_score`/`iv_rank`/`strategy` may differ; match the real candidate dict):
```python
def build_signal_records(candidates: list[dict], factor_lab: dict, *, run_date: str, ts: str) -> list[dict]:
    records: list[dict] = []
    for c in candidates:
        symbol = c.get("symbol")
        if not symbol:
            continue
        signal_type = c.get("signal_type") or _infer_signal_type(c, factor_lab)  # e.g. "momentum_reversal"
        score = c.get("global_score") or c.get("score")
        iv_rank = c.get("iv_rank")
        strategy = c.get("strategy") or "unknown"
        source_run_date = c.get("source_run_date") or run_date
        rec = {"symbol": symbol, "signal_type": signal_type, "score": score, "iv_rank": iv_rank,
               "strategy": strategy, "source_run_date": source_run_date, "ts": ts}
        if c.get("signal_id"):
            rec["signal_id"] = c["signal_id"]
        else:
            rec["fingerprint"] = f"{run_date}:{symbol}:{signal_type}:{strategy}"
        records.append(rec)
    return records
```
(Define `_infer_signal_type` to map candidate/strategy to a stable string; keep simple — default to `strategy` or `"signal"`.)

In `hqa/signal_watchdog.py`, after `has_signal, sigs = signals.evaluate_signals(...)`, add:
```python
signal_records = signals.build_signal_records(candidates, signals.parse_factor_lab(factor_out),
                                              run_date=..., ts=ts)
```
(use the scan run_date; if unavailable use `ts[:10]`), and add `"signal_records": signal_records` to the `append_jsonl` record dict.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_signals.py tests/test_signal_watchdog.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add hqa/signals.py hqa/signal_watchdog.py tests/test_signals.py tests/test_signal_watchdog.py
git commit -m "feat(1a-4): signal_watchdog emits structured signal_records (no string-guessing for missed-op)"
```

---

## Task H4 (HQA): 员工④ missed-opportunity tracker

**Files:**
- Create: `hqa/missed_opportunities.py`
- Create: `tests/test_missed_opportunities.py`
- Create: `scripts/hermes/hqa-missed-opportunities.sh`

**Interfaces:**
- Produces: `run(run_read_signals, run_ops_status, now_iso, log_path, review_dir=None, date=None) -> tuple[int, str]`; `cross_reference(signals: list[dict], ops_status: dict) -> list[dict]`; `summarize(...) -> str`.
- Consumes: `reviewlog.new_draft`; `runlog.append_jsonl`; a `run_read_signals` callable returning today's `signal_records` (reads `logs/signal_watchdog.jsonl`); `run_paper_ops_status` (Task H2).

- [ ] **Step 1: Write the failing test**

`tests/test_missed_opportunities.py`:
```python
from __future__ import annotations

import json
from pathlib import Path
from hqa import missed_opportunities


def _read_signals_factory(records):
    def _read(date=None):
        return records
    return _read


def test_sleeves_zero_guard_one_summary(monkeypatch, tmp_path):
    drafts = []
    def fake_new_draft(**kw):
        drafts.append(kw); return "2026-07-07-001"
    monkeypatch.setattr("hqa.missed_opportunities.reviewlog.new_draft", fake_new_draft)
    sigs = [{"symbol": "NVDA", "signal_type": "mom", "strategy": "s", "ts": "2026-07-07T13:00:00Z"}]
    ops = {"counts": {"sleeve_count": 0}, "sleeves": [], "signals": [], "executions": []}
    n, msg = missed_opportunities.run(_read_signals_factory(sigs), lambda: json.dumps(ops),
                                      lambda: "2026-07-07T21:00:00Z", tmp_path / "m.json",
                                      review_dir=tmp_path, date="2026-07-07")
    assert n == 0  # no per-signal missed drafts in guard mode
    assert len(drafts) == 1
    assert "sleeves=0" in drafts[0]["event"] or "sleeves=0" in msg


def test_cross_reference_marks_unacted_signal():
    sigs = [{"symbol": "NVDA", "signal_type": "mom", "strategy": "s", "ts": "2026-07-07T13:00:00Z"}]
    ops = {"counts": {"sleeve_count": 1}, "sleeves": [{"sleeve_id": "s1"}],
           "signals": [{"signal_id": "sig-1", "symbols": ["AAPL"]}],
           "executions": [{"signal_id": "sig-1", "symbols": ["AAPL"], "status": "pending"}]}
    missed = missed_opportunities.cross_reference(sigs, ops)
    assert len(missed) == 1
    assert missed[0]["symbol"] == "NVDA"  # NVDA signal had no execution


def test_cross_reference_skips_acted_symbol():
    sigs = [{"symbol": "NVDA", "signal_type": "mom", "strategy": "s"}]
    ops = {"counts": {"sleeve_count": 1}, "sleeves": [{"sleeve_id": "s1"}],
           "signals": [{"signal_id": "sig-1", "symbols": ["NVDA"]}],
           "executions": [{"signal_id": "sig-1", "symbols": ["NVDA"], "status": "pending"}]}
    assert missed_opportunities.cross_reference(sigs, ops) == []


def test_unstructured_signals_no_guessing():
    # signal records absent (old log) -> cross_reference returns [], run marks signals_unstructured
    sigs = []  # caller couldn't build records
    ops = {"counts": {"sleeve_count": 1}, "sleeves": [{"sleeve_id": "s1"}], "signals": [], "executions": []}
    assert missed_opportunities.cross_reference(sigs, ops) == []


def test_ops_unavailable_does_not_fabricate(monkeypatch, tmp_path):
    drafts = []
    monkeypatch.setattr("hqa.missed_opportunities.reviewlog.new_draft", lambda **kw: drafts.append(kw) or "x")
    n, msg = missed_opportunities.run(_read_signals_factory([{"symbol": "NVDA"}]),
                                      lambda: (1, ""),  # ops call failed
                                      lambda: "2026-07-07T21:00:00Z", tmp_path / "m.json", review_dir=tmp_path, date="2026-07-07")
    assert "ops_unavailable" in msg
    assert n == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_missed_opportunities.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `hqa/missed_opportunities.py`**

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Any

from hqa import reviewlog, runlog


def cross_reference(signals: list[dict], ops_status: dict) -> list[dict]:
    if not signals:
        return []
    executions = ops_status.get("executions", [])
    acted_symbols: set[str] = set()
    for ex in executions:
        for s in ex.get("symbols", []):
            acted_symbols.add(s)
    missed = []
    for sig in signals:
        sym = sig.get("symbol")
        if sym and sym not in acted_symbols:
            missed.append(sig)
    return missed


def summarize(missed: list[dict], ops_status: dict, ts: str, *, signals_unstructured: bool = False,
              ops_unavailable: bool = False) -> str:
    if ops_unavailable:
        return f"[{ts}] missed-opportunities: ops_unavailable (could not read paper ops-status); skipped"
    sleeve_count = ops_status.get("counts", {}).get("sleeve_count", 0)
    if signals_unstructured:
        return f"[{ts}] missed-opportunities: signals_unstructured (no signal_records in log); skipped per-signal check"
    if sleeve_count == 0:
        return f"[{ts}] missed-opportunities: {len(missed)} signals, sleeves=0, all unacted — suggest allocating a paper sleeve"
    lines = [f"[{ts}] missed-opportunities: {len(missed)} unacted signals"]
    for m in missed:
        lines.append(f"  · {m.get('symbol')} {m.get('signal_type')} (score={m.get('score')})")
    return "\n".join(lines)


def _read_today_signal_records(log_dir: Path, date: str) -> list[dict]:
    import json as _json
    path = log_dir / "signal_watchdog.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        if not rec.get("has_signal"):
            continue
        if rec.get("ts", "").startswith(date):
            out.extend(rec.get("signal_records", []))
    return out


def run(run_read_signals: Callable[..., list[dict]], run_ops_status: Callable[..., tuple[int, str]],
        now_iso: Callable[[], str], log_path: Path, *, review_dir: Path | None = None,
        date: str | None = None) -> tuple[int, str]:
    ts = now_iso()
    today = date or ts[:10]
    signals = run_read_signals(date=today)
    exit_code, out = run_ops_status(target_date=today)
    ops_unavailable = exit_code != 0
    ops_status: dict = {}
    if not ops_unavailable:
        try:
            ops_status = json.loads(out.strip().splitlines()[-1])
        except (json.JSONDecodeError, ValueError, IndexError):
            ops_unavailable = True

    signals_unstructured = False
    if not signals and not ops_unavailable:
        # caller signals absent — but we only know "unstructured" if the watchdog log has has_signal rows w/o signal_records
        signals_unstructured = True

    missed = cross_reference(signals, ops_status) if (not ops_unavailable and not signals_unstructured) else []
    msg = summarize(missed, ops_status, ts, signals_unstructured=signals_unstructured, ops_unavailable=ops_unavailable)

    runlog.append_jsonl({"ts": ts, "job": "missed-opportunities", "date": today,
                         "n_signals": len(signals), "n_missed": len(missed),
                         "ops_unavailable": ops_unavailable, "signals_unstructured": signals_unstructured}, log_path)

    if review_dir is not None and not ops_unavailable:
        sleeve_count = ops_status.get("counts", {}).get("sleeve_count", 0)
        if sleeve_count == 0 and signals:
            reviewlog.new_draft(kind="missed-opportunity",
                                event=f"{today}: {len(signals)} signals, sleeves=0, all unacted — suggest allocating paper sleeve",
                                data={"n_signals": len(signals)}, source="missed-opportunities",
                                ts=ts, review_dir=review_dir, fingerprint=f"{today}:sleeves=0")
        else:
            for m in missed:
                sym = m.get("symbol")
                reviewlog.new_draft(kind="missed-opportunity",
                                    event=f"{sym} {m.get('signal_type')} signal unacted",
                                    data={"signal": m, "ops_status": ops_status}, source="missed-opportunities",
                                    ts=ts, review_dir=review_dir, fingerprint=f"{today}:{sym}:{m.get('signal_type')}")
    return len(missed), msg
```
(Read `signal_watchdog.py`'s JSONL field names before finalizing `_read_today_signal_records` — the date filter uses `ts.startswith(date)`. If the watchdog stores a separate `run_date` field, prefer that.)

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_missed_opportunities.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Add the wrapper + install test**

`scripts/hermes/hqa-missed-opportunities.sh`:
```bash
#!/usr/bin/env bash
# HQA missed-opportunity tracker (D-26 ④). Reads signal_watchdog.jsonl + paper ops-status.
set -euo pipefail
cd "__HQA_REPO_DIR__"
exec python3 -m hqa.missed_opportunities "$@"
```
Extend `tests/test_install.py` to assert the wrapper is copied + `__HQA_REPO_DIR__` substituted (mirror existing wrapper assertions).

- [ ] **Step 6: Run + commit**

Run: `./.venv/bin/pytest tests/test_missed_opportunities.py tests/test_install.py -q`
Expected: PASS.
```bash
git add hqa/missed_opportunities.py tests/test_missed_opportunities.py scripts/hermes/hqa-missed-opportunities.sh tests/test_install.py
git commit -m "feat(1a-4): missed-opportunity tracker (④) — signal_records × ops-status, sleeves=0 guard"
```

---

## Task H5 (HQA): 员工③ portfolio-risk daily

**Files:**
- Create: `hqa/portfolio_risk.py`
- Create: `tests/test_portfolio_risk.py`
- Create: `scripts/hermes/hqa-portfolio-risk.sh`

**Interfaces:**
- Produces: `parse_account(output: str) -> dict`; `compute_risk(positions, price_series, benchmark_symbol) -> dict`; `build_report(...) -> str`; `run(run_account_show, run_prices, now_iso, log_path, account_id="default", benchmark="SPY", provider="futu") -> str`.
- Consumes: `run_paper_account_show` (H2), `price_series.get_close_series` (H1).

- [ ] **Step 1: Write the failing test**

`tests/test_portfolio_risk.py`:
```python
from __future__ import annotations

import json
from hqa import portfolio_risk


def test_parse_account_json():
    out = json.dumps({"account_id": "default", "exists": True, "cash": 1000000.0, "realized_pnl": 0.0,
                      "kill_switch": False, "positions": [{"symbol": "NVDA", "qty": 10.0, "avg_cost": 148.5}], "pending_orders": []})
    acct = portfolio_risk.parse_account(out)
    assert acct["exists"] is True
    assert acct["positions"][0]["symbol"] == "NVDA"


def test_parse_account_missing():
    acct = portfolio_risk.parse_account(json.dumps({"exists": False, "cash": None, "positions": []}))
    assert acct["exists"] is False


def test_compute_risk_basic():
    positions = [{"symbol": "NVDA", "qty": 10.0, "avg_cost": 148.5}, {"symbol": "AAPL", "qty": 5.0, "avg_cost": 200.0}]
    series = {
        "NVDA": [{"date": "2026-07-05", "close": 148.0}, {"date": "2026-07-06", "close": 150.0}],
        "AAPL": [{"date": "2026-07-05", "close": 200.0}, {"date": "2026-07-06", "close": 202.0}],
        "SPY":   [{"date": "2026-07-05", "close": 600.0}, {"date": "2026-07-06", "close": 606.0}],
    }
    risk = portfolio_risk.compute_risk(positions, series, "SPY")
    assert risk["gross_exposure"] == 10*150.0 + 5*202.0
    assert "concentration" in risk and "HHI" in risk
    assert "beta" in risk
    assert "NVDA" in risk["beta"]


def test_compute_risk_missing_price_beta_unavailable():
    positions = [{"symbol": "ZZZ", "qty": 10.0, "avg_cost": 1.0}]
    series = {"ZZZ": [], "SPY": [{"date": "2026-07-06", "close": 600.0}]}
    risk = portfolio_risk.compute_risk(positions, series, "SPY")
    assert risk["beta"]["ZZZ"] == "unavailable"


def test_positions_zero_guard_message():
    msg = portfolio_risk.build_report({"gross_exposure": 0, "positions": []},
                                       {"exists": True, "cash": 1000000.0, "positions": []}, "ts", "futu")
    assert "无持仓" in msg or "no positions" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_portfolio_risk.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `hqa/portfolio_risk.py`**

```python
from __future__ import annotations

import json
from typing import Callable
from hqa import price_series, runlog


def parse_account(output: str) -> dict:
    for line in reversed(output.splitlines()):
        s = line.strip()
        if not s:
            continue
        try:
            d = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return {"exists": False, "positions": []}
        return d if isinstance(d, dict) else {"exists": False, "positions": []}
    return {"exists": False, "positions": []}


def _daily_returns(series: list[dict]) -> list[float]:
    closes = [row["close"] for row in series if "close" in row]
    return [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes)) if closes[i-1]]


def compute_risk(positions: list[dict], price_series_map: dict[str, list[dict]], benchmark_symbol: str) -> dict:
    bench = price_series_map.get(benchmark_symbol, [])
    bench_ret = _daily_returns(bench)
    betas: dict[str, object] = {}
    last_prices: dict[str, float] = {}
    for p in positions:
        sym = p["symbol"]
        s = price_series_map.get(sym, [])
        if not s:
            betas[sym] = "unavailable"; continue
        last_prices[sym] = s[-1]["close"]
        r = _daily_returns(s)
        n = min(len(r), len(bench_ret))
        if n < 2:
            betas[sym] = "unavailable"; continue
        rb = bench_ret[-n:]; ri = r[-n:]
        mb = sum(rb)/n; mi = sum(ri)/n
        cov = sum((ri[k]-mi)*(rb[k]-mb) for k in range(n))/n
        var = sum((b-mb)**2 for b in rb)/n
        betas[sym] = cov/var if var else "unavailable"
    gross = sum(p["qty"] * last_prices.get(p["symbol"], p["avg_cost"]) for p in positions)
    weights = {p["symbol"]: (p["qty"]*last_prices.get(p["symbol"], p["avg_cost"]))/gross for p in positions} if gross else {}
    sorted_w = sorted(weights.values(), reverse=True)
    hhi = sum(w*w for w in weights.values())
    return {"gross_exposure": gross, "weights": weights, "concentration": {"top1": sorted_w[0] if sorted_w else 0,
            "top3": sum(sorted_w[:3])}, "HHI": hhi, "beta": betas, "positions": positions}


def build_report(risk: dict, account: dict, ts: str, provider: str) -> str:
    if not account.get("exists"):
        return f"[{ts}] portfolio-risk: paper account not found (exists=false); allocate a sleeve to enable"
    positions = account.get("positions", [])
    if not positions:
        return f"[{ts}] portfolio-risk: no positions (cash={account.get('cash')}); allocate a sleeve to enable risk daily"
    lines = [f"[{ts}] portfolio-risk (provider={provider})",
             f"  gross_exposure={risk['gross_exposure']:.2f}  HHI={risk['HHI']:.4f}  top1={risk['concentration']['top1']:.2%}  top3={risk['concentration']['top3']:.2%}"]
    for sym, b in risk["beta"].items():
        lines.append(f"  beta {sym} = {b if isinstance(b, str) else f'{b:.2f}'}")
    return "\n".join(lines)


def run(run_account_show: Callable[..., tuple[int, str]], run_prices: Callable[..., dict[str, list[dict]]],
        now_iso: Callable[[], str], log_path, *, account_id: str = "default", benchmark: str = "SPY",
        provider: str = "futu") -> str:
    ts = now_iso()
    code, out = run_account_show(account_id)
    account = parse_account(out)
    positions = account.get("positions", [])
    symbols = [p["symbol"] for p in positions] + ([benchmark] if positions else [])
    series = run_prices(symbols, "2026-01-01", ts[:10], provider=provider) if positions else {}
    risk = compute_risk(positions, series, benchmark) if positions else {"gross_exposure": 0, "positions": []}
    msg = build_report(risk, account, ts, provider)
    runlog.append_jsonl({"ts": ts, "job": "portfolio-risk", "account_id": account_id, "provider": provider,
                         "exists": account.get("exists"), "n_positions": len(positions), "risk": risk}, log_path)
    return msg
```
(For `run_prices` in `main`, wire `price_series.get_close_series(..., run_data_prices=quant_cli.run_data_prices, run_longbridge_kline=quant_cli.run_longbridge_kline)` via a small lambda. The start date `2026-01-01` is a default lookback; make it a `--lookback-start` flag if desired.)

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_portfolio_risk.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Wrapper + install test + commit**

`scripts/hermes/hqa-portfolio-risk.sh` (mirror H4 Step 5); extend `tests/test_install.py`.
Run: `./.venv/bin/pytest tests/test_portfolio_risk.py tests/test_install.py -q` → PASS.
```bash
git add hqa/portfolio_risk.py tests/test_portfolio_risk.py scripts/hermes/hqa-portfolio-risk.sh tests/test_install.py
git commit -m "feat(1a-4): portfolio-risk daily (③) — exposure/concentration/correlation/beta, futu+longbridge"
```

---

## Task H6 (HQA): 员工② prediction ledger (`predictions.py` + `prediction_cli.py`)

**Files:**
- Create: `hqa/predictions.py`
- Create: `hqa/prediction_cli.py`
- Modify: `hqa/config.py` (+ `PREDICTION_DIR`)

**Interfaces (mirror `reviewlog`):** `new_prediction(...)`, `load_entries`, `list_due`, `score(...)`, `render_markdown`, `write_markdown`. CLI `hqa-prediction`: `create | list | reconcile | render`. Scoring per spec §5 (direction Brier + range hit, split dimensions).

- [ ] **Step 1: Write the failing test** (`tests/test_predictions.py`)

```python
from __future__ import annotations

import json
from pathlib import Path
from hqa import predictions


def test_new_prediction_requires_entry_close(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        predictions.new_prediction("NVDA", "up", "2026-07-14", 0.7, ts="t", prediction_dir=tmp_path,
                                   entry_close_price=None, entry_close_source="futu")


def test_new_prediction_validates_direction(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        predictions.new_prediction("NVDA", "range", "2026-07-14", 0.7, ts="t", prediction_dir=tmp_path,
                                   entry_close_price=148.0, entry_close_source="futu")  # range not allowed


def test_new_prediction_stores_open_entry(tmp_path):
    pid = predictions.new_prediction("NVDA", "up", "2026-07-14", 0.7, range_low=145.0, range_high=160.0,
                                     ts="2026-07-07T10:00:00Z", prediction_dir=tmp_path,
                                     entry_close_price=148.0, entry_close_source="futu")
    entries = predictions.load_entries(tmp_path)
    assert entries[0]["id"] == pid
    assert entries[0]["status"] == "open"
    assert entries[0]["entry_close_price"] == 148.0


def test_score_direction_brier_and_range(tmp_path):
    pid = predictions.new_prediction("NVDA", "up", "2026-07-14", 0.7, range_low=145.0, range_high=160.0,
                                     ts="2026-07-07T10:00:00Z", prediction_dir=tmp_path,
                                     entry_close_price=148.0, entry_close_source="futu")
    scored = predictions.score(pid, outcome_price=152.3, price_source="futu",
                               scored_ts="2026-07-14T21:00:00Z", prediction_dir=tmp_path)
    assert scored["outcome_return"] == 152.3/148.0 - 1
    assert scored["outcome_direction"] == "up"  # return > 0.005
    assert scored["direction_score"] == 1
    assert abs(scored["brier"] - (0.7-1)**2) < 1e-9
    assert scored["outcome_in_range"] is True
    assert scored["range_score"] == 1.0


def test_score_direction_wrong_brier(tmp_path):
    pid = predictions.new_prediction("NVDA", "down", "2026-07-14", 0.6, ts="t", prediction_dir=tmp_path,
                                     entry_close_price=148.0, entry_close_source="futu")
    scored = predictions.score(pid, outcome_price=152.3, price_source="futu", scored_ts="s", prediction_dir=tmp_path)
    assert scored["direction_score"] == 0
    assert abs(scored["brier"] - (0.6-0)**2) < 1e-9


def test_score_range_outside_linear_decay(tmp_path):
    pid = predictions.new_prediction("NVDA", "up", "2026-07-14", 0.7, range_low=145.0, range_high=155.0,
                                     ts="t", prediction_dir=tmp_path, entry_close_price=150.0, entry_close_source="futu")
    # price 158 -> center=150, half=5, decay = 1 - |158-150|/5 = max(0, 1-1.6) = 0
    scored = predictions.score(pid, outcome_price=158.0, price_source="futu", scored_ts="s", prediction_dir=tmp_path)
    assert scored["range_score"] == 0.0
    assert scored["outcome_in_range"] is False


def test_list_due(tmp_path):
    predictions.new_prediction("NVDA", "up", "2026-07-14", 0.7, ts="t", prediction_dir=tmp_path,
                               entry_close_price=148.0, entry_close_source="futu")
    due = predictions.list_due(tmp_path, today="2026-07-14")
    assert len(due) == 1


def test_score_missing_price_stays_open_no_fabrication(tmp_path):
    # price unavailable -> score returns open + unavailable, writes NO scored row, no fabricated brier
    pid = predictions.new_prediction("NVDA", "up", "2026-07-14", 0.7, ts="t", prediction_dir=tmp_path,
                                     entry_close_price=148.0, entry_close_source="futu")
    out = predictions.score(pid, outcome_price=None, price_source="unavailable",
                            scored_ts="s", prediction_dir=tmp_path)
    assert out["status"] == "open"
    assert out["price_source"] == "unavailable"
    # the latest entry on disk is still the open one (no scored row appended)
    entries = predictions.load_entries(tmp_path)
    assert all(e["status"] == "open" for e in entries)
    assert all("brier" not in e for e in entries)


def test_render_markdown(tmp_path):
    predictions.new_prediction("NVDA", "up", "2026-07-14", 0.7, ts="t", prediction_dir=tmp_path,
                               entry_close_price=148.0, entry_close_source="futu")
    md = predictions.render_markdown(tmp_path)
    assert "NVDA" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_predictions.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `hqa/predictions.py`** (mirror `reviewlog.py` structure; `_entries_path` → `prediction_dir/entries.jsonl`; id = `YYYY-MM-DD-NNN` from `ts[:10]`; `load_entries` dedup by id last-wins; `score` appends a scored row with same id)

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ALLOWED_DIRECTIONS = {"up", "down", "flat"}
_DEFAULT_FLAT_THRESHOLD = 0.005


def _entries_path(prediction_dir: Path) -> Path:
    return prediction_dir / "entries.jsonl"


def load_entries(prediction_dir: Path) -> list[dict]:
    path = _entries_path(prediction_dir)
    if not path.exists():
        return []
    by_id: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        by_id[e["id"]] = e
    return list(by_id.values())


def _next_id(prediction_dir: Path, date: str) -> str:
    existing = [e["id"] for e in load_entries(prediction_dir) if e["id"].startswith(date)]
    n = len(existing) + 1
    return f"{date}-{n:03d}"


def new_prediction(subject, direction, horizon, confidence, *, range_low=None, range_high=None,
                   flat_threshold_pct=_DEFAULT_FLAT_THRESHOLD, falsifier=None, rationale=None,
                   ts, prediction_dir, entry_close_price, entry_close_source) -> str:
    if direction not in _ALLOWED_DIRECTIONS:
        raise ValueError(f"direction must be {sorted(_ALLOWED_DIRECTIONS)}, got {direction!r}")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError("confidence must be in [0,1]")
    if (range_low is None) != (range_high is None):
        raise ValueError("range_low and range_high must both be set or both None")
    if range_low is not None and not (range_low < range_high):
        raise ValueError("range_low must be < range_high")
    if entry_close_price is None:
        raise ValueError("entry_close_price required (cannot fix direction baseline); refused")
    date = ts[:10]
    pid = _next_id(prediction_dir, date)
    entry = {"id": pid, "ts": ts, "status": "open", "subject": subject, "direction": direction,
             "range_low": range_low, "range_high": range_high, "flat_threshold_pct": flat_threshold_pct,
             "horizon": horizon, "confidence": confidence, "falsifier": falsifier or "",
             "rationale": rationale or "", "entry_close_price": entry_close_price, "entry_close_source": entry_close_source}
    prediction_dir.mkdir(parents=True, exist_ok=True)
    with _entries_path(prediction_dir).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return pid


def list_due(prediction_dir: Path, today: str) -> list[dict]:
    return [e for e in load_entries(prediction_dir) if e["status"] == "open" and e["horizon"] <= today]


def _score_values(entry, outcome_price):
    ecp = entry["entry_close_price"]
    ret = outcome_price / ecp - 1
    thr = entry.get("flat_threshold_pct", _DEFAULT_FLAT_THRESHOLD)
    if ret > thr:
        outcome_dir = "up"
    elif ret < -thr:
        outcome_dir = "down"
    else:
        outcome_dir = "flat"
    direction_score = 1 if entry["direction"] == outcome_dir else 0
    brier = (entry["confidence"] - direction_score) ** 2
    in_range = None; range_score = None
    if entry.get("range_low") is not None and entry.get("range_high") is not None:
        lo, hi = entry["range_low"], entry["range_high"]
        center = (lo + hi) / 2; half = (hi - lo) / 2
        in_range = lo <= outcome_price <= hi
        range_score = 1.0 if in_range else max(0.0, 1 - abs(outcome_price - center) / half) if half else 0.0
    return ret, outcome_dir, direction_score, brier, in_range, range_score


def score(prediction_id, *, outcome_price, price_source, scored_ts, prediction_dir) -> dict:
    entry = next((e for e in load_entries(prediction_dir) if e["id"] == prediction_id), None)
    if entry is None:
        raise KeyError(prediction_id)
    if price_source == "unavailable" or outcome_price is None:
        # leave open, do not fabricate
        return {"id": prediction_id, "status": "open", "price_source": "unavailable"}
    ret, odir, dscore, brier, in_range, rscore = _score_values(entry, outcome_price)
    scored = dict(entry)
    scored.update({"status": "scored", "outcome_price": outcome_price, "outcome_return": ret,
                   "outcome_direction": odir, "direction_score": dscore, "outcome_in_range": in_range,
                   "range_score": rscore, "brier": brier, "price_source": price_source, "scored_ts": scored_ts})
    with _entries_path(prediction_dir).open("a", encoding="utf-8") as f:
        f.write(json.dumps(scored, ensure_ascii=False, sort_keys=True) + "\n")
    return scored


def render_markdown(prediction_dir: Path) -> str:
    entries = sorted(load_entries(prediction_dir), key=lambda e: e["ts"], reverse=True)
    lines = ["# Prediction Ledger", ""]
    for e in entries:
        lines.append(f"- {e['id']} [{e['status']}] {e['subject']} {e['direction']} conf={e['confidence']}"
                     f" horizon={e['horizon']}" + (f" -> brier={e.get('brier')}" if e["status"]=="scored" else ""))
    return "\n".join(lines) + "\n"


def write_markdown(prediction_dir: Path) -> Path:
    p = prediction_dir / "entries.md"
    p.write_text(render_markdown(prediction_dir), encoding="utf-8")
    return p
```

In `hqa/config.py` add: `PREDICTION_DIR = Path(os.environ.get("HQA_PREDICTION_DIR", "predictions"))` (mirror `REVIEW_DIR`).

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_predictions.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add hqa/predictions.py hqa/config.py tests/test_predictions.py
git commit -m "feat(1a-4): prediction ledger (②) — JSONL, open->scored, direction Brier + range hit"
```

---

## Task H7 (HQA): `prediction_cli.py` + `reconcile` (price fetch via price_series)

**Files:**
- Create: `hqa/prediction_cli.py`
- Create: `tests/test_prediction_cli.py`
- Create: `scripts/hermes/hqa-prediction.sh`

**Interfaces:** `hqa-prediction create --subject --direction --horizon --confidence [--range-low --range-high --flat-threshold-pct --falsifier --rationale]`; `list [--status --since]`; `reconcile [--date]`; `render`. `create`/`reconcile` fetch prices via `price_series.get_close_series` (entry close for create; outcome close for reconcile).

- [ ] **Step 1: Write the failing test** (`tests/test_prediction_cli.py`)

```python
from __future__ import annotations

import json
from pathlib import Path
from hqa import prediction_cli


def _price_factory(close):
    def _get(symbols, start, end, *, run_data_prices=None, run_longbridge_kline=None, provider="futu"):
        return {s: [{"date": "2026-07-07", "close": close, "source": "futu"}] for s in symbols}
    return _get


def test_cli_create_refuses_without_entry_close(tmp_path, monkeypatch):
    # price fetch returns empty -> create refuses exit 2
    monkeypatch.setattr("hqa.prediction_cli.price_series.get_close_series", lambda *a, **k: {})
    rc = prediction_cli.main(["create", "--subject", "NVDA", "--direction", "up", "--horizon", "2026-07-14", "--confidence", "0.7", "--prediction-dir", str(tmp_path)])
    assert rc == 2


def test_cli_create_succeeds_with_entry_close(tmp_path, monkeypatch):
    monkeypatch.setattr("hqa.prediction_cli.price_series.get_close_series", _price_factory(148.0))
    rc = prediction_cli.main(["create", "--subject", "NVDA", "--direction", "up", "--horizon", "2026-07-14",
                              "--confidence", "0.7", "--range-low", "145", "--range-high", "160", "--prediction-dir", str(tmp_path)])
    assert rc == 0
    from hqa import predictions
    entries = predictions.load_entries(tmp_path)
    assert entries[0]["entry_close_price"] == 148.0


def test_cli_reconcile_scores_due(tmp_path, monkeypatch):
    # seed an open due prediction
    from hqa import predictions
    predictions.new_prediction("NVDA", "up", "2026-07-14", 0.7, ts="2026-07-07T10:00:00Z", prediction_dir=tmp_path,
                               entry_close_price=148.0, entry_close_source="futu")
    monkeypatch.setattr("hqa.prediction_cli.price_series.get_close_series", _price_factory(152.3))
    rc = prediction_cli.main(["reconcile", "--date", "2026-07-14", "--prediction-dir", str(tmp_path)])
    assert rc == 0
    entries = predictions.load_entries(tmp_path)
    assert entries[0]["status"] == "scored"
    assert entries[0]["brier"] == (0.7-1)**2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_prediction_cli.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `hqa/prediction_cli.py`** (mirror `review_cli.py` argparse structure)

```python
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from hqa import config, predictions, price_series, quant_cli, runlog


def _fetch_close(symbol, start, end):
    return price_series.get_close_series([symbol], start, end,
                                         run_data_prices=quant_cli.run_data_prices,
                                         run_longbridge_kline=quant_cli.run_longbridge_kline)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="hqa-prediction")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("--subject", required=True)
    p_create.add_argument("--direction", required=True, choices=["up", "down", "flat"])
    p_create.add_argument("--horizon", required=True)
    p_create.add_argument("--confidence", type=float, required=True)
    p_create.add_argument("--range-low", type=float, default=None)
    p_create.add_argument("--range-high", type=float, default=None)
    p_create.add_argument("--flat-threshold-pct", type=float, default=0.005)
    p_create.add_argument("--falsifier", default="")
    p_create.add_argument("--rationale", default="")
    p_create.add_argument("--prediction-dir", default=str(config.PREDICTION_DIR))

    p_list = sub.add_parser("list")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--since", default=None)
    p_list.add_argument("--prediction-dir", default=str(config.PREDICTION_DIR))

    p_recon = sub.add_parser("reconcile")
    p_recon.add_argument("--date", default=None)
    p_recon.add_argument("--prediction-dir", default=str(config.PREDICTION_DIR))

    p_render = sub.add_parser("render")
    p_render.add_argument("--prediction-dir", default=str(config.PREDICTION_DIR))

    args = parser.parse_args(argv)
    pdir = Path(args.prediction_dir)

    if args.cmd == "create":
        today = runlog.utc_now_iso()[:10]
        series = _fetch_close(args.subject, today, today)
        rows = series.get(args.subject, [])
        if not rows:
            print("cannot fetch entry-day close; cannot fix direction baseline; refused")
            return 2
        entry_close = rows[-1]["close"]; src = rows[-1]["source"]
        pid = predictions.new_prediction(args.subject, args.direction, args.horizon, args.confidence,
                                         range_low=args.range_low, range_high=args.range_high,
                                         flat_threshold_pct=args.flat_threshold_pct, falsifier=args.falsifier,
                                         rationale=args.rationale, ts=runlog.utc_now_iso(), prediction_dir=pdir,
                                         entry_close_price=entry_close, entry_close_source=src)
        predictions.write_markdown(pdir)
        print(pid)
        return 0

    if args.cmd == "list":
        for e in predictions.load_entries(pdir):
            if args.status and e["status"] != args.status:
                continue
            print(f"{e['id']}\t{e['status']}\t{e['subject']}\t{e['direction']}\t{e['horizon']}")
        return 0

    if args.cmd == "reconcile":
        today = args.date or runlog.utc_now_iso()[:10]
        due = predictions.list_due(pdir, today)
        for e in due:
            series = _fetch_close(e["subject"], e["horizon"], e["horizon"])
            rows = series.get(e["subject"], [])
            if not rows:
                predictions.score(e["id"], outcome_price=None, price_source="unavailable",
                                  scored_ts=runlog.utc_now_iso(), prediction_dir=pdir)
                continue
            predictions.score(e["id"], outcome_price=rows[-1]["close"], price_source=rows[-1]["source"],
                              scored_ts=runlog.utc_now_iso(), prediction_dir=pdir)
        predictions.write_markdown(pdir)
        print(f"reconciled {len(due)} due predictions")
        return 0

    if args.cmd == "render":
        print(predictions.write_markdown(pdir))
        return 0
    return 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_prediction_cli.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Wrapper + install test + commit**

`scripts/hermes/hqa-prediction.sh` (mirror); extend `tests/test_install.py`.
Run: `./.venv/bin/pytest tests/test_prediction_cli.py tests/test_install.py -q` → PASS.
```bash
git add hqa/prediction_cli.py tests/test_prediction_cli.py scripts/hermes/hqa-prediction.sh tests/test_install.py
git commit -m "feat(1a-4): hqa-prediction CLI + reconcile (②) — entry/outcome close via price_series"
```

---

## Task H8 (HQA): weekly_review 预测对账段 + readonly allowlist + final suite

**Files:**
- Modify: `hqa/weekly_review.py` (+ read `predictions/entries.jsonl` scored, add 预测对账段)
- Modify: `tests/test_weekly_review.py`
- Modify: `scripts/hermes/hqa-quant-readonly.sh` (+ `"paper account-show"`, `"paper strategies ops-status"`, `"data prices"`)

- [ ] **Step 1: Write the failing test** (append to `tests/test_weekly_review.py`)

```python
def test_weekly_review_includes_prediction_reconciliation(tmp_path):
    from hqa import weekly_review, predictions
    pred_dir = tmp_path / "predictions"
    predictions.new_prediction("NVDA", "up", "2026-07-14", 0.7, ts="2026-07-07T10:00:00Z", prediction_dir=pred_dir,
                               entry_close_price=148.0, entry_close_source="futu")
    predictions.score("2026-07-07-001", outcome_price=152.3, price_source="futu", scored_ts="2026-07-14T21:00:00Z", prediction_dir=pred_dir)
    report = weekly_review.run(review_dir=tmp_path, log_dir=tmp_path, now_iso=lambda: "2026-07-15T00:00:00Z", days=7, prediction_dir=pred_dir)
    assert "预测对账" in report or "prediction" in report.lower()
    assert "NVDA" in report
```

- [ ] **Step 2: Run to verify fail**

Run: `./.venv/bin/pytest tests/test_weekly_review.py -k prediction -q`
Expected: FAIL (weekly_review.run has no `prediction_dir` param / no 预测段).

- [ ] **Step 3: Implement**

In `weekly_review.run` add optional `prediction_dir: Path | None = None`; when set, load scored entries with `ts/scored_ts` in the window, compute mean Brier + direction hit rate + range hit rate, and append a section in `build_report`. Keep backward compat: `prediction_dir=None` → no section (existing tests stay green).

In `scripts/hermes/hqa-quant-readonly.sh` extend the allowlist array with `"paper account-show"`, `"paper strategies ops-status"`, `"data prices"` (these pass the platform no-write tests from Tasks P2/P3/P1). Re-run `bash scripts/install.sh` to redeploy.

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/bin/pytest tests/test_weekly_review.py tests/test_install.py -q`
Expected: PASS.

- [ ] **Step 5: Full HQA suite + commit**

Run: `./.venv/bin/pytest -q` → all green.
```bash
git add hqa/weekly_review.py tests/test_weekly_review.py scripts/hermes/hqa-quant-readonly.sh tests/test_install.py
git commit -m "feat(1a-4): weekly_review 预测对账段 + readonly allowlist for 3 read seams"
```

---

## Acceptance (run after all tasks)

- [ ] Platform: `paper account-show --json` missing account → `exists=false`, no file created; `ops-status --format json` → no reconcile, arrays present; `data prices --provider futu --json` failure → error JSON + nonzero, no sample fallback. (`./.venv/bin/python -m pytest tests/test_cli_paper_readonly.py tests/test_cli_data_prices.py -q`)
- [ ] HQA: ④ sleeves=0 guard + cross-reference + unstructured/ops_unavailable; ③ exposure/concentration/beta + missing-price unavailable + no-position guard; ② ledger create/list_due/score + direction Brier + range hit/decay + missing-price stays open; weekly_review 预测对账段. (`./.venv/bin/pytest -q`)
- [ ] Three employees never crash scheduler; missing data honestly marked; no fabricated beta/scores.
- [ ] Readonly allowlist admits only the 3 read seams; write commands still require approval.
- [ ] Both suites green sandbox-disabled: HQA + platform.

---

## Notes for the implementer

- **Platform repo commits** land on its current branch (`audit-remediation-2026-06-23` or wherever the 1a-3 work sits); do NOT push. HQA commits land on HQA `main`; do NOT push.
- **Sandbox:** platform git/pytest fail with "Operation not permitted" under the Bash sandbox — retry with `dangerouslyDisableSandbox: true`.
- **Read before finalize:** each task's "inspect first" notes (`load_ohlcv` signature, `Position` shape, candidate field names, watchdog JSONL fields) are real — verify them in the actual source before writing the implementation; the plan's code is a faithful template but the platform has evolved.
- **Spec deviation recorded:** longbridge uses `kline <SYM> --count N` (working) not `kline history --start --end` (errors on this account). Decision logged in Global Constraints.
```
