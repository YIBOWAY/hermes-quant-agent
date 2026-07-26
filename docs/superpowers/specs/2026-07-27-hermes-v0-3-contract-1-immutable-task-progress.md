# Contract 1: Immutable Evidence-Backed Task Progress

**Status:** normative implementation specification  
**Contract:** Hermes v0.3 Contract 1  
**Authority:** HQA workflow journal schema v2  
**Scope:** local, single-operator research Tasks  
**Safety posture:** read projection plus private HQA command; no public write, approval, promotion, broker, or trading authority

## 1. Purpose and Normative Language

This contract adds honest milestone progress to feature-enabled HQA Research Tasks without changing the existing research-plan lifecycle, Task/Attempt/Run relationships, transport Command lifecycle, Gate semantics, or trading safety posture.

The terms **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, and **MAY** are normative.

Contract 2 budgets and Contract 3 comparisons are outside this document. Contract 2 depends on the identity, ownership, compare-and-swap, replay, and terminal-honesty semantics defined here.

## 2. Existing Authority Preserved

The following remain authoritative and separate:

- HQA's append-only workflow journal owns Task, Attempt, execution progress, Task state, and Task terminal outcome.
- The PostgreSQL command ledger owns transport Command state.
- Hermes Run authority owns Run state.
- Gate 1, Gate 2, Gate 3, approval, result, release, and promotion authorities retain their existing exact-reference and digest-bound semantics.
- Workspace projections are disposable read models, never business journals.

Existing relations remain:

- Workspace `1:N` Tasks.
- Task `1:N` Attempts.
- Attempt `0..1` submission Command and `0..1` Run.
- Run `0..N` result links and control Commands.
- Existing Task states remain `draft|plan_proposed|awaiting_plan_confirmation|awaiting_formula_confirmation|ready|running|awaiting_domain_gate|terminal`.
- Hermes Run terminal states remain exactly `completed|failed|cancelled`.

### 2.1 PostgreSQL ledger state versus public observation category

The authoritative PostgreSQL `CommandState` union is exactly:

```text
queued | leased | delivered | outcome_unknown | succeeded | failed | cancelled
```

Its terminal states are exactly:

```text
succeeded | failed | cancelled
```

`delivered` and `outcome_unknown` are nonterminal. `rejected` and `timed_out` are public observation/result categories only where an existing adapter explicitly maps a rejection or client-side wait expiry. They MUST NOT be inserted into `hermes_commands.state`, `hermes_command_events.from_state`, or `hermes_command_events.to_state`, and MUST NOT be treated as PostgreSQL ledger states without a separately versioned ledger migration.

A workspace/public client MAY use the broader terminal observation set `succeeded|failed|cancelled|rejected|timed_out` for presentation or polling termination, but the adapter MUST retain the source category and MUST NOT claim that `rejected` or `timed_out` came from the ledger. Contract tests MUST separately test the seven-state ledger union, the three ledger terminals, and the broader public observation categories.

No Task completion is inferred from any ledger state or public observation category.

## 3. Progress Semantics

A feature-enabled Task owns exactly one immutable ordered `execution_progress_plan`, created atomically with the Task and first Attempt in the authoritative `research_started` record.

This plan is distinct from the existing mutable, Run-sourced research plan represented by `plan_version`, `plan_digest`, `plan_source_ref`, `ProposePlan`, and `RevisePlan`. Those existing fields and commands retain their meanings.

Progress is replay-derived only:

```text
total_steps = count(execution_progress_plan.steps)
completed_steps = count(unique accepted step_completed records)
next_step_id = step at ordinal completed_steps + 1, or null
is_complete = completed_steps == total_steps
display_ratio = {numerator: completed_steps, denominator: total_steps}
```

Uniqueness is exactly `(task_ref, execution_progress_plan_digest, step_id)`. Completion is strict prefix order: only ordinal `completed_steps + 1` may complete.

The ratio means declared milestones completed. It is not percent effort, elapsed time, provider work, confidence, tokens, cost, or research difficulty.

