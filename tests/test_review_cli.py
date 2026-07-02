from __future__ import annotations

from hqa import review_cli, reviewlog


def test_cli_draft_then_confirm_roundtrip(tmp_path, capsys):
    rc = review_cli.main(["draft", "--kind", "manual", "--event", "bad exit",
                          "--data", "rid=r9", "--review-dir", str(tmp_path)])
    assert rc == 0
    entry_id = capsys.readouterr().out.strip()
    assert entry_id == "2026-07-01-001" or entry_id.endswith("-001")

    rc = review_cli.main(["confirm", entry_id, "--judgment", "too early",
                          "--next-rule", "wait", "--review-dir", str(tmp_path)])
    assert rc == 0
    e = reviewlog.load_entries(tmp_path)[0]
    assert e["status"] == "confirmed"
    assert e["judgment"] == "too early"
    assert e["data"] == {"rid": "r9"}


def test_cli_confirm_unknown_id_returns_1(tmp_path, capsys):
    rc = review_cli.main(["confirm", "missing", "--review-dir", str(tmp_path)])
    assert rc == 1


def test_cli_render_writes_markdown(tmp_path, capsys):
    review_cli.main(["draft", "--event", "e", "--review-dir", str(tmp_path)])
    rc = review_cli.main(["render", "--review-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "entries.md").exists()
