from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _init_hermes_checkout(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700)
    subprocess.run(
        ["git", "-C", str(path), "init", "-q", "-b", "main"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Install Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "config",
            "user.email",
            "install@example.invalid",
        ],
        check=True,
    )
    (path / "hermes.py").write_text("VERSION = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(path), "add", "hermes.py"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "-m", "initial"],
        check=True,
    )
    return path


def _codesign_identity(helper: Path) -> tuple[str, str]:
    inspected = subprocess.run(
        ["/usr/bin/codesign", "-d", "--verbose=4", str(helper)],
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert inspected.returncode == 0, inspected.stdout + inspected.stderr
    identifier = re.search(r"^Identifier=(.+)$", inspected.stderr, re.MULTILINE)
    cdhash = re.search(r"^CDHash=(.+)$", inspected.stderr, re.MULTILINE)
    assert identifier is not None, inspected.stderr
    assert cdhash is not None, inspected.stderr
    return identifier.group(1), cdhash.group(1)


def _install(
    tmp_path,
    *,
    platform_dir: Path | None = None,
    hermes_source_dir: Path | None = None,
    hermes_api_key_file: Path | str | None = None,
    installer_repo: Path = REPO,
    forbidden_text: str | None = None,
):
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"
    helper_parent = hermes_home / "bin"
    helper_parent.mkdir(parents=True, mode=0o700)
    helper = helper_parent / "hqa-intent-payload-crypto"
    helper.write_text("#!/bin/bash\nexit 64\n", encoding="utf-8")
    helper.chmod(0o700)
    if hermes_source_dir is None:
        hermes_source_dir = _init_hermes_checkout(tmp_path / "hermes-source")
    env = dict(
        os.environ,
        HOME=str(fake_home),
        HERMES_HOME=str(hermes_home),
        HQA_HERMES_SOURCE_DIR=str(hermes_source_dir),
        HQA_SKIP_NATIVE_BUILD="1",
    )
    if platform_dir is not None:
        env["HQA_AIQP_DIR"] = str(platform_dir)
    if hermes_api_key_file is not None:
        env["HQA_HERMES_COMPAT_HERMES_API_KEY_FILE"] = str(
            hermes_api_key_file
        )
    else:
        env.pop("HQA_HERMES_COMPAT_HERMES_API_KEY_FILE", None)
    result = subprocess.run(
        ["bash", str(installer_repo / "scripts" / "install.sh")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    if forbidden_text is not None:
        forbidden_bytes = forbidden_text.encode("utf-8")
        assert forbidden_text not in result.stdout
        for deployed in hermes_home.rglob("*"):
            if deployed.is_file():
                assert forbidden_bytes not in deployed.read_bytes(), deployed
    return hermes_home / "scripts"


def test_install_normalizes_default_source_from_lexical_hermes_home(
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    (fake_home / "nested").mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"
    helper_parent = hermes_home / "bin"
    helper_parent.mkdir(parents=True, mode=0o700)
    helper = helper_parent / "hqa-intent-payload-crypto"
    helper.write_text("#!/bin/bash\nexit 64\n", encoding="utf-8")
    helper.chmod(0o700)
    source = _init_hermes_checkout(hermes_home / "hermes-agent")
    lexical_home = fake_home / "nested" / ".." / ".hermes"

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(lexical_home),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert result.returncode == 0, result.stdout
    installed = hermes_home / "scripts" / "hqa-hermes-compatibility-watch.sh"
    assert f"HQA_INSTALLED_HERMES_SOURCE_DIR={source}" in installed.read_text(
        encoding="utf-8"
    )


def test_install_cannot_skip_a_missing_native_helper(tmp_path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert result.returncode != 0
    assert "skip requires an existing helper" in result.stdout
    assert not (hermes_home / "scripts").exists()
    assert not (hermes_home / "skills").exists()


def test_install_cannot_skip_native_build_for_nonprivate_helper(tmp_path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"
    helper_parent = hermes_home / "bin"
    helper_parent.mkdir(parents=True, mode=0o700)
    helper = helper_parent / "hqa-intent-payload-crypto"
    helper.write_text("#!/bin/bash\nexit 64\n", encoding="utf-8")
    helper.chmod(0o755)

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert result.returncode != 0
    assert "exact private physical helper" in result.stdout
    assert helper.stat().st_mode & 0o777 == 0o755
    assert not (hermes_home / "scripts").exists()
    assert not (hermes_home / "skills").exists()


def test_install_skip_refuses_symlinked_helper_ancestor_without_execution(
    tmp_path,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"
    hermes_home.mkdir(mode=0o700)
    victim_bin = tmp_path / "victim-bin"
    victim_bin.mkdir(mode=0o700)
    executed = tmp_path / "executed"
    victim_helper = victim_bin / "hqa-intent-payload-crypto"
    victim_helper.write_text(
        f"#!/bin/bash\nprintf executed > {executed!s}\nexit 64\n",
        encoding="utf-8",
    )
    victim_helper.chmod(0o700)
    (hermes_home / "bin").symlink_to(victim_bin, target_is_directory=True)

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert result.returncode != 0
    assert "helper path must contain only physical directories" in result.stdout
    assert not executed.exists()
    assert (hermes_home / "bin").is_symlink()
    assert not (hermes_home / "scripts").exists()
    assert not (hermes_home / "skills").exists()


def test_install_refuses_symlinked_hermes_root_before_any_target_write(
    tmp_path,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    victim = tmp_path / "victim"
    victim.mkdir(mode=0o755)
    hermes_home = fake_home / ".hermes"
    hermes_home.symlink_to(victim, target_is_directory=True)

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert result.returncode != 0
    assert hermes_home.is_symlink()
    assert not (victim / "scripts").exists()
    assert not (victim / "skills").exists()
    assert not (victim / "bin").exists()
    assert victim.stat().st_mode & 0o777 == 0o755


def test_install_refuses_world_writable_intermediate_ancestor_before_write(
    tmp_path,
) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o777)
    unsafe.chmod(0o777)
    fake_home = unsafe / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert result.returncode != 0
    assert "ancestor must be owner-controlled" in result.stdout
    assert unsafe.stat().st_mode & 0o777 == 0o777
    assert fake_home.stat().st_mode & 0o777 == 0o700
    assert not hermes_home.exists()


def test_install_stages_then_refuses_symlinked_publish_directory(
    tmp_path,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"
    helper_parent = hermes_home / "bin"
    helper_parent.mkdir(parents=True, mode=0o700)
    helper = helper_parent / "hqa-intent-payload-crypto"
    helper.write_text("#!/bin/bash\nexit 64\n", encoding="utf-8")
    helper.chmod(0o700)
    _init_hermes_checkout(hermes_home / "hermes-agent")
    victim = tmp_path / "victim-scripts"
    victim.mkdir(mode=0o700)
    marker = victim / "marker"
    marker.write_text("unchanged", encoding="utf-8")
    (hermes_home / "scripts").symlink_to(victim, target_is_directory=True)

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert result.returncode != 0
    assert "install destination contains a symlink or non-directory" in result.stdout
    assert (hermes_home / "scripts").is_symlink()
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert sorted(victim.iterdir()) == [marker]
    assert not (hermes_home / "skills").exists()
    assert not list(hermes_home.glob(".hqa-install.*"))


def test_install_atomically_upgrades_owner_controlled_legacy_files(
    tmp_path,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"
    helper_parent = hermes_home / "bin"
    helper_parent.mkdir(parents=True, mode=0o700)
    helper = helper_parent / "hqa-intent-payload-crypto"
    helper.write_text("#!/bin/bash\nexit 64\n", encoding="utf-8")
    helper.chmod(0o700)
    scripts = hermes_home / "scripts"
    scripts.mkdir(mode=0o755)
    legacy_wrapper = scripts / "hqa-research-task.sh"
    legacy_wrapper.write_text("legacy\n", encoding="utf-8")
    legacy_wrapper.chmod(0o755)
    skill_dir = hermes_home / "skills" / "hqa-research-task"
    skill_dir.mkdir(parents=True, mode=0o755)
    legacy_skill = skill_dir / "SKILL.md"
    legacy_skill.write_text("legacy\n", encoding="utf-8")
    legacy_skill.chmod(0o644)
    _init_hermes_checkout(hermes_home / "hermes-agent")

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert result.returncode == 0, result.stdout
    assert legacy_wrapper.read_text(encoding="utf-8").startswith("#!/bin/bash\n")
    assert legacy_wrapper.stat().st_mode & 0o777 == 0o700
    assert legacy_skill.read_text(encoding="utf-8").startswith("---\n")
    assert legacy_skill.stat().st_mode & 0o777 == 0o600


def test_install_reports_only_candidate_files_and_preserves_unrelated_entries(
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"
    helper_parent = hermes_home / "bin"
    helper_parent.mkdir(parents=True, mode=0o700)
    helper = helper_parent / "hqa-intent-payload-crypto"
    helper.write_text("#!/bin/bash\nexit 64\n", encoding="utf-8")
    helper.chmod(0o700)
    scripts = hermes_home / "scripts"
    scripts.mkdir(mode=0o700)
    orphan_wrapper = scripts / "hqa-unrelated-existing.sh"
    orphan_wrapper.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    orphan_wrapper.chmod(0o700)
    unrelated_skill = hermes_home / "skills" / "unrelated-existing"
    unrelated_skill.mkdir(parents=True, mode=0o700)
    unrelated_card = unrelated_skill / "SKILL.md"
    unrelated_card.write_text("unrelated\n", encoding="utf-8")
    unrelated_card.chmod(0o600)
    _init_hermes_checkout(hermes_home / "hermes-agent")

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert str(orphan_wrapper) not in result.stdout
    assert str(unrelated_card) not in result.stdout
    assert f"installed: {scripts / 'hqa-research-task.sh'}" in result.stdout
    assert (
        f"installed: {hermes_home / 'skills/hqa-research-task/SKILL.md'}"
        in result.stdout
    )
    assert orphan_wrapper.read_text(encoding="utf-8").endswith("exit 0\n")
    assert unrelated_card.read_text(encoding="utf-8") == "unrelated\n"


def test_install_copies_physical_executable_wrappers(tmp_path):
    dest = _install(tmp_path)
    names = sorted(p.name for p in dest.glob("hqa-*.sh"))
    assert names == [
        "hqa-aihot-alerts.sh",
        "hqa-artifacts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-factor-repro.sh",
        "hqa-full-9h-daily-close.sh",
        "hqa-full-9h-freshness.sh",
        "hqa-full-9h-notification-drain.sh",
        "hqa-full-9h-weekly.sh",
        "hqa-hermes-command-worker.sh",
        "hqa-hermes-compatibility-watch.sh",
        "hqa-intent-payload-reconcile.sh",
        "hqa-market-foresight.sh",
        "hqa-notify.sh",
        "hqa-opportunities.sh",
        "hqa-options-collect.sh",
        "hqa-options-radar.sh",
        "hqa-options-research.sh",
        "hqa-paper-research.sh",
        "hqa-portfolio-risk.sh",
        "hqa-prediction.sh",
        "hqa-premarket-digest.sh",
        "hqa-quant-readonly.sh",
        "hqa-research-task.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ]
    for wrapper in dest.glob("hqa-*.sh"):
        assert not wrapper.is_symlink()  # physical file (symlink would be blocked)
        assert os.access(wrapper, os.X_OK)  # executable
        body = wrapper.read_text()
        # Every wrapper launches a real program — an hqa Python module
        # (digest/watchdog), the private Platform runtime launcher, the
        # platform quant-system CLI (collect/gate), or the Hermes messaging
        # CLI (notify). No stubs.
        assert (
            "python3 -m hqa." in body
            or "hqa-paper-gate-show.py" in body
            or "quant-system" in body
            or "hermes send" in body
        )


def test_install_builds_private_native_intent_crypto_helper(tmp_path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    hermes_home = fake_home / ".hermes"
    _init_hermes_checkout(hermes_home / "hermes-agent")
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(os.environ, HOME=str(fake_home), HERMES_HOME=str(hermes_home)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout
    helper = hermes_home / "bin" / "hqa-intent-payload-crypto"
    assert helper.is_file()
    assert not helper.is_symlink()
    assert helper.stat().st_mode & 0o777 == 0o700
    assert helper.parent.stat().st_mode & 0o777 == 0o700
    first_identity = _codesign_identity(helper)
    assert first_identity[0] == "hqa-intent-payload-crypto"

    repeated = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(os.environ, HOME=str(fake_home), HERMES_HOME=str(hermes_home)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )

    assert repeated.returncode == 0, repeated.stdout
    assert _codesign_identity(helper) == first_identity


def test_wrappers_pass_hermes_escape_check(tmp_path):
    # Replicate cron/scheduler.py: script must resolve INSIDE the scripts dir.
    dest = _install(tmp_path)
    scripts_dir_resolved = dest.resolve()
    for name in (
        "hqa-aihot-alerts.sh",
        "hqa-artifacts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-full-9h-daily-close.sh",
        "hqa-full-9h-freshness.sh",
        "hqa-full-9h-notification-drain.sh",
        "hqa-full-9h-weekly.sh",
        "hqa-factor-repro.sh",
        "hqa-hermes-command-worker.sh",
        "hqa-hermes-compatibility-watch.sh",
        "hqa-intent-payload-reconcile.sh",
        "hqa-market-foresight.sh",
        "hqa-notify.sh",
        "hqa-options-collect.sh",
        "hqa-opportunities.sh",
        "hqa-options-radar.sh",
        "hqa-options-research.sh",
        "hqa-paper-research.sh",
        "hqa-portfolio-risk.sh",
        "hqa-prediction.sh",
        "hqa-premarket-digest.sh",
        "hqa-quant-readonly.sh",
        "hqa-research-task.sh",
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
        assert "__HQA_HERMES_SOURCE_DIR__" not in body, (
            f"{wrapper.name}: unsubstituted Hermes source placeholder remains"
        )
        assert "__HQA_HERMES_API_KEY_FILE__" not in body, (
            f"{wrapper.name}: unsubstituted Hermes API-key placeholder remains"
        )


def test_installed_compatibility_watcher_freezes_selected_hermes_checkout_and_key_path(
    tmp_path: Path,
) -> None:
    selected = _init_hermes_checkout(tmp_path / "selected-hermes-worktree")
    api_key = tmp_path / "hermes-api.key"
    api_key.write_text("test-key\n", encoding="utf-8")
    api_key.chmod(0o600)
    scripts = _install(
        tmp_path,
        hermes_source_dir=selected,
        hermes_api_key_file=api_key,
    )
    watcher = scripts / "hqa-hermes-compatibility-watch.sh"
    body = watcher.read_text(encoding="utf-8")

    assert f"HQA_INSTALLED_HERMES_SOURCE_DIR={selected}" in body
    assert (
        'export HQA_HERMES_COMPAT_HERMES_REPO="$HQA_INSTALLED_HERMES_SOURCE_DIR"'
        in body
    )
    assert f"HQA_INSTALLED_HQA_REPO={REPO}" in body
    assert 'export HQA_HERMES_COMPAT_HQA_REPO="$HQA_INSTALLED_HQA_REPO"' in body
    assert f"HQA_INSTALLED_HERMES_API_KEY_FILE={api_key}" in body
    assert (
        "export HQA_HERMES_COMPAT_HERMES_API_KEY_FILE="
        '"$HQA_INSTALLED_HERMES_API_KEY_FILE"'
    ) in body
    assert "import hermes" not in body


def test_installer_freezes_existing_default_key_without_copying_secret(
    tmp_path: Path,
) -> None:
    release_repo = tmp_path / "release-hqa"
    release_repo.mkdir(mode=0o700)
    shutil.copytree(REPO / "scripts", release_repo / "scripts")
    shutil.copytree(REPO / "skills", release_repo / "skills")
    default_key = release_repo / "data" / "_runtime" / "hermes-api.key"
    default_key.parent.mkdir(parents=True, mode=0o700)
    secret = "install-secret-never-copy-f321c809"
    default_key.write_text(f"{secret}\n", encoding="utf-8")
    default_key.chmod(0o600)
    selected = _init_hermes_checkout(tmp_path / "selected-hermes-worktree")

    scripts = _install(
        tmp_path,
        hermes_source_dir=selected,
        installer_repo=release_repo,
        forbidden_text=secret,
    )
    body = (scripts / "hqa-hermes-compatibility-watch.sh").read_text(
        encoding="utf-8"
    )

    assert f"HQA_INSTALLED_HQA_REPO={release_repo}" in body
    assert f"HQA_INSTALLED_HERMES_API_KEY_FILE={default_key}" in body


@pytest.mark.parametrize("configured_key", [False, True])
def test_installed_compatibility_watcher_rejects_runtime_key_redirect(
    tmp_path: Path,
    configured_key: bool,
) -> None:
    selected = _init_hermes_checkout(tmp_path / "selected-hermes-worktree")
    if configured_key:
        api_key: Path | str = tmp_path / "hermes-api.key"
        api_key.write_text("test-key\n", encoding="utf-8")
        api_key.chmod(0o600)
        expected_key = str(api_key)
    else:
        api_key = ""
        expected_key = ""
    scripts = _install(
        tmp_path,
        hermes_source_dir=selected,
        hermes_api_key_file=api_key,
    )
    watcher = scripts / "hqa-hermes-compatibility-watch.sh"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(mode=0o700)
    marker = tmp_path / "watcher-environment"
    python = fake_bin / "python3"
    python.write_text(
        "#!/bin/bash\n"
        "printf '%s\\0%s\\0' "
        '"$HQA_HERMES_COMPAT_HQA_REPO" '
        '"$HQA_HERMES_COMPAT_HERMES_API_KEY_FILE" '
        '> "$WATCH_ENV_MARKER"\n',
        encoding="utf-8",
    )
    python.chmod(0o700)

    result = subprocess.run(
        ["bash", str(watcher)],
        env=dict(
            os.environ,
            PATH=f"{fake_bin}:/usr/bin:/bin",
            WATCH_ENV_MARKER=str(marker),
            HQA_HERMES_COMPAT_HQA_REPO=str(tmp_path / "hostile-hqa"),
            HQA_HERMES_COMPAT_HERMES_API_KEY_FILE=str(
                tmp_path / "hostile-key"
            ),
        ),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert marker.read_bytes().split(b"\0") == [
        os.fsencode(REPO),
        os.fsencode(expected_key),
        b"",
    ]


@pytest.mark.parametrize("invalid_source", ["relative", "non_git", "symlink"])
def test_install_refuses_invalid_hermes_source_checkout(
    tmp_path: Path,
    invalid_source: str,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"
    helper_parent = hermes_home / "bin"
    helper_parent.mkdir(parents=True, mode=0o700)
    helper = helper_parent / "hqa-intent-payload-crypto"
    helper.write_text("#!/bin/bash\nexit 64\n", encoding="utf-8")
    helper.chmod(0o700)
    if invalid_source == "relative":
        selected = Path("relative-hermes")
    elif invalid_source == "non_git":
        selected = tmp_path / "not-a-git-checkout"
        selected.mkdir(mode=0o700)
    else:
        physical = _init_hermes_checkout(tmp_path / "physical-hermes")
        selected = tmp_path / "linked-hermes"
        selected.symlink_to(physical, target_is_directory=True)

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_HERMES_SOURCE_DIR=str(selected),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert not (hermes_home / "scripts").exists()
    assert not (hermes_home / "skills").exists()
    assert not list(hermes_home.glob(".hqa-install.*"))


@pytest.mark.parametrize(
    "invalid_key",
    ["relative", "symlink", "public", "fifo"],
)
def test_install_refuses_invalid_hermes_api_key_file(
    tmp_path: Path,
    invalid_key: str,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(mode=0o700)
    hermes_home = fake_home / ".hermes"
    helper_parent = hermes_home / "bin"
    helper_parent.mkdir(parents=True, mode=0o700)
    helper = helper_parent / "hqa-intent-payload-crypto"
    helper.write_text("#!/bin/bash\nexit 64\n", encoding="utf-8")
    helper.chmod(0o700)
    selected = _init_hermes_checkout(tmp_path / "selected-hermes-worktree")
    if invalid_key == "relative":
        api_key = Path("relative-key")
    elif invalid_key == "symlink":
        physical = tmp_path / "physical-key"
        physical.write_text("test-key\n", encoding="utf-8")
        physical.chmod(0o600)
        api_key = tmp_path / "linked-key"
        api_key.symlink_to(physical)
    elif invalid_key == "public":
        api_key = tmp_path / "public-key"
        api_key.write_text("test-key\n", encoding="utf-8")
        api_key.chmod(0o644)
    else:
        api_key = tmp_path / "fifo-key"
        os.mkfifo(api_key, mode=0o600)

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=dict(
            os.environ,
            HOME=str(fake_home),
            HERMES_HOME=str(hermes_home),
            HQA_HERMES_SOURCE_DIR=str(selected),
            HQA_HERMES_COMPAT_HERMES_API_KEY_FILE=str(api_key),
            HQA_SKIP_NATIVE_BUILD="1",
        ),
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert not (hermes_home / "scripts").exists()
    assert not (hermes_home / "skills").exists()
    assert not list(hermes_home.glob(".hqa-install.*"))


def test_installed_factor_repro_wrapper_freezes_identity_and_exact_allowlist(
    tmp_path,
) -> None:
    platform_dir = tmp_path / "release-platform"
    platform_dir.mkdir()
    scripts_dest = _install(tmp_path, platform_dir=platform_dir)
    wrapper = scripts_dest / "hqa-factor-repro.sh"
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    path_marker = tmp_path / "path-python-executed"
    stub = stub_dir / "python3"
    stub.write_text(
        "#!/bin/bash\n"
        f"printf 'executed\\n' > \"{path_marker}\"\n"
        "exit 99\n",
        encoding="utf-8",
    )
    stub.chmod(0o700)
    injection_marker = tmp_path / "python-injection-executed"
    injected = tmp_path / "injected"
    injected.mkdir()
    injected_hook = (
        "from pathlib import Path\n"
        f"Path({str(injection_marker)!r}).write_text('executed')\n"
    )
    (injected / "sitecustomize.py").write_text(injected_hook, encoding="utf-8")
    startup = tmp_path / "python-startup.py"
    startup.write_text(injected_hook, encoding="utf-8")
    user_base = tmp_path / "python-user-base"
    for version in ("3.8", "3.9", "3.10", "3.11", "3.12", "3.13"):
        site_packages = user_base / "lib" / f"python{version}" / "site-packages"
        site_packages.mkdir(parents=True)
        (site_packages / "sitecustomize.py").write_text(
            injected_hook,
            encoding="utf-8",
        )
    env = dict(
        os.environ,
        PATH=f"{stub_dir}:/usr/bin:/bin",
        HQA_AIQP_DIR="/tmp/escaped-platform",
        HQA_QUANT_SYSTEM_BIN="/tmp/escaped-quant-system",
        HQA_FACTOR_REPRO_BIN="/tmp/escaped-factor-wrapper",
        PYTHONHOME="/tmp/escaped-python-home",
        PYTHONINSPECT="1",
        PYTHONNOUSERSITE="0",
        PYTHONPATH=str(injected),
        PYTHONSTARTUP=str(startup),
        PYTHONUSERBASE=str(user_base),
    )

    assert wrapper.is_file()
    assert not wrapper.is_symlink()
    assert wrapper.stat().st_mode & 0o777 == 0o700
    body = wrapper.read_text(encoding="utf-8")
    assert "__HQA_REPO_DIR__" not in body
    assert "__HQA_PLATFORM_DIR__" not in body
    assert "__HERMES_SCRIPTS_DIR__" not in body
    assert "agent-v0.2-backend.env" not in body
    assert "\nsource " not in body
    assert "unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT" in body
    assert "export PYTHONNOUSERSITE=1" in body
    assert "exec /usr/bin/python3 -s -m hqa.factor_repro_cli" in body

    for operation in ("propose", "list", "detail", "approve", "backtest", "promote"):
        result = subprocess.run(
            [str(wrapper), operation, "--help"],
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert f"usage: hqa-factor-repro {operation}" in result.stdout
        assert not path_marker.exists()
        assert not injection_marker.exists()

    for argv in ([], ["propose-extra"], ["promotion-status"]):
        refused = subprocess.run(
            [str(wrapper), *argv],
            env=env,
            capture_output=True,
            text=True,
        )
        assert refused.returncode == 2
        assert refused.stdout == ""
        assert "factor_repro_operation_not_allowed" in refused.stderr
        assert "cwd=" not in refused.stderr

    paper_wrapper = scripts_dest / "hqa-paper-research.sh"
    paper_result = subprocess.run(
        [str(paper_wrapper), "prepare-intent"],
        input="",
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert paper_result.returncode == 2
    assert "paper_research_" in paper_result.stdout + paper_result.stderr
    assert not path_marker.exists()
    assert not injection_marker.exists()

    options_wrapper = scripts_dest / "hqa-options-research.sh"
    options_result = subprocess.run(
        [str(options_wrapper)],
        input="",
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert options_result.returncode == 78
    assert "paper_gate_env_error=runtime_env_missing" in options_result.stderr
    assert not path_marker.exists()
    assert not injection_marker.exists()

    readonly_wrapper = scripts_dest / "hqa-quant-readonly.sh"
    readonly_body = readonly_wrapper.read_text(encoding="utf-8")
    assert "unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT" in readonly_body
    assert "export PYTHONNOUSERSITE=1" in readonly_body
    assert 'exec /usr/bin/python3 -s "$SCRIPT_DIR/hqa-paper-gate-show.py"' in (
        readonly_body
    )
    readonly_result = subprocess.run(
        [
            str(readonly_wrapper),
            "hermes",
            "paper-gate",
            "show",
            "--gate-id",
            "paper-gate-python-boundary",
            "--workspace-id",
            "ws-local-main",
            "--platform-session-id",
            "platform-session-python-boundary",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert readonly_result.returncode == 78
    assert "paper_gate_env_error=runtime_env_missing" in readonly_result.stderr
    assert not path_marker.exists()
    assert not injection_marker.exists()


def test_python_wrappers_use_install_time_repo_placeholder():
    for name in (
        "hqa-aihot-alerts.sh",
        "hqa-artifacts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-full-9h-daily-close.sh",
        "hqa-full-9h-freshness.sh",
        "hqa-full-9h-notification-drain.sh",
        "hqa-full-9h-weekly.sh",
        "hqa-hermes-compatibility-watch.sh",
        "hqa-intent-payload-reconcile.sh",
        "hqa-market-foresight.sh",
        "hqa-opportunities.sh",
        "hqa-paper-research.sh",
        "hqa-options-radar.sh",
        "hqa-portfolio-risk.sh",
        "hqa-prediction.sh",
        "hqa-premarket-digest.sh",
        "hqa-research-task.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ):
        body = (REPO / "scripts" / "hermes" / name).read_text(encoding="utf-8")
        assert "cd __HQA_REPO_DIR__" in body


def test_full_9h_wrappers_are_thin_fixed_job_adapters() -> None:
    expected = {
        "hqa-full-9h-daily-close.sh": "daily_close",
        "hqa-full-9h-freshness.sh": "freshness",
        "hqa-full-9h-notification-drain.sh": "notification_drain",
        "hqa-full-9h-weekly.sh": "weekly",
    }
    for name, job in expected.items():
        body = (REPO / "scripts" / "hermes" / name).read_text(encoding="utf-8")
        assert "cd __HQA_REPO_DIR__" in body
        assert f"-m hqa.research_automation_cli {job}" in body
        assert "--workdir" not in body


def test_full_9h_desired_cron_contract_is_versioned_and_parallel_pool_safe() -> None:
    contract = json.loads(
        (REPO / "config" / "hermes-cron.v1.json").read_text(encoding="utf-8")
    )

    assert set(contract) == {"schema_version", "timezone", "jobs"}
    assert contract["schema_version"] == "1.0"
    assert contract["timezone"] == "Asia/Shanghai"
    assert contract["jobs"] == [
        {
            "job_id": "daily_close",
            "name": "hqa-full-9h-daily-close",
            "schedule": "15,25 8 * * 2-6",
            "script": "hqa-full-9h-daily-close.sh",
            "no_agent": True,
            "deliver": "local",
        },
        {
            "job_id": "freshness",
            "name": "hqa-full-9h-freshness",
            "schedule": "17 */2 * * *",
            "script": "hqa-full-9h-freshness.sh",
            "no_agent": True,
            "deliver": "local",
        },
        {
            "job_id": "weekly",
            "name": "hqa-full-9h-weekly",
            "schedule": "0,10 9 * * 0",
            "script": "hqa-full-9h-weekly.sh",
            "no_agent": True,
            "deliver": "local",
            "replaces_name": "hqa-weekly-review",
        },
        {
            "job_id": "notification_drain",
            "name": "hqa-full-9h-notification-drain",
            "schedule": "7,22,37,52 * * * *",
            "script": "hqa-full-9h-notification-drain.sh",
            "no_agent": True,
            "deliver": "local",
        },
        {
            "job_id": "hermes_compatibility_watch",
            "name": "hqa-hermes-compatibility-watch",
            "schedule": "*/15 * * * *",
            "script": "hqa-hermes-compatibility-watch.sh",
            "no_agent": True,
            "deliver": "local",
        },
        {
            "job_id": "intent_payload_retention",
            "name": "hqa-intent-payload-reconcile",
            "schedule": "11 * * * *",
            "script": "hqa-intent-payload-reconcile.sh",
            "no_agent": True,
            "deliver": "local",
        },
    ]
    assert all("workdir" not in job for job in contract["jobs"])


def test_hermes_compatibility_wrapper_is_a_fixed_no_argument_adapter() -> None:
    body = (
        REPO / "scripts" / "hermes" / "hqa-hermes-compatibility-watch.sh"
    ).read_text(encoding="utf-8")
    assert "cd __HQA_REPO_DIR__" in body
    assert "exec python3 -m hqa.hermes_compatibility_cli check" in body
    assert "--no-agent" in body
    assert "--profile local_agent_v0_2" in body
    assert "--platform-root __HQA_PLATFORM_DIR__" in body
    assert "HQA_INSTALLED_HERMES_SOURCE_DIR=__HQA_HERMES_SOURCE_DIR__" in body
    assert "HQA_HERMES_COMPAT_HERMES_REPO" in body
    assert "HQA_INSTALLED_HQA_REPO=__HQA_REPO_DIR__" in body
    assert "HQA_HERMES_COMPAT_HQA_REPO" in body
    assert "HQA_INSTALLED_HERMES_API_KEY_FILE=__HQA_HERMES_API_KEY_FILE__" in body
    assert "HQA_HERMES_COMPAT_HERMES_API_KEY_FILE" in body
    assert '"$@"' not in body
    assert '"$#" -ne 0' in body


def test_hermes_compatibility_wrapper_rejects_forwarded_arguments(tmp_path) -> None:
    source = REPO / "scripts" / "hermes" / "hqa-hermes-compatibility-watch.sh"
    wrapper = tmp_path / "watch.sh"
    wrapper.write_text(
        source.read_text(encoding="utf-8").replace("__HQA_REPO_DIR__", str(tmp_path)),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    result = subprocess.run(
        ["bash", str(wrapper), "--url", "http://example.invalid"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "accepts no arguments" in result.stderr


def test_hermes_compatibility_wrapper_rejects_unsubstituted_source(
    tmp_path: Path,
) -> None:
    source = REPO / "scripts" / "hermes" / "hqa-hermes-compatibility-watch.sh"
    wrapper = tmp_path / "watch.sh"
    wrapper.write_text(
        source.read_text(encoding="utf-8")
        .replace("__HQA_REPO_DIR__", str(tmp_path))
        .replace("__HQA_PLATFORM_DIR__", str(tmp_path)),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    result = subprocess.run(
        ["bash", str(wrapper)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "unsubstituted Hermes source" in result.stderr


def test_hermes_compatibility_wrapper_rejects_unsubstituted_key_path(
    tmp_path: Path,
) -> None:
    source = REPO / "scripts" / "hermes" / "hqa-hermes-compatibility-watch.sh"
    wrapper = tmp_path / "watch.sh"
    wrapper.write_text(
        source.read_text(encoding="utf-8")
        .replace("__HQA_REPO_DIR__", str(tmp_path))
        .replace("__HQA_PLATFORM_DIR__", str(tmp_path))
        .replace("__HQA_HERMES_SOURCE_DIR__", str(tmp_path)),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    result = subprocess.run(
        ["bash", str(wrapper)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "unsubstituted API-key path" in result.stderr


# --- D-25 read-only gate wrapper -------------------------------------------

READONLY_SRC = REPO / "scripts" / "hermes" / "hqa-quant-readonly.sh"
PAPER_GATE_SHOW_SRC = REPO / "scripts" / "hermes" / "hqa-paper-gate-show.py"
PAPER_SOURCE_STAGE_SRC = REPO / "scripts" / "hermes" / "hqa-paper-source-stage.py"


def _build_paper_source_stager(
    tmp_path: Path,
) -> tuple[Path, Path]:
    repo = tmp_path / "release-hqa"
    repo.mkdir(mode=0o700)
    (repo / ".gitignore").write_text(
        "data/_runtime/*\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["/usr/bin/git", "init", "-q", str(repo)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["/usr/bin/git", "-C", str(repo), "add", ".gitignore"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repo),
            "-c",
            "user.name=HQA Test",
            "-c",
            "user.email=hqa-test@example.invalid",
            "commit",
            "-qm",
            "test fixture",
        ],
        check=True,
        capture_output=True,
    )
    launcher = tmp_path / "hqa-paper-source-stage.py"
    launcher.write_text(
        PAPER_SOURCE_STAGE_SRC.read_text(encoding="utf-8").replace(
            "__HQA_REPO_DIR__",
            str(repo),
        ),
        encoding="utf-8",
    )
    launcher.chmod(0o700)
    return launcher, repo


def _run_paper_source_stager(
    launcher: Path,
    source: bytes,
    *arguments: str,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(launcher), *arguments],
        input=source,
        capture_output=True,
        timeout=10,
    )


def test_paper_source_stage_content_addresses_private_ignored_source(
    tmp_path: Path,
) -> None:
    launcher, repo = _build_paper_source_stager(tmp_path)
    source = (
        b"from quant_system.factors.base import BaseFactor\n"
        b"\n"
        b"class PaperFactor(BaseFactor):\n"
        b"    factor_id = 'paper_factor_v3'\n"
    )

    result = _run_paper_source_stager(launcher, source)

    assert result.returncode == 0, result.stderr.decode()
    assert result.stderr == b""
    receipt = json.loads(result.stdout)
    assert set(receipt) == {
        "source_file_ref",
        "reviewed_source_sha256",
    }
    digest = receipt["reviewed_source_sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    staged = Path(receipt["source_file_ref"])
    assert staged == (
        repo / "data" / "_runtime" / "factor-gate1" / "sources" / f"source-{digest}.py"
    )
    assert staged.read_bytes() == source
    assert staged.stat().st_mode & 0o777 == 0o600
    assert staged.parent.stat().st_mode & 0o777 == 0o700
    ignored = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), "check-ignore", "-q", str(staged)],
        capture_output=True,
    )
    assert ignored.returncode == 0
    status = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
    )
    assert status.stdout == b""


def test_paper_source_stage_replays_exact_source_without_replacing_it(
    tmp_path: Path,
) -> None:
    launcher, _repo = _build_paper_source_stager(tmp_path)
    source = b"FACTOR_ID = 'same-reviewed-source'\n"

    first = _run_paper_source_stager(launcher, source)
    assert first.returncode == 0, first.stderr.decode()
    first_receipt = json.loads(first.stdout)
    staged = Path(first_receipt["source_file_ref"])
    first_inode = staged.stat().st_ino

    second = _run_paper_source_stager(launcher, source)

    assert second.returncode == 0, second.stderr.decode()
    assert second.stderr == b""
    assert second.stdout == first.stdout
    assert staged.stat().st_ino == first_inode
    assert staged.read_bytes() == source
    assert list(staged.parent.glob(".*.tmp")) == []


def test_paper_source_stage_concurrent_replay_publishes_one_complete_file(
    tmp_path: Path,
) -> None:
    launcher, _repo = _build_paper_source_stager(tmp_path)
    source = b"FACTOR_ID = 'concurrent-reviewed-source'\n"
    processes = [
        subprocess.Popen(
            [str(launcher)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(6)
    ]
    for process in processes:
        assert process.stdin is not None
        process.stdin.write(source)
        process.stdin.close()

    results: list[tuple[int, bytes, bytes]] = []
    for process in processes:
        assert process.stdout is not None
        assert process.stderr is not None
        returncode = process.wait(timeout=10)
        results.append((returncode, process.stdout.read(), process.stderr.read()))

    assert {returncode for returncode, _stdout, _stderr in results} == {0}
    assert {stderr for _returncode, _stdout, stderr in results} == {b""}
    receipts = {stdout for _returncode, stdout, _stderr in results}
    assert len(receipts) == 1
    receipt = json.loads(receipts.pop())
    staged = Path(receipt["source_file_ref"])
    assert staged.read_bytes() == source
    assert staged.stat().st_nlink == 1
    assert sorted(path.name for path in staged.parent.iterdir()) == [staged.name]


@pytest.mark.parametrize(
    ("source", "expected_error"),
    [
        (b"", b"paper_source_stage_error=source_empty\n"),
        (b"\xff\n", b"paper_source_stage_error=source_not_utf8\n"),
        (b"def broken(:\n", b"paper_source_stage_error=source_not_python\n"),
        (
            b"value = 'embedded\\x00'\x00\n",
            b"paper_source_stage_error=source_not_python\n",
        ),
    ],
)
def test_paper_source_stage_rejects_non_python_input_without_receipt(
    tmp_path: Path,
    source: bytes,
    expected_error: bytes,
) -> None:
    launcher, repo = _build_paper_source_stager(tmp_path)

    result = _run_paper_source_stager(launcher, source)

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == expected_error
    assert not (repo / "data").exists()


def test_paper_source_stage_rejects_arguments_without_reading_source(
    tmp_path: Path,
) -> None:
    launcher, repo = _build_paper_source_stager(tmp_path)

    result = _run_paper_source_stager(
        launcher,
        b"SECRET_SOURCE = True\n",
        "--source",
        "do-not-accept.py",
    )

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"paper_source_stage_error=arguments_not_allowed\n"
    assert not (repo / "data").exists()


def test_paper_source_stage_rejects_source_larger_than_256_kib(
    tmp_path: Path,
) -> None:
    launcher, repo = _build_paper_source_stager(tmp_path)
    source = b"#" * (256 * 1024 + 1)

    result = _run_paper_source_stager(launcher, source)

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"paper_source_stage_error=source_too_large\n"
    assert not (repo / "data").exists()


def test_paper_source_stage_rejects_symlink_at_content_address(
    tmp_path: Path,
) -> None:
    launcher, repo = _build_paper_source_stager(tmp_path)
    source = b"FACTOR_ID = 'must-not-follow-link'\n"
    digest = hashlib.sha256(source).hexdigest()
    sources = repo / "data" / "_runtime" / "factor-gate1" / "sources"
    sources.mkdir(parents=True, mode=0o700)
    (sources.parent).chmod(0o700)
    sources.chmod(0o700)
    victim = tmp_path / "victim.py"
    victim.write_bytes(b"ORIGINAL = True\n")
    staged = sources / f"source-{digest}.py"
    staged.symlink_to(victim)

    result = _run_paper_source_stager(launcher, source)

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"paper_source_stage_error=source_conflict\n"
    assert victim.read_bytes() == b"ORIGINAL = True\n"
    assert staged.is_symlink()


def test_paper_source_stage_rejects_non_private_sources_directory(
    tmp_path: Path,
) -> None:
    launcher, repo = _build_paper_source_stager(tmp_path)
    gate = repo / "data" / "_runtime" / "factor-gate1"
    gate.mkdir(parents=True, mode=0o700)
    gate.chmod(0o700)
    sources = gate / "sources"
    sources.mkdir(mode=0o755)
    sources.chmod(0o755)

    result = _run_paper_source_stager(launcher, b"FACTOR_ID = 'unsafe-dir'\n")

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"paper_source_stage_error=runtime_directory_unsafe\n"
    assert list(sources.iterdir()) == []


_TEST_DATABASE_URL = "postgresql://unit:secret@127.0.0.1:5432/quantplatform"
_EXACT_GATE_ARGS = [
    "hermes",
    "paper-gate",
    "show",
    "--gate-id",
    "paper-gate-1",
    "--workspace-id",
    "ws-local-main",
    "--platform-session-id",
    "platform-session-1",
]


def _build_gate(
    tmp_path,
    *,
    runtime_env: str | None = None,
    runtime_env_mode: int = 0o600,
):
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
        'if [ "${1:-}" = hermes ] && [ "${2:-}" = paper-gate ]; then\n'
        "  printf 'DBENV|%s|%s|%s|%s|%s\\n' "
        '"${QS_DATABASE_ENABLED-unset}" '
        '"${QS_DATABASE_AUTO_MIGRATE-unset}" '
        '"${QS_DATABASE_CONNECT_TIMEOUT_SECONDS-unset}" '
        '"${QS_DATABASE_URL-unset}" '
        '"${QS_DATABASE_SECRET_SENTINEL-unset}"\n'
        '  if [ "${3:-}" = attest-run ]; then\n'
        "    printf 'HERMESENV|%s|%s|%s|%s|%s|%s\\n' "
        '"${QS_HERMES_GATEWAY_ENABLED-unset}" '
        '"${QS_HERMES_GATEWAY_BASE_URL-unset}" '
        '"${QS_HERMES_GATEWAY_API_KEY_FILE-unset}" '
        '"${OPENAI_API_KEY-unset}" '
        '"${FUTU_API_SECRET-unset}" '
        '"${QS_AGENT_V02_CANDIDATE_ENABLED-unset}"\n'
        "  fi\n"
        "  input=''\n  IFS= read -r input || true\n"
        '  [ -z "$input" ] || printf \'STDIN|%s\\n\' "$input"\n'
        'elif [ "${1:-}" = hermes ] && [ "${2:-}" = vertical-a ]; then\n'
        "  printf 'VERTICALENV|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\\n' "
        '"${QS_DATABASE_ENABLED-unset}" '
        '"${QS_DATABASE_AUTO_MIGRATE-unset}" '
        '"${QS_AGENT_V02_CANDIDATE_ENABLED-unset}" '
        '"${QS_AGENT_V02_RELEASE_WORKSPACE_ID-unset}" '
        '"${QS_LOCAL_MUTATION_ENABLED-unset}" '
        '"${QS_DRY_RUN-unset}" '
        '"${QS_PAPER_TRADING-unset}" '
        '"${QS_LIVE_TRADING_ENABLED-unset}" '
        '"${QS_KILL_SWITCH-unset}" '
        '"${QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED-unset}" '
        '"${HERMES_PLATFORM_COMMAND_ID-unset}" '
        '"${HERMES_PLATFORM_SESSION_ID-unset}" '
        '"${HERMES_PLATFORM_RUN_ID-unset}" '
        '"${HERMES_PLATFORM_MANAGED_SESSION_ID-unset}" '
        '"${OPENAI_API_KEY-unset}" '
        '"${FUTU_API_SECRET-unset}"\n'
        "  input=''\n  IFS= read -r input || true\n"
        '  [ -z "$input" ] || printf \'STDIN|%s\\n\' "$input"\n'
        "fi\n"
    )
    stub.chmod(0o755)
    env_file = platform / "data" / "_runtime" / "agent-v0.2-backend.env"
    env_file.parent.mkdir(parents=True)
    if runtime_env is None:
        runtime_env = (
            "QS_ENVIRONMENT=local\n"
            "QS_DATABASE_ENABLED=true\n"
            f'QS_DATABASE_URL="{_TEST_DATABASE_URL}"\n'
            "QS_DATABASE_CONNECT_TIMEOUT_SECONDS=7\n"
            "QS_DATABASE_AUTO_MIGRATE=false\n"
            "QS_KILL_SWITCH=true\n"
        )
    env_file.write_text(runtime_env, encoding="utf-8")
    env_file.chmod(runtime_env_mode)
    launcher = tmp_path / "hqa-paper-gate-show.py"
    launcher.write_text(
        PAPER_GATE_SHOW_SRC.read_text(encoding="utf-8").replace(
            "__HQA_PLATFORM_DIR__", str(platform)
        ),
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    body = READONLY_SRC.read_text().replace("__HQA_PLATFORM_DIR__", str(platform))
    gate = tmp_path / "hqa-quant-readonly.sh"
    gate.write_text(body)
    gate.chmod(0o755)
    return gate


def _run_gate(tmp_path, args, *, env=None):
    gate = _build_gate(tmp_path)
    return subprocess.run(
        ["bash", str(gate), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


@pytest.mark.parametrize(
    "args, expected_argv",
    [
        (["doctor"], "ARGV|doctor"),
        (["config", "show"], "ARGV|config|show"),
        (["factor", "list"], "ARGV|factor|list"),
        (
            [
                "data",
                "prices",
                "--symbol",
                "AAPL",
                "--start",
                "2026-01-01",
                "--end",
                "2026-07-10",
                "--provider",
                "futu",
            ],
            "ARGV|data|prices|--symbol|AAPL|--start|2026-01-01|--end|2026-07-10|--provider|futu",
        ),
        (
            ["paper", "account-show", "--account", "main", "--format", "json"],
            "ARGV|paper|account-show|--account|main|--format|json",
        ),
        (
            [
                "hermes",
                "paper-gate",
                "show",
                "--gate-id",
                "paper-gate-1",
                "--workspace-id",
                "ws-local-main",
                "--platform-session-id",
                "platform-session-1",
            ],
            (
                "ARGV|hermes|paper-gate|show\n"
                "DBENV|true|false|7|"
                f"{_TEST_DATABASE_URL}|unset\n"
                'STDIN|{"gate_id":"paper-gate-1",'
                '"platform_session_id":"platform-session-1",'
                '"workspace_id":"ws-local-main"}'
            ),
        ),
    ],
)
def test_gate_allows_readonly_commands(tmp_path, args, expected_argv):
    result = _run_gate(tmp_path, args)
    assert result.returncode == 0, result.stderr
    # Argv is forwarded verbatim (trailing flags preserved) to the platform CLI.
    assert result.stdout.strip() == expected_argv


def test_exact_gate_allows_context_colons_and_200_character_boundary(
    tmp_path,
) -> None:
    workspace_id = "workspace:" + ("w" * 190)
    platform_session_id = "session:" + ("s" * 192)
    assert len(workspace_id) == 200
    assert len(platform_session_id) == 200

    result = _run_gate(
        tmp_path,
        [
            "hermes",
            "paper-gate",
            "show",
            "--gate-id",
            "paper-gate-1",
            "--workspace-id",
            workspace_id,
            "--platform-session-id",
            platform_session_id,
        ],
    )

    assert result.returncode == 0, result.stderr
    assert f'"workspace_id":"{workspace_id}"' in result.stdout
    assert f'"platform_session_id":"{platform_session_id}"' in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        [],  # empty → refused
        ["paper", "rebalance"],  # write: mutates account
        ["paper", "run-sample"],  # write: runs a loop
        ["agent", "review", "--approve"],  # write: approval lock
        ["agent", "list-candidates"],  # generic evidence bypasses HQA Gate 1
        ["agent", "propose-factor"],  # write: creates candidate file
        ["hermes", "paper-gate", "register"],  # write: opens a Gate
        ["hermes", "paper-gate", "list"],  # list-and-substitute is forbidden
        ["hermes", "paper-gate", "show"],  # missing exact Gate id
        [
            "hermes",
            "paper-gate",
            "show",
            "--gate-id",
            "paper-gate-1",
        ],  # missing exact workspace/session selectors
        [
            "hermes",
            "paper-gate",
            "show",
            "--gate-id",
            "gate;touch-pwned",
            "--workspace-id",
            "ws-local-main",
            "--platform-session-id",
            "platform-session-1",
        ],
        [
            "hermes",
            "paper-gate",
            "show",
            "--gate-id",
            "paper-gate-1",
            "--workspace-id",
            "workspace;touch-pwned",
            "--platform-session-id",
            "platform-session-1",
        ],
        [
            "hermes",
            "paper-gate",
            "show",
            "--gate-id",
            "paper-gate-1",
            "--platform-session-id",
            "platform-session-1",
            "--workspace-id",
            "ws-local-main",
        ],
        [
            "hermes",
            "paper-gate",
            "show",
            "--gate-id",
            "paper-gate-1",
            "--workspace-id",
            "ws-local-main",
            "--platform-session-id",
            "platform-session-1",
            "extra",
        ],
        [
            "hermes",
            "paper-gate",
            "show",
            "--gate-id",
            "paper-gate-1",
            "--workspace-id",
            "w" * 201,
            "--platform-session-id",
            "platform-session-1",
        ],
        [
            "hermes",
            "paper-gate",
            "show",
            "--gate-id",
            "paper-gate-1",
            "--workspace-id",
            "ws-local-main",
            "--platform-session-id",
            "s" * 201,
        ],
        ["options", "daily-scan"],  # write: scan snapshot (audit F4)
        ["options", "daily-scan", "--top", "20"],
        ["options", "buyside-screen"],  # write: scan side-effect
        ["options", "daily-task"],  # refreshes inputs (side effect)
        ["options", "prune-cache", "--delete"],  # deletes cache
        ["data", "ingest-tiingo"],  # write: downloads + stores
        ["data", "ingest-sample"],  # write: generates + stores
        ["backtest", "run-sample"],  # compute/write
        ["config"],  # bare group, not the `config show` leaf
        ["options"],  # bare group
        ["doctor; rm -rf /"],  # injection as single token, no match
        ["serve"],  # starts a server
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
    # Audit F4: options daily-scan / buyside-screen must NOT be allowlisted.
    body = READONLY_SRC.read_text()
    for entry in (
        '"doctor"',
        '"config show"',
        '"data prices"',
        '"factor list"',
        '"paper account-show"',
        '"hermes paper-gate show"',
    ):
        assert entry in body
    assert '"options daily-scan"' not in body
    assert '"options buyside-screen"' not in body
    assert '"agent list-candidates"' not in body


def _run_built_gate(gate: Path, *, env: dict[str, str] | None = None):
    return subprocess.run(
        ["bash", str(gate), *_EXACT_GATE_ARGS],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def test_exact_gate_loader_scrubs_inherited_database_env_and_forces_rails(
    tmp_path,
) -> None:
    gate = _build_gate(tmp_path)
    inherited = dict(
        os.environ,
        QS_DATABASE_AUTO_MIGRATE="true",
        QS_DATABASE_CONNECT_TIMEOUT_SECONDS="999",
        QS_DATABASE_ENABLED="false",
        QS_DATABASE_SECRET_SENTINEL="must-not-cross",
        QS_DATABASE_URL="postgresql://attacker:wrong@127.0.0.1:1/wrong",
    )

    result = _run_built_gate(gate, env=inherited)

    assert result.returncode == 0, result.stderr
    assert f"DBENV|true|false|7|{_TEST_DATABASE_URL}|unset" in result.stdout


@pytest.mark.parametrize(
    "operation",
    ("attest-run", "register", "show", "complete", "list"),
)
def test_fixed_runtime_port_forwards_only_exact_paper_gate_operations(
    tmp_path,
    operation,
) -> None:
    _build_gate(
        tmp_path,
        runtime_env=(
            "QS_DATABASE_ENABLED=true\n"
            f"QS_DATABASE_URL={_TEST_DATABASE_URL}\n"
            "QS_DATABASE_AUTO_MIGRATE=false\n"
            "QS_HERMES_GATEWAY_ENABLED=true\n"
            "QS_HERMES_GATEWAY_BASE_URL=http://127.0.0.1:8642\n"
            "QS_HERMES_GATEWAY_API_KEY_FILE=/private/hermes-api-key\n"
            "QS_AGENT_V02_CANDIDATE_ENABLED=true\n"
        ),
    )
    launcher = tmp_path / "hqa-paper-gate-show.py"
    inherited = dict(
        os.environ,
        OPENAI_API_KEY="must-not-cross",
        FUTU_API_SECRET="must-not-cross",
        QS_AGENT_V02_CANDIDATE_ENABLED="attacker-value",
        QS_DATABASE_URL="postgresql://attacker:wrong@127.0.0.1:1/wrong",
        QS_HERMES_GATEWAY_BASE_URL="http://attacker.invalid",
    )
    request = '{"operation":"fixed-runtime-port-test"}\n'

    result = subprocess.run(
        [str(launcher), "hermes", "paper-gate", operation],
        input=request,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=inherited,
    )

    assert result.returncode == 0, result.stderr
    assert f"ARGV|hermes|paper-gate|{operation}" in result.stdout
    assert f"DBENV|true|false|unset|{_TEST_DATABASE_URL}|unset" in result.stdout
    if operation == "attest-run":
        assert (
            "HERMESENV|true|http://127.0.0.1:8642|"
            "/private/hermes-api-key|unset|unset|unset"
        ) in result.stdout
    else:
        assert "HERMESENV" not in result.stdout
    assert "STDIN|" + request.strip() in result.stdout
    assert "must-not-cross" not in result.stdout + result.stderr
    assert "attacker.invalid" not in result.stdout + result.stderr


def test_fixed_runtime_port_vertical_a_loads_only_bounded_backend_profile(
    tmp_path,
) -> None:
    _build_gate(
        tmp_path,
        runtime_env=(
            "QS_ENVIRONMENT=local\n"
            "QS_DATABASE_ENABLED=true\n"
            f"QS_DATABASE_URL={_TEST_DATABASE_URL}\n"
            "QS_DATABASE_AUTO_MIGRATE=false\n"
            "QS_HERMES_GATEWAY_ENABLED=true\n"
            "QS_HERMES_GATEWAY_BASE_URL=http://127.0.0.1:8642\n"
            "QS_AGENT_V02_CANDIDATE_ENABLED=true\n"
            "QS_AGENT_V02_RELEASE_WORKSPACE_ID=ws-local-main\n"
            "QS_LOCAL_MUTATION_ENABLED=true\n"
            "QS_DRY_RUN=false\n"
            "QS_PAPER_TRADING=false\n"
            "QS_LIVE_TRADING_ENABLED=true\n"
            "QS_KILL_SWITCH=false\n"
            "QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED=true\n"
            "FUTU_API_SECRET=backend-provider-secret-must-not-load\n"
        ),
    )
    launcher = tmp_path / "hqa-paper-gate-show.py"
    inherited = dict(
        os.environ,
        HERMES_PLATFORM_COMMAND_ID="command-one",
        HERMES_PLATFORM_SESSION_ID="platform-session-one",
        HERMES_PLATFORM_RUN_ID="run-one",
        HERMES_PLATFORM_MANAGED_SESSION_ID="managed-session-one",
        HERMES_PLATFORM_UNRELATED="must-not-cross",
        OPENAI_API_KEY="must-not-cross",
        FUTU_API_SECRET="must-not-cross",
    )
    request = (
        '{"ticker":"AAPL","expiry":"2026-08-21","strike":220.0,"goal_note":"bounded"}\n'
    )

    result = subprocess.run(
        [str(launcher), "hermes", "vertical-a", "execute-from-hermes"],
        input=request,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=inherited,
    )

    assert result.returncode == 0, result.stderr
    assert "ARGV|hermes|vertical-a|execute-from-hermes" in result.stdout
    assert (
        "VERTICALENV|true|false|true|ws-local-main|true|"
        "true|true|false|true|false|command-one|platform-session-one|"
        "run-one|managed-session-one|unset|unset"
    ) in result.stdout
    assert "STDIN|" + request.strip() in result.stdout
    assert "must-not-cross" not in result.stdout + result.stderr
    assert "backend-provider-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["hermes", "paper-gate", "delete"],
        ["hermes", "paper-gate", "show", "extra"],
        ["hermes", "vertical-a", "execute-from-hermes", "extra"],
        ["hermes", "vertical-b", "execute-from-hermes"],
    ],
)
def test_fixed_runtime_port_refuses_non_exact_argv_without_exec(
    tmp_path,
    arguments,
) -> None:
    _build_gate(tmp_path)
    launcher = tmp_path / "hqa-paper-gate-show.py"

    result = subprocess.run(
        [str(launcher), *arguments],
        input="{}\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 2
    assert "REFUSED: invalid fixed runtime port invocation" in result.stderr
    assert "ARGV" not in result.stdout


def test_fixed_runtime_port_rejects_oversized_stdin_before_exec(tmp_path) -> None:
    _build_gate(tmp_path)
    launcher = tmp_path / "hqa-paper-gate-show.py"

    result = subprocess.run(
        [str(launcher), "hermes", "paper-gate", "register"],
        input="x" * (256 * 1024 + 1),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 78
    assert "paper_gate_env_error=request_too_large" in result.stderr
    assert "ARGV" not in result.stdout


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing", "runtime_env_missing"),
        ("mode", "runtime_env_mode_must_be_600"),
        ("symlink", "runtime_env_not_regular"),
        ("malformed", "runtime_env_malformed"),
        ("missing_url", "database_url_missing"),
        ("auto_migrate", "database_auto_migrate_forbidden"),
    ],
)
def test_exact_gate_loader_fails_closed_for_untrusted_runtime_env(
    tmp_path,
    mutation,
    expected_error,
) -> None:
    gate = _build_gate(tmp_path)
    env_file = tmp_path / "platform" / "data" / "_runtime" / "agent-v0.2-backend.env"
    if mutation == "missing":
        env_file.unlink()
    elif mutation == "mode":
        env_file.chmod(0o640)
    elif mutation == "symlink":
        victim = tmp_path / "runtime-env-victim"
        victim.write_text(
            f"QS_DATABASE_ENABLED=true\nQS_DATABASE_URL={_TEST_DATABASE_URL}\n",
            encoding="utf-8",
        )
        victim.chmod(0o600)
        env_file.unlink()
        env_file.symlink_to(victim)
    elif mutation == "malformed":
        env_file.write_text(
            "QS_DATABASE_ENABLED=true\nthis is not dotenv\n",
            encoding="utf-8",
        )
    elif mutation == "missing_url":
        env_file.write_text("QS_DATABASE_ENABLED=true\n", encoding="utf-8")
    elif mutation == "auto_migrate":
        env_file.write_text(
            "QS_DATABASE_ENABLED=true\n"
            f"QS_DATABASE_URL={_TEST_DATABASE_URL}\n"
            "QS_DATABASE_AUTO_MIGRATE=true\n",
            encoding="utf-8",
        )
    result = _run_built_gate(gate)

    assert result.returncode == 78
    assert f"paper_gate_env_error={expected_error}" in result.stderr
    assert "ARGV" not in result.stdout
    assert _TEST_DATABASE_URL not in result.stderr


def test_exact_gate_loader_never_evaluates_runtime_shell_syntax(tmp_path) -> None:
    sentinel = tmp_path / "shell-code-executed"
    gate = _build_gate(
        tmp_path,
        runtime_env=(
            "QS_DATABASE_ENABLED=true\n"
            f'IGNORED_UNKNOWN_KEY="$(touch {sentinel})"\n'
            f'QS_DATABASE_URL="$(touch {sentinel})"\n'
            "QS_DATABASE_AUTO_MIGRATE=false\n"
        ),
    )

    result = _run_built_gate(gate)

    assert result.returncode == 78
    assert "paper_gate_env_error=database_url_shell_syntax_forbidden" in result.stderr
    assert not sentinel.exists()
    assert "ARGV" not in result.stdout


def test_install_deploys_private_exact_gate_env_launcher(tmp_path) -> None:
    scripts_dest = _install(tmp_path)
    launcher = scripts_dest / "hqa-paper-gate-show.py"

    assert launcher.is_file()
    assert not launcher.is_symlink()
    assert launcher.stat().st_mode & 0o777 == 0o700
    body = launcher.read_text(encoding="utf-8")
    assert "__HQA_PLATFORM_DIR__" not in body
    assert "source " not in body
    assert "QS_DATABASE_AUTO_MIGRATE" in body
    assert "agent-v0.2-backend.env" in body
    assert "hqa-paper-gate-show.py" in (
        scripts_dest / "hqa-quant-readonly.sh"
    ).read_text(encoding="utf-8")


def test_install_deploys_private_paper_source_stager(tmp_path) -> None:
    scripts_dest = _install(tmp_path)
    launcher = scripts_dest / "hqa-paper-source-stage.py"

    assert launcher.is_file()
    assert not launcher.is_symlink()
    assert launcher.stat().st_mode & 0o777 == 0o700
    body = launcher.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/python3\n")
    assert "__HQA_REPO_DIR__" not in body
    assert "__HQA_PLATFORM_DIR__" not in body
    assert "__HERMES_SCRIPTS_DIR__" not in body
    assert str(REPO) in body


# --- D-25 HQA skill card ----------------------------------------------------

SKILL_SRC = REPO / "skills" / "hermes" / "hqa-quant" / "SKILL.md"
# The read-write CLIs the card documents; every `-m hqa.<mod>` template must
# name one of these (guards against invented modules).
_WRITE_PATH_MODULES = (
    "hqa.factor_repro_cli",
    "hqa.paper_research_cli",
    "hqa.review_cli",
)
# Platform read-only subcommands baked into the gate allowlist (Task L1). Any
# gate template in the card must forward one of these — no invented commands.
_READONLY_SUBCOMMANDS = (
    "doctor",
    "config show",
    "data prices",
    "factor list",
    "paper account-show",
    "hermes paper-gate show",
)


def test_install_deploys_skill_card_with_substitution(tmp_path):
    # install.sh must also deploy skills/hermes/<name>/SKILL.md to
    # $HERMES_HOME/skills/<name>/SKILL.md with the repo/platform placeholders
    # replaced (same seam as the script wrappers).
    scripts_dest = _install(tmp_path)
    skill = scripts_dest.parent / "skills" / "hqa-quant" / "SKILL.md"
    assert skill.is_file(), "SKILL.md not deployed under $HERMES_HOME/skills/hqa-quant/"
    body = skill.read_text(encoding="utf-8")
    assert "__HQA_REPO_DIR__" not in body
    assert "__HQA_PLATFORM_DIR__" not in body
    # The gate wrapper is referenced by absolute deployed path, not placeholder.
    assert str(scripts_dest / "hqa-quant-readonly.sh") in body
    assert str(scripts_dest / "hqa-portfolio-risk.sh") in body
    assert str(scripts_dest / "hqa-prediction.sh") in body
    assert str(scripts_dest / "hqa-opportunities.sh") in body
    assert str(scripts_dest / "hqa-factor-repro.sh") in body


def test_install_deploys_v3_research_authority_skill_and_wrapper(tmp_path) -> None:
    scripts_dest = _install(tmp_path)
    wrapper = scripts_dest / "hqa-research-task.sh"
    skill = scripts_dest.parent / "skills" / "hqa-research-task" / "SKILL.md"

    assert wrapper.is_file()
    assert wrapper.stat().st_mode & 0o111
    assert skill.is_file()
    body = skill.read_text(encoding="utf-8")
    assert str(wrapper) in body
    assert "__HERMES_SCRIPTS_DIR__" not in body
    assert "__HQA_REPO_DIR__" not in body


def test_installed_wrapper_freezes_canonical_v3_authority_environment(
    tmp_path,
) -> None:
    scripts_dest = _install(tmp_path)
    wrapper = scripts_dest / "hqa-research-task.sh"
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    stub = stub_dir / "python3"
    stub.write_text(
        "#!/bin/bash\n"
        "printf '%s\\n' \"$HQA_INTENT_PAYLOAD_DIR\"\n"
        "printf '%s\\n' \"$HQA_WORKFLOW_AUTHORITY_DIR\"\n"
        "printf '%s\\n' \"$HQA_INTENT_PAYLOAD_CRYPTO_HELPER\"\n"
        "printf '%s\\n' \"$HQA_WORKFLOW_OWNER_USER_ID\"\n",
        encoding="utf-8",
    )
    stub.chmod(0o700)

    result = subprocess.run(
        [str(wrapper), "audit"],
        env=dict(
            os.environ,
            PATH=f"{stub_dir}:/usr/bin:/bin",
            HQA_INTENT_PAYLOAD_DIR="/tmp/escaped-intent",
            HQA_WORKFLOW_AUTHORITY_DIR="/tmp/escaped-workflow",
            HQA_INTENT_PAYLOAD_CRYPTO_HELPER="/tmp/escaped-helper",
            HQA_WORKFLOW_OWNER_USER_ID="escaped-owner",
        ),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(REPO / "data" / "_runtime" / "intent-payloads-v2"),
        str(REPO / "data" / "_runtime" / "workflow-authority-v2"),
        str(scripts_dest.parent / "bin" / "hqa-intent-payload-crypto"),
        "local-owner-v1",
    ]


def test_skill_card_frontmatter_mirrors_hermes_contract():
    body = SKILL_SRC.read_text(encoding="utf-8")
    assert body.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    front = body.split("---", 2)[1]
    assert re.search(r"^name:\s*hqa-quant\s*$", front, re.M)
    assert re.search(r"^description:\s*\S", front, re.M)
    assert re.search(r"^version:\s*1\.\d+\.\d+\s*$", front, re.M)
    # platforms must be a list containing macos.
    assert re.search(r"^platforms:\s*\[.*macos.*\]\s*$", front, re.M)
    # metadata.hermes.tags present with the quant/trading/hqa tags.
    assert re.search(r"^\s*hermes:\s*$", front, re.M)
    assert re.search(r"tags:\s*\[.*\bhqa\b.*\]", front)


def test_installed_skill_documents_exact_gate2_cas_command(tmp_path) -> None:
    scripts_dest = _install(tmp_path)
    body = (scripts_dest.parent / "skills" / "hqa-quant" / "SKILL.md").read_text()
    assert "version: 1.18.4" in body
    assert "--expected-source-digest <reviewed-source-sha256>" in body
    assert '--confirmation-note "<formula-and-translation-review>"' in body
    assert (
        "approve --candidate-id <id> --expected-digest <sha256> "
        '--expected-status pending --note "<translation-review>"'
    ) in body
    assert "never refetch" in body.lower()
    # Source card must match the installed card for the Gate 2 surface.
    source = SKILL_SRC.read_text(encoding="utf-8")
    assert "version: 1.18.4" in source
    assert (
        "approve --candidate-id <id> --expected-digest <sha256> "
        '--expected-status pending --note "<translation-review>"'
    ) in source
    assert "never refetch" in source.lower()


def test_skill_uses_exact_candidate_backtest_and_unambiguous_platform_commands(
    tmp_path,
) -> None:
    source = SKILL_SRC.read_text(encoding="utf-8")
    assert "version: 1.18.4" in source
    assert ("backtest --candidate-id <id> --expected-digest <sha256>") in source
    assert "backtest --factor-id" not in source
    for operation in ("propose", "list", "detail", "approve", "backtest", "promote"):
        assert f"__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh {operation}" in source
    assert "python3 -m hqa.factor_repro_cli" not in source
    assert "--final-backtest-receipt <backtest-id>" in source
    assert (
        "__HQA_PLATFORM_DIR__/ai-quant/bin/quant-system agent promote-candidate"
        not in source
    )

    scripts_dest = _install(tmp_path)
    installed = (scripts_dest.parent / "skills" / "hqa-quant" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "version: 1.18.4" in installed
    for operation in ("propose", "list", "detail", "approve", "backtest", "promote"):
        assert f"{scripts_dest / 'hqa-factor-repro.sh'} {operation}" in installed
    assert "python3 -m hqa.factor_repro_cli" not in installed
    assert "__HQA_PLATFORM_DIR__" not in installed


def test_skill_routes_paper_research_through_verified_reproducibility_intake(
    tmp_path,
) -> None:
    def assert_intake_contract(body: str) -> None:
        front = body.split("---", 2)[1].lower()
        contract = " ".join(body.split())
        for trigger in (
            "paper",
            "literature",
            "factor research",
            "论文",
            "文献",
            "因子",
        ):
            assert trigger in front
        assert "version: 1.18.4" in contract

        search_at = contract.index("call the actual `web_search` tool")
        extract_at = contract.index("call `web_extract`")
        decision_at = contract.index("Make the reproducibility decision")
        workflow_at = contract.index("Only after this intake passes")
        assert search_at < extract_at < decision_at < workflow_at

        assert "canonical title plus a DOI or arXiv identifier" in contract
        assert "primary publisher, DOI, or arXiv source" in contract
        assert "An exact unique primary-source match is verified" in contract
        assert "If search fails" in contract
        assert "report the intake as `BLOCKED` and stop" in contract
        assert "requires successfully extracted usable full-text bytes" in contract
        assert "abstract-only response is insufficient" in contract
        assert (
            "report `BLOCKED` and stop before making a reproducibility decision"
            in contract
        )
        assert "formula or deterministic rules" in contract
        assert "input/data definitions" in contract
        assert "honestly summarize what the paper does and stop" in contract
        assert (
            "Do not call `prepare-intent`, create `research_start`, or run any "
            "backtest"
        ) in contract
        assert (
            "ask the user for an explicit non-empty ordered `universe`" in contract
        )
        assert (
            "Never guess, infer, sort, deduplicate, or substitute that universe"
            in contract
        )
        assert "Never install PDF dependencies into system/global Python" in contract
        assert "`uv pip install --system`" in contract
        assert (
            "task-scoped temporary directory with its own isolated `.venv`" in contract
        )

    source = SKILL_SRC.read_text(encoding="utf-8")
    assert_intake_contract(source)

    scripts_dest = _install(tmp_path)
    installed = (scripts_dest.parent / "skills" / "hqa-quant" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert_intake_contract(installed)


def test_skill_routes_natural_language_papers_through_two_attempt_coordinator(
    tmp_path,
) -> None:
    source = SKILL_SRC.read_text(encoding="utf-8")
    assert "__HERMES_SCRIPTS_DIR__/hqa-paper-research.sh <operation>" in source
    for operation in (
        "prepare-intent",
        "start-plan",
        "confirm-plan",
        "open-gate1",
        "open-gate2",
        "open-gate3",
        "complete-after-human-commit",
    ):
        assert f"`{operation}`" in source
    assert "Attempt 1" in source
    assert "Attempt 2" in source
    assert "--provider futu --final" in source
    assert "creates zero orders" in source
    assert "must not type or run that commit" in source
    assert "paper_research_platform_outcome_unknown" in source
    assert "**next managed Hermes turn**" in source
    assert "subject_command_id" in source
    assert "subject_hermes_run_id" in source
    assert "`research_start`" in source
    assert "`research_continue`" in source
    assert "paper_title:<exact title>" in source
    assert "universe:[<ordered symbols>]" in source
    assert "research_claim_digest" in source
    assert "must not send `paper_title` or `universe` again" in source
    assert "research-claim:sha256:<research_claim_digest>" in source
    assert "claimless Task can never acquire a claim on a later Attempt" in source
    assert "produce a different digest at `prepare-intent`" in source
    assert "verbatim" in source and "current user message" in source
    assert "never argv, environment" in source
    assert "stdout never contains" in source
    assert "does not create a Task/Attempt" in source
    assert "old Platform `StartResearch` / `ContinueResearch` path" in source
    assert "`hqa-research-task`" in source
    assert "Never self-report those derived references in JSON." in source
    assert "intent_expires_at, command_id, hermes_run_id, hqa_run_ref" not in source

    scripts_dest = _install(tmp_path)
    wrapper = scripts_dest / "hqa-paper-research.sh"
    installed = (scripts_dest.parent / "skills" / "hqa-quant" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert wrapper.is_file()
    assert wrapper.stat().st_mode & 0o111
    wrapper_body = wrapper.read_text(encoding="utf-8")
    assert "prepare-intent|start-plan" in wrapper_body
    assert (
        f'HQA_PAPER_GATE_PORT_BIN="{scripts_dest / "hqa-paper-gate-show.py"}"'
        in wrapper_body
    )
    assert "unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT" in wrapper_body
    assert "export PYTHONNOUSERSITE=1" in wrapper_body
    assert "exec /usr/bin/python3 -s -m hqa.paper_research_cli" in wrapper_body
    assert str(wrapper) in installed
    assert "__HERMES_SCRIPTS_DIR__" not in installed
    assert "**next managed Hermes turn**" in installed
    assert "Each `prepare-intent` call is the sole" in installed
    assert 'kind:"research_start"' in installed
    assert 'kind:"research_continue"' in installed
    assert "paper_title:<exact title>" in installed
    assert "universe:[<ordered symbols>]" in installed
    assert "research_claim_digest" in installed
    assert "must not send `paper_title` or `universe` again" in installed
    assert "research-claim:sha256:<research_claim_digest>" in installed
    assert "produce a different digest at `prepare-intent`" in installed
    assert "subject_run_attestation_ref" in installed
    assert "final_backtest_receipt_digest" in installed


def test_skill_routes_natural_language_options_through_exact_managed_run(
    tmp_path,
) -> None:
    source = SKILL_SRC.read_text(encoding="utf-8")
    assert "__HERMES_SCRIPTS_DIR__/hqa-options-research.sh" in source
    assert "{ticker, expiry, strike, goal_note}" in source
    assert "sole natural-language Vertical-A ingress" in source
    for selector in (
        "HERMES_PLATFORM_COMMAND_ID",
        "HERMES_PLATFORM_SESSION_ID",
        "HERMES_PLATFORM_RUN_ID",
        "HERMES_PLATFORM_MANAGED_SESSION_ID",
    ):
        assert selector in source
    assert "must never create an" in source
    assert "zero-order evidence remain mandatory" in source
    assert "agent-v0.2-options-research/v1" in source

    scripts_dest = _install(tmp_path)
    wrapper = scripts_dest / "hqa-options-research.sh"
    installed = (scripts_dest.parent / "skills" / "hqa-quant" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    body = wrapper.read_text(encoding="utf-8")
    assert wrapper.is_file()
    assert wrapper.stat().st_mode & 0o111
    assert "hermes vertical-a execute-from-hermes" in body
    assert "unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT" in body
    assert "export PYTHONNOUSERSITE=1" in body
    assert "exec /usr/bin/python3 -s" in body
    assert str(scripts_dest / "hqa-paper-gate-show.py") in body
    assert "quant-system" not in body
    assert "__HQA_PLATFORM_DIR__" not in body
    assert str(wrapper) in installed
    assert "__HERMES_SCRIPTS_DIR__" not in installed


def test_skill_card_uses_unified_paper_snapshot_json_contract():
    body = SKILL_SRC.read_text(encoding="utf-8")
    assert "paper account-show --account default --format json" in body


def test_skill_card_documents_strict_portfolio_risk_v2() -> None:
    body = SKILL_SRC.read_text(encoding="utf-8")
    lower = body.lower()

    assert "version: 1.18.4" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-portfolio-risk.sh" in body
    assert "logs/portfolio_risk.jsonl" in body
    assert "current snapshot" in lower
    assert "correlation" in lower and "beta" in lower
    assert "data prices" in lower
    assert "qfq" in lower
    assert "60" in lower and "inner join" in lower
    assert "no sample" in lower and "longbridge" in lower
    assert "no risk-policy threshold" in lower


def test_skill_card_documents_prediction_ledger_contract() -> None:
    body = SKILL_SRC.read_text(encoding="utf-8")
    lower = body.lower()

    assert "version: 1.18.4" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-prediction.sh" in body
    assert "create" in lower and "list" in lower and "reconcile" in lower
    assert "predictions/entries.jsonl" in body
    assert "binary brier" in lower
    assert "first" in lower and ">= horizon_date" in lower
    assert "no longbridge" in lower and "no sample" in lower
    assert "9h" in lower and "cron" in lower


def test_skill_card_documents_market_foresight_and_artifact_shelf() -> None:
    body = SKILL_SRC.read_text(encoding="utf-8")
    lower = body.lower()

    assert "version: 1.18.4" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-market-foresight.sh" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-artifacts.sh" in body
    assert "artifacts/hermes-feed/manifest.v1.json" in body
    assert "proposal_only" in lower
    assert "human-confirmed" in lower
    assert "composer" in lower and "not wired" in lower


def test_skill_card_documents_opportunity_ledger_contract() -> None:
    body = SKILL_SRC.read_text(encoding="utf-8")
    lower = body.lower()

    assert "version: 1.18.4" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh" in body
    assert "opportunities/entries.jsonl" in body
    assert "sync-signals" in lower and "record-action" in lower
    assert "sync-actions" in lower and "reconcile" in lower
    assert "not_actionable" in lower and "expired_coverage_unknown" in lower
    assert "matching ticker is not causality" in lower
    assert "never invoke generate-signal" in lower


def test_skill_card_documents_full_9h_automation_contract() -> None:
    body = SKILL_SRC.read_text(encoding="utf-8")
    lower = body.lower()

    assert "version: 1.18.4" in body
    for wrapper in (
        "hqa-full-9h-daily-close.sh",
        "hqa-full-9h-freshness.sh",
        "hqa-full-9h-weekly.sh",
        "hqa-full-9h-notification-drain.sh",
    ):
        assert f"__HERMES_SCRIPTS_DIR__/{wrapper}" in body
    assert "schema 1.1" in lower and "six" in lower
    assert "local" in lower and "delivery_unknown" in lower
    assert "no-agent" in lower and "--workdir" in body
    assert "prediction reconciliation" in lower and "weekly" in lower
    assert "never" in lower and "trade" in lower


def test_skill_card_readonly_templates_use_gate_wrapper():
    # Every read-only command template must go through the single-command gate
    # wrapper (absolute path), never bare `quant-system` and never a compound
    # command (&&/|/;) that would bypass the Hermes allowlist shortcut.
    body = SKILL_SRC.read_text(encoding="utf-8")
    gate = "hqa-quant-readonly.sh"
    gate_lines = [
        ln
        for ln in body.splitlines()
        if gate in ln
        and ln.lstrip().startswith(("`", "|", "python3", "/", "bash", "$HERMES", "~/"))
    ]
    assert gate_lines, "no gate-wrapper command templates found in the card"
    for ln in gate_lines:
        # Extract the command text following the wrapper name, stripping the
        # markdown code-span backticks and any trailing table cell.
        after = ln.split(gate, 1)[1]
        cmd = after.split("|")[0].replace("`", "").strip()
        assert cmd, f"empty gate subcommand in: {ln!r}"
        first_two = " ".join(cmd.split()[:2])
        first_three = " ".join(cmd.split()[:3])
        first_one = cmd.split()[0]
        assert (
            cmd in _READONLY_SUBCOMMANDS
            or first_three in _READONLY_SUBCOMMANDS
            or first_two in _READONLY_SUBCOMMANDS
            or first_one in _READONLY_SUBCOMMANDS
        ), f"gate template forwards a non-allowlisted subcommand: {cmd!r}"


def test_skill_card_has_no_compound_operators_on_gate_lines():
    # Hermes command_allowlist glob matching is bypassed by &&/|/;/$( — the card
    # must teach single-command wrapper invocations only (plan line 20).
    body = SKILL_SRC.read_text(encoding="utf-8")
    for ln in body.splitlines():
        if "hqa-quant-readonly.sh" in ln and "```" not in ln:
            # A shell pipe inside a markdown table cell is fine ONLY as the table
            # delimiter; disallow actual shell compounding of the wrapper call.
            payload = ln.split("hqa-quant-readonly.sh", 1)[1]
            # Table cell ends at ` | `; inspect only the command up to that.
            cell = payload.split("|")[0]
            assert "&&" not in cell, f"compound && breaks allowlist: {ln!r}"
            assert ";" not in cell, f"compound ; breaks allowlist: {ln!r}"
            assert "$(" not in cell, f"cmd-subst breaks allowlist: {ln!r}"


def test_skill_card_write_templates_name_real_modules():
    # Read-write op templates must invoke real hqa modules via `python3 -m`.
    body = SKILL_SRC.read_text(encoding="utf-8")
    module_hits = re.findall(r"python3 -m (hqa\.[\w_]+)", body)
    assert module_hits, "no `python3 -m hqa.<mod>` write templates found"
    for mod in module_hits:
        assert mod in _WRITE_PATH_MODULES, f"unknown/invented module: {mod}"


def test_skill_card_covers_required_sections():
    body = SKILL_SRC.read_text(encoding="utf-8").lower()
    # (2) artifact-first — real log + scan paths.
    assert "logs/" in body
    assert "options_scans" in body
    # (3) 30s triage — background + run-id + notify push.
    assert "30" in body and "hqa-notify.sh" in body
    # (4) safety redlines — approval + kill_switch/paper_trading not bypassed.
    assert "approval" in body
    assert "kill_switch" in body or "kill switch" in body
    assert "paper_trading" in body or "paper trading" in body


def test_skill_card_documents_json_status_honestly():
    # doctor --json is supported and used by HQA's watchdog, but the skill
    # gate templates must still not invent --json on other platform leaves
    # (many still reject it). Card must also not claim doctor lacks --json.
    body = SKILL_SRC.read_text(encoding="utf-8")
    assert "doctor --json is supported" in body or "doctor --json` is supported" in body
    for ln in body.splitlines():
        if "hqa-quant-readonly.sh" in ln:
            cell = ln.split("hqa-quant-readonly.sh", 1)[1].split("|")[0]
            assert "--json" not in cell, (
                f"gate/platform template must not invent --json on unknown leaves: {ln!r}"
            )


def test_skill_card_does_not_list_scan_as_readonly():
    body = SKILL_SRC.read_text(encoding="utf-8")
    # Scan must not appear as a pre-authorized gate template.
    for ln in body.splitlines():
        if "hqa-quant-readonly.sh" in ln and "options" in ln:
            assert "daily-scan" not in ln
            assert "buyside-screen" not in ln
    assert "default" in body.lower() and "futu" in body.lower()


# --- D-25 async completion push wrapper -------------------------------------

NOTIFY_SRC = REPO / "scripts" / "hermes" / "hqa-notify.sh"


def _build_notify(tmp_path, repo_dir):
    """Materialise hqa-notify.sh with __HQA_REPO_DIR__ pointed at a scratch repo
    (so the fallback JSONL lands under tmp, never the real repo)."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    body = NOTIFY_SRC.read_text().replace("__HQA_REPO_DIR__", str(repo_dir))
    notify = tmp_path / "hqa-notify.sh"
    notify.write_text(body)
    notify.chmod(0o755)
    return notify


def _run_notify(tmp_path, args, *, path):
    """Run the notifier under a controlled PATH so we decide whether a `hermes`
    binary is reachable. Returns the completed process."""
    repo_dir = tmp_path / "repo"
    notify = _build_notify(tmp_path, repo_dir)
    env = dict(os.environ, PATH=path)
    return subprocess.run(
        ["bash", str(notify), *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_notify_fallback_writes_jsonl_when_hermes_absent(tmp_path):
    # PATH without a `hermes` binary → local fallback: append one JSON line to
    # logs/notify_fallback.jsonl under the repo dir AND echo the message.
    result = _run_notify(
        tmp_path,
        ["#backtest", "run-x done: sharpe=1.18"],
        path="/usr/bin:/bin",
    )
    assert result.returncode == 0, result.stderr
    fallback = tmp_path / "repo" / "logs" / "notify_fallback.jsonl"
    assert fallback.is_file(), "fallback JSONL not created"
    lines = [ln for ln in fallback.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one JSONL line, got {lines!r}"
    record = json.loads(lines[0])
    assert set(record) >= {"ts", "target", "message"}
    assert record["target"] == "#backtest"
    # Message carries the [HQA] prefix + a UTC timestamp before the body.
    assert record["message"].startswith("[HQA] ")
    assert "run-x done: sharpe=1.18" in record["message"]
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["message"])
    # The message is also echoed to stdout for the caller/log.
    assert "run-x done: sharpe=1.18" in result.stdout
    assert "[HQA] " in result.stdout


def test_notify_fallback_appends_second_line(tmp_path):
    # Two invocations append (never truncate) — the JSONL is a running log.
    repo_dir = tmp_path / "repo"
    notify = _build_notify(tmp_path, repo_dir)
    env = dict(os.environ, PATH="/usr/bin:/bin")
    for msg in ("first", "second"):
        r = subprocess.run(
            ["bash", str(notify), "#ch", msg],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert r.returncode == 0, r.stderr
    fallback = repo_dir / "logs" / "notify_fallback.jsonl"
    lines = [ln for ln in fallback.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["message"].endswith("first")
    assert json.loads(lines[1])["message"].endswith("second")


def test_notify_delivers_via_hermes_when_available(tmp_path):
    # PATH with a stub `hermes` that succeeds → deliver via `hermes send`, NO
    # fallback JSONL. The stub records its argv so we assert the discord target
    # and the [HQA]-prefixed message are forwarded.
    stubdir = tmp_path / "stub"
    stubdir.mkdir()
    argv_log = tmp_path / "hermes_argv.txt"
    stub = stubdir / "hermes"
    stub.write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" > "{argv_log}"\nexit 0\n')
    stub.chmod(0o755)
    result = _run_notify(
        tmp_path,
        ["#backtest", "done"],
        path=f"{stubdir}:/usr/bin:/bin",
    )
    assert result.returncode == 0, result.stderr
    fallback = tmp_path / "repo" / "logs" / "notify_fallback.jsonl"
    assert not fallback.exists(), "must not fall back when hermes delivery succeeds"
    forwarded = argv_log.read_text()
    assert "send" in forwarded
    assert "discord" in forwarded  # --to discord[:#channel]
    assert "[HQA] " in forwarded


def test_notify_falls_back_when_hermes_delivery_fails(tmp_path):
    # PATH with a `hermes` that EXITS NONZERO (delivery/backend error) → the
    # wrapper must still not lose the message: fall back to the JSONL log.
    stubdir = tmp_path / "stub"
    stubdir.mkdir()
    stub = stubdir / "hermes"
    stub.write_text("#!/bin/bash\nexit 1\n")
    stub.chmod(0o755)
    result = _run_notify(
        tmp_path,
        ["#backtest", "salvage-me"],
        path=f"{stubdir}:/usr/bin:/bin",
    )
    assert result.returncode == 0, result.stderr
    fallback = tmp_path / "repo" / "logs" / "notify_fallback.jsonl"
    assert fallback.is_file(), "delivery failure must still persist to fallback"
    assert "salvage-me" in fallback.read_text()


def test_notify_source_uses_repo_placeholder_and_discord_target():
    # Static guards: the source ships the install-time repo placeholder (so the
    # fallback log resolves per-machine) and delivers to discord via hermes send.
    body = NOTIFY_SRC.read_text(encoding="utf-8")
    assert "__HQA_REPO_DIR__" in body
    assert "logs/notify_fallback.jsonl" in body
    assert "hermes send" in body
    assert "discord" in body
