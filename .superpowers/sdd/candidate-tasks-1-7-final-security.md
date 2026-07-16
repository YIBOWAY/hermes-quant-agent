# Final Security Review — Candidate Integrity Tasks 1–7

| Field | Value |
|-------|--------|
| **Repo** | `/Users/sunyibo/programs/ai-quant-platform` |
| **Range** | `4933b898..ae191bee` (10 commits) |
| **Scope** | Candidate path isolation, CAS, dirfd boundary, migration dry-run defaults, Gate 3 isolation, no main-worktree mutation, no auto-commit |
| **Reviewer** | Security Reviewer (final branch review) |
| **Date** | 2026-07-13 |
| **Verdict** | **CLEAR** |

No P0 or P1 findings that block merge for the stated threat model (local single-operator platform; candidate integrity and Gate 3 human gates). Residual hardening notes are documented as non-blocking P2/observations.

---

## Executive Summary

Tasks 1–7 deliver a coherent integrity boundary for agent candidates and Gate 3 promotion:

1. **Unified agent root** — API and CLI share `resolve_agent_output_dir` / `resolve_candidates_dir` (not `QS_DATA_DIR` / CWD drift).
2. **Dirfd exact-byte FS** — candidate open/read/write/publish use `O_NOFOLLOW|O_DIRECTORY|O_CLOEXEC`, single-component names, `renameat2`/`renameatx_np` no-replace, and nlink=1 regular-file rules.
3. **Immutable publication + digest-bound review CAS** — content never overwritten; approvals require `expected_manifest_digest` + `expected_status="pending"`; locks bind `(candidate_id, digest)`.
4. **Migration dry-run default** — CLI audit-only unless `--apply` and required `--backup-dir`; legacy trees are never mutated.
5. **Gate 3 isolation** — public `agent promote-candidate` materializes only into a detached managed worktree, never commits, and refuses dirty scoped paths on the main worktree.

Authorization paths (SafetyGate, research load, promote prepare/status) re-verify via `VerifiedCandidateSnapshot` / pool lock and fail closed on integrity drift. Legacy unbound locks never authorize.

---

## Commit Map (security-relevant)

| Commit | Intent |
|--------|--------|
| `5c8188a` | Unify API candidate root with CLI (`paths.py`, DI) |
| `1741f74` | Dirfd exact-byte FS boundary (`candidate_fs.py`, manifests) |
| `cb4d7e0` | Harden dirfd + approval binding |
| `51647d9` | Immutable writes + revision-bound approvals + SafetyGate on agent root |
| `ed3b9bb` | Require `expected_status` on review CAS |
| `8aaa278` | Recheck digest before research/promotion |
| `392485a` | Require revision on every review surface (API/CLI/frontend) |
| `a4252d5` | Conflict-safe candidate root migration |
| `1a6f471` | Migration backup verify + root barrier coverage |
| `ae191be` | Gate 3 isolated review worktrees (no commit) |

---

## Focus-Area Findings

### 1. Candidate path isolation — PASS

**Evidence**

