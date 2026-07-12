from __future__ import annotations

import json
import re

import pytest

from hqa import runlog


def test_utc_now_iso_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", runlog.utc_now_iso())


def test_append_creates_parent_and_writes_valid_json(tmp_path):
    path = tmp_path / "nested" / "run.jsonl"
    runlog.append_jsonl({"job": "x", "n": 1}, path)
    runlog.append_jsonl({"job": "x", "n": 2}, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["n"] == 1
    assert json.loads(lines[1])["n"] == 2


def test_append_rejects_non_finite_json_numbers(tmp_path):
    path = tmp_path / "run.jsonl"

    with pytest.raises(ValueError):
        runlog.append_jsonl({"job": "x", "n": float("nan")}, path)

    assert not path.exists()


def test_append_validates_utf8_before_opening_artifact(tmp_path):
    path = tmp_path / "run.jsonl"

    with pytest.raises(UnicodeEncodeError):
        runlog.append_jsonl({"job": "x", "warning": "\ud800"}, path)

    assert not path.exists()
