### Task 7: Persistent isolated Gate 3 worktree and scoped patch

**Files:**

- Create: <code>src/quant_system/agent/promotion_workspace.py</code>
- Create: <code>tests/test_promotion_workspace.py</code>
- Modify: <code>src/quant_system/agent/promote.py</code>
- Modify: <code>src/quant_system/cli.py</code>

**Interfaces:**

- Internal <code>prepare_promotion_workspace</code> returns <code>PromotionWorkspaceResult</code> from explicit repository, agent-output root, candidate ID, expected digest, base commit, promotion root, and worktree root keyword arguments. It resolves the candidate only through <code>CandidatePool(agent_output_dir)</code> and re-verifies immediately before materialization.
- Existing public <code>agent promote-candidate</code> becomes the only prepare entry and delegates to <code>prepare_promotion_workspace</code>. The old direct main-worktree materializer flags/path are removed or rejected; <code>promote_candidate</code> remains internal Python only.
- Exact public prepare contract is <code>agent promote-candidate --candidate-id ID --expected-digest SHA256 --base-commit COMMIT</code>. All three options are required; there is no public candidates/library/tests/repo/promotion/worktree path option. Missing any required option exits 2 before resolver, candidate, git, state, or worktree mutation.
- Prepare stdout is one JSON object with exactly <code>promotion_id</code>, <code>worktree</code>, <code>patch</code>, and <code>manifest</code>. Human instructions go to stderr so callers can parse stdout deterministically.
- Exact status contract is <code>agent promotion-status --promotion-id ID</code>. Exact cleanup contract is <code>agent cleanup-promotion --promotion-id ID [--abandon]</code>. They locate repo/candidate/worktree from the validated immutable manifest, audited mutable state, and standard resolver; they accept no candidate, digest, base, repo, worktree, or state-path override. <code>--abandon</code> is false by default and is the only force/removal escape for an unreviewed workspace.
- No shell strings: Git calls are argument arrays with <code>shell=False</code>.
- Output persists under <code>resolve_agent_output_dir()/agent/promotions/{promotion_id}</code>; detached worktree persists under a repo-independent managed temp root until explicit cleanup.
- The system creates neither branch nor commit. After reviewing the exact scoped diff, the human creates a named branch in the worktree and commits; cleanup refuses a detached commit that is not reachable from a named local branch unless the human explicitly uses <code>--abandon</code>.
- The only scoped paths are promoted factor module, promoted package <code>__init__.py</code>, and generated factor test.
- <code>manifest.v1.json</code> is immutable and deterministic: it contains no absolute candidate/worktree/promotion path, wall clock, or current date. A separate mutable <code>state.json</code> stores the managed worktree path and lifecycle. <code>promotion_id</code> is derived from the canonical candidate ID/digest, base commit, scoped paths, resulting byte digests, and patch digest, so same inputs are idempotent and concurrent different facts conflict.
- <code>state.json</code> is untrusted input on every status/cleanup. Its strict schema binds <code>promotion_id</code>, immutable-manifest SHA-256, fixed platform repo identity, managed-root identity, direct-child worktree path, and lifecycle. Unknown/missing fields, symlinks, path escape, manifest mismatch, or Git worktree-registration mismatch fail closed—even with <code>--abandon</code>.

- [ ] **Step 1: Write Gate 3 isolation RED tests**

~~~python
def test_promotion_uses_detached_worktree_and_ignores_unrelated_main_dirty(tmp_path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "unrelated.txt").write_text("user dirty\n", encoding="utf-8")
    fingerprint = _fingerprint(repo / "unrelated.txt")
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)

    result = prepare_promotion_workspace(
        repo_dir=repo,
        agent_output_dir=agent_output,
        candidate_id=candidate_id,
        expected_candidate_digest=digest,
        base_commit=_git(repo, "rev-parse", "HEAD").strip(),
        promotion_root=tmp_path / "promotion-state",
        worktree_root=tmp_path / "worktrees",
    )

    assert result.worktree_path != repo
    assert result.patch_path.read_bytes().startswith(b"diff --git ")
    assert _fingerprint(repo / "unrelated.txt") == fingerprint
    assert _git(repo, "status", "--short") == " M unrelated.txt\n"
    assert _git(result.worktree_path, "log", "-1", "--format=%H").strip() == result.base_commit


def test_promotion_refuses_changed_candidate_or_existing_scoped_target(tmp_path) -> None:
    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    candidate = agent_output / "agent" / "candidates" / candidate_id
    (candidate / "factor.py.candidate").write_text(_CHANGED_FACTOR, encoding="utf-8")
    with pytest.raises(PromotionWorkspaceError, match="candidate"):
        prepare_promotion_workspace(
            repo_dir=repo,
            agent_output_dir=agent_output,
            candidate_id=candidate_id,
            expected_candidate_digest=digest,
            base_commit=_git(repo, "rev-parse", "HEAD").strip(),
            promotion_root=tmp_path / "state",
            worktree_root=tmp_path / "worktrees",
        )
