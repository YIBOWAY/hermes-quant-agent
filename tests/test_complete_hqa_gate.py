from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "scripts" / "complete_hqa_gate.py"
WRAPPER = ROOT / "scripts" / "verify_agent_v02_complete_hqa.sh"


def _load_helper():
    spec = importlib.util.spec_from_file_location("complete_hqa_gate_test", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_population_validation_requires_exact_skip_nodes_and_reasons() -> None:
    gate = _load_helper()
    expected = {
        "tests/test_aihot.py::test_fetch_items_live_smoke": (
            "network; flip to run a live smoke test manually"
        ),
        "tests/test_quant_cli.py::test_run_doctor_integration_real": (
            "manual — requires working quant-system environment; "
            "run with --no-skip to verify live"
        ),
    }
    population = {
        "schema_version": "hqa.complete-hqa-population.v1",
        "collected_node_ids": [
            "tests/test_aihot.py::test_fetch_items_live_smoke",
            "tests/test_example.py::test_passes",
            "tests/test_quant_cli.py::test_run_doctor_integration_real",
        ],
        "deselected_node_ids": [],
        "outcomes": [
            {
                "node_id": "tests/test_aihot.py::test_fetch_items_live_smoke",
                "outcome": "skipped",
                "reason": expected[
                    "tests/test_aihot.py::test_fetch_items_live_smoke"
                ],
            },
            {
                "node_id": "tests/test_example.py::test_passes",
                "outcome": "passed",
                "reason": None,
            },
            {
                "node_id": (
                    "tests/test_quant_cli.py::test_run_doctor_integration_real"
                ),
                "outcome": "skipped",
                "reason": expected[
                    "tests/test_quant_cli.py::test_run_doctor_integration_real"
                ],
            },
        ],
    }

    result = gate.validate_population(
        population,
        expected_skips=expected,
        minimum_passed=1,
    )

    assert result == {
        "collected": 3,
        "errors": 0,
        "failed": 0,
        "node_ids": population["collected_node_ids"],
        "passed": 1,
        "skipped": 2,
        "skips": [
            {
                "node_id": node_id,
                "reason": expected[node_id],
            }
            for node_id in sorted(expected)
        ],
        "xfailed": 0,
        "xpassed": 0,
    }

    substituted = {
        **population,
        "outcomes": [
            *population["outcomes"][:-1],
            {
                "node_id": (
                    "tests/test_quant_cli.py::test_run_doctor_integration_real"
                ),
                "outcome": "skipped",
                "reason": "different reason",
            },
        ],
    }
    with pytest.raises(gate.GateError, match="skip_set_not_declared"):
        gate.validate_population(
            substituted,
            expected_skips=expected,
            minimum_passed=1,
        )


def test_junit_validation_matches_population_and_skip_reasons() -> None:
    gate = _load_helper()
    first_reason = "network; flip to run a live smoke test manually"
    second_reason = (
        "manual — requires working quant-system environment; "
        "run with --no-skip to verify live"
    )
    junit = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="0" failures="0" skipped="2" tests="3">'
        '<testcase classname="tests.test_aihot" '
        'name="test_fetch_items_live_smoke">'
        '<properties><property name="hqa_node_id" '
        'value="tests/test_aihot.py::test_fetch_items_live_smoke"/>'
        "</properties>"
        f'<skipped type="pytest.skip" message="{first_reason}"/>'
        "</testcase>"
        '<testcase classname="tests.test_example" name="test_passes">'
        '<properties><property name="hqa_node_id" '
        'value="tests/test_example.py::test_passes"/></properties>'
        "</testcase>"
        '<testcase classname="tests.test_quant_cli" '
        'name="test_run_doctor_integration_real">'
        '<properties><property name="hqa_node_id" '
        'value="tests/test_quant_cli.py::test_run_doctor_integration_real"/>'
        "</properties>"
        f'<skipped type="pytest.skip" message="{second_reason}"/>'
        "</testcase>"
        "</testsuite>"
        "</testsuites>"
    ).encode()
    population_result = {
        "collected": 3,
        "errors": 0,
        "failed": 0,
        "node_ids": [
            "tests/test_aihot.py::test_fetch_items_live_smoke",
            "tests/test_example.py::test_passes",
            "tests/test_quant_cli.py::test_run_doctor_integration_real",
        ],
        "passed": 1,
        "skipped": 2,
        "xfailed": 0,
        "xpassed": 0,
    }

    assert gate.validate_junit(
        junit,
        pytest_exit=0,
        population_result=population_result,
        expected_skip_reasons=(first_reason, second_reason),
    ) == {
        "errors": 0,
        "failed": 0,
        "passed": 1,
        "skipped": 2,
        "tests": 3,
        "xfail": 0,
    }

    substituted = junit.replace(first_reason.encode(), b"different reason")
    with pytest.raises(gate.GateError, match="junit_skip_reasons_invalid"):
        gate.validate_junit(
            substituted,
            pytest_exit=0,
            population_result=population_result,
            expected_skip_reasons=(first_reason, second_reason),
        )

    substituted_node = junit.replace(
        b"tests/test_example.py::test_passes",
        b"tests/test_other.py::test_passes",
    )
    with pytest.raises(gate.GateError, match="junit_node_ids_invalid"):
        gate.validate_junit(
            substituted_node,
            pytest_exit=0,
            population_result=population_result,
            expected_skip_reasons=(first_reason, second_reason),
        )


