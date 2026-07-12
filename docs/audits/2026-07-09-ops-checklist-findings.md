# Ops checklist findings — 2026-07-09

> **Historical ops snapshot:** this records the 2026-07-09 follow-up only. For
> the active cross-repo plan and current git layers, start at
> [`../README.md`](../README.md).

Companion to `2026-07-09-adversarial-review-personal-quant-assistant.md`.
Stop-bleed code was already in the working tree; this note records the five ops
items executed after the audit.

## 1) Redeploy wrappers + skill — DONE

```bash
bash scripts/install.sh
```

Verified:

| Path | Result |
|------|--------|
| `~/.hermes/scripts/hqa-quant-readonly.sh` | allowlist: `doctor`, `config show`, `factor list`, `paper account-show`, `agent list-candidates` only (**no** `options daily-scan` / `buyside-screen`) |
| `~/.hermes/skills/hqa-quant/SKILL.md` | `version: 1.1.0` |

Note: first attempts from the Claude sandbox hit macOS TCC (`Operation not permitted`
on `~/.hermes/scripts/*`); install succeeded with full permissions.

## 2) Discord / gateway delivery — GATEWAY UP; jobs still `Deliver: local`

| Check | Result |
|-------|--------|
| `launchctl` `ai.hermes.gateway` | **running** (pid present; Discord connected as Hermes-bot) |
| `hermes cron status` | **Gateway is running — cron jobs will fire automatically** |
| All 7 HQA jobs | **Deliver: local** (stdout stays local; not pushed to Discord) |

Earlier in the session, sandbox + a SIGTERM teardown made status look down;
launchd had already reinstalled the agent and Discord came back after proxy
(`127.0.0.1:7897`) connected.

**Not changed:** flipping every job to Discord is an outward-facing config change.
Keep `local` until you explicitly want channel noise; use `hqa-notify.sh` for
selective push, or `hermes cron edit <id> --deliver discord` per job.

## 3) Options collect gaps (07-08+, OpenD, sleep, 3600s) — ROOT CAUSE

### Evidence

- Scan artifacts under platform `data/options_scans/`: metas only through
  **2026-07-07** (`01,02,03,06,07`). No `2026-07-08` / `2026-07-09` meta or jsonl.
- Cron `hqa-options-collect` last run: **2026-07-09T00:00:01+08:00**
  `error: Script timed out after 3600s`.
- `iv_history/*` **did** receive **2026-07-08** rows for **78/100** tickers
  (partial run) — history appends mid-scan; **meta/jsonl written only at end**
  (`RadarSnapshotStore.write` after full `daily-task` scan step).
- Successful full run 07-07 wall time ~47 min (`15:11` → `15:58` UTC in
  `daily_task_status.json`); wrapper comment estimates ~56 min at ~33s/symbol.
- OpenD app present: `/Applications/Futu_OpenD.app`. 07-07 had 10
  `FutuProviderError` failures mid-universe (rate limit / session flaps).
- Mac sleep / caffeinate: not proven as primary; **hard timeout is sufficient**
  to explain missing end-of-run artifacts even if OpenD stayed up.

### Actions taken

1. Raised Hermes `cron.script_timeout_seconds`: **3600 → 7200** in
   `~/.hermes/config.yaml` (headroom for Futu retries).
2. Updated `scripts/hermes/hqa-options-collect.sh` comment + redeployed.

### Still open (manual / next window)

- Ensure **OpenD is logged in** before 23:00 Mon–Fri local.
- Prefer machine awake for the ~1h collect window (or `caffeinate` wrapper later).
- Tonight’s 23:00 collect should be the first test of 7200s; watch for meta
  `2026-07-09` (or next US session date labeling).
- Optional later: incremental/resume collect so a kill still leaves a usable
  partial snapshot (platform change).

## 4) Review-library hygiene + threshold decision — DONE

All prior drafts confirmed via `python -m hqa.review_cli confirm`:

| ID | Kind | Judgment |
|----|------|----------|
| `2026-07-03-001` | manual | workspace half-rollback; restored |
| `2026-07-03-002` … `2026-07-07-001` (6×) | alert | **false-alarm**: empty safety + non-zero doctor → infra, not kill-switch (PR-1) |
| `2026-07-09-001` | decision | **min_score=150**, **min_iv_rank=null** until IV history matures |

`review/entries.md` re-rendered. Runtime review files remain gitignored.

## 5) Platform `iv_rank` all-null — ROOT CAUSE

### Facts

- `2026-07-07.jsonl`: **686/686** rows have top-level `iv_rank: null` (and nested
  `candidate.iv_rank: null`).
- `compute_iv_rank` (`ai-quant-platform` `options/iv_history.py`):

  ```text
  min_samples = 30
  history = all current_iv rows (last lookback_days raw appends, not unique days)
  if len(history) < min_samples: return None
  ```

- Per scanned ticker after 07-07: history **min/med/max rows ≈ 15/22/22**, all
  **&lt; 30** → rank always `None`.
- Unique calendar `run_date`s in history: only **6**
  (`07-01,02,03,06,07,08`).
- Extra inflation: `_record_atm_iv` runs **inside the strategy loop** → up to
  **2 appends/ticker/day** (sell_put + covered_call), so raw row count rises
  faster than true day-span; even so, median still under 30.
- Early rows often show placeholder-ish `current_iv=0.28` (4 tickers stuck only
  on 0.28); later rows have real ATM IV range, but rank never unlocks without
  sample count.

### Implications for HQA

- Keeping `min_iv_rank: null` in `data/_runtime/signal_thresholds.json` is
  **correct** — any non-null floor would drop every candidate.
- `global_score` treats missing rank as `0` (`0.4 * clip(iv_rank or 0)`), so
  scores are systematically **under-weighted** on the IV term until history
  matures.
- Unlock paths (platform, not done here):

  1. ~**8+ more successful raw appends** (or ~**24 unique trading days** if
     deduped by day) at current cadence; or
  2. Lower `min_samples` (e.g. 10–15) for early-life rank with wider
     uncertainty; and/or
  3. Deduplicate history by `run_date` (one ATM IV per day) so multi-strategy
     double-writes stop polluting the series; and/or
  4. Seed history from a longer IV source if available.

## DoD snapshot (ops)

| Item | Status |
|------|--------|
| install wrappers + skill 1.1.0 | done |
| gateway running + Discord connected | done (jobs remain Deliver local by design) |
| collect gap explained + timeout 7200 | done; next collect is the proof |
| review drafts closed + threshold confirmed | done |
| iv_rank null root-caused | done; min_iv_rank stays null |

Stop-bleed code in the HQA repo is still uncommitted unless you ask for a commit.