~~~

Also test base commit mismatch, concurrent same promotion, deterministic patch/manifest digest across different candidate/worktree roots and mocked current dates, scoped target collision, any dirty/untracked scoped path in the user's main worktree, no automatic commit, explicit cleanup refusing an uncommitted worktree, and cleanup refusing a clean but unreferenced detached human commit until a named branch contains it.

Invoke the real Typer command handler with <code>CliRunner</code> against injected temp internals. Parametrize omission of <code>--candidate-id</code>, <code>--expected-digest</code>, and <code>--base-commit</code>; assert exit 2 and byte-identical candidate/repo/promotion/worktree fingerprints. On success, assert stdout parses to exactly:

~~~python
assert set(payload) == {"promotion_id", "worktree", "patch", "manifest"}
assert Path(payload["worktree"]) != repo
assert Path(payload["patch"]).read_bytes() == result.patch_path.read_bytes()
assert Path(payload["manifest"]).read_bytes() == result.manifest_path.read_bytes()
~~~

Assert <code>promotion-status --help</code> exposes only required <code>--promotion-id</code>, and <code>cleanup-promotion --help</code> exposes only required <code>--promotion-id</code> plus optional <code>--abandon</code>. Reject empty/dot/<code>../</code>/slash/backslash/absolute promotion IDs before state lookup. CLI help and an AST/source test must prove <code>agent_promote_candidate</code> calls only <code>prepare_promotion_workspace</code>, no public direct materializer flags remain, and <code>src/quant_system/cli.py</code> contains no call to <code>promote_candidate</code>.

Add cleanup/status state-injection tests that modify <code>state.json</code> to point at the main platform repo, another registered repository, an arbitrary outside directory, a symlink under the managed root, a nested rather than direct-child path, the correct path with a different promotion ID, and the correct path with a different manifest digest/repo identity. Invoke both default cleanup and <code>--abandon</code>; every case must refuse and leave the main repo, every other repo, outside tree, Git worktree registry, patch, manifest, and candidate fingerprints unchanged.

The patch test must prove both newly created factor/test files and the modified package init appear in an exact three-path <code>--binary --full-index</code> patch, replay it into a second clean checkout at the base commit, and compare all three replayed bytes and SHA-256 values to the manifest. A final-status test must tamper with the worktree after patch creation and prove the human commit is not accepted as Gate 3 completion.

- [ ] **Step 2: Run and confirm RED**

Run: <code>./ai-quant/bin/python -m pytest -q tests/test_promotion_workspace.py</code>

Expected: module import fails.

- [ ] **Step 3: Implement the orchestrator while preserving pure materializer**

Use narrow argument-array Git runners; patch-producing commands capture bytes and never round-trip through text decoding:

~~~python
def _git_text(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        shell=False,
    )


def _git_bytes(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        check=check,
        capture_output=True,
        text=False,
        shell=False,
    )
~~~

Before any write:

- resolve and verify base commit with <code>rev-parse --verify BASE^{commit}</code>, require it equals the user's main-worktree <code>git rev-parse HEAD</code>, then repeat that equality check under the promotion-state lock immediately before worktree creation;
- validate candidate ID, re-verify the digest-bound approved candidate through <code>CandidatePool(agent_output_dir)</code>, and retain its verified bytes;
- derive factor ID/class statically;
- calculate the exact three scoped relative paths;
- refuse existing factor/test target at the base commit;
- run <code>git status --porcelain=v1 --untracked-files=all -- scoped paths</code> in the user's main worktree and refuse any output while allowing unrelated dirty paths;
- acquire an exclusive promotion-state lock.

Under that lock, repeat both main <code>HEAD == base</code> and scoped-status-empty checks, then re-verify the candidate/digest immediately before <code>git worktree add</code>. After materialization and replay but before writing immutable promotion state, verify the candidate once more and require the same digest; any drift removes only the new isolated/replay worktrees and publishes no promotion record.

Then:

