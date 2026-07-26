from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "scripts" / "build_intent_payload_crypto.sh"


def _build(destination: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(BUILD), str(destination)],
        cwd=REPO,
        text=True,
        capture_output=True,
        timeout=60,
    )


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


def test_build_produces_a_private_physical_swift_helper(tmp_path: Path) -> None:
    destination = tmp_path / "private-bin" / "hqa-intent-payload-crypto"

    built = _build(destination)

    assert built.returncode == 0, built.stdout + built.stderr
    metadata = destination.lstat()
    assert stat.S_ISREG(metadata.st_mode)
    assert not destination.is_symlink()
    assert metadata.st_nlink == 1
    assert metadata.st_uid == os.geteuid()
    assert stat.S_IMODE(metadata.st_mode) == 0o700
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700

    no_protocol = subprocess.run(
        [str(destination)],
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert no_protocol.returncode == 64
    assert no_protocol.stdout == ""
    assert no_protocol.stderr == ""


def test_build_uses_stable_codesign_identity_across_random_staging_names(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first" / "hqa-intent-payload-crypto"
    second = tmp_path / "second" / "hqa-intent-payload-crypto"

    first_build = _build(first)
    second_build = _build(second)

    assert first_build.returncode == 0, first_build.stdout + first_build.stderr
    assert second_build.returncode == 0, second_build.stdout + second_build.stderr
    first_identity = _codesign_identity(first)
    second_identity = _codesign_identity(second)
    assert first_identity[0] == "hqa-intent-payload-crypto"
    assert second_identity[0] == "hqa-intent-payload-crypto"
    assert first_identity == second_identity


def test_build_refuses_symlinked_destination_ancestor_without_touching_target(
    tmp_path: Path,
) -> None:
    physical = tmp_path / "physical"
    physical.mkdir(mode=0o755)
    marker = physical / "marker"
    marker.write_text("unchanged", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(physical, target_is_directory=True)

    built = _build(linked / "hqa-intent-payload-crypto")

    assert built.returncode != 0
    assert linked.is_symlink()
    assert stat.S_IMODE(physical.stat().st_mode) == 0o755
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert not (physical / "hqa-intent-payload-crypto").exists()


def test_build_refuses_final_symlink_without_replacing_or_writing_target(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "private-bin"
    parent.mkdir(mode=0o700)
    target = tmp_path / "victim"
    target.write_text("unchanged", encoding="utf-8")
    destination = parent / "hqa-intent-payload-crypto"
    destination.symlink_to(target)

    built = _build(destination)

    assert built.returncode != 0
    assert destination.is_symlink()
    assert destination.readlink() == target
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_build_refuses_world_writable_intermediate_ancestor(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o777)
    unsafe.chmod(0o777)
    private_parent = unsafe / "private-bin"
    private_parent.mkdir(mode=0o700)
    destination = private_parent / "hqa-intent-payload-crypto"

    built = _build(destination)

    assert built.returncode != 0
    assert "owner-controlled" in built.stderr
    assert unsafe.stat().st_mode & 0o777 == 0o777
    assert private_parent.stat().st_mode & 0o777 == 0o700
    assert not destination.exists()
