"""Shared pytest hooks.

IntentPayloadStore refuses any world/group-writable ancestor on the authority
path chain. macOS default pytest basetemp under /tmp fails that check, so pin
basetemp inside the repo when the user did not override it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_orig_rmtree = shutil.rmtree


def _xattr_safe_rmtree(
    path: object,
    ignore_errors: bool = False,
    onerror: object = None,
    **kwargs: object,
) -> None:
    """shutil.rmtree wrapper that strips macOS com.apple.provenance xattrs.

    macOS adds ``com.apple.provenance`` to files created in certain contexts
    (e.g. git objects), which prevents removal with EPERM even as owner.
    Strip extended attributes with ``xattr -cr`` before the second attempt.
    """
    try:
        _orig_rmtree(path, ignore_errors=ignore_errors, onerror=onerror, **kwargs)  # type: ignore[call-arg]
    except (PermissionError, OSError):
        try:
            subprocess.run(
                ["xattr", "-cr", str(path)],
                check=False,
                capture_output=True,
                timeout=15,
            )
        except Exception:  # noqa: BLE001
            pass
        _orig_rmtree(path, ignore_errors=True, **kwargs)  # type: ignore[call-arg]


shutil.rmtree = _xattr_safe_rmtree  # type: ignore[assignment]


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

