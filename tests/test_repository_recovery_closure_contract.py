from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hqa import repository_recovery, repository_recovery_cli
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


def _repository(
    tmp_path: Path,
    *,
    build_timeout_child: bool = False,
    build_timeout_child_ignores_first_term: bool = False,
    wheel_pth_payload: bytes | None = None,
) -> Path:
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
    (repository / "README.md").write_text("closure fixture\n", encoding="utf-8")
    (repository / "hqa").mkdir()
    (repository / "hqa" / "__init__.py").write_text(
        'VALUE = "closure-fixture"\n', encoding="utf-8"
    )
    (repository / "pyproject.toml").write_text(
        "[build-system]\n"
        "requires = []\n"
        'build-backend = "build_backend"\n'
        'backend-path = ["."]\n'
        "\n"
        "[project]\n"
        'name = "hermes-quant-agent"\n'
        'version = "0.0.0"\n'
        'readme = "README.md"\n'
        'requires-python = ">=3.11"\n'
        "dependencies = []\n"
        "\n"
        "[project.optional-dependencies]\n"
        "dev = []\n",
        encoding="utf-8",
    )
    (repository / "uv.lock").write_text(
        "version = 1\n"
        "revision = 3\n"
        'requires-python = ">=3.11"\n'
        "\n"
        "[[package]]\n"
        'name = "hermes-quant-agent"\n'
        'version = "0.0.0"\n'
        'source = { editable = "." }\n'
        "\n"
        "[package.optional-dependencies]\n"
        "dev = []\n"
        "\n"
        "[package.metadata]\n"
        'provides-extras = ["dev"]\n',
        encoding="utf-8",
    )
    wheel_pth_entry = (
        ""
        if wheel_pth_payload is None
        else f"        'closure_hook.pth': {wheel_pth_payload!r},\n"
    )
    if build_timeout_child_ignores_first_term:
        timeout_build_prefix = (
            "    child_code = ("
            "\"import os,signal,time;from pathlib import Path;\""
            "\"signal.signal(signal.SIGTERM,lambda *_:"
            "signal.signal(signal.SIGTERM,signal.SIG_DFL));\""
            "\"Path('timeout-child-ready').write_text('ready');\""
            "\"os.close(1);os.close(2);time.sleep(60)\""
            ")\n"
            "    child = subprocess.Popen([sys.executable, '-c', child_code])\n"
            "    Path('timeout-child.pid').write_text(str(child.pid), encoding='utf-8')\n"
            "    while not Path('timeout-child-ready').exists():\n"
            "        time.sleep(0.01)\n"
            "    time.sleep(60)\n"
        )
    elif build_timeout_child:
        timeout_build_prefix = (
            "    child = subprocess.Popen(['/bin/sleep', '60'])\n"
            "    Path('timeout-child.pid').write_text(str(child.pid), encoding='utf-8')\n"
            "    time.sleep(60)\n"
        )
    else:
        timeout_build_prefix = ""
    (repository / "build_backend.py").write_text(
        "from __future__ import annotations\n"
        "\n"
        "import base64\n"
        "import hashlib\n"
        "from pathlib import Path\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "import zipfile\n"
        "\n"
        "def get_requires_for_build_wheel(config_settings=None):\n"
        "    return []\n"
        "\n"
        "def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):\n"
        + timeout_build_prefix
        +
        "    name = 'hermes_quant_agent-0.0.0'\n"
        "    dist_info = name + '.dist-info'\n"
        "    files = {\n"
        "        'hqa/__init__.py': Path('hqa/__init__.py').read_bytes(),\n"
        "        dist_info + '/METADATA': (\n"
        "            b'Metadata-Version: 2.3\\nName: hermes-quant-agent\\n'\n"
        "            b'Version: 0.0.0\\n\\n'\n"
        "        ),\n"
        "        dist_info + '/WHEEL': (\n"
        "            b'Wheel-Version: 1.0\\nGenerator: closure-fixture\\n'\n"
        "            b'Root-Is-Purelib: true\\nTag: py3-none-any\\n\\n'\n"
        "        ),\n"
        + wheel_pth_entry
        +
        "    }\n"
        "    rows = []\n"
        "    for path, payload in files.items():\n"
        "        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b'=')\n"
        "        rows.append(f'{path},sha256={digest.decode()},{len(payload)}')\n"
        "    record = dist_info + '/RECORD'\n"
        "    files[record] = ('\\n'.join(rows) + f'\\n{record},,\\n').encode()\n"
        "    wheel = name + '-py3-none-any.whl'\n"
        "    target = Path(wheel_directory) / wheel\n"
        "    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:\n"
        "        for path, payload in files.items():\n"
        "            archive.writestr(path, payload)\n"
        "    return wheel\n",
        encoding="utf-8",
    )
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


