from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_release_packaging_metadata_is_complete_and_locked() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["build-system"] == {
        "requires": ["setuptools>=68", "wheel"],
        "build-backend": "setuptools.build_meta",
    }

    project = pyproject["project"]
    assert project["name"] == "hermes-quant-agent"
    assert project["version"] == "0.2.2"
    assert project["readme"] == "README.md"
    assert project["requires-python"] == ">=3.11"
    assert project["dependencies"] == []
    assert project["optional-dependencies"] == {"dev": ["pytest==8.4.2"]}

    assert pyproject["tool"]["setuptools"]["packages"]["find"] == {
        "where": ["."],
        "include": ["hqa*"],
        "namespaces": False,
    }

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert lock["requires-python"] == ">=3.11"
    packages = {
        (package["name"], package.get("version")): package
        for package in lock["package"]
    }
    assert ("hermes-quant-agent", "0.2.2") in packages
    assert ("pytest", "8.4.2") in packages
