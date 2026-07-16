### Task 6: Dry-run-first legacy root audit and migration

**Files:**

- Modify: <code>src/quant_system/agent/candidate_fs.py</code>
- Create: <code>src/quant_system/agent/candidate_migration.py</code>
- Create: <code>tests/test_candidate_migration.py</code>
- Modify: <code>src/quant_system/cli.py</code>

**Interfaces:**

- <code>audit_candidate_roots(*, legacy_dir, agent_output_dir) -> CandidateMigrationReport</code> is read-only; canonical is always <code>resolve_candidates_dir(resolve_agent_output_dir(agent_output_dir))</code>.
- <code>apply_candidate_migration(report, backup_dir) -> CandidateMigrationReport</code> refuses if source facts differ from the audit.
- The report separately lists existing canonical candidates without <code>manifest.v1.json</code> as <code>canonical_unversioned</code>; apply may add a manifest without changing metadata/artifact bytes or granting approval.
- CLI command <code>agent migrate-candidates</code> defaults to dry-run JSON; <code>--apply</code> and an explicit backup directory are both required to write.
- Dry-run opens both roots with <code>create=False</code> and creates no root, lock, backup, manifest, or temp entry. Apply reads legacy source, writes backup, and mutates canonical only through Task 2/3 held-dirfd primitives.
- Every discovered directory name passes <code>_validate_candidate_id</code>. Invalid ID, directory/metadata identity mismatch, symlink/type failure, or drift is reported and never copied.
- Legacy, canonical, and backup roots must be three distinct non-overlapping trees: no pair may share the same held-FD identity, equal real path, or have an ancestor/descendant relationship. Validate planned paths before creating backup/canonical entries, then repeat with safely opened FDs immediately before any copy/write.

- [ ] **Step 1: Write migration RED tests**

