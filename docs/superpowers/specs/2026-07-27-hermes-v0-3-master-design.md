# Hermes v0.3 Master Design

**Status:** standalone master design for implementation planning  
**Product scope:** local, single-operator Hermes research workbench  
**Safety scope:** research and observation only; public write remains default OFF; live trading remains disabled  
**Precondition:** v0.2.1 release closure is complete on clean, committed HQA and Platform revisions

## 1. Purpose and Decision

Hermes v0.3 extends the approved D-31/F2 research workbench without replacing its information architecture or weakening its authority boundaries. The release adds three independently gated capabilities in this order:

1. immutable, event-derived Task progress;
2. repository-owned absolute wall-clock budgets;
3. deterministic, read-only backtest candidate comparison.

The existing platform shell remains the product frame. The global Sidebar remains the only heavyweight sidebar. Hermes retains lightweight in-content tabs for **Today / Conversations / Tasks / Awaiting Confirmation / Results**. The main stage remains a wide trading-desk surface rather than a narrow center column between two permanent rails.

v0.3 is additive. It does not make Hermes progress, budget status, comparison ranking, or a recommendation into approval or execution authority. It does not retire a legacy route merely because a new read surface exists.

## 2. Normative Dependencies

This master design governs product composition, page behavior, capability activation, provenance labels, responsive behavior, and legacy-route migration. The following three specifications are normative for domain semantics, versioned wire schemas, canonicalization, persistence, replay, state transitions, algorithms, limits, errors, and hermetic acceptance:

1. **Contract 1: Immutable Task Progress**  
   `docs/superpowers/specs/2026-07-27-hermes-v0-3-contract-1-immutable-task-progress.md`
2. **Contract 2: Repository-Owned Absolute Wall-Clock Budget**  
   `docs/superpowers/specs/2026-07-27-hermes-v0-3-contract-2-wall-clock-budget.md`
3. **Contract 3: Deterministic Backtest Comparison**  
   `docs/superpowers/specs/2026-07-27-hermes-v0-3-contract-3-backtest-comparison.md`

This document does not duplicate those schemas. If a field, transition, digest, formula, error, or authority rule differs, the applicable contract specification wins. A change to a contract schema requires changing that contract and its compatibility tests; editing UI copy or this master design cannot alter domain semantics.

v0.2.1 closure is a hard prerequisite and is normative in:

- `docs/superpowers/specs/2026-07-27-hermes-v0-2-1-closure-design.md`

The existing approved product and frontend authorities remain:

- `docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md` for D-31 product decisions and F0-F5 interaction gates;
- `docs/superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md` for official API/BFF boundaries and the page-local expand/parity/cutover/contract migration;
- Platform repository path `docs/design/hermes-workbench/README.md` (not an HQA-local file) for the approved direction-A full-width trading-desk craft, responsive breakpoints, and delivered F2/F2.1/3E-A status.

## 3. Non-Negotiable Authority Boundaries

The following authorities remain separate:

| Concern | Authority | UI treatment |
|---|---|---|
| Task, Attempt, progress plan, progress events, budget binding, budget enforcement, Task/Attempt terminal outcome | HQA append-only workflow authority | Projected read model only |
| Transport Command lifecycle, outbox, lease, exact Run link | Platform PostgreSQL command ledger | Command activity, never inferred Task completion |
| Hermes Run lifecycle and exact-Run stop effect | Hermes Run authority | Run status and stop reconciliation |
| Candidate review | Gate 2 exact manifest-digest manual CAS | Independent human review surface |
| Promotion review | Gate 3 exact candidate/final-receipt/base-commit evidence | Independent human review surface |
| Comparison events and workspace aggregation | Disposable projection | Rebuildable observation only |

No UI reducer may infer one authority's state from another. In particular:

- `N/N` progress does not terminalize a Task, complete a Run, approve evidence, or satisfy any Gate.
- `budget_exceeded` is an HQA terminal outcome, not a Command state, Run state, stop-layer state, or approval result.
- a stopped Run does not prove a stopped Attempt or Task while any layer is unknown or open;
- comparison rank 1 and `proposal_only` do not create, prefill, or submit a Gate 2 action;
- a provider name, populated metric, or successful request does not establish real data provenance.

## 4. Current Baseline Versus v0.3 Activation

The interface must tell the truth about what exists now. Future layouts may be implemented behind capability checks, but unavailable capability must never be rendered as active data.

### 4.1 Current capabilities

The current delivered baseline is:

| Surface | Current capability |
|---|---|
| Global shell | Existing platform Sidebar and SafetyStrip |
| Hermes navigation | Today, Conversations, Tasks, Awaiting Confirmation, Results |
| Today | Read-only action/exception/result overview from platform/HQA projections |
| Conversations | Persisted official Hermes session list and transcript reads |
| Composer | Disabled unless the independent local mutation admission is fully satisfied |
| Tasks | Read-only automation, weekly-review, and opportunity artifacts; not a research Task write ledger |
| Awaiting Confirmation | Read-only review context; approval mutation remains disabled |
| Results | Read-only unified catalog/detail preview over authoritative artifacts |
| Agent Studio redirect | Page-local mechanism exists, default OFF |
| Factor Lab, Experiments, Backtester | Legacy pages retain their write workflows |
| Global legacy redirect | `legacyRedirects=false` |