def test_generated_pytest_driver_records_exact_node_outcomes(
    tmp_path: Path,
) -> None:
    gate = _load_helper()
    suite = tmp_path / "test_sample.py"
    suite.write_text(
        "import pytest\n"
        "def test_passes():\n"
        "    assert True\n"
        "@pytest.mark.skip(reason='declared test skip')\n"
        "def test_skips():\n"
        "    raise AssertionError('must not run')\n",
        encoding="utf-8",
    )
    driver = tmp_path / "pytest_driver.py"
    population = tmp_path / "population.json"
    junit = tmp_path / "junit.xml"
    gate.write_pytest_driver(driver, population)

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(driver),
            "-q",
            "-p",
            "no:cacheprovider",
            suite.name,
            "--junitxml",
            str(junit),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    document = json.loads(population.read_text(encoding="utf-8"))
    result = gate.validate_population(
        document,
        expected_skips={
            "test_sample.py::test_skips": "declared test skip",
        },
        minimum_passed=1,
    )
    assert result["node_ids"] == [
        "test_sample.py::test_passes",
        "test_sample.py::test_skips",
    ]
    assert gate.validate_junit(
        junit.read_bytes(),
        pytest_exit=completed.returncode,
        population_result=result,
        expected_skip_reasons=("declared test skip",),
    )["tests"] == 2
    assert population.stat().st_mode & 0o777 == 0o600


