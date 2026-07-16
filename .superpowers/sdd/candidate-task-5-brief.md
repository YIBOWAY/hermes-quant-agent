### Task 5: Digest-aware API, CLI, frontend compatibility, and HQA callers

**Files:**

- Modify: platform <code>src/quant_system/api/routes/agent.py</code>, <code>routes/factors.py</code>, <code>schemas/agent.py</code>, <code>cli.py</code>.
- Modify: platform <code>tests/test_api_agent.py</code>, <code>test_api_response_models.py</code>, <code>test_cli_json_output.py</code>, <code>test_frontend_openapi_generation.py</code>.
- Modify: platform <code>src/frontend/components/forms/AgentTaskForm.tsx</code>, <code>lib/api.ts</code>, and generated <code>lib/api.generated.ts</code>.
- Modify: HQA <code>hqa/quant_cli.py</code>, <code>hqa/factor_repro_cli.py</code>.
- Modify: HQA <code>tests/test_quant_cli.py</code>, <code>test_factor_repro.py</code>, <code>test_factor_repro_cli.py</code>.
- Modify: HQA <code>skills/hermes/hqa-quant/SKILL.md</code> and <code>tests/test_install.py</code>.

**Interfaces:**

- Candidate list/detail returns <code>approval_binding</code>, <code>integrity_state</code>, nullable authoritative <code>manifest_digest</code>, nullable non-authoritative <code>observed_manifest_digest</code>, <code>approval_enabled</code>, and stable nullable <code>integrity_error_code</code> per item.
- Review input requires <code>expected_manifest_digest</code>; stale target maps to HTTP 409 with code <code>candidate_revision_stale</code>.
- Review input also requires <code>expected_status: "pending"</code>; an already decided target maps to HTTP 409 <code>candidate_review_state_stale</code> and the first decision remains unchanged.
- Review of <code>migration_required</code> maps to HTTP 409 <code>candidate_migration_required</code>; corrupt maps to HTTP 409 <code>candidate_integrity_failed</code>. List stays 200 when another candidate is bad.
- Platform CLI review requires both <code>--expected-digest</code> and <code>--expected-status pending</code>.
- <code>hqa.quant_cli.run_agent_review(*, candidate_id, decision, note, expected_manifest_digest, expected_status, ...)</code> requires caller-supplied values as keyword arguments; it never lists/refetches a candidate to fill either value.
- <code>hqa-factor-repro approve</code> requires <code>--candidate-id</code>, <code>--expected-digest</code>, <code>--expected-status pending</code>, and <code>--note</code>. Propose/list/detail print the authoritative digest and exact approval syntax for the human to copy; observed migration evidence is never substituted.
- <code>skills/hermes/hqa-quant/SKILL.md</code> is part of the executable Gate 2 surface, not deferred documentation. Bump its version to <code>1.9.0</code>, replace the old two-value approve example, state that all four values come from one human-inspected verified item, and prohibit an approval handler from refetching them. <code>tests/test_install.py</code> proves both source and installed cards preserve that exact command.

- [ ] **Step 1: Write API/CLI RED contracts**

