# Candidate Integrity Task 4 Report

**Task:** Re-verify before one-shot load and promotion  
**Platform branch:** `audit-remediation-2026-06-23`  
**BASE:** `ed3b9bbc5f6c116dbe3b75bed1c4b6de625633d7`  
**Status:** COMPLETE  

## Commit

| SHA | Subject |
|-----|---------|
| `8aaa278c778e10ab145a658292bdf4d579df6ce6` | `fix(agent): recheck candidate digest before research or promotion` |

Short: `8aaa278`

**Not pushed** (controller owns platform push).

**Preserved dirty/untracked (not staged):**
- `data/options_universe/earnings_calendar.csv`
- `.understand-anything/diff-overlay.json`

## What changed

### One-shot loader (`promotion.py`)

- Enumerates via `CandidatePool(agent_output_dir).list_for_read()`
- Re-verifies each candidate with `load_verified_candidate_snapshot` at the last responsible moment
- Authorizes only `approval_binding == "approved"` (digest-bound structured lock; legacy unbound never loads)
- Compiles **only** `snapshot.artifact_bytes["factor.py.candidate"]` with a synthetic compile name (`<id/factor.py.candidate>`) — never reopens candidate absolute paths
- Tamper/integrity failures raise `CandidateIntegrityError` (fail closed; no silent skip of corrupt approved candidates)
- Skips `migration_required` and invalid-id junk names without compile

### Internal materializer (`promote.py`)

- Signature is now:
  `promote_candidate(snapshot, *, expected_candidate_digest, library_dir, tests_dir)`
- No candidate filesystem I/O, no `SafetyGate`/`CandidatePool`, no wall clock (`datetime` removed)
- Compares `expected_candidate_digest` to `snapshot.manifest_digest` before AST checks
- Uses only `snapshot.artifact_bytes`; refuses non-`approved` binding and missing `review_record`
- Provenance header is path-free and clock-free:
  - `candidate_id`, `manifest_schema`, `manifest_digest`, `approved_on` (UTC date from structured review record)
  - No absolute candidate/lock/worktree paths
- Preserved: exclusive create, promote lock, rollback, registry/alpha101 collision, keyword/underscore refusal, atomic init rewrite, no-git/no-process static contract

### Callers

- `cli.py` `agent promote-candidate`: loads verified snapshot immediately before materializer; maps `PromotionError`/`CandidateIntegrityError` to exit 1
- `registry.py`: one-shot path still requires explicit `agent_output_dir`; documents re-verify + resident purity

### Tests

- Loader: tamper-after-approval raises `CandidateIntegrityError`; legacy `{}` lock never compiles
- Materializer: tamper refuses with zero module/init/test/lock writes; dual-root approved candidate yields byte-identical outputs; provenance asserts no paths/clocks
- Registry factory: tampered approved candidate refuses `build_factor_registry(include_approved_candidates=True)`

## Test summary

```bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_promotion.py \
  tests/test_agent_promote.py \
  tests/test_factor_registry_factory.py \
  tests/test_cli_experiment_provider.py
```

**Result:** all passed (70 tests).

Contracts verified:
- Approved-then-tampered candidates never compile or materialize
- Legacy unbound locks never authorize load
- Materializer consumes only verified snapshot bytes + expected digest
- Provenance has no absolute paths and no wall clock
- Dual absolute roots produce byte-identical module/init/test
- Existing exclusive-create, lock, rollback, collision, AST, CLI Gate-3 line tests still green

## Concerns / follow-ups

1. **Public CLI still uses legacy main-worktree materialize path** until Task 7 (`prepare_promotion_workspace`). CLI now correctly re-verifies then calls internal `promote_candidate`, but Gate 3 isolation is still Task 7.
2. **Fail-closed loader:** any non-migration corrupt candidate in the pool raises and aborts the whole one-shot load batch (by design for tamper). Operators with mixed junk dirs may need cleanup; invalid-id names are still skipped.
3. **`expected_candidate_digest` on CLI** currently equals the just-verified snapshot digest (re-verify CAS). Public CLI will require explicit `--expected-digest` in Task 7 prepare contract.
4. **No real candidate data mutation**, no paper/live, no push.

## Files in commit (7)

```
src/quant_system/agent/promote.py
src/quant_system/agent/promotion.py
src/quant_system/cli.py
src/quant_system/factors/registry.py
tests/test_agent_promote.py
tests/test_agent_promotion.py
tests/test_factor_registry_factory.py
```
