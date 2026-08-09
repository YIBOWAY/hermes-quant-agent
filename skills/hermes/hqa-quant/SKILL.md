---
name: hqa-quant
description: "HQA quant ops from Hermes — read-only market/signal/radar queries, local prediction and opportunity ledgers, human-gated research/account writes, artifact-first answers, and 30s async triage for long jobs."
version: 1.15.0
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
as `range_hit`. Full Slice 9H now performs bounded automatic prediction
reconciliation after the US close; it never creates a prediction automatically.

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
whole feed degraded. Feed schema 1.1 has six exact sources: portfolio risk,
prediction, market foresight, weekly review, opportunity summary, and automation
status. Composer submission remains disabled and is not wired to an agent-task
POST route.

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
profit and not advice to trade. Full Slice 9H aggregates these folded states;
it still never infers causality from a ticker or creates a decision/action.

### Full Slice 9H automation — read-only/proposal-only

The four installed no-agent wrappers are the only automation entry points:

| Job | Wrapper | Asia/Shanghai schedule |
|---|---|---|
| Post-close reconcile | `__HERMES_SCRIPTS_DIR__/hqa-full-9h-daily-close.sh` | `15,25 8 * * 2-6` |
| Freshness projection | `__HERMES_SCRIPTS_DIR__/hqa-full-9h-freshness.sh` | `17 */2 * * *` |
| Weekly review | `__HERMES_SCRIPTS_DIR__/hqa-full-9h-weekly.sh` | `0,10 9 * * 0` |
| Notification drain | `__HERMES_SCRIPTS_DIR__/hqa-full-9h-notification-drain.sh` | `7,22,37,52 * * * *` |

Hermes cron registers them with `--no-agent --deliver local` and deliberately
omits `--workdir`; each wrapper changes to the repository itself, while omitting
workdir keeps long legacy collection jobs from serially blocking full 9H.
The second daily/weekly minute is an idempotent retry of the same logical slot;
drain is offset so it does not collide with either source job's start minute.
Each drain processes at most five remote records, bounding its send portion to
75 seconds even when every remote attempt reaches the timeout.

`daily_close` consumes the latest existing scan without launching one, writes
portfolio risk, performs bounded prediction reconciliation, reads platform
coverage only for source-established eligible opportunities, reconciles missed
states, and rebuilds the feed. `freshness` and `weekly` read local receipts and
folded ledgers. `notification_drain` handles only durable outbox records.

The default target is `local`: one private idempotent receipt is written and no
external message is sent. A configured `discord:<channel>` uses bounded async
delivery. Known failures retain a local fallback; ambiguous timeout/crash state
is `delivery_unknown` and is never automatically retried. These jobs never
generate a strategy, run a backtest, mutate a paper account, create an
execution, send an order, or trade.

### Human-gated writes — approval required

Run from the repo dir. Each of these mutates state (creates a candidate,
writes an approval lock, runs a backtest, records a review), so Hermes will
show an approval prompt. That is intended; do not try to route them through the
read-only gate.

#### Natural-language paper reproduction (Agent v0.2 primary route)

When the user asks in natural language to reproduce or extract a factor from a
paper, use the active `/hermes` managed Session and advance exactly one visible
next step. Do not send the user to the old collection of disconnected commands.
The installed coordinator is:

`__HERMES_SCRIPTS_DIR__/hqa-paper-research.sh <operation>`

It reads exactly one strict JSON object from stdin. The command is a write path,
so every invocation remains subject to the normal Hermes approval prompt. Never
route it through `hqa-quant-readonly.sh`. The JSON is metadata-only: pass
content-addressed payload/result/provider references and digests, never the
paper body, prompt, source bytes, API credentials, or a human note other than
the explicit plan-confirmation note.

Use only IDs that the current workspace turn or the immediately preceding exact
receipt supplied. Never invent, list-and-substitute, or silently refresh an ID.
In particular:

