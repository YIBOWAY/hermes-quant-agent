from __future__ import annotations

import argparse
import json
import sys

from hqa.ops_digest import DEFAULT_BACKEND, build_ops_digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only morning ops digest")
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    args = parser.parse_args(argv)
    digest = build_ops_digest(backend=args.backend)
    json.dump(digest, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
