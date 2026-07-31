from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from hqa import repository_recovery as recovery_module
from hqa.detached_manifest import (
    DetachedManifestError,
    build_manifest,
    verify_manifest,
)
from hqa.repository_recovery import (
    RepositoryRecoveryError,
    capture_repository,
    repository_identity,
    restore_drill,
    verify_package,
    verify_receipt,
)


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
    _git(repository, "config", "user.name", "Recovery Test")
    _git(repository, "config", "user.email", "recovery@example.invalid")
    (repository / "both.txt").write_text("base\n", encoding="utf-8")
    (repository / "deleted.txt").write_text("delete me\n", encoding="utf-8")
    (repository / "executable.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (repository / "executable.sh").chmod(0o755)
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "base")
    _git(repository, "remote", "add", "origin", "https://example.invalid/z.git")
    _git(
        repository,
        "config",
        "--add",
        "remote.origin.url",
        "https://example.invalid/a.git",
    )
    _git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(
        repository,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/main",
    )
    (repository / "both.txt").write_text("staged\n", encoding="utf-8")
    _git(repository, "add", "both.txt")
    (repository / "both.txt").write_text("worktree after stage\n", encoding="utf-8")
    (repository / "deleted.txt").unlink()
    (repository / "untracked.bin").write_bytes(b"\x00recovery\xff")
    return repository