The following MUST NOT modify progress: clocks or timers; polling or refresh cadence; heartbeats, retries, leases, or workers; model/provider activity, tokens, costs, prompts, or tool calls; Run duration or Command state; approval, Gate, result, promotion, release, or trading state.

`N/N` MUST NOT terminalize a Task or satisfy Attempt completion, provider evidence, result linkage, domain gates, Gate 2, Gate 3, approval, release, or promotion. A feature-enabled Task terminal outcome `completed` additionally requires `N/N`, while every existing success gate remains required. Existing non-success outcomes may terminalize at `k/N` and freeze progress there.

Legacy Tasks are never backfilled. They project `progress=null` and `progress_contract_status="legacy_unavailable"`.

## 4. Schema-v2 Dual Reader and Capabilities

Contract 1 remains within workflow command and journal `schema_version: 2`.

- Pre-feature schema-v2 commands and records MUST retain canonical bytes and digests.
- The reader MUST accept the exact legacy `research_started.data` shape and the exact feature shape, which is the legacy field set plus `execution_progress_plan`.
- The closed command union gains `workflow.complete_plan_step`.
- The closed event reducer gains `step_completed`.
- Every other unknown command kind, event kind, field, or shape remains an error.
- Changing the global authority version to `3` for Contract 1 is forbidden absent a separately sealed migration.

This is shape dispatch, not permissive extra-field handling.

Independent deployment-owned capabilities are:

```json
{"task_progress_read_schema":1,"task_progress_write_schema":1}
```

Missing or `null` means unsupported. A configured value other than integer `1` MUST fail startup. Readers deploy first. With writes enabled, new `workflow.start_research` commands MUST contain `execution_progress_plan`; with writes disabled they MUST retain the exact legacy shape and reject that field. `workflow.complete_plan_step` returns `workflow_progress_write_disabled` unless writes are enabled. Disabling writes after feature records exist MUST preserve replay and reads. No untrusted request may select a capability.

## 5. Common Types and Exact Bounds

`Identifier` is ASCII matching `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. `Sha256` is lowercase `[0-9a-f]{64}`. Existing refs retain their exact prefixes and identifier grammar: `task:`, `attempt:`, `run:`, `workspace:`, and `session:`. `payload_ref` remains `payload:sha256:` plus a lowercase SHA-256.

Input timestamps use the existing RFC 3339 grammar with timezone and at most six fractional digits. HQA normalizes authority timestamps to `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Completion commands contain no timestamp; HQA assigns `occurred_at` under the authority lock.

Schema-1 limits are fixed:

- steps per plan: `1..64`;
- `step_id`: `1..128` ASCII characters under `Identifier`;
- label: `1..2,000` UTF-8 bytes;
- evidence reference: `1..256` ASCII characters matching `[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}`;
- evidence `allowed_kinds`: `0..8` unique closed values;
- plan canonical bytes including `plan_digest`: at most `32,768`;
- completion command canonical bytes: at most `8,192`;
- progress entries per workspace snapshot/page: at most `1,000`;
- task follow events per page: `1..1,000`.

Existing authority limits remain: 64 KiB per record, 64 MiB journal, 100,000 events, positive Task versions `1..2^63-1`, and page limit at most 1,000. Boolean values MUST NOT pass integer validation.

A label must contain valid Unicode scalars, at least one non-whitespace character, no control character, no leading/trailing whitespace, and no more than 2,000 UTF-8 bytes. Unicode normalization is forbidden; producers SHOULD use NFC, but submitted scalars are digest-significant.

## 6. Canonical JSON and Digests

All Contract 1 digests use this profile:

1. Parse UTF-8 with duplicate-key rejection at every object level.
2. Reject invalid UTF-8, lone surrogates, NaN, Infinity, negative-zero numeric tokens, floats, and non-integer numbers.
3. Validate the exact closed schema before serialization.
4. Sort object keys by Unicode code point; preserve array order.
5. Use compact `,` and `:` separators and no insignificant whitespace.
6. Emit Unicode directly as UTF-8 with `ensure_ascii=false` and `allow_nan=false`.
7. Emit booleans and null as lowercase JSON literals; integers are base-10 with no sign or leading zero.
8. Append no newline and no byte-order mark.

