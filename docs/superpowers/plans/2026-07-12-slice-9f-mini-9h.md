# Slice 9F + mini 9H — Market Foresight and visible Hermes artifact shelf

> **Status (2026-07-12): COMPLETE (local worktree + live runtime acceptance).**
> This bite-sized plan expanded the next queue item from
> `2026-07-10-phase-1a-4-v2.md`. It delivered 9F and only the visible, read-only
> artifact-consumption subset of 9H. Slice 9G was subsequently delivered by its
> own 2026-07-12 plan; full 9H was subsequently completed and accepted under
> `2026-07-12-full-9h-automation-notifications.md`. This is a predecessor record,
> not a current queue pointer.

## Outcome

Turn the current manual risk/prediction tools and empty `/hermes` stream into a
visible, read-only research loop:

```text
Hermes-authored forecast thesis
  -> HQA validates it against strict completed-session Futu/QFQ evidence
  -> immutable market-foresight candidate (proposal only)
  -> rebuildable Hermes artifact feed
  -> platform GET /api/hermes/artifacts
  -> real risk / prediction / foresight cards on /hermes
```

This slice does **not** enable Composer submit, `/api/agent/tasks`, paper
mutation, strategy execution, backtests, trading, cron, Discord, or automatic
promotion into the prediction ledger.

## Decisions

1. **Hermes reasons; HQA validates and publishes.** Direction, confidence,
   rationale and falsifier originate in the Hermes/user research turn. HQA
   does not hide another LLM call. It validates the candidate and attaches
   strict market evidence.
2. **Candidate is not a prediction-ledger write.** 9F produces a proposal-only
   artifact. A later explicit human confirmation invokes the existing 9E
   `PredictionLedger.create`, which re-anchors the entry price from Futu.
3. **One rebuildable feed seam.** HQA projects the latest portfolio-risk
   artifact, folded 9E prediction states and 9F candidates into
   `artifacts/hermes-feed/manifest.v1.json`. The projection is not a new fact source and
   may be deleted/rebuilt.
4. **Platform never parses HQA raw JSONL.** A small platform catalog reads only
   the versioned feed path and returns a stable card envelope.
5. **One frontend interface.** `/hermes` renders `<ArtifactShelf>` from one
   discriminated-union response and preserves the disabled Composer safety
   boundary.
6. **Mini 9H is deliberately synchronous/manual.** 9F publish refreshes the
   feed, and `hqa-artifacts refresh` can rebuild it explicitly. Scheduling and
   notifications remain full 9H.

## Public interfaces

### HQA

```python
class MarketForesightPublisher:
    def publish(self, request: dict[str, object]) -> dict[str, object]: ...
    def list(self) -> list[dict[str, object]]: ...

class HermesArtifactFeed:
    def rebuild(self, *, limit: int = 50) -> dict[str, object]: ...
    def read(self) -> dict[str, object]: ...
```

`publish` is idempotent by request identity and intent hash. Same request plus
same intent returns the existing immutable artifact; same request plus changed
intent fails closed. All successful candidates carry `proposal_only=true`,
`requires_human_confirmation=true`, and `trading_allowed=false`.

### Platform

```http
GET /api/hermes/artifacts?limit=20
```

The response contains `schema_version`, `read_status`, `as_of`, newest-first
`items`, per-source status, and stable warnings. Missing feed is `empty`;
partial source failure or stale feed is `degraded`; an unreadable/unsupported
manifest is `unavailable`. Local paths and raw exceptions never leave the API.

### Frontend

```tsx
<ArtifactShelf envelope={artifacts} locale={locale} />
```

The shelf renders `portfolio_risk`, `prediction`, and `market_foresight`
cards, including honest empty/degraded/unavailable states. The page remains an
async RSC; Composer stays disabled and performs no network write.

## TDD tracer bullets

1. **9F publish:** a valid US-equity thesis with strict completed-session
   evidence produces one immutable proposal artifact and no prediction entry.
2. **9F safety/failure:** unavailable or invalid evidence writes no candidate;
   request-id conflict fails closed.
3. **Feed projection:** risk, folded predictions and foresight candidates
   become one finite, versioned, atomically written feed; source corruption is
   explicit and healthy sources remain visible.
4. **Platform catalog:** missing, valid, stale and corrupt feed states map to
   one stable GET response; GET performs zero writes.
5. **Hermes shelf:** the RSC renders all three card kinds and accessible
   empty/degraded/unavailable states while Composer remains disabled.
6. **Live E2E:** generate one real 9F candidate, refresh the feed, restart the
   current backend/frontend if needed, and verify `/zh/hermes` displays real
   risk and foresight cards using the running local stack.

## Verification gates

- HQA targeted tests, then full `./.venv/bin/pytest`.
- Platform targeted API/settings/contracts, OpenAPI generation, frontend
  Vitest/type-check/lint, then full backend suite.
- Browser E2E against the running 8765/3001 services.
- Before/after fingerprints prove no paper account, strategy, cache, backtest,
  broker, or trading artifact changed during 9F generation and feed reads.
- Independent Code Reviewer reports no remaining P0/P1/P2.

## Deferred to 9G / full 9H

- 9G signal/decision/action identity and missed-opportunity artifacts.
- Cron cadence, prediction reconciliation schedule, weekly aggregation,
  Discord/local notifications and freshness monitoring.
- Composer submit, interactive Hermes job runner, full timeline and approvals.
- Brief archive completion, AI daily-report persistence and Paper PostgreSQL
  canonical cutover remain separate product-closure work.

## Delivery record (2026-07-12)

- HQA now publishes immutable, proposal-only market-foresight candidates from
  strict completed-session US Futu/QFQ evidence. Publication is atomic,
  idempotent by request and intent, and fails closed on conflict or corrupt
  stored data. It never writes the prediction ledger automatically.
- `hqa-artifacts refresh|show` projects portfolio risk, folded prediction states
  and foresight candidates into the versioned manifest. A broken source
  degrades that source while healthy cards remain visible.
- The platform exposes only `GET /api/hermes/artifacts`; it bounds manifest
  size, validates the schema and provenance, and returns stable
  `available`/`empty`/`degraded`/`unavailable` states without leaking local
  paths or exceptions.
- `/zh/hermes` was verified against the running 8765/3001 stack. It displayed
  the real AAPL proposal and portfolio-risk card, reported the prediction
  source honestly as empty, and kept both Composer controls disabled.
- Full verification: HQA `332 passed, 2 skipped`; platform `1057 passed, 15
  skipped`; frontend 24 files / 84 tests plus type-check and ESLint. Scoped
  Ruff and diff checks passed. A live Futu smoke produced candidate
  `mfp_755315fd9240ec095c741edc`; all 17 observed paper-account and strategy
  state files retained identical content hashes.
- At this slice's acceptance point, the implementation remained in the existing
  dirty local worktrees and had not been committed or pushed. That was a
  historical delivery-state fact, not an incomplete
  feature claim.
- Adversarial review initially reproduced five P1 and four P2 issues. The
  closure added per-write unique feed temporaries, strict risk-source isolation,
  discriminated payload allowlists, parser/time fail-closed handling, clock-skew
  and complete-source validation, regenerated OpenAPI types consumed by the
  frontend, scored-prediction metrics, and a hermetic full-stack Playwright
  path covering all three card kinds plus the disabled Composer.
- The independent Code Reviewer re-ran the original adversarial reproductions
  and the repair contracts, then returned final `PASS` with zero remaining
  P0/P1/P2 and no paper, strategy, backtest, order or trading write path.
