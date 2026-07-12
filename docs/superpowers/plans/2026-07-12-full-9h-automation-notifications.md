# Full Slice 9H — Auditable automation, weekly review, freshness and notifications

> **Status (2026-07-12): COMPLETE (code delivery + live runtime acceptance).**
> This is the current delivery record for the final Phase 1a-4 v2 slice after
> 9A-9G and the read-only mini 9H shelf. No next implementation slice has been
> selected. This plan was expanded from current source and runtime facts; it did
> not revive the superseded 2026-07-07 code templates.

## Acceptance summary

- HQA full suite: `530 passed, 2 skipped`.
- Platform backend: `1122 passed, 15 skipped`; frontend: 24 files / 85 tests
  plus type-check and ESLint; throwaway PostgreSQL: `13 passed`.
- All four Hermes `no-agent`, local-delivery cron jobs were triggered through
  Hermes and report `ok`: `hqa-full-9h-daily-close`,
  `hqa-full-9h-freshness`, `hqa-full-9h-weekly`, and
  `hqa-full-9h-notification-drain`.
- Feed schema 1.1 publishes exactly six sources: `portfolio_risk`, `prediction`,
  `market_foresight`, `weekly_review`, `opportunity_summary`, and
  `automation_status`. Weekly, opportunity, and automation are visible through
  the existing read-only API and `/hermes` alongside the original three kinds.
- The real opportunity projection remains honest: `59 not_actionable / 0 missed`.
- Notification target defaults to local; acceptance did not send a real Discord
  message. Local run and notification receipts are visible and idempotent.
- Acceptance triggered no strategy, backtest, paper mutation, broker, or trading
  path. Full 9H added no platform database migration/table.

## Outcome

Deliver a visible, auditable, read-only automation loop:

```text
Hermes no-agent cron
  -> one HQA ResearchAutomation job
  -> portfolio-risk / prediction reconcile / opportunity reconcile
  -> strict weekly + opportunity + per-job freshness projections
  -> versioned Hermes feed 1.1
  -> existing read-only GET /api/hermes/artifacts
  -> /hermes automation, opportunity and weekly cards
  -> idempotent local/Discord notification receipt
```

The loop may read market/account facts and append proposal/audit artifacts. It
never generates a strategy signal, creates or processes an execution, runs a
backtest, mutates a paper account, sends a broker order or enables live trading.

## Kickoff source-fact verdict (historical)

These were the source facts used to scope this plan before implementation; they
are retained as design evidence and do not describe the post-acceptance runtime.

- Hermes Agent v0.18.2 was running with the built-in ticker. Seven pre-9H HQA
  jobs were active, `no-agent`, local-delivery jobs and reported `ok`.
- There was no cron for portfolio risk, prediction reconciliation, opportunity
  reconciliation, artifact refresh or source/job freshness.
- The pre-9H weekly review had three loose counts and no strict prediction,
  opportunity or freshness facts; it cannot be promoted unchanged.
- The platform detected only whole-feed staleness from manifest
  `as_of`. A frequently refreshed manifest can otherwise hide a stopped source
  job, so job-level freshness must be an HQA artifact.
- HQA and platform both hard-coded the three mini-9H kinds. Publishing a new
  kind before a compatible reader is deployed would make the feed unavailable.
- All pre-9H jobs carried the same workdir and therefore shared one serial Hermes
  pool. The long options collection job can block them. New wrappers already
  `cd` into the repository, so full-9H jobs must omit Hermes `--workdir` and use
  their own bounded non-blocking process lock.
- `hqa-notify.sh` had no notification identity, timeout, lock, successful
  receipt or first-class local target. Its fallback log is not a durable outbox.

## Responsibility split

### HQA / Hermes owns

- schedules and one-shot job execution;
- prediction and opportunity reconciliation cadence;
- strict weekly aggregation from official ledger interfaces;
- run receipts, job freshness and notification receipts;
- feed 1.1 production and the three new aggregate projections.

### Platform owns only

- backward-compatible feed 1.0/1.1 validation;
- the existing read-only artifact GET;
- strict response models and read-only `/hermes` cards.

The platform does not gain a scheduler, outbound worker, Discord credential,
database table/migration, POST route or health-field shortcut.

## Deep module interfaces

### `ResearchAutomation`

One public behavior:

```python
runner.run(
    job="daily_close|freshness|weekly|notification_drain",
    request_id="...",
    as_of="UTC-Z timestamp",
) -> strict result document
```

The implementation hides dependency ordering, isolation, run idempotency,
freshness policy, weekly aggregation, feed refresh and notification policy.
Callers do not invoke internal steps or write artifacts directly.

Invariants:

- same request/same intent returns the existing receipt without repeating work;
- same request/different job/as-of fails closed;
- only one process runs at a time; a concurrent trigger returns `skipped_busy`
  without waiting behind a long job;
