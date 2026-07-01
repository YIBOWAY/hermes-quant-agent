from __future__ import annotations

import os
import subprocess
from pathlib import Path

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
    assert names == ["hqa-doctor-watchdog.sh", "hqa-premarket-digest.sh"]
    for wrapper in dest.glob("hqa-*.sh"):
        assert not wrapper.is_symlink()            # physical file (symlink would be blocked)
        assert os.access(wrapper, os.X_OK)         # executable
        assert "python3 -m hqa." in wrapper.read_text()


def test_wrappers_pass_hermes_escape_check(tmp_path):
    # Replicate cron/scheduler.py: script must resolve INSIDE the scripts dir.
    dest = _install(tmp_path)
    scripts_dir_resolved = dest.resolve()
    for name in ("hqa-doctor-watchdog.sh", "hqa-premarket-digest.sh"):
        resolved = (scripts_dir_resolved / name).resolve()
        # raises ValueError (⇒ test failure) if the path escapes the scripts dir
        resolved.relative_to(scripts_dir_resolved)
