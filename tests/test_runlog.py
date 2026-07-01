from __future__ import annotations

import json
import re

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