def _command_spec(tmp_path: Path) -> tuple[Path, str]:
    spec = tmp_path / "planned-environment-rebuild.json"
    payload = {
        "allowed_external_symlink_targets": [
            (
                "/Users/sunyibo/.local/share/uv/python/"
                "cpython-3.11-macos-aarch64-none/bin/python3.11"
            )
        ],
        "allowed_write_roots": ["{repository}/.venv"],
        "argv": [
            "/opt/homebrew/bin/uv",
            "venv",
            "--clear",
            "--offline",
            "--no-python-downloads",
            "--cache-dir",
            "{repository}/.venv/.uv-cache",
            "--python",
            "/Users/sunyibo/.local/bin/python3.11",
            "{repository}/.venv",
        ],
        "cwd": "{repository}",
        "environment": {},
        "expected_exit_code": 0,
        "network_allowed": False,
        "schema_version": "hqa.repository-command-rehearsal.v1",
        "side_effect_classification": "environment_rebuild",
        "required_paths": [
            "{repository}/.venv/pyvenv.cfg",
            "{repository}/.venv/bin/python",
        ],
    }
    spec.write_text(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    spec.chmod(0o600)
    return spec, hashlib.sha256(spec.read_bytes()).hexdigest()


def _marker_command_spec(
    tmp_path: Path,
    script: str,
    *,
    required_path: str = "{repository}/.venv/rehearsal-marker",
) -> tuple[Path, str]:
    spec = tmp_path / "marker-command.json"
    document = {
        "allowed_external_symlink_targets": [],
        "allowed_write_roots": ["{repository}/.venv"],
        "argv": [sys.executable, "-c", script, "{repository}"],
        "cwd": "{repository}",
        "environment": {},
        "expected_exit_code": 0,
        "network_allowed": False,
        "required_paths": [required_path],
        "schema_version": "hqa.repository-command-rehearsal.v1",
        "side_effect_classification": "environment_rebuild",
    }
    spec.write_text(
        json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    spec.chmod(0o600)
    return spec, hashlib.sha256(spec.read_bytes()).hexdigest()


def _rewrite_receipt_and_reindex(
    package: Path, receipt: dict[str, object]
) -> None:
    receipt_payload = (
        json.dumps(
            receipt,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    (package / "restore-receipt.json").write_bytes(receipt_payload)
    index = json.loads((package / "recovery-files.json").read_bytes())
    entry = next(
        item
        for item in index["entries"]
        if item["path"] == "restore-receipt.json"
    )
    entry["bytes"] = len(receipt_payload)
    entry["sha256"] = hashlib.sha256(receipt_payload).hexdigest()
    (package / "recovery-files.json").write_text(
        json.dumps(index, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rewrite_json_member_and_reindex(
    package: Path,
    name: str,
    document: dict[str, object],
) -> None:
    payload = (
        json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    (package / name).write_bytes(payload)
    index = json.loads((package / "recovery-files.json").read_bytes())
    entry = next(item for item in index["entries"] if item["path"] == name)
    entry["bytes"] = len(payload)
    entry["sha256"] = hashlib.sha256(payload).hexdigest()
    (package / "recovery-files.json").write_text(
        json.dumps(index, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_marker_command_cannot_verify_an_environment_rebuild(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    command_spec, command_spec_sha256 = _marker_command_spec(
        tmp_path,
        (
            "from pathlib import Path; import sys; "
            "root=Path(sys.argv[1]) / '.venv'; root.mkdir(); "
            "(root / 'rehearsal-marker').write_text('not a rebuild')"
        ),
    )
    package = tmp_path / "evidence" / "package"

    with pytest.raises(
        RepositoryRecoveryError,
        match="caller-authored rehearsal command specs are forbidden",
    ):
        capture_and_drill_closure_repository(
            repository,
            package,
            tmp_path / "restore-first",
            tmp_path / "restore-second",
            None,
            rehearsal_patch_sha256=None,
            rehearsal_command_spec=command_spec,
            rehearsal_command_spec_sha256=command_spec_sha256,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt6-test-operator",
        )
    assert not package.exists()


def test_patch_rehearsal_cannot_certify_release_recovery(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    patch, patch_sha256 = _rehearsal_patch(tmp_path)

    with pytest.raises(
        RepositoryRecoveryError,
        match="patch rehearsals cannot certify release recovery",
    ):
        capture_and_drill_closure_repository(
            repository,
            tmp_path / "evidence" / "package",
            tmp_path / "restore-first",
            tmp_path / "restore-second",
            patch,
            rehearsal_patch_sha256=patch_sha256,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt6-test-operator",
        )


def test_command_rehearsal_rebuilds_ignored_environment_only_in_first_restore(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    source_before = repository_identity(repository)
    package = tmp_path / "evidence" / "package"
    first = tmp_path / "restores" / "first"
    second = tmp_path / "restores" / "second"

    result = capture_and_drill_closure_repository(
        repository,
        package,
        first,
        second,
        None,
        rehearsal_patch_sha256=None,
        rehearsal_rebuild=True,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt5-test-operator",
    )

    assert result["restore_verified"] is True
    smoke = subprocess.run(
        [
            str(first / ".venv" / "runtime" / "bin" / "python"),
            "-I",
            "-B",
            "-c",
            (
                "import hqa,sys; "
                "assert sys.version_info[:2] == (3, 11); "
                "assert '/.venv/runtime/' in hqa.__file__"
            ),
        ],
        check=False,
        capture_output=True,
    )
    assert smoke.returncode == 0, smoke.stderr.decode()
    assert not (second / ".venv").exists()
    assert repository_identity(repository) == source_before
    assert repository_identity(second) == source_before

    receipt = json.loads((package / "restore-receipt.json").read_bytes())
    rehearsal = receipt["rehearsal"]
    assert rehearsal["command_exit_code"] == 0
    assert rehearsal["enabled"] is True
    assert rehearsal["environment_names"] == [
        "LANG",
        "LC_ALL",
        "PATH",
        "UV_PROJECT_ENVIRONMENT",
    ]
    assert rehearsal["executable_path"] == str(
        Path("/opt/homebrew/bin/uv").resolve()
    )
    assert len(rehearsal["executable_sha256"]) == 64
    assert len(rehearsal["input_sha256"]) == 64
    assert rehearsal["required_paths_present"] is True
    assert rehearsal["rebuild_proof"]["verified"] is True
    assert rehearsal["rebuild_proof"]["probe_exit_code"] == 0
    assert rehearsal["rebuild_proof"]["direct_url"]["dir_info"] == {
        "editable": False
    }
    assert rehearsal["rebuild_proof"]["source_inventory_sha256"] == (
        rehearsal["rebuild_proof"]["installed_inventory_sha256"]
    )
    assert rehearsal["tracked_git_identity_unchanged"] is True
    assert rehearsal["ignored_paths_changed"] == [".venv/"]
    assert rehearsal["write_scope_respected"] is True
    assert rehearsal["sandbox_preflight"]["write_denied"] is True
    assert rehearsal["sandbox_preflight"]["network_denied"] is True
    assert rehearsal["write_inventory_before"] == []
    symlinks = [
        entry
        for entry in rehearsal["write_inventory_after"]
        if entry["type"] == "symlink"
    ]
    assert [entry["path"] for entry in symlinks] == [
        ".venv/runtime/bin/python",
        ".venv/runtime/bin/python3",
        ".venv/runtime/bin/python3.11",
    ]
    assert {entry["resolved_target"] for entry in symlinks} == {
        rehearsal["managed_python"]["resolved_path"]
    }
    assert rehearsal["state_changed"] is True
    assert verify_closure_package(package)["restore_verified"] is True
    identity = json.loads((package / "identity.json").read_bytes())
    assert identity["rehearsal_input"]["kind"] == "closed_rebuild"
    assert identity["rehearsal_input"]["document"]["schema_version"] == (
        "hqa.repository-closed-rebuild.v2"
    )


def test_verifier_performs_an_independent_fresh_rebuild(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    package = tmp_path / "evidence" / "package"
    capture_and_drill_closure_repository(
        repository,
        package,
        tmp_path / "restore-first",
        tmp_path / "restore-second",
        None,
        rehearsal_patch_sha256=None,
        rehearsal_rebuild=True,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt6-test-operator",
    )

    verification = verify_closure_package(package)

    assert verification["verification_rebuild_verified"] is True
    proof = verification["verification_rebuild_proof"]
    assert proof["verified"] is True
    assert proof["probe_exit_code"] == 0
    assert proof["python_version"] == [3, 11]


def test_rebuild_probe_does_not_execute_wheel_pth_code(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "pth-executed"
    payload = (
        "import pathlib; pathlib.Path("
        f"{str(sentinel)!r}"
        ").write_text('executed')\n"
    ).encode()
    repository = _repository(tmp_path, wheel_pth_payload=payload)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")

    with pytest.raises(
        RepositoryRecoveryError,
        match="unsafe pth member in closed rebuild environment",
    ):
        capture_and_drill_closure_repository(
            repository,
            tmp_path / "evidence" / "package",
            tmp_path / "restore-first",
            tmp_path / "restore-second",
            None,
            rehearsal_patch_sha256=None,
            rehearsal_rebuild=True,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt6-test-operator",
        )
    assert not sentinel.exists()


@pytest.mark.parametrize(
    ("target_kind", "expected_error"),
    [
        ("caller_external", "absolute rehearsal symlink target is not managed"),
        ("absolute_internal", "absolute rehearsal symlink target is not managed"),
        ("relative_escape", "rehearsal symlink escapes managed write root"),
        ("dangling", "dangling rehearsal symlink is forbidden"),
        ("cycle", "rehearsal symlink cycle is forbidden"),
    ],
)
def test_closed_rebuild_verifier_rejects_unmanaged_symlink_graph(
    tmp_path: Path,
    target_kind: str,
    expected_error: str,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    package = tmp_path / "evidence" / "package"
    first = tmp_path / "restore-first"
    capture_and_drill_closure_repository(
        repository,
        package,
        first,
        tmp_path / "restore-second",
        None,
        rehearsal_patch_sha256=None,
        rehearsal_rebuild=True,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt6-test-operator",
    )
    link = first / ".venv" / "runtime" / "bin" / "python3"
    link.unlink()
    if target_kind == "caller_external":
        target = "/bin/sh"
    elif target_kind == "absolute_internal":
        target = str(first / ".venv" / "runtime" / "bin" / "python")
    elif target_kind == "relative_escape":
        target = "../../../../../outside"
    elif target_kind == "dangling":
        target = "missing-python"
    else:
        target = "python3"
    link.symlink_to(target)

    with pytest.raises(RepositoryRecoveryError, match=expected_error):
        verify_closure_package(package)


def test_closure_package_has_exact_section_4_1_files_and_two_restores(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    source_before = repository_identity(repository)
    package = tmp_path / "evidence" / "recovery" / "hqa" / "release"
    first = tmp_path / "restores" / "first"
    second = tmp_path / "restores" / "second"

    result = capture_and_drill_closure_repository(
        repository,
        package,
        first,
        second,
        None,
        rehearsal_patch_sha256=None,
        rehearsal_rebuild=True,
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
    assert (first / "value.txt").read_text(encoding="utf-8") == "unstaged\n"
    assert (first / ".venv" / "runtime" / "bin" / "python").exists()
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
    assert identity["deliberate_exclusions"]["bounds"]["max_paths"] == 100_000
    assert identity["untracked_capture_bounds"] == {
        "max_bytes": 4 * 1024 * 1024 * 1024,
        "max_files": 100_000,
        "observed_bytes": len(b"\x00closure\xff"),
        "observed_files": 1,
    }

    receipt = json.loads((package / "restore-receipt.json").read_bytes())
    assert receipt["same_filesystem_class"] is True
    assert len(set(receipt["filesystem_devices"].values())) == 1
    assert receipt["first_restore"]["restore_verified"] is True
    assert receipt["first_restore"]["comparison_mismatches"] == []
    assert receipt["rehearsal"]["command_exit_code"] == 0
    assert receipt["rehearsal"]["rebuild_proof"]["verified"] is True
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
        RepositoryRecoveryError,
        match="patch rehearsals cannot certify release recovery",
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


def test_closure_capture_rejects_command_spec_digest_substitution(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    command_spec, _command_spec_sha256 = _command_spec(tmp_path)
    package = tmp_path / "evidence" / "package"

    with pytest.raises(
        RepositoryRecoveryError,
        match="caller-authored rehearsal command specs are forbidden",
    ):
        capture_and_drill_closure_repository(
            repository,
            package,
            tmp_path / "restore-first",
            tmp_path / "restore-second",
            None,
            rehearsal_patch_sha256=None,
            rehearsal_command_spec=command_spec,
            rehearsal_command_spec_sha256="0" * 64,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt5-test-operator",
        )

    assert not package.exists()


def test_closure_capture_rejects_open_command_spec(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    command_spec, _command_spec_sha256 = _command_spec(tmp_path)
    document = json.loads(command_spec.read_bytes())
    document["unexpected"] = "not closed"
    command_spec.write_text(
        json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    command_spec_sha256 = hashlib.sha256(command_spec.read_bytes()).hexdigest()
    package = tmp_path / "evidence" / "package"

    with pytest.raises(
        RepositoryRecoveryError,
        match="caller-authored rehearsal command specs are forbidden",
    ):
        capture_and_drill_closure_repository(
            repository,
            package,
            tmp_path / "restore-first",
            tmp_path / "restore-second",
            None,
            rehearsal_patch_sha256=None,
            rehearsal_command_spec=command_spec,
            rehearsal_command_spec_sha256=command_spec_sha256,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt5-test-operator",
        )

    assert not package.exists()


@pytest.mark.parametrize(
    "environment_name",
    ["PYTHONPATH", "PYTHONHOME", "DYLD_LIBRARY_PATH", "OPENAI_API_KEY"],
)
def test_closure_capture_rejects_environment_overlay(
    tmp_path: Path,
    environment_name: str,
) -> None:
    repository = _repository(tmp_path)
    command_spec, _command_spec_sha256 = _command_spec(tmp_path)
    document = json.loads(command_spec.read_bytes())
    document["environment"][environment_name] = "forbidden"
    command_spec.write_text(
        json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    command_spec_sha256 = hashlib.sha256(command_spec.read_bytes()).hexdigest()

    with pytest.raises(
        RepositoryRecoveryError,
        match="caller-authored rehearsal command specs are forbidden",
    ):
        capture_and_drill_closure_repository(
            repository,
            tmp_path / "evidence" / "package",
            tmp_path / "restore-first",
            tmp_path / "restore-second",
            None,
            rehearsal_patch_sha256=None,
            rehearsal_command_spec=command_spec,
            rehearsal_command_spec_sha256=command_spec_sha256,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt5-test-operator",
        )


def test_closure_command_inventory_rejects_symlink(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    command_spec, command_spec_sha256 = _marker_command_spec(
        tmp_path,
        (
            "import pathlib, sys; "
            "root = pathlib.Path(sys.argv[1]) / '.venv'; "
            "root.mkdir(); (root / 'escape').symlink_to('/tmp')"
        ),
        required_path="{repository}/.venv/escape",
    )
    package = tmp_path / "evidence" / "package"

    with pytest.raises(
        RepositoryRecoveryError,
        match="caller-authored rehearsal command specs are forbidden",
    ):
        capture_and_drill_closure_repository(
            repository,
            package,
            tmp_path / "restore-first",
            tmp_path / "restore-second",
            None,
            rehearsal_patch_sha256=None,
            rehearsal_command_spec=command_spec,
            rehearsal_command_spec_sha256=command_spec_sha256,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt5-test-operator",
        )

    assert not package.exists()


@pytest.mark.parametrize("target_kind", ["caller_external", "absolute_internal"])
def test_caller_cannot_allowlist_unmanaged_or_absolute_internal_symlink(
    tmp_path: Path,
    target_kind: str,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    first = tmp_path / "restore-first"
    if target_kind == "caller_external":
        target = "/bin/sh"
        script = (
            "import pathlib, sys; "
            "root = pathlib.Path(sys.argv[1]) / '.venv'; root.mkdir(); "
            f"(root / 'escape').symlink_to({target!r})"
        )
    else:
        target = str(first / ".venv" / "payload")
        script = (
            "import pathlib, sys; "
            "root = pathlib.Path(sys.argv[1]) / '.venv'; root.mkdir(); "
            "(root / 'payload').write_text('not an interpreter'); "
            f"(root / 'escape').symlink_to({target!r})"
        )
    command_spec, _ = _marker_command_spec(
        tmp_path,
        script,
        required_path="{repository}/.venv/escape",
    )
    document = json.loads(command_spec.read_bytes())
    document["allowed_external_symlink_targets"] = [target]
    command_spec.write_text(
        json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    command_spec_sha256 = hashlib.sha256(command_spec.read_bytes()).hexdigest()

    with pytest.raises(
        RepositoryRecoveryError,
        match="caller-authored rehearsal command specs are forbidden",
    ):
        capture_and_drill_closure_repository(
            repository,
            tmp_path / "evidence" / "package",
            first,
            tmp_path / "restore-second",
            None,
            rehearsal_patch_sha256=None,
            rehearsal_command_spec=command_spec,
            rehearsal_command_spec_sha256=command_spec_sha256,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt6-test-operator",
        )


def test_closure_command_sandbox_denies_write_outside_allowed_root(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    command_spec, command_spec_sha256 = _marker_command_spec(
        tmp_path,
        (
            "import pathlib, sys; repository = pathlib.Path(sys.argv[1]); "
            "root = repository / '.venv'; root.mkdir(); "
            "(root / 'rehearsal-marker').write_text('allowed'); "
            "(repository / 'outside-marker').write_text('forbidden')"
        ),
    )
    package = tmp_path / "evidence" / "package"
    first = tmp_path / "restore-first"

    with pytest.raises(
        RepositoryRecoveryError,
        match="caller-authored rehearsal command specs are forbidden",
    ):
        capture_and_drill_closure_repository(
            repository,
            package,
            first,
            tmp_path / "restore-second",
            None,
            rehearsal_patch_sha256=None,
            rehearsal_command_spec=command_spec,
            rehearsal_command_spec_sha256=command_spec_sha256,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt5-test-operator",
        )
    assert not (first / "outside-marker").exists()
    assert not package.exists()


def test_closure_package_verification_rejects_receipt_tamper(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    package = tmp_path / "evidence" / "package"
    capture_and_drill_closure_repository(
        repository,
        package,
        tmp_path / "restore-first",
        tmp_path / "restore-second",
        None,
        rehearsal_patch_sha256=None,
        rehearsal_rebuild=True,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt5-test-operator",
    )

    (package / "restore-receipt.json").write_bytes(b"{}\n")
    with pytest.raises(RepositoryRecoveryError, match="digest mismatch"):
        verify_closure_package(package)


def test_closure_package_verification_rejects_reindexed_semantic_tamper(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    package = tmp_path / "evidence" / "package"
    capture_and_drill_closure_repository(
        repository,
        package,
        tmp_path / "restore-first",
        tmp_path / "restore-second",
        None,
        rehearsal_patch_sha256=None,
        rehearsal_rebuild=True,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt5-test-operator",
    )
    receipt = json.loads((package / "restore-receipt.json").read_bytes())
    receipt["first_restore"]["compared_fields"] = [
        {
            "expected_sha256": "1" * 64,
            "field": "invented",
            "match": True,
            "observed_sha256": "2" * 64,
        }
    ]
    _rewrite_receipt_and_reindex(package, receipt)

    with pytest.raises(
        RepositoryRecoveryError,
        match="closure restore comparison field-set mismatch",
    ):
        verify_closure_package(package)


def test_closure_verifier_rejects_reindexed_write_scope_tamper(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    package = tmp_path / "evidence" / "package"
    capture_and_drill_closure_repository(
        repository,
        package,
        tmp_path / "restore-first",
        tmp_path / "restore-second",
        None,
        rehearsal_patch_sha256=None,
        rehearsal_rebuild=True,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt5-test-operator",
    )
    receipt = json.loads((package / "restore-receipt.json").read_bytes())
    receipt["rehearsal"]["ignored_paths_changed"] = ["outside/"]
    _rewrite_receipt_and_reindex(package, receipt)

    with pytest.raises(
        RepositoryRecoveryError,
        match="closed rebuild write scope mismatch",
    ):
        verify_closure_package(package)


def test_closure_verifier_rejects_reindexed_cache_write_root(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    package = tmp_path / "evidence" / "package"
    capture_and_drill_closure_repository(
        repository,
        package,
        tmp_path / "restore-first",
        tmp_path / "restore-second",
        None,
        rehearsal_patch_sha256=None,
        rehearsal_rebuild=True,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt6-test-operator",
    )
    identity = json.loads((package / "identity.json").read_bytes())
    rebuild_spec = identity["rehearsal_input"]["document"]
    rebuild_spec["cache_path"] = str(package)
    identity["rehearsal_input"]["sha256"] = hashlib.sha256(
        (
            json.dumps(
                rebuild_spec,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
    ).hexdigest()
    _rewrite_json_member_and_reindex(package, "identity.json", identity)
    receipt = json.loads((package / "restore-receipt.json").read_bytes())
    receipt["rehearsal"]["input_sha256"] = identity["rehearsal_input"][
        "sha256"
    ]
    _rewrite_receipt_and_reindex(package, receipt)

    with pytest.raises(
        RepositoryRecoveryError,
        match="closed rebuild cache authority mismatch",
    ):
        verify_closure_package(package)


def test_closure_capture_rejects_restore_nested_in_cache(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    package = tmp_path / "evidence" / "package"

    with pytest.raises(
        RepositoryRecoveryError,
        match="closed rebuild cache authority mismatch",
    ):
        capture_and_drill_closure_repository(
            repository,
            package,
            tmp_path / "restore-first",
            package.parent / "uv-cache" / "second",
            None,
            rehearsal_patch_sha256=None,
            rehearsal_rebuild=True,
            repository_id="hqa",
            publication_url="https://github.com/example/closure.git",
            publication_remote_name="github",
            operator_identity="attempt6-test-operator",
        )
    assert not package.exists()


def test_failed_rehearsal_finalizes_a_truthful_false_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path, build_timeout_child=True)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    monkeypatch.setattr(
        repository_recovery,
        "_CLOSED_REBUILD_COMMAND_TIMEOUT_SECONDS",
        2,
    )
    package = tmp_path / "evidence" / "package"
    first = tmp_path / "restore-first"

    result = capture_and_drill_closure_repository(
        repository,
        package,
        first,
        tmp_path / "restore-second",
        None,
        rehearsal_patch_sha256=None,
        rehearsal_rebuild=True,
        repository_id="hqa",
        publication_url="https://github.com/example/closure.git",
        publication_remote_name="github",
        operator_identity="attempt5-test-operator",
    )

    assert result["restore_verified"] is False
    receipt = json.loads((package / "restore-receipt.json").read_bytes())
    assert receipt["first_restore"]["restore_verified"] is True
    assert receipt["rehearsal"]["command_exit_code"] == 124
    assert receipt["rehearsal"]["command_timed_out"] is True
    assert receipt["rehearsal"]["rebuild_proof"]["verified"] is False
    assert receipt["second_restore"]["restore_verified"] is True
    assert receipt["restore_verified"] is False
    verification = verify_closure_package(package)
    assert verification["verified"] is True
    assert verification["restore_verified"] is False
    child_pid = int(
        (
            first
            / ".venv"
            / "rebuild-project"
            / "timeout-child.pid"
        ).read_text(encoding="utf-8")
    )
    child_terminated = False
    for _ in range(40):
        observed = subprocess.run(
            ["/bin/ps", "-p", str(child_pid), "-o", "stat="],
            check=False,
            capture_output=True,
            text=True,
        )
        if observed.returncode != 0 or observed.stdout.strip().startswith("Z"):
            child_terminated = True
            break
        time.sleep(0.05)
    assert child_terminated is True


def test_timeout_refuses_when_process_group_survives_term(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(
        tmp_path,
        build_timeout_child_ignores_first_term=True,
    )
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
    monkeypatch.setattr(
        repository_recovery,
        "_CLOSED_REBUILD_COMMAND_TIMEOUT_SECONDS",
        2,
    )
    monkeypatch.setattr(
        repository_recovery,
        "_TIMEOUT_TERM_GRACE_SECONDS",
        0.25,
    )
    package = tmp_path / "evidence" / "package"
    first = tmp_path / "restore-first"
    pid_path = (
        first
        / ".venv"
        / "rebuild-project"
        / "timeout-child.pid"
    )
    child_pid: int | None = None
    try:
        with pytest.raises(
            RepositoryRecoveryError,
            match=r"process group survived TERM pgid=\d+ argv_sha256=[0-9a-f]{64}",
        ):
            capture_and_drill_closure_repository(
                repository,
                package,
                first,
                tmp_path / "restore-second",
                None,
                rehearsal_patch_sha256=None,
                rehearsal_rebuild=True,
                repository_id="hqa",
                publication_url="https://github.com/example/closure.git",
                publication_remote_name="github",
                operator_identity="attempt6-test-operator",
            )
    finally:
        for _ in range(40):
            if pid_path.is_file():
                child_pid = int(pid_path.read_text(encoding="utf-8"))
                break
            time.sleep(0.05)
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(40):
                observed = subprocess.run(
                    ["/bin/ps", "-p", str(child_pid), "-o", "stat="],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if (
                    observed.returncode != 0
                    or observed.stdout.strip().startswith("Z")
                ):
                    break
                time.sleep(0.05)
            else:
                pytest.fail("timeout test child survived TERM-only cleanup")
    assert child_pid is not None
    assert not package.exists()


def test_closure_cli_rejects_patch_bypass(
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

    with pytest.raises(SystemExit) as exc_info:
        repository_recovery_cli.main()
    assert exc_info.value.code == 2
    assert "--rehearsal-rebuild" in capsys.readouterr().err
    assert not package.exists()


def test_closure_cli_runs_implementation_owned_closed_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = _repository(tmp_path)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "ignore environment")
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
            "--rehearsal-rebuild",
        ],
    )

    assert repository_recovery_cli.main() == 0
    assert json.loads(capsys.readouterr().out)["restore_verified"] is True
