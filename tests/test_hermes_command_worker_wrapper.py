from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
WRAPPER_SRC = REPO / "scripts" / "hermes" / "hqa-hermes-command-worker.sh"


def _materialize_wrapper(tmp_path: Path) -> Path:
    platform = tmp_path / "platform"
    bindir = platform / "ai-quant" / "bin"
    bindir.mkdir(parents=True)
    cli = bindir / "quant-system"
    cli.write_text(
        "#!/bin/bash\n"
        "printf 'CWD=%s\\n' \"$PWD\"\n"
        "printf 'PYTHONPATH=%s\\n' \"${PYTHONPATH-unset}\"\n"
        "printf 'PYTHONHOME=%s\\n' \"${PYTHONHOME-unset}\"\n"
        "printf 'ARGV'\n"
        "for arg in \"$@\"; do printf '|%s' \"$arg\"; done\n"
        "printf '\\n'\n",
        encoding="utf-8",
    )
    cli.chmod(0o755)

    wrapper = tmp_path / WRAPPER_SRC.name
    wrapper.write_text(
        WRAPPER_SRC.read_text(encoding="utf-8").replace(
            "__HQA_PLATFORM_DIR__", str(platform)
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def test_wrapper_can_only_enter_the_fixed_reconcile_only_worker_leaf(tmp_path: Path) -> None:
    wrapper = _materialize_wrapper(tmp_path)

    result = subprocess.run(
        ["bash", str(wrapper), "--once"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "ARGV|hermes|connector-worker|--once" in result.stdout


def test_wrapper_refuses_arguments_outside_the_worker_lifecycle_contract(
    tmp_path: Path,
) -> None:
    wrapper = _materialize_wrapper(tmp_path)

    result = subprocess.run(
        ["bash", str(wrapper), "--prompt", "do something"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "REFUSED: unsupported connector-worker argument" in result.stderr
    assert "ARGV" not in result.stdout


def test_wrapper_refuses_non_numeric_lifecycle_values_without_echoing_them(
    tmp_path: Path,
) -> None:
    wrapper = _materialize_wrapper(tmp_path)
    sensitive_value = "provider-secret-must-not-escape"

    result = subprocess.run(
        [
            "bash",
            str(wrapper),
            "--poll-interval-seconds",
            sensitive_value,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "REFUSED: unsupported connector-worker argument" in result.stderr
    assert sensitive_value not in result.stdout + result.stderr
    assert "ARGV" not in result.stdout


def test_wrapper_refuses_fixed_input_so_prompt_never_enters_process_argv(
    tmp_path: Path,
) -> None:
    wrapper = _materialize_wrapper(tmp_path)
    sensitive_prompt = "private research prompt must not enter argv"

    result = subprocess.run(
        ["bash", str(wrapper), "--fixed-input", sensitive_prompt],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "REFUSED: unsupported connector-worker argument" in result.stderr
    assert sensitive_prompt not in result.stdout + result.stderr
    assert "ARGV" not in result.stdout


def test_wrapper_forwards_only_documented_loop_controls_from_platform_cwd(
    tmp_path: Path,
) -> None:
    wrapper = _materialize_wrapper(tmp_path)

    result = subprocess.run(
        [
            "bash",
            str(wrapper),
            "--poll-interval-seconds",
            "30.0",
            "--max-cycles",
            "2",
            "--reconcile-limit",
            "100",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "tainted", "PYTHONHOME": "tainted"},
    )

    assert result.returncode == 0, result.stderr
    assert f"CWD={tmp_path / 'platform'}" in result.stdout
    assert "PYTHONPATH=unset" in result.stdout
    assert "PYTHONHOME=unset" in result.stdout
    assert (
        "ARGV|hermes|connector-worker|--poll-interval-seconds|30.0"
        "|--max-cycles|2|--reconcile-limit|100"
    ) in result.stdout
