# Candidate Integrity Task 8 Report

**Task:** Full verification, independent code review coordination notes, and documentation reconciliation  
**Platform branch:** `audit-remediation-2026-06-23`  
**HQA branch:** `codex/full-9h`  
**Status:** COMPLETE  

## Commits

| Repo | SHA | Subject |
|------|-----|---------|
| platform | `7987afa9f85f3f51152c733b963429445ec9ef17` (short `7987afa`) | `fix(agent): stabilize Gate 3 determinism and ruff gates` |
| platform | `15898868f3d98693c8959ee48a48ae19e9e15810` (short `1589886`) | `docs(agent): record candidate integrity and Gate 3 delivery` |
| HQA | `a5d9cb1d63c69c2c1bc45d5d656900c5a3cdddf8` (short `a5d9cb1`) | `docs(agent): reconcile candidate integrity and Gate 3 delivery` |

**Not pushed** (controller owns platform push; HQA push not requested).

**Preserved dirty/untracked (not staged):**
- platform: `data/options_universe/earnings_calendar.csv`, `.understand-anything/diff-overlay.json`
- HQA: `.superpowers/`

Tasks 1–7 code remained at platform `ae191bee` / HQA `2f0c96d` before this task. Task 8 added only the verification fix commit above plus docs commits.

## Fresh verification evidence

### Step 1 — focused platform safety suites + ruff

```text
./ai-quant/bin/python -m pytest -q <15 focused test modules>
→ 320 passed

./ai-quant/bin/python -m ruff check src/quant_system tests
→ All checks passed!
```

Focused modules:
`test_candidate_manifest`, `test_candidate_repository`, `test_candidate_migration`,
`test_agent_phase7`, `test_api_agent`, `test_agent_propose_source_file`,
`test_agent_promotion`, `test_agent_promote`, `test_promotion_workspace`,
`test_factor_registry_factory`, `test_cli_experiment_provider`,
`test_cli_json_output`, `test_api_response_models`,
`test_frontend_openapi_generation`, `test_frontend_e2e_config`.

### Step 2 — frontend + HQA caller gates

```text
npm --prefix src/frontend run test       → 85 passed (24 files)
npm --prefix src/frontend run type-check → clean
npm --prefix src/frontend run lint       → clean

HQA focused:
./.venv/bin/pytest -q tests/test_quant_cli.py tests/test_factor_repro.py \
  tests/test_factor_repro_cli.py tests/test_install.py
→ 100 passed, 1 skipped
  (skip: tests/test_quant_cli.py live quant-system manual smoke)
```

### Step 3 — independent code review summary (Tasks 1–7 + final range)

Per-task reviews already exist under `.superpowers/sdd/candidate-task-*-review.md`.
Final adversarial range review:

| Artifact | Verdict |
|----------|---------|
| Task 1 path unification | **Approved** |
| Task 2 dirfd/manifest (initial) | Needs fixes → addressed in `cb4d7e0` |
| Task 3 repository/CAS (initial) | Needs fixes (expected_status) → addressed in `ed3b9bb` |
| Task 4 re-verify load/promote | **Approved** |
| Task 5 FastAPI / React / HQA | **Approved** (×3) |
| Task 6 migration security | **Approved**; python HIGH items fixed in `1a6f471` |
| Task 7 Gate 3 python + security | **Approved** (×2) |
| Final range security `candidate-tasks-1-7-final-security.md` | **CLEAR** (no P0/P1) |

Adversarial focus areas (approve wrong digest; race approve/reject; bad IDs; root/lock swaps; symlink/FIFO/traversal; corrupt manifest; legacy lock reuse; mutate after approve; HQA CAS bypass; omit Gate 3 args; incomplete intent-to-add; tamper base/head/scoped; main-worktree contamination; paper/live path / auto-commit) — final security review reports **PASS** on isolation, CAS, migration dry-run default, Gate 3 no-commit / no main-tree mutation.

Residual non-blocking P2 only (display-only `reviews.jsonl` Path read, multi-user temp worktree root, NUL component edge, importable internal materializer).

### Step 4 — complete repository gates

```text
cd /Users/sunyibo/programs/ai-quant-platform
PYTHON_BIN=./ai-quant/bin/python bash scripts/verify.sh
→ Ruff clean
→ Pytest: 1329 passed, 15 skipped (1344 collected)
→ Frontend lint/type-check/test (85) clean
→ Frontend build skipped (default; no RUN_BUILD=1)

cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest
→ 579 passed, 2 skipped (581 collected)
```