Current UI must keep explicit notices such as “research task write ledger is not connected” when the authoritative Task projection is absent. A fixture with realistic values does not erase this notice.

### 4.2 Future activated capabilities

Each v0.3 surface activates only after its own contract, integration, and revision gates pass:

| Capability | Required gate | Newly allowed UI |
|---|---|---|
| Task progress read | Contract 1 read capability plus authoritative HQA projection | Step list, `completed/total`, next milestone, derived ratio |
| Task progress write | Contract 1 write capability plus separately authorized mutation surface | Completion command only in the approved owner-local control surface; not implied by this design |
| Wall-clock budget | Contract 2 active enforcement capability | Accepted budget, absolute deadline, remaining display, enforcement/reconciliation state |
| Candidate comparison | Contract 3 evidence, origin, axis, ranking, and proposal capabilities | A/B/C comparison, deterministic ranking or abstention, proposal-only review suggestion |
| Legacy route cutover | Page-specific parity, approval, flag, rollback, and observation gate | Navigation removal and temporary page-local soft redirect |

Disabled capabilities do not show zeroes, empty charts, inactive controls, or fabricated sample values as though they were authoritative. They show one of: **not available**, **not activated**, **legacy data unavailable**, **source degraded**, or **sample preview**, according to the actual condition.

## 5. Information Architecture

### 5.1 Global frame

`/hermes` remains inside the existing platform layout.

- The global Sidebar is the sole heavyweight navigation rail and continues to expose non-Hermes domains such as paper trading, options, AI news, data, and settings.
- Hermes does not add a second vertical application sidebar.
- The global SafetyStrip is the sole persistent paper/live/kill/API safety statement. Content panels do not repeat a large “simulation only” warning card.
- The main Hermes canvas is width-constrained only by the approved content maximum and viewport padding. It is not constrained to a narrow chat column.
- Watch, recovery, source, and technical details use collapsed sections, a bottom strip, or an on-demand drawer. They do not occupy a permanent right rail.

### 5.2 Hermes local navigation

The in-content tab order and route ownership are fixed:

| Tab | Route | Purpose |
|---|---|---|
| Today | `/hermes` | Action, exceptions, active work, recent authoritative results |
| Conversations | `/hermes/sessions` | Persisted session list and transcript reads |
| Tasks | `/hermes/tasks` | Research Task/Attempt/progress/budget read model when activated; current artifact evidence otherwise |
| Awaiting Confirmation | `/hermes/approvals` | Command approvals and Gate review objects, visibly separated by authority |
| Results | `/hermes/results` | Unified factor/backtest/experiment catalog and detail |

Locale prefixes and current query semantics remain intact. Deep links retain stable identifiers. Browser back/forward must restore the selected route, filters, expanded details, and scroll target without creating a command or re-running work.

### 5.3 Density and hierarchy

Every page follows three information levels:

1. **Action and exception:** what requires the operator now, what failed, what is stale, and what remains unknown.
2. **Conclusion:** progress, result summary, ranking or abstention, and relevant limitations.
3. **Technical evidence:** exact refs and digests, source freshness, cursor/checkpoint, event IDs, run IDs, policies, and raw evidence links permitted by the source contract.

Healthy automation remains compressed. Repeated card grids must not promote normal background jobs above exceptions or active research.

## 6. Shared Provenance and Labeling Contract

Every non-authoritative or non-production datum carries a persistent visible label near the datum, not only in a tooltip or technical drawer.

### 6.1 Labels

| Internal provenance | English label | Chinese label | Use |
|---|---|---|---|
| `authoritative_hqa` | `AUTHORITATIVE HQA` | `HQA 权威数据` | HQA journal-derived Task/progress/budget projection |
| verified Contract 3 real origin | `REAL OBSERVED` | `真实观测` | Production comparison only after origin verification |
| `sample` | `SAMPLE` | `示例数据` | Product demonstration from the separate sample application/store |
| `sample_fixture` | `SAMPLE FIXTURE` | `示例夹具` | UI fixture projected through sample-only code paths |
| `test_synthetic` | `TEST SYNTHETIC` | `测试合成` | Automated tests only; never accepted by deployed production or sample applications |
| `hermetic_fixture` | `HERMETIC FIXTURE` | `隔离测试夹具` | Test receipts and screenshots |
| legacy unavailable | `LEGACY: PROGRESS UNAVAILABLE` | `旧任务：无进度数据` | Pre-Contract-1 Tasks |