~~~python
def test_candidate_review_returns_409_for_stale_digest(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="api-stale",
        goal="stale",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# candidate\n",
    )
    client = TestClient(create_app(agent_output_dir=tmp_path))
    response = client.post(
        f"/api/agent/candidates/{artifact.candidate_id}/review",
        json={
            "decision": "approve",
            "note": "reviewed",
            "expected_manifest_digest": "0" * 64,
            "expected_status": "pending",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_revision_stale"
    assert not (artifact.path.parent / "approved.lock").exists()


def test_unversioned_candidate_is_readable_but_review_is_disabled(tmp_path) -> None:
    _write_unversioned_candidate(tmp_path / "agent" / "candidates", "legacy-pending")
    client = TestClient(create_app(agent_output_dir=tmp_path))

    item = client.get("/api/agent/candidates").json()["candidates"][0]

    assert item["integrity_state"] == "migration_required"
    assert item["manifest_digest"] is None
    assert len(item["observed_manifest_digest"]) == 64
    assert item["approval_enabled"] is False
    response = client.post(
        "/api/agent/candidates/legacy-pending/review",
        json={
            "decision": "approve",
            "note": "must migrate first",
            "expected_manifest_digest": item["observed_manifest_digest"],
            "expected_status": "pending",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_migration_required"
~~~

Add API tests proving omission of <code>expected_status</code> returns 422 and a second decision returns 409 without changing the first lock. Add CLI tests proving omission of either <code>--expected-digest</code> or <code>--expected-status pending</code> exits 2 and writes no lock. Add API/CLI tests proving a corrupt item does not hide a verified item. Add HQA tests proving the authoritative digest and status printed by a verified list item are the exact values the human explicitly passes to review, while <code>migration_required</code>/<code>corrupt</code> items are printed with approval disabled and never invoke review.

Add these HQA and installed-skill assertions explicitly:

~~~python
def test_approve_requires_explicit_human_cas_values_and_never_refetches(
    monkeypatch, capsys
) -> None:
    seen = {}
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *args, **kwargs: pytest.fail("approve must not refetch"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: seen.update(kwargs) or (0, "ok"),
    )

    rc = cli.main(
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "a" * 64,
            "--expected-status", "pending",
            "--note", "translation confirmed",
        ]
    )

    assert rc == 0
    assert seen == {
        "candidate_id": "factor-x-1",
        "decision": "approve",
        "note": "translation confirmed",
        "expected_manifest_digest": "a" * 64,
        "expected_status": "pending",
    }


def test_installed_skill_documents_exact_gate2_cas_command(tmp_path) -> None:
    scripts_dest = _install(tmp_path)
    body = (scripts_dest.parent / "skills" / "hqa-quant" / "SKILL.md").read_text()
    assert "version: 1.9.0" in body
    assert (
        "approve --candidate-id <id> --expected-digest <sha256> "
        "--expected-status pending --note \"<translation-review>\""
    ) in body
    assert "never refetch" in body.lower()
~~~

Parametrize omissions of each of the four HQA approve options, an empty/whitespace-only note, a malformed digest, and an <code>--expected-status approved</code> attempt. Argument/local validation must exit 2 before <code>run_agent_review</code> is called. Update every existing <code>version: 1.8.0</code> assertion in <code>tests/test_install.py</code> to <code>1.9.0</code> in the same change.

- [ ] **Step 2: Run cross-contract tests and confirm RED**

Run:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
./ai-quant/bin/python -m pytest -q tests/test_api_agent.py \
  tests/test_cli_json_output.py tests/test_api_response_models.py

cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest -q tests/test_quant_cli.py tests/test_factor_repro.py \
  tests/test_factor_repro_cli.py tests/test_install.py
~~~

Expected: schema/signature assertions fail.

- [ ] **Step 3: Implement exact request/response contracts**

Use:

~~~python
class AgentReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=2000)
    expected_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_status: Literal["pending"]
~~~

Catch domain errors from most specific to most general so subclasses cannot collapse into the revision code:

~~~python
try:
    record = runner.review(...)
except CandidateReviewStateStaleError as exc:
    raise _candidate_conflict(candidate_id, "candidate_review_state_stale") from exc
except CandidateMigrationRequiredError as exc:
    raise _candidate_conflict(candidate_id, "candidate_migration_required") from exc
except CandidateIntegrityError as exc:
    raise _candidate_conflict(candidate_id, "candidate_integrity_failed") from exc
except CandidateStaleError as exc:
    raise _candidate_conflict(candidate_id, "candidate_revision_stale") from exc
~~~

<code>_candidate_conflict</code> always returns HTTP 409 with <code>{"code", "resource": "agent_candidate", "id"}</code>. Add one direct API test for each branch and assert the pre-existing decision/control bytes and candidate bytes remain unchanged.

Make detail source preview come only from <code>VerifiedCandidateSnapshot.artifact_bytes</code>. Keep factors candidate loading derived from the route's injected <code>AgentOutputDirDep</code> established in Task 1; it must not call a process-global resolver. Update every candidate Typer command to accept an optional explicit agent root but otherwise call the same resolver; no command keeps a CWD-relative <code>data/agent_run</code> default. Review requires both <code>--expected-digest</code> and <code>--expected-status pending</code>. The old Agent Studio must first read the selected candidate detail and submit both values; if detail is unavailable or status is not pending, disable approve/reject rather than submitting without CAS.

Implement HQA approve with <code>choices=("pending",)</code> and pass all fields directly to the keyword-only <code>run_agent_review</code>. Neither function calls <code>run_list_candidates</code>, candidate detail, platform API, or any parser to replace supplied values. Update propose/list output so a verified item prints <code>candidate_id</code>, authoritative <code>manifest_digest</code>, <code>status=pending</code>, and the complete copyable approve command. A <code>migration_required</code> item prints only <code>observed_manifest_digest</code> with “migration evidence; approval disabled”; corrupt prints no digest/source.

For read-only migration visibility, list/detail may use <code>list_for_read</code>. Show a source preview for <code>migration_required</code> only through the same no-symlink/no-escape exact-byte reader used to compute <code>observed_manifest_digest</code>; label that digest “迁移证据，不能审批”. A corrupt item has no source preview. The old Agent Studio and new Hermes view disable controls whenever <code>approval_enabled</code> is false.

- [ ] **Step 4: Regenerate and verify both repositories**

Run:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
npm --prefix src/frontend run generate:api-types
./ai-quant/bin/python -m pytest -q tests/test_api_agent.py \
  tests/test_cli_json_output.py tests/test_api_response_models.py \
  tests/test_frontend_openapi_generation.py
npm --prefix src/frontend run test
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint

cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest -q tests/test_quant_cli.py tests/test_factor_repro.py \
  tests/test_factor_repro_cli.py tests/test_install.py
~~~

Expected: all commands pass.

- [ ] **Step 5: Commit platform and HQA changes separately**

Platform:

~~~bash
git add src/quant_system/api/routes/agent.py \
  src/quant_system/api/routes/factors.py src/quant_system/api/schemas/agent.py \
  src/quant_system/cli.py src/frontend/components/forms/AgentTaskForm.tsx \
  src/frontend/lib/api.ts src/frontend/lib/api.generated.ts \
  tests/test_api_agent.py tests/test_cli_json_output.py \
  tests/test_api_response_models.py tests/test_frontend_openapi_generation.py
git commit -m "feat(agent): require candidate revision on every review surface"
~~~

HQA:

~~~bash
git add hqa/quant_cli.py hqa/factor_repro_cli.py tests/test_quant_cli.py \
  tests/test_factor_repro.py tests/test_factor_repro_cli.py \
  skills/hermes/hqa-quant/SKILL.md tests/test_install.py
git commit -m "fix(hqa): carry candidate digest through manual Gate 2 review"
~~~

The platform commit intentionally lands first: until the HQA commit follows, an old caller is rejected for omitting the digest, which is a safe fail-closed compatibility window. Do not run a real review between the two commits, and finish both repository commits before runtime smoke.

---

