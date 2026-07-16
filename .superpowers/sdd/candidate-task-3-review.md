# Candidate Task 3 Review

**Task:** Atomic candidate repository and digest-bound review CAS  
**Commit:** `51647d95ad59a9ab9b0449be6e2eae7cb3e66a8f` (`51647d9`)  
**Base:** `cb4d7e0f06352cc6a52a3320f2c3478fe5fb1803`  
**Platform branch:** `audit-remediation-2026-06-23`  
**Reviewer role:** Senior Python code review (security + CAS contracts)

## Spec Compliance

| Key check | Result |
|-----------|--------|
| Immutable after publish; same ID+digest noop; same ID+different bytes conflict | **Pass** |
| Review CAS with `expected_manifest_digest` + `expected_status="pending"` | **Pass** (server-side) |
| All content/control writes via Task 2 dirfd primitives | **Pass** |
| API/CLI require CAS fields; stable 409 errors | **Partial** — digest required; `expected_status` defaults to `"pending"` on API + CLI |
| No `Path.open` / `tempfile` / path-string `os.replace` for content/control writes | **Pass** |
| Structured decision locks; final decision immutable | **Pass** |
| `list_for_read` isolates verified / migration_required / corrupt | **Pass** |
| ID validation before root open; shared rejection surface | **Pass** |
| `SafetyGate(agent_output_dir)` only; no candidates-dir bypass | **Pass** |
| Concurrent approve/reject + retry immutability | **Pass** |
| Pool lock symlink/FIFO/hardlink fail-closed | **Pass** |
| Partial publish leaves no final candidate | **Pass** |

Core repository semantics match the brief. The only blocking contract gap is that **`expected_status` is not actually required** at the API/CLI boundary (see HIGH issue below).

## Strengths

1. **Dirfd-only mutation path.** `write_candidate` and `review` publish exclusively through `write_regular_exclusive_at`, `atomic_write_noreplace_at`, `mkdir_exclusive_at`, and `rename_directory_noreplace_at`. No residual pathname content/control writes in `candidate_pool.py` / new `candidate_fs.py` helpers.

2. **Pool lock is properly verified.** `locked_candidates_root` requires a single-link regular `.candidate-pool.lock`, re-stats via `dir_fd` + `O_NOFOLLOW`, checks dev/ino match the held FD before and after the critical section, and holds `fcntl.LOCK_EX`.

3. **Publication is stage → fsync → no-replace rename under the pool lock.** Same stable inputs return the existing verified snapshot without rewriting; different artifact bytes raise `CandidateConflictError` without mutating the final tree. Interrupted rename leaves only hidden staging / lock entries.

4. **Review CAS is fail-closed and final.** Pre-validates ID / lowercase 64-hex digest / note length / literal `pending` before opening the root. Under the pool lock: verify snapshot, refuse any existing decision control, compare digest, exclusive no-replace lock publish, re-read lock bytes, refuse opposite lock. Retries never flip/delete/replace the winner.

5. **Authorization is digest-bound.** Structured `approved.lock` must match candidate ID + current manifest digest; `{}` / legacy / wrong-digest locks become `legacy_unbound` and `SafetyGate` returns `False`.

6. **Read isolation is correct.** Corrupt items expose only ID + `integrity_state` + stable error code; migration items expose non-authoritative `observed_manifest_digest` with `approval_enabled=False`; one bad item does not hide healthy siblings. `list_for_read` never writes a stored manifest.

7. **Caller surface cleaned up.** `SafetyGate` / promote / promotion / registry / factors take agent-output roots only; static regression test bans `SafetyGate(...candidates_dir...)`.

8. **API 409 map is stable and ordered correctly.** `migration_required`, `review_state_stale`, `stale_digest`, `integrity_error` with structured detail; missing candidates stay 404.

9. **Test suite is adversarial and green.** Repository + API + promotion/promote/CLI/registry suites exercised for this review all passed (including concurrent race matrix, lock-type abuse, invalid-ID zero-write, partial publish).

## Issues

