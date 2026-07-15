# Hermes gateway 0.18.2 capability evidence

> **历史合同 / 当前失配（2026-07-15）。** 本文冻结的是旧 TUI WebSocket checkout
> `4281151ae859241351ba14d8c7682dc67ff4c126` 与 `server.py` SHA-256
> `2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17`。当前本机 Hermes
> checkout 已是 `9baa7d4673ce89f09378daa3660530f8bf142708`，TUI source SHA-256 已变为
> `539d36e7fe90e2fc5df1d454febffab5b78736ddc9c0083fda0ee8f07d588d11`，所以 installation
> fingerprint **不再匹配**，旧 bridge 必须 fail-closed。后文均是历史冻结证据，不能据此
> 打开 chat/session mutation。D-31 当前采用 official API Server 的只读合同：
> [`hermes-api-server-0.18.2.md`](hermes-api-server-0.18.2.md)。

Observed 2026-07-13. This document is a local compatibility snapshot, not a
promise about newer Hermes versions.

Machine-readable twin:
[`config/hermes-gateway-capabilities.v1.json`](../../config/hermes-gateway-capabilities.v1.json).
Chat write admission remains fail-closed until
`python -m hqa.hermes_capability_cli verify-chat` exits 0 against a
Git-bound independent review record and a matching installation fingerprint.

## Snapshot identity (live reconfirm)

| Field | Value |
|---|---|
| Hermes version banner | `Hermes Agent v0.18.2 (2026.7.7.2) · upstream b03c94db` |
| Upstream identity note | Implementation plan text recorded plan-era `e4ea0a0e`; the frozen contract was live-reviewed at `b03c94db`. Hermes banner `upstream` is `origin/main`'s tip (`hermes_cli/banner.py`), not the installed checkout. 2026-07-14 local banner reports `226e8de8` while checkout `4281151ae…` and `server.py` SHA remain freeze-identical. HQA installation match uses version + checkout + server digest only; banner tip is diagnostic (`banner_upstream_drift`) and does not rewrite the reviewed snapshot or open write gates. |
| Source checkout commit | `4281151ae859241351ba14d8c7682dc67ff4c126` (unchanged vs plan/contract) |
| `tui_gateway/server.py` SHA-256 | `2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17` (unchanged) |
| Working tree (tracked) | clean (`git status --porcelain --untracked-files=no` empty) |
| Transport / default endpoint | WebSocket JSON-RPC · `ws://127.0.0.1:9119` (`hermes serve --help`: host `127.0.0.1`, port `9119`) |

## Reproduce without a model call

Exact commands (read-only; no network model call):

```bash
hermes --version
hermes serve --help
git -C /Users/sunyibo/.hermes/hermes-agent rev-parse HEAD
git -C /Users/sunyibo/.hermes/hermes-agent status \
  --porcelain --untracked-files=no
shasum -a 256 \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
rg -n '^@method\("(session|prompt|approval|config)' \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
rg -n \
  -e 'client_request|idempoten|request_correlation|request_lookup' \
  -e 'run_id|event_id|event_cursor' \
  -e 'requested_provider|actual_provider|fallback' \
  -e 'approval.*(digest|ttl|expir|single)' \
  -e 'interrupt.*(idempoten|reconcil)' \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
sed -n '1138,1152p' \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
sed -n '4515,4610p' \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
sed -n '5161,5304p' \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
sed -n '5528,5680p' \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
sed -n '8420,8525p' \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
sed -n '8114,8170p' \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
sed -n '10199,10315p' \
  /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
```

Record both matching and zero-result searches. A false capability means the
specific create/submit/event/interrupt/approval/Run contract lacks the required
semantic guarantee; it does not claim that a similarly named token is absent
from unrelated billing, process, or internal implementation code.

### Observed command results (2026-07-13 reconfirm)

**`hermes --version`**

```text
Hermes Agent v0.18.2 (2026.7.7.2) · upstream b03c94db
Install directory: /Users/sunyibo/.hermes/hermes-agent
Install method: git
Python: 3.11.15
OpenAI SDK: 2.24.0
```

**`hermes serve --help`** (summary): JSON-RPC/WebSocket gateway; default
`--host 127.0.0.1`, `--port 9119`; headless (no browser UI). Public bind always
requires auth; loopback remains the supported local surface.