Labels use text plus shape/icon where needed and never rely on color alone. `REAL OBSERVED` is derived by the Contract 3 verifier; request fields, provider copy, filenames, or fixture content cannot set it.

### 6.2 Mixed and missing provenance

- Mixed origins never collapse to the “best” label. They fail closed under Contract 3.
- Production rejects sample, fixture, and synthetic comparison inputs.
- The sample application accepts only verified sample inputs.
- `TEST SYNTHETIC` is test-process-only.
- Missing provenance is `unverified` or a contract-defined problem/abstention, never real.
- Sample progress or budget data cannot appear in production merely because all required fields are populated.

## 7. Page Design

### 7.1 Today

Today preserves the approved order:

1. current action and exceptions;
2. compressed automation health;
3. active research Tasks;
4. recent results;
5. collapsed technical/source detail;
6. composer dock according to independent chat admission.

When Contract 1 is active, active Task rows may show the exact derived ratio and next milestone. Copy says **milestones completed**, not **percent of work completed**. A bar is a visualization of `completed_steps / total_steps`; it carries the textual fraction and does not imply duration or confidence.

When Contract 2 is active, a Task may show its latest Attempt deadline and state. “Time remaining” is presentation-only, calculated from the immutable deadline and current display clock. The countdown does not write progress, renew a budget, or decide expiry. At or after the deadline, the UI waits for authoritative enforcement state and uses **deadline reached; reconciling** while terminality is unresolved.

Today never embeds the full candidate comparison. It may show a concise result such as **comparison proposal available** or **comparison abstained**, with a link to the Results detail.

### 7.2 Conversations

Conversations remains session-oriented. v0.3 adds links to exact Task, Attempt, Run, result, and comparison projections only when immutable refs exist.

- A transcript message is never Task authority or evidence by itself.
- Streaming text does not change progress.
- Tool activity, token counts, model/provider activity, elapsed time, heartbeats, and reconnects do not change progress.
- A session/provider fallback remains explicit and does not change data origin.
- The transcript keeps its current pinned title/session identity and latest-message behavior.
- Reconnect uses snapshot plus cursor replay; an SSE break is not failure.

### 7.3 Tasks list

Before Contract 1 activation, the current read-only artifact page remains and states that it is not the research Task ledger.

After Contract 1 read activation, the page gains a separate authoritative research section. It does not silently reinterpret existing automation artifacts as Tasks.

Each authoritative Task row shows:

- Task identity and current HQA state;
- terminal outcome separately from structural state;
- origin/provenance label;
- progress availability;
- exact milestone ratio and next milestone when available;
- latest Attempt identity and state;
- wall-clock budget summary only when Contract 2 is active;
- exception or reconciliation reason before technical refs.

Filters include Task state, terminal outcome, progress availability, budget state, and provenance. Default sorting is action required first, then active, then most recently authoritative; it never sorts by a client-side countdown as though that changed authority.

### 7.4 Task detail

`/hermes/tasks/{task_ref}` is introduced only with authoritative Task read capability. It uses an unframed page layout with these bands:

1. Task header: exact ref, state, terminal outcome, provenance.
2. Attention band: blockers, required Gate, reconciliation, or integrity failure.
3. Milestones: immutable ordered steps and accepted completion events.
4. Attempts: ordered Attempt history with exact Command/Run links.
5. Budget: binding, absolute deadline, enforcement phase, and recovery state.
6. Evidence: permitted refs/digests and authoritative event timeline.
7. Technical details: versions, cursors, checkpoints, policy digests.

The milestones section distinguishes:

- pending;
- next eligible;
- completed by accepted event;
- unavailable for a legacy Task;
- frozen by a non-success terminal outcome.

The UI never offers arbitrary step checking. Any future completion control must be admitted separately by Contract 1 write capability and the owner-local mutation policy, must submit the exact next step with expected-version CAS, and must render evidence requirements before confirmation.

### 7.5 Budget presentation and recovery

Contract 2 owns all semantics. The UI provides no budget editing after authoritative acceptance.

The budget panel shows:

- wall-clock allowance as accepted;
- accepted timestamp and absolute deadline;
- queue/approval/lease time inclusion;
- current enforcement phase;
- exact Run stop/reconciliation status when a Run exists;
- closed producer observations when no Run exists;
- original terminal outcome when authoritative pre-deadline completion won;
- `budget_exceeded` only after the HQA terminal event commits.

State copy is exact:

| Authority state | User-facing copy |
|---|---|
| active before deadline | `Budget active` |
| deadline reached, claim or producer state unresolved | `Deadline reached; reconciling` |
| stop requested but one or more layers unknown/open | `Stop requested; work may still be active` |
| terminal HQA budget outcome | `Budget exceeded` |
| terminal completion proved before deadline | Existing terminal outcome; budget panel says `Completed before deadline` |
| integrity failure | `Budget integrity failure; dispatch disabled` |

