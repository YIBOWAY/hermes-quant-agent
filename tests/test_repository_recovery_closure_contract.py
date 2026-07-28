from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from hqa import repository_recovery_cli
from hqa.repository_recovery import (
    RepositoryRecoveryError,
    capture_and_drill_closure_repository,
    repository_identity,
    verify_closure_package,
)


EXPECTED_PACKAGE_FILES = {
    "bundle.bundle",
    "identity.json",
    "index-stages.txt",
    "index.bin",
    "pseudo-refs.txt",
    "recovery-files.json",
    "refs.txt",
    "restore-receipt.json",
    "staged.patch",
    "status-v2-z.bin",
    "submodules.txt",
    "unstaged.patch",
    "untracked.tar",
    "worktree-list.txt",
}


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout.decode().strip()


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "source"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "Closure Test")
    _git(repository, "config", "user.email", "closure@example.invalid")
    (repository / "value.txt").write_text("base\n", encoding="utf-8")
    (repository / "executable.sh").write_text(
        "#!/bin/sh\nexit 0\n", encoding="utf-8"
    )
    (repository / "executable.sh").chmod(0o755)
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "base")
    _git(
        repository,
        "remote",
        "add",
        "github",
        "https://github.com/example/closure.git",
    )
    (repository / "value.txt").write_text("staged\n", encoding="utf-8")
    _git(repository, "add", "value.txt")
    (repository / "value.txt").write_text("unstaged\n", encoding="utf-8")
    (repository / "untracked.bin").write_bytes(b"\x00closure\xff")
    return repository


def _rehearsal_patch(tmp_path: Path) -> tuple[Path, str]:
    patch = tmp_path / "planned-next.patch"
    patch.write_text(
        "diff --git a/value.txt b/value.txt\n"
        "--- a/value.txt\n"
        "+++ b/value.txt\n"
        "@@ -1 +1 @@\n"
        "-unstaged\n"
        "+rehearsed\n",
        encoding="utf-8",
    )
    patch.chmod(0o600)
    return patch, hashlib.sha256(patch.read_bytes()).hexdigest()


