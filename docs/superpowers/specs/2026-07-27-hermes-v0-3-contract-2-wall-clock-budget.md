# Contract 2: Repository-Owned Absolute Wall-Clock Budget

**Status:** normative implementation specification  
**Contract version:** `wall-clock-budget.v1`  
**Authority version:** HQA workflow journal schema `3`  
**Dependency:** Contract 1 must be implemented, replay-safe, and active before Contract 2 writers activate  
**Scope:** private, owner-scoped research Attempts only  
**Safety:** no public write, no browser/chat mutation, no live trading, no provider-native task budget

## 1. Normative Language and Authority

The terms **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative.

The existing ownership boundaries remain:

- HQA append-only workflow journal owns Task and Attempt lifecycle, the budget binding, the deadline claim, enforcement progress, and HQA terminal outcomes.
- PostgreSQL Hermes command ledger owns transport Command lifecycle and durable dispatch/control-command identity.
- Hermes Run authority owns Run lifecycle and exact-Run stop effects.
- Existing Gate 1, Gate 2, Gate 3, result, promotion, release, broker, and trading authorities retain their current semantics.
- Deadline schedulers, scanners, workers, workspace projections, and UI state are observations and wake-up mechanisms. They are not business authority.

Contract 2 MUST NOT infer one authority's state from another. Every cross-authority observation carries an exact immutable reference, an authority-local version or cursor, an authoritative occurrence timestamp when available, and a digest of the normalized observation.

## 2. Closed Vocabulary

### 2.1 Existing states retained

Task structural states remain:

```text
draft | plan_proposed | awaiting_plan_confirmation |
awaiting_formula_confirmation | ready | running |
awaiting_domain_gate | terminal
```

Attempt structural states remain:

```text
planned | running | reconciling | stop_requested | terminal
```

The canonical Platform transport Command states are:

```text
queued | leased | delivered | outcome_unknown |
succeeded | failed | cancelled
```

Transport-terminal states are exactly:

```text
succeeded | failed | cancelled
```

`delivered` and `outcome_unknown` are nonterminal. The Platform backend parser, frontend `TERMINAL_COMMAND_STATES` snapshot, command-ledger database checks, fixtures, and generated API snapshots MUST use this exact set. `rejected` and `timed_out` are public observation/result categories only where an existing adapter maps them; they MUST NOT be inserted into the PostgreSQL `CommandState` union without a separately versioned command-ledger migration.

Hermes Run states remain:

```text
queued | running | waiting_for_approval | stopping |
completed | failed | cancelled
```

Hermes Run terminal states are exactly `completed|failed|cancelled`.

Layered stop per-layer states remain:

```text
requested | confirmed | already_terminal | unknown | not_applicable
```

Layered stop overall states remain:

```text
requested | reconciling | stopped | already_terminal
```

### 2.2 New HQA outcome

`budget_exceeded` is added only to the HQA terminal-outcome vocabulary for Attempts and, under the explicit Task-closure policy in section 12, Tasks.

It is not:

- a transport Command state;
- a Hermes Run state;
- a stop-layer state;
- an `ObserveStop.outcome`;
- a `ResolveReconcile.terminal_outcome`;
- a success result;
- an approval, Gate, promotion, release, or trading state.

Existing `CompleteAttempt` remains success-only with `terminal_outcome="completed"`. Existing `CompleteTask` remains unchanged. Existing generic `ResolveReconcile` remains restricted to its pre-v3 terminal values. Existing `ObserveStop.confirmed` continues to require actual outcome `stopped`. Budget terminalization uses dedicated commands only.

## 3. Policy and Bounds

### 3.1 Repository-owned policy

The initial immutable policy is `wall-clock-budget-policy.v1`:

```json
{
  "schema_version": 1,
  "policy_id": "wall-clock-budget-policy.v1",
  "policy_version": 1,
  "minimum_wall_clock_seconds": 1,
  "maximum_wall_clock_seconds": 2592000,
  "timestamp_precision": "microseconds",
  "deadline_equality_rule": "deadline_wins",
  "task_closure_policy": "close_latest_attempt_task"
}
```

`2592000` is 30 days and matches the existing repository's maximum managed payload lifetime. This is the maximum accepted wall-clock budget, not an inherited payload TTL. The policy document MUST live in HQA source control, be parsed with the strict canonical JSON profile in section 5, and have a committed lowercase SHA-256 digest. Runtime configuration selects only the exact `(policy_id, policy_version, policy_digest)` tuple; callers cannot override bounds or equality semantics.

A deployment MUST fail startup if the configured policy tuple is absent, noncanonical, digest-mismatched, or unsupported. Policy changes require a new positive integer `policy_version` and new digest. Existing bindings continue under the exact policy version and digest stored at acceptance.

### 3.2 Wall-clock field

`wall_clock_seconds` MUST be a built-in JSON integer, not a boolean, float, decimal, string, or coerced value. It MUST be in `[1,2592000]`.

### 3.3 Reserved token and cost fields

Only wall clock is enforceable in v1. Token and cost fields remain reserved null and MUST NOT be translated to Anthropic, provider, model, pacing, pricing, or token-budget parameters.

## 4. Timestamp Contract

All Contract 2 timestamps use this exact canonical grammar:

```regex
^[0-9]{4}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z$
```

Calendar validity is additionally checked by a timezone-aware Gregorian UTC parser. Leap seconds (`:60`), offsets, absent fractions, fractions other than six digits, lowercase `z`, whitespace, and naive timestamps reject. Years are `0001..9999`; invalid month/day combinations reject.

Normalization accepts no alternate wire spelling in v3 records. Producers may receive a timezone-aware clock object internally, but MUST canonicalize to UTC with exactly six fractional digits before digesting or appending.

Deadline arithmetic is:

```text
deadline_at = accepted_at + timedelta(seconds=wall_clock_seconds)
```

Arithmetic MUST occur on a timezone-aware UTC datetime using checked addition. If the result exceeds `9999-12-31T23:59:59.999999Z`, acceptance fails with `workflow_budget_deadline_overflow`; no Task, Attempt, binding, operation receipt, timer, or Platform Command is created.

Comparisons use exact parsed instants:

- `now < deadline_at`: pre-deadline;
- `now == deadline_at`: expired, deadline wins;
- `now > deadline_at`: expired.

Monotonic clocks MAY drive local sleeps only. They MUST NOT determine correctness or be serialized.

## 5. Canonical JSON and Digests

All new documents use UTF-8, sorted object keys, compact separators `,` and `:`, `ensure_ascii=false`, `allow_nan=false`, and rejection of duplicate keys and non-string object keys. NaN, Infinity, negative zero represented as a float, and non-JSON values reject. No Unicode normalization is performed; exact UTF-8 code points are authoritative.

Every digest is lowercase 64-character SHA-256 over the canonical bytes of the explicitly named digest input. Self-digest fields are excluded from their own input.

Identifiers use existing HQA grammar:

```regex
^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$
```

Platform action identifiers retain their existing 200-character grammar. References use the existing exact prefix plus an HQA identifier or digest as applicable.

### 5.1 Closed scalar and reference grammar

Every object in this specification is a built-in JSON object with string keys, its listed fields are REQUIRED unless explicitly typed nullable, and `additionalProperties` is false. A nullable field is still present and has either its non-null type or JSON `null`. Arrays are built-in JSON arrays. JSON booleans are never accepted as integers.