**`git … rev-parse HEAD`**

```text
4281151ae859241351ba14d8c7682dc67ff4c126
```

**`git … status --porcelain --untracked-files=no`**

```text
(empty — clean tracked tree)
```

**`shasum -a 256 …/tui_gateway/server.py`**

```text
2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17  .../tui_gateway/server.py
```

**`rg -n '^@method\("(session|prompt|approval|config)' …/server.py`**
— matching method registrations include (allowlisted subset for the contract
shown in **bold**):

| Line | Method |
|---:|---|
| 5161 | **session.create** |
| 5307 | **session.list** |
| 5353 | session.most_recent |
| 5543 | **session.resume** |
| 5913 | session.cwd.set |
| 6070 | session.active_list |
| 6108 | session.activate |
| 6132 | session.delete |
| 6174 | session.title |
| 6475 | session.usage |
| 6501 | session.context_breakdown |
| 7759 | **session.status** |
| 7816 | **session.history** |
| 7839 | session.undo |
| 7867 | session.compress |
| 7963 | session.save |
| 8018 | session.close |
| 8030 | session.branch |
| 8114 | **session.interrupt** |
| 8383 | session.steer |
| 8420 | **prompt.submit** |
| 10004 | prompt.background |
| 10199 | **approval.respond** |
| 10224 | **config.set** |
| 11181 | config.get |
| 13811 | config.show |

**`rg -n` recovery / identity / evidence patterns** — 84 total matching lines.
Interpretation is **semantic**, not token-presence:

| Pattern family | Observed in server.py? | Semantic note for D-31 contract |
|---|---|---|
| `client_request` | **0 matches** | No client request ID field on create/submit |
| `request_correlation` | **0 matches** | No durable request-correlation metadata |
| `request_lookup` | **0 matches** | No lookup-by-client-request API |
| `run_id` | **0 matches** | No caller-supplied / immutable Run ID on submit |
| `event_id` | **0 matches** | Events carry `type` + `session_id` only (see `_emit`) |
| `event_cursor` | **0 matches** | No replay cursor contract |
| `actual_provider` | **0 matches** | No immutable actual-provider evidence on Run |
| `requested_provider` | Internal resolver only (~7 lines near agent build) | Not a create/submit request-recovery field; not bound to a Run evidence object |
| `fallback` | Many internal uses (transport, title, provider chain, session lookup helpers) | **Not** an immutable session primary/fallback policy on the create contract; `_resolve_runtime_with_fallback` can walk a configured chain at agent build |
| `idempoten*` | Session teardown, process cancel, **billing** `idempotency_key` | **Not** on `session.create` / `prompt.submit` |
| `approval.*(digest\|ttl\|expir\|single)` | **0 matches** | `approval.respond` takes `choice` / `all` only |
| `interrupt.*(idempoten\|reconcil)` | **0 matches** | `session.interrupt` clears turn flags; no Run-scoped idempotent reconcile |

### Inspected line ranges (summary)

- **`_emit` (1138–1152):** gateway events are JSON-RPC notifications
  `method=event` with `params={type, session_id, payload?}` — no durable
  `event_id` or cursor.
- **Agent build / provider (4515–4610):** per-session `model_override` /
  `provider_override` feed `_resolve_runtime_with_fallback`; primary provider
  is not immutably locked at session create, and fallback is internal
  resolution rather than a frozen session policy + Run evidence tuple.
- **`session.create` (5161–5304):** accepts optional `model`/`provider` as a
  per-session override; returns `session_id` / `stored_session_id` / lazy
  `info`; no client idempotency key, request correlation, or Run ID.
- **`session.resume` (5543+):** rebinds transport, may restore/build agent
  (or lazy-register without agent); mutation surface, not authorized by
  read-only chat.
- **`prompt.submit` (8420–8525):** params are essentially `session_id`,
  `text`, optional `truncate_before_user_ordinal`; returns
  `{"status": "streaming"}`; no client request ID / Run ID / provider
  evidence binding.
- **`session.interrupt` (8114–8155):** cooperative interrupt + flag clear;
  returns `{"status": "interrupted"}`; no Run-scoped idempotent
  reconciliation handle.
