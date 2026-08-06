from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, path: str, body: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _topology(tmp_path: Path) -> tuple[Path, Path, Path]:
    bare = tmp_path / "official.git"
    seed = tmp_path / "seed"
    root = tmp_path / "hermes"
    runtime = tmp_path / "runtime"

    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    _git(seed, "config", "user.name", "Hermes Update Test")
    _git(seed, "config", "user.email", "update@example.invalid")
    _commit(seed, "official.txt", "official-v1\n", "official v1")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-q", "-u", "origin", "main")

    subprocess.run(["git", "clone", "-q", str(bare), str(root)], check=True)
    _git(root, "config", "user.name", "Hermes Update Test")
    _git(root, "config", "user.email", "update@example.invalid")
    _git(root, "branch", "codex/integration")
    _git(root, "worktree", "add", "-q", str(runtime), "codex/integration")
    _commit(runtime, "integration.txt", "local contract\n", "local integration")

    _commit(seed, "upstream.txt", "official-v2\n", "official v2")
    _git(seed, "push", "-q", "origin", "main")
    return root, runtime, tmp_path / "state"


def test_check_reports_official_commits_missing_from_both_worktrees(tmp_path) -> None:
    from hqa.hermes_update import UpdateConfig, check_update

    root, runtime, state = _topology(tmp_path)

    report = check_update(
        UpdateConfig(
            hermes_root=root,
            runtime_worktree=runtime,
            state_dir=state,
        ),
        fetch=True,
    )

    assert report.status == "update_available"
    assert report.root_missing_official == 1
    assert report.runtime_missing_official == 1
    assert report.runtime_local_commits == 1
    assert report.blockers == ()


def test_check_blocks_when_the_runtime_has_tracked_changes(tmp_path) -> None:
    from hqa.hermes_update import UpdateConfig, check_update

    root, runtime, state = _topology(tmp_path)
    (runtime / "integration.txt").write_text("unfinished edit\n", encoding="utf-8")

    report = check_update(
        UpdateConfig(
            hermes_root=root,
            runtime_worktree=runtime,
            state_dir=state,
        ),
        fetch=True,
    )

    assert report.status == "blocked"
    assert report.blockers == ("runtime_tracked_changes",)


def test_apply_validates_in_isolation_then_promotes_both_worktrees(tmp_path) -> None:
    from hqa.hermes_update import UpdateConfig, apply_update

    root, runtime, state = _topology(tmp_path)
    root_before = _git(root, "rev-parse", "HEAD")
    runtime_before = _git(runtime, "rev-parse", "HEAD")

    receipt = apply_update(
        UpdateConfig(
            hermes_root=root,
            runtime_worktree=runtime,
            state_dir=state,
            validation_commands=(("git", "diff", "--check"),),
        )
    )

    assert receipt.status == "applied"
    assert receipt.root_before == root_before
    assert receipt.runtime_before == runtime_before
    assert _git(root, "rev-parse", "HEAD") == receipt.official_head
    assert _git(runtime, "merge-base", "--is-ancestor", receipt.official_head, "HEAD") == ""
    assert (runtime / "integration.txt").read_text(encoding="utf-8") == "local contract\n"
    assert (runtime / "upstream.txt").read_text(encoding="utf-8") == "official-v2\n"
    assert receipt.receipt_path.is_file()
    assert receipt.backup_bundle.is_file()


def test_apply_keeps_a_conflicted_candidate_without_touching_live_worktrees(
    tmp_path,
) -> None:
    from hqa.hermes_update import UpdateConfig, apply_update

    root, runtime, state = _topology(tmp_path)
    _commit(runtime, "upstream.txt", "local competing file\n", "local conflict")
    root_before = _git(root, "rev-parse", "HEAD")
    runtime_before = _git(runtime, "rev-parse", "HEAD")

    receipt = apply_update(
        UpdateConfig(
            hermes_root=root,
            runtime_worktree=runtime,
            state_dir=state,
            validation_commands=(("git", "diff", "--check"),),
        )
    )

    assert receipt.status == "conflict"
    assert receipt.error_code == "candidate_merge_conflict"
    assert receipt.candidate_path is not None
    assert receipt.candidate_path.is_dir()
    assert _git(root, "rev-parse", "HEAD") == root_before
    assert _git(runtime, "rev-parse", "HEAD") == runtime_before


