from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest


def _git(repo: Path, *args: str, text: bool = True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def _make_repository(tmp_path: Path, repo: str) -> tuple[Path, str, str]:
    remote_checkout = tmp_path / f"{repo}-remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(remote_checkout)],
        check=True,
        capture_output=True,
    )
    checkout = tmp_path / repo
    checkout.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "candidate", str(checkout)],
        check=True,
        capture_output=True,
    )
    _git(checkout, "config", "user.name", "Manifest Test")
    _git(checkout, "config", "user.email", "manifest@example.invalid")
    local_remote = remote_checkout.resolve().as_uri()
    remote = f"https://example.invalid/{remote_checkout.name}"
    _git(checkout, "remote", "add", "origin", local_remote)
    (checkout / "source.txt").write_text(f"{repo}\n", encoding="utf-8")
    if repo == "hermes":
        gateway = checkout / "venv" / "bin" / "python"
        gateway.parent.mkdir(parents=True)
        gateway.symlink_to(Path(sys.executable).resolve())
        package = checkout / "hermes_cli"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "main.py").write_text(
            "import signal\n"
            "import time\n"
            "stopping = False\n"
            "def stop(*_args):\n"
            "    global stopping\n"
            "    stopping = True\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "signal.signal(signal.SIGINT, stop)\n"
            "while not stopping:\n"
            "    time.sleep(0.05)\n",
            encoding="utf-8",
        )
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-q", "-m", "initial")
    head = _git(checkout, "rev-parse", "HEAD").strip()
    _git(checkout, "push", "-q", "-u", "origin", "candidate")
    _git(checkout, "remote", "set-url", "origin", remote)
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


def _process_started_at(pid: int) -> str:
    output = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    ).stdout.strip()
    parsed = datetime.strptime(output, "%a %b %d %H:%M:%S %Y")
    local_timezone = datetime.now().astimezone().tzinfo
    assert local_timezone is not None
    return parsed.replace(tzinfo=local_timezone).astimezone().isoformat()


def _aligned_specs(tmp_path: Path):
    from hqa.release_manifest import (
        RepositorySpec,
        RuntimeSpec,
        runtime_command_sha256,
    )

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
    hermes_checkout, _, hermes_head, hermes_archive = expected["hermes"]
    command = (
        str(hermes_checkout / "venv" / "bin" / "python"),
        "-m",
        "hermes_cli.main",
        "gateway",
        "run",
        "--replace",
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=hermes_checkout,
    )
    for _ in range(50):
        if process.poll() is not None:
            raise AssertionError("test Hermes process exited early")
        try:
            started_at = _process_started_at(process.pid)
            break
        except subprocess.CalledProcessError:
            time.sleep(0.01)
    else:
        raise AssertionError("test Hermes process was not observable")
    stamp_path = tmp_path / "hermes-runtime-stamp.json"
    stamp_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repo": "hermes",
                "pid": process.pid,
                "started_at": started_at,
                "command_sha256": runtime_command_sha256(command),
                "version": "1.0.0",
                "source_commit": hermes_head,
                "source_archive_sha256": hermes_archive,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    stamp_path.chmod(0o600)
    runtime_specs.append(
        RuntimeSpec(
            repo="hermes",
            installed_checkout=hermes_checkout,
            command=command,
            version="1.0.0",
            installed_commit=hermes_head,
            installed_archive_sha256=hermes_archive,
            running_commit=hermes_head,
            running_archive_sha256=hermes_archive,
            pid=process.pid,
            started_at=started_at,
            environment={"APP_ENV": "test"},
            config={"chat_write_ready": False},
            runtime_stamp_path=stamp_path,
        )
    )
    return repository_specs, runtime_specs, expected, process


