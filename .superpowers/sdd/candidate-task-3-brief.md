### Task 3: Atomic candidate repository and digest-bound review CAS

**Files:**

- Modify: <code>src/quant_system/agent/candidate_fs.py</code>
- Modify: <code>src/quant_system/agent/models.py</code>
- Modify: <code>src/quant_system/agent/candidate_pool.py</code>
- Modify: <code>src/quant_system/agent/safety.py</code>
- Modify: <code>src/quant_system/agent/promotion.py</code>
- Modify: <code>src/quant_system/agent/promote.py</code>
- Modify: <code>src/quant_system/agent/runner.py</code>
- Modify: <code>src/quant_system/api/routes/agent.py</code>
- Modify: <code>src/quant_system/api/schemas/agent.py</code>
- Modify: <code>src/quant_system/cli.py</code>
- Create: <code>tests/test_candidate_repository.py</code>
- Modify: <code>tests/test_agent_phase7.py</code>
- Modify: <code>tests/test_agent_promotion.py</code>
- Modify: <code>tests/test_agent_promote.py</code>
- Modify: <code>tests/test_api_agent.py</code>
- Modify: <code>tests/test_cli_json_output.py</code>

**Interfaces:**

- <code>write_candidate</code> publishes a complete staged <code>&lt;candidate_id&gt;</code> directory with no-replace rename while holding a verified regular <code>.candidate-pool.lock</code> opened through the held candidates-root FD.
- Review takes <code>expected_manifest_digest</code> and <code>expected_status="pending"</code>; either mismatch raises a stale error without creating a review or changing locks.
- A structured <code>approved.lock</code>/<code>rejected.lock</code> contains schema version, candidate ID, decision, manifest digest, note, reviewer, and timestamp.
- Read listing isolates each directory: <code>verified</code> items expose an authoritative digest; safe legacy items expose only a non-authoritative <code>observed_manifest_digest</code> with <code>migration_required</code>; corrupt items expose only candidate ID, <code>integrity_state</code>, and a stable error code while untrusted display metadata/status/binding remain null. Neither exceptional state can approve, compile, execute, or promote, and one bad item never hides healthy items.
- <code>get</code>, review, API detail, <code>SafetyGate</code>, and CLI validate the ID before opening the candidates root. No caller has a separate regex/path resolver, and all require directory/metadata/manifest ID equality from Task 2.
- New public contract is <code>SafetyGate(agent_output_dir)</code>; it delegates to the safe repository and never accepts an already-derived candidates directory. Update every production/test call site in this task and add a static regression assertion against <code>SafetyGate(...candidates_dir...)</code> or direct <code>/ "agent" / "candidates"</code> construction in candidate consumers.
- Create/review never write through a pathname after the safe root is open. Before publication/decision return, they re-check that the held candidates root and held candidate directory are still the entries named by their parents.

- [ ] **Step 1: Write repository RED tests**

