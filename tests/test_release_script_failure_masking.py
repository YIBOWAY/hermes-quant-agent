from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_install_and_crypto_build_do_not_mask_cleanup_failures() -> None:
    for relative in (
        "scripts/install.sh",
        "scripts/build_intent_payload_crypto.sh",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")

        assert "|| true" not in source
        assert "cleanup_and_exit()" in source
        assert "trap cleanup_and_exit EXIT" in source
        assert "else\n    cleanup_status=$?" in source
        assert "cleanup_status=$?" in source


def test_install_cleanup_distinguishes_absent_from_unsafe_root() -> None:
    source = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")

    assert "except FileNotFoundError:" in source
    assert "except (NotADirectoryError, OSError) as exc:" in source
    assert "install cleanup refused unsafe Hermes root" in source
    assert "install staging changed type or owner before cleanup" in source