The progress plan digest excludes `plan_digest` and hashes exactly:

```json
{"schema_version":1,"steps":[...validated ordered steps...]}
```

Golden canonical bytes:

```json
{"schema_version":1,"steps":[{"evidence_policy":"exact_positive","evidence_requirement":{"allowed_kinds":["workflow_event"],"required":true},"label":"Plan accepted","ordinal":1,"step_id":"plan.accepted"}]}
```

Expected SHA-256:

```text
e51966bdc27593ae0b1ae8a973839734d65a7956f80f3a88f35b74fdf471a1b1
```

Python and TypeScript implementations MUST share ASCII, non-ASCII, boundary, and mutation golden vectors byte-for-byte.

## 7. Execution Progress Plan Schema

Exact shape:

```json
{
  "schema_version": 1,
  "steps": [{
    "step_id": "plan.accepted",
    "ordinal": 1,
    "label": "Plan accepted",
    "evidence_policy": "exact_positive",
    "evidence_requirement": {"required":true,"allowed_kinds":["workflow_event"]}
  }],
  "plan_digest": "e51966bdc27593ae0b1ae8a973839734d65a7956f80f3a88f35b74fdf471a1b1"
}
```

Top-level and step fields are exact. `evidence_policy` is `exact_positive|none`. `evidence_requirement` is always explicit. For `exact_positive`, `required=true` and `allowed_kinds` contains `1..8` unique closed kinds. For `none`, it is exactly `{"required":false,"allowed_kinds":[]}`.

`none` is permitted only for `task.accepted` and `operator.note.recorded`. Each may occur at most once; `task.accepted`, if present, is ordinal 1. Such completion records only the named administrative action and MUST NOT claim research, evidence generation, Run success, or approval. Every other user-visible milestone requires `exact_positive`.

A valid plan has unique IDs and ordinals, array-order ordinals exactly `1..N`, no duplicate `casefold(trim(label))` validation key, and no timestamps, percentages, durations, budgets, provider/model/session IDs, tokens, prompts, payload bodies, results, approvals, Gate state, promotion, release, trading state, mutable paths, or vague timer/activity milestones. Validation MUST NOT rewrite input.

Closed plan failure reasons are `empty_plan|too_many_steps|invalid_identifier|invalid_ordinal|duplicate_step_id|duplicate_ordinal|invalid_label|duplicate_semantic_milestone|forbidden_evidence_policy|invalid_evidence_requirement|forbidden_plan_content|digest_mismatch|plan_too_large`.

## 8. Command Schemas

The feature-enabled `workflow.start_research` is the exact legacy schema-v2 document plus one required field:

```json
{
  "schema_version": 2,
  "kind": "workflow.start_research",
  "operation_id": "op-1",
  "workspace_ref": "workspace:local",
  "managed_session_ref": "session:local",
  "payload_ref": "payload:sha256:<64-lower-hex>",
  "intent_expires_at": "2026-07-27T12:00:00.000000Z",
  "execution_progress_plan": {"schema_version":1,"steps":[{"step_id":"task.accepted","ordinal":1,"label":"Task accepted","evidence_policy":"none","evidence_requirement":{"required":false,"allowed_kinds":[]}}],"plan_digest":"<sha256>"}
}
```

Existing Task/Attempt derivation, payload binding, expiry, operation digest, and receipt semantics remain unchanged. The plan is validated before append and participates in the canonical command digest.

`workflow.complete_plan_step` is exact:

```json
{
  "schema_version": 2,
  "kind": "workflow.complete_plan_step",
  "operation_id": "progress-op-1",
  "task_ref": "task:<identifier>",
  "expected_version": 4,
  "step_id": "plan.accepted",
  "progress_plan_digest": "<sha256>",
  "attempt_ref": null,
  "run_ref": null,
  "evidence_ref": "evidence:<identifier>",
  "evidence_digest": "<sha256>"
}
```

