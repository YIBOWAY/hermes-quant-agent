# Gateway Task 1 Report — Strict capability snapshot and fail-closed evaluator

**Status:** DONE  
**Branch:** `codex/full-9h`  
**BASE:** `2939c0487268acc0546e999b26b55d49dbebdae8`  
**Commit:** `1b461ef` — `feat(hqa): add fail-closed Hermes gateway capability contract`  
**Date:** 2026-07-13

---

## 1. Preflight reconfirm (read-only)

| Check | Expected (controller) | Observed | Match |
|---|---|---|---|
| `hermes --version` | Hermes Agent v0.18.2 (2026.7.7.2) · upstream **b03c94db** | same | yes |
| `git -C ~/.hermes/hermes-agent rev-parse HEAD` | `4281151ae859241351ba14d8c7682dc67ff4c126` | same | yes |
| tracked-only `git status --porcelain --untracked-files=no` | empty | empty | yes |
| `shasum -a 256 tui_gateway/server.py` | `2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17` | same | yes |
| HQA Python | 3.9.6 via `./.venv/bin/python` | 3.9.6 | yes |

**Source-review note (upstream tip drift only):**

- Plan-frozen `upstream_commit` was `e4ea0a0e`.
- Live `hermes --version` banner now reports **`b03c94db`** (origin/main tip moved).
- Source checkout HEAD and `server.py` digest are **unchanged** from the plan.
- No other capability evidence flags were invented as true to pass tests.
- Snapshot / tests use `upstream_commit: "b03c94db"` and `observed_at: "2026-07-13T09:13:45Z"` (this reconfirm timestamp, ISO Z).

Did **not** edit installed Hermes at `/Users/sunyibo/.hermes/hermes-agent`.

---

## 2. TDD sequence

### RED

```text
./.venv/bin/pytest -q tests/test_hermes_capabilities.py
→ ModuleNotFoundError: No module named 'hqa.hermes_capabilities'
```

### GREEN

```text
./.venv/bin/pytest -q tests/test_hermes_capabilities.py
...................                                                      [100%]
```

19 tests passed (including parametrized cases).

---

## 3. Files delivered

| Path | Action |
|---|---|
| `tests/test_hermes_capabilities.py` | Create — fail-closed gate + schema rejection tests |
| `hqa/hermes_capabilities.py` | Create — strict types, parser, pure evaluator |
| `config/hermes-gateway-capabilities.v1.json` | Create — known 0.18.2 fail-closed snapshot |
| `hqa/config.py` | Modify — path constants for capabilities/review/bin/source |

Committed **only** those four paths. Unrelated dirty/untracked (`.superpowers/`) left alone. Not pushed.

---

## 4. Behavior summary

- `load_capabilities(Path)`: exact-key JSON schema; loopback WebSocket only (`127.0.0.1` / `::1`, path `/api/ws`, no userinfo/query/fragment); rejects non-1.0 schema / non-websocket transport / non-loopback; error text never echoes credentials-bearing endpoint material.
- `evaluate_chat_gate(...)`: independent gates for read / write / stream / resume / approval / stop.
- Known snapshot: **read open**, all mutations **fail-closed** with stable blocker codes:
  - write/stream blockers include `missing_request_recovery`, `missing_run_identity`, `missing_provider_policy_lock`, `missing_actual_provider_evidence`, `missing_event_replay`
  - approval: `missing_chat_contract`, `missing_approval_binding`
  - stop: `missing_run_identity`, `missing_stop_contract`
- Evidence truth flags match observed 0.18.2 facts: only `session_provider_override: true`; provider policy immutability, recovery, run/event identity, approval binding, and stop contract all remain false.

Config anchors (not env-overridable for admission paths):

- `HERMES_GATEWAY_CAPABILITIES_PATH`
- `HERMES_GATEWAY_REVIEW_PATH`

Env-overridable install pointers (for later verify-chat):

- `HERMES_BIN_PATH` (`HQA_HERMES_BIN_PATH`)
- `HERMES_SOURCE_DIR` (`HQA_HERMES_SOURCE_DIR`)

---

## 5. Self-review

| Check | Result |
|---|---|
| No Hermes session create/submit / provider / network | pass |
| No edit of installed Hermes checkout | pass |
| Python 3.9-safe (`from __future__ import annotations`) | pass |
| Commit message exact | pass |
| Only listed files staged | pass |
| No invented capability `true` flags | pass |
| `upstream_commit` = `b03c94db` in tests + snapshot | pass |
| Tasks 2–4 (CLI, docs, review record) not started | pass |

---

## 6. Concerns

None blocking. Minor note: commit author identity used auto-detected local git identity (pre-existing machine config message); content is correct.

---

## 7. Out of scope (intentionally not done)

- CLI `show` / `verify-chat` (Task 2+)
- Contract docs / README updates
- Review record JSON
- Any live gateway mutation or BFF exposure
