# D-31 Wave 2 — Hermes capability re-audit (2026-07-14)

Read-only preflight + source re-scan for bridge readiness. **No live
`session.create` / `prompt.submit`.** Chat write remains fail-closed.

## 1. Preflight (live)

| Check | Result |
|---|---|
| `hermes --version` | `Hermes Agent v0.18.2 (2026.7.7.2) · upstream 226e8de8` |
| Install dir | `/Users/sunyibo/.hermes/hermes-agent` (git) |
| `git rev-parse HEAD` | `4281151ae859241351ba14d8c7682dc67ff4c126` **matches freeze** |
| Tracked status (`--untracked-files=no`) | clean (only untracked `.install_method`) |
| `tui_gateway/server.py` SHA-256 | `2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17` **matches freeze** |
| `hermes serve --status` | 1 process: `hermes_cli.main serve --host 127.0.0.1 --port 0` |
| Loopback `ws://127.0.0.1:9119` | **not listening** (process used `--port 0`, not contract default 9119) |

Frozen contract snapshot (`config/hermes-gateway-capabilities.v1.json`):

- `upstream_commit`: `b03c94db` (banner value at freeze)
- `source_checkout_commit`: `4281151ae…`
- `server_source_sha256`: `2a05d897…`
- review: `verdict=blocked` (trusted Git record)

## 2. Source capability truth (`tui_gateway/server.py` at HEAD)

Semantic re-scan of the **installed** server (byte-identical to freeze):

| Evidence flag | Still false? | Notes |
|---|---|---|
| `client_idempotency_key` | **yes** | no client key on create/submit |
| `request_correlation_metadata` / `request_lookup_by_client_id` | **yes** | 0 matches |
| `run_id` | **yes** | 0 matches; submit returns `{status: streaming}` only |
| `event_id` / `event_cursor` | **yes** | `_emit` → `{type, session_id, payload?}` only |
| `run_provider_evidence` / `actual_provider` | **yes** | 0 `actual_provider`; resolver-only `requested_provider` |
| primary/fallback policy immutable | **yes** | create override + later `config.set` unlock |
| approval digest/ttl/single-use | **yes** | `approval.respond` choice/all only |
| stop idempotent/reconcilable | **yes** | interrupt clears flags; no Run reconcile |

Read methods still registered: `session.list`, `session.status`, `session.history`.

`idempoten*` hits remain teardown/billing only — **not** create/submit recovery.

**Conclusion:** all write-gate evidence flags remain **false**. Capabilities did not improve.

## 3. NEW capability snapshot needed?

| Question | Answer |
|---|---|
| New **ready** contract? | **No** — source still lacks recovery/run/event/provider evidence |
| New **blocked** re-freeze of evidence? | **No** — evidence matrix unchanged vs `b03c94db` freeze |
| What drifted? | **Banner fingerprint only**: Hermes `format_banner_version_label` prints `upstream` = `git rev-parse --short=8 origin/main` (`hermes_cli/banner.py`). Local HEAD stayed at `4281151ae…`; remote tip moved `b03c94db` → `226e8de8` (repo reports behind origin by ~199 commits). |
| origin/main `server.py` | Different SHA (`165441d2…`); **not** the running install. Do not re-bind contract to remote tip without checkout + re-review. |

**Admission rule unchanged:** chat write/stream only when `verify-chat` exit 0 against a Git-reviewed `ready` contract **and** matching local install fingerprint **and** true source evidence for recovery/run/event/provider locks.

## 4. `verify-chat` before / after probe fix

**Before (exit 3):** blockers included capability gaps + `contract_review_blocked` + `installation_fingerprint_mismatch` (banner `226e8de8` ≠ freeze `b03c94db`) → `chat_read_enabled=false` even though checkout/server matched.

**Probe fix (HQA):** installation match keys are now only:

1. `hermes_version`
2. `source_checkout_commit`
3. `server_source_sha256`
4. plus `source_tracked_clean`

Banner `upstream` is retained as diagnostic (`banner_upstream_commit` / `banner_upstream_drift`) and **no longer** closes gates when the pinned checkout matches. This is not write enablement.

**After fix (live reconfirm):** `installation.matches_snapshot=true`, `banner_upstream_drift=true` (`226e8de8`); `status=blocked` exit 3; `chat_read_enabled=true`; `chat_write_enabled=false` / `stream_enabled=false`; blockers = capability gaps + `contract_review_blocked` only (no fingerprint mismatch).

## 5. Minimal platform/HQA read-only bridge interface

Implemented scaffold: `hqa/hermes_read_bridge.py` (`HermesReadBridge`).

```text
HermesReadBridge(gate: HermesChatGate, transport: JsonRpcTransport)
  requires: gate.chat_read_enabled is True
  methods:
    list_sessions(limit=200)     → session.list
    session_status(session_id)   → session.status
    session_history(session_id)  → session.history
  never exposes (even if a future write gate opens — needs a separate type):
    session.create | session.resume | session.interrupt
    prompt.submit | prompt.background
    approval.respond | config.set
```

Platform BFF rules for Wave 2:

1. Build gate via `hqa.hermes_capability_cli` / evaluator; **never** hardcode ready.
2. Construct `HermesReadBridge` only when `chat_read_enabled`.
3. Inject loopback-only authenticated transport bound to contract endpoint; no browser secrets.
4. If `chat_write_enabled` is false (current truth), UI composer stays disabled; bridge must not grow submit helpers “for later”.
5. Runtime handshake on the **actual** listening process (port may not be 9119 if `--port 0`) is a later slice; static fingerprint alone never authorizes writes.
6. Old `POST /api/agent/tasks` remains non-fallback.

Hermetic tests: `tests/test_hermes_read_bridge.py` (fake transport only).

## 6. Runtime notes / open ops

- Dashboard/gateway process is up on **auto port 0**, not contract default **9119**. Read bridge live smoke needs either restart on 9119 or discovery of the bound port — still **read-only**, no create/submit.
- Do not `git pull` Hermes to `226e8de8` just to quiet the banner; that would change `server.py` and force a full new contract + independent review.
- Chat ready remains **blocked** until upstream Hermes adds real recovery/run/event/provider contracts and a `ready` review lands.

## 7. Artifacts touched this re-audit

- `.superpowers/sdd/wave2-hermes-capability-reaudit.md` (this file)
- `hqa/hermes_capability_cli.py` — banner-upstream non-authoritative for fingerprint match
- `tests/test_hermes_capability_cli.py` — banner drift case
- `hqa/hermes_read_bridge.py` + `tests/test_hermes_read_bridge.py` — read-only scaffold

**Chat write: NOT ready.**