def test_package_and_two_external_receipts_bind_same_final_index(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    expected = repository_identity(repository)
    package = tmp_path / "evidence" / "package"
    capture = capture_repository(repository, package)

    first_receipt = tmp_path / "evidence" / "receipts" / "first.json"
    second_receipt = tmp_path / "evidence" / "receipts" / "second.json"
    first = restore_drill(
        package,
        tmp_path / "restores" / "first",
        first_receipt,
    )
    second = restore_drill(
        package,
        tmp_path / "restores" / "second",
        second_receipt,
    )

    assert first["restore_verified"] is True
    assert second["restore_verified"] is True
    assert repository_identity(tmp_path / "restores" / "first") == expected
    assert repository_identity(tmp_path / "restores" / "second") == expected
    staged_oid = _git(repository, "rev-parse", ":both.txt")
    _git(tmp_path / "restores" / "first", "cat-file", "-e", staged_oid)
    assert _git(repository, "diff", "--cached", "--binary") == _git(
        tmp_path / "restores" / "first",
        "diff",
        "--cached",
        "--binary",
    )
    assert _git(repository, "config", "--get-all", "remote.origin.url") == _git(
        tmp_path / "restores" / "first",
        "config",
        "--get-all",
        "remote.origin.url",
    )
    assert first["package_validation"] == second["package_validation"]
    assert (
        first["package_validation"]["recovery_files_sha256"]
        == capture["recovery_files_sha256"]
    )
    assert (
        first["package_validation"]["recovery_files_bytes"]
        == capture["recovery_files_bytes"]
    )
    assert not (package / "restore-receipt.json").exists()
    index = json.loads((package / "recovery-files.json").read_text(encoding="utf-8"))
    assert all("receipt" not in entry["path"] for entry in index["entries"])
    assert verify_receipt(package, first_receipt)["verified"] is True
    assert verify_receipt(package, second_receipt)["verified"] is True


def test_package_verification_rejects_tamper_and_extra_file(tmp_path: Path) -> None:
    package = tmp_path / "evidence" / "package"
    capture_repository(_repository(tmp_path), package)
    assert verify_package(package)["verified"] is True

    (package / "bundle.bundle").write_bytes(b"tampered")
    with pytest.raises(RepositoryRecoveryError, match="digest mismatch"):
        verify_package(package)


def test_package_verification_rejects_a_symlinked_root(tmp_path: Path) -> None:
    package = tmp_path / "evidence" / "package"
    capture_repository(_repository(tmp_path), package)
    alias = tmp_path / "package-alias"
    alias.symlink_to(package, target_is_directory=True)
    with pytest.raises(RepositoryRecoveryError, match="symlinked"):
        verify_package(alias)


def test_capture_records_but_does_not_restore_ignored_content(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text("ignored.local\n", encoding="utf-8")
    (repository / "ignored.local").write_text("not recovery input\n", encoding="utf-8")
    package = tmp_path / "evidence" / "package"
    capture_repository(repository, package)

    identity = json.loads((package / "identity.json").read_bytes())
    assert identity["deliberate_exclusions"]["paths"] == ["ignored.local"]
    receipt = restore_drill(
        package,
        tmp_path / "restore",
        tmp_path / "evidence" / "receipt.json",
    )
    assert receipt["restore_verified"] is True
    assert not (tmp_path / "restore" / "ignored.local").exists()


def test_capture_rejects_package_inside_any_worktree(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(RepositoryRecoveryError, match="overlaps"):
        capture_repository(repository, repository / ".ignored-package")


def test_receipt_must_be_outside_the_package(tmp_path: Path) -> None:
    package = tmp_path / "evidence" / "package"
    capture_repository(_repository(tmp_path), package)
    with pytest.raises(RepositoryRecoveryError, match="outside"):
        restore_drill(
            package,
            tmp_path / "restore",
            package / "receipt.json",
        )
    with pytest.raises(RepositoryRecoveryError, match="destination"):
        restore_drill(
            package,
            package / "restore",
            tmp_path / "receipt.json",
        )


def test_linked_worktree_admin_state_restores_standalone(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-b", "main")
    _git(primary, "config", "user.name", "Recovery Test")
    _git(primary, "config", "user.email", "recovery@example.invalid")
    (primary / "value.txt").write_text("base\n", encoding="utf-8")
    _git(primary, "add", "value.txt")
    _git(primary, "commit", "-m", "primary")
    linked = tmp_path / "linked"
    _git(primary, "worktree", "add", "-b", "topic", str(linked))
    primary_message = Path(_git(primary, "rev-parse", "--git-path", "COMMIT_EDITMSG"))
    linked_message = Path(_git(linked, "rev-parse", "--git-path", "COMMIT_EDITMSG"))
    if not primary_message.is_absolute():
        primary_message = primary / primary_message
    if not linked_message.is_absolute():
        linked_message = linked / linked_message
    primary_message.write_text("primary admin\n", encoding="utf-8")
    linked_message.write_text("linked admin\n", encoding="utf-8")

    package = tmp_path / "evidence" / "linked-package"
    capture_repository(linked, package)
    receipt = restore_drill(
        package,
        tmp_path / "restore-linked",
        tmp_path / "evidence" / "linked-receipt.json",
    )
    assert receipt["restore_verified"] is True


def test_sha256_repository_preserves_object_format(tmp_path: Path) -> None:
    repository = tmp_path / "sha256-source"
    repository.mkdir()
    _git(repository, "init", "--object-format=sha256", "-b", "main")
    _git(repository, "config", "user.name", "Recovery Test")
    _git(repository, "config", "user.email", "recovery@example.invalid")
    (repository / "value.txt").write_text("sha256\n", encoding="utf-8")
    _git(repository, "add", "value.txt")
    _git(repository, "commit", "-m", "sha256")

    package = tmp_path / "evidence" / "sha256-package"
    capture_repository(repository, package)
    receipt = restore_drill(
        package,
        tmp_path / "restore-sha256",
        tmp_path / "evidence" / "sha256-receipt.json",
    )
    assert receipt["restore_verified"] is True
    assert (
        _git(tmp_path / "restore-sha256", "rev-parse", "--show-object-format")
        == "sha256"
    )


def test_detached_manifest_exact_set_and_mutation_checks(tmp_path: Path) -> None:
    root = tmp_path / "seal"
    root.mkdir()
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    nested = root / "nested"
    nested.mkdir()
    (nested / "b.bin").write_bytes(b"\x00b")

    build_manifest(root)
    result = verify_manifest(root)
    assert result["verified"] is True
    assert result["covered_file_count"] == 2

    (root / "extra").write_text("extra\n", encoding="utf-8")
    with pytest.raises(DetachedManifestError, match="file set mismatch"):
        verify_manifest(root)


def test_detached_manifest_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    root = tmp_path / "seal"
    root.mkdir()
    target = root / "target"
    target.write_text("x", encoding="utf-8")
    (root / "link").symlink_to(target)
    with pytest.raises(DetachedManifestError, match="unsafe"):
        build_manifest(root)
    (root / "link").unlink()

    os.link(target, root / "hardlink")
    with pytest.raises(DetachedManifestError, match="unique regular"):
        build_manifest(root)


def test_detached_manifest_rejects_an_empty_root(tmp_path: Path) -> None:
    root = tmp_path / "seal"
    root.mkdir()
    with pytest.raises(DetachedManifestError, match="cannot be empty"):
        build_manifest(root)


def test_detached_manifest_rejects_root_symlink_bad_directory_and_crlf(
    tmp_path: Path,
) -> None:
    root = tmp_path / "seal"
    root.mkdir()
    (root / "covered").write_text("covered\n", encoding="utf-8")
    alias = tmp_path / "seal-alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(DetachedManifestError, match="symlinked"):
        build_manifest(alias)

    bad = root / "bad\ndir"
    bad.mkdir()
    with pytest.raises(DetachedManifestError, match="unsafe"):
        build_manifest(root)
    bad.rmdir()

    build_manifest(root)
    manifest = root / "manifest.sha256"
    manifest.write_bytes(manifest.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(DetachedManifestError, match="LF only"):
        verify_manifest(root)


def test_managed_python_contract_uses_explicit_root_with_private_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed_root = tmp_path / "operator" / ".local" / "share" / "uv" / "python"
    interpreter = managed_root / "cpython-3.11-test" / "bin" / "python3.11"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"managed-python-fixture\n")
    interpreter.chmod(0o700)
    invocation = tmp_path / "release" / ".venv" / "bin" / "python"
    invocation.parent.mkdir(parents=True)
    invocation.symlink_to(interpreter)

    private_home = tmp_path / "evidence-home"
    private_home.mkdir()
    monkeypatch.setenv("HOME", str(private_home))
    monkeypatch.setenv("HQA_UV_MANAGED_PYTHON_ROOT", str(managed_root))
    monkeypatch.setattr(recovery_module.sys, "_base_executable", str(interpreter))
    monkeypatch.setattr(recovery_module.sys, "executable", str(invocation))

    contract = recovery_module._managed_python_contract()

    assert contract["resolved_path"] == str(interpreter)
    assert contract["version"] == "3.11"


def test_managed_python_contract_derives_uv_root_with_private_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed_root = tmp_path / "operator" / ".local" / "share" / "uv" / "python"
    interpreter = managed_root / "cpython-3.11-test" / "bin" / "python3.11"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"managed-python-fixture\n")
    interpreter.chmod(0o700)
    invocation = tmp_path / "release" / ".venv" / "bin" / "python"
    invocation.parent.mkdir(parents=True)
    invocation.symlink_to(interpreter)

    private_home = tmp_path / "evidence-home"
    private_home.mkdir()
    monkeypatch.setenv("HOME", str(private_home))
    monkeypatch.delenv("HQA_UV_MANAGED_PYTHON_ROOT", raising=False)
    monkeypatch.setattr(recovery_module.sys, "_base_executable", str(interpreter))
    monkeypatch.setattr(recovery_module.sys, "executable", str(invocation))

    contract = recovery_module._managed_python_contract()

    assert contract["resolved_path"] == str(interpreter)
    assert contract["version"] == "3.11"


def test_managed_python_contract_rejects_broad_explicit_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interpreter = tmp_path / "bin" / "python3.11"
    interpreter.parent.mkdir()
    interpreter.write_bytes(b"unbound-python-fixture\n")
    interpreter.chmod(0o700)
    monkeypatch.setenv("HQA_UV_MANAGED_PYTHON_ROOT", str(tmp_path))
    monkeypatch.setattr(recovery_module.sys, "_base_executable", str(interpreter))
    monkeypatch.setattr(recovery_module.sys, "executable", str(interpreter))

    with pytest.raises(
        RepositoryRecoveryError,
        match="managed Python root must identify the uv install directory",
    ):
        recovery_module._managed_python_contract()
