# Candidate Task 4 Review

**Task:** Re-verify before one-shot load and promotion  
**Base:** `ed3b9bbc5f6c116dbe3b75bed1c4b6de625633d7`  
**Commit under review:** `8aaa278c778e10ab145a658292bdf4d579df6ce6`  
**Platform:** `/Users/sunyibo/programs/ai-quant-platform` (`audit-remediation-2026-06-23`)  
**Reviewer role:** senior Python code review (security + Pythonic standards)

## Assessment: **Approved**

No CRITICAL or HIGH issues. Task key properties are met: re-verify immediately before compile/materialize, materializer consumes only `VerifiedCandidateSnapshot` bytes + expected digest, no candidate-path reopen after verify, provenance is path-free and clock-free. Suites green (70 tests).

## Brief compliance checklist

| Requirement | Status |
|---|---|
| Loader re-verifies via `load_verified_candidate_snapshot` at last responsible moment | Met |
| Compile uses only `snapshot.artifact_bytes["factor.py.candidate"]` | Met |
| Synthetic compile name (no absolute candidate path) | Met |
| Authorize only `approval_binding == "approved"` (legacy unbound never loads) | Met |
| One-shot entry takes `agent_output_dir` only; resident remains promoted-only | Met |
| `promote_candidate(snapshot, *, expected_candidate_digest, ...)` | Met |
| Materializer does no candidate FS I/O / no SafetyGate / no wall clock | Met |
| Provenance: candidate_id, manifest schema/digest, UTC approval date from review record | Met |
| No absolute candidate/lock/worktree path in provenance | Met |
| Tamper-after-approval loader RED test | Met |
| Materializer dual-root byte-identical + no path/clock | Met |
| Registry factory refuses tampered approved candidate | Met |
| Existing exclusive-create / lock / rollback / collision / AST / CLI tests kept | Met (suite green) |

## What was verified

### Loader (`src/quant_system/agent/promotion.py`)

- Enumerates with `CandidatePool(agent_root).list_for_read()`.
- Re-calls `load_verified_candidate_snapshot` per candidate before any compile.
- Skips `invalid_id` and `migration_required`; re-raises `CandidateIntegrityError` (fail closed).
- Skips non-`approved` bindings and non-factor artifacts without compile.
- Decodes with `errors="strict"`; compiles under synthetic `"<id/factor.py.candidate>"`.
- No post-snapshot reopen of candidate artifact paths.

### Materializer (`src/quant_system/agent/promote.py`)

- Signature is snapshot + `expected_candidate_digest` only (no `agent_output_dir` / `promotion_date`).
- Digest CAS before AST; requires `approval_binding == "approved"` and non-None `review_record`.
- Source taken solely from `snapshot.artifact_bytes`; no `CandidatePool` / `SafetyGate`.
- `_approval_date_utc` parses ISO date prefix from structured record (no `datetime` import).
- Provenance header is path-free; exclusive create, promote lock, rollback, collision checks preserved.
- Static AST inspection confirms `promote_candidate` never uses `candidate_dir`.

### Callers

- CLI `agent promote-candidate`: loads verified snapshot immediately before materializer; maps `PromotionError` / `CandidateIntegrityError` → exit 1.
- `build_factor_registry(..., include_approved_candidates=True)` still requires explicit `agent_output_dir`; docs stress one-shot-only re-verify.

### Tests re-run

```text
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_promotion.py \
  tests/test_agent_promote.py \
  tests/test_factor_registry_factory.py \
  tests/test_cli_experiment_provider.py
```

**Result:** 70 passed. `ruff check` on touched modules: all checks passed.

---

## Findings

### [MEDIUM] Materializer “tamper” test never invokes `promote_candidate`

**File:** `tests/test_agent_promote.py` (`test_materializer_refuses_source_changed_after_digest_bound_approval`)

**Issue:** After mutating approved bytes, the test only asserts that `load_verified_candidate_snapshot` raises and that the library/tests tree is empty. Because promote is never called, the “no module/init/test/lock writes” assertions are vacuously true and do not exercise the materializer’s digest/approval refusal paths.

**Fix (optional, non-blocking):** Keep the re-verify refusal test, and add an explicit materializer unit test, e.g.:

1. Wrong `expected_candidate_digest` against a good snapshot → `PromotionError`, zero writes.
2. Snapshot with `approval_binding != "approved"` (or missing `review_record`) → `PromotionError`, zero writes.

The security property is still enforced at the re-verify boundary; this is test-depth only.

### [MEDIUM] CLI binds `expected_candidate_digest` to the just-loaded snapshot digest

**File:** `src/quant_system/cli.py` (~1954–1956)

**Issue:** `expected_candidate_digest=snapshot.manifest_digest` makes the materializer’s digest CAS tautological for the public CLI path. Real re-verify is still done; the CAS only bites when a future caller supplies an external expected digest (Task 7 prepare contract). Report already documents this.

**Fix:** Deferred to Task 7 (`--expected-digest` / prepare workspace). No action required for Task 4.

### [MEDIUM] Fail-closed one-shot load aborts the whole batch on any corrupt candidate

**File:** `src/quant_system/agent/promotion.py` (~364–367)

**Issue:** Any `CandidateIntegrityError` during re-verify (including a corrupt *pending* neighbor) aborts loading of all approved candidates. Safer than silent skip of approved-then-tampered candidates; can surprise operators with mixed junk under `agent/candidates`.

**Fix:** Accept as designed (documented in implementer report). Optional later refinement: raise only when list metadata suggests the corrupt entry was previously approved / digest-bound, else skip non-approved corrupt entries. Not required for this task.

### [MEDIUM] Stale module docstring still references SafetyGate as the loader gate

**File:** `src/quant_system/agent/promotion.py:1`

**Issue:** Module docstring still says “First consumer of the SafetyGate…”. Loader authorization is now digest-bound `VerifiedCandidateSnapshot.approval_binding`, not `SafetyGate` lock existence.

**Fix:** Update the top docstring in a follow-up to describe snapshot re-verify + `approval_binding == "approved"`.

---

## Non-issues (explicitly checked)

- No candidate-path reopen after verify in loader or materializer.
- No wall clock in promote provenance (`datetime` / `date.today` removed).
- No absolute lock/worktree path in generated headers.
- Legacy `{}` approved.lock never authorizes one-shot load (covered by test).
- Resident paper path still uses `include_approved_candidates=False`.
- No bare `except`, no mutable defaults, no secrets, no shell injection in changed code.
- Exclusive-create / promote lock / rollback / registry+alpha101 collision / keyword refusal contracts retained.

## Residual / follow-ups (from implementer; concur)

1. Gate-3 workspace isolation remains Task 7 (`prepare_promotion_workspace`).
2. Public CLI `--expected-digest` still Task 7.
3. No paper/live, no push, no real candidate data mutation in this change.

## Verdict

**Approved** — mergeable for Task 4. Address MEDIUM items opportunistically or in follow-up tasks; none block the security goal of re-verify-before-load/promote with snapshot-only materialization.
