from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_agent_v02_focused_safety.sh"
SELECTORS = (
    "tests/test_gate.py",
    "tests/test_gate_cli.py",
    "tests/test_hermes_run_acceptance.py",
    "tests/test_hermes_run_acceptance_live.py",
    "tests/test_hermes_run_adapter.py",
    "tests/test_hermes_run_cli.py",
    "tests/test_intent_workflow.py",
    "tests/test_paper_gate_cli.py",
    "tests/test_release_evidence.py",
    "tests/test_release_manifest.py",
    "tests/test_release_process_boundaries.py",
    "tests/test_research_workflow_saga.py",
    "tests/test_workflow_authority.py",
    "tests/test_workflow_contract.py",
)


def _run_git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("/usr/bin/git", "-C", str(repository), *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hermes_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    hermes_live = tmp_path / "owned-hermes"
    integration = (
        hermes_live / ".claude" / "worktrees" / "v2-integration"
    )
    gateway = integration / "gateway" / "run.py"
    gateway.parent.mkdir(parents=True)
    gateway.write_text("# isolated gateway fixture\n", encoding="utf-8")
    subprocess.run(
        (
            "/usr/bin/git",
            "init",
            "-q",
            "-b",
            "codex/agent-v0-2-release",
            str(integration),
        ),
        check=True,
        capture_output=True,
    )
    _run_git(integration, "config", "user.name", "Focused Safety Test")
    _run_git(
        integration,
        "config",
        "user.email",
        "focused-safety@example.invalid",
    )
    _run_git(
        integration,
        "remote",
        "add",
        "origin",
        "https://github.com/NousResearch/hermes-agent.git",
    )
    _run_git(integration, "add", "gateway/run.py")
    _run_git(integration, "commit", "-q", "-m", "fixture")

    owned_python = tmp_path / "owned-python" / "python3.11"
    owned_python.parent.mkdir()
    owned_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    owned_python.chmod(0o700)
    hermes_python = hermes_live / "venv" / "bin" / "python"
    hermes_python.parent.mkdir(parents=True)
    hermes_python.symlink_to(owned_python)
    return hermes_live, integration, hermes_python


def _release_fixture(
    tmp_path: Path,
    *,
    capture_environment: bool = False,
) -> tuple[Path, Path, Path]:
    assert SCRIPT.is_file(), "focused-safety wrapper is absent"
    _hermes_fixture(tmp_path)
    release = tmp_path / "release"
    scripts = release / "scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / SCRIPT.name
    shutil.copy2(SCRIPT, wrapper)
    wrapper.chmod(0o755)
    for selector in SELECTORS:
        target = release / selector
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# selector fixture\n", encoding="utf-8")

    capture = tmp_path / "capture.txt"
    python = release / ".venv" / "focused" / "bin" / "python"
    python.parent.mkdir(parents=True)
    environment_capture = (
        '  printf "ENV_PYTEST_ADDOPTS=%s\\n" "${PYTEST_ADDOPTS-unset}"\n'
        '  printf "ENV_PYTEST_PLUGINS=%s\\n" "${PYTEST_PLUGINS-unset}"\n'
        '  printf "ENV_PYTHONHOME=%s\\n" "${PYTHONHOME-unset}"\n'
        '  printf "ENV_PYTHONPATH=%s\\n" "${PYTHONPATH-unset}"\n'
        '  printf "ENV_PYTHONWARNINGS=%s\\n" "${PYTHONWARNINGS-unset}"\n'
        '  printf "ENV_OPENAI_API_KEY=%s\\n" "${OPENAI_API_KEY-unset}"\n'
        '  printf "ENV_FUTU_HOST=%s\\n" "${FUTU_HOST-unset}"\n'
        '  printf "ENV_QS_LLM_PROVIDER=%s\\n" "${QS_LLM_PROVIDER-unset}"\n'
        '  printf "ENV_UNRELATED_INJECTION=%s\\n" "${UNRELATED_INJECTION-unset}"\n'
        '  printf "ENV_HOME=%s\\n" "${HOME-unset}"\n'
        '  printf "ENV_TEMP=%s\\n" "${TEMP-unset}"\n'
        '  printf "ENV_TMP=%s\\n" "${TMP-unset}"\n'
        '  printf "ENV_TMPDIR=%s\\n" "${TMPDIR-unset}"\n'
        '  printf "ENV_PYTEST_DISABLE_PLUGIN_AUTOLOAD=%s\\n" '
        '"${PYTEST_DISABLE_PLUGIN_AUTOLOAD-unset}"\n'
        '  printf "ENV_PYTHONNOUSERSITE=%s\\n" "${PYTHONNOUSERSITE-unset}"\n'
        '  printf "ENV_PYTHONPYCACHEPREFIX=%s\\n" '
        '"${PYTHONPYCACHEPREFIX-unset}"\n'
        '  printf "ENV_HQA_PROVIDER_ACCESS=%s\\n" '
        '"${HQA_PROVIDER_ACCESS-unset}"\n'
        '  printf "ENV_HQA_HERMES_LIVE=%s\\n" '
        '"${HQA_HERMES_LIVE-unset}"\n'
        '  printf "ENV_HQA_HERMES_INTEGRATION_WT=%s\\n" '
        '"${HQA_HERMES_INTEGRATION_WT-unset}"\n'
        '  printf "ENV_HQA_HERMES_VENV_PYTHON=%s\\n" '
        '"${HQA_HERMES_VENV_PYTHON-unset}"\n'
        '  printf "ENV_QS_DATABASE_AUTO_MIGRATE=%s\\n" '
        '"${QS_DATABASE_AUTO_MIGRATE-unset}"\n'
        '  printf "ENV_QS_DATABASE_ENABLED=%s\\n" '
        '"${QS_DATABASE_ENABLED-unset}"\n'
        '  printf "ENV_QS_DEFAULT_DATA_PROVIDER=%s\\n" '
        '"${QS_DEFAULT_DATA_PROVIDER-unset}"\n'
        '  printf "ENV_QS_FUTU_ENABLED=%s\\n" "${QS_FUTU_ENABLED-unset}"\n'
        '  printf "ENV_QS_KILL_SWITCH=%s\\n" "${QS_KILL_SWITCH-unset}"\n'
        '  printf "ENV_QS_LIVE_TRADING_ENABLED=%s\\n" '
        '"${QS_LIVE_TRADING_ENABLED-unset}"\n'
        if capture_environment
        else ""
    )
    python.write_text(
        "#!/bin/sh\n"
        "{\n"
        '  printf "PWD=%s\\n" "$PWD"\n'
        '  for argument in "$@"; do\n'
        '    printf "ARG=%s\\n" "$argument"\n'
        "  done\n"
        f"{environment_capture}"
        f"}} > {shlex.quote(str(capture))}\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return wrapper, python, capture


def _arguments(
    wrapper: Path,
    python: Path | str,
    basetemp: Path | str,
) -> tuple[str, ...]:
    fixture_root = wrapper.parents[2]
    hermes_live = fixture_root / "owned-hermes"
    integration = (
        hermes_live / ".claude" / "worktrees" / "v2-integration"
    )
    hermes_python = hermes_live / "venv" / "bin" / "python"
    return (
        str(wrapper),
        "--python",
        str(python),
        "--basetemp",
        str(basetemp),
        "--hermes-live",
        str(hermes_live),
        "--integration-worktree",
        str(integration),
        "--hermes-python",
        str(hermes_python),
    )


def _invoke(
    wrapper: Path,
    python: Path | str,
    basetemp: Path | str,
    *extra_arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (*_arguments(wrapper, python, basetemp), *extra_arguments),
        check=False,
        capture_output=True,
        text=True,
    )


def test_focused_safety_wrapper_executes_exact_round1_gate6_selectors(
    tmp_path: Path,
) -> None:
    wrapper, python, capture = _release_fixture(tmp_path)
    basetemp = tmp_path / "focused-safety-basetemp"

    completed = _invoke(wrapper, python, basetemp)

    assert completed.returncode == 0, completed.stderr
    lines = capture.read_text(encoding="utf-8").splitlines()
    assert lines[0] == f"PWD={wrapper.parents[1]}"
    assert lines[1:] == [
        "ARG=-X",
        "ARG=int_max_str_digits=0",
        "ARG=-I",
        "ARG=-m",
        "ARG=pytest",
        "ARG=-q",
        f"ARG=--basetemp={basetemp}",
        *(f"ARG={selector}" for selector in SELECTORS),
    ]


def test_focused_safety_wrapper_rejects_selector_and_pytest_passthrough(
    tmp_path: Path,
) -> None:
    substitutions = (
        ("tests/test_gate.py::test_substituted_selector",),
        ("-k", "gate"),
        ("--ignore=tests/test_release_manifest.py",),
        ("--maxfail=1",),
        ("--deselect=tests/test_gate.py",),
    )

    for index, extra_arguments in enumerate(substitutions):
        case_root = tmp_path / f"case-{index}"
        wrapper, python, capture = _release_fixture(case_root)
        basetemp = case_root / "focused-safety-basetemp"

        completed = _invoke(
            wrapper,
            python,
            basetemp,
            *extra_arguments,
        )

        assert completed.returncode == 78
        assert "hqa_focused_safety_error=arguments_invalid" in completed.stderr
        assert not capture.exists()


def test_focused_safety_wrapper_replaces_the_host_environment_with_safe_rails(
    tmp_path: Path,
) -> None:
    wrapper, python, capture = _release_fixture(
        tmp_path,
        capture_environment=True,
    )
    basetemp = tmp_path / "focused-safety-basetemp"
    bash_env_marker = tmp_path / "bash-env-sourced"
    bash_env = tmp_path / "hostile-bash-env"
    bash_env.write_text(
        f"printf sourced > {shlex.quote(str(bash_env_marker))}\n",
        encoding="utf-8",
    )
    hostile_environment = {
        "ANTHROPIC_API_KEY": "injected-anthropic-secret",
        "BASH_ENV": str(bash_env),
        "FUTU_HOST": "injected-provider-host",
        "HOME": "/injected/home",
        "HQA_PROVIDER_ACCESS": "enabled",
        "HQA_HERMES_LIVE": "/injected/hermes-live",
        "HQA_HERMES_INTEGRATION_WT": "/injected/integration",
        "HQA_HERMES_VENV_PYTHON": "/injected/hermes-python",
        "LLM_API_KEY": "injected-llm-secret",
        "OPENAI_API_KEY": "injected-openai-secret",
        "PYTEST_ADDOPTS": "-k injected",
        "PYTEST_PLUGINS": "injected_plugin",
        "PYTHONHOME": "/injected/python-home",
        "PYTHONPATH": "/injected/python-path",
        "PYTHONWARNINGS": "error",
        "QS_DATABASE_AUTO_MIGRATE": "true",
        "QS_DATABASE_ENABLED": "true",
        "QS_DEFAULT_DATA_PROVIDER": "futu",
        "QS_FUTU_ENABLED": "true",
        "QS_KILL_SWITCH": "false",
        "QS_LIVE_TRADING_ENABLED": "true",
        "QS_LLM_PROVIDER": "openai",
        "TEMP": "/injected/temp",
        "TMP": "/injected/tmp",
        "TMPDIR": "/injected/tmpdir",
        "UNRELATED_INJECTION": "must-not-survive",
    }

    completed = subprocess.run(
        _arguments(wrapper, python, basetemp),
        check=False,
        capture_output=True,
        text=True,
        env=hostile_environment,
    )

    assert completed.returncode == 0, completed.stderr
    environment = dict(
        line.removeprefix("ENV_").split("=", 1)
        for line in capture.read_text(encoding="utf-8").splitlines()
        if line.startswith("ENV_")
    )
    assert environment == {
        "FUTU_HOST": "unset",
        "HOME": f"{basetemp}.home",
        "HQA_HERMES_INTEGRATION_WT": str(
            tmp_path
            / "owned-hermes"
            / ".claude"
            / "worktrees"
            / "v2-integration"
        ),
        "HQA_HERMES_LIVE": str(tmp_path / "owned-hermes"),
        "HQA_HERMES_VENV_PYTHON": str(
            tmp_path / "owned-hermes" / "venv" / "bin" / "python"
        ),
        "HQA_PROVIDER_ACCESS": "disabled",
        "OPENAI_API_KEY": "unset",
        "PYTEST_ADDOPTS": "unset",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_PLUGINS": "unset",
        "PYTHONHOME": "unset",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": "unset",
        "PYTHONPYCACHEPREFIX": f"{basetemp}.pycache",
        "PYTHONWARNINGS": "unset",
        "QS_DATABASE_AUTO_MIGRATE": "false",
        "QS_DATABASE_ENABLED": "false",
        "QS_DEFAULT_DATA_PROVIDER": "sample",
        "QS_FUTU_ENABLED": "false",
        "QS_KILL_SWITCH": "true",
        "QS_LIVE_TRADING_ENABLED": "false",
        "QS_LLM_PROVIDER": "unset",
        "TEMP": f"{basetemp}.tmp",
        "TMP": f"{basetemp}.tmp",
        "TMPDIR": f"{basetemp}.tmp",
        "UNRELATED_INJECTION": "unset",
    }
    assert not Path(f"{basetemp}.home").exists()
    assert not Path(f"{basetemp}.tmp").exists()
    assert not bash_env_marker.exists()


def test_focused_safety_wrapper_rejects_selector_symlink_substitution(
    tmp_path: Path,
) -> None:
    wrapper, python, capture = _release_fixture(tmp_path)
    substituted_selector = wrapper.parents[1] / SELECTORS[0]
    replacement = tmp_path / "replacement-selector.py"
    replacement.write_text("# substituted selector\n", encoding="utf-8")
    substituted_selector.unlink()
    substituted_selector.symlink_to(replacement)

    completed = _invoke(
        wrapper,
        python,
        tmp_path / "focused-safety-basetemp",
    )

    assert completed.returncode == 78
    assert "hqa_focused_safety_error=selector_unsafe" in completed.stderr
    assert not capture.exists()


def test_focused_safety_wrapper_rejects_symlinked_authority_inputs(
    tmp_path: Path,
) -> None:
    wrapper_root = tmp_path / "wrapper"
    wrapper, python, capture = _release_fixture(wrapper_root)
    real_wrapper = wrapper.with_name(f"{wrapper.name}.real")
    wrapper.rename(real_wrapper)
    wrapper.symlink_to(real_wrapper.name)
    completed = _invoke(
        wrapper,
        python,
        wrapper_root / "focused-safety-basetemp",
    )
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=" in completed.stderr
    assert not capture.exists()

    python_root = tmp_path / "python"
    wrapper, python, capture = _release_fixture(python_root)
    real_python = python_root / "real-python"
    python.rename(real_python)
    python.symlink_to(real_python)
    completed = _invoke(
        wrapper,
        python,
        python_root / "focused-safety-basetemp",
    )
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=" in completed.stderr
    assert not capture.exists()

    basetemp_root = tmp_path / "basetemp"
    wrapper, python, capture = _release_fixture(basetemp_root)
    real_basetemp = basetemp_root / "real-basetemp"
    real_basetemp.mkdir(mode=0o700)
    basetemp = basetemp_root / "focused-safety-basetemp"
    basetemp.symlink_to(real_basetemp, target_is_directory=True)
    completed = _invoke(wrapper, python, basetemp)
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=" in completed.stderr
    assert not capture.exists()


def test_focused_safety_wrapper_rejects_noncanonical_and_boundary_paths(
    tmp_path: Path,
) -> None:
    python_root = tmp_path / "python"
    wrapper, python, capture = _release_fixture(python_root)
    aliased_python = python.parent / ".." / "bin" / "python"
    completed = _invoke(
        wrapper,
        aliased_python,
        python_root / "focused-safety-basetemp",
    )
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=path_not_canonical" in completed.stderr
    assert not capture.exists()

    outside_python_root = tmp_path / "outside-python"
    wrapper, python, capture = _release_fixture(outside_python_root)
    external_python = outside_python_root / "python"
    shutil.copy2(python, external_python)
    completed = _invoke(
        wrapper,
        external_python,
        outside_python_root / "focused-safety-basetemp",
    )
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=python_must_be_release_local" in (
        completed.stderr
    )
    assert not capture.exists()

    basetemp_root = tmp_path / "basetemp"
    wrapper, python, capture = _release_fixture(basetemp_root)
    completed = _invoke(
        wrapper,
        python,
        wrapper.parents[1] / "inside-release-basetemp",
    )
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=basetemp_must_be_external" in (
        completed.stderr
    )
    assert not capture.exists()

    relative_root = tmp_path / "relative"
    wrapper, python, capture = _release_fixture(relative_root)
    completed = _invoke(wrapper, python, "relative-basetemp")
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=path_not_canonical" in completed.stderr
    assert not capture.exists()


