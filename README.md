# Hermes-quant-agent

Hermes orchestration layer for the local `ai-quant-platform`. Phase 1a-4/9H is
complete; current D-32 work targets a real Agent v0.2 with complete `/hermes`
Web Chat while preserving read-only / proposal-only and never touching the trading
chain:

Start with [`docs/README.md`](docs/README.md): it separates the long-term HQA
roadmap, the current D-32 Agent v0.2 plan, and predecessor delivery records. The
`docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md` delivery record covers Slice 9A's paper-strategy
read model and explicit crash recovery, Slice 9B's unified paper snapshot,
Slice 9C's current-snapshot portfolio risk v1, Slice 9D's strict historical
price seam + risk v2, Slice 9E's prediction ledger, Slice 9F's proposal-only
market foresight, the mini 9H read-only Hermes artifact shelf, and Slice 9G's
auditable opportunity ledger. Full 9H adds the four-job
read-only automation loop, strict weekly/opportunity/freshness projections,
durable notification receipts, feed schema 1.1 and the visible `/hermes` cards.
D-31 has since delivered the official API GET-only session BFF (3A), PostgreSQL
command/event/outbox/run-link ledger with claim/lease/heartbeat primitives (3B),
and a deterministic connector notify/scan/expired-lease reconcile runtime (3C).
The runtime does not claim queued commands and remains reconcile-only: real Hermes
chat/provider Run submission and approval mutations
are still blocked. Slice 3C.1 has a code-accepted append-only Task/Attempt
authority, immutable content-addressed payloads, exact cross-authority bindings,
and reverse audit. Platform migration 006 has not been applied to the live database;
a later v0.2 review found its `UNIQUE(task_id)` incompatible with multi-Attempt
research. Because the current runner replays old SQL, the selected fix is to revise
the never-live 006 and redo its full evidence—not assume a later 007 can repair it—
before any live authorization.
This foundation is not yet an activated write path. The read-only Unified Results catalog and details are
delivered and locally accepted as 3E-A, while independent Hermes Run results and
full results cutover are not. Agent Studio has only a reversible page-scoped
redirect mechanism that defaults off; exact-bound audit parity, user cutover
approval, and retirement of all four legacy research pages remain open. The only
active implementation plan is [Agent v0.2 full `/hermes` Web Chat](docs/superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md);
the [Wave 3 plan](docs/superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md)
is a predecessor delivery record. Read both it and the accepted
[local Hermes integration decision](docs/design/2026-07-15-local-hermes-integration-decision.md)
for evidence before changing the bridge. Discord stays usable, but no temporary
web chat or fallback path is planned. The platform frontend plan is the Slice 0-8 delivery
record, not an executable queue. Platform Phase 15 is reference only.

- **Safety watchdog** (`hqa.doctor_watchdog`) — `[SILENT]`; JSON-first safety
  parse; splits `[INFRA]` (doctor/platform failure) vs `[SAFETY]` (baseline
  breach) so infra flaps no longer masquerade as kill-switch failures.
- **Pre-market digest** (`hqa.premarket_digest`) — daily summary of platform
  safety status, the latest collected Futu options-radar artifact, and AI HOT
  headlines with explicit degraded labels when sources are unavailable.
- **Review log** (`hqa.reviewlog`, `hqa.review_cli`) — append-only JSONL
  cognition store with Markdown rendering and human-filled confirmation fields.
- **Signal watchdog** (`hqa.signal_watchdog`) — consumes collected scan
  artifacts; loads `data/_runtime/signal_thresholds.json` (`min_score`, optional
  `min_iv_rank`) to exit permanent collect. Missing artifact sets
  `artifact_missing=true` in the log. Does not launch expensive Futu scans or
  `factor refresh-lab` by default (`--scan` / `--refresh-lab` opt-in).
- **Opportunity ledger** (`hqa.opportunities`, `hqa.opportunity_cli`) — folds
  structured `signal_records` into a locked append-only decision/action ledger.
  It validates exact platform signal/execution IDs through the pure
  `paper strategies observations` seam and records complete coverage watermarks
  before an eligible, expired action window can become `missed`. Current
  options-scan candidates remain `not_actionable` because the platform has no
  supported paper-options execution route. Use `hqa-opportunities.sh
  sync-signals|decide|record-action|sync-actions|reconcile|list`; symbol matching
  is forbidden and no command creates a signal, execution or trade.
- **Weekly review** (`hqa.weekly_review`) — emits a strict seven-day aggregate
  across safety, signals, reviews, prediction calibration and opportunity state;
  malformed sources degrade locally instead of breaking the whole projection.
- **Scene-B factor reproduction** (`hqa.factor_repro_cli`) — human-gated
  `propose|detail|approve|backtest|promote` flow covering the three human gates: factor
  formula confirm (exact reviewed source SHA-256 + non-empty note, persisted and
  bound to the resulting candidate manifest) → Gate 2 digest CAS approve
  (`--candidate-id` + `--expected-digest` + `--expected-status pending` +
  `--note`; never refetch and require the exact machine receipt) → successful
  content-addressed `--final` one-shot backtest receipt → Gate 3 HQA
  `promote --candidate-id --expected-digest --final-backtest-receipt --base-commit`
  Gate-1/backtest-revalidated isolated review worktree (human `git diff` + commit; never
  auto-commits). Raw platform review/promotion commands are generic primitives,
  not proof of the supported Scene-B provenance chain.
  The receipt accepts only Futu/Tiingo evidence and re-verifies the platform's
  persisted config, summary, exact generated report, unique experiment
  namespace rooted at the explicitly passed HQA artifact authority directory,
  and fixed one-run identity. Gate 3 additionally checks the actual
  three-file worktree, Git patch, and the platform's same-provenance status;
  timeouts remain an explicit unknown outcome with recovery evidence.
  Factor code is generated in the Hermes session, ingested via platform
  `agent propose-factor --source-file`, then backtested through the exact
  candidate ID + expected manifest digest path of
  `experiment run-config --provider futu` (futu
  is the only configured provider; tiingo is not set up). Candidates share the
  platform repo-anchored `data/agent_run/agent/candidates` root. Anti-overfit
  guardrails: per-factor trial counter (warns at 3rd run), 183-day holdout by
  default (`--final` runs the full window), and `hqa-gate` requiring
  `paper_days_completed >= 30` before broker-sim promotion.