All shown fields are required, including nullable fields. Missing, extra, or unknown fields reject. The command accepts no timestamp, percentage, duration, provider/model state, token count, terminal outcome, approval, Gate, promotion, release, or trading field.

The Task must exist and be owner-scoped; the digest must match its immutable plan; the step must exist and be next. A non-null Attempt must belong to the Task. A non-null Run requires an Attempt and must already be exactly bound to it. Evidence ref and digest are both non-null or both null. `exact_positive` requires both; `none` requires both null.

## 9. Evidence Observation and Validation

The completion command never embeds evidence bodies. `CompletionEvidencePort.observe(ref,digest)` returns exact metadata:

```json
{
  "schema_version": 1,
  "evidence_ref": "evidence:<identifier>",
  "evidence_digest": "<sha256>",
  "kind": "workflow_event",
  "source_authority": "hqa",
  "source_event_id": "event:<sha256>",
  "source_event_digest": "<sha256>",
  "task_ref": "task:<identifier>",
  "attempt_ref": null,
  "run_ref": null,
  "observed_outcome": "positive",
  "observed_at": "2026-07-27T12:00:00.000000Z"
}
```

Fields are exact. `kind` is `workflow_event|provider_evidence|result_receipt|domain_gate_receipt|run_terminal_receipt`. `observed_outcome` is `positive|negative|unknown`.

Evidence is positive only when ref and digest exactly match; kind is allowed; source authority is deployment-allowlisted rather than caller-supplied; event ID/digest are immutable; Task/Attempt/Run bindings match; outcome is `positive`; the kind-specific predicate passes; and no authority fact has revoked or superseded it at validation time.

Kind predicates are: accepted HQA workflow predicate; existing provider-evidence ref bound to the Attempt and accepted by HQA; existing result link; domain gate outcome `passed`; or exact bound Run authoritative state `completed`.

Absent, stale, revoked, cross-owner, cross-Task, cross-Attempt, cross-Run, wrong-kind, ref/digest-mismatched, negative, unknown, failed, cancelled, rejected, timed-out, stopped, partial, provider-refusal, `delivered`, idle, or `outcome_unknown` observations never append `step_completed`. Here `rejected` and `timed_out` are observation categories, not ledger states. A provider label, callback, populated field, or model assertion is not evidence.

Production rejects fixture/sample evidence. Hermetic tests use a separate port and mark resulting projections `sample_fixture`.

## 10. Accepted Journal Event

The existing schema-v2 envelope remains exact:

```json
{
  "schema_version":2,"sequence":12,"event_id":"event:<sha256>",
  "operation_id":"progress-op-1","operation_digest":"<sha256>",
  "owner_user_id":"<identifier>","task_ref":"task:<identifier>",
  "attempt_ref":null,"task_version":5,"event_type":"step_completed",
  "occurred_at":"2026-07-27T12:00:00.000000Z","data":{},
  "previous_record_sha256":"<sha256-or-null>","record_sha256":"<sha256>"
}
```

For `step_completed`, `data` is exact:

```json
{
  "step_id":"plan.accepted","step_ordinal":1,
  "progress_plan_digest":"<sha256>","attempt_ref":null,"run_ref":null,
  "evidence_ref":"evidence:<identifier>","evidence_digest":"<sha256>",
  "evidence_kind":"workflow_event","evidence_source_authority":"hqa",
  "evidence_source_event_id":"event:<sha256>",
  "evidence_source_event_digest":"<sha256>"
}
```

For a `none` step, every evidence field is null. One accepted completion increments Task version once and appends one record. Replay revalidates plan digest, identity, ordinal prefix, evidence cardinality, and uniqueness; violation is `workflow_journal_corrupt`. `research_continued`, `plan_proposed`, and `plan_revised` MUST NOT replace the execution plan.