def test_focused_safety_wrapper_rejects_group_or_world_writable_authority(
    tmp_path: Path,
) -> None:
    unsafe_cases: list[tuple[Path, Path, Path, Path]] = []

    wrapper_root = tmp_path / "wrapper"
    wrapper, python, capture = _release_fixture(wrapper_root)
    wrapper.chmod(0o775)
    unsafe_cases.append(
        (wrapper, python, capture, wrapper_root / "focused-basetemp")
    )

    python_root = tmp_path / "python"
    wrapper, python, capture = _release_fixture(python_root)
    python.chmod(0o775)
    unsafe_cases.append(
        (wrapper, python, capture, python_root / "focused-basetemp")
    )

    selector_root = tmp_path / "selector"
    wrapper, python, capture = _release_fixture(selector_root)
    (wrapper.parents[1] / SELECTORS[0]).chmod(0o666)
    unsafe_cases.append(
        (wrapper, python, capture, selector_root / "focused-basetemp")
    )

    release_root = tmp_path / "release-root"
    wrapper, python, capture = _release_fixture(release_root)
    wrapper.parents[1].chmod(0o777)
    unsafe_cases.append(
        (wrapper, python, capture, release_root / "focused-basetemp")
    )

    python_directory_root = tmp_path / "python-directory"
    wrapper, python, capture = _release_fixture(python_directory_root)
    python.parent.chmod(0o777)
    unsafe_cases.append(
        (
            wrapper,
            python,
            capture,
            python_directory_root / "focused-basetemp",
        )
    )

    for wrapper, python, capture, basetemp in unsafe_cases:
        completed = _invoke(wrapper, python, basetemp)
        assert completed.returncode == 78
        assert "hqa_focused_safety_error=" in completed.stderr
        assert "unsafe_mode" in completed.stderr
        assert not capture.exists()

    basetemp_root = tmp_path / "basetemp"
    wrapper, python, capture = _release_fixture(basetemp_root)
    basetemp = basetemp_root / "focused-basetemp"
    basetemp.mkdir(mode=0o700)
    basetemp.chmod(0o777)
    completed = _invoke(wrapper, python, basetemp)
    assert completed.returncode == 78
    assert "unsafe_mode" in completed.stderr
    assert not capture.exists()