- **`approval.respond` (10199–10218):** `choice` default deny + optional
  `all`; no command-digest, TTL, or single-use binding.
- **`config.set` (10224+):** can switch session `model` (and thus provider)
  when the session is not busy — primary policy remains unlocked after create.

## Confirmed read surface

session.list, session.status and session.history exist.

## Stateful resume surface

session.resume exists, but rebinds a transport and may restore/build an agent.
It is a separately gated mutation and is not authorized by chat_read_enabled.

## Confirmed mutation surface

session.create, prompt.submit, session.interrupt, approval.respond and config.set
exist. session.create accepts a per-session model/provider override; config.set
can later switch the session model/provider, so the primary policy is not locked.

## Missing recovery contract

session.create and prompt.submit expose no client idempotency key, durable
request-correlation metadata, lookup by client request ID or caller-supplied
Run ID. The inspected session contract does not prove an immutable primary or
fallback provider policy. Events have no
durable event_id/cursor replay contract. The inspected turn output does not
provide immutable requested/actual provider+model, fallback from/to/reason, and
usage evidence bound to the same Run. approval.respond has no command-digest,
TTL, or single-use binding; session.interrupt has no Run-scoped idempotent
reconciliation contract.

These gaps map to the checked-in contract `evidence` flags (all false except
`session_provider_override=true`) and to the capability evaluator blocker codes
`missing_request_recovery`, `missing_run_identity`,
`missing_provider_policy_lock`, `missing_actual_provider_evidence`,
`missing_event_replay` (plus `contract_unreviewed` until Task 4 review lands).
They keep `chat_write_enabled` / `stream_enabled` false; the real Hermes chat
mutation slice stays disabled until a newer observed contract and independent
review say otherwise.

## Admission rule

A bridge implementation plan may be written only after a newly observed
contract makes hqa.hermes_capability_cli verify-chat exit 0 with
review.verdict=ready and installation.matches_snapshot=true. Until then the
platform may display read-only/offline capability state, but session creation,
session resume, prompt submit, streaming, approval and stop remain disabled. The old
/api/agent/tasks endpoint is not a fallback.

## Independent review

Two-stage independent review of Tasks 1–3 completed before writing this
record. Stage A (plan/spec compliance) and Stage B (professional code review)
each returned CLEAR with no unresolved P0/P1 on checklists 1–11. Neither
stage shared its conclusion with the other before completion.

### Worktree baseline (Step 1)

Exact pre-existing `git status --short` at review start (retained verbatim;
not cleaned, staged, reverted, or reinterpreted):

```text
?? .superpowers/
```

### Immutable review inputs (verbatim)

```bash
$ git rev-parse HEAD
c767b758e524e2a3ee15f66ab7618eafbcd87057

$ shasum -a 256 config/hermes-gateway-capabilities.v1.json
d52d375aafb3f9bbff391ea4a5000ee1060c5962fd4852f000a1d377e45c27b9  config/hermes-gateway-capabilities.v1.json

$ date -u +%Y-%m-%dT%H:%M:%SZ
2026-07-13T09:30:52Z
```

`git show c767b758e524e2a3ee15f66ab7618eafbcd87057:config/hermes-gateway-capabilities.v1.json`
is byte-identical to the working default contract (digest above).

| Field | Value |
|---|---|
| Reviewed at | `2026-07-13T09:30:52Z` |
| Contract SHA-256 | `d52d375aafb3f9bbff391ea4a5000ee1060c5962fd4852f000a1d377e45c27b9` |
| Commit reviewed | `c767b758e524e2a3ee15f66ab7618eafbcd87057` |
| Verdict | **BLOCKED** |
| Reason | current Hermes contract lacks deterministic request recovery, replayable event identity, Run identity, immutable provider/fallback policy and actual-provider evidence. |

Machine-readable twin:
[`config/hermes-gateway-capabilities.v1.review.json`](../../config/hermes-gateway-capabilities.v1.review.json)
(`verdict: "blocked"`). Chat write/stream admission remains fail-closed;
`verify-chat` must not exit 0 until a later source-backed contract and a
committed independent `ready` review exist against a clean matching
installation.
