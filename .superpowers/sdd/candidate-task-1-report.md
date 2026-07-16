# Candidate Integrity Task 1 Report

**Task:** Canonical agent path dependency  
**Platform branch:** `audit-remediation-2026-06-23`  
**BASE:** `4933b898fbfe82208cb42eb63c11dfd366341835`  
**Status:** COMPLETE  

## Commit

| SHA | Subject |
|-----|---------|
| `5c8188a62b395acfab2f47633e28ad25851eb943` | `feat(agent): unify API candidate root with CLI source of truth` |

Short: `5c8188a`

**Not pushed** (controller owns platform push).

**Preserved dirty/untracked (not staged):**
- `data/options_universe/earnings_calendar.csv`
- `.understand-anything/diff-overlay.json`

## What changed

### New modules
- `src/quant_system/agent/paths.py`
  - `PLATFORM_REPO_ROOT`, `DEFAULT_AGENT_OUTPUT_DIR`, `DEFAULT_LEGACY_CANDIDATES_DIR`
  - `resolve_agent_output_dir(explicit=None)` — explicit arg → `QS_AGENT_OUTPUT_DIR` → repo-anchored `data/agent_run`
  - `resolve_legacy_candidates_dir(...)`
  - `resolve_candidates_dir(agent_output_dir)` → `{agent_output_dir}/agent/candidates`
  - Relative overrides are repo-anchored via lexical `os.path.abspath` (no symlink follow)
- `tests/test_agent_paths.py` — default/env/CWD independence, relative anchoring, source regression

### DI / API
- `build_services` / `create_app` accept additive `agent_output_dir`
- `AgentOutputDirDep` injected into:
  - all `/api/agent/*` candidate/task/review routes
  - `/api/factors?include_candidates=true`
- Removed module-level `AGENT_CANDIDATES_DIR` / `_REPO_ROOT` from `routes/factors.py`
- Agent routes no longer use general `OutputDirDep` for candidates; task creation passes both `agent_output_dir` (candidates/audit) and `result_output_dir`/`output_dir` (experiment reads)

### AgentRunner
- Required `agent_output_dir` for `CandidatePool` + `AgentAuditLog`
- Optional `result_output_dir` for experiment/result reads (summarize); never a candidate-root fallback from general data

### CLI
- All agent commands use `--agent-output-dir` (default `None` → resolver), no `"data/agent_run"` string defaults
- `experiment run-config`: removed `--candidates-dir`; uses `--agent-output-dir` + `resolve_candidates_dir(resolve_agent_output_dir(...))`
- `promote-candidate`: removed public `--candidates-dir` bypass; resolves candidates via agent root

### Playwright
- Sets `QS_AGENT_OUTPUT_DIR: path.join(e2eDataRoot, "agent-output")` beside `QS_DATA_DIR` so e2e general data does not relocate candidates

### Tests updated (task + fallout)
- Brief files: `test_api_agent.py`, `test_cli_experiment_provider.py`, `test_factor_registry_factory.py`, `test_frontend_e2e_config.py`
- Fallout from AgentRunner/CLI rename: `test_agent_phase7.py`, `test_agent_propose_source_file.py`, `test_agent_promote.py` (CLI promote only), `test_cli_json_output.py`

## Test summary

Command (brief + fallout):

```bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_paths.py \
  tests/test_api_agent.py \
  tests/test_cli_experiment_provider.py \
  tests/test_factor_registry_factory.py \
  tests/test_frontend_e2e_config.py \
  tests/test_agent_phase7.py \
  tests/test_agent_propose_source_file.py \
  tests/test_agent_promote.py::test_cli_promote_candidate_prints_files_and_gate3_line \
  tests/test_agent_promote.py::test_cli_promote_candidate_refusal_exits_nonzero \
  tests/test_cli_json_output.py
```

**Result:** 60 passed (1 Starlette/httpx deprecation warning only).

Contracts verified:
- Injected `agent_output_dir` isolated from general `output_dir` / `QS_DATA_DIR`
- Task writes candidates + audit only under agent root
- Repo default `…/data/agent_run` is CWD-independent; env override works
- `/api/factors?include_candidates=true` uses create_app agent root
- run-config approved-candidate loader is CWD-independent via `QS_AGENT_OUTPUT_DIR` / `--agent-output-dir`
- Playwright config asserts `QS_AGENT_OUTPUT_DIR`
- Source regression: no `Path("data/agent_run")`, `"data/agent_run"` defaults, `AGENT_CANDIDATES_DIR`, or candidate-adjacent `QS_DATA_DIR` in active consumers

## Concerns / follow-ups

1. **Agent CLI flag rename is a breaking UX change** for operators/scripts still using `--output-dir` / `--candidates-dir` on agent commands and `experiment run-config`. HQA wrappers/skills may need a later task to pass `--agent-output-dir` / `QS_AGENT_OUTPUT_DIR`.
2. **`AgentRunner(output_dir=...)` keyword removed.** Direct unit call sites outside the updated tests would TypeError; fallout tests above were fixed.
3. **`load_approved_factor_candidates` still takes `candidates_dir`** (not `agent_output_dir`). CLI resolves candidates once then passes the directory — correct for Task 1; later integrity tasks may re-verify via agent root.
4. **Default production API** without `agent_output_dir`/`QS_AGENT_OUTPUT_DIR` now uses repo-anchored `data/agent_run` (aligned with CLI), not `settings.data.data_dir`. This intentionally fixes the prior API/CLI split.
5. **No migration, no paper/live mutation, no Hermes chat** — as required.
6. **Promote CLI** still materializes into the main worktree library/tests paths (existing Gate 3 materializer); workspace isolation is a later task.

## Files in commit (18)

```
src/quant_system/agent/paths.py          (new)
src/quant_system/agent/runner.py
src/quant_system/api/bootstrap.py
src/quant_system/api/server.py
src/quant_system/api/dependencies.py
src/quant_system/api/routes/agent.py
src/quant_system/api/routes/factors.py
src/quant_system/cli.py
src/frontend/playwright.config.ts
tests/test_agent_paths.py               (new)
tests/test_api_agent.py
tests/test_cli_experiment_provider.py
tests/test_factor_registry_factory.py
tests/test_frontend_e2e_config.py
tests/test_agent_phase7.py
tests/test_agent_promote.py
tests/test_agent_propose_source_file.py
tests/test_cli_json_output.py
```