## 11. Idempotency, CAS, Terminal Races, and Recovery

The operation namespace remains `(owner_user_id,operation_id)`. Same identity and canonical digest returns the original receipt with `replayed=true`, appends nothing, and changes no version. Same identity and different digest is `workflow_idempotency_conflict`. Rejected commands do not reserve the ID.

A different operation targeting an already-completed semantic step returns `workflow_step_already_completed` with safe details `requested_operation_id`, `original_operation_id`, `original_event_id`, `task_ref`, `task_version`, `step_id`, `completed_steps`, and `total_steps`; it appends nothing and does not reserve the requested ID.

Under the single HQA authority lock, processing order is:

1. Load, strictly verify, and replay the journal.
2. Resolve same-operation replay/conflict.
3. Resolve Task and reject terminal Task immutability.
4. Compare expected version.
5. Validate immutable plan digest and membership.
6. Detect semantic duplicate, then validate next ordinal.
7. Validate exact Task/Attempt/Run/evidence bindings.
8. Build `current+1` record with authority timestamp.
9. Apply reducer to a copy and enforce quotas.
10. Append and fsync journal, then update disposable projection.
11. Return the receipt.

A completion that locks first may append; a following terminal command must use the new version. A terminal command that locks first makes the Task immutable and completion appends nothing. Concurrent same-version writers cannot both succeed. After ordinal `k`, a concurrent `k+1` command is stale and must be rebuilt with a new operation ID.

Task outcome `completed` at `k/N` returns `workflow_progress_incomplete`; non-success terminal outcomes remain legal under existing gates.

After timeout, connection loss, append-then-ack loss, storage ambiguity, or process failure, the caller MUST query `operation_receipt(original_operation_id)` before retrying and retry only with the original ID and byte-identical command. Existing storage failures remain `workflow_storage_unavailable`; this contract does not invent `workflow_durability_unknown`. Projection corruption is repaired only from verified journal replay; journal corruption is never hidden. Unknown current events remain corruption.

## 12. HQA Read Projection

Available projection is exact:

```json
{
  "task_ref":"task:<identifier>","progress_contract_status":"available",
  "progress_plan_schema_version":1,"progress_plan_digest":"<sha256>",
  "steps":[{"step_id":"plan.accepted","ordinal":1,"label":"Plan accepted","evidence_policy":"exact_positive","completed_event_id":null,"completed_at":null}],
  "completed_steps":0,"total_steps":1,"next_step_id":"plan.accepted",
  "is_complete":false,"display_ratio":{"numerator":0,"denominator":1},
  "task_state":"draft","terminal_outcome":null,"task_version":1,
  "provenance":"authoritative_hqa"
}
```

Legacy projection is exact:

```json
{"task_ref":"task:<identifier>","progress_contract_status":"legacy_unavailable","progress":null,"task_state":"draft","terminal_outcome":null,"task_version":1,"provenance":"authoritative_hqa"}
```

Production accepts only `authoritative_hqa`. `sample_fixture` is legal only in hermetic applications/tests and remains visibly labeled.

## 13. Workspace Snapshot and Follow Wire Contract

Existing `WorkspaceCommandProjection`, `tasks?:string[]`, `attempts?:string[]`, `runs?:string[]`, and `snapshot_workspace_cursor?:number` remain unchanged.

Snapshot adds optional:

```ts
task_progress_by_ref?: Record<string, TaskProgressProjection>
task_progress_checkpoint?: WorkspaceSourceCheckpoint
progress_capabilities?: { read_schema: 1 | null; write_schema: 1 | null }
```

Absence means unsupported and never licenses synthesis from Task IDs. Map keys equal value `task_ref`, serialize sorted, contain no more than 1,000 entries, and refer only to Tasks in the snapshot.

Follow pages add optional:

```ts
task_events?: WorkspaceTaskFollowEvent[]
task_progress_by_ref?: Record<string, TaskProgressProjection>
task_progress_checkpoint?: WorkspaceSourceCheckpoint
progress_capabilities?: { read_schema: 1 | null; write_schema: 1 | null }
```