| Name | Exact grammar and bound |
|---|---|
| `Identifier` | ASCII `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` |
| `PlatformIdentifier` | ASCII `[A-Za-z0-9][A-Za-z0-9._:-]{0,199}` |
| `Sha256` | lowercase `[0-9a-f]{64}` |
| `CanonicalUtc` | section 4 grammar and calendar validation |
| `TaskRef` | `task:` + `Identifier` |
| `AttemptRef` | `attempt:` + `Identifier` |
| `RunRef` | `run:` + `Identifier` |
| `CommandRef` | `command:` + `Identifier` |
| `ActionRef` | `action:` + `PlatformIdentifier` |
| `EventRef` | `event:` + `Sha256` |
| `LeaseRef` | `lease:` + `PlatformIdentifier` |
| `EvidenceRef` | ASCII `[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}` |
| `AuthorityId` | ASCII `[a-z][a-z0-9._-]{0,127}` |
| `CursorText` | printable ASCII, 1..256 bytes, no whitespace or control characters |
| `PositiveInt32` | built-in integer `1..2147483647` |
| `PositiveInt63` | built-in integer `1..9223372036854775807` |
| `NonNegativeInt63` | built-in integer `0..9223372036854775807` |

The maximum canonical command document is 64 KiB, matching the existing record ceiling. A producer observation is at most 16 KiB. An all-clear contains exactly one observation for each applicable matrix row, at most 32 observations, and is at most 256 KiB. A workspace snapshot is at most 4 MiB; a follow page contains `1..1000` events and is at most 4 MiB. Limits are checked before append or publication.

### 5.2 Digest coverage

`command_digest` covers the complete canonical command document. `budget_digest`, `binding_digest`, `observation_digest`, `all_clear_digest`, `layered_stop_digest`, source event digests, checkpoint digests, migration semantic-import digest, and problem evidence digests each cover the complete validated object named by the field with only that object's self-digest field omitted. No digest covers a mutable path, current clock display, delivery attempt, or projection row address.

## 6. Version Migration

### 6.1 Platform actions

Existing Platform `UserActionV1` remains byte-for-byte unchanged. New budgeted research actions use a separate closed parser `UserActionV2`; v1 parsers reject v2 and v2 parsers reject v1 unless called through an explicit dual-reader dispatcher.

`research.start` and `research.continue` action v2 add exactly `budget`. All other action kinds remain v1 and MUST NOT be accepted in a v2 envelope.

Platform action v2 fields are:

```text
schema_version: 2
kind: research.start | research.continue
client_action_id
workspace
managed_session_ref
task_ref              # continue only
payload_ref
payload_digest
initial_mode           # start only, exactly plan_only
budget
```

The action digest covers the complete v2 document, including reserved-null objects. A v1 action and v2 action never share a digest namespace accidentally because `schema_version` is included.

### 6.2 HQA commands and journal

Existing command schema v2, journal filename `workflow-events.v2.jsonl`, projection filename `workflow-projection.v2.json`, record bytes, event IDs, hashes, backups, and replay remain immutable.

Contract 2 introduces command schema `3`, journal `workflow-events.v3.jsonl`, projection `workflow-projection.v3.json`, and lock `.workflow-authority-v3.lock`. A v3 authority is created by a one-time sealed migration:

1. Securely lock the v2 authority and freeze writers.
2. Replay and verify every v2 record under the unmodified v2 reducer.
3. Translate each verified v2 record, in sequence order, into exactly one closed `legacy_v2_record_imported` v3 event. Its data contains `legacy_sequence`, `legacy_event_id`, `legacy_event_type`, `legacy_occurred_at`, `legacy_record_sha256`, `legacy_previous_record_sha256`, `legacy_operation_id`, `legacy_operation_digest`, `legacy_task_ref`, `legacy_attempt_ref`, `legacy_task_version`, and `legacy_semantic_facts`.
4. `legacy_semantic_facts` is the exact closed v3 semantic payload for the imported v2 event kind. It MUST contain every canonical fact required to replay the Task and Attempt without the v2 projection. Feature-enabled `research_started` imports the complete immutable `execution_progress_plan`; every `step_completed` import carries its exact step, ordinal, plan digest, Attempt/Run bindings, and evidence metadata. Importing only a projection digest, record digest, or locator is forbidden.
5. The v3 reducer validates the imported event against the verified v2 record, replays `legacy_semantic_facts`, and MUST rebuild every Contract 1 progress field and completion from v3 journal alone after both v2 and v3 projections are deleted. Legacy pre-Contract-1 Tasks remain `legacy_unavailable`; feature-enabled Tasks remain fully available.
6. The v3 initial projection MUST equal the verified v2 semantic projection for all preexisting fields, including Contract 1 execution progress.
7. Produce `WorkflowV2ToV3MigrationReceiptV1` containing owner, v2 journal SHA-256, v2 projection SHA-256, v2 event count, v3 migration-head record SHA-256, v3 projection SHA-256, Contract 1 semantic-import digest, tool revision, and migration timestamp.
8. Seal the receipt and retain the v2 authority read-only.
9. Start v3 writers only after byte-for-byte v2 backup/restore, projection-deletion rebuild, Contract 1 completion replay, and semantic projection equivalence pass.

No in-place edit, filename rename, version-number substitution, or v3-to-v2 downgrade is allowed. A Task is governed entirely by one authority version. Legacy Tasks migrated into v3 have `budget_contract_status="legacy_unbudgeted"`; budgets are never backfilled onto existing Attempts.

### 6.3 Rollback after v3 writes

Before the first v3 write, rollback may disable v3 and return to the untouched v2 authority. After any non-migration v3 record exists, rollback means:

- disable new v2 action acceptance and new budgeted Attempt creation;
- leave v3 replay/read enabled;
- keep dispatch and success-finalization budget barriers enabled for all existing bindings;
- reconcile every claimed or overdue binding forward;
- never rewrite, truncate, translate, or downgrade v3 history.

## 7. Budget Schemas

### 7.1 `TaskBudgetV1`

Exact fields:

| Field | Type | Required |
|---|---|---:|
| `schema_version` | integer `1` | yes |
| `wall_clock_seconds` | integer `1..2592000` | yes |
| `tokens` | `ReservedTokenBudgetV1` or null | yes |
| `cost` | `ReservedCostBudgetV1` or null | yes |

`ReservedTokenBudgetV1` is exactly:

```json
{
  "type": "tokens",
  "total": null,
  "unit": "model_tokens",
  "enforcement": "reserved"
}
```

`ReservedCostBudgetV1` is exactly:

```json
{
  "type": "cost",
  "amount_minor": null,
  "currency": null,
  "enforcement": "reserved"
}
```

For canonical cross-language behavior, `tokens` and `cost` are required keys. Each value may be null or its exact reserved object. Non-null total, amount, or currency rejects. Unknown fields reject.

`budget_digest = sha256(canonical_json(TaskBudgetV1))`.

### 7.2 Budget-bearing HQA acceptance commands

`StartResearchV3` exact fields:

```text
schema_version:3
kind:"workflow.start_research"
operation_id:Identifier
owner_user_id:Identifier
workspace_ref:exact `workspace:` + Identifier
managed_session_ref:exact `session:` + Identifier
payload_ref:exact `payload:sha256:` + Sha256
intent_expires_at:CanonicalUtc
budget:TaskBudgetV1
budget_policy_id:Identifier
budget_policy_version:PositiveInt32
budget_policy_digest:Sha256
source_action_ref:ActionRef
source_action_digest:Sha256
execution_progress_plan:Contract 1 ExecutionProgressPlanV1
```