def test_rollback_restores_only_the_exact_applied_receipt(tmp_path) -> None:
    from hqa.hermes_update import UpdateConfig, apply_update, rollback_update

    root, runtime, state = _topology(tmp_path)
    config = UpdateConfig(
        hermes_root=root,
        runtime_worktree=runtime,
        state_dir=state,
        validation_commands=(("git", "diff", "--check"),),
    )
    applied = apply_update(config)

    rolled_back = rollback_update(config, applied.receipt_path)

    assert rolled_back.status == "rolled_back"
    assert _git(root, "rev-parse", "HEAD") == applied.root_before
    assert _git(runtime, "rev-parse", "HEAD") == applied.runtime_before


def test_apply_rolls_back_if_the_live_restart_check_fails(tmp_path) -> None:
    from hqa.hermes_update import UpdateConfig, apply_update

    root, runtime, state = _topology(tmp_path)
    root_before = _git(root, "rev-parse", "HEAD")
    runtime_before = _git(runtime, "rev-parse", "HEAD")
    restart = tmp_path / "restart"
    restart.write_text(
        "#!/bin/bash\n"
        f"count_file={tmp_path / 'restart.count'!s}\n"
        'count="$(cat "$count_file" 2>/dev/null || printf 0)"\n'
        'count="$((count + 1))"\n'
        'printf "%s" "$count" > "$count_file"\n'
        '[ "$count" -gt 1 ]\n',
        encoding="utf-8",
    )
    restart.chmod(0o700)

    receipt = apply_update(
        UpdateConfig(
            hermes_root=root,
            runtime_worktree=runtime,
            state_dir=state,
            validation_commands=(("git", "diff", "--check"),),
            restart_commands=((str(restart),),),
        )
    )

    assert receipt.status == "rolled_back_after_failure"
    assert receipt.error_code == "post_promotion_failed"
    assert _git(root, "rev-parse", "HEAD") == root_before
    assert _git(runtime, "rev-parse", "HEAD") == runtime_before


def test_cli_check_emits_a_machine_readable_operator_report(tmp_path) -> None:
    root, runtime, state = _topology(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "hqa.hermes_update_cli", "check"],
        cwd=Path(__file__).resolve().parent.parent,
        env={
            **os.environ,
            "HQA_HERMES_UPDATE_ROOT": str(root),
            "HQA_HERMES_UPDATE_RUNTIME": str(runtime),
            "HQA_HERMES_UPDATE_STATE": str(state),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "update_available"
    assert report["root_missing_official"] == 1
    assert report["runtime_local_commits"] == 1


def test_cli_candidate_environment_includes_api_server_test_dependencies(
    monkeypatch,
    tmp_path,
) -> None:
    from hqa.hermes_update_cli import _environment_config

    monkeypatch.setenv("HQA_HERMES_UPDATE_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("HQA_HERMES_UPDATE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("HQA_HERMES_UPDATE_STATE", str(tmp_path / "state"))

    config = _environment_config()

    assert config.validation_commands[0][-2:] == ("--extra", "messaging")
    assert config.validation_commands[1][:4] == (
        config.validation_commands[0][0],
        "run",
        "--no-sync",
        "pytest",
    )
    assert "tests/gateway/test_api_server_runs.py" in config.validation_commands[1]
    assert (
        "tests/gateway/test_api_server_managed_runs.py"
        not in config.validation_commands[1]
    )
    assert config.install_commands[0][-8:] == (
        "--extra",
        "all",
        "--extra",
        "messaging",
        "--extra",
        "edge-tts",
        "--extra",
        "voice",
    )
