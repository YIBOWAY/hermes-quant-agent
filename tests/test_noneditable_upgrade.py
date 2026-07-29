from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from hqa.noneditable_upgrade import (
    NoneditableUpgradeError,
    ReleaseAuthority,
    build_baseline_compatibility_wheel,
    observe_release_identity,
    validate_noneditable_probe,
    verify_noneditable_upgrade,
)


ROOT = Path(__file__).resolve().parent.parent
PUBLISHED_BASELINE = "a5589ba0626e76bc99b55bd1a126d578196c51f4"


def _extract_commit(commit: str, destination: Path) -> None:
    archive = subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), "archive", "--format=tar", commit],
        check=True,
        capture_output=True,
    ).stdout
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(destination, filter="data")


def test_published_baseline_without_project_metadata_builds_noneditable_wheel(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    _extract_commit(PUBLISHED_BASELINE, baseline)
    destination = tmp_path / "dist"

    result = build_baseline_compatibility_wheel(
        baseline,
        destination,
        baseline_commit=PUBLISHED_BASELINE,
    )

    wheel = Path(result["path"])
    assert result["baseline_project_metadata_present"] is False
    assert result["baseline_lock_present"] is False
    assert result["compatibility_metadata_generated"] is True
    assert result["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert result["version"] == "0+baseline.a5589ba0626e"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "hqa/__init__.py" in names
        assert not any(name.endswith((".pth", "direct_url.json")) for name in names)
        metadata = archive.read(
            "hermes_quant_agent-0+baseline.a5589ba0626e.dist-info/METADATA"
        ).decode("utf-8")
        assert "Name: hermes-quant-agent\n" in metadata
        assert "Version: 0+baseline.a5589ba0626e\n" in metadata
        record_name = (
            "hermes_quant_agent-0+baseline.a5589ba0626e.dist-info/RECORD"
        )
        record = list(
            csv.reader(
                archive.read(record_name).decode("utf-8").splitlines()
            )
        )
        assert [row[0] for row in record] == names
        assert record[-1] == [record_name, "", ""]


def test_import_probe_rejects_source_pth_editable_and_symlink_identity(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "environment"
    site_packages = environment / "lib/python3.11/site-packages"
    module = site_packages / "hqa/__init__.py"
    distribution = site_packages / "hermes_quant_agent-0.2.2.dist-info"
    python = environment / "bin/python"
    wheel = tmp_path / "hermes_quant_agent-0.2.2-py3-none-any.whl"
    for path in (module, distribution / "METADATA", python):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture\n")
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("hqa/__init__.py", b"fixture\n")
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
    installed_inventory = [
        {
            "bytes": len(b"fixture\n"),
            "path": "__init__.py",
            "sha256": hashlib.sha256(b"fixture\n").hexdigest(),
        }
    ]
    installed_tree_sha256 = hashlib.sha256(
        json.dumps(
            installed_inventory,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    source = tmp_path / "source"
    source.mkdir()
    document = {
        "direct_url": {
            "archive_info": {"hash": f"sha256={wheel_sha256}"},
            "url": wheel.resolve().as_uri(),
        },
        "distribution": str(distribution.resolve()),
        "installed_file_count": 1,
        "installed_tree_sha256": installed_tree_sha256,
        "module": str(module.resolve()),
        "pth": [],
        "pythonpath": None,
        "site_packages": str(site_packages.resolve()),
        "symlink_components": [],
        "sys_executable": str(python.resolve()),
        "sys_path": [str(site_packages.resolve())],
        "version": "0.2.2",
    }

    accepted = validate_noneditable_probe(
        document,
        environment_root=environment,
        expected_version="0.2.2",
        expected_wheel=wheel,
        forbidden_source_roots=(source,),
    )
    assert accepted == {
        "editable": False,
        "isolated": True,
        "source_root_import": False,
        "source_root_pth": False,
        "symlink_free": True,
        "wheel_bound": True,
    }

    mutations = (
        {"pth": [{"path": str(site_packages / "leak.pth"), "text": str(source)}]},
        {"direct_url": {"dir_info": {"editable": True}, "url": source.as_uri()}},
        {"symlink_components": [str(environment / "bin/python")]},
        {"sys_path": [str(site_packages), str(source)]},
        {"pythonpath": str(source)},
    )
    for mutation in mutations:
        with pytest.raises(NoneditableUpgradeError):
            validate_noneditable_probe(
                {**document, **mutation},
                environment_root=environment,
                expected_version="0.2.2",
                expected_wheel=wheel,
                forbidden_source_roots=(source,),
            )


def _release_repository(tmp_path: Path) -> tuple[Path, ReleaseAuthority]:
    repository = tmp_path / "repository"
    repository.mkdir()
    commands = (
        ("/usr/bin/git", "init", "-q", "-b", "codex/agent-v0-2-release"),
        ("/usr/bin/git", "config", "user.email", "upgrade@example.invalid"),
        ("/usr/bin/git", "config", "user.name", "Upgrade Test"),
    )
    for command in commands:
        subprocess.run(command, cwd=repository, check=True)
    (repository / "value.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(
        ["/usr/bin/git", "add", "value.txt"], cwd=repository, check=True
    )
    subprocess.run(
        ["/usr/bin/git", "commit", "-qm", "baseline"],
        cwd=repository,
        check=True,
    )
    baseline = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repository / "value.txt").write_text("final\n", encoding="utf-8")
    subprocess.run(
        ["/usr/bin/git", "commit", "-qam", "final"],
        cwd=repository,
        check=True,
    )
    publication_url = "https://github.com/example/hqa-release-fixture.git"
    subprocess.run(
        ["/usr/bin/git", "remote", "add", "github", publication_url],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        [
            "/usr/bin/git",
            "update-ref",
            "refs/remotes/github/codex/agent-v0-2-release",
            "HEAD",
        ],
        cwd=repository,
        check=True,
    )
    return repository, ReleaseAuthority(
        absolute_checkout_path=repository.resolve(),
        branch="codex/agent-v0-2-release",
        publication_remote_name="github",
        publication_url=publication_url,
        published_baseline=baseline,
    )


def test_release_identity_is_exact_clean_published_and_descends_from_baseline(
    tmp_path: Path,
) -> None:
    repository, authority = _release_repository(tmp_path)

    identity = observe_release_identity(repository, authority)

    assert identity["absolute_checkout_path"] == str(repository.resolve())
    assert identity["branch"] == authority.branch
    assert identity["publication_url"] == authority.publication_url
    assert identity["published_baseline"] == authority.published_baseline
    assert identity["base_is_ancestor"] is True
    assert identity["remote_published"] is True
    assert identity["working_tree_clean"] is True
    assert identity["hidden_index_paths"] == []
    assert len(identity["commit"]) == len(identity["tree"]) == 40

    with pytest.raises(NoneditableUpgradeError, match="canonical checkout"):
        observe_release_identity(
            repository,
            replace(
                authority,
                absolute_checkout_path=tmp_path / "other",
            ),
        )
    with pytest.raises(NoneditableUpgradeError, match="publication URL"):
        observe_release_identity(
            repository,
            replace(authority, publication_url="https://example.invalid/wrong.git"),
        )
    (repository / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(NoneditableUpgradeError, match="clean"):
        observe_release_identity(repository, authority)


def _upgrade_repository(tmp_path: Path) -> tuple[Path, ReleaseAuthority]:
    repository = tmp_path / "upgrade-repository"
    repository.mkdir()
    for command in (
        ("/usr/bin/git", "init", "-q", "-b", "codex/agent-v0-2-release"),
        ("/usr/bin/git", "config", "user.email", "upgrade@example.invalid"),
        ("/usr/bin/git", "config", "user.name", "Upgrade Test"),
    ):
        subprocess.run(command, cwd=repository, check=True)
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (repository / "README.md").write_text("upgrade fixture\n", encoding="utf-8")
    (repository / "hqa").mkdir()
    (repository / "hqa/__init__.py").write_text(
        'VALUE = "baseline"\n', encoding="utf-8"
    )
    (repository / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n",
        encoding="utf-8",
    )
    subprocess.run(["/usr/bin/git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["/usr/bin/git", "commit", "-qm", "published baseline"],
        cwd=repository,
        check=True,
    )
    baseline = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    (repository / "hqa/__init__.py").write_text(
        'VALUE = "final"\n', encoding="utf-8"
    )
    (repository / "hqa/noneditable_upgrade_cli.py").write_text(
        "from __future__ import annotations\n"
        "import argparse\n"
        "def main() -> int:\n"
        "    parser = argparse.ArgumentParser(prog='hqa-upgrade-fixture')\n"
        "    parser.parse_args()\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    (repository / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools>=68", "wheel"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "\n"
        "[project]\n"
        'name = "hermes-quant-agent"\n'
        'version = "0.2.2"\n'
        'readme = "README.md"\n'
        'requires-python = ">=3.11"\n'
        "dependencies = []\n"
        "\n"
        "[project.optional-dependencies]\n"
        "dev = []\n"
        "\n"
        "[tool.setuptools.packages.find]\n"
        'where = ["."]\n'
        'include = ["hqa*"]\n'
        "namespaces = false\n",
        encoding="utf-8",
    )
    (repository / "uv.lock").write_text(
        "version = 1\n"
        "revision = 3\n"
        'requires-python = ">=3.11"\n'
        "\n"
        "[[package]]\n"
        'name = "hermes-quant-agent"\n'
        'version = "0.2.2"\n'
        'source = { editable = "." }\n'
        "\n"
        "[package.optional-dependencies]\n"
        "dev = []\n"
        "\n"
        "[package.metadata]\n"
        'provides-extras = ["dev"]\n',
        encoding="utf-8",
    )
    subprocess.run(["/usr/bin/git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["/usr/bin/git", "commit", "-qm", "final package"],
        cwd=repository,
        check=True,
    )
    publication_url = "https://github.com/example/hqa-upgrade-fixture.git"
    subprocess.run(
        ["/usr/bin/git", "remote", "add", "github", publication_url],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        [
            "/usr/bin/git",
            "update-ref",
            "refs/remotes/github/codex/agent-v0-2-release",
            "HEAD",
        ],
        cwd=repository,
        check=True,
    )
    return repository, ReleaseAuthority(
        absolute_checkout_path=repository.resolve(),
        branch="codex/agent-v0-2-release",
        publication_remote_name="github",
        publication_url=publication_url,
        published_baseline=baseline,
    )


def test_upgrade_rehearsal_is_offline_private_noneditable_and_fresh_equivalent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, authority = _upgrade_repository(tmp_path)
    output = tmp_path / "private-output"
    python = Path(
        "/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/"
        "agent-v02-work/ai-quant-platform/.venv/bin/python"
    ).resolve()
    uv = Path("/opt/homebrew/bin/uv")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "hostile-source"))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("QS_BROKER_PASSWORD", "must-not-reach-child")

    result = verify_noneditable_upgrade(
        repository_root=repository,
        output_dir=output,
        authority=authority,
        python_binary=python,
        uv_binary=uv,
    )

    assert result["status"] == "passed"
    assert result["repository_identity_stable"] is True
    assert result["published_baseline"] == authority.published_baseline
    assert result["baseline_wheel"]["compatibility_metadata_generated"] is True
    assert result["baseline_import_validation"]["wheel_bound"] is True
    assert result["upgraded_final_import"]["version"] == "0.2.2"
    assert result["fresh_final_import"]["version"] == "0.2.2"
    assert result["final_environment_equivalent"] is True
    assert result["final_cli_equivalent"] is True
    assert result["final_lock_consumed_in_same_environment"] is True
    assert result["offline"] is True
    assert result["network_denied"] is True
    assert result["provider_or_trading_credentials_inherited"] is False
    assert result["noneditable"] is True
    assert result["isolated_import"] is True
    assert result["safety"] == {
        "database_auto_migrate": False,
        "global_kill_switch": True,
        "live_trading_enabled": False,
        "provider_access": "disabled",
    }
    isolation = result["process_isolation"]
    assert "PYTHONPATH" not in isolation["environment_variable_names"]
    assert set(isolation["credential_like_names_removed"]) >= {
        "OPENAI_API_KEY",
        "QS_BROKER_PASSWORD",
    }
    sync_argv = result["final_dependency_sync_in_upgrade_environment"]["argv"]
    assert sync_argv[:3] == [
        "/usr/bin/sandbox-exec",
        "-p",
        "(version 1) (allow default) (deny network*)",
    ]
    assert "--frozen" in sync_argv
    assert "--offline" in sync_argv
    assert "--no-editable" in sync_argv
    assert "--no-install-project" in sync_argv
    assert (output.stat().st_mode & 0o777) == 0o700
    receipt = output / "noneditable-upgrade-receipt.json"
    assert (receipt.stat().st_mode & 0o777) == 0o600
    receipt_bytes = receipt.read_bytes()
    assert not receipt_bytes.endswith(b"\n")
    assert result == json.loads(receipt_bytes)
    for evidence in [receipt, *sorted(output.glob("*.log"))]:
        payload = evidence.read_bytes()
        assert not payload.endswith(b"\n")
        assert payload == json.dumps(
            json.loads(payload),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    assert repository.joinpath("value.txt").exists() is False


def test_published_wrapper_is_commit_bound_isolated_and_has_no_effect_probe() -> None:
    from hqa.noneditable_upgrade_cli import build_parser

    wrapper = ROOT / "scripts/verify_agent_v02_noneditable_upgrade.sh"
    source = wrapper.read_text(encoding="utf-8")

    assert wrapper.stat().st_mode & 0o111
    assert "set -euo pipefail" in source
    assert '"-I" "-S" "-B"' in source
    assert "sandbox-exec" in source
    assert "git archive" not in source
    assert '"archive"' in source
    assert "hqa/noneditable_upgrade.py" in source
    assert "hqa/noneditable_upgrade_cli.py" in source
    assert "runpy.run_module" in source
    assert "PYTHONPATH" not in source
    assert "|| true" not in source
    assert "/api/health" not in source
    assert "curl " not in source
    parser = build_parser()
    output = parser.parse_args(["--output-dir", "/private/tmp/hqa-upgrade"])
    assert output.output_dir == "/private/tmp/hqa-upgrade"
