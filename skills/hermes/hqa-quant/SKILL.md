---
name: hqa-quant
description: "HQA quant ops and paper/literature/factor research (论文、文献、因子与策略研究) from Hermes — verified web discovery, read-only market/signal/radar queries, local ledgers, human-gated research/account writes, artifact-first answers, and 30s async triage."
version: 1.18.5
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

#### Natural-language options research (Agent v0.2 Vertical A)

When the user asks in the active `/hermes` managed Session for one specific
put-option observation, invoke:

`__HERMES_SCRIPTS_DIR__/hqa-options-research.sh`

Send exactly one JSON object on stdin:
`{ticker, expiry, strike, goal_note}`. `expiry` is `YYYY-MM-DD`; `strike` is a
positive number. If ticker, expiry, or strike is absent, ask the user for the
missing value instead of guessing it, scanning a chain, or substituting a
different contract. Never call the browser-only `vertical.options_a.bind`
endpoint or type a provider receipt yourself.

This wrapper is the sole natural-language Vertical-A ingress. The Platform
derives a caller-stable action ID from the exact current
`HERMES_PLATFORM_COMMAND_ID`, `HERMES_PLATFORM_SESSION_ID`,
`HERMES_PLATFORM_RUN_ID`, `HERMES_PLATFORM_MANAGED_SESSION_ID`, and normalized
request. It persists the request before provider I/O, binds the exact delivered
conversation Run, grants one Futu read-only call, returns a typed options result,
and seals any uncertain post-claim outcome without automatic replay. A retry of
the same Run and body returns the same completed result. It must never create an
order: `kill_switch=true`, `live_trading_enabled=false`, pending-order processing
OFF, and canonical begin/end zero-order evidence remain mandatory.

The success receipt has contract `agent-v0.2-options-research/v1` and includes
`domain_request_id`, `result_id`, `provider_receipt_id`, `capture_digest`,
`ingress_command_id`, exact Session/Run refs, and `status:"completed"`. Preserve
those references; do not claim success from prose alone.

#### Natural-language paper reproduction (Agent v0.2 primary route)

Requests about a paper, literature review, alpha/factor/strategy extraction, or
portfolio-construction research trigger this skill. Before any workflow write,
perform this research intake in order:

1. First call the actual `web_search` tool. Verify the canonical title plus a
   DOI or arXiv identifier against a primary publisher, DOI, or arXiv source;
   never trust only the user's spelling, a secondary search snippet, or model
   memory. An exact unique primary-source match is verified without another
   confirmation round. If results identify more than one plausible paper, show
   the ambiguity and ask the user rather than selecting one. If search fails,
   returns no usable result, or finds no primary source, report the intake as
   `BLOCKED` and stop.
   A terminal command (`curl`, `urllib`, or an arXiv API), browser navigation,
   provider-internal browsing, or a remembered identifier never satisfies this
   step. The current turn must contain an actual `web_search` result with
   `success=true` and a unique primary-source hit. If the tool is absent, not
   called, returns an error envelope, or yields no unique primary source, report
   `BLOCKED` and stop; do not replace it with terminal or browser access.
2. Then call `web_extract` on the verified primary abstract/landing page and,
   when needed, its PDF or full text. Source the paper's claims from those
   extracted bytes, not from search-result prose or a remembered description.
   A factor/strategy extraction or backtest request requires successfully
   extracted usable full-text bytes; an error envelope, empty body, or
   abstract-only response is insufficient. Try the verified primary PDF and
   then the isolated local fallback below. If usable full text still cannot be
   obtained, report `BLOCKED` and stop before making a reproducibility decision.