- slow platform/Futu reads never hold prediction or opportunity ledger locks;
- one failed/degraded step does not erase healthy artifacts;
- every completed attempt writes one finite, strict, UTF-8 run receipt;
- a job is `available`, `degraded` or `unavailable`; degraded is observable but
  not treated as permission to mutate anything.

Job behavior:

- `daily_close`: catch up signal observations from the latest existing scan
  artifact without launching a scan, write current portfolio risk, reconcile
  due predictions, obtain bounded read-only platform coverage only for
  source-established eligible opportunities, reconcile them, publish
  projections and refresh the feed. `not_actionable` opportunities never call
  the platform observation seam and never become `missed`.
- `freshness`: perform no Futu/account read; fold run receipts into per-job
  freshness, refresh the feed, and notify only on a new degraded/recovered
  state fingerprint.
- `weekly`: build a strict seven-day review, refresh opportunity/freshness/feed,
  and always create one idempotent weekly notification.
- `notification_drain`: perform no market/account read; attempt only pending or
  explicitly retryable outbox records. It never retries `delivery_unknown`.

### `NotificationOutbox`

```python
outbox.deliver(request, send_adapter) -> notification receipt
outbox.list(...) -> folded receipts
```

- request identity, target and message intent are immutable;
- local is a first-class durable delivery target;
- remote delivery has a bounded timeout;
- each drain handles at most five records, so its 15-second per-record timeout
  gives a 75-second send budget and cannot occupy both source-job retry slots;
- concurrent duplicate delivery calls invoke the adapter at most once;
- known failure persists a `fallback_persisted` receipt with mode 0600;
- an ambiguous interrupted attempt becomes `delivery_unknown`, never a false
  `delivered` claim and never an automatic duplicate retry;
- no secret, token or raw exception is persisted or returned.

The full-9H runner defaults to `HQA_FULL9H_NOTIFY_TARGET=local`. A human may
later configure `discord:<channel>`; acceptance must not send a real external
notification.

## Run and freshness contracts

Run receipts are append-only, locked, finite JSON under `automation/runs.jsonl`.
The latest automation projection is an atomic rebuildable status artifact.

Expected modes and budgets:

| job | Hermes schedule (Asia/Shanghai local) | freshness budget |
|---|---|---|
| `daily_close` | `15,25 8 * * 2-6` | 30 hours |
| `freshness` | `17 */2 * * *` | 3 hours |
| `weekly` | `0,10 9 * * 0` | 8 days |
| `notification_drain` | `7,22,37,52 * * * *` | 30 minutes |

The second daily/weekly invocation is an idempotent same-slot retry: a healthy
first run replays its receipt, while a non-blocking-lock busy result gets one
bounded retry ten minutes later. Drain is offset from both source jobs so it
cannot consume the same process slot at their exact start minute; its five-item
limit also bounds the worst-case send portion to 75 seconds.

An argument-free wrapper always canonicalizes both request identity and
`as_of` to the latest non-future primary slot. This keeps early/manual runs from
publishing future-dated windows; explicit `--as-of` plus `--request-id` remains
an intentional operator override.

Per-job projection fields are bounded and exact:

- `job_id`, expected interval, last attempt/success, `fresh_until`;
- `fresh|stale|failed|never_run` plus stable reason code;
- last run ID and conservative notification state:
  `delivered|queued|fallback_persisted|not_required|delivery_unknown`.

The HQA monitor detects a stopped source job. The platform retains its separate
whole-feed `feed_stale` check so a stopped monitor is also detectable. Runtime
platform freshness is tightened from 86400 seconds to 10800 seconds (twice the
two-hour cadence plus jitter).

## Weekly and opportunity projections

Weekly aggregation reads public ledger/list interfaces, not raw event parsing.
It publishes:

- exact UTC period and week ID;
- safety alert, unique signal, review draft/confirmed counts;
- prediction created/scored/hit counts and nullable mean binary Brier;
- opportunity observed/missed/coverage-unknown counts;
- limitations, `proposal_only=true`, `trading_allowed=false`.

Opportunity summary publishes only bounded aggregate facts for a seven-day
window:

- a complete resolution-count map whose sum equals `total_count`;
- miss-reason counts whose sum equals `missed`;
- no raw decision rationale, ledger event or inferred ticker linkage;
- `proposal_only=true`, `trading_allowed=false`.

The cross-repository 1.1 `data` payloads are exact:

- `weekly_review`: `week_id`, `period_start`, `period_end`, safety/signal/review
  counts, prediction created/scored/hit counts, nullable mean direction Brier,
  opportunity observed/missed/coverage-unknown counts, bounded `limitations`,
  and the two safety flags.
- `opportunity_summary`: `window_start`, `window_end`, `total_count`, an exact
  nine-key resolution map, an exact three-key missed-reason map, and the two
  safety flags. Resolution counts sum to total; missed reasons sum to missed.
- `automation_status`: `checked_at`, `overall_status`, one bounded row for each
  of the four job IDs, and the safety flags. Each row has `expected_schedule`,
  `timezone`, budget, last attempt/success/fresh-until, status/reason, last run
  ID and conservative notification status.