No countdown reaches zero and changes the Task locally. Reloading, retrying, re-leasing, or restarting does not reset the displayed deadline.

### 7.6 Awaiting Confirmation

This page remains a common inbox, not a merged authority. Objects are grouped and labeled by type:

- Hermes Command approval;
- Gate 1 plan/formula confirmation;
- Gate 2 research approval item;
- Gate 3 promotion review;
- proposal-only comparison result requiring a new manual Gate 2 review.

A Contract 3 recommendation is shown in a read-only **Comparison proposal** section. It contains no approve button, mutation URL, approval token, expected status, actor/note default, executable command, or auto-submit callback. Starting Gate 2 requires entering the independent Gate 2 surface, re-reading exact candidate bytes under its own authorization, and providing the existing human note and digest/status CAS inputs.

### 7.7 Results and comparison

Comparison is a result-detail mode, not a new top-level heavyweight workspace.

The Results list may show comparison records with:

- proposal ready or abstained;
- verified origin label;
- candidate count;
- required-axis completeness;
- policy and evidence-set identity in technical detail.

The comparison detail uses one wide main column:

1. identity and verified origin;
2. controlled-design summary;
3. candidate selector/table;
4. cross-regime stability;
5. cost sensitivity;
6. capacity, normally unavailable until its independent capability activates;
7. deterministic ranking or abstention;
8. limitations and exact immutable evidence;
9. read-only next action.

The ranking unit and all formulas come from Contract 3. The UI does not recompute rank from rounded display values. It consumes the response order and renders exact decimal strings with policy-defined formatting.

If any required candidate-axis pair is incomplete, the ranking area is empty by contract and the page leads with the abstention reason. It never drops the incomplete candidate and ranks survivors.

Charts are optional views of contract results. Every chart has a table/text equivalent, exact axis units, accessible legend, and visible unsupported/unavailable states. Unsupported spread, borrow, fees, nonlinear impact, or capacity evidence is labeled unsupported or unavailable, never plotted as zero.

### 7.8 Technical and recovery drawer

The shared on-demand technical drawer may include:

- exact Task/Attempt/Run/Command refs;
- manifest, plan, budget, policy, evidence, and response digests;
- source authority and event ID;
- source checkpoint/cursor and last successful synchronization;
- schema and capability versions;
- limitations and problem codes.

It must not expose prompts, payload bodies, reasoning, tool output, secrets, provider response bodies, unrestricted evidence bodies, or mutable filesystem paths.

## 8. Responsive and Interaction Rules

The approved F2 responsive behavior remains binding.

### 8.1 Desktop, approximately 1440px

- Preserve at least 1100px usable Hermes main content where the platform shell permits it.
- Keep the global 240px Sidebar; add no permanent secondary rail.
- Local tabs remain horizontal.
- Comparison tables and evidence bands use the full stage.
- A temporary drawer overlays or pushes within the main stage only when opened by the operator.

### 8.2 Laptop, approximately 1280px

- Use one strong main column.
- Move secondary metadata beneath the primary content.
- Candidate comparison tables may horizontally scroll inside their own bounded region; the document itself must not overflow.
- Long identifiers wrap or use explicit copy controls without widening the page.

### 8.3 Tablet, approximately 768px

- Stack content in reading order: status, action, primary content, evidence, technical detail.
- Local navigation becomes compact horizontally scrollable tabs or an equivalent tab control with all five destinations reachable.
- Comparison candidates use a selector/segmented view plus a complete accessible table below; no squeezed three-column cards.
- Drawers become full-width sheets.

### 8.4 Phone, approximately 390px

- Single column only.
- Preserve action and exception content above normal automation.
- Show textual progress ratio next to or above the bar.
- Candidate metrics stack by axis; ranking remains a numbered list/table, not a tiny chart.
- Sticky composer is allowed only under independent chat admission and must not occlude content.
- Every interactive target is at least 44 CSS pixels.

### 8.5 Horizontal quality gates

All activated surfaces require:

- semantic HTML and landmarks;
- complete keyboard path and visible focus;
- WCAG AA contrast;
- state conveyed by text, not color alone;
- `prefers-reduced-motion` support;
- no streaming-scroll hijack;
- zero product console errors and warnings;
- no document-level horizontal overflow;
- reviewed visual regression at 1440x900, 1280x800, 768x1024, and 390x844;
- English and Chinese long text, long IDs, and long error messages;
- manual review of snapshot changes rather than blind update.

## 9. Capability and Data Admission

### 9.1 Reader-first rule

For every contract:

1. deploy strict/tolerant readers and old-record compatibility;
2. activate projection and sample-only UI;
3. prove authoritative integration and rebuild/replay behavior;
4. activate production UI;
5. activate writes or enforcement only under that contract's independent gate.

The frontend receives explicit capability values from the server. It does not infer activation from field presence.

### 9.2 Fail-closed rendering

The frontend differentiates:

