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
        "hqa-quant-readonly.sh",
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
        "hqa-quant-readonly.sh",
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


# --- D-25 read-only gate wrapper -------------------------------------------

READONLY_SRC = REPO / "scripts" / "hermes" / "hqa-quant-readonly.sh"


def _build_gate(tmp_path):
    """Materialise the gate wrapper against a stub platform CLI that echoes
    its argv, so tests can assert both the allow (argv construction) and the
    refuse (exit 2, no exec) paths without touching the real quant-system."""
    platform = tmp_path / "platform"
    bindir = platform / "ai-quant" / "bin"
    bindir.mkdir(parents=True)
    stub = bindir / "quant-system"
    stub.write_text(
        "#!/bin/bash\nprintf 'ARGV'\nfor a in \"$@\"; do printf '|%s' \"$a\"; done\n"
        "printf '\\n'\n"
    )
    stub.chmod(0o755)
    body = READONLY_SRC.read_text().replace("__HQA_PLATFORM_DIR__", str(platform))
    gate = tmp_path / "hqa-quant-readonly.sh"
    gate.write_text(body)
    gate.chmod(0o755)
    return gate


def _run_gate(tmp_path, args):
    gate = _build_gate(tmp_path)
    return subprocess.run(
        ["bash", str(gate), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.mark.parametrize(
    "args, expected_argv",
    [
        (["doctor"], "ARGV|doctor"),
        (["config", "show"], "ARGV|config|show"),
        (["factor", "list"], "ARGV|factor|list"),
        (
            ["options", "daily-scan", "--top", "20"],
            "ARGV|options|daily-scan|--top|20",
        ),
        (["options", "buyside-screen"], "ARGV|options|buyside-screen"),
        (["paper", "account-show", "--account", "main"],
         "ARGV|paper|account-show|--account|main"),
        (["agent", "list-candidates"], "ARGV|agent|list-candidates"),
    ],
)
def test_gate_allows_readonly_commands(tmp_path, args, expected_argv):
    result = _run_gate(tmp_path, args)
    assert result.returncode == 0, result.stderr
    # Argv is forwarded verbatim (trailing flags preserved) to the platform CLI.
    assert result.stdout.strip() == expected_argv


@pytest.mark.parametrize(
    "args",
    [
        [],                              # empty → refused
        ["paper", "rebalance"],          # write: mutates account
        ["paper", "run-sample"],         # write: runs a loop
        ["agent", "review", "--approve"],  # write: approval lock
        ["agent", "propose-factor"],     # write: creates candidate file
        ["options", "daily-task"],       # refreshes inputs (side effect)
        ["options", "prune-cache", "--delete"],  # deletes cache
        ["data", "ingest-tiingo"],       # write: downloads + stores
        ["backtest", "run-sample"],      # compute/write
        ["config"],                      # bare group, not the `config show` leaf
        ["options"],                     # bare group
        ["doctor; rm -rf /"],            # injection as single token, no match
        ["serve"],                       # starts a server
        ["totally-unknown"],
    ],
)
def test_gate_refuses_non_allowlisted(tmp_path, args):
    result = _run_gate(tmp_path, args)
    assert result.returncode == 2
    assert "REFUSED: not in read-only allowlist" in result.stderr
    # Stub CLI must never have been exec'd on the refuse path.
    assert "ARGV" not in result.stdout


def test_gate_source_declares_readonly_allowlist():
    # Lock the verified read-only set into the script source. Every entry was
    # confirmed side-effect-free via `quant-system <cmd> --help`; adding a
    # write command here should require an explicit, reviewed change.
    body = READONLY_SRC.read_text()
    for entry in (
        '"doctor"',
        '"config show"',
        '"factor list"',
        '"options daily-scan"',
        '"options buyside-screen"',
        '"paper account-show"',
        '"agent list-candidates"',
    ):
        assert entry in body

