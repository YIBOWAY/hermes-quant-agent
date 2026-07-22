"""Shared pytest hooks.

IntentPayloadStore refuses any world/group-writable ancestor on the authority
path chain. macOS default pytest basetemp under /tmp fails that check, so pin
basetemp inside the repo when the user did not override it.
"""

from __future__ import annotations

from pathlib import Path


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    if getattr(config.option, "basetemp", None):
        return
    root = Path(__file__).resolve().parent.parent / ".tmp-pytest"
    root.mkdir(mode=0o700, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    config.option.basetemp = str(root / "run")