The existing numeric command `event_id` and cursor remain command-only. HQA string IDs never occupy that field and Task events require no `command_id`.

Contract 1 follow event is exact:

```json
{
  "source_authority":"hqa_workflow_v2","source_event_id":"event:<sha256>",
  "source_event_digest":"<sha256>","type":"task.step_completed",
  "task_ref":"task:<identifier>","task_version":5,"step_id":"plan.accepted",
  "step_ordinal":1,"completed_steps":1,"total_steps":4,
  "attempt_ref":null,"run_ref":null,"evidence_ref":"evidence:<identifier>",
  "evidence_digest":"<sha256>","occurred_at":"2026-07-27T12:00:00.000000Z"
}
```

Checkpoint is exact:

```json
{"schema_version":1,"source_authority":"hqa_workflow_v2","owner_user_id":"<identifier>","workspace_ref":"workspace:<identifier>","last_sequence":12,"last_source_event_id":"event:<sha256>","last_source_event_digest":"<sha256>","last_record_sha256":"<sha256>"}
```

At sequence zero the last three fields are null. Command cursor and HQA checkpoint advance independently.

Platform persists source checkpoint, dedupe `(source_authority,source_event_id)` plus digest, derived Task row, and optional Task-event outbox in one transaction. Same ID/same digest is replay; same ID/different digest is `workspace_progress_source_conflict`, health becomes `corrupt`, and affected follow stops pending rebuild/audit.

The projector consumes strict HQA sequence. Gap, regression, owner/workspace mismatch, hash mismatch, stale semantic cursor, or unknown event sets `authority_health.task_progress="resync_required"` and emits no later event. Rebuild deletes only disposable source rows and replays verified HQA from sequence 1. Crash before commit replays; crash after commit before acknowledgement dedupes. No checkpoint-first or projection-first state is legal.

HQA stale semantic cursors return `workflow_event_cursor_stale`. Existing workspace numeric cursor `<0` or `>head` requires resnapshot, `after==head` returns empty, and frontend compatibility tests retain the current negative-cursor clamp while backend validation remains strict.

## 14. Closed Error Contract

Private authenticated adapters return safe `hermes.contract_problem` schema 1 with fixed value-free message, closed code, retry class, allowlisted metadata details, and nullable request ID. No labels, evidence bodies, prompts, payloads, tool/provider output, secrets, or mutable paths are returned.

| Code | HTTP | Recovery |
|---|---:|---|
| `workflow_invalid_progress_plan` | 400 | correct request |
| `workflow_progress_write_disabled` | 409 | activate capability; no blind retry |
| `workflow_progress_unavailable` | 409 | legacy/read-only |
| `workflow_progress_plan_immutable` | 409 | do not mutate |
| `workflow_step_not_found` | 400 | correct request |
| `workflow_step_out_of_order` | 409 | refresh Task |
| `workflow_step_already_completed` | 409 | consume original metadata |
| `workflow_evidence_required` | 400 | supply exact pair |
| `workflow_evidence_forbidden` | 400 | remove pair |
| `workflow_evidence_invalid` | 422 | obtain qualifying evidence |
| `workflow_binding_conflict` | 409 | audit refs; no substitution |
| `workflow_stale_version` | 409 | refresh and use new operation for changed bytes |
| `workflow_idempotency_conflict` | 409 | audit identity |
| `workflow_progress_incomplete` | 409 | satisfy milestones or legal non-success outcome |
| `workflow_terminal_immutable` | 409 | read-only |
| `workflow_storage_unavailable` | 503 | query receipt before exact retry |
| `workflow_journal_corrupt` | 500 | stop and audit |
| `workflow_event_cursor_stale` | 409 | full resnapshot |
| `workspace_progress_source_conflict` | 500 | stop projector; rebuild/audit |
| `workspace_progress_resync_required` | 409 | snapshot and new checkpoint |