- The Hermes API server injects four concurrency-safe selectors into this Run:
  `HERMES_PLATFORM_COMMAND_ID`, `HERMES_PLATFORM_SESSION_ID`,
  `HERMES_PLATFORM_RUN_ID`, and
  `HERMES_PLATFORM_MANAGED_SESSION_ID`. The wrapper fills absent
  `command_id`, `platform_session_id`, `hermes_run_id`, and
  `hermes_session_id` from them; if JSON supplies one, it must match exactly.
  Missing or mismatched env fails closed. Never recover these values from
  prompt text or a dynamic system prompt. They are selectors, not
  authorization: HQA and Platform still revalidate the durable authorities.
- `workspace_id` and `platform_session_id` come from the active ready
  `web_managed_session`; the HQA task binds them as
  `workspace:<workspace_id>` and `session:<platform_session_id>`.
- `command_id`, `hermes_run_id`, `hqa_run_ref`, and provider/result references
  come from the exact current Run receipts. A Gate may use a different Hermes
  Run from its parent, but Gate 1/2 stay on planning Attempt 1 and Gate 3 must
  use the new final-research Attempt 2.
- Reuse one caller-stable `operation_id` for an interrupted logical step.
  Reusing it with different input is a conflict. A registration timeout is
  `paper_research_platform_outcome_unknown`: inspect the same `gate_id`; do not
  create another Gate or rerun a provider/backtest.
- `dry_run=true`, `paper_trading=true`, `live_trading_enabled=false`, and
  `kill_switch=true` remain fixed. This workflow creates zero orders.

The only legal sequence is:

1. **Plan Run (Attempt 1).** Let Hermes analyze the named paper and create an
   explicit plan card. After the exact planning submission, Hermes Run and
   provider receipt exist, invoke `start-plan` with:
   `operation_id, workspace_id, platform_session_id, payload_ref,
   intent_expires_at, command_id, hermes_run_id, hqa_run_ref,
   provider_evidence_ref, plan_version, plan_digest`.
   The coordinator records
   `StartResearch → ObserveSubmission → ObserveRun →
   ObserveProviderEvidence → ProposePlan → RequestPlanConfirmation →
   CompleteAttempt`, then stops at `awaiting_plan_confirmation`.

2. **Independent plan confirmation.** Show the exact plan card/digest to the
   human. Only after a clear confirmation invoke `confirm-plan` with
   `operation_id, task_ref, expected_task_version, plan_version, plan_digest,
   confirmation_note`. Formula confirmation is not implied by plan
   confirmation.

3. **Gate 1 — exact formula/source.** Generate or stage the candidate source,
   show the formula, plain-language translation, universe, exact file and
   SHA-256 to the human, then invoke `open-gate1` with
   `operation_id, gate_id, workspace_id, platform_session_id, task_ref,
   expected_task_version, attempt_ref, command_id, hermes_run_id, hqa_gate_ref,
   source_file_ref, universe, reviewed_source_sha256`.
   `attempt_ref` must be planning Attempt 1. The coordinator only opens the
   browser challenge. The human's separate `ConfirmFormulaSource` action is
   what calls the existing `paper_gate_cli confirm-formula`; never click or
   imply that action automatically.

4. **Candidate proposal, then Gate 2.** After Gate 1 is confirmed, run the
   existing exact-source `factor_repro_cli propose` path to create the bound
   candidate. Show its exact source and manifest. Invoke `open-gate2` with
   `operation_id, gate_id, parent_gate_id, workspace_id, platform_session_id,
   task_ref, expected_task_version, attempt_ref, command_id, hermes_run_id,
   hqa_gate_ref, reviewed_source_sha256, gate1_confirmation_id, candidate_id,
   expected_digest, expected_status`. `expected_status` is literally
   `pending`; Gate 1 and Gate 2 must share Task, Attempt 1, source lineage and
   HQA Gate ref. The human's independent `ReviewCandidateCAS` action supplies
   the exact candidate/digest/status/note without a refetch.