- verified empty;
- unavailable source;
- degraded source;
- corrupt/integrity failure;
- capability disabled;
- legacy data unavailable;
- sample fixture;
- real authoritative data.

Unknown enum values, unsupported schema versions, digest conflicts, cursor gaps, and impossible state combinations produce an integrity state and suppress action controls. They do not become generic empty states.

### 9.3 Sample application boundary

Sample comparison and rich future-state demonstrations run through a separately wired hermetic application/store. Production has no `allow_sample`, query switch, cookie, environment toggle, or request field that changes its real-only origin policy. Test synthetic inputs remain test-only.

## 10. Legacy Route Migration

The global invariant remains:

```text
legacyRedirects = false
```

This value remains false through every page-local migration. No implementation may reinterpret it as “all legacy routes have migrated.” Global capability output must continue to report `legacyRedirects=false`; page-local admission is a separate, typed server decision.

### 10.1 `LegacyPageParitySealV1`

Every legacy page cutover requires one immutable, content-addressed server-owned seal. The exact schema is:

| Field | Type | Rule |
|---|---|---|
| `schema_version` | literal `legacy-page-parity-seal.v1` | Required; unknown versions fail closed. |
| `page_id` | `agent_studio|factor_lab|experiments|backtester` | Identifies exactly one legacy page. |
| `legacy_route_family` | non-empty ordered array of route templates | Includes the page root and every owned detail/deep-link route. |
| `destination` | exact locale-neutral Hermes route/intent descriptor | Must equal the page mapping in Section 10.4. |
| `source_revision` | `{repository_url,commit}` | Exact clean 40-hex Platform commit containing the legacy source. |
| `destination_revision` | `{repository_url,commit}` | Exact clean 40-hex Platform commit containing the Hermes destination and redirect implementation. |
| `evidence_digests` | non-empty role-unique array of `{role,sha256}` | Binds page-specific E2E, accessibility, visual, API/contract, deep-link/query/locale, rollback, and telemetry receipts. |
| `workflow_parity_matrix` | non-empty array of `LegacyWorkflowParityV1` | Enumerates every page-owned read, write, async, cancel, approval/handoff, and result workflow. |
| `rollback` | `LegacyRollbackPolicyV1` | Names owner, page-local flag, disable procedure, navigation restore procedure, verification receipt, and maximum response time. |
| `observation_policy` | `LegacyObservationPolicyV1` | Defines duration, required telemetry coverage, regression thresholds, rollback triggers, and completion criteria. |
| `approval` | `LegacyCutoverApprovalV1` | Exact human approval identity, approved seal pre-digest, timestamp, and evidence reference. |
| `valid_from` | canonical UTC timestamp | Seal cannot admit redirect before this instant. |
| `expires_at` | canonical UTC timestamp | Required and strictly later than `valid_from`; expired seals fail closed. |
| `revocation` | `{status:"current"|"revoked",revoked_at:null|string,revoked_by:null|string,reason_code:null|string}` | Revocation fields are all null for `current` and all required for `revoked`. |
| `seal_digest` | lowercase SHA-256 | Digest of canonical seal bytes excluding `seal_digest`. |

`LegacyWorkflowParityV1` contains exactly:

- `workflow_id`: stable page-local identifier;
- `kind`: `read|write|async_status|cancel|approval_handoff|result_handoff|deep_link`;
- `legacy_entry`: exact route and initiating control;
- `destination_entry`: exact Hermes route and initiating control;
- `authority`: the unchanged domain/API/Gate authority;
- `required`: literal `true`;
- `status`: `passed|failed|not_applicable`;
- `evidence_digest`: lowercase SHA-256 for `passed`, null only for justified `not_applicable`;
- `not_applicable_reason`: bounded string only when status is `not_applicable`.

A required owned workflow may be `not_applicable` only when direct repository evidence proves the legacy page never owned it. Any `failed`, omitted, duplicate, unknown, or unjustified item invalidates the seal. Read-only result parity never satisfies a legacy write workflow.

`LegacyRollbackPolicyV1` contains exactly:

- `owner_id` and `owner_role`;
- the exact page-local `flag_name`;
- `disable_value:false`;
- bounded `max_response_seconds`;
- `disable_procedure_digest`;
- `navigation_restore_procedure_digest`;
- `verification_receipt_digest`;
- closed `rollback_trigger_codes` shared with the observation policy.

The rollback action changes only the named page-local flag, restores that page's navigation entry, and verifies the legacy route. It does not toggle `legacyRedirects`, another page flag, a domain API, a Gate, or a safety control.

`LegacyObservationPolicyV1` contains exactly:

- `policy_id`, `policy_digest`, `duration_seconds`, `starts_at`, and `ends_at`;
- `required_telemetry`: deep-link requests, redirect decisions, destination success/error, legacy fallback use, write-workflow outcomes, async/cancel outcomes, locale/query preservation, and rollback latency;
- `minimum_coverage`: policy-fixed counts or ratios for each required telemetry class;
- `rollback_triggers`: closed code, threshold, evaluation window, and required action;
- `completion`: all coverage met, no open rollback trigger, no unresolved severity-1/2 parity regression, and a digested observation receipt.