~~~python
def test_same_id_same_manifest_is_noop_but_different_bytes_conflict(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    first = pool.write_candidate(
        task_id="stable-task",
        goal="stable goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# exact\n",
    )
    before = first.path.stat().st_mtime_ns
    second = pool.write_candidate(
        task_id="stable-task",
        goal="stable goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# exact\n",
    )
    assert second.manifest_digest == first.manifest_digest
    assert second.path.stat().st_mtime_ns == before

    with pytest.raises(CandidateConflictError):
        pool.write_candidate(
            task_id="stable-task",
            goal="stable goal",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="# changed\n",
        )
    assert first.path.read_text(encoding="utf-8") == "# exact\n"


def test_review_requires_current_digest_and_legacy_lock_never_allows(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="review-task",
        goal="review goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# review\n",
    )
    with pytest.raises(CandidateStaleError):
        pool.review(
            candidate_id=artifact.candidate_id,
            decision="approve",
            note="wrong revision",
            expected_manifest_digest="0" * 64,
            expected_status="pending",
        )
    assert not (artifact.path.parent / "approved.lock").exists()

    (artifact.path.parent / "approved.lock").write_text("{}", encoding="utf-8")
    assert pool.get(artifact.candidate_id).approval_binding == "legacy_unbound"
    assert SafetyGate(tmp_path).allow_promotion(artifact.candidate_id) is False


@pytest.mark.parametrize(
    "case",
    [
        "parent",
        "absolute",
        "metadata.json",
        "manifest.v1.json",
        "approved.lock",
        "rejected.lock",
        "reviews.jsonl",
        "nested/metadata.json",
    ],
)
def test_write_rejects_unsafe_or_reserved_filename_before_any_side_effect(
    tmp_path, case
) -> None:
    filename = {
        "parent": "../escaped.py",
        "absolute": str(tmp_path / "absolute-escaped.py"),
    }.get(case, case)
    pool = CandidatePool(tmp_path / "output")

    with pytest.raises(CandidateIntegrityError):
        pool.write_candidate(
            task_id="unsafe-path",
            goal="must not write",
            artifact_type="factor",
            filename=filename,
            content="# escaped\n",
        )

    assert not any(tmp_path.iterdir())
    assert not pool.candidates_dir.exists()


def test_unversioned_and_corrupt_items_remain_visible_but_never_authorize(
    tmp_path,
) -> None:
    pool = CandidatePool(tmp_path / "output")
    _write_unversioned_candidate(pool.candidates_dir, "legacy-pending")
    _write_corrupt_candidate(pool.candidates_dir, "broken")

    items = {item.candidate_id: item for item in pool.list_for_read()}

    legacy = items["legacy-pending"]
    assert legacy.integrity_state == "migration_required"
    assert legacy.manifest_digest is None
    assert len(legacy.observed_manifest_digest or "") == 64
    assert legacy.approval_enabled is False
    assert items["broken"].integrity_state == "corrupt"
    assert items["broken"].artifact_type is None
    assert items["broken"].status is None
    assert items["broken"].approval_binding is None
    with pytest.raises(CandidateMigrationRequiredError):
        pool.review(
            candidate_id="legacy-pending",
            decision="approve",
            note="observed digest is not authority",
            expected_manifest_digest=legacy.observed_manifest_digest or "",
            expected_status="pending",
        )
~~~

Add these explicit adversarial tests before implementation:

~~~python
@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "../outside", "../../outside", "/tmp/outside", "a/b", r"a\b", "approved.lock"],
)
def test_get_review_safety_api_and_cli_share_candidate_id_rejection_with_zero_writes(
    tmp_path, bad_id
) -> None:
    agent_output = tmp_path / "agent-output"
    outside = tmp_path / "outside"
    before = _tree_fingerprint(tmp_path)

    with pytest.raises(CandidateIntegrityError):
        CandidatePool(agent_output).get(bad_id)
    with pytest.raises(CandidateIntegrityError):
        CandidatePool(agent_output).review(
            candidate_id=bad_id,
            decision="approve",
            note="must fail before IO",
            expected_manifest_digest="0" * 64,
            expected_status="pending",
        )
    assert SafetyGate(agent_output).allow_promotion(bad_id) is False
    assert _invoke_review_cli(agent_output, bad_id).exit_code != 0
    assert _tree_fingerprint(tmp_path) == before
    assert not outside.exists()
~~~

Use a barrier-synchronized two-thread test where approve and reject both submit the same digest and <code>expected_status="pending"</code>. Assert exactly one returns <code>ReviewRecord</code>, exactly one raises <code>CandidateReviewStateStaleError</code>, exactly one decision lock exists, its bytes remain unchanged after every retry, and no opposite lock is created or deleted. Repeat approve→reject, reject→approve, approve→approve, and reject→reject retries to prove a final decision is never overwritten, deleted, or flipped.

Add root/lock/candidate swap tests: (a) <code>.candidate-pool.lock</code> is a symlink, hardlink-to-outside, FIFO, or other non-regular/non-single-link file; (b) the candidates-root entry is renamed and replaced after its FD opens; (c) the candidate entry is renamed/replaced after verified read but before review-lock publication. Every case must fail closed, leave the replacement and outside target byte-identical, and create no decision/control in the replacement tree. Also interrupt candidate creation before publish and prove no partial final candidate is visible.

- [ ] **Step 2: Run and confirm failures**

Run: <code>./ai-quant/bin/python -m pytest -q tests/test_candidate_repository.py tests/test_agent_phase7.py tests/test_api_agent.py tests/test_cli_json_output.py</code>

Expected: failures show missing digest fields/errors and the legacy lock is currently accepted.

- [ ] **Step 3: Implement dirfd-locked publication and review**

Extend <code>candidate_fs.py</code> with one reusable candidates-root lock. It must use the already-open root FD and verify the lock is a regular file:

~~~python
@contextmanager
def locked_candidates_root(agent_output_dir: Path, *, create: bool) -> Iterator[OpenedDirectory]:
    candidates_path = resolve_candidates_dir(agent_output_dir)
    with open_absolute_directory(candidates_path, create=create) as opened:
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        lock_fd = os.open(".candidate-pool.lock", flags, 0o600, dir_fd=opened.fd)
        try:
            lock_stat = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
                raise CandidateIntegrityError("candidate pool lock must be regular")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
            assert_entry_is_open_fd(opened.fd, ".candidate-pool.lock", lock_fd)
            yield opened
            assert_entry_is_open_fd(opened.fd, ".candidate-pool.lock", lock_fd)
            assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
~~~

Do not add a <code>Path.open</code>/<code>tempfile</code>/<code>os.replace</code> fallback. All content/control writes call Task 2's exclusive dirfd primitives.

Creation rules:

