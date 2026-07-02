from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from hqa import config, reviewlog, runlog


def _parse_kv(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        key, _, value = item.partition("=")
        out[key] = value
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="hqa-review")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_draft = sub.add_parser("draft")
    p_draft.add_argument("--kind", default="manual")
    p_draft.add_argument("--event", required=True)
    p_draft.add_argument("--data", action="append", default=[])
    p_draft.add_argument("--source", default="manual")
    p_draft.add_argument("--review-dir", default=str(config.REVIEW_DIR))

    p_confirm = sub.add_parser("confirm")
    p_confirm.add_argument("id")
    for field in ("judgment", "basis", "result", "failure-point", "next-rule"):
        p_confirm.add_argument(f"--{field}", default="")
    p_confirm.add_argument("--review-dir", default=str(config.REVIEW_DIR))

    p_list = sub.add_parser("list")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--review-dir", default=str(config.REVIEW_DIR))

    p_render = sub.add_parser("render")
    p_render.add_argument("--review-dir", default=str(config.REVIEW_DIR))

    args = parser.parse_args(argv)
    review_dir = Path(args.review_dir)

    if args.cmd == "draft":
        entry_id = reviewlog.new_draft(
            kind=args.kind, event=args.event, data=_parse_kv(args.data),
            source=args.source, ts=runlog.utc_now_iso(), review_dir=review_dir,
        )
        reviewlog.write_markdown(review_dir)
        print(entry_id)
        return 0

    if args.cmd == "confirm":
        ok = reviewlog.confirm(
            args.id, review_dir,
            judgment=args.judgment, basis=args.basis, result=args.result,
            failure_point=args.failure_point, next_rule=args.next_rule,
        )
        if not ok:
            print(f"not found: {args.id}")
            return 1
        reviewlog.write_markdown(review_dir)
        print(f"confirmed: {args.id}")
        return 0

    if args.cmd == "list":
        for e in reviewlog.list_entries(review_dir, status=args.status):
            print(f"{e['id']}\t{e['status']}\t{e['kind']}\t{e.get('event', '')}")
        return 0

    if args.cmd == "render":
        path = reviewlog.write_markdown(review_dir)
        print(str(path))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