The policy must trigger rollback for any lost or misrouted write, authority mismatch, stable-ID break, locale/query/deep-link loss above its exact threshold, destination integrity failure, safety-boundary regression, or inability to complete page-local rollback within `max_response_seconds`. Observation success is evidence for the later physical-deletion decision; it does not mutate or extend the seal.

`LegacyCutoverApprovalV1` contains exactly:

- `approver_id`, `approver_role`, and `approval_method`;
- `approved_at` and `approval_expires_at`;
- `approved_seal_pre_digest`, computed over the canonical seal with `approval` and `seal_digest` omitted;
- `approval_evidence_digest`;
- `decision:"approve_cutover"`.

Approval identity cannot be a frontend environment variable, Git author, test actor, default value, or inferred operator. Approval is single-seal, page-specific, expires independently, and becomes unusable after revocation or any source/destination/evidence/policy change.

Canonical JSON for seal and nested digests is UTF-8, sorted-key, compact-separator JSON with `ensure_ascii=false`, `allow_nan=false`, duplicate-key rejection, exact closed fields, and bounded strings/arrays. The server verifies all nested digests, then recomputes `seal_digest`; a path, filename, mutable branch, working-tree state, or “latest” reference is never identity.

### 10.2 Server capability authority

The Platform server owns seal storage, verification, current/revoked state, and redirect admission. The frontend owns no cutover authority. The same-origin server capability response exposes, for each page, exactly:

```text
page_id
flag_name
flag_enabled
seal_status = absent | invalid | pending | accepted | expired | revoked
accepted_seal_digest = sha256 | null
source_revision = 40-hex | null
destination_revision = 40-hex | null
approval_expires_at = UTC timestamp | null
observation_state = not_started | observing | completed | rollback_required
redirect_admitted = boolean
reason_codes = closed string[]
```

`redirect_admitted=true` if and only if all of the following are true in one server evaluation:

1. the request names one known page and its configured page-local flag is exactly true;
2. one accepted `LegacyPageParitySealV1` exists for that page and destination;
3. its `seal_digest`, nested evidence, workflow matrix, revisions, approval, rollback, and observation-policy digests verify;
4. both exact revisions are admitted deployment revisions and the running destination bytes match `destination_revision`;
5. the approval and seal are within `valid_from`/expiry and revocation status is `current`;
6. observation state is not `rollback_required` and no rollback trigger is open;
7. global `legacyRedirects` remains false and standing safety assertions remain satisfied.

Every other condition returns `redirect_admitted=false` with a closed reason code. Missing capability data, server error, stale cache, unknown enum, digest mismatch, expiry, revocation, revision drift, or telemetry-triggered rollback fails closed to the legacy page. Capability responses must be `Cache-Control: no-store` or bound to an expiry/revocation-aware server cache whose maximum age cannot outlive the earliest seal/approval expiry. A previously accepted client response cannot authorize a later navigation.

The legacy page route performs the server admission check before reading legacy data and redirects only on `redirect_admitted=true`. Frontend variables, build-time flags, middleware constants, cookies, query parameters, local storage, or client-side state cannot bypass this check. The existing environment-driven Agent Studio mechanism therefore remains default OFF and is not activation authority until it is upgraded to this server gate.

Seal state transitions are closed:

```text
absent -> pending -> accepted -> expired
                     |       -> revoked
                     -> revoked
```

Only a server-side acceptance command with exact expected state and seal digest may move `pending` to `accepted`. Revocation is terminal for that digest. Renewal or any changed evidence produces a new seal digest and requires new approval; no in-place extension is allowed.

### 10.3 Final contract decision

Physical deletion requires a separate immutable `LegacyPageContractDecisionV1`, not a seal mutation. It contains page ID, accepted seal digest, exact observation receipt digest, final source/destination revisions, telemetry-completeness digest, remaining deep-link policy, retained domain/API/CLI/engine/artifact authorities, deletion revision, decision identity and timestamp, rollback conclusion, and decision digest. The decision is valid only after `observation_state=completed`, all required telemetry coverage is met, no rollback trigger or unresolved severity-1/2 regression remains, and written human decision is current.

Deletion removes only obsolete page components and rewrites old E2E tests as parity/redirect/compatibility tests. It does not delete domain engines, APIs, CLIs, artifacts, Gate authorities, async status/cancel, stable IDs, or compatibility routes required by the final decision.

Each page follows the same four phases independently.

### 10.4 Expand

- Add the Hermes destination and read-only links.
- Keep the legacy page, navigation entry, writes, deep links, query/locale behavior, handoffs, async controls, and tests.
- Record exact parity gaps and usage.

### 10.5 Parity

