from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path
from types import ModuleType

import pytest

from hqa import paper_research_cli

REPO = Path(__file__).resolve().parent.parent
LAUNCHER_SOURCE = REPO / "scripts" / "hermes" / "hqa-paper-gate-show.py"
_DATABASE_URL = "postgresql://runtime:secret@127.0.0.1:5432/quantplatform"


def _load_launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hqa_paper_gate_timeout_test",
        LAUNCHER_SOURCE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_pid_exit(pid: int, *, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while _pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not _pid_exists(pid)


def test_registry_uses_fixed_python_without_inheriting_python_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path_marker = tmp_path / "path-python-executed"
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "python3"
    shim.write_text(
        "#!/bin/bash\n"
        f"printf 'executed\\n' > \"{path_marker}\"\n"
        "exit 99\n",
        encoding="utf-8",
    )
    shim.chmod(0o700)
    injected_marker = tmp_path / "injected"
    injected = tmp_path / "python-injected"
    injected.mkdir()
    (injected / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(injected_marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    launcher = tmp_path / "fixed-launcher.py"
    launcher.write_text(
        "import json, os, sys\n"
        "assert sys.flags.no_user_site == 1\n"
        "for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', "
        "'PYTHONINSPECT', 'PYTHONUSERBASE'):\n"
        "    assert key not in os.environ\n"
        "assert os.environ['PYTHONNOUSERSITE'] == '1'\n"
        "assert sys.argv[1:] == ['hermes', 'paper-gate', 'show']\n"
        "request = json.load(sys.stdin)\n"
        "print(json.dumps({'contract': 'agent-v0.2-paper-gate-cli/v1', "
        "'operation': 'show', 'ok': True, "
        "'gate': {**request, 'status': 'pending'}}, "
        "sort_keys=True, separators=(',', ':')))\n",
        encoding="utf-8",
    )
    launcher.chmod(0o700)
    monkeypatch.setenv("PATH", f"{shim_dir}:/usr/bin:/bin")
    monkeypatch.setenv("PYTHONPATH", str(injected))
    monkeypatch.setenv("PYTHONHOME", "/tmp/escaped-python-home")
    monkeypatch.setenv("PYTHONSTARTUP", str(injected / "sitecustomize.py"))
    monkeypatch.setenv("PYTHONINSPECT", "1")
    monkeypatch.setenv("PYTHONUSERBASE", str(tmp_path / "escaped-user-base"))

    registry = paper_research_cli.SubprocessPaperGateRegistry(
        executable=launcher,
        cwd=tmp_path,
        timeout_seconds=5,
    )
    shown = registry.show(
        "paper-gate-fixed-python",
        workspace_id="ws-local-main",
        platform_session_id="platform-session-one",
    )

    assert shown["status"] == "pending"
    assert not path_marker.exists()
    assert not injected_marker.exists()


def test_registry_outer_timeout_leaves_launcher_room_for_group_cleanup() -> None:
    launcher = _load_launcher()

    cleanup_budget = (
        launcher._PAPER_GATE_TIMEOUT_SECONDS
        + launcher._PROCESS_TERMINATE_GRACE_SECONDS
        + launcher._PROCESS_GROUP_REAP_SECONDS
    )
    assert paper_research_cli._PLATFORM_TIMEOUT_SECONDS >= cleanup_budget + 5
    assert launcher._VERTICAL_A_TIMEOUT_SECONDS == 120.0


@pytest.mark.parametrize(
    ("argv", "selected_keys", "include_platform_context"),
    [
        (
            ["hermes", "paper-gate", "show"],
            "_DATABASE_KEYS",
            False,
        ),
        (
            ["hermes", "vertical-a", "execute-from-hermes"],
            "_VERTICAL_A_KEYS",
            True,
        ),
    ],
)
def test_runtime_port_timeout_kills_and_reaps_entire_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    selected_keys: str,
    include_platform_context: bool,
) -> None:
    launcher = _load_launcher()
    platform = tmp_path / "platform"
    quant_system = platform / "ai-quant" / "bin" / "quant-system"
    quant_system.parent.mkdir(parents=True)
    runtime_env = platform / "data" / "_runtime" / "agent-v0.2-backend.env"
    runtime_env.parent.mkdir(parents=True)
    runtime_env.write_text(
        "QS_DATABASE_ENABLED=true\n"
        f"QS_DATABASE_URL={_DATABASE_URL}\n"
        "QS_DATABASE_AUTO_MIGRATE=false\n",
        encoding="utf-8",
    )
    runtime_env.chmod(0o600)
    pids_path = tmp_path / "spawned-pids.json"
    child_code = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "while True:\n"
        "    time.sleep(1)\n"
    )
    quant_system.write_text(
        "#!/usr/bin/python3 -s\n"
        "import json, os, signal, subprocess, time\n"
        f"child_code = {child_code!r}\n"
        "child = subprocess.Popen(['/usr/bin/python3', '-s', '-c', child_code])\n"
        f"open({str(pids_path)!r}, 'w', encoding='utf-8').write("
        "json.dumps({'parent': os.getpid(), 'child': child.pid}))\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "while True:\n"
        "    time.sleep(1)\n",
        encoding="utf-8",
    )
    quant_system.chmod(0o700)
    monkeypatch.setattr(launcher, "_PLATFORM_DIR", platform)
    monkeypatch.setattr(launcher, "_QUANT_SYSTEM", quant_system)
    monkeypatch.setattr(launcher, "_RUNTIME_ENV", runtime_env)

    result = launcher._run_platform(
        argv,
        request=b"{}\n",
        selected_keys=getattr(launcher, selected_keys),
        include_platform_context=include_platform_context,
        timeout_seconds=1.0,
    )

    assert result == 78
    assert "paper_gate_env_error=quant_system_timeout" in capsys.readouterr().err
    assert pids_path.is_file()
    pids = json.loads(pids_path.read_text(encoding="utf-8"))
    assert _wait_for_pid_exit(pids["parent"])
    assert _wait_for_pid_exit(pids["child"])