Platform skip inventory (expected offline defaults): Futu OpenD integration (1), PostgreSQL integration (13), local futuapi skill (1).  
HQA skips: network aihot smoke (1), live quant-system manual (1).

### Verification fix included in this task

`test_patch_manifest_deterministic_across_roots_and_clock` was flaky: git commit timestamps and `utc_now_iso()` (datetime.now) were not frozen, so identical factor bytes produced different candidate digests / promotion_ids across roots. Fixed by pinning `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` in the fixture and monkeypatching `utc_now_iso` in the test. Also fixed 3 ruff issues (import sort ×2, E501 ×1). Confirmed 20/20 deterministic re-runs and full `verify.sh` green.

## Live dry-run migration (no `--apply`)

Command:

```bash
./ai-quant/bin/quant-system agent migrate-candidates
```

Result (pretty-printed):

```json
{
  "legacy_dir": "/Users/sunyibo/programs/ai-quant-platform/data/agent/candidates",
  "agent_output_dir": "/Users/sunyibo/programs/ai-quant-platform/data/agent_run",
  "canonical_dir": "/Users/sunyibo/programs/ai-quant-platform/data/agent_run/agent/candidates",
  "candidate_ids": ["factor-momentum_20d_reversal-323b045e4b"],
  "copyable": [],
  "identical": [],
  "conflicts": [],
  "canonical_unversioned": ["factor-momentum_20d_reversal-323b045e4b"],
  "legacy_unbound": [],
  "items": [{
    "candidate_id": "factor-momentum_20d_reversal-323b045e4b",
    "integrity_state": "migration_required",
    "locations": ["canonical"],
    "source_manifest_digest": null,
    "canonical_manifest_digest": "294bbe7b846ae86384e56deae8ba8df2576ac6ffa8a5937e4f82a2352fdd8558"
  }],
  "applied": false,
  "legacy_present": false,
  "canonical_present": true
}
```

**No real data mutated.** `--apply` was not run and remains unauthorized.

## Docs reconciled

### Platform (`1589886`)

- `AGENTS.md` — candidate root resolver, integrity states, Gate 2 CAS, Gate 3 prepare/status/cleanup, Hermes approval UI still closed
- `README.md` — digest-bound pool + agent-studio CAS note
- `docs/INDEX.md` — candidate integrity delivery row + dry-run facts (2026-07-13)

### HQA (`a5d9cb1`)

- `AGENTS.md`, `README.md`, `docs/README.md` — D-31 wave status + Gate 2/3/migration facts
- `skills/hermes/hqa-quant/SKILL.md` — Gate 3 prepare four-field / promotion-id / no auto-commit wording
- `docs/design/vision-daily-life.md` — four-value Gate 2 + prepare Gate 3 commands
- `docs/design/hermes_quant_agent_plan.md` — Scene-B flow updated to CAS + isolated worktree
- `docs/design/2026-07-01-roadmap-phases-0b-4.md` — D-31 delivery progress note only
- `docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md` — §8.3 baseline delivered; frontend/bridge still pending

Historical plans and completed delivery records were **not** rewritten.

## Completion criteria checklist

| Criterion | Evidence |
|-----------|----------|
| Shared `resolve_agent_output_dir` for API/CLI/loader/migration/promotion | Tasks 1–7 code + AGENTS/INDEX docs |
| Shared candidate-ID validator; bad IDs zero-write | Task 2/3 tests + final security CLEAR |
| Immutable after publish; same-ID idempotent or conflict | Task 3 review Approved after CAS fix |
| Dirfd / no-follow / no-replace / pool lock | Task 2/3 + final security PASS |
| Gate 2 digest+pending CAS; legacy unbound non-authority | Task 3/5 + HQA skill 1.9.0 |
| HQA four-value human CAS, no refetch | Task 5 HQA review + install tests |
| Compile/materialize re-verify exact bytes | Task 4 Approved |
| Real migration dry-run only | Live dry-run `applied=false` |
| migration_required/corrupt readable, no authority | Live item + list_for_read tests |
| Gate 3 prepare/status/cleanup contracts | Task 7 + suites |
| No paper/live path, auto-commit, provider call, browser CAS bypass | Final security CLEAR |
| Live docs match fresh evidence; historical plans untouched | Docs commits above |
| Focused + complete two-repo gates green | Counts in this report |

## Status

**COMPLETE.** Candidate integrity baseline and Gate 3 isolation are verified and documented. Real migration apply and Hermes workbench approval UI remain intentionally closed.
