# Candidate Task 7 — Python / Spec Review

**Task:** Persistent isolated Gate 3 worktree and scoped patch  
**Package:** `1a6f471..ae191be` (`feat(agent): prepare Gate 3 diffs in isolated review worktrees`)  
**Files reviewed:**
- `src/quant_system/agent/promotion_workspace.py` (new, ~1192 lines)
- `src/quant_system/agent/promote.py` (docstring-only public-contract update)
- `src/quant_system/cli.py` (prepare / status / cleanup public surface)
- `tests/test_promotion_workspace.py` (43 tests)
- `tests/test_agent_promote.py` (CLI contract update)

**Diagnostics run:**
- `pytest -q tests/test_agent_promote.py tests/test_promotion_workspace.py tests/test_agent_promotion.py` → **95 passed**
- `ruff check` on promote / promotion_workspace / test_promotion_workspace → **clean**
- `grep promote_candidate(` on `cli.py` → only `def agent_promote_candidate` (no materializer call)
- Manual check: working-tree patch after `--intent-to-add` is byte-identical to `BASE..HEAD` commit-range patch with the same diff options

---

## Assessment: **Approved**

No CRITICAL or HIGH findings that break the Gate 3 isolation / fail-closed contract. MEDIUM items below are follow-ups, not merge blockers.

---

## Spec compliance

| Requirement | Verdict |
|-------------|---------|
| `prepare_promotion_workspace` via `CandidatePool` + digest re-verify | **PASS** — pre-lock, under lock before materialize, again before publish |
| Public CLI only: `--candidate-id`, `--expected-digest`, `--base-commit` | **PASS** — no library/tests/repo/worktree/agent-output path options |
| Missing required option → exit 2, no mutation | **PASS** — parametrized CLI test |
| stdout exactly `{promotion_id, worktree, patch, manifest}`; human steps on stderr | **PASS** |
| `promotion-status` / `cleanup-promotion` promotion-id only; `--abandon` optional | **PASS** |
| Git via argv arrays, `shell=False` only | **PASS** |
| Detached worktree; no branch/commit/push/merge by system | **PASS** |
| Scoped paths only: factor module, package `__init__.py`, generated test | **PASS** |
| Immutable `manifest.v1.json` (no abs paths/clock); mutable `state.json` | **PASS** |
| Deterministic `promotion_id`; idempotent same facts | **PASS** |
| State untrusted; identity bind + registration; fail closed even with `--abandon` | **PASS** — 8 mutations × {default, abandon} |
| Main dirty unrelated paths preserved; scoped dirty refused | **PASS** |
| Status uses `BASE..HEAD` patch, not empty worktree diff | **PASS** |
| Cleanup refuses uncommitted / detached-unreferenced; named branch unlocks | **PASS** |
| Pure materializer remains git/process-free; CLI does not call `promote_candidate` | **PASS** — AST + static import tests |

---

## Findings

### [MEDIUM] `_worktree_remove(force=False)` silently escalates to `--force`

**File:** `src/quant_system/agent/promotion_workspace.py:334-355`

**Issue:** When `force=False` and `git worktree remove` fails, the helper always retries with `--force`. That makes the parameter a soft hint rather than a hard policy. Default (reviewed) cleanup is the only non-abandon caller of `force=False`; it only reaches removal after a clean reviewed-commit check, so this is not a Gate 3 evidence bypass, but it weakens the API contract and can mask unexpected worktree state.

**Fix:** Only escalate when `force=True` (or a separate `allow_force_fallback` used exclusively by abandon / internal staging-replay cleanup). On non-force failure, raise `PromotionWorkspaceError` with stderr.

---

### [MEDIUM] Abandoned / missing worktree blocks re-prepare of the same facts

**File:** `src/quant_system/agent/promotion_workspace.py:706-723`

**Issue:** Idempotent prepare requires the managed worktree directory to still exist. After `--abandon` (or manual worktree deletion), the immutable promotion directory remains and re-prepare of the same candidate/digest/base refuses with “missing managed worktree” until the operator deletes the promotion record by hand. Report acknowledges this; workflow recovery is rough.

**Fix (optional product hardening):** If existing status is `abandoned` and manifest/patch still match, recreate the worktree and rewrite state to `awaiting_human_commit`; or document an explicit `agent reset-promotion` / allow re-prepare to reclaim abandoned IDs.

