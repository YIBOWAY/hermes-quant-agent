---
name: hqa-quant
description: "HQA quant ops from Hermes — read-only market/signal/radar queries via a pre-authorized gate, human-gated factor & review writes, artifact-first answers, and 30s async triage for long jobs."
version: 1.0.0
platforms: [macos]
metadata:
  hermes:
    tags: [quant, trading, hqa]
    related_skills: []
---

# HQA Quant Ops

Operate the HQA quant stack (Hermes repo `__HQA_REPO_DIR__` + ai-quant-platform
`__HQA_PLATFORM_DIR__`) with minimum round-trips. Two rules keep latency low and
safety intact:

1. **Answer from artifacts first** — the scheduled watchdogs already wrote the
   answer to a JSONL log. Read it before running anything.
2. **Read-only queries are pre-authorized; writes are not.** Read-only platform
   queries go through one gate wrapper that Hermes may run without asking. Any
   command that mutates an account, approves a factor, or trades stays behind a
   human approval prompt — never bypass it.

## 1. Command quick-ref

### Read-only platform queries — no approval needed

Run through the single-command gate wrapper (absolute path, one command, no
`&&`/`|`/`;` so the Hermes `command_allowlist` shortcut applies). The wrapper
re-checks the subcommand against a hardcoded read-only allowlist and refuses
anything else with `REFUSED: not in read-only allowlist` (exit 2).