## Cross-repository feed 1.1

Keep the path `artifacts/hermes-feed/manifest.v1.json`, but expand the schema
to `1.1`. Deploy the platform's dual reader before HQA emits 1.1.

- 1.0 remains exactly the existing three-source contract.
- 1.1 requires six exact sources/kinds:
  `portfolio_risk`, `prediction`, `market_foresight`, `weekly_review`,
  `opportunity_summary`, `automation_status`.
- New items are strict discriminated payloads with finite/count invariants.
- Automation/opportunity retain only the latest item; weekly history is bounded.
- `/hermes` uses explicit exhaustive rendering; no unknown kind falls through
  to the market-foresight card.
- Composer and agent-task submission remain disabled.

## Hermes schedule migration

After wrappers and tests pass:

1. create `hqa-full-9h-daily-close` without `--workdir`;
2. create `hqa-full-9h-freshness` without `--workdir`;
3. create `hqa-full-9h-notification-drain` without `--workdir`;
4. edit the existing `hqa-weekly-review` job in place to
   `hqa-full-9h-weekly`, preserving Sunday 09:00 and local delivery;
5. keep all four `--no-agent --deliver local` for acceptance;
6. trigger each through Hermes once and verify run/delivery receipts plus cron
   `last_status=ok` before calling the schedule live.

Creation/edit is an explicit local operational action. No job is added to a
mutating platform allowlist.

## TDD tracer bullets

Implement vertically, one RED -> GREEN behavior at a time:

### A. Notification outbox

1. local delivery writes one 0600 receipt and is idempotent;
2. remote success/failure/timeout map to honest receipts;
3. concurrent duplicate request calls the sender once;
4. request reuse with changed target/message and corrupt/torn JSON fail closed.

### B. Weekly/opportunity aggregation

1. empty ledgers produce exact zeros/null mean Brier;
2. strict seven-day boundaries and unique signal IDs;
3. prediction and missed counts/means come through official folded states;
4. resolution/miss sums, finite values and proposal-only flags are invariant;
5. malformed run/review inputs degrade honestly rather than leaking exceptions.

### C. Automation coordinator

1. one daily-close run exercises all public steps and writes one receipt;
2. repeated request is no-op; changed intent conflicts;
3. concurrent trigger returns `skipped_busy`;
4. one step failure preserves later healthy projections and degrades the run;
5. freshness folds current/prior receipts at exact boundary times;
6. notification policy dedupes unchanged degraded state and always emits weekly;
7. no execution/backtest/paper/broker command is reachable.

### D. Feed/platform/UI

1. platform reads existing 1.0 unchanged;
2. platform reads strict 1.1 and rejects wrong source sets/counts/non-finite data;
3. HQA feed produces six exact sources with bounded retention;
4. API read remains byte/mtime pure and request-time feed staleness remains;
5. English/Chinese cards render weekly/opportunity/automation explicitly;
6. degraded freshness is human-readable and Composer remains disabled;
7. isolated full-stack fixture covers all six kinds.

### E. Real acceptance

1. use local notification only; no Discord message is sent;
2. run all four wrappers once and prove idempotent receipts;
3. reconcile real 9G signals without creating execution/trade facts;
4. platform paper/account/strategy fingerprints remain unchanged;
5. install/reconcile cron, verify gateway ticker and new jobs `ok`;
6. restart backend/frontend with PostgreSQL enabled/reachable and safety flags;
7. exercise health, brief archive, AI news, `/zh/hermes` and targeted browser
   flows against the final worktree.

## Planned files

HQA:

- `hqa/notifications.py`, `hqa/opportunity_observations.py`
- `hqa/research_automation.py`, `hqa/research_automation_runtime.py`,
  `hqa/research_automation_cli.py`
- deepen `hqa/weekly_review.py`, `hqa/opportunity_cli.py` and
  `hqa/hermes_artifacts.py`
- `hqa/config.py`, thin Hermes wrappers, installer and skill card
- focused notification/weekly/automation/feed/install tests

Platform:

- Hermes strict models/catalog/API-generated types
- ArtifactShelf and six-kind fixture/tests
- current README/INDEX/OVERVIEW/plan documentation only

## Completion gate (met)

- Every tracer bullet is green under hermetic tests.
- Independent Code Reviewer has no remaining P0/P1/P2.
- Full HQA/platform/frontend/PostgreSQL gates pass.
- Real local cron runs and local notification receipts are visible and
  idempotent; no external notification is sent during acceptance.
- Backend/frontend/Docker PostgreSQL/OpenD/Hermes gateway are running and key
  user flows pass.
- Active docs say full 9H complete and select no new implementation slice
  without a separate user/product decision.
- Commit only intended source/docs/tests. Preserve the platform earnings file,
  CodeGraph overlay, runtime ledgers, artifacts and local notification receipts.