`execution_progress_plan` is REQUIRED and is exactly Contract 1's immutable execution-progress-plan schema, including its verified `plan_digest`. Contract 2 defines no second progress schema. `StartResearchV3` is invalid unless Contract 1 read/write capabilities are active and the plan passes Contract 1 canonicalization, quotas, evidence-policy, and digest validation.

`ContinueResearchV3` exact fields are `schema_version:3`, `kind:"workflow.continue_research"`, `operation_id:Identifier`, `owner_user_id:Identifier`, `task_ref:TaskRef`, `expected_version:PositiveInt63`, `payload_ref` using the existing `payload:sha256:` + `Sha256` grammar, `intent_expires_at:CanonicalUtc`, `budget:TaskBudgetV1`, `budget_policy_id:Identifier`, `budget_policy_version:PositiveInt32`, `budget_policy_digest:Sha256`, `source_action_ref:ActionRef`, and `source_action_digest:Sha256`. It MUST NOT contain `execution_progress_plan`: continuation reuses the Task's immutable Contract 1 plan and never replaces it. Its `research_continued` semantic payload carries the immutable progress-plan digest and completed step event refs only as reducer cross-checks; they do not create, reset, or advance completion.

A v3 `StartResearch` or `ContinueResearch` MUST contain a budget. Unbudgeted new v3 Attempts are forbidden while `wall_clock_budget_v1` writer capability is active; there is no “accept now, bind later” mode.

### 7.3 Authoritative acceptance event

The authoritative acceptance event is exactly:

- `research_started` for Attempt 1; or
- `research_continued` for each later Attempt.

Its `occurred_at` is `accepted_at`. The WorkflowAuthority obtains and normalizes the clock once while holding its owner authority lock, after command validation and replay/idempotency lookup, and before building the record. That same timestamp is used for the event envelope and binding. Attempt creation, budget binding, operation receipt, and Task-version increment are one journal append under the same lock. No scheduler, Platform action receipt, command-ledger row, worker lease, or HTTP arrival time can set `accepted_at`.

The feature-enabled `research_started` event data contains the existing exact fields plus `execution_progress_plan` and `budget_binding`. `research_continued` contains its existing v2 semantic fields plus `execution_progress_plan_digest`, `completed_step_event_refs`, and `budget_binding`. The reducer recomputes completion from accepted Contract 1 events and rejects a continuation whose plan digest or completion refs differ. A v3 Task therefore preserves `N/N`, next step, completion event identity, and Contract 1's `completed` terminal guard after projection deletion and replay.

### 7.4 `BudgetBindingV1`

Exact required fields:

```text
schema_version:1
budget_digest
binding_digest
budget_policy_id
budget_policy_version
budget_policy_digest
accepted_at
deadline_at
source_action_ref
source_action_digest
source_workflow_event_ref
task_ref
attempt_ref
attempt_number
```

`binding_digest` excludes itself and is SHA-256 of canonical JSON containing all other binding fields. `source_workflow_event_ref` equals the containing event's deterministic event ID. The reducer recomputes task/attempt refs, event ID, timestamps, deadline arithmetic, budget/policy digests, attempt number, and binding digest; mismatch is journal corruption.

One binding exists per budgeted Attempt. A replay returns the original receipt and binding. `ContinueResearch` creates a new Attempt and requires a new complete budget. It never inherits the prior deadline, and unused time never rolls over. Retry/re-lease/restart within one Attempt retains the same binding.

## 8. Deterministic Identity

All formulas use canonical JSON and lowercase SHA-256.

```text
enforcement_id = "budget-enforcement:" + sha256({
  schema_version:1,
  owner_user_id,
  task_ref,
  attempt_ref,
  binding_digest
})
```

```text
claim_operation_id = "budget-claim-" + sha256({enforcement_id,binding_digest})[:48]
```

```text
stop_action_id = "budget-stop-" + sha256({
  enforcement_id,
  binding_digest,
  run_ref
})[:48]
```

```text
attempt_terminal_operation_id = "budget-attempt-terminal-" +
  sha256({enforcement_id,binding_digest})[:40]
```

```text
task_terminal_operation_id = "budget-task-terminal-" +
  sha256({enforcement_id,binding_digest,attempt_ref})[:40]
```

```text
observation_id = "budget-observation:" + sha256({
  enforcement_id,
  authority_id,
  subject_ref,
  authority_version_or_cursor,
  state,
  occurred_at,
  observed_at,
  evidence_digest
})
```

A different Run ref observed for an Attempt after `budget_stop_control_bound` is an integrity conflict. The system MUST NOT mint another stop identity.

## 9. Commands, Events, and Receipts

### 9.0 Exact command envelope

Every Contract 2 command is a closed schema-v3 document with these REQUIRED common fields:

```text
schema_version:3
kind:the exact literal named below
operation_id:Identifier
owner_user_id:Identifier
task_ref:TaskRef
attempt_ref:AttemptRef
expected_version:PositiveInt63
```

The authority instance authenticates `owner_user_id`; request routing cannot select another owner. The Task MUST belong to that owner, the Attempt MUST belong to that Task, and the Attempt's current binding MUST equal every supplied binding field. Commands contain no prompt, payload body, provider body, free-form note, model/provider ID, mutable path, UI time, or client-supplied authority timestamp.

In the command definitions below, unqualified `enforcement_id` is `EvidenceRef`, `binding_digest`, `observation_digest`, `layered_stop_digest`, `all_clear_digest`, `stop_action_digest`, `final_observation_digest`, and preserved evidence digests are `Sha256`; `run_ref`, `command_ref`, `stop_command_ref`, event refs, action refs, and lease refs use section 5.1. `reason_code` is a literal closed per-command enum. Every shown nullable field is REQUIRED and explicit `null` when absent.

### 9.1 Commands

All are schema version `3`, strict closed documents, and include the common envelope above.

`ClaimBudgetDeadline`:

```text
kind:"workflow.claim_budget_deadline"
enforcement_id
binding_digest
deadline_at
claimed_at
trigger:"scheduler"|"scanner"|"dispatch_barrier"|"success_barrier"|"recovery"
```

`RecordBudgetDispatchSuppressed`:

```text
kind:"workflow.record_budget_dispatch_suppressed"
enforcement_id
binding_digest
command_ref:null|command ref
lease_ref:null|bounded ref
observation_digest
```

`BindBudgetStopControl`:

```text
kind:"workflow.bind_budget_stop_control"
enforcement_id
binding_digest
run_ref
stop_action_ref
stop_action_digest
stop_command_ref
```

`ObserveBudgetStop`:

```text
kind:"workflow.observe_budget_stop"
enforcement_id
binding_digest
run_ref
stop_action_ref
stop_command_ref
layered_stop_receipt
layered_stop_digest
observation_digest
```

`BeginBudgetReconcile`:

```text
kind:"workflow.begin_budget_reconcile"
enforcement_id
binding_digest
reason_code
```

`ObserveBudgetProducer`:

```text
kind:"workflow.observe_budget_producer"
enforcement_id
binding_digest
claim_event_ref
authority_observation
```

`TerminalizeAttemptForBudget`:

