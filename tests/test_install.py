from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _install(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = dict(os.environ, HOME=str(fake_home), HERMES_HOME=str(fake_home / ".hermes"))
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    return fake_home / ".hermes" / "scripts"


def test_install_copies_physical_executable_wrappers(tmp_path):
    dest = _install(tmp_path)
    names = sorted(p.name for p in dest.glob("hqa-*.sh"))
    assert names == [
        "hqa-aihot-alerts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-options-collect.sh",
        "hqa-options-radar.sh",
        "hqa-premarket-digest.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ]
    for wrapper in dest.glob("hqa-*.sh"):
        assert not wrapper.is_symlink()            # physical file (symlink would be blocked)
        assert os.access(wrapper, os.X_OK)         # executable
        body = wrapper.read_text()
        # Every wrapper launches a real program — either an hqa Python module
        # (digest/watchdog) or the platform quant-system CLI (collect). No stubs.
        assert "python3 -m hqa." in body or "quant-system" in body


def test_wrappers_pass_hermes_escape_check(tmp_path):
    # Replicate cron/scheduler.py: script must resolve INSIDE the scripts dir.
    dest = _install(tmp_path)
    scripts_dir_resolved = dest.resolve()
    for name in (
        "hqa-aihot-alerts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-options-collect.sh",
        "hqa-options-radar.sh",
        "hqa-premarket-digest.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ):
        resolved = (scripts_dir_resolved / name).resolve()
        # raises ValueError (⇒ test failure) if the path escapes the scripts dir
        resolved.relative_to(scripts_dir_resolved)


def test_symlink_would_be_blocked_by_escape_check(tmp_path):
    # Negative case: a symlink inside the scripts dir resolves OUTSIDE it,
    # so Hermes' relative_to(scripts_dir) check raises ValueError (job blocked).
    scripts_dir = tmp_path / ".hermes" / "scripts"
    scripts_dir.mkdir(parents=True)
    outside = tmp_path / "outside.sh"
    outside.write_text("#!/bin/bash\n")
    (scripts_dir / "evil.sh").symlink_to(outside)
    scripts_dir_resolved = scripts_dir.resolve()
    resolved = (scripts_dir_resolved / "evil.sh").resolve()
    with pytest.raises(ValueError):
        resolved.relative_to(scripts_dir_resolved)


def test_deployed_wrappers_have_no_unsubstituted_placeholders(tmp_path):
    # Regression guard: install.sh MUST sed-substitute the __HQA_REPO_DIR__ and
    # __HQA_PLATFORM_DIR__ placeholders. If install.sh were ever regressed to a
    # plain `cp` (exit 0, no substitution), the deployed wrappers would be dead
    # at runtime (cd to a literal "__HQA_REPO_DIR__" dir fails under
    # `set -euo pipefail`). This test locks in the sed substitution.
    dest = _install(tmp_path)
    for wrapper in dest.glob("hqa-*.sh"):
        body = wrapper.read_text()
        assert "__HQA_REPO_DIR__" not in body, (
            f"{wrapper.name}: unsubstituted __HQA_REPO_DIR__ placeholder remains"
        )
        assert "__HQA_PLATFORM_DIR__" not in body, (
            f"{wrapper.name}: unsubstituted __HQA_PLATFORM_DIR__ placeholder remains"
        )


def test_python_wrappers_use_install_time_repo_placeholder():
    for name in (
        "hqa-aihot-alerts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-options-radar.sh",
        "hqa-premarket-digest.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ):
        body = (REPO / "scripts" / "hermes" / name).read_text(encoding="utf-8")
        assert "cd __HQA_REPO_DIR__" in body