3. Make the reproducibility decision from the extracted source. A directly
   actionable factor or strategy needs enough formula or deterministic rules,
   input/data definitions, eligibility/universe rules, rebalance/holding logic,
   and parameter values to implement without invention.
   - If that contract is missing, honestly summarize what the paper does and
     stop. Do not call `prepare-intent`, create `research_start`, or run any
     backtest. Architecture, training, optimizer, or benchmark claims are not
     permission to invent a hand-written factor.
   - If it is actionable, ask the user for an explicit non-empty ordered
     `universe` before `prepare-intent`. Never guess, infer, sort, deduplicate,
     or substitute that universe from paper benchmarks, examples, mentioned
     assets, or defaults.

Before any final answer, self-check the current turn's tool history. If a
successful `web_search` did not precede `web_extract` or the isolated full-text
fallback, the only valid paper-intake conclusion is `BLOCKED`; do not present a
reproducibility verdict, factor, backtest, or strategy summary as validated.

Prefer `web_extract` over adding a local PDF parser. Never install PDF
dependencies into system/global Python, the user site, any project environment,
or any existing Hermes, HQA, or Platform runtime/venv; in particular, never run
`uv pip install --system`. If local parsing is truly necessary, use only a
task-scoped temporary directory with its own isolated `.venv`, invoke that
environment's interpreter explicitly, and do not expose it through
Hermes/HQA/Platform environment variables.

Only after this intake passes, the title has one exact verified primary-source
match (or the user resolved a real ambiguity), and the user supplied the ordered
universe may the managed research workflow below begin.

When the user asks in natural language to reproduce or extract a factor from a
paper, use the active `/hermes` managed Session and advance exactly one visible
next step. Do not send the user to the old collection of disconnected commands.
The installed coordinator is:

`__HERMES_SCRIPTS_DIR__/hqa-paper-research.sh <operation>`

It reads exactly one strict JSON object from stdin. The command is a write path,
so every invocation remains subject to the normal Hermes approval prompt. Never
route it through `hqa-quant-readonly.sh`. Each `prepare-intent` call is the sole
exception to the otherwise metadata-only JSON schema: its stdin object carries
the exact current user message in `prompt`, the exact `paper_title`, and the
exact ordered `universe` symbol array. Those values must travel only through
stdin and process memory into the encrypted IntentPayloadStore; never argv, environment,
temporary files, or logs. The receipt exposes only
`research_claim_digest`, not `prompt` or `paper_title`. Every non-prepare
operation is metadata-only: pass content-addressed payload/result/provider
references and digests, never the paper body, prompt, paper title, source bytes,
ordered universe, API credentials, or a human note other than the explicit
plan-confirmation note.

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
- After a browser Gate action, resolve only that exact parent Gate through the
  fixed read-only continuation port:
  `__HERMES_SCRIPTS_DIR__/hqa-quant-readonly.sh hermes paper-gate show --gate-id <exact-parent-gate-id> --workspace-id <exact-workspace-id> --platform-session-id <exact-platform-session-id>`.
  The wrapper requires exactly those nine argv, validates all three selectors,
  and encodes the strict
  `{"gate_id":"...","platform_session_id":"...","workspace_id":"..."}`
  JSON stdin internally. It loads only the database connection required for
  this exact read from the fixed Platform backend runtime env, without sourcing
  or evaluating that file, and always forces startup migration OFF.
  The `gate_id` must come from the current workspace turn or its immediately
  preceding exact receipt; the workspace and Platform Session selectors must
  be the current managed-session values already bound into the HQA Task. Never
  use `paper-gate list`, `register`, or another operation as a substitute.
  Require `ok=true`, `operation=show`, the same
  `gate_id`, `workspace_id`, `platform_session_id`, `task_ref`, and the expected
  post-action status. Preserve only the returned post-action `task_version` and
  `gate1_confirmation_id` needed by the next step. If either is missing, the
  Session binding differs, or the status is `outcome_unknown`, stop and
  reconcile the same action identity; never guess or silently refresh.
