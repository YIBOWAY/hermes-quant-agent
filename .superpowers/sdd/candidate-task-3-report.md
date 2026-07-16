# Candidate Integrity Task 3 Report

**Task:** Atomic candidate repository and digest-bound review CAS  
**Platform branch:** `audit-remediation-2026-06-23`  
**BASE:** `cb4d7e0f06352cc6a52a3320f2c3478fe5fb1803`  
**Status:** COMPLETE  

## Commit

| SHA | Subject |
|-----|---------|
| `51647d95ad59a9ab9b0449be6e2eae7cb3e66a8f` | `fix(agent): make candidate writes immutable and approvals revision-bound` |
| `ed3b9bbc5f6c116dbe3b75bed1c4b6de625633d7` | `fix(agent): require expected_status for candidate review CAS` |

Short (review fix): `ed3b9bb`

**Not pushed** (controller owns platform push).

**Preserved dirty/untracked (not staged):**
- `data/options_universe/earnings_calendar.csv`
- `.understand-anything/diff-overlay.json`

## What changed

### Core repository

- `src/quant_system/agent/candidate_fs.py`
  - `locked_candidates_root`: exclusive `fcntl.flock` on verified single-link regular `.candidate-pool.lock` under held candidates FD
  - `mkdir_exclusive_at`, `remove_entry_tree_at` dirfd helpers
  - No `Path.open` / `tempfile` / path-string `os.replace` fallback

- `src/quant_system/agent/candidate_pool.py`
  - Atomic stage → fsync → `rename_directory_noreplace_at` publication under pool lock
  - Idempotent same-id/same-bytes create; different bytes → `CandidateConflictError`
  - Filename + protected `metadata_extra` rejection before any side effect
  - `list_for_read` isolates verified / migration_required / corrupt items
  - Review CAS: `expected_manifest_digest` + literal `expected_status="pending"`; structured decision locks; final decision immutable (never flipped/deleted)
  - Pre-validation of ID/digest/note before root open (zero writes on bad IDs)

- `src/quant_system/agent/models.py`
  - `CandidateArtifact.manifest_digest`, `ReviewRecord.manifest_digest`, `CandidateReadItem`

- `src/quant_system/agent/safety.py`
  - **New public contract:** `SafetyGate(agent_output_dir)` only
  - Authorizes only `approval_binding == "approved"` on verified snapshot; legacy `{}` locks never authorize

### Callers / API / CLI

- `promotion.py` / `promote.py` / `registry.py` / `factors.py` / `cli.py`: take `agent_output_dir` (no candidates-dir bypass)
- `runner.py`: `list_for_read`; review requires and audits CAS fields before mutation
- API schemas/routes: CAS fields, integrity state on list/detail, stable 409 codes (`stale_digest`, `review_state_stale`, `migration_required`, `integrity_error`)
- CLI review: `--expected-digest` + `--expected-status pending`

### Tests

- New `tests/test_candidate_repository.py`: noop/conflict create, stale digest, unsafe filename zero-side-effect, migration/corrupt isolation, invalid-ID zero-write, concurrent approve/reject + immutable retries, pool-lock symlink/FIFO/hardlink, root/candidate swap, partial publish, structured approve, static SafetyGate regression
- Updated phase7, promotion, promote, API, CLI JSON, factor registry factory, experiment provider

## Test summary

```bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_paths.py \
  tests/test_candidate_manifest.py \
  tests/test_candidate_repository.py \
  tests/test_agent_phase7.py \
  tests/test_agent_promotion.py tests/test_agent_promote.py \
  tests/test_agent_propose_source_file.py \
  tests/test_api_agent.py tests/test_cli_json_output.py \
  tests/test_factor_registry_factory.py \
  tests/test_cli_experiment_provider.py
```

**Result:** all passed (212+ including related suites).

Contracts verified:
- Same ID + same bytes is noop; different bytes conflict without overwrite
- Review requires current digest + pending status; wrong digest writes nothing
- Structured approve.lock binds schema/ID/decision/digest/note/reviewer/timestamp
- Legacy unbound locks never authorize promotion
- Concurrent approve/reject: exactly one winner; retries never flip final decision
- Bad candidate IDs: get/review/SafetyGate/CLI reject with zero tree writes
- Corrupt and migration_required items remain listed but cannot review/promote
- SafetyGate accepts agent-output root only

## Concerns / follow-ups

1. **Task 4** still owns removing reopen-after-verification in promote/load paths (snapshot/bytes-only consumers). Loader already prefers `artifact_bytes` where available.
2. **HQA / frontend CAS** (Task 5) must learn `--expected-digest` / `--expected-status`; backend no longer accepts digest-less review.
3. **JSON review contract** now includes `manifest_digest` in the `--json` payload (additive field).
4. **macOS `/var` vs `/private/var`:** dirfd walk is lexical; pytest tmp uses resolved `/private/var` paths — production agent root must not rely on intermediate symlink components.
5. **No real candidate data mutation**, no paper/live, no push.

## Files in commit (20)

```
src/quant_system/agent/candidate_fs.py
src/quant_system/agent/candidate_pool.py
src/quant_system/agent/models.py
src/quant_system/agent/promote.py
src/quant_system/agent/promotion.py
src/quant_system/agent/runner.py
src/quant_system/agent/safety.py
src/quant_system/api/routes/agent.py
src/quant_system/api/routes/factors.py
src/quant_system/api/schemas/agent.py
src/quant_system/cli.py
src/quant_system/factors/registry.py
tests/test_candidate_repository.py (new)
tests/test_agent_phase7.py
tests/test_agent_promote.py
tests/test_agent_promotion.py
tests/test_api_agent.py
tests/test_cli_experiment_provider.py
tests/test_cli_json_output.py
tests/test_factor_registry_factory.py
```

## Review fix (`ed3b9bb`)

Addressed Important/Medium findings from `candidate-task-3-review.md`:

1. **`expected_status` required CAS field**
   - `AgentReviewRequest.expected_status`: removed `= "pending"` default (now in JSON schema `required[]`)
   - CLI `--expected-status`: removed default; option is required
   - API test asserts POST without `expected_status` → **422**
   - CLI test asserts missing `--expected-status` → **non-zero exit**, no lock written

2. **`review()` lock context**
   - Replaced manual `__enter__`/`__exit__(None, None, None)` with
     `with locked_candidates_root(...) as root:` so CAS exceptions are not masked

**Tests:** `test_api_agent` CAS case, CLI missing-status + review JSON, full `test_candidate_repository` + `test_agent_phase7` — all pass. Dirty tree preserved; not pushed.