- **Options radar summary** (`hqa.options_radar`) — daily structured summary
  for the latest collected Futu scan artifact; fresh Futu scans require
  explicit `--scan`.
- **Portfolio risk v2** (`hqa.portfolio_risk`) — consumes the unified paper
  snapshot once, writes one finite `logs/portfolio_risk.jsonl` artifact, and
  reports current long/short/gross/net exposure, gross-book concentration,
  account weights, valuation provenance, and repository degradation. Invested
  accounts also request strict Futu QFQ daily history through the platform
  `data prices` seam, globally align trading dates before returns, and report
  per-position beta versus SPY plus position-pair correlations. History failure
  degrades only that section and preserves current facts. It does not substitute
  sample/local/Tiingo/Longbridge data or calculate aggregate beta, VaR, FX,
  threshold verdicts, forecasts, or trading actions.
- **Prediction ledger** (`hqa.predictions`, `hqa.prediction_cli`) — records an
  explicitly stated US-equity direction forecast as a locked append-only JSONL
  event, anchors it to the latest completed Futu/QFQ session, and later scores
  the first actual session on or after the calendar horizon. Create and score
  are idempotent; concurrent IDs/scores use a local POSIX lock and CAS; torn or
  corrupt ledgers fail closed. The score is a declared-direction binary Brier,
  not a three-class probability score. There is no sample/local/Tiingo/
  Longbridge fallback and no account, strategy, backtest, or trading side
  effect. Use `hqa-prediction.sh create|list|reconcile`; full 9H now runs a
  bounded post-close reconcile but never creates predictions. Runtime data
  defaults to `predictions/`; override it with
  `HQA_PREDICTION_DIR` or `--prediction-dir` (use a temporary override for
  smoke tests rather than fabricating a formal prediction).
- **Market foresight** (`hqa.market_foresight`,
  `hqa.market_foresight_cli`) — validates a Hermes/user-authored US-equity
  thesis against the latest completed Futu/QFQ session and publishes an
  immutable proposal-only candidate. It never auto-creates a prediction or
  trading action. Use `hqa-market-foresight.sh propose|list`; changed intent
  under the same request ID fails closed.
- **Hermes artifact feed** (`hqa.hermes_artifacts`,
  `hqa.hermes_artifacts_cli`) — rebuilds or reads
  `artifacts/hermes-feed/manifest.v1.json`. Schema 1.1 adds weekly review,
  opportunity summary and per-job automation freshness to the original risk,
  prediction and market-foresight sources. The platform consumes it through the
  same read-only API; use `hqa-artifacts.sh refresh|show`.
- **Full 9H automation** (`hqa.research_automation`) — runs post-close,
  two-hour freshness, Sunday weekly and 15-minute notification-drain jobs through
  Hermes no-agent cron. Stable receipts, a non-blocking process lock and a
  private outbox make replays auditable. The default notification target is
  local; external delivery is not exercised by acceptance. No job generates a
  strategy, runs a backtest, mutates paper state, creates an execution or trades.

- **AI-HOT alerts** (`hqa.aihot_alerts`) — `[SILENT]` notable-news watchdog;
  prints only when score/category filters find something worth attention.

Slice 9G remains the decision/action fact source; full 9H only schedules its safe
read/reconcile interfaces and publishes aggregates. It adds no database table,
POST route, platform scheduler, execution path or trading permission.

Hermes-facing affordances (D-25): read-only platform queries run through
`scripts/hermes/hqa-quant-readonly.sh` (allowlist-gated; **no** full options
scan — those write snapshots and stay human-approved); `hqa-notify.sh` pushes
async completions to Discord with a local JSONL fallback; the `hqa-quant`
skill card gives Hermes artifact-first command templates and a >30s triage
convention. Machine-readable paper-account queries use the existing
`paper account-show --format json` command and the platform's unified snapshot
envelope; there is no second account command or JSON shape. After changing
wrappers/skill: `bash scripts/install.sh`. Historical price reads are allowed
only through the exact `data prices` leaf; `data ingest-*` remains refused.

Ops note (2026-07-09 audit): missing same-day scan meta surfaces as
`DEGRADED: no scan artifact for <date>` in premarket/options-radar digests
rather than silent empty options.

Logic lives in `hqa/` (Python 3.9, stdlib only). Hermes cron runs thin wrappers
copied into `~/.hermes/scripts/` by `scripts/install.sh`.

Tests: `./.venv/bin/pytest`

Install/update Hermes script wrappers:

```bash
bash scripts/install.sh
```

See `docs/README.md` first, then
`docs/design/2026-07-01-roadmap-phases-0b-4.md` for product decisions and
`docs/design/hermes_quant_agent_plan.md` for the original system design.