Authentication retains existing indistinguishable 401/403 behavior and does not reveal whether a Task or evidence exists. No public mutation adapter is created.

## 15. Hermetic Interfaces

```text
TaskSubmissionPort.submit(StartResearchWithProgress) -> WorkflowReceipt
ProgressPlanCodec.canonical_bytes(plan_without_digest) -> bytes
ProgressPlanCodec.digest(plan_without_digest) -> lower_hex64
ProgressPlanPolicyValidator.validate(plan) -> valid|closed_reason
StepCompletionPort.complete(command) -> WorkflowReceipt|AlreadyCompletedResult
CompletionEvidencePort.observe(ref,digest) -> CompletionEvidenceObservationV1
EvidencePolicyValidator.validate(step,command,observation) -> valid|closed_reason
TaskProgressReadPort.snapshot(task_ref) -> TaskProgressProjection
TaskProgressFollowPort.events(task_ref,after_event_id,limit) -> WorkflowEventPage
ProgressReconcilePort.operation_receipt(operation_id) -> WorkflowReceipt|null
ProgressReconcilePort.rebuild_projection() -> AuditReceipt
WorkspaceProgressProjectionPort.apply(source_record) -> atomic projection result
CompositeWorkspaceFollowPort.page(command_cursor,progress_checkpoint,limit) -> WorkspaceEventPage
```

Fakes inject authority timestamps and faults at validation, pre-append, fsync/ack, projection transaction, checkpoint, cursor gap, duplicate-ID/different-digest, stale CAS, terminal race, journal corruption, and evidence unknown-to-positive boundaries.

## 16. No Public Write and Safety Boundary

Contract 1 adds no browser, chat, unauthenticated, or public mutation route; does not add the completion command to a standing public allowlist; exposes no authority credential/path; changes no `mutation_enabled` semantics; performs no approval, Gate mutation, registration, promotion, release, Git, broker, order, or trading action; and changes no safety flag.

The only write is a private in-process or owner-authenticated HQA command inside the existing local authority boundary. Workspace APIs are read-only. Contract 1 dependency graphs contain no approval, promotion, release, Git, broker, order, or trading port.

Standing assertions remain `kill_switch=true`, `live_trading_enabled=false`, public write default OFF, and `release_authorized=false`.

## 17. Required Test Matrix

### 17.1 Codec, bounds, and schema

- Minimum/maximum/over-limit steps, identifiers, labels, allowed kinds, plan bytes, command bytes, journal limits, and page limits.
- Exact ordinals; gaps, zero, negative, duplicates, unsorted values, and boolean-as-integer rejection.
- Duplicate JSON keys at every depth; unknown/missing/extra fields for every object.
- Invalid UTF-8/Unicode, NaN, Infinity, floats, exponent, negative zero, integer overflow, whitespace, and controls.
- Shared Python/TypeScript canonical bytes and SHA-256 golden vectors, including mutation sensitivity.

### 17.2 Plan, creation, and compatibility

- Timer/percentage/token/provider/model/vague/duplicate/forbidden plans reject; validator never rewrites.
- `none` only for the two administrative IDs; every work step requires exact-positive evidence.
- Legacy start remains byte-identical with writes off; feature start creates Task, Attempt, and plan atomically.
- Invalid plan creates zero records/refs and reserves no operation ID.
- Pre-feature v2, feature v2, and mixed journals replay; third shapes remain corruption.
- Delete/rebuild byte-matches clean replay; existing plan proposal/revision/continuation cannot mutate progress plan.

### 17.3 Transitions, idempotency, and terminal races

- Every `0/N..N/N` for `N=1` and `N=64`; `N/N` alone is nonterminal.
- Completed outcome rejects at `k/N`; existing completion evidence remains required at `N/N`.
- Exhaustive out-of-order/skip cases, same-operation replay/conflict, and different-operation semantic duplicate.
- Concurrent same-step writers produce one append; consecutive same-version steps make the second stale.
- Completion-first versus terminal-first lock acquisition, stop/expiry/reconcile/provider-callback races, and no synthesized progress.
- Every legal non-success terminal outcome freezes at `k/N`.