```text
kind:"workflow.terminalize_attempt_for_budget"
enforcement_id
binding_digest
claim_event_ref
all_clear_digest
final_observation_digest
open_producers:[]
terminal_outcome:"budget_exceeded"
```

`PreserveAttemptTerminalBeforeBudget`:

```text
kind:"workflow.preserve_attempt_terminal_before_budget"
enforcement_id
binding_digest
claim_event_ref
preserved_terminal_event_ref
preserved_terminal_outcome
preserved_terminal_evidence_digest
preserved_terminal_occurred_at
```

This command appends budget resolution metadata only; it does not create or alter the earlier terminal outcome.

`TerminalizeTaskForBudget`:

```text
kind:"workflow.terminalize_task_for_budget"
enforcement_id
binding_digest
attempt_terminal_event_ref
terminal_outcome:"budget_exceeded"
```

`ObserveBudgetProducer.reason_code` is exactly `producer_closed|producer_open|producer_unknown|producer_unavailable|producer_stale|producer_cursor_gap|producer_inapplicable`. `BeginBudgetReconcile.reason_code` is exactly `stop_outcome_unknown|producer_open|producer_unknown|producer_unavailable|producer_stale|producer_cursor_gap|authority_recovery`. The reason must agree with the embedded observation or current authoritative fact.

### 9.2 Closed event envelope

Every v3 record contains exactly `schema_version:3`, `sequence:PositiveInt63`, `event_id:EventRef`, `operation_id:Identifier`, `operation_digest:Sha256`, `owner_user_id:Identifier`, `task_ref:TaskRef`, `attempt_ref:AttemptRef|null`, `task_version:PositiveInt63`, `event_type`, `occurred_at:CanonicalUtc`, `data`, `previous_record_sha256:Sha256|null`, and `record_sha256:Sha256`. Sequence 1 requires null previous digest; later records require the prior record digest. Event ID and record digest are recomputed under the existing semantic-ID/hash-chain algorithm with schema version 3. Unknown event type, extra/missing field, invalid owner/ref/time, noncanonical bytes, sequence gap, or digest mismatch is `workflow_journal_corrupt`.

### 9.3 Events

Each event uses the v3 hash-chain envelope and exact event data matching its command after removal of command-only `kind`, `schema_version`, and `expected_version`; authority-derived `phase_sequence`, `phase_event_ref`, and exact receipt fields are added where specified below:

```text
budget_deadline_claimed
budget_dispatch_suppressed
budget_stop_control_bound
budget_stop_observed
budget_reconcile_started
budget_producer_observed
attempt_budget_exceeded
budget_already_terminal
task_budget_exceeded
```

There is no standalone `budget_bound` append. Binding is part of `research_started|research_continued`, preserving atomic acceptance.

### 9.4 `BudgetDeadlineClaimV1`

Exact fields:

```text
schema_version:1
enforcement_id
binding_digest
task_ref
attempt_ref
deadline_at
claimed_at
trigger
disposition:"enforcing"|"already_terminal"
preserved_terminal_outcome:null|existing terminal outcome
preserved_terminal_evidence_digest:null|sha256
claim_event_ref
```

For `enforcing`, the preserved pair is null. For `already_terminal`, both are present.

A claim is a durable fence and nonterminal while evidence is unknown. It suppresses future dispatch and success finalization immediately, but does not itself assert `budget_exceeded`.

### 9.5 `BudgetEnforcementReceiptV1`

Exact fields:

```text
schema_version:1
enforcement_id
binding_digest
phase_sequence
phase
phase_event_ref
task_ref
attempt_ref
run_ref
stop_action_ref
stop_command_ref
deadline_at
observed_at
layered_stop_receipt
layered_stop_digest
observation_digest
all_clear_digest
terminal_outcome
idempotent_replay
```

Nullable fields are explicitly present as null. `phase` is one of:

```text
claimed | dispatch_suppressed | stop_control_bound |
stop_observed | reconciling | terminal | already_terminal
```

`terminal_outcome="budget_exceeded"` is valid only at `phase="terminal"`. Receipt projections are derived from journal replay and are not independently writable.

### 9.6 Layered stop receipt schema

`layered_stop_receipt` is either null or the existing public `LayeredStopReceipt` closed dictionary. Its REQUIRED keys are `hermes_run`, `hqa_attempt`, `platform_job`, `overall`, and `idempotent_replay`; optional `run_id` and `run_status` are represented in Contract 2 canonical form as REQUIRED nullable fields. Each layer is `requested|confirmed|already_terminal|unknown|not_applicable`; overall is `requested|reconciling|stopped|already_terminal`; `run_id` is a `PlatformIdentifier|null`; `run_status` is a bounded printable ASCII string `1..64|null`; `idempotent_replay` is boolean. `layered_stop_digest` is null iff the receipt is null, otherwise it is its canonical digest. Contract 2 does not add a layer or state.

## 10. Authority-Locked Barriers

WorkflowAuthority performs a deadline check under its lock/CAS:

1. before allowing any new submission Command binding;
2. before a dispatcher leases a queued Command;
3. before `mark_dispatch_started` permits external dispatch;
4. before requeue/re-lease after retry or lease loss;
5. before accepting `ObserveRun` for a newly created Run;
6. before accepting provider evidence, result links, Gate 3 evidence, `CompleteAttempt`, or successful `CompleteTask` paths;
7. at every scheduler/scanner/recovery claim.

Platform lease and dispatch code MUST call an HQA-owned `DeadlineEligibilityPort` with exact Attempt/binding/expected Task version before its PostgreSQL transition. An unavailable, corrupt, stale, claimed, or expired response suppresses lease/dispatch. Platform MUST NOT cache an “eligible” response across a version change or external effect.

At `now >= deadline_at`, the barrier invokes the deterministic claim command before returning suppression. Scanner participation is not required for correctness.

## 11. Scheduler and Scanner Ownership

`DeadlineSchedulerPort.arm(enforcement_id, deadline_at)` is called only after the acceptance receipt is durable. Failure to arm does not roll back or invalidate acceptance; it emits an operational alert and relies on barriers/scanner.

The scheduler:

- owns no timestamp, state, or terminal decision;
- may wake early, exactly on time, late, more than once, or after restart;
- submits only `ClaimBudgetDeadline` using deterministic identity;
- MUST NOT dispatch stop effects directly.

The durable scanner reads HQA v3 bindings through a persisted semantic cursor. It scans for `deadline_at <= authoritative_clock_now` without a terminal budget resolution. Cursor advancement and the set of examined binding/event digests are committed atomically in the scanner store. On cursor gap, regression, authority reset, digest mismatch, or journal corruption it stops and audits; it never skips forward.

A scanner restart reopens from the last committed cursor and may resubmit exact deterministic claims. Early scans append nothing. Late scans preserve the original deadline and use current `claimed_at` only as observation metadata.

## 12. Enforcement Transition Table

The aggregate begins implicitly as `bound` in the Attempt binding.

