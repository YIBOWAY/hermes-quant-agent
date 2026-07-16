# Security Review: Candidate Task 7 (Isolated Gate 3 Worktree)

**Reviewer role:** Security Reviewer (read-only)  
**Scope:** `1a6f471a39b531c403e774cdf86cc07638c1d43e` → `ae191bee4fbf63a6a391624bd62958046af8858c`  
**Platform commit:** `ae191be` — `feat(agent): prepare Gate 3 diffs in isolated review worktrees`  
**Files:** `promotion_workspace.py` (new), `promote.py` (docstring only), `cli.py`, `tests/test_promotion_workspace.py` (new), `tests/test_agent_promote.py`  
**Date:** 2026-07-13  

## Verdict

**Assessment: Approved**

All six critical checks pass. No CRITICAL or HIGH findings on the public Gate 3 surface. Residual MEDIUM/LOW notes are local multi-process / multi-user hardening follow-ups and do not block this isolation delivery.

## Critical checks

| Check | Result | Evidence |
|-------|--------|----------|
| Never commits / merges / pushes | **PASS** | Prepare uses only `worktree add --detach`, `add --intent-to-add`, `diff`, `apply` (replay only), `worktree move/remove/prune`. Status is read-only git plus mutable `state.json` update. Cleanup is `worktree remove` only. The only `git switch`/`commit` strings are human stderr instructions. `shell=True` absent (`shell=False` ×4). |
| Never mutates user's dirty main worktree | **PASS** | Materializer roots are `worktree / promoted` and `worktree / tests/factors` only. Main tree gets read-only `rev-parse` / scoped `status`. Unrelated dirty path fingerprint preserved (`test_promotion_uses_detached_worktree_and_ignores_unrelated_main_dirty`). Scoped dirty in main is refused. |
| Prepare requires candidate-id + expected-digest + base-commit | **PASS** | CLI `agent_promote_candidate(candidate_id, expected_digest, base_commit)` — no defaults, no path options. Missing any option → Typer exit 2 before mutation (`test_cli_missing_required_exits_2_without_mutation` fingerprints candidates/repo/promo/worktree). Help asserts no `--library-dir`/`--tests-dir`/`--agent-output-dir`/`--worktree`. |
| Cleanup needs reviewed-commit evidence or `--abandon` | **PASS** | Default cleanup re-runs full `_evaluate_reviewed_commit` (main HEAD==base, clean worktree, exactly one commit beyond base, parent==base, named local branch contains HEAD, exact three-path `diff-tree`, per-blob mode/SHA-256, candidate re-verify, `BASE..HEAD` patch bytes + digest == prepared patch). Failure → `PromotionWorkspaceError`. `--abandon` is opt-in (`False` default); retains audit state `abandoned`. Uncommitted + detached-unreferenced refuse tests covered. |
| Digest re-verify before materialize | **PASS** | `_load_verified_approved` via `CandidatePool.get` + expected 64-hex digest + `approval_binding=="approved"`: (1) pre-lock, (2) under exclusive promotion-root lock immediately before `worktree add` / materialize, (3) again after replay before publishing immutable records. Materializer also binds `expected_candidate_digest` to in-memory snapshot bytes. Drift → no promotion record; staging/replay removed. |
| Tests only use temp git repos | **PASS** | All fixtures via `_git_repo(tmp_path)` under pytest `tmp_path`. CLI success/missing-option tests monkeypatch `resolve_platform_repo` / `resolve_managed_worktree_root` and set `QS_AGENT_OUTPUT_DIR` to temp agent root. No live platform worktree mutation in tests. |

## OWASP / threat-oriented review

### Injection / command execution

