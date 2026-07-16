# Candidate Task 3 Re-review

**Task:** Atomic candidate repository and digest-bound review CAS  
**Commits:**
- `51647d95ad59a9ab9b0449be6e2eae7cb3e66a8f` — initial Task 3
- `ed3b9bbc5f6c116dbe3b75bed1c4b6de625633d7` — review fix (`expected_status` required + `with` lock)
**Base:** `cb4d7e0f06352cc6a52a3320f2c3478fe5fb1803`  
**Platform branch:** `audit-remediation-2026-06-23`  
**HEAD:** `ed3b9bbc5f6c116dbe3b75bed1c4b6de625633d7`  
**Prior review:** `candidate-task-3-review.md` (**Needs fixes**)  
**This review:** re-check after expected_status + with-lock fixes

## Fix verification

### 1. `expected_status` is truly required — **Confirmed**

| Layer | Evidence | Result |
|-------|----------|--------|
| API schema | `AgentReviewRequest.expected_status: Literal["pending"]` with **no default** | Pass |
| JSON schema | `required: ['decision', 'note', 'expected_manifest_digest', 'expected_status']` | Pass |
| Pydantic fields | `is_required()=True`, `default=PydanticUndefined` for both CAS fields | Pass |
| CLI Typer option | `--expected-status` has no default; Click `required=True`, `default=None` | Pass |
| Runner / Pool | Keyword-only params, no defaults; reject non-`"pending"` | Pass |
| API test | POST without `expected_status` → **422** (and still no lock written on later stale path) | Pass |
| CLI test | Missing `--expected-status` → **non-zero exit**, no `approved.lock` | Pass |

Grep of production `src/` shows no remaining `expected_status = "pending"` defaults on public review entry points. Call sites that pass `"pending"` are explicit CAS values, not silent defaults.

### 2. `review()` lock context — **Confirmed**

`CandidatePool.review` now uses:

```python
with locked_candidates_root(self.output_dir, create=False) as root:
    ...
```

The previous manual `__enter__` / `__exit__(None, None, None)` path is gone. CAS exceptions (`CandidateStaleError`, `CandidateReviewStateStaleError`, etc.) propagate through the contextmanager protocol; post-yield identity asserts no longer run on failure paths and cannot mask the original error. `finally` still unlocks/closes the pool lock FD.

## Spec compliance (updated)

| Key check | Result |
|-----------|--------|
| Immutable after publish; same ID+digest noop; conflict on different bytes | **Pass** |
| Review CAS: `expected_manifest_digest` + `expected_status="pending"` | **Pass** |
| API/CLI **require** both CAS fields (no default) | **Pass** (fixed) |
| All content/control writes via Task 2 dirfd primitives | **Pass** |
| Structured decision locks; final decision immutable | **Pass** |
| `list_for_read` isolates verified / migration_required / corrupt | **Pass** |
| ID validation before root open; shared rejection surface | **Pass** |
| `SafetyGate(agent_output_dir)` only | **Pass** |
| Concurrent approve/reject + retry immutability | **Pass** |
| Pool lock symlink/FIFO/hardlink fail-closed | **Pass** |
| Partial publish leaves no final candidate | **Pass** |
| `with locked_candidates_root` in review | **Pass** (fixed) |

## Diagnostics

```text
pytest (targeted re-review): PASS
  tests/test_api_agent.py::test_agent_review_missing_expected_status_and_stale_second_decision
  tests/test_cli_json_output.py::test_agent_review_missing_expected_status_exits_nonzero
  tests/test_candidate_repository.py
  tests/test_agent_phase7.py

ruff (fix surfaces): All checks passed
mypy/bandit: not run (not invoked for this re-review beyond ruff)
```

OpenAPI/schema spot-check via `AgentReviewRequest.model_json_schema()` confirms both CAS fields are in `required[]` and `expected_status` is `const: "pending"` with no default.

## Remaining non-blocking notes (from prior review; unchanged)

```text
[MEDIUM] Root/candidate swap tests swap before open, not mid-hold
File: tests/test_candidate_repository.py
Issue: Tests still replace the tree before review() starts rather than
  after the held FD is live / after verified read and before lock publish.
  Implementation has assert_entry_is_open_fd checkpoints that should catch
  mid-hold swaps, but that path is not exercised by injection.
Fix: Optional follow-up — barrier/monkeypatch around
  assert_entry_is_open_fd or atomic_write_noreplace_at.

[MEDIUM] Structured lock parser ignores payload decision field
File: src/quant_system/agent/candidate_manifest.py
Issue: _parse_bound_review trusts basename-derived decision and does not
  require data["decision"] to match; hand-crafted approved.lock with
  decision="reject" but correct ID+digest could still authorize.
  ReviewRecord.manifest_digest may still be omitted on parse path.
Fix: Require data.get("decision") == decision; populate
  ReviewRecord.manifest_digest from the lock. Reasonable Task 4 / hardening
  follow-up; not a Task 3 CAS-boundary regression.

[MEDIUM] write_candidate / review exceed readability threshold
File: src/quant_system/agent/candidate_pool.py
Issue: Long nested mutation procedures. Harder to audit future changes.
Fix: Extract helpers without changing semantics.

[LOW] Runner imports private validators from candidate_pool
File: src/quant_system/agent/runner.py
Issue: Couples AgentRunner.review to _validate_digest/_validate_note.
Fix: Public validate_review_cas_inputs() shared with CandidatePool.review.

[LOW] macOS /var vs /private/var lexical walk
File: src/quant_system/agent/candidate_fs.py
Issue: Unresolved intermediate symlink components fail closed. Ops must
  use resolved agent roots. Documented in Task 3 report.
```

None of the above is CRITICAL or HIGH. None reopens the CAS-field contract.

## Issues introduced by the fix commit

None found. `ed3b9bb` is a minimal, correct patch:

1. Removes API/CLI defaults for `expected_status`
2. Adds missing-status API 422 + CLI non-zero tests
3. Replaces manual lock enter/exit with `with locked_candidates_root(...)`

No new security surface, no silent fallbacks, no regression of digest CAS.

## Assessment

**Approved**

Prior HIGH blocker is resolved: `expected_status` is required at API schema, CLI, Runner, and Pool, with tests proving omission fails closed (422 / non-zero, no lock write). The recommended `with locked_candidates_root` fix is also landed.

Remaining MEDIUM items are quality/hardening follow-ups and do not block merge of Task 3. Core security intent — immutable publication, digest-bound review CAS, structured final locks, dirfd-only writes, concurrent finality, SafetyGate agent-root contract, corrupt/migration isolation — remains solid.