| Current | Input/guard | Event | Next | External effect |
|---|---|---|---|---|
| `bound` | `now < deadline` | none | `bound` | none |
| `bound` | exact terminal Attempt event with `occurred_at < deadline` | `budget_already_terminal` | `already_terminal` | none |
| `bound` | `now >= deadline`, not resolved | `budget_deadline_claimed` | `claimed` | none |
| `claimed` | queued/leased/undispatched producer found | `budget_dispatch_suppressed` | `dispatch_suppressed` | cancel/suppress only through owning authority |
| `claimed|dispatch_suppressed|reconciling` | exact Run is bound and no stop control exists | `budget_stop_control_bound` | `stop_control_bound` | durable Platform stop Command identity committed before stop call |
| `stop_control_bound|reconciling` | stop observation arrives | `budget_stop_observed` | `stop_observed` or `reconciling` | at most one durable stop effect |
| any nonterminal enforcement phase | missing/stale/unknown producer observation | `budget_reconcile_started` or `budget_producer_observed` | `reconciling` | none beyond exact retries |
| any nonterminal enforcement phase | verified pre-deadline HQA terminal event | `budget_already_terminal` | `already_terminal` | none; preserve actual outcome |
| any nonterminal enforcement phase | closed producer matrix fresh and all closed, no pre-deadline success | `attempt_budget_exceeded` | `terminal` | none |
| `terminal` | Task closure policy satisfied | `task_budget_exceeded` | Task terminal | none |
| `terminal|already_terminal` | exact replay | none | unchanged | none |

Illegal phase skips, phase-sequence regression, changed immutable field, changed Run ref, mismatched stop identity, or event digest reuse fail with `workflow_budget_integrity_failure` and place the Attempt in operational `stop_and_audit`; they do not append a guessed recovery event.

Each accepted phase increments Task version once. Same operation ID plus same digest returns the original receipt with `idempotent_replay=true`. Same operation ID plus different digest is `workflow_idempotency_conflict`. A semantically duplicate phase under another operation ID returns `workflow_budget_phase_already_recorded`, references the original phase event, appends nothing, and does not reserve the new operation ID.

## 13. Deadline Race Resolution

The deadline claim is a fence against new work, not the final outcome. Resolution uses authoritative occurrence time, never observation arrival time.

1. If an HQA terminal event was durably appended before the claim and its `occurred_at < deadline_at`, the actual existing outcome wins.
2. If a producer completed an external effect before the deadline but HQA did not terminalize, that effect alone does not prove Task/Attempt success. It must be reconciled through the existing exact success evidence path and produce an HQA terminal event whose authoritative source evidence proves occurrence before the deadline.
3. During reconciliation, exact immutable evidence with authoritative `occurred_at < deadline_at` may resolve the claim as `already_terminal`; the claim remains in history.
4. Evidence occurring exactly at or after the deadline cannot establish pre-deadline completion and cannot overwrite the claim.
5. Missing occurrence time, mutable timestamps, worker-local timestamps, receipt arrival time, or unverified provider timestamps are `unknown`; enforcement remains `reconciling`.
6. Once `attempt_budget_exceeded` is appended after a complete all-clear proof, later success is ineligible and cannot rewrite the terminal event.

This rule makes completion-before-deadline win independent of delayed observation while preventing late success from overwriting a fully reconciled terminal decision.

## 14. Exact-Run Stop Protocol

When a Run exists:

1. Under HQA lock, validate the exact Attempt-to-Run binding and claim fence.
2. Derive the stop action ID and digest from the enforcement and exact Run ref.
3. In Platform PostgreSQL, create or retrieve the durable control Command using that identity before any Run mutation.
4. Append `budget_stop_control_bound` with the exact action and Command refs.
5. Call the production Run control port. The in-process fake adapter is test-only and cannot attest at-most-one production effect.
6. Observe through the production Run control outcome authority and build the unchanged layered receipt.
7. Lost acknowledgement, timeout, unavailable observer, or any unknown Attempt/job layer remains `reconciling`; replay reuses the original action and Command.
8. `hermes_run=confirmed` alone never terminalizes Attempt or Task.
9. An already-terminal Run preserves its actual Run status. It does not automatically determine HQA outcome.

At-most-one external stop effect is guaranteed by the durable Platform control-command/outcome authority keyed by stop action identity, not by scheduler dedupe or process memory.

## 15. No-Run All-Clear Evidence

No fake Run or stop Command is created when no Run is bound. Terminalization requires a closed producer matrix and a fresh `NoOpenProducerEvidenceV1`.

### 15.1 Closed producer matrix

| `authority_id` | Subject | Closed states | Open/unknown states | Required version/freshness source |
|---|---|---|---|---|
| `hqa.workflow.v3` | Attempt | terminal only | all other states | Task version under same HQA lock as terminalization |
| `platform.command_ledger.v1` | exact Attempt-bound submission Command or proven absence | `succeeded|failed|cancelled`; absence only with absence fence below | `queued|leased|delivered|outcome_unknown`, unavailable | PostgreSQL transaction snapshot plus command event head |
| `platform.command_outbox.v1` | outbox rows for exact Command | consumed or atomically cancelled before dispatch | unconsumed, claimed, unavailable | same PostgreSQL snapshot and outbox high-water mark |
| `platform.dispatch_lease.v1` | exact Command lease | no active lease and no dispatch-started ambiguity | active/unexpired lease, stale unknown, unavailable | same command row version and DB statement timestamp |
| `platform.run_link.v1` | Attempt/Command Run links | no link at or before captured run-link high-water mark | any Run link, cursor gap, unavailable | run-link cursor/high-water mark in same DB snapshot |
| `hermes.run_authority` | exact Run if discovered | `completed|failed|cancelled` plus observed outcome | nonterminal, missing after prior binding, unavailable | authoritative Run version/event cursor |
| `platform.job_authority.v1` | exact Attempt-bound Platform job | terminal or proven absent | nonterminal, unknown, unavailable | job-store snapshot version/high-water mark |
| `platform.result_authority.v1` | Attempt-bound artifact/result producer | committed terminal artifact or no producer registration before fence | writing/pending/unknown/unavailable | result authority snapshot/version |
| `hqa.provider_evidence.v3` | provider evidence bindings | immutable existing refs only; no pending producer | pending/unknown producer | HQA Task version and exact refs |

Production activation is forbidden until each matrix adapter is implemented against a real durable authority. A non-existent current job or result store cannot be treated as “absent”; it is `unsupported_authority` and keeps the Attempt reconciling unless deployment policy proves that producer class is impossible for the accepted action kind.

### 15.2 Absence fence

Absence is valid only when:

- the observation is taken after the claim event is durable;
- the authority query is scoped by owner, Task, Attempt, source action, and where applicable Command;
- it records the authority's transaction snapshot ID or semantic high-water cursor;
- the high-water cursor is at least the cursor captured by the claim/reconcile start;
- the observation is used in the same HQA lock/CAS cycle or revalidated after reacquiring the lock;
- no new binding or producer registration can commit without first passing the claimed-deadline barrier.

### 15.3 `AuthorityProducerObservationV1`

Exact fields and types:

```text
schema_version:1
authority_id:AuthorityId
subject_ref:EvidenceRef
binding_digest:Sha256
claim_event_ref:EventRef
authority_version_or_cursor:CursorText
claim_fence_cursor:CursorText
state:"closed"|"open"|"unknown"|"unavailable"|"stale"|"cursor_gap"|"inapplicable"
is_open:boolean|null
occurred_at:CanonicalUtc|null
observed_at:CanonicalUtc
evidence_ref:EvidenceRef
evidence_digest:Sha256
observation_digest:Sha256
```