- All Git invocations are argument arrays with `shell=False` (`_git_text`, `_git_bytes`, replay `git apply`).
- No `os.system`, no shell string interpolation of candidate IDs, digests, or paths into a shell.
- `base_commit` is passed as a single argv element to `rev-parse --verify REF^{commit}` then must equal main `HEAD` (resolved full object name).
- Scoped paths are derived from AST-validated `factor_id` (`^[A-Za-z][A-Za-z0-9_]*$` in `promote.py`) under fixed relative roots — no `../` module names.
- `validate_promotion_id` rejects empty, `.`/`..`, `/` `\`, absolute, and non-`[a-z0-9][a-z0-9_-]{0,120}` IDs before state lookup.

### Path traversal / worktree escape

- Public CLI never accepts repo/worktree/promotion/candidate path overrides; always `resolve_platform_repo()`, `resolve_managed_worktree_root()`, `default_promotion_root(resolve_agent_output_dir())`.
- Status/cleanup derive the worktree as `worktree_root / promotion_id` and require `state.worktree_path` equality; state path alone cannot redirect removal.
- State binds fixed platform repo and managed-root identity via `st_dev`/`st_ino` (`follow_symlinks=False`).
- Symlink promotion dir, symlink promotion files, symlink managed worktree child → fail closed.
- Nested / outside / main-repo / other-repo / wrong-id / wrong-manifest / wrong-repo-identity state injections refuse for both default cleanup and `--abandon` (16 cases) and leave main/other/outside/patch/manifest/candidate/worktree-registry fingerprints unchanged.
- Manifest/state reads use `open_absolute_directory` + `read_regular_bytes_at` (nofollow final component).
- Immutable records published with `O_EXCL`; patch/manifest exclude absolute worktree/candidate roots and wall clock.

### Broken access / Gate 3 authority

- Public prepare no longer materializes into the main tree; `cli.py` does not import or call `promote_candidate`.
- AST/source test: `agent_promote_candidate` calls only `prepare_promotion_workspace`.
- Approval authority still requires digest-bound `approval_binding=="approved"` via pool verification — not legacy locks.
- System never creates branch/commit; human named branch + commit is the Gate 3 completion signal.
- Reviewed acceptance requires commit-range patch equality (`BASE..HEAD`), not empty working-tree `git diff` (explicit regression test).
- Tampered worktree content after prepare is not accepted as reviewed.
- Pure materializer remains process/git-free (`test_promote_module_still_git_free`).

### Sensitive data / secrets

- No hardcoded secrets, tokens, or credentials in the diff.
- CLI stdout is deterministic JSON path/id metadata; human instructions on stderr.
- Candidate source appears in managed review worktrees and scoped patch files under agent promotions — expected for local Gate 3 review.

### Misconfiguration / defaults

- `--abandon` defaults false; only force/removal escape for unreviewed workspaces after full state validation still fails closed on invalid state.
- Managed worktree root: `tempfile.gettempdir()/ai-quant-platform-gate3-worktrees` (CLI fixed; not attacker-selectable via public options).
- Prepare refuses existing factor/test at base, dirty scoped paths in main, base≠HEAD, unapproved/mismatched digest candidates.

### Race / TOCTOU

- Exclusive `fcntl` lock on promotion root for prepare critical section; HEAD==base and scoped-status re-checked under lock; candidate re-verified under lock before materialize and again before publish.
- Concurrent same-id idempotency: existing matching manifest/patch returns durable paths; conflicting facts refuse.
- Status/cleanup do **not** take the same flock (see residual).

### Dependency / logging

- No new third-party dependencies.
- Failures surface as `promotion_*_refused reason=...` without embedding secrets beyond operator-visible paths/ids.

## Residual findings (non-blocking)

### MEDIUM — Status/cleanup omit promotion-root flock

**Location:** `promotion_status`, `cleanup_promotion_workspace` vs `_promotion_root_lock` in prepare only.

**Impact:** Concurrent prepare (idempotent re-entry) and cleanup/`--abandon` on the same promotion id can race: e.g. abandon removes the managed worktree while re-prepare expects it, or dual cleanup double-`worktree remove`. Failures are local operator inconsistency / refuse, not silent main-tree materialization. Shared object DB commits already made by the human remain (by design).

**Recommendation (follow-up):** Acquire the same exclusive promotion-root lock (or a per-promotion lock) around status state writes and cleanup removal + state update.

### LOW — Managed worktree root under process tempdir

**Location:** `DEFAULT_MANAGED_WORKTREE_ROOT = Path(tempfile.gettempdir()) / "ai-quant-platform-gate3-worktrees"`.

**Impact:** On multi-user Linux where `gettempdir()` is shared `/tmp`, a pre-created attacker-owned managed root could observe or interfere with worktree directories. macOS user-private temp dirs largely mitigate this. Single-operator local Gate 3 model matches product assumptions.

**Recommendation (follow-up):** Prefer a user-owned cache path (e.g. under agent output or `XDG_CACHE_HOME`) with `0o700` mkdir, without changing the public CLI contract.

### LOW — Internal Python API accepts arbitrary `worktree_root` / `repo_dir`

**Location:** `prepare_promotion_workspace(...)` kwargs used by tests.

**Impact:** A non-CLI caller could point `worktree_root` inside the main working tree and create a nested detached worktree directory there. Public CLI always pins `resolve_managed_worktree_root()` and `resolve_platform_repo()`, so the operator entry point is safe.

**Recommendation (follow-up):** Refuse when managed root identity is inside `repo_dir` (or require `worktree_root` resolve outside repo) even for the Python API.

### LOW — `_worktree_remove(..., force=False)` falls back to `--force`

**Location:** `_worktree_remove` last-resort force on any non-zero remove.

**Impact:** Default cleanup after durable review evidence may force-remove if plain remove fails. Does not bypass the reviewed-commit gate (force only runs after evaluation succeeded, or on abandon/staging rollback). Slightly broader than “force only for abandon.”

**Recommendation (follow-up):** Reserve force fallback for `force=True` / abandon / internal staging-replay cleanup only; surface plain-remove failures on reviewed cleanup.

### INFO — Path-based state replace after nofollow validation

State updates use `O_EXCL` temp + `os.replace` on path strings rather than dirfd primitives used for candidate FS. Promotion dir/file symlink checks run first; residual TOCTOU requires local FS write races. Acceptable for local operator CLI; align with dirfd style if promotion records ever become a multi-tenant surface.

## Critical-check detail

### 1. No commit / merge / push

Automated git surface:

| Phase | Commands |
|-------|----------|
| Prepare | `rev-parse`, `status`, `cat-file`, `worktree add --detach`, `add --intent-to-add`, `diff` / `diff --cached`, `worktree move`, `worktree remove`/`prune`, replay `apply` |
| Status | `rev-parse`, `status`, `rev-list`, `for-each-ref`, `diff-tree`, `ls-tree`, `show`, `diff BASE..HEAD` |
| Cleanup | `worktree remove` (+ prune); optional force only for abandon/rollback paths |

Human-only next steps (stderr): `git switch -c codex/promotion-{id}`, scoped `git add`, human commit.

### 2. Main dirty isolation

```text
prepare
  → refuse dirty scoped paths on main (allow unrelated dirty)
  → git worktree add --detach STAGING BASE   # not main WT files
  → promote_candidate(..., library_dir=STAGING/..., tests_dir=STAGING/...)
  → intent-to-add + scoped patch inside staging only
  → publish under managed root + agent promotions/