5. **Futu final evidence, then Gate 3 (Attempt 2).** Only after Gate 2 is
   `reviewed`, run the approved candidate's one-shot backtest with
   `factor_repro_cli backtest ... --provider futu --final`. Do not substitute
   sample/local/Tiingo evidence. When its exact command, Hermes Run, provider
   receipt and content-addressed `backtest-…` result exist, invoke
   `open-gate3` with
   `operation_id, gate_id, parent_gate_id, workspace_id, platform_session_id,
   task_ref, expected_task_version, payload_ref, intent_expires_at, command_id,
   hermes_run_id, hqa_run_ref, provider_evidence_ref, result_ref, hqa_gate_ref,
   reviewed_source_sha256, gate1_confirmation_id, candidate_id,
   expected_digest, final_backtest_receipt_id, base_commit`.
   `result_ref` must be exactly
   `result:<final_backtest_receipt_id>`. The coordinator creates Attempt 2 and
   records submission/Run/provider/result facts before entering Gate 3.

6. **Independent promotion review.** The human's
   `PreparePromotionReview` browser action first resolves the exact domain Gate
   as `passed`, records `ObserveGate3`, and then asks
   `paper_gate_cli promote` to prepare the isolated review worktree. It never
   commits. Show the returned `promotion_id`, worktree, patch and manifest.

7. **Human Git review and commit, then completion.** The human personally
   reviews `git diff` and creates exactly one scoped commit in the named
   worktree. HQA must not type or run that commit for them. After they supply
   the exact 40-character commit, invoke `complete-after-human-commit` with
   `operation_id, gate_id, workspace_id, task_ref, expected_task_version,
   attempt_ref, hqa_run_ref, provider_evidence_ref, reviewed_commit`.
   The coordinator calls the read-only promotion-status seam, re-attests the
   exact candidate/digest/final receipt/base/patch and reviewed commit, then
   records `CompleteAttempt → CompleteTask`, reverse-audits the Workflow
   authority, creates one immutable content-addressed HQA completion receipt,
   and registers that exact terminal fact through
   `quant-system hermes paper-gate complete`. Until Platform returns the same
   receipt ref/digest with `status=completed`, the paper workflow is not
   complete and candidate evidence must remain fail-closed. If that registrar
   times out, treat it as `paper_research_platform_outcome_unknown` and replay
   this same logical operation/receipt; never create a replacement Task,
   Attempt, Gate, promotion, or backtest.

If the current workspace is missing any required exact binding, say which
receipt is missing and stop. Never create a fake Task/Attempt/Run/provider
receipt, never reuse the planning Attempt for Gate 3, never treat Gate 2 review
as Gate 3, and never call completion before the human commit is independently
re-attested.

#### Low-level Scene-B diagnostics and recovery

The commands below remain useful for inspecting or recovering one exact step.
They are not a substitute for the coordinator's two-Attempt workflow and must
not be presented as the normal natural-language user journey.

| Operation | Command |
|---|---|
| Propose factor (Scene-B Gate 1) | `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli propose --goal "<hypothesis>" --source-file <factor.py> --expected-source-digest <reviewed-source-sha256> --confirmation-note "<formula-and-translation-review>" --universe SPY,QQQ` |
| List candidates (Gate 2 inspect) | `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli list` |
| Detail one candidate | `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli detail --candidate-id <id>` |
| Approve translation (gate 2, human-only) | `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli approve --candidate-id <id> --expected-digest <sha256> --expected-status pending --note "<translation-review>"` |
| Backtest an approved factor | `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli backtest --candidate-id <id> --expected-digest <sha256> --symbol SPY --start 2020-01-01 --end 2024-12-31` |
| Prepare Gate 3 review workspace | `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli promote --candidate-id <id> --expected-digest <sha256> --final-backtest-receipt <backtest-id> --base-commit <40-char-HEAD>` |
| Review draft (post-mortem) | `cd __HQA_REPO_DIR__ && python3 -m hqa.review_cli draft --event "<what happened>" --kind note` |
| Review confirm | `cd __HQA_REPO_DIR__ && python3 -m hqa.review_cli confirm <id> --judgment "<call>" --basis "<why>"` |

Notes on the write path:
- `propose` is itself Gate 1: before any platform call it verifies the exact
  non-symlink source bytes against the human-supplied SHA-256, requires a
  non-empty confirmation note, stages content-addressed bytes, and writes a
  durable confirmation plus candidate binding under `data/_runtime/factor-gate1`.