def test_focused_safety_wrapper_rejects_reused_temp_authority(
    tmp_path: Path,
) -> None:
    basetemp_root = tmp_path / "basetemp"
    wrapper, python, capture = _release_fixture(basetemp_root)
    basetemp = basetemp_root / "focused-basetemp"
    basetemp.mkdir(mode=0o700)
    (basetemp / "prior-run").write_text("occupied\n", encoding="utf-8")

    completed = _invoke(wrapper, python, basetemp)

    assert completed.returncode == 78
    assert "hqa_focused_safety_error=basetemp_must_be_empty" in (
        completed.stderr
    )
    assert not capture.exists()

    pycache_root = tmp_path / "pycache"
    wrapper, python, capture = _release_fixture(pycache_root)
    basetemp = pycache_root / "focused-basetemp"
    pycache = Path(f"{basetemp}.pycache")
    pycache.mkdir(mode=0o700)
    (pycache / "prior-run").write_text("occupied\n", encoding="utf-8")

    completed = _invoke(wrapper, python, basetemp)

    assert completed.returncode == 78
    assert "hqa_focused_safety_error=pycache_must_be_empty" in (
        completed.stderr
    )
    assert not capture.exists()


def test_focused_safety_wrapper_requires_exact_owned_hermes_authority(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing"
    wrapper, python, capture = _release_fixture(missing_root)
    basetemp = missing_root / "focused-basetemp"
    completed = subprocess.run(
        (
            str(wrapper),
            "--python",
            str(python),
            "--basetemp",
            str(basetemp),
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=arguments_invalid" in completed.stderr
    assert not capture.exists()

    wrong_relationship_root = tmp_path / "wrong-relationship"
    wrapper, python, capture = _release_fixture(wrong_relationship_root)
    arguments = list(
        _arguments(
            wrapper,
            python,
            wrong_relationship_root / "focused-basetemp",
        )
    )
    arguments[-1] = str(wrong_relationship_root / "owned-python" / "python3.11")
    completed = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=hermes_python_not_authoritative" in (
        completed.stderr
    )
    assert not capture.exists()

    dirty_root = tmp_path / "dirty"
    wrapper, python, capture = _release_fixture(dirty_root)
    integration = (
        dirty_root
        / "owned-hermes"
        / ".claude"
        / "worktrees"
        / "v2-integration"
    )
    (integration / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    completed = _invoke(
        wrapper,
        python,
        dirty_root / "focused-basetemp",
    )
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=integration_dirty" in completed.stderr
    assert not capture.exists()

    branch_root = tmp_path / "branch"
    wrapper, python, capture = _release_fixture(branch_root)
    integration = (
        branch_root
        / "owned-hermes"
        / ".claude"
        / "worktrees"
        / "v2-integration"
    )
    _run_git(integration, "branch", "-m", "wrong-branch")
    completed = _invoke(
        wrapper,
        python,
        branch_root / "focused-basetemp",
    )
    assert completed.returncode == 78
    assert "hqa_focused_safety_error=integration_branch_mismatch" in (
        completed.stderr
    )
    assert not capture.exists()


def test_focused_safety_wrapper_has_owner_checks_and_no_effect_probe() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '[[ "$owner" == "$(/usr/bin/id -u)" ]]' in source
    assert "/usr/bin/env -i" in source
    assert "HQA_HERMES_LIVE=" in source
    assert "HQA_HERMES_INTEGRATION_WT=" in source
    assert "HQA_HERMES_VENV_PYTHON=" in source
    assert "HQA_PROVIDER_ACCESS=disabled" in source
    assert "QS_KILL_SWITCH=true" in source
    assert "QS_LIVE_TRADING_ENABLED=false" in source
    assert "QS_DATABASE_AUTO_MIGRATE=false" in source
    assert source.count("  tests/test_") == len(SELECTORS)
    for forbidden in (
        "--deselect",
        "--ignore",
        "--lf",
        "--maxfail",
        "--sw",
        "/api/health",
        "curl ",
        "wget ",
        "quant-system",
    ):
        assert forbidden not in source
