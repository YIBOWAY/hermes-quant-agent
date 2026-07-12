# Slice 9G — Signal / decision / action ledger and missed-opportunity assessment

> **Status (2026-07-12): COMPLETE.** This is the delivered bite-sized
> expansion of Slice 9G from `2026-07-10-phase-1a-4-v2.md`. It replaces the
> symbol-matching sketch in the superseded 2026-07-07 plan. Full 9H cron, weekly
> projection, notifications and freshness monitoring were subsequently completed
> and accepted under `2026-07-12-full-9h-automation-notifications.md`. This is a
> predecessor record, not a current queue pointer.

## Outcome

Build an auditable, proposal-only opportunity loop:

```text
structured market signal
  -> stable signal identity
  -> explicit human decision and action eligibility
  -> explicit causal action evidence
  -> complete action-coverage watermark
  -> action-window missed candidate
```

`missed` in this slice means only that an explicitly actionable signal passed
its declared action deadline without a causally linked action. It does **not**
mean that the market later moved profitably or that a trade should have been
placed.

## Source-fact verdict

The old `date + symbol + strategy` identity and same-symbol execution matching
are rejected:

- The real 2026-07-10 options artifact has 59 contracts at score >= 150, but
  the old key collapses them to 29 rows. One ticker and strategy can have many
  expiries and strikes.
- The watchdog can consume the same artifact repeatedly, so `observed_at`
  cannot be part of source identity.
- Scene-A rows are option-contract `covered_call` / `sell_put` candidates.
  Platform resident sleeves produce equity `StrategySignal` and
  `StrategyExecutionPlan` records. A matching underlying symbol is not a
  causal link.
- Platform `ops-status` currently exposes aggregate counts only. Counts cannot
  prove which signal was considered or acted upon.
- The live platform currently has one running allocated sleeve and no persisted
  strategy signals or executions. The first real 9G smoke must therefore be
  honestly empty/unknown, never fabricated for display.

## Safety boundary

- Read-only or proposal-only only. No signal generation, backtest, execution
  creation, pending execution processing, rebalance, broker order or trade.
- `decide` records a human intent; it is not execution authorization.
- `record-action` records evidence about an already-existing external action;
  it never creates that action.
- Platform observations never open the account repository, provider, mutation
  lock or recovery path and never rename a corrupt journal.
- Do not add the broad prefix `paper strategies` to the Hermes allowlist. It
  would expose mutating subcommands.
- The opportunity ledger is canonical for 9G. Run logs, review drafts, the
  Hermes shelf and notifications are projections, not fact sources.

## Domain contract

### Stable signal identity

The watchdog keeps its human-readable `signals` list and adds
`signal_records`. Each record carries:

- `signal_id = sig_<24 hex>`;
- `source.kind=options_scan`, source date and a canonical source-row digest;
- option contract symbol, underlying, strategy, score and IV rank;
- a canonical threshold-policy digest;
- `eligibility.status=unknown|not_actionable|eligible`, route, reason and an
  optional explicit UTC action deadline.

Identity hashes schema version, source kind/date, the exact canonical source
row, option-contract symbol and threshold-policy digest. Re-reading the same
artifact is idempotent; distinct contracts never collide. Old text-only logs
are never parsed back into structured signals.

The current options-radar rows have no supported resident paper-options route,
so automatic ingestion records them as `not_actionable` (or `unknown` when
required identity facts are absent), not as missed.

### Opportunity event ledger

`OpportunityTracker` is the single deep module. Its public surface is:

```python
tracker.record(command)
tracker.reconcile_due(as_of=None, limit=50, cursor=None)
tracker.list(status=None, since=None, limit=100, cursor=None)
```

It hides strict schema validation, state folding, idempotency, process locking,
atomic append and corruption handling. The versioned append-only event types
are:

1. `signal_observed` — immutable structured signal and source digest.
2. `decision_recorded` — explicit `act|decline|defer`, actor, reason and
   request identity. A decision records intent only: it cannot create or
   upgrade action eligibility, route or deadline.
3. `action_observed` — explicit opportunity `signal_id` plus a durable external
   platform signal/execution identity and its literal status. Symbol matching
   is forbidden.
4. `action_coverage_observed` — complete/untruncated observation snapshot and
   the UTC time through which action evidence is covered.
5. `missed_assessed` — one immutable assessment written by reconciliation only
   after every prerequisite is true.

Every event has a schema version, stable event ID, request ID, recorded time,
payload SHA-256 and strict finite JSON payload. Same request/same intent is
idempotent; same request/different intent fails closed. Duplicate keys,
non-finite numbers, invalid UTF-8, torn events, orphan references, identity
reuse with changed payload, backwards action transitions and one external
action linked to two signals make the ledger corrupt and block writes.