- `list` is informational only and strips any platform approval command from its
  human-readable output. Run `detail --candidate-id <id>` to obtain one exact
  machine-JSON-backed review bundle. `propose` / `detail` print `candidate_id`,
  authoritative `manifest_digest`, `status=pending`, and a complete copyable
  HQA approve command only when the exact Gate 1 binding verifies. All four Gate 2 values
  (`--candidate-id`, `--expected-digest`, `--expected-status pending`, `--note`)
  come from one human-inspected verified item. The approve handler must
  **never refetch** digest or status; pass the printed values explicitly.
  The raw platform `agent list-candidates` leaf is intentionally absent from the
  Hermes read-only gate because it is generic diagnostic evidence, not Scene-B
  approval authority.
- `migration_required` items print only `observed_manifest_digest` as migration
  evidence with approval disabled. `corrupt` items print no digest/source.
- Do not auto-approve; a human inspects the generated factor before `approve`.
- `backtest` defaults to **`--provider futu`** (the only configured live data
  source on this machine). Pass `--provider tiingo` only when a Tiingo token is
  configured; otherwise the platform will fail. `sample`, local, and any
  environment-provided synthetic default are rejected before Gate 1/config or
  platform execution. Non-final runs reserve the last
  183 days as holdout unless `--final` is passed (D-21); a per-factor trial
  counter prints an overfit warning after 3 runs (D-21). The human supplies only
  the verified `candidate_id` and exact approved digest; the platform derives
  `factor_id` from that same snapshot and records all three values in the
  experiment config and receipt.
- A successful non-final backtest never authorizes Gate 3. A successful
  `--final` run writes a canonical content-addressed
  `final_backtest_receipt=backtest-…` bound to the exact candidate, manifest
  digest, factor, experiment/run, provider, symbols, full window and report.
  HQA safe-reads and hashes the persisted platform config, agent summary and
  report; requires the platform's unique per-invocation experiment namespace,
  rooted exactly below the configured `HQA_FACTOR_EXPERIMENT_OUTPUT_DIR`, exact
  single `run-001`, safety/provenance schema, and byte-for-byte generated report;
  then re-verifies those artifacts whenever the receipt is consumed.
  Promotion must consume that exact receipt ID and revalidates it both before
  and after preparing the review workspace.
- Promotion (Gate 3) is always a separate human decision through the HQA wrapper:
  `cd __HQA_REPO_DIR__ && python3 -m hqa.factor_repro_cli promote
  --candidate-id <id> --expected-digest <sha256>
  --final-backtest-receipt <backtest-id> --base-commit <40-char-HEAD>`
  revalidates the exact Gate 1 binding and successful final one-shot receipt, then prepares
  an isolated managed review worktree and prints
  exactly `{promotion_id, worktree, patch, manifest}`. Status/cleanup use
  `__HQA_PLATFORM_DIR__/ai-quant/bin/quant-system agent promotion-status
  --promotion-id <promotion_id>` and
  `__HQA_PLATFORM_DIR__/ai-quant/bin/quant-system agent cleanup-promotion
  --promotion-id <promotion_id>` only; destructive cleanup needs reviewed-commit
  evidence or explicit `--abandon`. HQA verifies the receipt manifest's exact
  candidate/digest/base/promotion binding, exact three-path allowlist, actual
  worktree bytes/modes/dirty set, and byte-identical Git patch before showing
  it. The immediate platform status must return the same manifest/patch/candidate/
  base/path provenance and must re-attest the still-uncommitted workspace.
  A timeout is an unknown outcome, never a failure proof: retain any safely
  parsed `promotion_id`, otherwise inspect the printed promotion root before a
  controlled retry.
  The system never auto-commits; the human
  `git diff` + commit completes Gate 3. The raw platform promotion command is a
  generic primitive and is not the supported Scene-B entry. New Hermes approval UI stays disabled
  until frontend/bridge gates land.

### `--json` output (D-22 status)

- **HQA authority-bearing write paths** are JSON-only: propose, approve,
  backtest candidate binding, and promote all fail closed unless exact machine
  receipts match their caller-supplied IDs/digests and expected state.
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