1. <code>git worktree add --detach WORKTREE BASE</code>;
2. call the existing materializer with paths rooted inside WORKTREE;
3. run only <code>git add --intent-to-add -- NEW_FACTOR NEW_TEST</code> inside the isolated worktree. Assert <code>git diff --cached --name-only</code> is empty, so intent-to-add makes complete new-file content visible to working-tree diff without staging content;
4. capture canonical patch bytes with <code>["git", "-C", worktree, "diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/", "--", *scoped_paths]</code>;
5. require working-tree HEAD still equals base; require <code>git diff --name-status -- scoped_paths</code> to be exactly new factor <code>A</code>, init <code>M</code>, new test <code>A</code>; require no fourth path anywhere in <code>git status --porcelain=v1 --untracked-files=all</code>; and require new-file-mode/<code>/dev/null</code> entries plus complete bytes for both new files in the patch;
6. create a second detached clean worktree at the same base, run <code>git apply --check --binary PATCH</code> then <code>git apply --binary PATCH</code>, require only the exact three scoped paths changed, compare their exact bytes/SHA-256 values to the first worktree, then remove only this internal replay worktree;
7. write immutable patch bytes and canonical <code>manifest.v1.json</code> with schema version, deterministic promotion ID, base commit, candidate ID/digest, exact ordered scoped paths, each resulting Git mode and SHA-256, and patch SHA-256. Exclude worktree path, absolute roots, timestamps, current date, and mutable status. Write strict <code>state.json</code> separately with promotion ID, manifest SHA-256, fixed platform repo <code>st_dev/st_ino</code>, managed-root <code>st_dev/st_ino</code>, direct-child worktree path, and <code>status="awaiting_human_commit"</code>;
8. emit the exact four-field JSON result on stdout and the human-only next sequence on stderr: inspect <code>git diff --binary --full-index -- scoped_paths</code>, create named branch <code>codex/promotion-{promotion_id}</code>, stage only the scoped paths, review the staged diff, and commit;
9. <code>prepare</code>/<code>status</code> never run content-staging <code>git add</code>, <code>git switch</code>, <code>git branch</code>, <code>git commit</code>, <code>git push</code>, or review-worktree removal. The sole automated review-index mutation is exact-path <code>--intent-to-add</code>; removal of the temporary replay worktree is internal verification, while removal of the persistent human review worktree belongs only to explicit cleanup.

Refactor <code>agent promote-candidate</code> to the exact prepare contract above, and add the exact promotion-ID-only status/cleanup commands. Before either command touches Git or a filesystem target, validate promotion ID; safely open the promotion directory/manifest/state without following symlinks; require strict schemas and state promotion/manifest binding; require recorded repo identity equals the fixed platform-repo constant; require the worktree is a no-symlink direct child named for that promotion under the fixed managed root; and parse <code>git worktree list --porcelain -z</code> from that fixed repo to require the exact registered worktree path. Never trust a repo/root/path supplied only by mutable state.

After state validation, status records the reviewed commit only when the user's current main-worktree HEAD still equals the recorded base, the review worktree is clean, its HEAD is exactly one commit whose parent is that base, <code>git diff-tree</code> equals the exact scoped path set, each commit blob's mode/bytes/digest equals the manifest, the candidate still verifies to its recorded digest, and <code>git for-each-ref --contains HEAD refs/heads</code> returns a named local branch.

Because a committed worktree has an empty working-tree diff, status must recompute canonical commit patch bytes with the same options as prepare plus <code>BASE..HEAD</code>:

~~~python
committed_patch = _git_bytes(
    worktree,
    "diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv",
    "--src-prefix=a/", "--dst-prefix=b/", f"{base_commit}..HEAD",
    "--", *scoped_paths,
).stdout
if hashlib.sha256(committed_patch).hexdigest() != manifest.patch_sha256:
    raise PromotionWorkspaceError("committed patch differs from reviewed patch")
if committed_patch != patch_path.read_bytes():
    raise PromotionWorkspaceError("committed patch bytes are not the prepared patch")
~~~

Tests must prove status does not mistakenly hash the now-empty <code>git diff -- scoped_paths</code>. Cleanup re-runs the full durable reviewed-commit check or requires <code>--abandon</code>; default cleanup refuses uncommitted, dirty, detached-unreferenced, changed-candidate, changed-patch, base/head mismatch, or invalid-state workspaces. Explicit <code>--abandon</code> may use forced worktree removal but must retain an audit state marked abandoned. <code>promote-candidate</code> and <code>promotion-status</code> never remove the persistent worktree.

- [ ] **Step 4: Run pure and workspace promotion tests**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q tests/test_agent_promote.py \
  tests/test_promotion_workspace.py tests/test_agent_promotion.py
./ai-quant/bin/python -m ruff check src/quant_system/agent/promote.py \
  src/quant_system/agent/promotion_workspace.py tests/test_promotion_workspace.py
~~~

Expected: all pass; the static test still proves <code>promote.py</code> imports no git/process module; the workspace test proves the user's main dirty fingerprint is unchanged.

Also run:

~~~bash
./ai-quant/bin/quant-system agent promote-candidate --help
./ai-quant/bin/quant-system agent promotion-status --help
./ai-quant/bin/quant-system agent cleanup-promotion --help
rg -n "promote_candidate\(" src/quant_system/cli.py
~~~

Expected: prepare help requires candidate ID/digest/base and exposes no direct path/materializer flags; status accepts only promotion ID; cleanup accepts only promotion ID plus explicit abandon; the source search returns no direct materializer call.

- [ ] **Step 5: Commit**

~~~bash
git add src/quant_system/agent/promotion_workspace.py src/quant_system/agent/promote.py \
  src/quant_system/cli.py tests/test_promotion_workspace.py tests/test_agent_promote.py
git commit -m "feat(agent): prepare Gate 3 diffs in isolated review worktrees"
~~~

---

