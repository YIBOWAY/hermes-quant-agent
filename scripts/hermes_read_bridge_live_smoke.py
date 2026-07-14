#!/usr/bin/env python3
"""Optional live smoke for the Hermes read-only bridge.

Skips (exit 0) when the contract loopback port is not listening.
Never calls session.create / prompt.submit / resume / interrupt / approval /
config.set. Does not claim chat_ready.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

# Allow running from repo root without install.
REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hqa import config  # noqa: E402
from hqa import hermes_read_bridge_cli  # noqa: E402
from hqa.hermes_capabilities import load_capabilities  # noqa: E402


def _port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def main() -> int:
    capabilities = load_capabilities(config.HERMES_GATEWAY_CAPABILITIES_PATH)
    endpoint = capabilities.endpoint
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if port is None:
        print(
            json.dumps(
                {
                    "status": "skip",
                    "reason": "contract_endpoint_missing_port",
                    "endpoint": endpoint,
                    "chat_ready": False,
                },
                sort_keys=True,
            )
        )
        return 0
    if not _port_open(host, port):
        print(
            json.dumps(
                {
                    "status": "skip",
                    "reason": "hermes_not_listening",
                    "endpoint": endpoint,
                    "chat_ready": False,
                    "note": (
                        "Contract default is ws://127.0.0.1:9119/api/ws; a "
                        "Hermes process started with --port 0 will not match."
                    ),
                },
                sort_keys=True,
            )
        )
        return 0

    # Live read only: list-sessions. Gate still rebuilt from contract+probe.
    code = hermes_read_bridge_cli.main(["list-sessions", "--limit", "5"])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