### 17.4 Ledger and public observation separation

- PostgreSQL accepts only `queued|leased|delivered|outcome_unknown|succeeded|failed|cancelled` and terminalizes only `succeeded|failed|cancelled`.
- Database checks, backend `CommandState`, HQA submission state, and ledger-event constraints share the seven-state vector.
- Public `rejected|timed_out` categories arise only through explicit adapter fixtures and never enter ledger rows/events.
- Frontend polling may stop on the broader public set but labels the source category and never completes Task progress.

### 17.5 Evidence and privacy

- Both-or-neither evidence pair, required/forbidden policies, and every allowed positive kind.
- Absent, stale, revoked, cross-owner/Task/Attempt/Run, wrong-kind, mismatch, negative, unknown, sample, provider assertion, failed, cancelled, rejected, timed-out, stopped, partial, refusal, idle, delivered, and outcome-unknown cases.
- Evidence changes between observation and lock validation fail closed; bodies never enter commands, journal, projections, errors, wire output, logs, or artifacts.
- Privacy scans cover prompts, payloads, reasoning, tool/provider output, secrets, model IDs, evidence bodies, notes, and mutable paths.

### 17.6 Journal, workspace, and invariance

- Sequence/event/operation/owner/timestamp/hash/version/reducer corruption, unknown events, ambiguous acknowledgement, and verified projection rebuild.
- Old and new snapshot/follow readers, absent/null capabilities, strict unsupported startup, optional fields, and unchanged ID arrays.
- Numeric command events and HQA string Task events cannot collide.
- Atomic projection crashes, dedupe replay/conflict, checkpoint gaps/regressions, source ownership, stale cursors, resnapshot, and rebuild.
- Independent command cursor/HQA checkpoint progress and snapshot/follow convergence under duplication, loss, reorder, reconnect, and rebuild.
- Production rejects `sample_fixture`.
- Property tests prove fixed plan plus accepted records yield byte-identical progress regardless of clocks, polling, retries, tokens, model/provider state, heartbeats, Run duration, Command/public observation categories, or UI cadence.
- Dependency spies prove zero approval, Gate mutation, promotion, release, Git, public-write, broker, order, trading, and safety-flag calls.

## 18. Activation and Rollback

Deploy dual readers, codecs, validators, reducer, and tests with capabilities off; then optional workspace parsers and atomic projection schema; run old/new/mixed replay and rebuild; enable private read; shadow-validate without append; enable one sealed owner/workspace writer canary; complete a hermetic Task through `0/N..N/N` with HQA/Platform restarts; then enable UI only on exact committed revisions.

Activation requires all test groups green, clean committed HQA/Platform revisions, cross-language vectors, mixed replay, delete/rebuild and crash proof, frontend discriminated Task-event parsing, ledger/public-observation parity tests, ready authority health, no unsupported capability, no production sample provenance, and runtime safety assertions.

Before the first feature record, both capabilities may be disabled. After any feature `research_started` or `step_completed`, history is never rewritten, downgraded, or stripped; dual reader/read projection remain; rollback sets writer capability null; records remain replayable read-only; projection defects rebuild from HQA; integrity defects suppress UI and require audit. A legacy writer MUST NOT append malformed continuation to a feature Task. `ContinueResearch` remains legal only because it does not mutate the plan.

## 19. Normative Source Anchors

- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/Hermes-quant-agent/hqa/workflow_contract.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/Hermes-quant-agent/hqa/workflow_authority.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/Hermes-quant-agent/hqa/agent_workspace_states.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/quant_system/hermes/command_ledger.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/quant_system/hermes/agent_workspace.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/quant_system/hermes/workspace_observe.py`
- `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/src/frontend/lib/hermes/workspaceClient.ts`

This specification authorizes no edit to those files, no public mutation route, and no safety-setting change. It defines the contract an implementation must satisfy.