1. Before creating the candidate root, lock, staging directory, or any file, derive then call <code>_validate_candidate_id(candidate_id)</code> and validate <code>filename</code> through the manifest module's shared V1 validator. Reject absolute, nested, <code>.</code>/<code>..</code>, backslash/non-canonical paths and every shared reserved control basename.
2. Before any write, reject <code>metadata_extra</code> keys colliding with <code>candidate_id</code>, <code>task_id</code>, <code>artifact_type</code>, <code>goal</code>, <code>universe</code>, <code>status</code>, <code>created_at</code>, <code>updated_at</code>, <code>files</code>, or <code>safety</code>.
3. Under the root lock, if final exists, compare stable input fields and exact artifact bytes through its verified manifest. Return it unchanged only if equal.
4. Otherwise create a random single-component staging directory relative to the candidates-root FD, then create <code>staging/&lt;candidate_id&gt;</code> so the verified directory basename already equals metadata/manifest identity. Write metadata/artifact/manifest exclusively through FDs, fsync every file and both directories, verify from the staged candidate FD, re-check root identity, and publish <code>&lt;candidate_id&gt;</code> with <code>rename_directory_noreplace_at</code> while still locked. Remove only the private staging entry by dirfd on failure.
5. Never update immutable metadata during review; derive list status from the structured lock.

<code>list_for_read</code> safely audits candidates independently. A missing stored manifest may be built in memory only to produce <code>observed_manifest_digest</code>; never write it, never place it in <code>manifest_digest</code>, and never accept it in review. A corrupt candidate returns no preview/digest and a stable <code>integrity_error_code</code>, while iteration continues. <code>get</code>, review, loader, execution, and promotion remain verified-only.

Mechanically update current loader/materializer callers in <code>promotion.py</code>, <code>promote.py</code>, their tests, and the temporary pre-Task-7 CLI call to pass an agent-output root rather than an already-derived candidates directory. They may delegate to <code>CandidatePool(agent_output_dir)</code>/<code>SafetyGate(agent_output_dir)</code>; no compatibility overload guesses whether a path is an agent root or candidates root. Task 4 then removes their remaining reopen-after-verification behavior by passing snapshots/bytes.

Update <code>AgentRunner.list_candidates</code> to delegate to <code>list_for_read</code>. Update <code>AgentRunner.review</code> to require and forward both <code>expected_manifest_digest</code> and <code>expected_status</code>; record those values in the audit task before mutation and never derive them from a new list call.

In this same security commit, adapt the platform API schema/route and CLI to require both CAS fields, map digest/status/migration/integrity failures to stable 409 errors, and expose per-item integrity state. Task 5 regenerates frontend contracts and updates HQA/legacy UI, but no backend caller may be left invoking the new Runner signature incorrectly between commits. Add API/CLI RED tests for missing status, stale second decision, migration-required review, and corrupt-item isolation before implementation.

Review validates candidate ID, lowercase digest shape, literal <code>expected_status="pending"</code>, and <code>note</code> length 1..2000 before opening/creating the root. It then holds the same root lock, opens the candidate directory by <code>O_DIRECTORY | O_NOFOLLOW</code>, verifies directory/metadata/manifest identity and current bytes, derives current status from decision controls, and compares both CAS values. Any existing decision is final and returns stale; it is never deleted, flipped, or replaced. For a pending candidate, re-check both held root and candidate entry identities, then atomically publish exactly one selected structured lock with exclusive/no-replace dirfd semantics; that immutable lock is the canonical review audit record. Do not append new decisions to <code>reviews.jsonl</code>; the API may merge historical legacy log entries with the canonical decision lock for display. <code>SafetyGate</code> validates the ID and parses the structured approval through the same safe repository, comparing its digest with the freshly verified snapshot.

- [ ] **Step 4: Run all candidate repository tests**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_paths.py \
  tests/test_candidate_manifest.py \
  tests/test_candidate_repository.py \
  tests/test_agent_phase7.py \
  tests/test_agent_promotion.py tests/test_agent_promote.py \
  tests/test_agent_propose_source_file.py \
  tests/test_api_agent.py tests/test_cli_json_output.py
~~~

Expected: all pass, including invalid-ID zero-write, lock/root/candidate swap, concurrent approve/reject, immutable-final-decision, and partial-publication tests.

- [ ] **Step 5: Commit**

~~~bash
git add src/quant_system/agent/candidate_fs.py src/quant_system/agent/models.py \
  src/quant_system/agent/candidate_pool.py \
  src/quant_system/agent/safety.py src/quant_system/agent/promotion.py \
  src/quant_system/agent/promote.py src/quant_system/agent/runner.py \
  src/quant_system/api/routes/agent.py src/quant_system/api/schemas/agent.py \
  src/quant_system/cli.py tests/test_candidate_repository.py \
  tests/test_agent_phase7.py tests/test_agent_promotion.py \
  tests/test_agent_promote.py tests/test_agent_propose_source_file.py \
  tests/test_api_agent.py tests/test_cli_json_output.py
git commit -m "fix(agent): make candidate writes immutable and approvals revision-bound"
~~~

---

