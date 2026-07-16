### Task 4: Re-verify before one-shot load and promotion

**Files:**

- Modify: <code>src/quant_system/agent/promotion.py</code>
- Modify: <code>src/quant_system/agent/promote.py</code>
- Modify: <code>src/quant_system/factors/registry.py</code>
- Modify: <code>tests/test_agent_promotion.py</code>
- Modify: <code>tests/test_agent_promote.py</code>
- Modify: <code>tests/test_factor_registry_factory.py</code>

**Interfaces:**

- Loader and materializer consume <code>VerifiedCandidateSnapshot</code> and its already-verified <code>artifact_bytes</code>; neither reopens a candidate path.
- One-shot loader entry points receive <code>agent_output_dir</code>, never a direct/default candidates directory. Resident registry construction remains promoted-only.
- Authorization requires <code>approval_binding == "approved"</code> and an approval lock digest equal to the freshly computed manifest digest.
- Generated provenance contains only stable candidate ID, manifest schema/digest, and the UTC approval date parsed from the structured approval record. It contains no absolute candidate/lock/worktree path and never reads today's clock.

- [ ] **Step 1: Add tamper and legacy-lock RED tests**

~~~python
def test_loader_refuses_source_changed_after_digest_bound_approval(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="tamper-task",
        goal="tamper",
        artifact_type="factor",
        filename="factor.py.candidate",
        content=_VALID_FACTOR_SOURCE,
    )
    pool.review(
        candidate_id=artifact.candidate_id,
        decision="approve",
        note="approved exact bytes",
        expected_manifest_digest=artifact.manifest_digest,
        expected_status="pending",
    )
    artifact.path.write_text(_VALID_FACTOR_SOURCE.replace("safe_factor", "changed_factor"))

    registry = build_default_factor_registry()
    with pytest.raises(CandidateIntegrityError):
        load_approved_factor_candidates(registry, agent_output_dir=tmp_path)
    assert "changed_factor" not in registry.factor_ids()
~~~

Add the equivalent materializer test: mutate candidate bytes after approval and assert no module, init, test, or lock file is written.

- [ ] **Step 2: Run and confirm RED**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_promotion.py \
  tests/test_agent_promote.py \
  tests/test_factor_registry_factory.py
~~~

Expected: the new tests fail because current consumers authorize by lock existence.

- [ ] **Step 3: Use verified snapshots at the last responsible moment**

In the loader, enumerate through <code>CandidatePool(agent_output_dir)</code>, and for each valid ID:

~~~python
snapshot = load_verified_candidate_snapshot(
    agent_output_dir=agent_output_dir,
    candidate_id=candidate_id,
)
if snapshot.approval_binding != "approved":
    continue
source = snapshot.artifact_bytes["factor.py.candidate"].decode(
    "utf-8", errors="strict"
)
_check_source(source, snapshot.candidate_id)
~~~

Make internal <code>promote_candidate</code> accept a <code>VerifiedCandidateSnapshot</code> plus <code>expected_candidate_digest</code>; compare the expected digest before AST checks and use only <code>snapshot.artifact_bytes</code>. Candidate filesystem verification belongs to the caller immediately before it invokes this internal materializer. Replace current absolute <code>approved.lock</code> provenance and <code>date.today()</code> output with stable candidate ID/digest and the UTC approval date from <code>snapshot.review_record</code>. Keep every existing no-process/no-git/static-safety/exclusive-create test. Add a test that copies the same approved candidate to two different absolute roots, verifies snapshots, runs with two different mocked current dates, and gets byte-identical module/init/test output.

- [ ] **Step 4: Run promotion and registry suites**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_promotion.py \
  tests/test_agent_promote.py \
  tests/test_factor_registry_factory.py \
  tests/test_cli_experiment_provider.py
~~~

Expected: all pass; legacy/unbound or changed candidates never compile.

- [ ] **Step 5: Commit**

~~~bash
git add src/quant_system/agent/promotion.py src/quant_system/agent/promote.py \
  src/quant_system/factors/registry.py \
  tests/test_agent_promotion.py tests/test_agent_promote.py \
  tests/test_factor_registry_factory.py tests/test_cli_experiment_provider.py
git commit -m "fix(agent): recheck candidate digest before research or promotion"
~~~

---