### State reducer

The reducer applies these rules in order:

1. `not_actionable` resolves to `not_actionable` and can never be missed.
2. Missing eligibility, route or deadline resolves to `unknown`.
3. A causally linked action at or before the deadline resolves to `acted` for
   pending/partial/filled or `action_failed` for blocked/failed/cancelled/
   missed-window/skipped. A failed action is not inaction.
4. A pre-deadline `decline` resolves to `declined`.
5. At or before the deadline the state remains `open` or `deferred`; equality
   is not late.
6. After the deadline, incomplete/truncated coverage or a coverage watermark
   before the deadline resolves to `expired_coverage_unknown`.
7. Only complete coverage through the deadline, with no timely action and no
   decline, permits `missed_assessed`. Its reason is `no_decision`,
   `act_without_action` or `defer_expired`.
8. A late/backfilled action remains visible but never erases an already-recorded
   action-window miss.

All timestamps are canonical UTC `Z`. Market source date is a separate fact;
the implementation must not derive it from a Shanghai-local timestamp.

## Platform read seam

Add one bounded CLI-only reader:

```text
quant-system paper strategies observations \
  --from-date YYYY-MM-DD \
  --to-date YYYY-MM-DD \
  --signal-id signal-... \
  --limit 200 \
  --format json
```

Filters are optional, `limit` is bounded, and ordering is deterministic by
`signal_date`, `generated_at`, `signal_id`. The JSON envelope contains:

- `schema_version`, `read_status=available|empty|degraded`;
- requested bounds, returned count and `truncated`;
- pure ops-quality counters for pending sleeves/journals, corrupt journals and
  recovery-required executions;
- observations with sleeve identity/mode/status, full stable signal identity
  and all causally linked execution identities/statuses.

The reader returns facts only and never computes `missed`. Duplicate signal
IDs, multiple executions for one signal, corrupt JSON or an inconsistent
cross-file relationship fail closed as degraded/error evidence. HQA accepts a
coverage event only from an available/empty, untruncated result that exhausts
the requested window.

This slice does not add an HTTP endpoint, frontend component, database table or
migration. Strategy-sleeve facts remain in their current file-backed store;
the new seam is an additive read model.

## Public HQA CLI

`python -m hqa.opportunity_cli` and installed `hqa-opportunities.sh` expose:

- `sync-signals --date YYYY-MM-DD` — consume the existing scan artifact and
  threshold policy; never run a fresh scan.
- `decide --signal-id ... --decision act|decline|defer --actor ... --reason ...
  --request-id ... [--decided-at ... --revisit-at ...]`.
- `record-action --signal-id ... --platform-signal-id ...
  --platform-execution-id ... --actor ... [--limit ...]` — validate both exact
  platform IDs through the pure observation seam; the request identity is
  derived from the validated external identity before evidence is recorded.
- `sync-actions --signal-id ... --covered-through ...
  [--from-date ... --to-date ... --limit ...]` — import a complete platform
  observation snapshot and its explicit coverage watermark without guessing
  links.
- `reconcile [--as-of ... --limit ... --cursor ...]`.
- `list [--status ... --since ... --limit ... --cursor ...]`.

All commands emit exactly one strict JSON document. Invalid requests return a
stable code and non-zero exit. Ledger corruption and incomplete platform
coverage fail closed. A future source adapter must establish an eligible route
and canonical UTC deadline in `signal_observed`; current options-scan rows stay
`not_actionable` because no supported paper-options route exists.

## TDD tracer bullets

### A. Structured signal identity

1. Two same-ticker/same-strategy contracts with different contract symbols get
   different IDs.
2. The same artifact and policy repeated many times produce one state per
   contract.
3. Isolated fixtures prove same-ticker contract rows cannot collide; a real
   2026-07-10 artifact smoke proves 59 qualifying rows produce 59 IDs, not 29.
4. Missing contract/source identity and old text-only logs remain unknown; no
   string parsing fallback exists.

### B. Ledger integrity and concurrency

1. Same request/same payload is idempotent; changed intent conflicts.
2. Concurrent identical/different commands preserve unique events and IDs.
3. Strict JSON, UTF-8, finite values, payload hash and transition corruption
   checks all fail closed before append.
4. External platform reads happen outside the ledger lock; the lock protects
   only recheck/fold/append.

### C. Decisions, actions and coverage

1. `act`, `decline`, `defer` transitions are explicit and auditable.
2. Same-symbol platform activity without explicit `signal_id` linkage is not
   an action.