`is_open` is `false` only for `closed|inapplicable`, `true` only for `open`, and null for `unknown|unavailable|stale|cursor_gap`. `inapplicable` is legal only when the digest-bound matrix policy marks that authority impossible for the accepted action kind. `occurred_at` is non-null only when the source authority supplies a verified occurrence instant. `observation_digest` excludes itself and covers all other fields. Observations are immutable; changed source version/cursor, state, time, ref, or digest creates a new observation ID and never mutates an earlier fact.

### 15.4 `NoOpenProducerEvidenceV1`

Exact fields and types:

```text
schema_version:1
enforcement_id:EvidenceRef
binding_digest:Sha256
claim_event_ref:EventRef
claim_task_version:PositiveInt63
matrix_policy_id:"no-open-producer-matrix.v1"
matrix_policy_digest:Sha256
observations:[AuthorityProducerObservationV1]
open_producers:[]
unknown_producers:[]
assembled_at:CanonicalUtc
all_clear_digest:Sha256
```

Observations are sorted by `(authority_id,subject_ref)`, contain exactly one entry for every applicable matrix row, contain no duplicates, and have claim/binding fields identical to the enclosing document. `all_clear_digest` excludes itself and covers the entire object. `open_producers` and `unknown_producers` are REQUIRED empty arrays for this all-clear type; a diagnostic candidate with non-empty arrays is a different internal type and cannot reach terminalization. Any missing, stale, cursor-gapped, unavailable, unsupported-but-possible, changed, or newly discovered producer leaves the Attempt `reconciling`.

## 16. Attempt and Task Terminalization

`TerminalizeAttemptForBudget` is legal only when:

- deadline claim is committed;
- `now >= deadline_at`;
- no verified pre-deadline HQA terminal outcome exists;
- the exact current all-clear document verifies under the same lock/CAS;
- every applicable producer is closed and none is unknown;
- no successful finalization, result, Gate 3, or Task completion has already committed;
- the target Attempt is not already terminal.

It appends `attempt_budget_exceeded`, transitions Attempt to `terminal`, sets `terminal_outcome="budget_exceeded"`, and increments Task version once.

The initial Task policy is `close_latest_attempt_task`. `TerminalizeTaskForBudget` is legal only when the budget-exceeded Attempt is the latest Attempt, every Attempt is terminal, Task has no successful terminal decision, and the exact Attempt terminal event is supplied. It appends `task_budget_exceeded` and transitions Task to terminal with the same outcome. A later `ContinueResearch` is therefore forbidden for this v1 policy. A future continue-after-budget policy requires a new policy version and MUST be defined before activation.

`budget_exceeded` evidence is never eligible as completed result, candidate, Gate 2, Gate 3, promotion, release, or provenance evidence.

## 17. Retry, Reconciliation, and Crash Recovery

- Before retrying after timeout, connection loss, append-then-ack loss, or process failure, query the v3 operation receipt by original operation ID. Contract 2 MUST add `operation_receipt(operation_id)`; absence in v2 is not inherited.
- Retry only with the original operation ID and exact canonical command bytes.
- Storage failure remains existing `workflow_storage_unavailable` unless a separately implemented and fault-tested `workflow_durability_unknown` contract lands.
- A worker crash before a phase append repeats the phase check.
- A crash after phase append replays the receipt and performs no duplicate append.
- A crash after durable stop Command creation but before HQA binding discovers the exact deterministic Command and appends the missing binding.
- A crash after external stop effect but before acknowledgement remains reconciling and observes/reuses the exact stop identity.
- Lease theft or expiry cannot bypass the HQA deadline barrier; a new lease holder rechecks eligibility.
- Projection corruption is rebuilt from verified journal replay. Journal corruption disables dispatch and success finalization for affected owner scope and requires audit.
- Scheduler hints and scanner projections are rebuildable from bindings and events.

## 18. Errors

Stable Contract 2 errors:

```text
workflow_invalid_budget
workflow_budget_policy_not_found
workflow_budget_policy_digest_mismatch
workflow_budget_deadline_overflow
workflow_budget_unavailable
workflow_budget_binding_conflict
workflow_budget_already_claimed
workflow_budget_phase_already_recorded
workflow_budget_integrity_failure
workflow_budget_not_expired
workflow_budget_dispatch_suppressed
workflow_budget_reconcile_required
workflow_budget_producer_open
workflow_budget_producer_unknown
workflow_budget_observation_stale
workflow_budget_cursor_gap
workflow_budget_terminal_ineligible
workflow_stale_version
workflow_terminal_immutable
workflow_idempotency_conflict
workflow_storage_unavailable
workflow_journal_corrupt
```

Validation and policy failures occur before acceptance with zero Task/Attempt/binding/timer/Platform writes. Integrity failure is fail-closed `stop_and_audit`. Cancellation or deadline does not erase already committed evidence. Unknown producer or stop status is reconciling, never success and never terminal budget evidence.

## 19. Hermetic Ports

```text
ClockPort.now_utc() -> canonical UTC
BudgetPolicyPort.get(id,version,digest) -> policy
WorkflowAuthorityV3.apply(command) -> receipt
WorkflowAuthorityV3.operation_receipt(operation_id) -> receipt|null
DeadlineEligibilityPort.evaluate(attempt_ref,binding_digest,expected_version) -> eligible|expired|claimed|terminal|unknown
DeadlineSchedulerPort.arm(enforcement_id,deadline_at)
DeadlineSchedulerPort.cancel(enforcement_id)
BudgetScannerPort.scan(after_cursor,limit) -> page
BudgetScannerCheckpointStore.commit(page_cursor,observed_digests)
StopCoordinatorPort.claim_and_stop(stop_action,exact_run_ref) -> layered observation
LayeredStopObserverPort.observe(exact_refs) -> LayeredStopReceipt
ProducerObservationPort.observe(authority_id,attempt_ref,claim_fence) -> AuthorityProducerObservationV1
ArtifactEligibilityPort.evaluate(attempt_ref) -> eligible|ineligible|unknown
WorkspaceBudgetProjectionPort.project(snapshot,events)
```

Fakes inject clock, overflow, pre-append failure, acknowledgement loss, projection failure, scheduler loss/duplication, scanner cursor gap, stale CAS, lease theft, stop transport loss, delayed Run link, delayed outbox, producer outage, and journal corruption. Production ports must not import candidate review, promotion, release, broker, order, Git, or public-route clients.

## 20. Projection and Workspace Wire Contract

The workspace surface is a disposable projection over HQA v3 and the existing PostgreSQL command follow spine. It never owns deadline, completion, stop, or terminal decisions.

### 20.1 `WorkspaceBudgetProjectionV1`

Every available budget projection is a closed object with exactly:

```text
schema_version:1
budget_contract_status:"available"
task_ref:TaskRef
attempt_ref:AttemptRef
attempt_number:PositiveInt32
budget:TaskBudgetV1
budget_digest:Sha256
binding_digest:Sha256
policy:{id:Identifier,version:PositiveInt32,digest:Sha256}
accepted_at:CanonicalUtc
deadline_at:CanonicalUtc
enforcement:{id:EvidenceRef,phase:"bound"|"claimed"|"dispatch_suppressed"|"stop_control_bound"|"stop_observed"|"reconciling"|"terminal"|"already_terminal",phase_sequence:NonNegativeInt63,last_event_ref:EventRef|null}
run_ref:RunRef|null
stop_action_ref:ActionRef|null
stop_command_ref:CommandRef|null
all_clear_digest:Sha256|null
terminal_outcome:"budget_exceeded"|null
preserved_terminal_outcome:"completed"|"failed"|"cancelled"|"stopped"|"domain_gate_rejected"|"intent_expired"|null
provenance:"authoritative_hqa"
```

