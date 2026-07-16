# Candidate Integrity Task 5 Report

**Task:** Digest-aware API, CLI, frontend compatibility, and HQA callers  
**Date:** 2026-07-13  
**Status:** Complete (committed, not pushed)  
**Implementer re-check:** working trees clean for Task 5 files; requirements present in HEAD; focused suites re-run green.

## Commits

| Repo | Branch | SHA | Message |
|---|---|---|---|
| ai-quant-platform | `audit-remediation-2026-06-23` | `392485ad190020c6179ad1a563a6cacf485f7e6d` | `feat(agent): require candidate revision on every review surface` |
| Hermes-quant-agent | `codex/full-9h` | `2f0c96d83b1cb2a5dfb6143bf3217732e83d039b` | `fix(hqa): carry candidate digest through manual Gate 2 review` |

Platform commit landed first (fail-closed window for old callers missing digest). No push. No real review executed between commits.

**Commit split note:** Platform backend (API/CLI/tests) and frontend CAS files landed in **one** platform commit (`392485a`), not the preferred two-commit split (backend then frontend). Content is correct; history was not rewritten. HQA is a separate repo commit as required.

## Brief coverage (re-verified)

| Requirement | Status |
|---|---|
| List/detail: `approval_binding`, `integrity_state`, `manifest_digest`, `observed_manifest_digest`, `approval_enabled`, `integrity_error_code` | Yes |
| Review requires `expected_manifest_digest` + `expected_status: "pending"` | Yes |
| 409: stale digest / review state / migration / integrity (most-specific first) | Yes |
| List stays 200 when another candidate is corrupt/migration | Yes |
| Platform CLI: both `--expected-digest` and `--expected-status pending` | Yes |
| HQA `run_agent_review` keyword-only; never list/refetch | Yes |
| `hqa-factor-repro approve` four CAS args; propose/list/detail print copyable command | Yes |
| Skill card `version: 1.9.0` + exact approve command + “never refetch” | Yes |
| Agent Studio: detail-bound CAS; disable when not reviewable | Yes |
| `factors.py` uses injected `AgentOutputDirDep` (no change needed) | Yes |

## Platform changes (`392485a`)

- **API schema** (`schemas/agent.py`): `AgentReviewRequest` requires `expected_manifest_digest` (`^[0-9a-f]{64}$`), `expected_status: "pending"`, note length 1..2000.
- **Review route** (`routes/agent.py`): domain errors most-specific-first → stable 409 codes:
  - `candidate_review_state_stale`
  - `candidate_migration_required`
  - `candidate_integrity_failed`
  - `candidate_revision_stale`
  - detail always `{code, resource: agent_candidate, id}`
- **Detail**: verified preview from verified snapshot bytes; migration via exact-byte observed reader; corrupt has no preview.
- **CLI**: review requires both CAS flags (missing → exit 2). List/propose print authoritative digest + copyable approve syntax for verified pending; migration prints observed evidence only; corrupt prints no digest.
- **Frontend**: Agent Studio `ReviewDialog` refetches detail, submits both CAS fields, disables when `approval_enabled`/pending/digest checks fail. OpenAPI regenerated. Nullable integrity fields handled on agent-studio, hermes, brief pages.
- **factors.py**: no Task 5 code change (already injects `AgentOutputDirDep`).

## HQA changes (`2f0c96d`)

- `run_agent_review(*, … expected_manifest_digest, expected_status, …)` keyword-only; never refetches.
- `approve` requires all four human values; validation exits 2 before `run_agent_review` on omissions / whitespace note / malformed digest / non-pending status.
- Propose/list/detail print verified digests + copyable approve command; migration/corrupt never substitute observed digests into approval.
- Skill card **1.9.0** documents exact Gate 2 CAS command and “never refetch”.

## Verification (re-run 2026-07-13)

Platform:

```text
./ai-quant/bin/python -m pytest -q tests/test_api_agent.py \
  tests/test_cli_json_output.py tests/test_api_response_models.py \
  tests/test_frontend_openapi_generation.py
# 40 passed (EXIT 0)
```

Earlier full frontend suite (from delivery commit window): npm test 85 passed; type-check/lint clean; `generate:api-types` already applied in `392485a`.

HQA:

```text
./.venv/bin/pytest -q tests/test_quant_cli.py tests/test_factor_repro.py \
  tests/test_factor_repro_cli.py tests/test_install.py
# all passed, 1 skipped (EXIT 0)
```

## Remaining frontend gaps (non-blocking)

- No dedicated `AgentTaskForm` unit/e2e asserting CAS POST body / `canReview` disable rules (OpenAPI + backend tests cover contract).
- Outer list gate is slightly looser (`approval_enabled !== false`) than inner `canReview` (`=== true`); submit path still fail-closed.
- Detail load failures soft-disable via fallback rather than a hard error banner.
- Hermes/brief remain read-only (correct); optional integrity badges not required for CAS safety.

## Preserved dirty / untracked (not staged)

- Platform: `data/options_universe/earnings_calendar.csv`, `.understand-anything/`
- HQA: `.superpowers/` (untracked; includes this report)

## Safety notes

- Gate 2 remains human-only CAS; HQA approve never lists/refetches digest or status.
- Observed migration digests never authorize approval.
- Second review leaves first lock bytes unchanged (`candidate_review_state_stale`).
- No paper/live trading, promotion, or broker paths touched.
- **Not pushed.**
