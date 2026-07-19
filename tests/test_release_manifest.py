from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest


def _git(repo: Path, *args: str, text: bool = True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def _make_repository(tmp_path: Path, repo: str) -> tuple[Path, str, str]:
    checkout = tmp_path / repo
    checkout.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "candidate", str(checkout)],
        check=True,
        capture_output=True,
    )
    _git(checkout, "config", "user.name", "Manifest Test")
    _git(checkout, "config", "user.email", "manifest@example.invalid")
    remote = f"https://example.invalid/{repo}.git"
    _git(checkout, "remote", "add", "origin", remote)
    (checkout / "source.txt").write_text(f"{repo}\n", encoding="utf-8")
    _git(checkout, "add", "source.txt")
    _git(checkout, "commit", "-q", "-m", "initial")
    head = _git(checkout, "rev-parse", "HEAD").strip()
    return checkout, remote, head


def _archive_sha256(checkout: Path) -> str:
    archive = _git(checkout, "archive", "--format=tar", "HEAD", text=False)
    return hashlib.sha256(archive).hexdigest()


def _resign(document: dict) -> None:
    basis = {key: value for key, value in document.items() if key != "manifest_digest"}
    document["manifest_digest"] = hashlib.sha256(
        json.dumps(
            basis,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _aligned_specs(tmp_path: Path):
    from hqa.release_manifest import RepositorySpec, RuntimeSpec

    repository_specs = []
    runtime_specs = []
    expected = {}
    for index, repo in enumerate(("hqa", "platform", "hermes"), start=1):
        checkout, remote, head = _make_repository(tmp_path, repo)
        archive_sha256 = _archive_sha256(checkout)
        expected[repo] = (checkout.resolve(), remote, head, archive_sha256)
        repository_specs.append(
            RepositorySpec(
                repo=repo,
                checkout=checkout,
                expected_remote=remote,
                expected_branch="candidate",
                expected_base_commit=head,
                expected_head_commit=head,
            )
        )
        if repo == "hermes":
            runtime_specs.append(
                RuntimeSpec(
                    repo=repo,
                    command=(f"/opt/{repo}/server", "--read-only"),
                    version="1.0.0",
                    installed_commit=head,
                    installed_archive_sha256=archive_sha256,
                    running_commit=head,
                    running_archive_sha256=archive_sha256,
                    pid=1000 + index,
                    started_at=f"2026-07-19T00:00:0{index}Z",
                    environment={"APP_ENV": "test"},
                    config={"chat_write_ready": False},
                )
            )
    return repository_specs, runtime_specs, expected


def test_build_manifest_captures_three_repo_sources_and_required_runtime(
    tmp_path: Path,
) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, expected = _aligned_specs(tmp_path)

    manifest = build_release_manifest(repository_specs, runtime_specs)

    assert manifest.schema_version == 1
    assert [item.repo for item in manifest.repositories] == [
        "hermes",
        "hqa",
        "platform",
    ]
    for repository in manifest.repositories:
        checkout, remote, head, archive_sha256 = expected[repository.repo]
        assert repository.checkout == str(checkout)
        assert repository.remote == remote
        assert repository.branch == "candidate"
        assert repository.parent_commit is None
        assert repository.base_commit == head
        assert repository.head_commit == head
        assert len(repository.tree_oid) == 40
        assert repository.archive_sha256 == archive_sha256
        assert repository.tracked_dirty == ()
        assert repository.untracked_dirty == ()
        assert repository.dirty_matches is True
    assert manifest.dirty_declarations_match is True
    assert manifest.candidate_source_committed is True
    assert manifest.working_trees_clean is True
    assert manifest.candidate_installed is True
    assert manifest.runtime_coverage is True
    assert manifest.runtime_blockers == ()
    assert manifest.runtime_aligned is True
    assert manifest.write_ready is True
    assert len(manifest.manifest_digest) == 64


def test_dirty_lists_require_exact_declarations_but_cleanliness_stays_distinct(
    tmp_path: Path,
) -> None:
    from hqa.release_manifest import RepositorySpec, build_release_manifest

    repository_specs, runtime_specs, expected = _aligned_specs(tmp_path)
    platform = expected["platform"][0]
    (platform / "source.txt").write_text("changed\n", encoding="utf-8")
    (platform / "notes").mkdir()
    (platform / "notes" / "new.txt").write_text("new\n", encoding="utf-8")

    undeclared = build_release_manifest(repository_specs, runtime_specs)
    platform_record = next(
        item for item in undeclared.repositories if item.repo == "platform"
    )
    assert platform_record.tracked_dirty == ("source.txt",)
    assert platform_record.untracked_dirty == ("notes/new.txt",)
    assert platform_record.dirty_matches is False
    assert platform_record.working_tree_clean is False
    assert undeclared.dirty_declarations_match is False
    assert undeclared.candidate_source_committed is True
    assert undeclared.working_trees_clean is False
    assert undeclared.write_ready is False

    repository_specs[1] = RepositorySpec(
        repo="platform",
        checkout=platform,
        expected_remote=expected["platform"][1],
        expected_branch="candidate",
        expected_base_commit=expected["platform"][2],
        expected_head_commit=expected["platform"][2],
        declared_tracked_dirty=("source.txt",),
        declared_untracked_dirty=("notes/new.txt",),
    )
    declared = build_release_manifest(repository_specs, runtime_specs)
    assert declared.dirty_declarations_match is True
    assert declared.candidate_source_committed is True
    assert declared.working_trees_clean is False
    assert declared.write_ready is False


def test_runtime_metadata_is_a_sanitized_allowlist() -> None:
    from hqa.release_manifest import RuntimeSpec

    base = {
        "repo": "hermes",
        "command": ("/opt/hermes/server", "--read-only"),
        "version": "1.0.0",
        "installed_commit": "1" * 40,
        "installed_archive_sha256": "2" * 64,
        "running_commit": "1" * 40,
        "running_archive_sha256": "2" * 64,
        "pid": 1001,
        "started_at": "2026-07-19T00:00:01Z",
        "environment": {"APP_ENV": "test"},
        "config": {"chat_write_ready": False},
    }
    rejected = (
        {"environment": {"OPENAI_API_KEY": "sk-secret"}},
        {"config": {"password": "secret"}},
        {"environment": {"UNREVIEWED_SETTING": "value"}},
        {"config": {"debug": True}},
        {"config": {"chat_write_ready": 1}},
    )
    for override in rejected:
        with pytest.raises(ValueError):
            RuntimeSpec(**dict(base, **override))

    with pytest.raises(TypeError):
        RuntimeSpec(**dict(base, bearer_token="secret"))


def test_manifest_digest_is_canonical_and_verification_rejects_tampering(
    tmp_path: Path,
) -> None:
    from hqa.release_manifest import (
        ManifestIntegrityError,
        ManifestValidationError,
        build_release_manifest,
        verify_release_manifest,
    )

    repository_specs, runtime_specs, _ = _aligned_specs(tmp_path)
    first = build_release_manifest(repository_specs, runtime_specs)
    reordered = build_release_manifest(
        list(reversed(repository_specs)),
        list(reversed(runtime_specs)),
    )

    assert first.manifest_digest == reordered.manifest_digest
    assert first.to_json_bytes() == reordered.to_json_bytes()
    assert verify_release_manifest(first.to_dict()) == first

    tampered = first.to_dict()
    tampered["write_ready"] = False
    with pytest.raises(ManifestIntegrityError):
        verify_release_manifest(tampered)

    unknown = first.to_dict()
    unknown["unexpected"] = "not part of schema v1"
    with pytest.raises(ManifestValidationError, match="unknown"):
        verify_release_manifest(unknown)


def test_repository_specs_reject_unknown_identity_and_unsafe_dirty_paths() -> None:
    from hqa.release_manifest import RepositorySpec

    base = {
        "repo": "hqa",
        "checkout": Path("/tmp/manifest-test-repo"),
        "expected_remote": "https://example.invalid/hqa.git",
        "expected_branch": "candidate",
        "expected_base_commit": "1" * 40,
        "expected_head_commit": "2" * 40,
    }
    invalid = (
        {"repo": "other"},
        {"expected_remote": "https://user:password@example.invalid/hqa.git"},
        {"expected_branch": ""},
        {"expected_base_commit": "not-a-git-oid"},
        {"expected_head_commit": "A" * 40},
        {"declared_tracked_dirty": ("../outside",)},
        {"declared_untracked_dirty": ("/absolute",)},
        {"declared_untracked_dirty": ("same.txt", "same.txt")},
    )
    for override in invalid:
        with pytest.raises((TypeError, ValueError)):
            RepositorySpec(**dict(base, **override))

    with pytest.raises(TypeError):
        RepositorySpec(**dict(base, unexpected="value"))


def test_runtime_specs_reject_unverifiable_or_secret_bearing_identity() -> None:
    from hqa.release_manifest import RuntimeSpec

    base = {
        "repo": "hermes",
        "command": ("/opt/hermes/server", "--read-only"),
        "version": "1.0.0",
        "installed_commit": "1" * 40,
        "installed_archive_sha256": "2" * 64,
        "running_commit": "1" * 40,
        "running_archive_sha256": "2" * 64,
        "pid": 1001,
        "started_at": "2026-07-19T00:00:01Z",
        "environment": {"APP_ENV": "test"},
        "config": {"chat_write_ready": False},
    }
    invalid = (
        {"repo": "other"},
        {"command": ()},
        {"command": ("server", "--api-key=secret")},
        {"version": ""},
        {"installed_commit": "short"},
        {"installed_archive_sha256": "A" * 64},
        {"running_commit": "short"},
        {"running_archive_sha256": "2" * 63},
        {"pid": True},
        {"pid": 0},
        {"started_at": "2026-07-19T00:00:01"},
    )
    for override in invalid:
        with pytest.raises((TypeError, ValueError)):
            RuntimeSpec(**dict(base, **override))


def test_verifier_rejects_invalid_runtime_identity_even_if_resigned(
    tmp_path: Path,
) -> None:
    from hqa.release_manifest import (
        ManifestValidationError,
        build_release_manifest,
        verify_release_manifest,
    )

    repository_specs, runtime_specs, _ = _aligned_specs(tmp_path)
    document = build_release_manifest(repository_specs, runtime_specs).to_dict()
    document["runtimes"][0]["pid"] = True
    _resign(document)

    with pytest.raises(ManifestValidationError, match="pid"):
        verify_release_manifest(document)


def test_verifier_rejects_nonabsolute_checkout_even_if_resigned(
    tmp_path: Path,
) -> None:
    from hqa.release_manifest import (
        ManifestValidationError,
        build_release_manifest,
        verify_release_manifest,
    )

    repository_specs, runtime_specs, _ = _aligned_specs(tmp_path)
    document = build_release_manifest(repository_specs, runtime_specs).to_dict()
    document["repositories"][0]["checkout"] = "relative/checkout"
    _resign(document)

    with pytest.raises(ManifestValidationError, match="checkout"):
        verify_release_manifest(document)


def test_candidate_install_and_running_process_mismatches_fail_closed(
    tmp_path: Path,
) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, _ = _aligned_specs(tmp_path)
    hermes_index = next(
        index for index, item in enumerate(runtime_specs) if item.repo == "hermes"
    )
    runtime_specs[hermes_index] = replace(
        runtime_specs[hermes_index],
        installed_commit="a" * 40,
        installed_archive_sha256="b" * 64,
        running_commit="a" * 40,
        running_archive_sha256="b" * 64,
    )
    old_live = build_release_manifest(repository_specs, runtime_specs)
    assert old_live.candidate_source_committed is True
    assert old_live.candidate_installed is False
    assert old_live.runtime_aligned is True
    assert old_live.write_ready is False

    actual = next(item for item in old_live.repositories if item.repo == "hermes")
    runtime_specs[hermes_index] = replace(
        runtime_specs[hermes_index],
        installed_commit=actual.head_commit,
        installed_archive_sha256=actual.archive_sha256,
        running_commit="c" * 40,
        running_archive_sha256="d" * 64,
    )
    stale_process = build_release_manifest(repository_specs, runtime_specs)
    assert stale_process.candidate_source_committed is True
    assert stale_process.candidate_installed is True
    assert stale_process.runtime_aligned is False
    assert stale_process.write_ready is False


def test_fresh_verification_detects_checkout_drift(tmp_path: Path) -> None:
    from hqa.release_manifest import (
        ManifestIntegrityError,
        build_release_manifest,
        verify_release_manifest,
    )

    repository_specs, runtime_specs, expected = _aligned_specs(tmp_path)
    manifest = build_release_manifest(repository_specs, runtime_specs)
    (expected["hqa"][0] / "later.txt").write_text("drift\n", encoding="utf-8")

    with pytest.raises(ManifestIntegrityError, match="fresh"):
        verify_release_manifest(manifest, repository_specs, runtime_specs)


def test_verifier_rejects_integer_readiness_even_if_resigned(tmp_path: Path) -> None:
    from hqa.release_manifest import (
        ManifestValidationError,
        build_release_manifest,
        verify_release_manifest,
    )

    repository_specs, runtime_specs, _ = _aligned_specs(tmp_path)
    document = build_release_manifest(repository_specs, runtime_specs).to_dict()
    document["candidate_source_committed"] = 1
    _resign(document)

    with pytest.raises(ManifestValidationError, match="boolean"):
        verify_release_manifest(document)


def test_builder_refuses_to_capture_credential_bearing_remote(tmp_path: Path) -> None:
    from hqa.release_manifest import ManifestValidationError, build_release_manifest

    repository_specs, runtime_specs, expected = _aligned_specs(tmp_path)
    _git(
        expected["hermes"][0],
        "remote",
        "set-url",
        "origin",
        "https://user:password@example.invalid/hermes.git",
    )

    with pytest.raises(ManifestValidationError, match="credentials"):
        build_release_manifest(repository_specs, runtime_specs)


def test_optional_repositories_do_not_require_fabricated_process_identity(
    tmp_path: Path,
) -> None:
    from hqa.release_manifest import build_release_manifest, verify_release_manifest

    repository_specs, runtime_specs, _ = _aligned_specs(tmp_path)
    hermes_runtime = [item for item in runtime_specs if item.repo == "hermes"]

    manifest = build_release_manifest(repository_specs, hermes_runtime)

    assert [item.repo for item in manifest.runtimes] == ["hermes"]
    assert manifest.runtime_coverage is True
    assert manifest.runtime_blockers == ()
    assert manifest.candidate_installed is True
    assert manifest.runtime_aligned is True
    assert manifest.write_ready is True
    assert verify_release_manifest(manifest) == manifest


def test_missing_required_hermes_runtime_is_an_explicit_blocker(
    tmp_path: Path,
) -> None:
    from hqa.release_manifest import build_release_manifest, verify_release_manifest

    repository_specs, _, _ = _aligned_specs(tmp_path)

    manifest = build_release_manifest(repository_specs, [])

    assert manifest.runtimes == ()
    assert manifest.runtime_coverage is False
    assert manifest.runtime_blockers == ("missing_required_runtime:hermes",)
    assert manifest.candidate_installed is False
    assert manifest.runtime_aligned is False
    assert manifest.write_ready is False
    assert verify_release_manifest(manifest) == manifest


def test_repository_capture_uses_the_explicit_remote_name(tmp_path: Path) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, expected = _aligned_specs(tmp_path)
    hermes_checkout = expected["hermes"][0]
    fork_remote = "https://example.invalid/user/hermes.git"
    _git(hermes_checkout, "remote", "add", "yiboway", fork_remote)
    hermes_index = next(
        index for index, item in enumerate(repository_specs) if item.repo == "hermes"
    )
    repository_specs[hermes_index] = replace(
        repository_specs[hermes_index],
        remote_name="yiboway",
        expected_remote=fork_remote,
    )

    manifest = build_release_manifest(repository_specs, runtime_specs)
    hermes = next(item for item in manifest.repositories if item.repo == "hermes")
    assert hermes.remote_name == "yiboway"
    assert hermes.remote == fork_remote
    assert hermes.source_identity_matches is True