- `paths.py`: repo-anchored absolute paths via lexical `os.path.abspath` (does not follow symlinks the way `Path.resolve()` would).
- `resolve_candidates_dir(agent_output_dir) → <root>/agent/candidates` is the only canonical layout.
- API injects `agent_output_dir` through `create_app` / `AgentOutputDirDep`; factors `include_candidates` uses the same root.
- Candidate IDs: `^[a-z0-9][a-z0-9_-]*$`, reserved control names blocked, no `/`, `\`, `.`, `..`.
- Artifact paths: single-component, ASCII, casefold-reserved controls blocked.
- `load_verified_candidate_snapshot` walks `agent_output → agent → candidates → id` holding FDs with identity re-checks.

**Risks checked**

| Attack | Outcome |
|--------|---------|
| Path traversal in `candidate_id` | Rejected by `_validate_candidate_id` |
| Symlink swap of agent/candidates/candidate | `O_NOFOLLOW` + `assert_entry_is_open_fd` fail closed |
| Hardlink smuggling of metadata/artifacts/locks | `st_nlink != 1` rejected |
| API/CLI root split | Closed by Task 1 DI + path helpers |

### 2. Dirfd boundary — PASS

**Evidence (`candidate_fs.py`)**

- Runtime probe for `O_NOFOLLOW`, `O_DIRECTORY`, `dir_fd`, `follow_symlinks=False`.
- Absolute open walks from `/` component-by-component.
- Writes: `O_CREAT|O_EXCL|O_NOFOLLOW`, fsync file + parent dir.
- Publish: Linux `renameat2(RENAME_NOREPLACE)` / Darwin `renameatx_np(RENAME_EXCL)`.
- Pool lock: exclusive `flock` on verified single-link regular `.candidate-pool.lock`, with pre/post identity checks.
- No `Path.open` / path-string `os.replace` on trusted candidate content writes.

Tests cover symlink/hardlink/lock corruption (`test_candidate_manifest.py`, `test_candidate_repository.py`).

### 3. CAS / revision binding — PASS

**Review CAS (`CandidatePool.review`)**

Required inputs:

- `expected_manifest_digest` — lowercase 64-hex
- `expected_status` — literal `"pending"` only
- Decision under `locked_candidates_root`
- Full re-verify via `_verify_from_opened` before lock write
- Digest mismatch → `CandidateStaleError`
- Non-pending / existing decision → `CandidateReviewStateStaleError`
- Decision lock: structured JSON with `schema_version`, `candidate_id`, `manifest_digest`; exclusive no-replace write; post-read byte equality

**Surfaces enforcing CAS**

| Surface | Enforcement |
|---------|-------------|
| CLI `agent review` | Required `--expected-digest`, `--expected-status` |
| API `POST .../review` | Pydantic: digest pattern + `expected_status: Literal["pending"]` |
| Frontend `AgentTaskForm` | Sends digest + `"pending"`; UI disabled unless `approval_enabled` and verified digest |
| SafetyGate | `approval_binding == "approved"` only (digest-bound lock parse) |
| Research load | Last-moment `load_verified_candidate_snapshot`; legacy unbound never loads |
| Gate 3 prepare | `expected_candidate_digest` rechecked multiple times under promotion lock |

Legacy `approved.lock` / unbound / multi-control → `legacy_unbound` → never authorizes.

### 4. Migration dry-run-only defaults — PASS

**Evidence**

- Module contract: audit is read-only (`create=False`, no locks/backups/manifests).
- CLI `agent migrate-candidates`: `--apply` defaults **False**; apply requires `--backup-dir`.
- Tests: dry-run leaves no manifest; `--apply` without backup exits non-zero.
- Apply refuses conflicts, re-validates root `(st_dev, st_ino)`, backs up first with byte-equal verify, publishes via exclusive staging + noreplace rename.
- Legacy source trees are **never mutated** (copy-out only; decision locks renamed only in staging/canonical).
- Planned-path overlap (legacy/canonical/backup) fail closed; held-FD identity collision fail closed.
- No HTTP migration apply route (CLI-only operator tool).

### 5. Gate 3 isolation — PASS

**Evidence (`promotion_workspace.py` + CLI)**

Public `agent promote-candidate`:

1. Requires approved candidate + exact digest + base commit equal to **main HEAD**.
2. Refuses dirty/untracked **scoped** paths on main worktree (does not require a clean entire tree — unrelated dirt is allowed).
3. `git worktree add --detach` under managed worktree root (default temp managed root).
4. Materializes via internal `promote_candidate` **only** into that worktree’s library/tests paths.
5. Captures scoped binary patch; replay-verifies on a second detached worktree.
6. Publishes immutable promotion records (`scoped.patch`, `manifest.v1.json`, `state.json`).
7. Status: **awaiting_human_commit** — system does not commit.

`promote_candidate` remains an internal materializer (no git, no network); production call graph is workspace-only (plus unit tests).

### 6. No main-worktree mutation — PASS

| Operation | Main worktree effect |
|-----------|----------------------|
| prepare | Read-only checks (`rev-parse`, `status` on scoped paths); writes only managed worktree + promotion records under agent output |
| status | Observes managed worktree; may update promotion `state.json` only |
| cleanup | Removes managed worktree registration; does not rewrite main tree files |

Tests: unrelated main dirt ignored; dirty scoped path refused without mutating main; main fingerprints preserved on refusal paths.

### 7. No auto-commit — PASS

- No `git commit` / `merge` / `push` / branch creation in production prepare/status/cleanup paths.
- Human instructions explicitly state the system will not commit.
- Cleanup requires either durable reviewed evidence (named branch, single commit beyond base, exact path set + blob digests + patch equality) or explicit `--abandon`.
- Detached HEAD human commit without named branch is refused.
- CLI docstring: `NEVER commits`.

---

## OWASP / Pattern Checklist (scoped)

| Check | Result |
|-------|--------|
| Injection (path / shell) | Git via `subprocess` argv lists, `shell=False`; path components validated |
| Broken auth / approval | Digest-bound locks; CAS; no auto promotion |
| Sensitive data | No secrets introduced; candidate source is operator data |
| Broken access | Review/promote require revision; migration not on API |
| Misconfiguration | Migration default dry-run; promote does not enable live trading |
| XSS | Frontend only posts structured JSON CAS fields (no raw HTML sinks in this range) |
| Insecure deserialization | JSON via stdlib + Pydantic schema; no pickle |
| Logging | Review audit records CAS inputs, not credentials |

---

## Residual Observations (non-blocking)

These do **not** violate the Task 1–7 acceptance criteria or produce a BLOCKED verdict under the local single-operator model.

### OBS-1 (P2) — Display-only Path I/O outside dirfd boundary

`api/routes/agent.py` merges `reviews.jsonl` via `Path.exists` / `read_text`, which **follows** a final-component symlink. Authorization never uses this content, but a local adversary who can plant `reviews.jsonl` as a symlink could leak arbitrary readable file bytes into the detail API response.

Same class of residual: audit log `glob` + `read_text` for display.

**Hardening (optional):** read through dirfd `read_regular_bytes_at` (or refuse symlinks with `lstat` + `S_ISLNK`).

### OBS-2 (P2) — Managed worktree root under shared temp

`DEFAULT_MANAGED_WORKTREE_ROOT = Path(tempfile.gettempdir()) / "ai-quant-platform-gate3-worktrees"`. On multi-user systems with a shared `/tmp`, a pre-created attacker-owned directory could observe or interfere with worktrees. macOS user-specific temp dirs mitigate this in the primary deployment.

**Hardening (optional):** default under agent output or `XDG_RUNTIME_DIR` with `0o700` ownership checks.

### OBS-3 (P2) — Component validator allows NUL ASCII

`_validate_single_component` requires `isascii()` but does not reject `\x00`. Python’s `os.open` raises `ValueError` (fail closed), but explicit rejection would be cleaner.

### OBS-4 (info) — Internal `promote_candidate` remains a callable materializer

Still importable and can write to caller-supplied library/tests roots. Public CLI no longer points it at the main tree. Keep it non-exported from operator docs; do not re-add a direct CLI that targets the main worktree.

---

## P0 / P1 List

| Severity | Finding |
|----------|---------|
| **P0** | *(none)* |
| **P1** | *(none)* |

---

## Verdict

### **CLEAR**

Candidate Integrity Tasks 1–7 meet the security bar for:

- candidate path isolation  
- dirfd exact-byte boundary  
- digest + status CAS on all review surfaces  
- migration dry-run-only defaults with conflict-safe apply  
- Gate 3 detached worktree isolation  
- no main-worktree mutation by prepare  
- no automatic git commit  

Residual notes (OBS-1–4) are defense-in-depth improvements, not merge blockers for this branch.

---

## Review Method

- Full commit list + diffstat for `4933b898..ae191bee` (41 files, ~9.1k insertions)
- Line-level review of: `candidate_fs.py`, `candidate_manifest.py`, `candidate_pool.py`, `candidate_migration.py`, `promotion_workspace.py`, `promote.py`, `promotion.py`, `safety.py`, `paths.py`, `cli.py` agent commands, `api/routes/agent.py`, `api/schemas/agent.py`, frontend review form CAS
- Grep for `git commit`, shell=True, path writes, CAS field plumbing
- Cross-check against adversarial tests: symlink/hardlink/lock, migration dry-run CLI, promotion dirty main / no-commit / branch requirements

---

## Sign-off

| Item | Status |
|------|--------|
| CRITICAL secrets in range | None found |
| Auto-commit / main-tree promote write | Not present on public path |
| Migration silent apply | Not present |
| CAS bypass on review API/CLI/UI | Not present |
| **Final verdict** | **CLEAR** |
