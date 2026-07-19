from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
WRAPPER = REPO / "scripts" / "hermes" / "hqa-research-task.sh"
SKILL = REPO / "skills" / "hermes" / "hqa-research-task" / "SKILL.md"


def _run(
    tmp_path: Path,
    *arguments: str,
    stdin: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = dict(
        os.environ,
        HQA_WORKFLOW_AUTHORITY_DIR=str(tmp_path / "workflow-authority-v2"),
        HQA_WORKFLOW_OWNER_USER_ID="owner-test",
    )
    return subprocess.run(
        [sys.executable, "-m", "hqa.workflow_authority_cli", *arguments],
        cwd=REPO,
        env=environment,
        input=(json.dumps(stdin) if stdin is not None else None),
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_apply_is_rejected_before_authority_or_stdin(tmp_path: Path) -> None:
    secret = "operation-do-not-read-or-leak-this-prompt"
    authority_root = tmp_path / "workflow-authority-v2"
    command = {
        "schema_version": 2,
        "kind": "workflow.start_research",
        "operation_id": secret,
        "workspace_ref": "workspace:managed-1",
        "managed_session_ref": "session:managed-1",
        "payload_ref": "payload:sha256:" + "a" * 64,
        "intent_expires_at": "2099-01-01T00:00:00.000000Z",
    }

    result = _run(tmp_path, "apply", stdin=command)

    assert result.returncode == 2
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "error": {
            "code": "workflow_invalid_request",
            "message": "workflow command is invalid",
            "retryable": False,
        }
    }
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert not authority_root.exists()


def test_apply_rejection_does_not_wait_for_or_read_stdin(tmp_path: Path) -> None:
    authority_root = tmp_path / "workflow-authority-v2"
    environment = dict(
        os.environ,
        HQA_WORKFLOW_AUTHORITY_DIR=str(authority_root),
        HQA_WORKFLOW_OWNER_USER_ID="owner-test",
    )
    read_fd, write_fd = os.pipe()

    try:
        result = subprocess.run(
            [sys.executable, "-m", "hqa.workflow_authority_cli", "apply"],
            cwd=REPO,
            env=environment,
            stdin=read_fd,
            text=True,
            capture_output=True,
            timeout=2,
        )
    finally:
        os.close(read_fd)
        os.close(write_fd)

    assert result.returncode == 2
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "error": {
            "code": "workflow_invalid_request",
            "message": "workflow command is invalid",
            "retryable": False,
        }
    }
    assert not authority_root.exists()


def test_cli_keeps_only_the_read_side_commands(tmp_path: Path) -> None:
    commands = (
        ("show", "--task-ref", "task:" + "a" * 64),
        ("events", "--task-ref", "task:" + "a" * 64),
        ("audit",),
        ("rebuild",),
    )

    for index, arguments in enumerate(commands):
        result = _run(tmp_path / str(index), *arguments)

        assert result.returncode == 1
        assert result.stderr == ""
        assert json.loads(result.stdout) == {
            "error": {
                "code": "workflow_authority_not_found",
                "message": "workflow authority rejected the operation",
                "retryable": False,
            }
        }


def test_invalid_read_arguments_are_nonretryable_and_create_no_authority(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "workflow-authority-v2"

    result = _run(
        tmp_path,
        "events",
        "--task-ref",
        "task:" + "a" * 64,
        "--limit",
        "0",
    )

    assert result.returncode == 2
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "error": {
            "code": "workflow_invalid_request",
            "message": "workflow command is invalid",
            "retryable": False,
        }
    }
    assert not authority_root.exists()


def test_hermes_research_task_wrapper_rejects_mutation_before_python(
    tmp_path: Path,
) -> None:
    body = WRAPPER.read_text(encoding="utf-8")
    installed_wrapper = tmp_path / "hqa-research-task.sh"
    installed_wrapper.write_text(
        body.replace("__HQA_REPO_DIR__", str(REPO)),
        encoding="utf-8",
    )
    installed_wrapper.chmod(0o755)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python_called = tmp_path / "python-called"
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" > "$HQA_TEST_PYTHON_CALLED"\nexit 97\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    environment = dict(
        os.environ,
        PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        HQA_TEST_PYTHON_CALLED=str(python_called),
    )
    secret = "do-not-read-or-leak-wrapper-stdin"

    result = subprocess.run(
        [str(installed_wrapper), "apply"],
        cwd=tmp_path,
        env=environment,
        input=secret,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert "cd __HQA_REPO_DIR__" in body
    assert "python3 -m hqa.workflow_authority_cli" in body
    assert "show|events|audit|rebuild" in body
    assert "hqa.research_task_cli" not in body
    assert "quant-system" not in body
    assert "hermes " not in body
    assert result.returncode == 2
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "error": {
            "code": "workflow_invalid_request",
            "message": "workflow command is invalid",
            "retryable": False,
        }
    }
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert not python_called.exists()


def test_hermes_skill_is_an_explicitly_read_only_dark_authority_surface() -> None:
    body = SKILL.read_text(encoding="utf-8")
    lower_body = body.lower()
    normalized_body = " ".join(lower_body.split())

    assert body.startswith("---\n")
    assert "name: hqa-research-task" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-research-task.sh" in body
    assert "read-only" in lower_body
    assert "show --task-ref" in body
    assert "events --task-ref" in body
    assert "audit" in body
    assert "rebuild" in body
    assert "apply" not in lower_body
    assert "mutation" not in lower_body
    assert "stdin" not in lower_body
    assert "resolve" not in lower_body
    assert "quant-system" not in body
    assert "provider" not in lower_body
    assert "chat_write_ready" in body
    assert "OFF" in body
    assert "worker claim/dispatch" in normalized_body
    assert "browser writes" in normalized_body
    assert "public composer submission" in normalized_body
    assert "paper trading" in normalized_body
    assert "live trading" in normalized_body
