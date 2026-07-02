from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from hqa import gate


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="hqa-gate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("config", help="path to strategy config JSON")
    args = parser.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    passed, results = gate.check_strategy(cfg)
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {r['criterion']}: {r['detail']}")
    print(f"OVERALL: {'PASS' if passed else 'FAIL'}")
    return 0