Prove, with real authoritative data and page-specific E2E, all behavior the page owns:

- read fields and evidence;
- every write workflow;
- deep links, stable IDs, bookmarks, locale prefixes, and query parameters;
- browser back/forward;
- loading, partial, degraded, corrupt, stale, and offline states;
- async status, cancellation, and handoffs;
- responsive, accessibility, and long-content behavior;
- no regression to the remaining legacy pages.

Read-only result parity does not prove write parity.

### 10.6 Cutover

Cutover requires one named default-OFF flag, evidence seal, written user approval, rollback owner, observation plan, and tested immediate rollback per page.

| Order | Legacy page | Hermes destination | Page-local flag |
|---:|---|---|---|
| 1 | Agent Studio | `/hermes/approvals` | existing `QS_HERMES_AGENT_STUDIO_REDIRECT_ENABLED` |
| 2 | Factor Lab | `/hermes` intent plus factor results | `QS_HERMES_FACTOR_LAB_REDIRECT_ENABLED` |
| 3 | Experiments | experiment results and activated research workflow | `QS_HERMES_EXPERIMENTS_REDIRECT_ENABLED` |
| 4 | Backtester | backtest intent/results and all inbound handoffs | `QS_HERMES_BACKTEST_REDIRECT_ENABLED` |

The three new flag names are the required page-local contract for their future implementation. All four flags default OFF. A flag is only operator intent; it is ineffective unless the current same-origin server response for the named page returns `redirect_admitted=true` for the exact accepted `LegacyPageParitySealV1`. Frontend environment variables alone cannot activate a redirect. A single global switch must never cut over multiple pages.

Cutover first removes only that page's navigation entry and enables a temporary soft redirect. Backend engines, APIs, CLIs, artifacts, and stable identifiers remain.

### 10.7 Contract

Physical deletion occurs only after the page's observation period has no rollback-triggering regression, legacy deep-link telemetry is understood, and a final written contract decision is recorded. Deletion removes obsolete page components and rewrites old E2E tests as parity/redirect tests. It does not delete domain engines, APIs, CLIs, artifacts, Gate authorities, async status/cancel, or stable IDs.

Backtester remains last because dashboard, experiment, factor, async-job, cancellation, and result-detail consumers depend on it.

## 11. Delivery Sequence

v0.3 implementation planning must split work into bounded slices. No slice may combine all three domain contracts and route retirement.

### Phase 0: Baseline seal

- Bind clean HQA and Platform revisions and dependency locks.
- Re-run current F2/F2.1/3E-A read-only acceptance.
- Assert safety flags and `legacyRedirects=false`.
- Capture current API/OpenAPI/frontend snapshots.

### Phase 1: Contract 1 readers and projection

- Land contract readers, replay compatibility, projection, workspace types, and sample fixtures.
- Add Tasks list/detail read UI behind explicit read capability.
- Keep all progress writes disabled.

### Phase 2: Contract 1 authoritative activation

- Prove real HQA projection, cursor/checkpoint recovery, and production sample rejection.
- Activate progress UI.
- Admit any write control only through a separate implementation plan and approval.

### Phase 3: Contract 2 shadow and enforcement

- Land versioned readers and migration.
- Run shadow observation without budget binding or enforcement.
- Activate hermetic enforcement, restart/lease-loss canary, then private authorized canary.
- Activate budget UI only after authoritative enforcement evidence.

### Phase 4: Contract 3 evidence and validate-only comparison

- Land strict evidence reader, origin policy, controlled design, axes, ranking policy, limits, and sample application.
- Keep production proposal capability disabled.
- Capacity begins disabled.

### Phase 5: Contract 3 production proposal activation

- Seal complete real producer evidence and exact reader/producer revisions.
- Activate required axes independently.
- Activate proposal-only UI only when every required axis is proposal-enabled.

### Phase 6: Page-local parity and cutover

- Agent Studio, Factor Lab, Experiments, then Backtester.
- Implement server-owned `LegacyPageParitySealV1` verification and the same-origin page capability response before any page-local flag can admit redirect.
- Run expand/parity/cutover/contract separately for each page.
- Require a new seal and approval after any revision, destination, evidence, workflow-matrix, rollback-policy, or observation-policy change.
- Keep global `legacyRedirects=false`.

## 12. Acceptance Matrix

### 12.1 Shared acceptance

- Existing current-capability pages preserve behavior with all v0.3 flags disabled.
- Old API/OpenAPI/frontend snapshots remain compatible except for explicitly additive optional fields.
- Unsupported fields and schema versions fail closed.
- Sample/real labels persist at every responsive width and through navigation.
- No UI reducer derives progress from timers, polling, tokens, provider activity, Run duration, or streaming.
- No countdown locally commits expiry.
- No comparison response validates as a Gate mutation input.
- No v0.3 module imports or calls approval, promotion, release, broker, order, public-write, or Git mutation clients unless that existing independent surface already owns the action.