Legacy Attempts use exactly `{"schema_version":1,"budget_contract_status":"legacy_unbudgeted","task_ref":TaskRef,"attempt_ref":AttemptRef,"budget":null,"provenance":"authoritative_hqa"}`. Impossible nullability combinations fail closed. UI remaining time is `max(0, deadline_at-display_clock)` and is never persisted or used as authority.

### 20.2 Snapshot envelope

The existing workspace command fields remain optional and unchanged. The additive closed snapshot envelope is:

```text
schema_version:1
workspace_id:PlatformIdentifier
owner_user_id:Identifier
workspace_ref:TaskRef-compatible workspace ref
snapshot_workspace_cursor:NonNegativeInt63|null
commands:[existing WorkspaceCommandProjection]
tasks:[TaskRef]
attempts:[AttemptRef]
runs:[RunRef]
task_progress_by_ref:Record<TaskRef,Contract1TaskProgressProjection>|null
budget_by_attempt_ref:Record<AttemptRef,WorkspaceBudgetProjectionV1>|null
source_checkpoints:{command:WorkspaceSourceCheckpointV1|null,hqa_v3:WorkspaceSourceCheckpointV1|null}
capabilities:{task_progress_read_schema:1|null,wall_clock_budget_read_schema:1|null,wall_clock_budget_write_schema:1|null,wall_clock_budget_enforcement:1|null}
authority_health:{command:"healthy"|"degraded"|"resync_required"|"corrupt",hqa_v3:"healthy"|"degraded"|"resync_required"|"corrupt"}
```

`workspace_ref` uses exact `workspace:` plus `Identifier`; the notation above does not permit `task:`. Record keys equal the embedded refs and are sorted lexicographically. A snapshot never mixes owners or workspaces. A null capability or projection means unsupported/unavailable, not zero.

### 20.3 Follow page and discriminated events

The follow request carries independent `after_workspace_cursor:NonNegativeInt63|null` and `after_hqa_checkpoint:WorkspaceSourceCheckpointV1|null` plus `limit:1..1000`. The response is:

```text
schema_version:1
workspace_id:PlatformIdentifier
command_events:[existing WorkspaceFollowEvent]
task_events:[WorkspaceBudgetFollowEventV1]
next_workspace_cursor:NonNegativeInt63|null
next_hqa_checkpoint:WorkspaceSourceCheckpointV1|null
has_more:{command:boolean,hqa_v3:boolean}
resync_required:{command:boolean,hqa_v3:boolean}
problems:[WorkspaceProblemV1]
```

`WorkspaceBudgetFollowEventV1` is a closed discriminated union. Common exact fields are `source_authority:"hqa_workflow_v3"`, `source_event_id:EventRef`, `source_event_digest:Sha256`, `type`, `task_ref`, `attempt_ref`, `task_version:PositiveInt63`, `binding_digest:Sha256`, `enforcement_id:EvidenceRef`, `occurred_at:CanonicalUtc`. `type` is exactly one of `task.budget_deadline_claimed|task.budget_dispatch_suppressed|task.budget_stop_control_bound|task.budget_stop_observed|task.budget_reconcile_started|task.budget_producer_observed|task.attempt_budget_exceeded|task.budget_already_terminal|task.task_budget_exceeded`; its `data` is the exact metadata-only event data from section 9. Unknown discriminants require HQA resnapshot and are never coerced into numeric command events.

### 20.4 Source checkpoint

`WorkspaceSourceCheckpointV1` is closed:

```text
schema_version:1
source_authority:"platform_command_ledger_v1"|"hqa_workflow_v3"
owner_user_id:Identifier
workspace_ref:workspace ref
last_sequence:NonNegativeInt63
last_source_event_id:EventRef|null
last_source_event_digest:Sha256|null
last_record_sha256:Sha256|null
checkpoint_digest:Sha256
```

At sequence zero the three last fields are null. Otherwise all are non-null. `checkpoint_digest` excludes itself. Command and HQA checkpoints advance independently. Projector persistence atomically commits checkpoint, `(source_authority,source_event_id,source_event_digest)` dedupe row, derived projection, and optional follow outbox. Gap, regression, owner/workspace mismatch, digest reuse, hash mismatch, or unsupported event sets `resync_required` and publishes no later HQA event until verified rebuild.

### 20.5 Problem envelope

`WorkspaceProblemV1` is closed and safe to expose:

```text
schema_version:1
type:"about:blank"
title:"Workspace source problem"
status:409|503
code:"workspace_budget_source_conflict"|"workspace_budget_cursor_gap"|"workspace_budget_schema_unsupported"|"workspace_budget_authority_unavailable"|"workspace_budget_integrity_failure"
source_authority:"hqa_workflow_v3"|"platform_command_ledger_v1"
owner_user_id:Identifier
workspace_ref:workspace ref
retryable:boolean
resnapshot_required:boolean
observed_at:CanonicalUtc
evidence_digest:Sha256|null
```

It contains no raw exception, prompt, payload, provider body, secret, path, or unrestricted evidence. `409` is used for conflict/gap/schema/integrity; `503` only for authority unavailable. Integrity and cursor problems set `resnapshot_required=true`; availability may be retryable without resnapshot.

### 20.6 Rebuild

Deleting every workspace budget/progress projection, dedupe row, and follow outbox then replaying the v3 journal from sequence 1 MUST byte-rebuild Contract 1 progress completion and Contract 2 budgets. The v2 projection is not an input. A crash before the atomic projector commit replays; a crash after commit is deduped; checkpoint-first and projection-first partial states are not representable.

## 21. Activation and Rollback Gates

Private capabilities:

```text
wall_clock_budget_read_schema=1
wall_clock_budget_write_schema=1
wall_clock_budget_enforcement=1
```

Rollout order:

1. Strict v2 action dual reader and v3 HQA parser/reducer with writers off.
2. Sealed v2-to-v3 migration and replay-only projection.
3. Shadow calculation emitted only to operational logs as `shadow_budget_observed`; no binding, timer, claim, state change, or stop.
4. Hermetic active enforcement with all producer adapters fake but exhaustive.
5. Restart, cursor, lease-loss, and acknowledgement-loss canary.
6. Private single-owner canary with real durable producer adapters and stop coordinator.

Activation requires:

- Contract 1 green;
- exact committed policy digest;
- v2 backup/restore and v3 semantic migration proof;
- homogeneous worker capability epoch;
- every lease, dispatch, redispatch, and success-finalization path instrumented with deadline eligibility checks;
- persisted scanner cursor and zero unowned overdue bindings;
- all closed producer-matrix adapters healthy;
- production durable stop coordinator and outcome authority healthy;
- exact parser/snapshot parity for transport terminal vocabulary;
- no mode that accepts a budget without binding/enforcement;
- safety assertions unchanged.

Rollback after v3 writes follows section 6.3.

## 22. Exhaustive Test Matrix

### 22.1 Schema and canonicalization

- Exact fields, missing/extra fields, duplicate keys, wrong built-in types, booleans-as-int, strings/floats/decimals, non-finite values, identifier/ref/digest bounds.
- `wall_clock_seconds` at `0,1,2592000,2592001`, and huge integers.
- Reserved fields as null and exact reserved objects; reject every non-null total, amount, currency, wrong unit, enforcement, type, or extra field.
- Shared Python/TypeScript canonical bytes and digest golden vectors for budget, binding, action, command, observation, all-clear, and identities.

