---
name: hqa-quant
description: "HQA quant ops from Hermes — read-only market/signal/radar queries, local prediction and opportunity ledgers, human-gated research/account writes, artifact-first answers, and 30s async triage for long jobs."
version: 1.7.0
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
2. **Read-only queries are pre-authorized; account/research execution writes are
   not.** Read-only platform queries go through one gate wrapper that Hermes may
   run without asking. Any command that mutates an account, approves a factor,
   runs a full options scan, backtests, or trades stays behind a human approval
   prompt — never bypass it. The prediction ledger is a local evidence artifact,
   not an account or execution path; create only when the user explicitly states
   the prediction to record.

## 1. Command quick-ref

### Read-only platform queries — no approval needed

Run through the single-command gate wrapper (absolute path, one command, no
`&&`/`|`/`;` so the Hermes `command_allowlist` shortcut applies). The wrapper
re-checks the subcommand against a hardcoded read-only allowlist and refuses
anything else with `REFUSED: not in read-only allowlist` (exit 2).

| Question | Command | Expected output |
|---|---|---|
| Local platform health | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh doctor` | offline health summary (safety invariants). Prefer the last line of `doctor_watchdog.jsonl` when available. |
| Effective config (secrets masked) | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh config show` | settings block |
| Strict daily history evidence | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh data prices --symbol AAPL --symbol SPY --start 2025-06-01 --end 2026-07-10 --provider futu --adjustment qfq --format json` | one multi-symbol Futu/QFQ envelope; no local/sample fallback |
| Registered research factors | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh factor list` | `factor_id=… name=… version=… lookback=… direction=…` lines |
| Paper account cash/positions | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh paper account-show --account default --format json` | unified `{account_id, account_exists, account}` snapshot with valuation, price provenance, storage mode, warnings, and reconciliation |
| Pending agent candidates | `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh agent list-candidates` | `candidate_id=… type=… status=pending path=…` lines |

The gate forwards trailing flags verbatim (e.g. `paper account-show --account
<main> --format json`). Anything not on the allowlist is refused — including **full options
scans** (`options daily-scan`, `options buyside-screen`, `options daily-task`),
which write snapshots and burn Futu quota. Those are **not** pre-authorized:
read scan results from artifacts (§2), or ask a human to approve a scan wrapper.

### Portfolio risk v2 — no approval needed

Run `__HERMES_SCRIPTS_DIR__/hqa-portfolio-risk.sh --account default` to append
one read-only portfolio-risk artifact and print the human summary generated from
that same artifact. It first consumes the unified **current snapshot** above for
long/short/gross/net exposure, invested-book concentration, account-equity
weights, valuation provenance, and repository evidence. For invested accounts,
v2 then makes one strict `data prices` request for every position plus SPY.

Historical evidence is explicit Futu QFQ daily data only: **no sample, local
cache, Tiingo, or Longbridge substitution**. All symbols are globally aligned by
trading-date inner join before simple close-to-close returns are calculated. At
least **60 aligned returns** are required; that is a data-validity minimum, not a
risk threshold. v2 reports per-position beta vs SPY and position-pair historical
correlation with sample counts. A single position has beta but pair correlation
is not applicable. Provider/sample failure degrades only the history portion;
the current snapshot facts remain visible. Use `--current-only` only when the
user explicitly wants the 9C current-snapshot report without a history request.

This v2 still does **not** calculate VaR, volatility, drawdown, stress, liquidity,
Greeks, FX conversion, forecasts, or projected pending-order exposure. There is
**no risk-policy threshold** configured, so it never invents a breach/safe
verdict. It is an observational report, not trading advice or execution.

### Prediction ledger — local artifact, no trading side effect

Use the deployed JSON-first wrapper; it writes only the HQA-local authoritative
`__HQA_REPO_DIR__/predictions/entries.jsonl` ledger:

| Operation | Command |
|---|---|
| Record an explicit user prediction | `__HERMES_SCRIPTS_DIR__/hqa-prediction.sh create --symbol AAPL --direction up --horizon-date 2026-08-07 --confidence 0.70 --falsifier "the first eligible close is below 300"` |
| Read current states | `__HERMES_SCRIPTS_DIR__/hqa-prediction.sh list --status open` |
| Score one page of due predictions | `__HERMES_SCRIPTS_DIR__/hqa-prediction.sh reconcile --limit 25` |
| Continue a due batch | `__HERMES_SCRIPTS_DIR__/hqa-prediction.sh reconcile --cursor '<next_cursor>' --limit 25` |

`create` and `reconcile` are local artifact writes, but they never modify the
paper account, strategy registry, cache, approval state, or any trading path.
Both consume only strict US-equity Futu/QFQ/1d evidence: **no Longbridge** and
**no sample**, local, Tiingo, or synthetic fallback. The horizon is a calendar
anchor; scoring uses the first actual Futu session `>= horizon_date` and obtains
the entry and outcome prices from the same later QFQ payload.

`confidence` is the probability that the declared direction is correct. The
reported score is a **binary Brier** for that declared-direction event, not a
three-class Brier score. A target range, when supplied, is reported separately
as `range_hit`. Automatic cron/notification and weekly aggregation remain
deferred to full Slice 9H; do not claim they are already running.

### Market foresight + Hermes artifact shelf

Use the proposal wrapper only after the user/Hermes research turn has supplied
the thesis. HQA validates strict completed-session Futu/QFQ evidence; it does
not generate a hidden thesis and does not auto-create a prediction:

| Operation | Command |
|---|---|
| Publish a proposal-only candidate | `__HERMES_SCRIPTS_DIR__/hqa-market-foresight.sh propose --symbol AAPL --subject "product validation" --direction flat --horizon-date 2026-07-17 --confidence 0.50 --falsifier "completed close leaves the declared flat band" --rationale "neutral validation baseline; not investment advice" --request-id <stable-id>` |
| List stored candidates | `__HERMES_SCRIPTS_DIR__/hqa-market-foresight.sh list` |
| Rebuild the cross-source feed | `__HERMES_SCRIPTS_DIR__/hqa-artifacts.sh refresh --limit 50` |
| Read the current feed | `__HERMES_SCRIPTS_DIR__/hqa-artifacts.sh show` |

Every candidate is immutable and explicitly `proposal_only`; promotion into the
prediction ledger requires a later human-confirmed `hqa-prediction.sh create`.
The rebuildable feed at
`__HQA_REPO_DIR__/artifacts/hermes-feed/manifest.v1.json` drives the platform's
read-only `/hermes` artifact shelf. A source may be `empty` without making the
whole feed degraded. Composer submission, cron, notifications, and automated
prediction reconciliation are not wired.

### Opportunity ledger — evidence only, never execution

Use `__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh` for the 9G
signal/decision/action audit trail. The canonical ledger is
`__HQA_REPO_DIR__/opportunities/entries.jsonl`; always read it through the CLI
so the strict reducer validates identity, event hashes and state transitions.

| Operation | Command |
|---|---|
| Backfill threshold-qualified signals from an existing artifact | `__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh sync-signals --date 2026-07-10` |
| Read folded opportunity states | `__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh list --limit 100` |
| Record a human decision | `__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh decide --signal-id <sig_id> --decision decline --actor human:sunyibo --reason "paper options route unavailable" --request-id <stable-id>` |
| Link an already-existing platform execution by exact IDs | `__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh record-action --signal-id <sig_id> --platform-signal-id <platform_signal_id> --platform-execution-id <execution_id> --actor human:sunyibo` |
| Record a complete platform coverage watermark | `__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh sync-actions --signal-id <sig_id> --covered-through <UTC-Z-timestamp>` |
| Assess due eligible signals | `__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh reconcile --limit 50` |

`sync-signals` consumes an existing scan file and never starts a scan.
`record-action` and `sync-actions` call only the bounded, pure
`paper strategies observations` read seam. They do not use the broad
`paper strategies` allowlist prefix and never invoke generate-signal,
create-execution, execute-pending or recovery. Action linking is exact
`signal_id`/`execution_id`; a matching ticker is not causality.

Current Scene-A rows are option contracts, while resident paper sleeves execute
equity strategies. Because no supported paper-options route exists, real
options rows are `not_actionable` (or `unknown` when identity is incomplete)
and cannot become missed. A `missed` assessment requires explicit eligible
route/deadline, complete untruncated coverage through that deadline, and no
timely linked action or decline. It means an action-window miss only—not missed
profit and not advice to trade. Weekly review, shelf projection and
notifications remain full Slice 9H.

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
- `backtest` defaults to **`--provider futu`** (the only configured live data
  source on this machine). Pass `--provider tiingo` only when a Tiingo token is
  configured; otherwise the platform will fail. Non-final runs reserve the last
  183 days as holdout unless `--final` is passed (D-21); a per-factor trial
  counter prints an overfit warning after 3 runs (D-21).
- Promotion to the live review pool is always a separate human decision
  (`agent promote-candidate` on the platform CLI, then human `git diff` + commit).

### `--json` output (D-22 status)

- **HQA write-path wrappers** are JSON-first: `factor_repro_cli` reads
  `candidate_id`/`experiment_id` from a JSON payload when the platform emits one
  and falls back to regex otherwise.
- **Platform `doctor --json` is supported** and is what HQA's doctor watchdog
  already calls. Paper account reads use the verified
  `paper account-show --format json` snapshot contract. Do **not** invent JSON
  flags on other gate commands unless the platform leaf is verified to accept
  them (many still do not).

## 2. Artifact-first: read the log, don't re-scan

For any market / signal / radar / safety question, the scheduled jobs already
computed the answer. Read the freshest artifact (last JSONL line = latest run);
only run a fresh scan if the artifact is missing or stale (not today's date) —
and a full Futu scan requires human approval, not the read-only gate.

| Question | Artifact (read last line) | Key fields |
|---|---|---|
| Safety invariants OK? | `__HQA_REPO_DIR__/logs/doctor_watchdog.jsonl` | `alert`, `channel` (`none`/`infra`/`safety`), `safety`, `deviations`, `doctor_exit` |
| Current + historical portfolio risk | `__HQA_REPO_DIR__/logs/portfolio_risk.jsonl` | `status`, `exposure`, `concentration`, `price_quality`, `history_source`, `historical_risk`, `reason_codes`, `limitations` |
| Any actionable market signal? | `__HQA_REPO_DIR__/logs/signal_watchdog.jsonl` | `has_signal`, `signals[]`, `score_summary`, `artifact_missing`, `thresholds` |
| Pre-market digest / headlines | `__HQA_REPO_DIR__/logs/premarket_digest.jsonl` | `headlines[]`, `doctor_exit`, `aihot_error`, `options` |
| Options radar candidates | `__HQA_PLATFORM_DIR__/data/options_scans/<YYYY-MM-DD>.jsonl` | per-candidate rows |
| Options scan run metadata | `__HQA_PLATFORM_DIR__/data/options_scans/<YYYY-MM-DD>_meta.json` | `candidate_count`, `scanned_tickers`, `finished_at` |
| Latest reviews / post-mortems | `__HQA_REPO_DIR__/review/entries.jsonl` | `event`, `judgment`, `next_rule`, `status` |
| Signal thresholds | `__HQA_REPO_DIR__/data/_runtime/signal_thresholds.json` | `min_score` (required for alert mode); `min_iv_rank` optional |
| Opportunity decisions/actions | `__HQA_REPO_DIR__/opportunities/entries.jsonl` | The watchdog publishes structured `signal_records[]`; do not tail the ledger directly. Use `hqa-opportunities.sh list` for folded `not_actionable`, `unknown`, `acted`, `action_failed`, `expired_coverage_unknown`, or `missed` state. |

The prediction ledger is an event stream, not a latest-run log: **do not tail
its last JSONL line to infer current state**. Use
`__HERMES_SCRIPTS_DIR__/hqa-prediction.sh list` so the strict reducer validates
and folds all created/scored events.

The opportunity ledger follows the same rule: use
`__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh list`; raw last-line inspection
cannot reconstruct decision/action/coverage state.

Deployed refresh wrappers (single-command, absolute path) if an artifact is
stale — background them per §3 when they may take >30s:
`__HERMES_SCRIPTS_DIR__/hqa-portfolio-risk.sh`,
`__HERMES_SCRIPTS_DIR__/hqa-options-radar.sh`,
`__HERMES_SCRIPTS_DIR__/hqa-signal-watchdog.sh`,
`__HERMES_SCRIPTS_DIR__/hqa-premarket-digest.sh`.
Full Futu collect stays on the scheduled `hqa-options-collect` cron (or a human-
approved one-shot); do not smuggle it through the read-only gate.

## 3. 30-second triage: background long jobs, ack immediately

If a task will plausibly take more than ~30s — any backtest, a full options
scan, or starting a service — do not block the conversation polling for it:

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

- **Account, research-execution, and trading writes always need human approval.**
  Propose/approve/backtest, review draft/confirm, `paper rebalance`, `agent
  review`, any data ingest, full options scans, and any trade path stay behind
  the approval prompt. Never route them through the read-only gate to dodge
  approval. A user-requested prediction artifact is not trading authorization.
- **Never flip the safety invariants.** `dry_run=true`, `paper_trading=true`,
  `live_trading_enabled=false`, `kill_switch=true` are load-bearing. Do not run
  commands that disable `paper_trading` or the `kill_switch`. If
  `doctor_watchdog.jsonl` shows `alert: true` with `channel: safety`, surface it
  — do not work around it. `channel: infra` means doctor/platform failed; re-
  check when healthy rather than treating it as a confirmed baseline breach.
- The read-only gate's allowlist is the trust boundary; if a needed query is
  not on it, ask a human rather than reaching for bare `quant-system`.
