# D-31 Wave 2 — Hermes read bridge wire report (2026-07-14)

## Status

**Read path expanded; write remains fail-closed.**  
This work does **not** claim Hermes is fully connected, does **not** flip the
capability review verdict to `ready`, and does **not** enable chat write /
stream / resume / approval mutations.

## What was added (HQA)

| Piece | Path | Role |
|---|---|---|
| Loopback JSON-RPC WebSocket transport | `hqa/hermes_read_bridge.py` (`LoopbackJsonRpcWsTransport`) | Pure-stdlib client; **loopback-only** (`127.0.0.1` / `::1`, path `/api/ws`); allowlists read methods; refuses mutations at transport |
| Read bridge library (existing + helpers) | `hqa/hermes_read_bridge.py` | `HermesReadBridge` + `assert_loopback_ws_endpoint` + `gate_from_mapping` + `open_read_bridge` |
| CLI surface | `hqa/hermes_read_bridge_cli.py` | `list-sessions`, `session-status --session-id`, `session-history --session-id` |
| Hermetic tests | `tests/test_hermes_read_bridge.py` | Fake transport + local fake WS server; no live Hermes required |
| Optional live smoke | `scripts/hermes_read_bridge_live_smoke.py` | Skips if contract port not listening; only `list-sessions` |

## CLI contract

```bash
./.venv/bin/python -m hqa.hermes_read_bridge_cli list-sessions [--limit N]
./.venv/bin/python -m hqa.hermes_read_bridge_cli session-status --session-id <id>
./.venv/bin/python -m hqa.hermes_read_bridge_cli session-history --session-id <id>
```

Each command:

1. Loads the default capability contract.
2. Applies the Git-bound review gate + live installation probe
   (same path as `hermes_capability_cli`).
3. Refuses with exit **3** if `chat_read_enabled` is false.
4. Opens a **loopback-only** WebSocket JSON-RPC transport to the contract
   endpoint (or a still-loopback `--endpoint` override).
5. Emits JSON with `"chat_ready": false` always — read success is **not**
   write admission.

Mutation aliases (`prompt-submit`, `session-create`, `session-resume`,
`session-interrupt`, `approval-respond`, `config-set`) are explicitly rejected
with `mutation_forbidden`.

## Explicit non-goals / still fail-closed

| Surface | Status |
|---|---|
| `prompt.submit` | **Never** on public bridge/CLI |
| `session.create` / `session.resume` / `session.interrupt` | **Never** |
| `approval.respond` / `config.set` | **Never** |
| Chat write / stream / resume admission | Still gated by `verify-chat` exit 0 + review `ready` + source evidence (currently **blocked**) |
| Platform `/api/hermes/sessions` proxy | **Not added** this slice — HQA CLI + library first; any future proxy must stay read-only and must not claim chat ready |
| Capability review verdict | Unchanged (`blocked`) — do not greenwash |

## Runtime note (ops)

Capability re-audit observed Hermes may run as `--port 0`, so
`ws://127.0.0.1:9119` may not be listening. Live smoke **skips** in that case.
Fingerprint match + `chat_read_enabled=true` authorize the *library* path;
they do not invent a listening port.

## Platform

No platform code changes in this slice (preserves dirty options-universe /
data_refresh work). Frontend BFF can call HQA CLI/library later under a
strict read-only proxy if desired.

## Honesty banner

> Hermes read bridge can list/status/history **when** `chat_read_enabled` and a
> reachable loopback endpoint exist.  
> **Chat write is still fail-closed.** `verify-chat` remains exit 3 until a
> reviewed ready contract with recovery/run/event/provider evidence lands.
