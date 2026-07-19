from __future__ import annotations

import os
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