- The first operation for each natural-language research body is
  `prepare-intent`. Send exactly
  `{workspace_id, kind, prompt, paper_title, universe}` on stdin, where
  `prompt` is the verbatim current user message, `paper_title` is the exact
  human-confirmed title, `universe` is a non-empty ordered JSON array of exact
  uppercase symbols, and `kind` is exactly `research_start` or
  `research_continue`. Symbol order is part of the claim: never sort, dedupe,
  add, remove, or substitute a symbol. If either the exact title or ordered
  universe is unavailable, ask the human and stop before preparing the intent;
  never infer either from a digest or silently choose a default. Omit owner,
  TTL, provider policy and client identity:
  HQA derives the owner from WorkflowAuthority, fixes TTL to 7 days, derives
  the idempotency identity from the current command, binds both current
  Session selectors into the policy reference, and read-attests the current
  command/Run/workspace/session before writing. Preserve only the returned
  metadata (`payload_ref`, `research_claim_digest`, other digests, scope,
  TTL/status); stdout never contains `prompt` or `paper_title`. The same current
  command with a different body, kind, title, or ordered universe conflicts.
  If exact current user bytes are unavailable, stop rather than paraphrasing.
- `prepare-intent` writes only the existing encrypted IntentPayloadStore. It
  does not create a Task/Attempt, register a Gate, run a provider/backtest, or
  call the old Platform `StartResearch` / `ContinueResearch` path. Never use
  `hqa-research-task`, `hqa.intent_workflow`, or another put/start/continue
  entry as a parallel natural-language control plane.
- The four injected selectors always identify the **current coordinator
  invocation**, never the earlier Run whose output is being recorded. For
  `start-plan` and `open-gate3`, finish the planning/final-research Run first,
  then invoke the coordinator in the **next managed Hermes turn**. Pass that
  earlier succeeded Run only as `subject_command_id` and
  `subject_hermes_run_id`. Current and subject command/Run IDs must both be
  different. Platform independently attests both bindings from PostgreSQL and
  the official Hermes GET-only status/events/actual-policy/output surfaces;
  HQA derives `hqa_run_ref`, `provider_evidence_ref`, and the attestation refs
  from that response. Never self-report those derived references in JSON.
- A later workflow action may consume only the `payload_ref` returned by the
  preceding `prepare-intent` in this same managed Session. It must still be
  active, unexpired, exact-owner/workspace/session scoped, and bound to the
  current managed-session policy reference. `start-plan` requires kind
  `research_start`; `open-gate3` requires kind `research_continue`. Pass its
  `payload_ref` and the exact `research_claim_digest` from that
  `prepare-intent` receipt. The coordinator reads authoritative owner/workspace/
  Session/TTL metadata, rejects another consumer before Workflow mutation,
  decrypts and re-hashes the sealed claim in process, and binds both payload and
  claim digest to Attempt 1. Attempt 2 inherits that immutable Task claim when
  it is created; a claimless Task can never acquire a claim on a later Attempt.
  Never supply an expiry timestamp as a substitute for that authority, and
  never reconstruct a claim from its digest.
- Gate 1/2 stay on planning Attempt 1 and Gate 3 creates final-research
  Attempt 2. The Futu receipt and its config/summary/report references and
  digests are read from the canonical final receipt; they are never typed into
  the coordinator request.
- Preserve the coordinator's returned evidence, not guessed equivalents:
  `subject_run_attestation_ref`, `subject_run_attestation_digest`,
  `hqa_run_ref`, and `provider_evidence_ref`. Gate 3 and terminal completion
  additionally bind `final_backtest_provider`,
  `final_backtest_receipt_digest`, and the exact config/summary/report
  reference-and-digest pairs. Terminal
  evidence also repeats the confirmed `plan_version`/`plan_digest` and subject
  command/Run IDs, so a later reader can verify the whole lineage.
- Hermes must omit `operation_id`, every new `gate_id`, every
  `hqa_gate_ref`, and the `start-plan` `plan_digest`. The coordinator derives
  them content-addressedly from authoritative stable inputs and returns every
  effective ID/digest in its receipt. A new coordinator command/Run replay
  therefore derives the same controls without model memory or invention.
  Supplying `operation_id`, a new `gate_id`, or `hqa_gate_ref` is a
  closed-schema error. Carry `parent_gate_id` and the terminal Gate 3
  `gate_id` only from the immediately preceding receipt/show response.