def test_repository_identity_binds_full_tests_tree_and_hidden_index(
    tmp_path: Path,
) -> None:
    gate = _load_helper()
    repo = tmp_path / "release"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "codex/agent-v0-2-release")
    _git(repo, "config", "user.name", "Gate Test")
    _git(repo, "config", "user.email", "gate@example.invalid")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_one.py").write_text(
        "def test_one():\n    assert True\n",
        encoding="utf-8",
    )
    (tests / "fixture.json").write_text('{"bound":true}\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "fixture")
    head = _git(repo, "rev-parse", "HEAD").strip()

    repository = gate.capture_repository_identity(
        repo,
        expected_commit=head,
        expected_branch="codex/agent-v0-2-release",
    )
    test_tree = gate.capture_tests_identity(repo, head)

    assert repository["clean"] is True
    assert repository["head"] == head
    assert [item["path"] for item in test_tree["files"]] == [
        "tests/fixture.json",
        "tests/test_one.py",
    ]
    assert test_tree["file_count"] == 2
    assert test_tree["python_test_file_count"] == 1

    _git(repo, "update-index", "--assume-unchanged", "tests/test_one.py")
    with pytest.raises(gate.GateError, match="hidden_index_state"):
        gate.capture_repository_identity(
            repo,
            expected_commit=head,
            expected_branch="codex/agent-v0-2-release",
        )


def test_environment_probes_bind_hqa_and_hermes_direct_urls(
    tmp_path: Path,
) -> None:
    gate = _load_helper()
    release = tmp_path / "hqa-release"
    hqa_environment = release / ".venv" / "final"
    hqa_python = hqa_environment / "bin" / "python"
    hqa_module = (
        hqa_environment
        / "lib"
        / "python3.11"
        / "site-packages"
        / "hqa"
        / "__init__.py"
    )
    hqa_python.parent.mkdir(parents=True)
    hqa_python.write_text("python", encoding="utf-8")
    hqa_module.parent.mkdir(parents=True)
    hqa_module.write_text("", encoding="utf-8")
    hqa_files = [
        {
            "bytes": 0,
            "path": "hqa/__init__.py",
            "sha256": gate._sha256(b""),
        }
    ]
    hqa_probe = {
        "dependency_inventory": [
            {"name": "hermes-quant-agent", "version": "0.2.2"},
            {"name": "pytest", "version": "8.4.2"},
        ],
        "direct_url": {
            "dir_info": {"editable": False},
            "url": release.resolve().as_uri(),
        },
        "distribution_name": "hermes-quant-agent",
        "distribution_root": str(hqa_module.parents[1]),
        "distribution_version": "0.2.2",
        "installed_files": hqa_files,
        "module_file": str(hqa_module),
        "pth_files": [{"lines": ["import _virtualenv"], "name": "_virtualenv.pth"}],
        "pytest_version": "8.4.2",
        "python": [3, 11, 15],
        "schema_version": "hqa.complete-hqa-environment-probe.v1",
        "sys_executable": str(hqa_python),
        "sys_prefix": str(hqa_environment),
    }

    assert gate.validate_hqa_environment_probe(
        hqa_probe,
        repository_root=release,
        python_path=hqa_python,
        expected_installed_files=hqa_files,
    )["direct_url"]["dir_info"]["editable"] is False

    live = tmp_path / "owned-hermes"
    integration = live / ".claude" / "worktrees" / "v2-integration"
    hermes_python = live / "venv" / "bin" / "python"
    hermes_module = integration / "hermes_cli" / "__init__.py"
    hermes_python.parent.mkdir(parents=True)
    hermes_python.write_text("python", encoding="utf-8")
    hermes_module.parent.mkdir(parents=True)
    hermes_module.write_text("", encoding="utf-8")
    hermes_distribution = (
        live / "venv" / "lib" / "python3.11" / "site-packages"
    )
    hermes_distribution.mkdir(parents=True)
    hermes_probe = {
        "dependency_inventory": [
            {"name": "hermes-agent", "version": "0.19.0"},
        ],
        "direct_url": {
            "dir_info": {"editable": True},
            "url": integration.resolve().as_uri(),
        },
        "distribution_name": "hermes-agent",
        "distribution_root": str(hermes_distribution),
        "distribution_version": "0.19.0",
        "module_file": str(hermes_module),
        "python": [3, 11, 15],
        "schema_version": "hqa.complete-hqa-hermes-probe.v1",
        "sys_executable": str(hermes_python),
        "sys_prefix": str(live / "venv"),
    }

    assert gate.validate_hermes_environment_probe(
        hermes_probe,
        live_root=live,
        integration_root=integration,
        python_path=hermes_python,
    )["direct_url"]["dir_info"]["editable"] is True

    substituted = {
        **hermes_probe,
        "direct_url": {
            "dir_info": {"editable": True},
            "url": (tmp_path / "different-hermes").resolve().as_uri(),
        },
    }
    with pytest.raises(gate.GateError, match="hermes_direct_url_invalid"):
        gate.validate_hermes_environment_probe(
            substituted,
            live_root=live,
            integration_root=integration,
            python_path=hermes_python,
        )


def test_public_wrapper_exposes_closed_complete_hqa_contract() -> None:
    described = subprocess.run(
        [str(WRAPPER), "--describe"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert described.returncode == 0, described.stderr
    contract = json.loads(described.stdout)
    assert contract["expected_skip_nodes"] == {
        "tests/test_aihot.py::test_fetch_items_live_smoke": (
            "network; flip to run a live smoke test manually"
        ),
        "tests/test_quant_cli.py::test_run_doctor_integration_real": (
            "manual — requires working quant-system environment; "
            "run with --no-skip to verify live"
        ),
    }
    assert contract["junit_required"] is True
    assert contract["minimum_passed"] == 2012
    assert contract["selector"] == "tests"
    assert contract["unexpected_skip_or_xfail_fails"] is True

    self_test = subprocess.run(
        [str(WRAPPER), "--self-test"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert self_test.returncode == 0, self_test.stderr
    assert json.loads(self_test.stdout) == {
        "schema_version": "hqa.complete-hqa-self-test.v1",
        "status": "pass",
    }

    forbidden = subprocess.run(
        [str(WRAPPER), "--repository-root", str(ROOT), "--describe"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert forbidden.returncode == 78
    assert "complete_hqa_error=public_argument_forbidden" in forbidden.stderr

    source = WRAPPER.read_text(encoding="utf-8")
    assert "|| true" not in source
    assert "/api/health" not in source
    assert "--deselect" not in source
    assert "--ignore" not in source
    assert "--update-snapshots" not in source


def test_run_arguments_are_exact_once_and_output_is_private(
    tmp_path: Path,
) -> None:
    gate = _load_helper()
    release = tmp_path / "release"
    release.mkdir()
    python = release / "python"
    python.write_text("python", encoding="utf-8")
    live = tmp_path / "hermes"
    integration = live / ".claude" / "worktrees" / "v2-integration"
    hermes_python = live / "venv" / "bin" / "python"
    integration.mkdir(parents=True)
    hermes_python.parent.mkdir(parents=True)
    hermes_python.write_text("python", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    output = evidence / "gate01"
    commit = "a" * 40
    arguments = [
        "--python",
        str(python),
        "--output-dir",
        str(output),
        "--expected-commit",
        commit,
        "--hermes-live",
        str(live),
        "--integration-worktree",
        str(integration),
        "--hermes-python",
        str(hermes_python),
    ]

    parsed = gate.parse_run_arguments(arguments)

    assert parsed["expected_commit"] == commit
    assert parsed["output_dir"] == output
    prepared = gate.prepare_output_directory(
        parsed["output_dir"],
        repository_root=release,
    )
    assert prepared == output
    assert output.stat().st_mode & 0o777 == 0o700

    with pytest.raises(gate.GateError, match="public_run_flags_invalid"):
        gate.parse_run_arguments([*arguments, "--python", str(python)])
    with pytest.raises(gate.GateError, match="output_dir_not_new"):
        gate.prepare_output_directory(output, repository_root=release)


def test_committed_authority_and_hqa_source_manifests_bind_live_bytes(
    tmp_path: Path,
) -> None:
    gate = _load_helper()
    repo = tmp_path / "release"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "codex/agent-v0-2-release")
    _git(repo, "config", "user.name", "Gate Test")
    _git(repo, "config", "user.email", "gate@example.invalid")
    (repo / "hqa").mkdir()
    (repo / "hqa" / "__init__.py").write_text(
        '__version__ = "0.2.2"\n',
        encoding="utf-8",
    )
    (repo / "scripts").mkdir()
    helper = repo / "scripts" / "complete_hqa_gate.py"
    wrapper = repo / "scripts" / "verify_agent_v02_complete_hqa.sh"
    helper.write_text("HELPER = True\n", encoding="utf-8")
    wrapper.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "fixture")
    head = _git(repo, "rev-parse", "HEAD").strip()

    authority = gate.capture_authority_identity(repo, head)
    source = gate.capture_hqa_source_identity(repo, head)

    assert [item["path"] for item in authority["files"]] == [
        "scripts/complete_hqa_gate.py",
        "scripts/verify_agent_v02_complete_hqa.sh",
    ]
    assert source["installed_files"] == [
        {
            "bytes": len('__version__ = "0.2.2"\n'.encode()),
            "path": "hqa/__init__.py",
            "sha256": gate._sha256(b'__version__ = "0.2.2"\n'),
        }
    ]

    helper.write_text("HELPER = False\n", encoding="utf-8")
    with pytest.raises(gate.GateError, match="committed_live_bytes_differ"):
        gate.capture_authority_identity(repo, head)


def test_pytest_argv_is_full_tree_and_json_artifacts_are_canonical(
    tmp_path: Path,
) -> None:
    gate = _load_helper()
    python = tmp_path / "python"
    driver = tmp_path / "driver.py"
    junit = tmp_path / "junit.xml"
    basetemp = tmp_path / "basetemp"

    assert gate.build_pytest_argv(
        python=python,
        driver=driver,
        junit=junit,
        basetemp=basetemp,
    ) == [
        str(python),
        "-X",
        "int_max_str_digits=0",
        "-I",
        "-B",
        str(driver),
        "-q",
        "-rs",
        "--import-mode=importlib",
        "-p",
        "no:cacheprovider",
        "tests",
        "--junitxml",
        str(junit),
        "--basetemp",
        str(basetemp),
    ]

    canonical = b'{"a":1,"b":2}'
    assert gate.load_canonical_json(canonical, field="fixture") == {
        "a": 1,
        "b": 2,
    }
    with pytest.raises(gate.GateError, match="fixture_not_canonical"):
        gate.load_canonical_json(b'{"b":2, "a":1}', field="fixture")
    with pytest.raises(gate.GateError, match="fixture_duplicate_key"):
        gate.load_canonical_json(b'{"a":1,"a":2}', field="fixture")