def test_closure_package_has_exact_section_4_1_files_and_two_restores(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    source_before = repository_identity(repository)
    patch, patch_sha256 = _rehearsal_patch(tmp_path)
    package = tmp_path / "evidence" / "recovery" / "hqa" / "release"
    first = tmp_path / "restores" / "first"
    second = tmp_path / "restores" / "second"

    result = capture_and_drill_closure_repository(
        repository,
        package,
        first,
        second,
        patch,
        rehearsal_patch_sha256=patch_sha256,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt5-test-operator",
    )

    assert result["restore_verified"] is True
    assert {child.name for child in package.iterdir()} == EXPECTED_PACKAGE_FILES
    assert stat.S_IMODE(package.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(child.stat().st_mode) == 0o600
        for child in package.iterdir()
    )
    assert repository_identity(repository) == source_before
    assert repository_identity(second) == source_before
    assert (first / "value.txt").read_text(encoding="utf-8") == "rehearsed\n"
    assert (second / "value.txt").read_text(encoding="utf-8") == "unstaged\n"

    identity = json.loads((package / "identity.json").read_bytes())
    assert identity["repository_id"] == "hqa"
    assert identity["publication_url"] == (
        "https://github.com/example/closure.git"
    )
    assert identity["absolute_checkout_path"] == str(repository)
    assert identity["branch"] == "main"
    assert identity["head"] == source_before["head_object_id"]
    assert identity["upstream"] is None
    assert identity["object_format"] == "sha1"
    assert identity["git_version"].startswith("git version ")
    assert identity["capture_time"].endswith("Z")
    assert identity["operator_identity"] == "attempt5-test-operator"
    assert identity["deliberate_exclusions"] == (
        source_before["deliberate_exclusions"]
    )

    receipt = json.loads((package / "restore-receipt.json").read_bytes())
    assert receipt["first_restore"]["restore_verified"] is True
    assert receipt["first_restore"]["comparison_mismatches"] == []
    assert receipt["rehearsal"]["check_exit_code"] == 0
    assert receipt["rehearsal"]["apply_exit_code"] == 0
    assert receipt["rehearsal"]["state_changed"] is True
    assert receipt["second_restore"]["restore_verified"] is True
    assert receipt["second_restore"]["comparison_mismatches"] == []
    assert receipt["restore_verified"] is True

    index = json.loads((package / "recovery-files.json").read_bytes())
    indexed_paths = [entry["path"] for entry in index["entries"]]
    assert "recovery-files.json" not in indexed_paths
    assert "restore-receipt.json" in indexed_paths
    assert set(indexed_paths) == EXPECTED_PACKAGE_FILES - {
        "recovery-files.json"
    }
    verification = verify_closure_package(package)
    assert verification["verified"] is True
    assert verification["restore_verified"] is True
    assert verification["recovery_files_sha256"] == (
        result["recovery_files_sha256"]
    )


def test_closure_capture_rejects_rehearsal_digest_substitution(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    patch, _patch_sha256 = _rehearsal_patch(tmp_path)
    package = tmp_path / "evidence" / "package"

    with pytest.raises(
        RepositoryRecoveryError, match="rehearsal patch digest mismatch"
    ):
        capture_and_drill_closure_repository(
            repository,
            package,
            tmp_path / "restore-first",
            tmp_path / "restore-second",
            patch,
            rehearsal_patch_sha256="0" * 64,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt5-test-operator",
        )

    assert not package.exists()


def test_closure_package_verification_rejects_receipt_tamper(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    patch, patch_sha256 = _rehearsal_patch(tmp_path)
    package = tmp_path / "evidence" / "package"
    capture_and_drill_closure_repository(
        repository,
        package,
        tmp_path / "restore-first",
        tmp_path / "restore-second",
        patch,
        rehearsal_patch_sha256=patch_sha256,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt5-test-operator",
    )

    (package / "restore-receipt.json").write_bytes(b"{}\n")
    with pytest.raises(RepositoryRecoveryError, match="digest mismatch"):
        verify_closure_package(package)


def test_failed_rehearsal_finalizes_a_truthful_false_receipt(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    patch = tmp_path / "non-applicable.patch"
    patch.write_text(
        "diff --git a/value.txt b/value.txt\n"
        "--- a/value.txt\n"
        "+++ b/value.txt\n"
        "@@ -1 +1 @@\n"
        "-not-the-current-value\n"
        "+rehearsed\n",
        encoding="utf-8",
    )
    patch.chmod(0o600)
    patch_sha256 = hashlib.sha256(patch.read_bytes()).hexdigest()
    package = tmp_path / "evidence" / "package"

    result = capture_and_drill_closure_repository(
        repository,
        package,
        tmp_path / "restore-first",
        tmp_path / "restore-second",
        patch,
        rehearsal_patch_sha256=patch_sha256,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt5-test-operator",
    )

    assert result["restore_verified"] is False
    receipt = json.loads((package / "restore-receipt.json").read_bytes())
    assert receipt["first_restore"]["restore_verified"] is True
    assert receipt["rehearsal"]["check_exit_code"] != 0
    assert receipt["rehearsal"]["apply_exit_code"] is None
    assert receipt["rehearsal"]["state_changed"] is False
    assert receipt["second_restore"]["restore_verified"] is True
    assert receipt["restore_verified"] is False
    verification = verify_closure_package(package)
    assert verification["verified"] is True
    assert verification["restore_verified"] is False


def test_closure_cli_runs_composite_capture_and_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = _repository(tmp_path)
    patch, patch_sha256 = _rehearsal_patch(tmp_path)
    package = tmp_path / "evidence" / "package"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "repository-recovery",
            "capture-closure-v2",
            "--repository",
            str(repository),
            "--repository-id",
            "hqa",
            "--publication-url",
            "https://github.com/example/closure.git",
            "--publication-remote-name",
            "github",
            "--operator-identity",
            "attempt5-test-operator",
            "--package",
            str(package),
            "--first-destination",
            str(tmp_path / "restore-first"),
            "--second-destination",
            str(tmp_path / "restore-second"),
            "--rehearsal-patch",
            str(patch),
            "--rehearsal-patch-sha256",
            patch_sha256,
        ],
    )

    assert repository_recovery_cli.main() == 0
    capture_result = json.loads(capsys.readouterr().out)
    assert capture_result["restore_verified"] is True

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "repository-recovery",
            "verify-closure-v2",
            "--package",
            str(package),
        ],
    )
    assert repository_recovery_cli.main() == 0
    verify_result = json.loads(capsys.readouterr().out)
    assert verify_result["verified"] is True
    assert verify_result["restore_verified"] is True