- Gate 1 and Gate 2 share the returned formula
  `hqa_gate_lineage_ref == hqa_gate_ref`. Gate 3 keeps that same
  `hqa_gate_lineage_ref` but receives the deterministic
  `<lineage-ref>-g3` domain `hqa_gate_ref`, because WorkflowAuthority binds one
  gate ref to exactly one Task/Attempt/role. Never substitute one for the
  other.
- A registration timeout is `paper_research_platform_outcome_unknown`: replay
  the same logical request with derived controls and inspect the exact returned
  or previously preserved `gate_id`; do not create another Gate or rerun a
  provider/backtest.
- `dry_run=true`, `paper_trading=true`, `live_trading_enabled=false`, and
  `kill_switch=true` remain fixed. This workflow creates zero orders.

The only legal sequence is:

1. **Prepare the initial intent, then run the plan.** In the current managed
   Hermes turn, invoke `prepare-intent` first with
   `{workspace_id, kind:"research_start", prompt:<exact current user body>,
   paper_title:<exact title>, universe:[<ordered symbols>]}`. Preserve its
   returned `payload_ref` and `research_claim_digest`; do not print or persist
   the prompt or title elsewhere. Do not begin until the ordered research
   universe is explicit. Then let Hermes analyze the named paper and create an
   explicit plan card. Preserve the succeeded planning command/Run IDs and
   exact output digest.

2. **Next-turn capture (Attempt 1).** In the **next managed Hermes turn**,
   invoke `start-plan`; its injected current command/Run prove the coordinator
   invocation while the preserved IDs identify the subject:
   `workspace_id, platform_session_id, payload_ref, subject_command_id,
   subject_hermes_run_id, plan_version, research_claim_digest`. Omit
   `operation_id` and `plan_digest`: the coordinator derives the former from
   stable bindings and the latter only from the independently attested subject
   output. A legacy supplied `plan_digest` is accepted only when it equals that
   attestation. `payload_ref` must name an active `research_start` payload.
   The coordinator records
   `StartResearch → ObserveSubmission → ObserveRun →
   ObserveProviderEvidence → ProposePlan → RequestPlanConfirmation →
   CompleteAttempt`, then stops at `awaiting_plan_confirmation`.

3. **Independent plan confirmation.** Show the exact plan card/digest to the
   human. Only after a clear confirmation invoke `confirm-plan` with
   `task_ref, expected_task_version, plan_version, plan_digest,
   confirmation_note`, carrying the digest from the `start-plan` receipt and
   omitting `operation_id`. Formula confirmation is not implied by plan
   confirmation.

4. **Gate 1 — exact formula/source.** Generate the candidate source in memory,
   then pipe its exact raw Python bytes only on stdin (no argv/env/log copy) to
   `__HERMES_SCRIPTS_DIR__/hqa-paper-research.sh stage-source`; pass no other
   arguments. The wrapper alone execs its installed internal
   `hqa-paper-source-stage.py` with no arguments under isolated Python; never
   invoke that internal launcher directly.
   Require its unique strict JSON receipt to contain exactly
   `{source_file_ref,reviewed_source_sha256}`. The helper alone stages mode-0600
   bytes beneath the configured ignored `HQA_FACTOR_GATE1_DIR`
   (`__HQA_REPO_DIR__/data/_runtime/factor-gate1/sources`); never write source
   to a tracked repository path, `/tmp`, or another caller-chosen location.
   Show the formula, plain-language translation, universe, and the exact helper
   receipt to the human, then invoke `open-gate1` with
   `workspace_id, platform_session_id, task_ref, expected_task_version,
   attempt_ref, source_file_ref, reviewed_source_sha256,
   research_claim_digest`, omitting `operation_id`, `gate_id`, and
   `hqa_gate_ref` and consuming only the helper-returned source fields.
   A claimed workflow must not send `paper_title` or `universe` again. HQA
   decrypts the Attempt 1 payload only in process, re-hashes the sealed claim,
   and writes only `research-claim:sha256:<research_claim_digest>` to the
   Platform Gate's legacy `universe` slot. The Gate registration also carries
   the exact claim and Attempt 1 payload digests. Reordered, missing, extra, or
   otherwise changed symbols produce a different digest at `prepare-intent`;
   `open-gate1` accepts only the digest already bound to the Task. A legacy
   claimless v1 workflow remains compatible and instead supplies one bounded
   printable `universe` string.
   `attempt_ref` must be planning Attempt 1. The coordinator only opens the
   browser challenge. The human's separate `ConfirmFormulaSource` action is
   what calls the existing `paper_gate_cli confirm-formula`; never click or
   imply that action automatically.