| Question | Command | Expected output |
|---|---|---|
| Local platform health | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh doctor` | offline health summary (safety invariants). If it errors, use the `doctor_watchdog.jsonl` artifact below. |
| Effective config (secrets masked) | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh config show` | JSON settings block |
| Registered research factors | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh factor list` | `factor_id=… name=… version=… lookback=… direction=…` lines |
| Sell-side options radar (fresh scan) | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh options daily-scan` | scan summary + candidate count (writes today's snapshot) |
| Buy-side options screen | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh options buyside-screen` | buy-side candidate table |
| Paper account cash/positions | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh paper account-show --account default` | cash + open positions for the account |
| Pending agent candidates | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh agent list-candidates` | `candidate_id=… type=… status=pending path=…` lines |

The gate forwards trailing flags verbatim, so `paper account-show --account
<id>` and `options daily-scan --top 20` work. Anything not on the allowlist
(e.g. `paper rebalance`, `agent review`, `data ingest-tiingo`, `serve`) is
refused — those are write/side-effecting and keep human approval.

### Human-gated writes — approval required

Run from the repo dir. Each of these mutates state (creates a candidate,
writes an approval lock, runs a backtest, records a review), so Hermes will
show an approval prompt. That is intended; do not try to route them through the
read-only gate.

| Operation | Command |
|---|---|
| Propose factor (Scene-B gate 1) | `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli propose --goal "<hypothesis>" --source-file <factor.py> --universe SPY,QQQ` |
| Approve translation (gate 2, human-only) | `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli approve --candidate-id <id> --note "<translation-review>"` |
| Backtest an approved factor | `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli backtest --factor-id <id> --symbol SPY --start 2020-01-01 --end 2024-12-31` |
| Review draft (post-mortem) | `cd __HQA_REPO_DIR__ && python3 -m hqa.review_cli draft --event "<what happened>" --kind note` |
| Review confirm | `cd __HQA_REPO_DIR__ && python3 -m hqa.review_cli confirm <id> --judgment "<call>" --basis "<why>"` |

Notes on the write path:
- `propose` prints `candidate_id=<id>` then the human gate instruction — do not
  auto-approve; a human inspects the generated factor before `approve`.
- `backtest` reserves the last 183 days as holdout unless `--final` is passed
  (D-21); it also increments a per-factor trial counter and prints an overfit
  warning after 3 runs (D-21). Add `--final` only for the one full-window run
  before promotion.
- Promotion to the live review pool is always a separate human decision.

### `--json` output (D-22 status)

D-22 made the **hqa write-path wrappers** JSON-first: `factor_repro_cli` reads
`candidate_id`/`experiment_id` from a JSON payload when the platform emits one
and falls back to regex otherwise, so parsing is robust either way. The
**platform read-only CLIs above do not yet accept `--json`** (verified
2026-07-06: `… doctor --json` → exit 2, "No such option"). Do not append
`--json` to the gate commands. Revisit this section and add the JSON output
contract once the platform ships it (plan D-25, line 94).

## 2. Artifact-first: read the log, don't re-scan

For any market / signal / radar / safety question, the scheduled jobs already
computed the answer. Read the freshest artifact (last JSONL line = latest run);
only run a fresh scan if the artifact is missing or stale (not today's date).

| Question | Artifact (read last line) | Key fields |
|---|---|---|
| Safety invariants OK? | `__HQA_REPO_DIR__/logs/doctor_watchdog.jsonl` | `alert`, `safety`, `deviations`, `doctor_exit` |
| Any actionable market signal? | `__HQA_REPO_DIR__/logs/signal_watchdog.jsonl` | `has_signal`, `signals[]`, `score_summary` |
| Pre-market digest / headlines | `__HQA_REPO_DIR__/logs/premarket_digest.jsonl` | `headlines[]`, `doctor_exit`, `aihot_error` |
| Options radar candidates | `__HQA_PLATFORM_DIR__/data/options_scans/<YYYY-MM-DD>.jsonl` | per-candidate rows |
| Options scan run metadata | `__HQA_PLATFORM_DIR__/data/options_scans/<YYYY-MM-DD>_meta.json` | `candidate_count`, `scanned_tickers`, `finished_at` |
| Latest reviews / post-mortems | `__HQA_REPO_DIR__/review/entries.jsonl` | `event`, `judgment`, `next_rule`, `status` |

Deployed read-only refresh wrappers (single-command, absolute path) if an
artifact is stale — background them per §3:
`__HERMES_SCRIPTS_DIR__/hqa-options-radar.sh`,
`__HERMES_SCRIPTS_DIR__/hqa-signal-watchdog.sh`,
`__HERMES_SCRIPTS_DIR__/hqa-premarket-digest.sh`.

## 3. 30-second triage: background long jobs, ack immediately

If a task will plausibly take more than ~30s — any backtest, a full options
scan (`options daily-scan` over the full universe), or starting a service — do
not block the conversation polling for it:

1. Launch it in the background (append `&` / run detached).
2. Reply immediately with an ack that includes a run identifier, e.g.
   "started backtest, run_id=<factor-id>-<date>; will push when done".
3. On completion, push the result through the async notifier:
   `__HERMES_SCRIPTS_DIR__/hqa-notify.sh "#backtest" "backtest <run_id> done: sharpe=… report=…"`
   (`hqa-notify.sh` delivers via `hermes send --to discord`, or appends to
   `__HQA_REPO_DIR__/logs/notify_fallback.jsonl` when Discord is unconfigured).

Fast read-only queries and artifact reads (§1, §2) return in well under 30s —
answer those inline, no backgrounding.

## 4. Safety red lines

- **Writes always need human approval.** Propose/approve/backtest, review
  draft/confirm, `paper rebalance`, `agent review`, any data ingest, and any
  trade path stay behind the approval prompt. Never route them through the
  read-only gate to dodge approval.
- **Never flip the safety invariants.** `dry_run=true`, `paper_trading=true`,
  `live_trading_enabled=false`, `kill_switch=true` are load-bearing. Do not run
  commands that disable `paper_trading` or the `kill_switch`. If
  `doctor_watchdog.jsonl` shows `alert: true` on these, surface it — do not
  work around it.
- The read-only gate's allowlist is the trust boundary; if a needed query is
  not on it, ask a human rather than reaching for bare `quant-system`.