```text
[HIGH] expected_status is not required on API/CLI CAS boundary
File: src/quant_system/api/schemas/agent.py:63-67
File: src/quant_system/cli.py:1846-1852
Issue: Brief requires both CAS fields. AgentReviewRequest sets
  expected_status: Literal["pending"] = "pending", so it is omitted from
  JSON schema required[] (only decision/note/expected_manifest_digest).
  CLI likewise defaults --expected-status to "pending". Omitting the field
  still succeeds (defaults to pending). Test
  test_agent_review_missing_expected_status_and_stale_second_decision only
  asserts missing digest → 422; it never asserts missing status → 422.
Fix: Remove the default on AgentReviewRequest.expected_status and on the
  CLI option so both fields are required. Extend the API test to POST
  without expected_status and expect 422; add a CLI invocation without
  --expected-status and expect non-zero exit.

[MEDIUM] review() uses manual __enter__/__exit__(None, None, None)
File: src/quant_system/agent/candidate_pool.py:449-540
Issue: locked_candidates_root is entered/exited manually and always exits
  as success (exc_type=None). On failure paths, post-yield identity asserts
  still run; if they raise, they can mask the original CAS exception
  (CandidateStaleError / CandidateReviewStateStaleError).
Fix: Use `with locked_candidates_root(...) as root:` so exceptions
  propagate through the contextmanager protocol correctly.

[MEDIUM] Root/candidate swap tests swap before open, not mid-hold
File: tests/test_candidate_repository.py:374-461
Issue: Brief asks for rename/replace after the candidates-root FD is open,
  and after verified read but before review-lock publication. Current tests
  replace the tree before review() starts. Implementation has
  assert_entry_is_open_fd checkpoints that should catch mid-hold swaps, but
  that path is not exercised by injection.
Fix: Add barrier/monkeypatch hooks around assert_entry_is_open_fd or
  atomic_write_noreplace_at to rename the root/candidate entry while the
  held FD is live; assert fail-closed and no decision lock in the
  replacement.

[MEDIUM] Structured lock parser ignores payload decision field
File: src/quant_system/agent/candidate_manifest.py:271-305
Issue: _parse_bound_review trusts the caller-supplied decision (from lock
  basename) and does not require data["decision"] to match. A hand-crafted
  approved.lock with decision="reject" but correct ID+digest still
  authorizes. Also omits manifest_digest on the returned ReviewRecord
  (digest returned out-of-band only).
Fix: Require data.get("decision") == decision (and candidate_id/digest
  already checked). Populate ReviewRecord.manifest_digest from the lock.

[MEDIUM] write_candidate / review exceed readability threshold
File: src/quant_system/agent/candidate_pool.py:223-373, 421-540
Issue: Both mutation methods are long nested procedures (staging, CAS,
  cleanup). Harder to audit future changes.
Fix: Extract helpers e.g. _stage_candidate_tree, _publish_decision_lock,
  _cas_preconditions without changing semantics.

[LOW] Runner imports private validators from candidate_pool
File: src/quant_system/agent/runner.py:145-149
Issue: AgentRunner.review imports _validate_digest/_validate_note (module-
  private) to pre-check before audit IO. Works, but couples to private API.
Fix: Export public validate_review_cas_inputs() from candidate_pool or
  candidate_manifest and share it with CandidatePool.review.

[LOW] macOS /var vs /private/var lexical walk (pre-existing class)
File: src/quant_system/agent/candidate_fs.py:open_absolute_directory
Issue: Report correctly notes lexical dirfd walk cannot cross intermediate
  symlinks. Unresolved /var/... agent roots fail closed. Pytest tmp_path is
  fine because it is already resolved. Document/operationalize resolved
  agent roots only.
Fix: No code change required for Task 3; keep as ops constraint / Task
  follow-up if a resolve-once helper is desired at the agent-root boundary.
```

## Diagnostic summary

```text
pytest (task suites): PASS
  tests/test_candidate_repository.py
  tests/test_api_agent.py
  tests/test_agent_phase7.py
  tests/test_cli_json_output.py
  tests/test_agent_promotion.py
  tests/test_agent_promote.py
  tests/test_agent_propose_source_file.py
  tests/test_factor_registry_factory.py
  tests/test_cli_experiment_provider.py
  tests/test_agent_paths.py
  tests/test_candidate_manifest.py

Forbidden write APIs in mutation modules: none found
ruff/mypy/bandit: not installed in environment (not run)
```

## Assessment

**Needs fixes**

Blockers are narrow and local:

1. Make `expected_status` required on API schema + CLI (no default), and assert missing status fails (422 / non-zero).
2. (Recommended in same patch) Switch `review()` to a real `with locked_candidates_root(...)`.

Everything else — immutability, digest CAS, structured locks, dirfd publication, concurrent finality, SafetyGate agent-root contract, corrupt/migration isolation, 409 mapping — is solid and meets the security intent of Task 3. After the CAS-field requirement is tightened, this is **Approve**-ready.