---

### [MEDIUM] CLI imports private `_human_instructions`

**File:** `src/quant_system/cli.py:1966`

**Issue:** Public CLI reaches into a private helper. Breaks encapsulation and makes renames/refactors of the workspace module leak into CLI.

**Fix:** Export a public `format_human_instructions(...)` (or fold text into `prepare_cli_payload` / a small public DTO) and import only public names from `promotion_workspace`.

---

### [MEDIUM] Narrow orphan-worktree window after `worktree move`

**File:** `src/quant_system/agent/promotion_workspace.py:737-770`

**Issue:** After `_worktree_move` succeeds, `staging` is set to `None`. If `_dir_identity` / model build fails before the inner publish `try`, the outer `except` only removes `staging` and will not remove `final_worktree`. Probability is low (identity/stat rarely fails), but a crash in that window leaves a registered managed worktree without promotion records.

**Fix:** Track `published_worktree` separately and always force-remove it in the outer cleanup path until exclusive patch/manifest/state writes succeed.

---

### [MEDIUM] `os.write` used without a full-write loop

**File:** `src/quant_system/agent/promotion_workspace.py:567-590`

**Issue:** `_write_bytes_exclusive` / `_write_bytes_replace` call `os.write(fd, payload)` once. POSIX allows short writes; a partial exclusive write would publish a truncated patch/manifest under `O_EXCL` with no retry.

**Fix:** Loop until all bytes are written (or use a helper that does), and prefer the existing dirfd atomic writers from `candidate_fs` if promotion records should share that boundary.

---

### [MEDIUM] Manifest digest re-read does not use the nofollow reader

**File:** `src/quant_system/agent/promotion_workspace.py:883-885`

**Issue:** Manifest/state content is parsed via `_read_nofollow_regular`, but `manifest_sha` is computed with `manifest_path.read_bytes()` after a prior `is_symlink` check. That is a small TOCTOU/inconsistency versus the nofollow boundary used elsewhere.

**Fix:** Hash the same bytes returned by `_read_nofollow_regular` (or re-read with it) for `state.manifest_sha256` comparison.

---

### [MEDIUM] Orchestrator size / parameter surface

**File:** `src/quant_system/agent/promotion_workspace.py` (`prepare_promotion_workspace` ~175 lines; 7 kw-only params)

**Issue:** Exceeds the shop guideline of &lt;50 lines / ≤5 params. Logic is correctly lock-scoped and tested, but harder to review incrementally.

**Fix (non-blocking):** Extract “preflight”, “materialize+patch+replay”, and “publish records” helpers; optionally pack roots into a small `PromotionRoots` dataclass.

---

## What looks solid

- Fail-closed state schema (`extra="forbid"`), promotion-id lexical validation, managed-root + repo `st_dev`/`st_ino` binding, and git worktree registration checks before status/cleanup mutation.
- Pure materializer preserved: no git/process imports; public CLI only calls `prepare_promotion_workspace`.
- Isolation: unrelated main dirty fingerprints preserved; scoped dirty / base mismatch / candidate drift / existing targets refused.
- Patch pipeline: `--binary --full-index` capture, intent-to-add without staged content, internal replay apply + per-file SHA-256, committed-range patch equality for status.
- Tests are substantive (isolation, CLI contracts, 16 state-injection cases, tamper rejection, abandon audit retain), not smoke-only.
- No `shell=True`, `eval`/`exec`, unsafe deserialization, or hardcoded secrets.

---

## Residual risk (accepted)

- Managed worktrees live under process tempdir (`tempfile.gettempdir()/ai-quant-platform-gate3-worktrees`); durability across reboot is OS-dependent (noted in implementer report).
- Status/cleanup do not share the prepare flock; concurrent local status+cleanup is a minor race, fail-closed in practice.
- Internal Python API still accepts explicit `repo_dir` / `worktree_root` / `promotion_root` (required for tests); production CLI pins fixed resolvers.

---

## Verdict

**Approved** — implements the Task 7 Gate 3 isolation contract with strong tests and fail-closed state handling. Address MEDIUM items in a follow-up cleanup pass if desired; none block merge of `ae191be`.