### 12.2 Frontend acceptance

- Unit/component tests cover every current/future/disabled/degraded/corrupt/sample/real state.
- Generated API types and handwritten discriminated unions reject unknown action-capable states.
- Playwright covers Today, Conversations, Tasks list/detail, budget recovery, Awaiting Confirmation, Results comparison, locale, deep links, back/forward, and page-local redirect rollback.
- Redirect tests prove that every page-local frontend flag remains ineffective for absent, pending, invalid, expired, revoked, revision-mismatched, approval-expired, observation-rollback, and server-unavailable seals.
- Seal tests use canonical digest vectors, exact source/destination revisions, complete workflow parity matrices, approval identity/expiry, revocation, no-store capability responses, and immediate page-local rollback without changing `legacyRedirects`.
- Visual tests cover the four binding viewports and long content.
- Accessibility tests cover keyboard-only operation, focus restoration, tabs, drawers, tables/charts, and 44px targets.
- A reconnect or refresh never submits a mutation or duplicates work.

### 12.3 Contract acceptance

Each contract's full hermetic matrix in its normative specification must pass before its UI activation. A green frontend against fixtures is not contract acceptance. Historical green evidence does not attest dirty or different committed bytes.

### 12.4 Operational acceptance

- Fresh `/api/health` after relevant service restarts.
- Projection deletion/rebuild and cursor-gap recovery demonstrated.
- HQA/Platform/Hermes restart scenarios preserve exact identities and do not renew budgets or synthesize progress.
- Source outage remains readable where cached authoritative evidence permits and disables affected actions.
- Release evidence binds exact commits, commands, exits, interpreters, lockfiles, capability configuration, and clean status.
- Normative-reference validation confirms the three exact contract filenames in Section 2 are produced in the same delivery workflow before this master design is accepted; a missing referenced file blocks implementation planning.

## 13. Rollback

Rollback disables capability admission and page-local redirects; it never rewrites append-only history or deletes artifacts.

- Contract 1 rollback disables new progress writes while retaining read/replay of accepted progress records.
- Contract 2 rollback after first versioned write is reconcile-forward: stop accepting new budgeted Attempts, continue scanners/reconciliation, and retain all budget history.
- Contract 3 rollback disables proposal capability and returns to validate-only or disabled axes; immutable evidence and prior read-only responses remain auditable.
- UI rollback hides unavailable activated views via explicit capability state while retaining honest legacy/unavailable notices.
- Route rollback flips only the affected page-local redirect OFF, revokes or marks rollback-required on its accepted seal, restores its navigation entry, and verifies the legacy route within the seal's maximum response time. The global `legacyRedirects` value and every other page remain unchanged.

Any rollback that encounters journal corruption, deterministic cache conflict, origin conflict, or unknown open producer enters stop-and-audit rather than guessing a repair.

## 14. Security, Privacy, and Trading Boundaries

v0.3 does not:

- add a public/browser/chat mutation route or standing public-write grant;
- change `kill_switch`, `live_trading_enabled`, `release_authorized`, or public-write defaults;
- submit, cancel, replace, or modify broker orders;
- translate repository wall-clock budgets into provider-native token/task budgets, pricing controls, or pacing;
- approve or reject a research candidate;
- register or auto-promote an artifact;
- satisfy Gate 1, Gate 2, or Gate 3;
- infer real origin from labels, provider names, populated fields, or successful Runs;
- expose prompts, payload bodies, reasoning, tool output, secrets, provider bodies, unrestricted evidence, or mutable filesystem paths;
- delete factor, experiment, backtest, candidate, Gate, CLI, API, artifact, async status/cancel, or safety engines during page migration.

Standing runtime assertions remain:

```text
kill_switch = true
live_trading_enabled = false
public_write_standing_default = false
release_authorized = false
legacyRedirects = false
```

## 15. Definition of Done

Hermes v0.3 is complete only when all of the following are true on exact clean committed revisions:

1. Contract 1, then Contract 2, then Contract 3 have passed their normative hermetic and integration gates.
2. Current capabilities remain clearly separated from future activated UI.
3. Every production datum has authoritative provenance; every sample/test datum has a persistent visible label.
4. The approved global Sidebar, five lightweight Hermes tabs, full-width stage, and responsive rules remain intact.
5. Progress, budget, and comparison states remain subordinate to their existing authorities and do not imply approval, promotion, release, public mutation, or trading authorization.
6. Each legacy page has independently completed expand, parity, cutover, and contract with its own default-OFF flag, current accepted `LegacyPageParitySealV1`, server `redirect_admitted=true` decision, written approval, observation receipt, and rollback evidence; global `legacyRedirects` remains false.
7. Frontend quality gates pass at all binding viewports with accessibility, locale, long content, recovery, and integrity states.
8. Documentation and release evidence identify exact contract versions, capability epochs, producer/reader revisions, commands, results, and clean repository state.