@pytest.fixture
def aligned_specs(tmp_path: Path, monkeypatch):
    import hqa.release_manifest as release_manifest

    def local_remote_head(remote: str, remote_ref: str):
        bare = tmp_path / Path(urlsplit(remote).path).name
        completed = subprocess.run(
            [
                "/usr/bin/git",
                f"--git-dir={bare}",
                "show-ref",
                "--hash",
                "--verify",
                remote_ref,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip() or None if completed.returncode == 0 else None

    monkeypatch.setattr(release_manifest, "_remote_head", local_remote_head)
    repository_specs, runtime_specs, expected, process = _aligned_specs(tmp_path)
    try:
        yield repository_specs, runtime_specs, expected
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def test_build_manifest_captures_three_repo_sources_and_required_runtime(
    aligned_specs,
) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, expected = aligned_specs

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
        assert repository.remote_published is True
        assert repository.remote_head_commit == head
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
    assert manifest.identity_manifest_ready is True
    assert manifest.write_ready is False
    assert manifest.runtimes[0].process_alive is True
    assert manifest.runtimes[0].command_matches is True
    assert manifest.runtimes[0].runtime_attested is True
    assert len(manifest.manifest_digest) == 64


def test_dirty_lists_require_exact_declarations_but_cleanliness_stays_distinct(
    aligned_specs,
) -> None:
    from hqa.release_manifest import RepositorySpec, build_release_manifest

    repository_specs, runtime_specs, expected = aligned_specs
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


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_hidden_git_index_paths_fail_closed(aligned_specs, index_flag: str) -> None:
    from hqa.release_manifest import ManifestIntegrityError, build_release_manifest

    repository_specs, runtime_specs, expected = aligned_specs
    hqa = expected["hqa"][0]
    _git(hqa, "update-index", index_flag, "source.txt")
    (hqa / "source.txt").write_text("hidden drift\n", encoding="utf-8")

    with pytest.raises(ManifestIntegrityError, match="assume-unchanged"):
        build_release_manifest(repository_specs, runtime_specs)


def test_runtime_metadata_is_a_sanitized_allowlist(aligned_specs) -> None:
    from hqa.release_manifest import RuntimeSpec

    _, runtime_specs, _ = aligned_specs
    runtime = runtime_specs[0]
    base = {
        field: getattr(runtime, field)
        for field in RuntimeSpec.__dataclass_fields__
    }
    rejected = (
        {"environment": {"OPENAI_API_KEY": "sk-secret"}},
        {"config": {"password": "secret"}},
        {"environment": {"UNREVIEWED_SETTING": "value"}},
        {"config": {"debug": True}},
        {"config": {"chat_write_ready": 1}},
        {"command": (runtime.command[0], "sk-live-secret")},
        {
            "command": (
                runtime.command[0],
                "--header",
                "Authorization: Bearer secret",
                "gateway",
                "run",
                "--replace",
            )
        },
        {
            "command": (
                runtime.command[0],
                "--key=secret",
                "hermes_cli.main",
                "gateway",
                "run",
                "--replace",
            )
        },
    )
    for override in rejected:
        with pytest.raises(ValueError):
            RuntimeSpec(**dict(base, **override))

    with pytest.raises(TypeError):
        RuntimeSpec(**dict(base, bearer_token="secret"))


def test_manifest_digest_is_canonical_and_verification_rejects_tampering(
    aligned_specs,
) -> None:
    from hqa.release_manifest import (
        ManifestIntegrityError,
        ManifestValidationError,
        build_release_manifest,
        validate_release_manifest_document,
        parse_release_manifest_json,
        verify_release_manifest,
    )

    repository_specs, runtime_specs, _ = aligned_specs
    first = build_release_manifest(repository_specs, runtime_specs)
    reordered = build_release_manifest(
        list(reversed(repository_specs)),
        list(reversed(runtime_specs)),
    )

    assert first.manifest_digest == reordered.manifest_digest
    assert first.to_json_bytes() == reordered.to_json_bytes()
    assert validate_release_manifest_document(first.to_dict()) == first
    assert parse_release_manifest_json(first.to_json_bytes()) == first
    assert verify_release_manifest(first, repository_specs, runtime_specs) == first

    tampered = first.to_dict()
    tampered["identity_manifest_ready"] = False
    with pytest.raises(ManifestIntegrityError):
        validate_release_manifest_document(tampered)

    unknown = first.to_dict()
    unknown["unexpected"] = "not part of schema v1"
    with pytest.raises(ManifestValidationError, match="unknown"):
        validate_release_manifest_document(unknown)

    with pytest.raises(ManifestValidationError, match="duplicate"):
        parse_release_manifest_json(
            b'{"schema_version":1,"schema_version":1}'
        )


def test_impossible_base_ancestry_is_rejected_even_if_resigned(
    aligned_specs,
) -> None:
    from hqa.release_manifest import (
        ManifestIntegrityError,
        build_release_manifest,
        validate_release_manifest_document,
    )

    repository_specs, runtime_specs, _ = aligned_specs
    document = build_release_manifest(repository_specs, runtime_specs).to_dict()
    document["repositories"][0]["base_present"] = False
    document["repositories"][0]["base_is_ancestor"] = True
    _resign(document)

    with pytest.raises(ManifestIntegrityError, match="base ancestry"):
        validate_release_manifest_document(document)


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
        {"expected_remote": "file:///tmp/local-only.git"},
        {"expected_remote": "ssh://git@example.invalid/hqa.git"},
        {"expected_remote": "https://user:password@example.invalid/hqa.git"},
        {"expected_remote": "https://example.invalid/hqa.git?token=secret"},
        {"expected_remote": "https://example.invalid/hqa.git#credential"},
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


def test_runtime_specs_reject_unverifiable_or_secret_bearing_identity(
    aligned_specs,
) -> None:
    from hqa.release_manifest import RuntimeSpec

    _, runtime_specs, _ = aligned_specs
    runtime = runtime_specs[0]
    base = {
        field: getattr(runtime, field)
        for field in RuntimeSpec.__dataclass_fields__
    }
    invalid = (
        {"repo": "other"},
        {"repo": "hqa"},
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
        {"runtime_stamp_path": Path("relative-stamp.json")},
    )
    for override in invalid:
        with pytest.raises((TypeError, ValueError)):
            RuntimeSpec(**dict(base, **override))


def test_verifier_rejects_invalid_runtime_identity_even_if_resigned(
    aligned_specs,
) -> None:
    from hqa.release_manifest import (
        ManifestValidationError,
        build_release_manifest,
        validate_release_manifest_document,
    )

    repository_specs, runtime_specs, _ = aligned_specs
    document = build_release_manifest(repository_specs, runtime_specs).to_dict()
    document["runtimes"][0]["pid"] = True
    _resign(document)

    with pytest.raises(ManifestValidationError, match="pid"):
        validate_release_manifest_document(document)


def test_resigned_valid_shape_requires_fresh_evidence(aligned_specs) -> None:
    from hqa.release_manifest import (
        ManifestIntegrityError,
        build_release_manifest,
        validate_release_manifest_document,
        verify_release_manifest,
    )

    repository_specs, runtime_specs, _ = aligned_specs
    document = build_release_manifest(repository_specs, runtime_specs).to_dict()
    document["runtimes"][0]["pid"] = 2**31 - 1
    _resign(document)

    checksum_valid = validate_release_manifest_document(document)
    assert checksum_valid.runtimes[0].pid == 2**31 - 1
    with pytest.raises(ManifestIntegrityError, match="fresh"):
        verify_release_manifest(document, repository_specs, runtime_specs)


def test_verifier_rejects_nonabsolute_checkout_even_if_resigned(
    aligned_specs,
) -> None:
    from hqa.release_manifest import (
        ManifestValidationError,
        build_release_manifest,
        validate_release_manifest_document,
    )

    repository_specs, runtime_specs, _ = aligned_specs
    document = build_release_manifest(repository_specs, runtime_specs).to_dict()
    document["repositories"][0]["checkout"] = "relative/checkout"
    _resign(document)

    with pytest.raises(ManifestValidationError, match="checkout"):
        validate_release_manifest_document(document)


def test_candidate_install_and_running_process_mismatches_fail_closed(
    aligned_specs,
) -> None:
    from hqa.release_manifest import (
        build_release_manifest,
        validate_release_manifest_document,
    )

    repository_specs, runtime_specs, _ = aligned_specs
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
    assert old_live.runtime_aligned is False
    assert "installed_identity_mismatch" in old_live.runtimes[0].blockers
    assert old_live.write_ready is False
    assert validate_release_manifest_document(old_live) == old_live

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


def test_nonexistent_runtime_pid_cannot_attest_or_enable_identity(
    aligned_specs,
) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    runtime_specs[0] = replace(runtime_specs[0], pid=2**31 - 1)

    manifest = build_release_manifest(repository_specs, runtime_specs)

    runtime = manifest.runtimes[0]
    assert runtime.process_alive is False
    assert runtime.command_matches is False
    assert runtime.runtime_attested is False
    assert runtime.blockers == ("process_missing", "runtime_stamp_invalid")
    assert manifest.runtime_aligned is False
    assert manifest.identity_manifest_ready is False
    assert manifest.write_ready is False


def test_runtime_stamp_is_required_for_alignment(aligned_specs) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    runtime_specs[0] = replace(runtime_specs[0], runtime_stamp_path=None)

    manifest = build_release_manifest(repository_specs, runtime_specs)

    assert manifest.runtimes[0].runtime_attested is False
    assert manifest.runtimes[0].blockers == ("runtime_stamp_missing",)
    assert manifest.runtime_aligned is False
    assert manifest.identity_manifest_ready is False


def test_runtime_stamp_symlink_fails_closed(aligned_specs, tmp_path: Path) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    assert runtime_specs[0].runtime_stamp_path is not None
    link = tmp_path / "runtime-stamp-link.json"
    link.symlink_to(runtime_specs[0].runtime_stamp_path)
    runtime_specs[0] = replace(runtime_specs[0], runtime_stamp_path=link)

    manifest = build_release_manifest(repository_specs, runtime_specs)

    assert manifest.runtimes[0].runtime_attested is False
    assert manifest.runtimes[0].blockers == ("runtime_stamp_invalid",)
    assert manifest.runtime_aligned is False


def test_runtime_stamp_hardlink_fails_closed(aligned_specs, tmp_path: Path) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    stamp_path = runtime_specs[0].runtime_stamp_path
    assert stamp_path is not None
    hardlink = tmp_path / "runtime-stamp-hardlink.json"
    os.link(stamp_path, hardlink)
    runtime_specs[0] = replace(runtime_specs[0], runtime_stamp_path=hardlink)

    manifest = build_release_manifest(repository_specs, runtime_specs)

    assert manifest.runtimes[0].runtime_attested is False
    assert manifest.runtimes[0].blockers == ("runtime_stamp_invalid",)


def test_runtime_stamp_identity_tamper_fails_closed(aligned_specs) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    stamp_path = runtime_specs[0].runtime_stamp_path
    assert stamp_path is not None
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    stamp["version"] = "forged-version"
    stamp_path.write_text(json.dumps(stamp, sort_keys=True), encoding="utf-8")

    manifest = build_release_manifest(repository_specs, runtime_specs)

    assert manifest.runtimes[0].runtime_attested is False
    assert manifest.runtimes[0].blockers == ("runtime_stamp_invalid",)
    assert manifest.runtime_aligned is False


def test_runtime_stamp_must_be_owner_only_0600(aligned_specs) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    stamp_path = runtime_specs[0].runtime_stamp_path
    assert stamp_path is not None
    stamp_path.chmod(0o644)

    manifest = build_release_manifest(repository_specs, runtime_specs)

    assert manifest.runtimes[0].runtime_attested is False
    assert manifest.runtimes[0].blockers == ("runtime_stamp_invalid",)


def test_live_pid_with_wrong_command_fails_closed(aligned_specs) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    sleeper = subprocess.Popen(
        ["sleep", "30"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        started_at = _process_started_at(sleeper.pid)
        runtime_specs[0] = replace(
            runtime_specs[0], pid=sleeper.pid, started_at=started_at
        )

        manifest = build_release_manifest(repository_specs, runtime_specs)

        runtime = manifest.runtimes[0]
        assert runtime.process_alive is True
        assert runtime.command_matches is False
        assert runtime.runtime_attested is False
        assert runtime.blockers == (
            "process_command_mismatch",
            "runtime_stamp_invalid",
        )
        assert manifest.runtime_aligned is False
        assert manifest.identity_manifest_ready is False
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=3)


def test_process_command_requires_an_exact_argv_not_a_suffix(
    aligned_specs, tmp_path: Path
) -> None:
    from hqa.release_manifest import _observed_command_matches

    _, runtime_specs, _ = aligned_specs
    expected = runtime_specs[0].command
    assert _observed_command_matches(expected, expected) is True
    assert _observed_command_matches(expected, ("/bin/sh", *expected)) is False

    fake_python = tmp_path / "not-a-framework" / "Versions" / "1" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("fake", encoding="utf-8")
    fake_expected = (str(fake_python), *expected[1:])
    fake_observed = (
        str(
            fake_python.parent.parent
            / "Resources"
            / "Python.app"
            / "Contents"
            / "MacOS"
            / "Python"
        ),
        *expected[1:],
    )
    assert _observed_command_matches(fake_expected, fake_observed) is False


def test_archive_limit_is_enforced_while_capturing(
    aligned_specs, monkeypatch
) -> None:
    import hqa.release_manifest as release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    monkeypatch.setattr(release_manifest, "_MAX_ARCHIVE_BYTES", 128)

    with pytest.raises(
        release_manifest.ManifestIntegrityError,
        match="archive exceeds",
    ):
        release_manifest.build_release_manifest(repository_specs, runtime_specs)


def test_fresh_verification_detects_checkout_drift(aligned_specs) -> None:
    from hqa.release_manifest import (
        ManifestIntegrityError,
        build_release_manifest,
        verify_release_manifest,
    )

    repository_specs, runtime_specs, expected = aligned_specs
    manifest = build_release_manifest(repository_specs, runtime_specs)
    (expected["hqa"][0] / "later.txt").write_text("drift\n", encoding="utf-8")

    with pytest.raises(ManifestIntegrityError, match="fresh"):
        verify_release_manifest(manifest, repository_specs, runtime_specs)


def test_repository_head_change_during_capture_fails_closed(
    aligned_specs, monkeypatch
) -> None:
    import hqa.release_manifest as release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    original = release_manifest._run_git
    state = {"changed": False}

    def racing_git(checkout, *args, text=True):
        output = original(checkout, *args, text=text)
        if (
            checkout.name == "hqa"
            and args == ("rev-parse", "HEAD^{commit}")
            and not state["changed"]
        ):
            state["changed"] = True
            (checkout / "source.txt").write_text("raced\n", encoding="utf-8")
            _git(checkout, "add", "source.txt")
            _git(checkout, "commit", "-q", "-m", "racing commit")
        return output

    monkeypatch.setattr(release_manifest, "_run_git", racing_git)

    with pytest.raises(
        release_manifest.ManifestIntegrityError,
        match="changed during evidence capture",
    ):
        release_manifest.build_release_manifest(repository_specs, runtime_specs)


def test_verifier_rejects_integer_readiness_even_if_resigned(aligned_specs) -> None:
    from hqa.release_manifest import (
        ManifestValidationError,
        build_release_manifest,
        validate_release_manifest_document,
    )

    repository_specs, runtime_specs, _ = aligned_specs
    document = build_release_manifest(repository_specs, runtime_specs).to_dict()
    document["candidate_source_committed"] = 1
    _resign(document)

    with pytest.raises(ManifestValidationError, match="boolean"):
        validate_release_manifest_document(document)


def test_builder_refuses_to_capture_credential_bearing_remote(aligned_specs) -> None:
    from hqa.release_manifest import ManifestValidationError, build_release_manifest

    repository_specs, runtime_specs, expected = aligned_specs
    _git(
        expected["hermes"][0],
        "remote",
        "set-url",
        "origin",
        "https://user:password@example.invalid/hermes.git",
    )

    with pytest.raises(ManifestValidationError, match="credential"):
        build_release_manifest(repository_specs, runtime_specs)


def test_optional_repositories_do_not_require_fabricated_process_identity(
    aligned_specs,
) -> None:
    from hqa.release_manifest import build_release_manifest, verify_release_manifest

    repository_specs, runtime_specs, _ = aligned_specs
    hermes_runtime = [item for item in runtime_specs if item.repo == "hermes"]

    manifest = build_release_manifest(repository_specs, hermes_runtime)

    assert [item.repo for item in manifest.runtimes] == ["hermes"]
    assert manifest.runtime_coverage is True
    assert manifest.runtime_blockers == ()
    assert manifest.candidate_installed is True
    assert manifest.runtime_aligned is True
    assert manifest.identity_manifest_ready is True
    assert manifest.write_ready is False
    assert verify_release_manifest(manifest, repository_specs, hermes_runtime) == manifest


def test_missing_required_hermes_runtime_is_an_explicit_blocker(
    aligned_specs,
) -> None:
    from hqa.release_manifest import build_release_manifest, verify_release_manifest

    repository_specs, _, _ = aligned_specs

    manifest = build_release_manifest(repository_specs, [])

    assert manifest.runtimes == ()
    assert manifest.runtime_coverage is False
    assert manifest.runtime_blockers == ("missing_required_runtime:hermes",)
    assert manifest.candidate_installed is False
    assert manifest.runtime_aligned is False
    assert manifest.identity_manifest_ready is False
    assert manifest.write_ready is False
    assert verify_release_manifest(manifest, repository_specs, []) == manifest


def test_repository_capture_uses_the_explicit_remote_name(
    aligned_specs, tmp_path: Path
) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, expected = aligned_specs
    hermes_checkout = expected["hermes"][0]
    fork_checkout = tmp_path / "hermes-fork.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(fork_checkout)],
        check=True,
        capture_output=True,
    )
    local_fork_remote = fork_checkout.resolve().as_uri()
    fork_remote = f"https://example.invalid/{fork_checkout.name}"
    _git(hermes_checkout, "remote", "add", "yiboway", local_fork_remote)
    _git(hermes_checkout, "push", "-q", "yiboway", "candidate")
    _git(hermes_checkout, "remote", "set-url", "yiboway", fork_remote)
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


def test_unpublished_local_head_is_not_remote_source_identity(
    aligned_specs, tmp_path: Path
) -> None:
    from hqa.release_manifest import build_release_manifest

    repository_specs, runtime_specs, expected = aligned_specs
    remote_uri = expected["hqa"][1]
    remote_path = tmp_path / Path(urlsplit(remote_uri).path).name
    subprocess.run(
        [
            "git",
            f"--git-dir={remote_path}",
            "update-ref",
            "-d",
            "refs/heads/candidate",
        ],
        check=True,
        capture_output=True,
    )

    manifest = build_release_manifest(repository_specs, runtime_specs)

    hqa = next(item for item in manifest.repositories if item.repo == "hqa")
    assert hqa.local_checkout_identity_matches is True
    assert hqa.remote_head_commit is None
    assert hqa.remote_published is False
    assert hqa.source_identity_matches is False
    assert manifest.candidate_source_committed is False
    assert manifest.identity_manifest_ready is False
