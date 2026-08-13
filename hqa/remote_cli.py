"""Chat remote for the personal quant assistant.

dispatch-research never hangs. hang only accepts an existing verified candidate.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BACKEND = "http://127.0.0.1:8876"


def _request(backend: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        backend.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            raise SystemExit(f"remote_http_{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"remote_unreachable:{exc.reason}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assistant remote: dispatch vs hang")
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    dispatch = sub.add_parser("dispatch-research")
    dispatch.add_argument("--objective", required=True)
    dispatch.add_argument("--hang-if-pass", action="store_true")
    hang = sub.add_parser("hang")
    hang.add_argument("--candidate-id", required=True)
    args = parser.parse_args(argv)

    if args.command == "status":
        payload = _request(args.backend, "GET", "/api/assistant/remote/book")
    elif args.command == "dispatch-research":
        payload = _request(
            args.backend,
            "POST",
            "/api/assistant/remote/dispatch",
            {
                "objective": args.objective,
                "hang_if_pass": args.hang_if_pass,
            },
        )
    else:
        payload = _request(
            args.backend,
            "POST",
            "/api/assistant/remote/hang",
            {"candidate_id": args.candidate_id},
        )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if isinstance(payload, dict) and payload.get("safety"):
        return 0
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict) and detail.get("code"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