3. One external execution cannot be assigned to two opportunities.
4. Pending to filled is valid; filled to pending is rejected.
5. Empty/available complete observation creates coverage; degraded or truncated
   observation does not.

### D. Reconcile matrix

1. Before deadline -> open/deferred.
2. Passed deadline without complete coverage -> expired-coverage-unknown.
3. Complete coverage + no action/decline -> exactly one missed assessment.
4. Decline -> declined; timely action -> acted/action-failed.
5. Not-actionable and unknown signals never become missed.
6. Concurrent reconcile writes at most one assessment; late action preserves
   the historical assessment.

### E. Purity and live smoke

1. Platform reader is observational in file/mirror/canonical settings: no
   account repository/provider/lock/recovery and identical path/bytes/mtime
   before and after.
2. Empty storage is not materialized and returns `empty`.
3. HQA wrapper/install/card contracts remain exact and do not widen the
   mutating allowlist.
4. Real 2026-07-10 scan ingestion yields distinct stable contract identities;
   because no paper-options route exists, it yields zero false missed.
5. The live platform returns an honest empty observation set. Paper account and
   sleeve file hashes remain unchanged.
6. Eligible-to-missed behavior is demonstrated only with isolated fixtures; no
   production signal/execution is generated for the demo.

## Delivered files

Platform:

- `src/quant_system/execution/paper_strategy_observations.py`
- `src/quant_system/cli.py`
- `tests/test_paper_strategy_observations.py`
- `tests/test_cli.py`

HQA:

- `hqa/signals.py`, `hqa/signal_watchdog.py`
- `hqa/opportunities.py`, `hqa/opportunity_cli.py`
- `hqa/quant_cli.py`, `hqa/config.py`
- `scripts/hermes/hqa-opportunities.sh`
- focused signal, ledger, CLI, adapter and install tests
- active roadmap/plan/README and Hermes skill-card reconciliation

## Delivery and acceptance record (2026-07-12)

- HQA now emits stable option-contract `signal_records`, automatically records
  them from the watchdog, and exposes a locked, strict event ledger through
  `hqa-opportunities.sh sync-signals|decide|record-action|sync-actions|reconcile|list`.
- The platform now exposes the CLI-only `paper strategies observations` read
  model. It validates physical layout, strict JSON, committed journals,
  cross-file identities and temporal causality without entering the account
  repository, provider, mutation lock or recovery path.
- Reviewer attacks closed public and hash-consistent forged misses, invalid
  UTF-8 before append, event-order-dependent state, malformed coverage,
  untrusted observation envelopes, non-canonical cursors, pre-source
  decisions/actions/deadlines, orphan/inconsistent committed journals and
  executions that predate their signals. The independent final verdict was
  **PASS with no remaining P0/P1/P2/P3**.
- Focused gates: HQA opportunity ledger/CLI `80 passed`; platform observation
  and CLI `63 passed`; scoped Ruff, format and diff checks passed.
- Full gates: HQA `429 passed, 2 skipped`; platform `1090 passed, 15 skipped`;
  frontend `24 files / 84 tests`, type-check and ESLint passed; throwaway
  PostgreSQL migration/persistence/reconciliation coverage `13 passed`.
- Real 2026-07-10 artifact smoke consumed 748 candidates and produced 59
  threshold signals with 59 unique stable IDs. All 59 are `not_actionable`
  because no supported paper-options route exists; the ledger produced zero
  false missed assessments.
- Real platform smoke returned `read_status=empty`, `returned_count=0`,
  `truncated=false`, four zero quality counters and `errors=[]`. Six observed
  paper-strategy files retained identical bytes, mtime and hash.
- Live 8765/3001 acceptance passed with PostgreSQL enabled/reachable, the four
  paper-only safety flags intact, `/brief/brf_20260710_3yz4rm` and `/zh/hermes`
  returning 200, and the Hermes artifact API exposing two real available cards
  while prediction stayed honestly `empty`. Isolated Playwright brief/Hermes
  user flows both passed.
- Slice 9G itself added no HTTP route, frontend component, `/hermes` card,
  database table/migration, scheduler, notification, strategy generation,
  execution or trading action.

## Completion gate

- All tracer bullets pass without external network, strategy, backtest, paper
  or trading mutation.
- Real scan/platform smoke is honest and observed paper files are byte/mtime
  identical.
- Targeted and full HQA/platform/frontend suites pass; scoped Ruff/diff checks
  are clean.
- Independent Code Reviewer reports no remaining P0/P1/P2.
- Active docs say 9G complete and identify full 9H as next.
- Commit only intended source/docs/test baselines. Exclude runtime ledgers,
  logs, generated live artifacts, caches and unrelated earnings-calendar data.