```

Main `.git` gains worktree registration metadata only (expected); working-tree content for unrelated dirty files unchanged.

### 3. Public prepare contract

```python
def agent_promote_candidate(
    candidate_id: ...,      # required
    expected_digest: ...,   # required
    base_commit: ...,       # required
) -> None:
    agent_root = resolve_agent_output_dir()  # no CLI override
    prepare_promotion_workspace(
        repo_dir=resolve_platform_repo(),
        ...,
        worktree_root=resolve_managed_worktree_root(),
    )
```

Stdout exactly `{promotion_id, worktree, patch, manifest}`.

### 4. Cleanup gating

```text
cleanup(abandon=False)
  → validate promotion_id + untrusted state schema + identities + registration
  → _evaluate_reviewed_commit (full durable evidence)
  → only then worktree remove; state status=cleaned + reviewed_commit

cleanup(abandon=True)
  → same validation (invalid state still refuses)
  → force-remove managed worktree path only
  → retain state status=abandoned (patch/manifest kept)
```

### 5. Digest re-verify timeline

```text
pre-lock:     CandidatePool.get + digest + approved
under lock:   re-get + digest + approved  →  materialize(snapshot, expected_digest)
post-replay:  re-get + digest  →  only then O_EXCL manifest/patch/state
status/clean: re-get + digest again inside reviewed evaluation
```

### 6. Test hygiene

| Control | Status |
|---------|--------|
| Git repos under `tmp_path` only | Yes |
| CLI monkeypatches platform/managed roots | Yes |
| State-injection refuses even with `--abandon` | Yes (8 mutations × 2) |
| Invalid promotion IDs never touch promo root | Yes |
| Real platform main dirty tree used as test repo | No |

## Test security coverage (relevant)

- Detached worktree ≠ main; unrelated main dirty fingerprint stable  
- Candidate digest drift / unapproved refuse  
- Base ≠ HEAD refuse  
- Existing scoped target at base refuse  
- Dirty scoped path in main refuse  
- No automatic commit; idempotent prepare  
- Three-path `--binary --full-index` patch + replay byte/digest match  
- Status uses commit-range patch, not empty WT diff  
- Tampered commit rejected  
- Uncommitted + detached-unreferenced cleanup refuse; named branch unlocks  
- Abandon removes worktree, keeps patch/manifest audit  
- 16 state-injection refuse cases (default + abandon)  
- Invalid promotion IDs before lookup  
- CLI missing required options exit 2, no mutation  
- CLI help contracts; AST no direct materializer call  
- `promote.py` still git/process free  

## Success metrics

| Metric | Status |
|--------|--------|
| No CRITICAL issues | Met |
| No HIGH issues | Met |
| No secrets in code | Met |
| Critical Gate 3 isolation invariants | Met |
| Security checklist for this task | Complete |

## Conclusion

Task 7 correctly moves public Gate 3 prepare into a persistent detached review worktree with digest-bound re-verification, immutable scoped patch/manifest, untrusted-state fail-closed status/cleanup, and no automated commit/merge/push. The public CLI cannot aim materialization or cleanup at arbitrary paths. Residual notes are concurrency flocking and multi-user temp-root hardening, not merge blockers for this isolation slice.

**Assessment: Approved**