5. **Candidate proposal, then Gate 2.** After Gate 1 is confirmed, use the
   fixed `hermes paper-gate show` command above for that exact parent Gate and
   preserve its `gate1_confirmation_id` plus post-action `task_version`; do not
   ask the human to copy either value and do not recreate their confirmation
   from a remembered note. Reuse that content-addressed decision with:
   `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh propose --gate1-confirmation-id
   <gate1_confirmation_id> --task-ref <task_ref>
   --source-file <same-source-file>
   --expected-source-digest <reviewed_source_sha256>`.
   This mode derives the original durable `task_ref` goal, claim marker and
   staged bytes from Gate 1 itself, requires the public `task_ref` from that same
   projection, rejects a cross-Task confirmation plus `--goal`,
   `--confirmation-note` and `--universe` substitution, and re-hashes the
   supplied source before any Platform call. Show the resulting exact source
   and manifest. Invoke
   `open-gate2` with
   `parent_gate_id, workspace_id, platform_session_id, task_ref,
   expected_task_version, attempt_ref, reviewed_source_sha256,
   gate1_confirmation_id, candidate_id, expected_digest, expected_status`,
   omitting all derived IDs. `expected_status` is literally
   `pending`; Gate 1 and Gate 2 must share Task, Attempt 1, source lineage and
   HQA Gate ref. The human's independent `ReviewCandidateCAS` action supplies
   the exact candidate/digest/status/note without a refetch.

6. **Prepare continuation, collect Futu final evidence, then next-turn Gate 3
   (Attempt 2).** Resolve that exact Gate 2 with the same fixed show command.
   Only after it returns `reviewed` with the same confirmation ID and exact
   post-action Task version, begin the exact
   final-research managed turn with `prepare-intent` using
   `{workspace_id, kind:"research_continue", prompt:<exact current user body>,
   paper_title:<same exact title>, universe:[<same ordered symbols>]}`.
   Require its returned `research_claim_digest` to equal Attempt 1 and preserve
   that new `payload_ref`. Then run the approved candidate's one-shot
   backtest with `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh backtest ... --provider futu --final`. Do not
   substitute sample/local/Tiingo evidence. Preserve the succeeded
   final-research command/Run IDs and content-addressed `backtest-…` result. In
   the **next managed Hermes turn**, invoke `open-gate3` with
   `parent_gate_id, workspace_id, platform_session_id, task_ref,
   expected_task_version, payload_ref, subject_command_id,
   subject_hermes_run_id, result_ref,
   reviewed_source_sha256, gate1_confirmation_id, candidate_id, expected_digest,
   final_backtest_receipt_id, base_commit, research_claim_digest`, omitting
   `operation_id`, `gate_id`, and `hqa_gate_ref`.
   `payload_ref` must name an active `research_continue` payload. Platform
   independently derives the subject Run/provider evidence, and HQA
   read-verifies that the canonical receipt says `provider=futu` and binds the
   exact candidate/digest plus receipt/config/summary/report digests.
   `result_ref` must be exactly
   `result:<final_backtest_receipt_id>`. The coordinator creates Attempt 2 and
   records submission/Run/provider/result facts before entering Gate 3. The
   Gate 2 registration repeats the exact claim/start digests from Gate 1; Gate
   3 repeats both and adds the exact continuation payload digest. Platform
   rejects any break in that lineage.