~~~python
def test_migration_never_overwrites_conflicting_canonical_candidate(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(legacy, "candidate-1", b"legacy\n", approved=True)
    _write_legacy_candidate(canonical, "candidate-1", b"canonical\n", approved=False)

    report = audit_candidate_roots(
        legacy_dir=legacy,
        agent_output_dir=agent_output,
    )

    assert report.conflicts == ["candidate-1"]
    assert report.copyable == []
    before = (canonical / "candidate-1" / "factor.py.candidate").read_bytes()
    with pytest.raises(CandidateMigrationConflict):
        apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    assert (canonical / "candidate-1" / "factor.py.candidate").read_bytes() == before


def test_migration_never_mutates_legacy_source_tree(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    _write_legacy_candidate(legacy, "candidate-1", b"legacy\n", approved=True)
    before = _tree_fingerprint(legacy)

    report = audit_candidate_roots(
        legacy_dir=legacy,
        agent_output_dir=agent_output,
    )
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")

    assert _tree_fingerprint(legacy) == before


def test_legacy_approval_is_preserved_as_evidence_but_not_authority(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(legacy, "candidate-1", b"same\n", approved=True)
    report = audit_candidate_roots(
        legacy_dir=legacy,
        agent_output_dir=agent_output,
    )
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    snapshot = CandidatePool(agent_output).get("candidate-1")
    assert snapshot.approval_binding == "legacy_unbound"
    assert (snapshot.candidate_dir / "legacy-approved.lock").exists()


def test_existing_canonical_candidate_gets_manifest_without_byte_or_authority_change(
    tmp_path,
) -> None:
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(canonical, "candidate-1", b"pending\n", approved=False)
    source = canonical / "candidate-1" / "factor.py.candidate"
    metadata = canonical / "candidate-1" / "metadata.json"
    before = (source.read_bytes(), metadata.read_bytes())

    report = audit_candidate_roots(
        legacy_dir=tmp_path / "missing-legacy",
        agent_output_dir=agent_output,
    )

    assert report.canonical_unversioned == ["candidate-1"]
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    assert (source.read_bytes(), metadata.read_bytes()) == before
    assert (canonical / "candidate-1" / "manifest.v1.json").is_file()
    assert CandidatePool(agent_output).get(
        "candidate-1"
    ).approval_binding == "pending"
~~~

Add tests that dry-run against absent roots leaves <code>tmp_path</code> byte-for-byte empty; <code>../../outside</code>, absolute, slash/backslash, dot, and reserved candidate directory names are rejected without canonical/backup writes; and <code>migration_required</code>, <code>corrupt</code>, and <code>verified</code> are reported as three mutually exclusive integrity states. Parametrize root overlap with legacy==canonical, backup==legacy, backup inside legacy, legacy inside backup, canonical inside legacy, legacy inside canonical, backup inside canonical, and canonical inside backup; every case must fail before root/lock/backup creation and leave all existing tree fingerprints unchanged. Add barrier tests that replace the legacy root, canonical root, pool lock, or canonical candidate entry after open. Apply must detect identity drift, leave the replacement/outside tree unchanged, and preserve the legacy source tree's complete inode/type/path/byte fingerprint on both success and failure.

- [ ] **Step 2: Run and confirm RED**

Run: <code>./ai-quant/bin/python -m pytest -q tests/test_candidate_migration.py</code>

Expected: module import fails.

- [ ] **Step 3: Implement idempotent audit/apply**

The report stores resolved legacy root, resolved agent-output/canonical roots, every validated candidate ID, source/canonical manifest digests, <code>copyable</code>, <code>identical</code>, <code>conflicts</code>, <code>canonical_unversioned</code>, <code>legacy_unbound</code>, and exactly one integrity state (<code>verified</code>, <code>migration_required</code>, or <code>corrupt</code>) per observed item. Before audit/apply, compare no-symlink real paths component-wise for equality/containment and, for roots that exist, compare held <code>st_dev/st_ino</code>. For an absent backup, validate its planned normalized absolute path before creation, safely create/open it, then repeat both overlap checks. Apply:

1. safely reopens the legacy root with <code>create=False</code>, reacquires the canonical root dirfd lock, and safely opens/creates the backup root only after <code>--apply</code> validation;
2. recomputes both root/candidate identities and exact digests through held FDs and rejects drift;
3. copies each legacy-only candidate into a canonical private staging directory using exclusive dirfd writes;
4. inside the staged canonical copy only, preserves an old decision as <code>legacy-approved.lock</code> or <code>legacy-rejected.lock</code>; it never modifies or renames the legacy source entry;
5. builds and verifies <code>manifest.v1.json</code> in the exact-ID staged directory;
6. publishes through <code>rename_directory_noreplace_at</code> without overwrite;
7. writes and fsyncs a complete backup through safe dirfds before canonical publication; the legacy source tree remains read-only and its inode/type/path/byte fingerprint must be identical before and after both successful and failed apply;
8. for each <code>canonical_unversioned</code> item, backs up the complete directory, re-verifies all audited bytes and held root/candidate identities under the root lock, atomically adds <code>manifest.v1.json</code> with no-replace semantics, and preserves pending status or moves a legacy-format decision to unbound evidence using only same-dirfd no-replace operations;
9. is a no-op on identical re-run.

Migration code must not contain <code>Path.open</code>, <code>Path.mkdir</code>, path-string <code>tempfile</code>, path-based <code>shutil.copy*</code>, <code>os.replace</code>, or overwrite-capable <code>os.rename</code>. Add a static source test for those bypasses.

Add Typer options:

~~~python
@agent_app.command("migrate-candidates")
def agent_migrate_candidates(
    legacy_dir: Path | None = None,
    agent_output_dir: Path | None = None,
    apply: bool = False,
    backup_dir: Path | None = None,
) -> None:
    resolved_legacy = resolve_legacy_candidates_dir(legacy_dir)
    resolved_agent_output = resolve_agent_output_dir(agent_output_dir)
    report = audit_candidate_roots(
        legacy_dir=resolved_legacy,
        agent_output_dir=resolved_agent_output,
    )
    if apply:
        if backup_dir is None:
            raise typer.BadParameter("--backup-dir is required with --apply")
        report = apply_candidate_migration(report, backup_dir=backup_dir)
    typer.echo(report.model_dump_json())
~~~

There is no <code>canonical_dir</code>/<code>--candidates-dir</code> option. Add a CLI test that <code>chdir</code>s outside the repository, runs dry-run with no path flags and a test <code>QS_AGENT_OUTPUT_DIR</code>, and observes exactly the same canonical root as API/list/run-config; HQA wrapper tests assert the environment is inherited rather than deriving a CWD-relative path.

- [ ] **Step 4: Run tests and real dry-run only**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q tests/test_candidate_migration.py
./ai-quant/bin/quant-system agent migrate-candidates
~~~

Expected on this machine: legacy root absent; no conflicts; <code>canonical_unversioned</code> contains the one pending candidate that needs a v1 manifest. The command must not change its files in dry-run mode.

- [ ] **Step 5: Commit code; stop before real apply**

~~~bash
git add src/quant_system/agent/candidate_fs.py \
  src/quant_system/agent/candidate_migration.py src/quant_system/cli.py \
  tests/test_candidate_migration.py
git commit -m "feat(agent): add conflict-safe candidate root migration"
~~~

Do not run <code>--apply</code> until the user separately authorizes mutation of real candidate data after seeing the dry-run JSON and backup path.

---

