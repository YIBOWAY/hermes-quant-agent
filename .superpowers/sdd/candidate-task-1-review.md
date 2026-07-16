# Candidate Integrity Task 1 Review

**Task:** Canonical agent path dependency  
**Package:** `4933b898fbfe82208cb42eb63c11dfd366341835`..`5c8188a62b395acfab2f47633e28ad25851eb943`  
**Verified HEAD:** `5c8188a` on platform `audit-remediation-2026-06-23`  
**Reviewer:** Python code review (static + package verification)  
**Date:** 2026-07-13  

## Verdict: **Approved**

No CRITICAL or HIGH issues. Spec contracts are implemented, tests pass, and preserved dirty files were not staged.

---

### Spec Compliance ✅

| Requirement | Status |
|---|---|
| `src/quant_system/agent/paths.py` with `resolve_agent_output_dir` / `resolve_candidates_dir` / legacy helper | ✅ |
| Default root = repo-anchored absolute `…/data/agent_run` (not CWD-relative) | ✅ verified: `/Users/sunyibo/programs/ai-quant-platform/data/agent_run` |
| `QS_DATA_DIR` does not relocate candidates | ✅ env probe + tests |
| `create_app` / `build_services` additive `agent_output_dir` | ✅ |
| `AgentOutputDirDep` on agent routes + `/api/factors?include_candidates=true` | ✅; no process-global `AGENT_CANDIDATES_DIR` |
| `CandidatePool` still appends `agent/candidates` once from agent root | ✅ |
| `AgentRunner` requires `agent_output_dir`; separate `result_output_dir` for experiment reads | ✅ |
| CLI agent options: `--agent-output-dir` default `None` → resolver; no `"data/agent_run"` defaults | ✅ |
| `experiment run-config`: `--candidates-dir` removed; resolves via `resolve_candidates_dir(resolve_agent_output_dir(...))` | ✅ |
| Playwright sets `QS_AGENT_OUTPUT_DIR` beside `QS_DATA_DIR` | ✅ |
| Source regression against `Path("data/agent_run")` / string defaults / `AGENT_CANDIDATES_DIR` / candidate-adjacent `QS_DATA_DIR` | ✅ |
| Commit message matches brief | ✅ `feat(agent): unify API candidate root with CLI source of truth` |
| Dirty `earnings_calendar.csv` + `.understand-anything/diff-overlay.json` preserved unstaged | ✅ |

**Independent verification**

```text
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_paths.py tests/test_api_agent.py \
  tests/test_cli_experiment_provider.py tests/test_factor_registry_factory.py \
  tests/test_frontend_e2e_config.py tests/test_agent_phase7.py \
  tests/test_agent_propose_source_file.py \
  tests/test_agent_promote.py::test_cli_promote_candidate_prints_files_and_gate3_line \
  tests/test_agent_promote.py::test_cli_promote_candidate_refusal_exits_nonzero \
  tests/test_cli_json_output.py
```

Result: **all passed** (Starlette/httpx deprecation warning only).  
`ruff check` on touched production modules: **All checks passed**.

Minor brief adaptation (acceptable): run-config spy still patches `load_approved_factor_candidates(..., candidates_dir=...)` rather than an `agent_output_dir` kwarg. CLI still resolves through the canonical pair and asserts the final candidates path; report concern #3 documents this as intentional Task-1 scope.

---

### Strengths

1. **Single source of truth** — `paths.py` centralizes repo root, defaults, lexical absolute anchoring (`os.path.abspath`, not symlink-following `Path.resolve()`), and the `agent/candidates` join rule.
2. **API isolation boundary is correct** — factors catalog and agent routes inject `AgentOutputDirDep` only; general `output_dir` / `QS_DATA_DIR` cannot relocate the pool. Task creation correctly dual-wires `agent_output_dir` + `result_output_dir=output_dir`.
3. **CWD independence** — relative overrides are repo-anchored; default no longer depends on process CWD (`Path("data/agent_run")` removed from production callers in scope).
4. **Regression harness** — pure path tests, DI isolation tests, run-config env/CWD test, factors create_app isolation test, Playwright env assertion, and source-string guard form a solid contract net.
5. **Fallout hygiene** — AgentRunner/CLI rename updated in phase7/promote/propose-source-file/json-output tests; no half-migrated call sites in the commit.
6. **Safety posture preserved** — no paper/live mutation, no promote auto-commit, no candidate exec path expansion beyond the existing opt-in catalog loader.

---

### Issues

#### Critical
None.

#### Important
None that block merge for Task 1.

#### Minor

```text
[MEDIUM] Empty QS_AGENT_OUTPUT_DIR collapses to platform repo root
File: src/quant_system/agent/paths.py:19-22
Issue: resolve_agent_output_dir treats "" as an explicit override.
       Path("") anchors at PLATFORM_REPO_ROOT, so candidates become
       <repo>/agent/candidates instead of DEFAULT_AGENT_OUTPUT_DIR.
Fix: Treat falsy/blank strings as unset (`if not raw: return DEFAULT_...`)
     before anchoring. Optional hardening only.

[MEDIUM] CLI --result-output-dir is not repo-anchored
File: src/quant_system/cli.py:1757-1759
Issue: agent_output_dir goes through resolve_agent_output_dir; result_output_dir
       uses bare Path(...), so a relative value is CWD-dependent.
Fix: Anchor via the same lexical absolute helper (or a shared result-root
     resolver) if summarize is expected to be CWD-independent.

[MEDIUM] create_app tests outside the agent surface still omit agent_output_dir
File: tests/test_api_*.py (many)
Issue: Brief preferred explicit agent_output_dir on create_app construction.
       Non-agent API tests still inherit the real repo default when DI is
       resolved. Low risk unless those tests hit candidate endpoints.
Fix: Later sweep: pass agent_output_dir=tmp_path/"agent-output" in shared
     TestClient helpers, or default test factory to a temp agent root.

[LOW] Operator-facing CLI flag rename is breaking
File: src/quant_system/cli.py (agent + run-config + promote)
Issue: --output-dir / --candidates-dir removed on agent surfaces. HQA wrappers
       currently rely on defaults (no flags) so they keep working, but any
       external scripts using old flags will fail.
Fix: Tracked follow-up (report concern #1); update HQA skills/docs when
     operators need overrides.
```

---

### Assessment: **Approved**

Task 1 delivers the canonical agent-path dependency as specified:

- production callers in scope no longer use CWD-relative `data/agent_run` defaults;
- candidates are independent of `QS_DATA_DIR`;
- API isolation is via `create_app(agent_output_dir=...)` + DI;
- tests prove isolation, CWD independence, and source regression.

Ship as-is. Address empty-env / `result_output_dir` anchoring in a later integrity polish if desired; do not block this slice.