### 22.2 Timestamp and arithmetic

- Exact six-digit UTC grammar; reject offsets, naive values, leap seconds, lowercase z, missing/short/long fractions, whitespace, invalid calendar dates.
- UTC date/month/year rollover, leap year, maximum date, checked overflow.
- `now` one microsecond before, equal to, and one microsecond after deadline.
- Wall-clock jumps backward/forward affect wake timing but not stored deadline or comparison rules.

### 22.3 Migration

- V1 Platform actions retain exact bytes/digests/routes; v2 strict parser rejects v1 and vice versa outside dispatcher.
- V2 HQA journals/backups remain exact and replay under unchanged reducer.
- Migration rejects corrupt sequence, owner, timestamp, event ID, hash chain, duplicate key, unknown event, insecure path, or quota overflow.
- V2 semantic projection equals v3 migrated projection for every legacy fixture.
- Mixed legacy-unbudgeted and new budgeted Tasks replay deterministically.
- No downgrade after first v3 write.

### 22.4 Acceptance and binding

- Atomic Task/Attempt/event/binding/receipt creation; injected failure leaves zero partial facts.
- Acceptance timestamp is exactly containing `research_started|research_continued.occurred_at`.
- Same-ID replay preserves acceptance/deadline; conflict changes nothing.
- Continue creates a fresh binding/deadline; retries/re-leases do not; no rollover.
- One binding per Attempt and one Attempt per binding.
- Policy missing/mismatch/unsupported fails before append.

### 22.5 Barriers and races

- Every dispatch, lease, re-lease, Run binding, provider evidence, result link, Gate 3, Attempt completion, and Task completion path invokes the deadline barrier.
- Completion terminal event at `< deadline` wins before or after delayed observation.
- Completion at `== deadline` and `> deadline` loses.
- Claim commits while external pre-deadline effect is unobserved: remains reconciling until exact evidence resolves.
- Late mutable/provider/worker timestamps never establish pre-deadline success.
- Claim and completion CAS permutations yield one deterministic result.

### 22.6 Scheduler and scanner

- Early, exact, late, duplicate, and missing scheduler wakes.
- Scheduler crash before/after claim submission and after lost response.
- Scanner restart at every cursor commit boundary; no skipped or duplicated semantic effect.
- Cursor gap, regression, head reset, changed digest, authority outage, and journal corruption stop and audit.
- Scanner and barrier race produce one claim.

### 22.7 Dispatch suppression

- Expired before Command creation: zero Command/outbox/dispatch.
- Expired queued: durable suppression/cancellation through command authority, zero external dispatch.
- Expired leased before dispatch marker: lease cannot dispatch.
- Expired after dispatch marker: no retry/re-lease; reconcile/stop exact effect.
- Lease steal and expired lease cannot renew budget.

### 22.8 Exact-Run stop

- One deterministic action and durable control Command under arbitrary retries/processes.
- Stop bind crash windows before/after Platform command commit and HQA append.
- Stop acknowledgement loss, timeout, observer outage, already completed/failed/cancelled Run, wrong Run, newly different Run, and unknown Attempt/job layers.
- Run-only confirmed stop never terminalizes HQA.
- Existing LayeredStopReceipt public dictionary and state transitions remain snapshot-compatible.
- Fake adapter cannot satisfy production activation test.

### 22.9 No-Run producer matrix

For every matrix row: closed, open, unknown, unavailable, stale, cursor-gapped, changed after observation, and inapplicable-by-policy cases.

Mandatory adversarial cases:

- delayed outbox row appears after an earlier empty query;
- active lease omitted by stale snapshot;
- job registered after scan but before terminal CAS;
- Run link appears after “no Run” observation;
- result/artifact writer remains open;
- unsupported producer authority is possible;
- producer observation has cursor before claim fence;
- producer closes exactly at deadline;
- all-clear document missing/duplicate/unsorted/mismatched observation;
- all-clear passes then Task version changes before append.

Only a fresh complete matrix yields one `attempt_budget_exceeded` event.

### 22.10 Terminal vocabulary and eligibility

- Update and snapshot-test exact HQA Attempt/Task outcome parsers, reducers, snapshots, CLI serializers, workspace TypeScript types, and UI renderers for `budget_exceeded`.
- Prove `CompleteAttempt`, `CompleteTask`, `ResolveReconcile`, `ObserveStop`, transport Command, Hermes Run, and LayerStatus parsers reject `budget_exceeded` where not explicitly allowed.
- Backend/frontend terminal Command parity for all seven canonical ledger states; `delivered` and `outcome_unknown` continue polling.
- `budget_exceeded` cannot satisfy result, candidate, Gate 2, Gate 3, promotion, release, or real-provenance validators.

### 22.11 Crash/property tests

Inject a crash before and after every append, fsync, projection write, scheduler arm/cancel, scanner checkpoint, Platform control-command commit, stop call, stop observation, producer observation, all-clear assembly, Attempt terminal append, and Task terminal append.

Property tests over arbitrary retries, crashes, reordered observations, scanner duplication, worker lease theft, and clock wake jitter prove:

- one immutable binding;
- one deadline claim;
- one stop identity and at most one external stop effect;
- at most one phase event per semantic observation;
- one Attempt terminal event;
- one optional Task terminal event;
- fixed authoritative facts produce byte-identical replay and terminal result.

### 22.12 Privacy and forbidden effects

- Persisted files and public projections contain no prompt, payload body, reasoning, tool output, provider body, secret, unrestricted evidence body, model/provider ID, mutable path, token usage, or monetary value.
- Dependency spies prove zero candidate review, Gate mutation, promotion, release, Git, subprocess, broker, order, public route, public flag, `kill_switch`, `live_trading_enabled`, or `release_authorized` mutation.
- Prove no Anthropic/provider task-budget, token-budget, pricing, or pacing parameter is emitted.

## 23. Explicit Non-Goals and Safety Assertions

Contract 2 does not:

- add or authorize public/browser/chat writes;
- approve, reject, register, or promote candidates;
- satisfy Gate 1, Gate 2, or Gate 3;
- submit, cancel, replace, or modify broker orders;
- add live trading;
- turn a deadline, stop, or budget outcome into provenance or authorization;
- reinterpret a transport terminal state as HQA completion;
- reinterpret a Run stop as Attempt or Task terminality;
- emit provider-native token, cost, or task budgets;
- prepare, commit, merge, or push Git changes.

Standing assertions remain:

```text
kill_switch=true
live_trading_enabled=false
public write standing default OFF
release_authorized=false
```

## 24. Direct Authority Anchors

Implementation must stay aligned with these direct sources:

- `/Users/sunyibo/programs/Hermes-quant-agent/hqa/workflow_contract.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/hqa/workflow_authority.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/hqa/agent_workspace_states.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/hqa/hermes_run_adapter.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/quant_system/hermes/agent_workspace_actions.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/quant_system/hermes/submission_saga.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/quant_system/hermes/command_ledger.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/quant_system/hermes/run_stop_port.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/quant_system/hermes/workspace_observe.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/frontend/lib/hermes/workspaceClient.ts`

Any implementation divergence requires a new reviewed contract revision, not an implicit reinterpretation.
