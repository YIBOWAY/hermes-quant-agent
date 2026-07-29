from __future__ import annotations

import stat
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from hqa.backup_restore_gate import (
    BackupRestoreGateError,
    run_backup_restore_gate,
)
from hqa.noneditable_upgrade import ReleaseAuthority
from hqa.repository_recovery import canonical_json_bytes


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _release_repository(tmp_path: Path) -> tuple[Path, ReleaseAuthority]:
    repository = tmp_path / "release"
    repository.mkdir()
    for arguments in (
        ("init", "-q", "-b", "codex/agent-v0-2-release"),
        ("config", "user.email", "gate8@example.invalid"),
        ("config", "user.name", "Gate 8 Test"),
    ):
        _git(repository, *arguments)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (repository / "README.md").write_text("gate 8 fixture\n", encoding="utf-8")
    executable = repository / "verify.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "published baseline")
    baseline = _git(repository, "rev-parse", "HEAD")
    (repository / "README.md").write_text("gate 8 final fixture\n", encoding="utf-8")
    _git(repository, "commit", "-qam", "final")
    publication_url = "https://github.com/example/hqa-gate8-fixture.git"
    _git(repository, "remote", "add", "github", publication_url)
    _git(
        repository,
        "update-ref",
        "refs/remotes/github/codex/agent-v0-2-release",
        "HEAD",
    )
    authority = ReleaseAuthority(
        absolute_checkout_path=repository.resolve(),
        branch="codex/agent-v0-2-release",
        publication_remote_name="github",
        publication_url=publication_url,
        published_baseline=baseline,
    )
    return repository, authority


def test_gate8_captures_once_and_verifies_two_exact_committed_restores(
    tmp_path: Path,
) -> None:
    repository, authority = _release_repository(tmp_path)
    expected_commit = _git(repository, "rev-parse", "HEAD")
    expected_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    output = tmp_path / "gate8-output"

    result = run_backup_restore_gate(
        repository,
        output,
        expected_commit=expected_commit,
        authority=authority,
    )

    assert result["schema_version"] == "hqa.agent-v0.2-backup-restore-gate.v1"
    assert result["gate"] == 8
    assert result["status"] == "pass"
    assert result["source"] == {
        "branch": "codex/agent-v0-2-release",
        "commit": expected_commit,
        "inventory": result["source"]["inventory"],
        "tree": expected_tree,
    }
    assert result["source"]["inventory"]["file_count"] == 3
    assert result["source"]["inventory"]["exact_committed_bytes"] is True
    assert result["package"]["capture_count"] == 1
    assert result["package"]["verified"] is True
    assert [entry["label"] for entry in result["restores"]] == [
        "first",
        "second",
    ]
    assert len({entry["destination"] for entry in result["restores"]}) == 2
    for entry in result["restores"]:
        assert entry["commit"] == expected_commit
        assert entry["tree"] == expected_tree
        assert entry["inventory"] == result["source"]["inventory"]
        assert entry["restore_verified"] is True
        assert entry["receipt_verified"] is True
    assert result["effects"] == {
        "database": "denied",
        "network": "denied",
        "provider": "denied",
        "runtime_mutation": "denied",
        "writes": [str(output.resolve())],
    }
    receipt = output / "receipt.json"
    receipt_bytes = receipt.read_bytes()
    assert receipt_bytes == canonical_json_bytes(result)
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert _git(repository, "status", "--porcelain=v2", "--untracked-files=all") == ""


def test_gate8_fails_closed_before_capture_on_mutable_release_identity(
    tmp_path: Path,
) -> None:
    repository, authority = _release_repository(tmp_path)
    expected_commit = _git(repository, "rev-parse", "HEAD")
    (repository / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(BackupRestoreGateError, match="release identity"):
        run_backup_restore_gate(
            repository,
            tmp_path / "dirty-output",
            expected_commit=expected_commit,
            authority=authority,
        )
    assert not (tmp_path / "dirty-output").exists()

    (repository / "untracked.txt").unlink()
    with pytest.raises(BackupRestoreGateError, match="expected commit"):
        run_backup_restore_gate(
            repository,
            tmp_path / "wrong-head-output",
            expected_commit="0" * len(expected_commit),
            authority=authority,
        )
    assert not (tmp_path / "wrong-head-output").exists()

    wrong_branch = replace(authority, branch="main")
    with pytest.raises(BackupRestoreGateError, match="release identity"):
        run_backup_restore_gate(
            repository,
            tmp_path / "wrong-branch-output",
            expected_commit=expected_commit,
            authority=wrong_branch,
        )
    assert not (tmp_path / "wrong-branch-output").exists()


def test_gate8_requires_new_absolute_external_canonical_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, authority = _release_repository(tmp_path)
    expected_commit = _git(repository, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BackupRestoreGateError, match="absolute"):
        run_backup_restore_gate(
            repository,
            Path("relative-output"),
            expected_commit=expected_commit,
            authority=authority,
        )
    with pytest.raises(BackupRestoreGateError, match="outside"):
        run_backup_restore_gate(
            repository,
            repository / "inside-output",
            expected_commit=expected_commit,
            authority=authority,
        )
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(BackupRestoreGateError, match="must not exist"):
        run_backup_restore_gate(
            repository,
            existing,
            expected_commit=expected_commit,
            authority=authority,
        )
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(BackupRestoreGateError, match="canonical"):
        run_backup_restore_gate(
            repository,
            alias / "output",
            expected_commit=expected_commit,
            authority=authority,
        )


def test_gate8_rejects_a_worktree_file_that_is_not_the_committed_blob(
    tmp_path: Path,
) -> None:
    repository, authority = _release_repository(tmp_path)
    expected_commit = _git(repository, "rev-parse", "HEAD")
    readme = repository / "README.md"
    readme.write_text("mutated bytes\n", encoding="utf-8")
    _git(repository, "update-index", "--assume-unchanged", "README.md")

    with pytest.raises(BackupRestoreGateError, match="committed bytes"):
        run_backup_restore_gate(
            repository,
            tmp_path / "hidden-output",
            expected_commit=expected_commit,
            authority=authority,
        )
    assert not (tmp_path / "hidden-output").exists()


def test_gate8_receipt_writer_rejects_noncanonical_duplicate_target(
    tmp_path: Path,
) -> None:
    repository, authority = _release_repository(tmp_path)
    expected_commit = _git(repository, "rev-parse", "HEAD")
    output = tmp_path / "output"
    output.mkdir(mode=0o700)
    (output / "receipt.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(BackupRestoreGateError, match="must not exist"):
        run_backup_restore_gate(
            repository,
            output,
            expected_commit=expected_commit,
            authority=authority,
        )