7. **Independent promotion review.** The human's
   `PreparePromotionReview` browser action first resolves the exact domain Gate
   as `passed`, records `ObserveGate3`, and then asks
   `paper_gate_cli promote` to prepare the isolated review worktree. It never
   commits. Show the returned `promotion_id`, worktree, patch and manifest.

8. **Human Git review and commit, then completion.** Resolve the exact prepared
   Gate 3 with the same fixed show command and preserve its post-action Task
   version. The human personally
   reviews `git diff` and creates exactly one scoped commit in the named
   worktree. HQA must not type or run that commit for them. After they supply
   the exact 40-character commit, invoke `complete-after-human-commit` with
   `gate_id, workspace_id, task_ref, expected_task_version, attempt_ref,
   reviewed_commit, research_claim_digest`, carrying `gate_id` only from the
   exact prepared Gate 3 receipt and omitting `operation_id`.
   The coordinator calls the read-only promotion-status seam, re-attests the
   exact candidate/digest/final receipt/base/patch and reviewed commit, then
   records `CompleteAttempt → CompleteTask`, reverse-audits the Workflow
   authority, creates one immutable content-addressed HQA completion receipt,
   binds it to the exact claim plus both start/continue payload digests,
   and registers that exact terminal fact through
   `quant-system hermes paper-gate complete`. HQA requires the closed Platform
   completion schema and exact evidence values; unknown response fields are
   rejected and never echoed. Until Platform returns the same receipt
   ref/digest with `status=completed`, the paper workflow is not complete and
   candidate evidence must remain fail-closed. If that registrar
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
| Propose factor from an already confirmed Browser Gate 1 | `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh propose --gate1-confirmation-id <gate1-id> --task-ref <task-ref> --source-file <factor.py> --expected-source-digest <reviewed-source-sha256>` |
| Create a standalone low-level Gate 1 and propose (diagnostic only) | `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh propose --goal "<hypothesis>" --source-file <factor.py> --expected-source-digest <reviewed-source-sha256> --confirmation-note "<formula-and-translation-review>" --universe SPY,QQQ` |
| List candidates (Gate 2 inspect) | `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh list` |
| Detail one candidate | `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh detail --candidate-id <id>` |
| Approve translation (gate 2, human-only) | `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh approve --candidate-id <id> --expected-digest <sha256> --expected-status pending --note "<translation-review>"` |
| Backtest an approved factor | `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh backtest --candidate-id <id> --expected-digest <sha256> --symbol SPY --start 2020-01-01 --end 2024-12-31` |
| Prepare Gate 3 review workspace | `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh promote --candidate-id <id> --expected-digest <sha256> --final-backtest-receipt <backtest-id> --base-commit <40-char-HEAD>` |
| Review draft (post-mortem) | `cd __HQA_REPO_DIR__ && python3 -m hqa.review_cli draft --event "<what happened>" --kind note` |
| Review confirm | `cd __HQA_REPO_DIR__ && python3 -m hqa.review_cli confirm <id> --judgment "<call>" --basis "<why>"` |

Notes on the write path:
- Standalone diagnostic `propose` can create Gate 1: before any Platform call
  it verifies the exact non-symlink source bytes against the human-supplied
  SHA-256, requires a non-empty confirmation note, stages content-addressed
  bytes, and writes a durable confirmation plus candidate binding under
  `data/_runtime/factor-gate1`. The normal integrated Browser flow instead
  passes `--gate1-confirmation-id` and the same projection's `--task-ref`; it
  re-attests and reuses the existing confirmation, rejects cross-Task reuse
  before Platform proposal, and never manufactures a second human decision.
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
  `__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh promote
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
