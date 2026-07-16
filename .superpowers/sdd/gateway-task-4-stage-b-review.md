# Stage B Independent Review — Hermes Gateway Capability Contract (Tasks 1–3)

**Reviewer role:** Stage B professional security / correctness review  
**Scope:** Committed Tasks 1–3 only (no Stage A conclusions consulted)  
**Repo:** `/Users/sunyibo/programs/Hermes-quant-agent`  
**Diff package:** `.superpowers/sdd/gateway-tasks-1-3-review.diff`  
**Commits reviewed:** `1b461ef` → `34713d8` → `c767b75` (`2939c04..HEAD`)  
**HEAD at review:** `c767b758e524e2a3ee15f66ab7618eafbcd87057`  
**Contract digest:** `d52d375aafb3f9bbff391ea4a5000ee1060c5962fd4852f000a1d377e45c27b9`  
**Review date:** 2026-07-13  

**Key artifacts:**

| Path | Role |
|---|---|
| `hqa/hermes_capabilities.py` | Strict loader + fail-closed chat gate evaluator |
| `hqa/hermes_capability_cli.py` | `show` / `verify-chat` JSON CLI + review/install gates |
| `config/hermes-gateway-capabilities.v1.json` | Frozen 0.18.2 machine contract |
| `docs/contracts/hermes-gateway-0.18.2.md` | Source-backed evidence |
| `tests/test_hermes_capabilities.py` | Parser / gate unit tests |
| `tests/test_hermes_capability_cli.py` | CLI / review / install unit tests |

**Live reconfirm (read-only, no model call):**

| Probe | Result |
|---|---|
| `hermes --version` | `Hermes Agent v0.18.2 (2026.7.7.2) · upstream b03c94db` |
| source `rev-parse HEAD` | `4281151ae859241351ba14d8c7682dc67ff4c126` |
| tracked `status --porcelain --untracked-files=no` | empty (clean) |
| `server.py` SHA-256 | `2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17` |
| HQA unit tests | `tests/test_hermes_capabilities.py` + `tests/test_hermes_capability_cli.py` → all passed |
| `python -m hqa.hermes_capability_cli verify-chat` | exit **3**, `status=blocked`, `review.blocker=contract_unreviewed` (Task 4 record not yet present — expected) |
| `installation.matches_snapshot` | `true` against live install |

---

## Executive summary

Tasks 1–3 implement a fail-closed, source-backed Hermes gateway capability contract and admission gate. The checked-in 0.18.2 snapshot correctly claims only one true semantic evidence flag (`session_provider_override`) and keeps chat write / stream / resume / approval / stop closed. Bridge admission (`verify-chat` exit 0) cannot open on method names alone, a custom contract, an unreviewed or drifted contract, dirty Hermes source, or installation fingerprint mismatch.

No P0 or P1 defects found. Residual notes are P2 / residual-risk only.

**Stage B overall: CLEAR for Tasks 1–3.**

---

## Checklist (PASS / FAIL with evidence)

### 1. Every true capability is supported by an exact Hermes source/help reference — **PASS**

**True claims in the frozen contract:**

| Claim | Evidence |
|---|---|
| Identity: version `0.18.2`, upstream `b03c94db`, checkout `4281151…`, `server.py` hash | Live `hermes --version`, `git rev-parse`, `shasum` match contract + docs |
| Transport `websocket_jsonrpc` + loopback host/port | `hermes serve --help`: JSON-RPC/WebSocket; default host `127.0.0.1`, port `9119` |
| Endpoint path `/api/ws` | Hermes `hermes_cli/web_server.py` `@app.websocket("/api/ws")` (and multiple gateway URL builders) |
| `relevant_methods_observed` methods exist | Live `@method("…")` registrations at documented lines (`session.create` 5161, `session.list` 5307, `session.resume` 5543, `session.status` 7759, `session.history` 7816, `session.interrupt` 8114, `prompt.submit` 8420, `approval.respond` 10199, `config.set` 10224) |
| **Only true evidence flag:** `session_provider_override=true` | `session.create` 5197–5202 / 5242: per-session `model`/`provider` override into `model_override`; not a global config write |

No other evidence booleans are true. Docs cite exact line ranges and reproduce commands.

### 2. No missing capability is inferred from UI behavior — **PASS**

`docs/contracts/hermes-gateway-0.18.2.md` is built from CLI/help, git fingerprint, and `tui_gateway/server.py` searches/line inspections. Explicit rule: false means the create/submit/event/interrupt/approval/Run contract lacks the semantic guarantee — not “token absent everywhere.” UI/desktop behavior is not used as positive proof of recovery, replay, Run identity, or approval binding.

### 3. `verify-chat` cannot become ready merely because method names exist or a stale snapshot was once ready — **PASS**

Layered fail-closed path in code:

1. **Evaluator** (`evaluate_chat_gate`): method presence alone is insufficient for write. Current methods + mostly-false evidence → `chat_write_enabled=false`, `stream_enabled=false` with blockers `missing_request_recovery`, `missing_run_identity`, `missing_provider_policy_lock`, `missing_actual_provider_evidence`, `missing_event_replay` (`test_known_gateway_is_readable_but_all_chat_mutations_fail_closed`).
2. **Review gate** (`_probe_review` / `_apply_review_gate`): missing / untrusted review → `contract_unreviewed` and closes writes (and reads when untrusted). Custom path → `custom_contract_unreviewed`. Trusted `blocked` verdict → `contract_review_blocked`.
3. **Installation gate** (`_apply_installation_gate`): fingerprint mismatch → `installation_fingerprint_mismatch`; dirty tracked source → `installation_source_dirty`; probe failure → `installation_probe_failed` (closes reads + mutations). Stale ready snapshot against drifted install cannot remain ready.
4. **Admission predicate:** `verify-chat` requires both `chat_write_enabled` and `stream_enabled` true (`test_verify_chat_requires_replay_even_when_submit_is_safe`).
5. **No contract override on verify-chat:** unknown `--contract` → exit 2 (`test_verify_chat_rejects_contract_override`).

Live: current install matches snapshot but review is absent → exit 3, `status=blocked`.

### 4. `session.resume` is not classified as read; bridge admission requires safe submit recovery and replayable stream identity — **PASS**

- `_READ_METHODS = {session.list, session.status, session.history}` — **does not** include `session.resume`.
- Resume is a mutation surface in evidence doc; evaluator requires full stream contract **plus** `session.resume` method (`test_resume_is_never_classified_as_a_read`).
- Write requires recovery (`any` of client idempotency / correlation / lookup-by-client-id) + `run_id` + provider policy lock + `run_provider_evidence`.
- Stream requires write conditions + `event_id` ∧ `event_cursor`.
- `verify-chat` ready = write ∧ stream only; resume remains independent (Task 2 interface).

### 5. Endpoint parsing rejects credentials, query/fragment, wrong paths, non-loopback hosts, invalid ports without reflecting secret text — **PASS**

`load_capabilities` requires:

- scheme ∈ `{ws, wss}`
- hostname ∈ `{127.0.0.1, ::1}` (rejects `0.0.0.0`, `localhost`)
- port ∈ `[1, 65535]`
- path exactly `/api/ws`
- no username/password, params, query, or fragment

All rejections raise the fixed message `Hermes endpoint must be loopback WebSocket` (no reflection of endpoint text). Parametrized tests cover credentialed URL, query+fragment with `token=secret`, wrong path, non-loopback, invalid port, and assert `"secret"` / `"pass"` absent from exception text.

### 6. Custom contract, missing/mismatched review, uncommitted review edit, tracked Hermes source change, or installation drift closes the effective gate — **PASS**

| Condition | Blocker / behavior | Test / live evidence |
|---|---|---|
| Custom `--contract` path | `custom_contract_unreviewed`, closes read+write | `test_custom_show_is_diagnostic_but_never_authoritative`, `test_probe_review_custom_path_never_authorizes` |
| Missing/invalid review schema, bad digest/commit, non-ancestor, reviewed contract differs, working≠HEAD, review working≠HEAD | `contract_unreviewed` | `test_probe_review_rejects_untrusted_records` (9 cases) |
| Trusted `verdict=blocked` | `contract_review_blocked`, mutations closed, reads may remain | `test_verify_chat_returns_three_for_known_blocked_contract` |
| Install fingerprint drift | `installation_fingerprint_mismatch`, closes reads+writes | `test_matching_ready_snapshot_stays_blocked_when_installation_drifted` |
| Tracked source dirty | `installation_source_dirty` | `test_tracked_source_dirty_closes_reads_and_writes` |
| Install probe failure | `installation_probe_failed`; only exception type name in JSON | `test_installation_probe_failed_closes_reads_and_mutations` |

Review binding checks: SHA-256 of contract bytes, 40-char reviewed commit ancestor of HEAD, HEAD and reviewed-commit blobs match working bytes for contract and review record.

### 7. Approval and stop stay independently closed without blocking otherwise-safe ordinary chat — **PASS**

- Approval requires clean chat contract **and** `approval.respond` + digest/TTL/single-use evidence.
- Stop requires `run_id` + `session.interrupt` + idempotent/reconcilable evidence; does **not** force-close ordinary chat when stop is incomplete.
- `test_safe_chat_does_not_open_approval_or_stop_from_method_names`: full recovery/stream evidence with approval/stop evidence false → write/stream true, approval/stop false.
- `test_ready_review_and_matching_installation_open_bridge_admission`: ready admission still leaves `approval_enabled` / `stop_enabled` false.

### 8. No secret, profile credential, state.db content, transcript, or provider token is checked into the contract — **PASS**

Contract JSON contains only schema identity, fingerprints, loopback endpoint without query/auth, method name allowlist, and boolean evidence. Evidence markdown records command output and source line summaries only. Secret-pattern scan of contract + evidence doc found no API keys, bearer tokens, passwords, or state.db payloads. (Hermes source comments mention `state.db` / credentials in *upstream* code paths; those are not copied into the HQA contract.)

### 9. No test invokes Grok, Codex, `prompt.submit`, `session.create`, `session.resume`, paper, or live paths — **PASS**

Capability tests only parse JSON fixtures and evaluate pure functions. CLI tests monkeypatch `_read` / `_probe_review` / `_probe_installation` or use isolated temp git repos for `_probe_review` provenance. Method names appear only as **string literals** in fixtures, never as live JSON-RPC calls. No paper/live/trading paths, no provider clients, no network model calls.

### 10. `relevant_methods_observed` is an allowlisted subset, not a complete server registry freeze — **PASS**

Evidence doc table lists many additional `@method` registrations (`session.most_recent`, `session.delete`, `prompt.background`, `config.get`, etc.) and marks the contract list as an **allowlisted subset** in bold. Loader accepts the list as observational strings; it does not assert equality with the full Hermes method set.

### 11. Primary-provider/model immutability, fallback-policy immutability, and complete per-Run requested/actual/fallback/usage evidence are proved separately; targeted searches support every false value — **PASS**

Separate evidence keys:

| Flag | Frozen value | Source support |
|---|---|---|
| `session_primary_provider_policy_immutable` | **false** | `session.create` accepts model/provider override; `config.set` model path can switch provider/model when not busy (10224+) |
| `session_provider_fallback_policy_immutable` | **false** | Agent build uses `_resolve_runtime_with_fallback` (4515–4588); fallback is internal resolution chain, not frozen session policy |
| `run_provider_evidence` | **false** | No `actual_provider` on Run; `prompt.submit` returns `{"status":"streaming"}` only; no immutable requested/actual/fallback/usage tuple bound to a Run |
| `client_idempotency_key` / `request_correlation_metadata` / `request_lookup_by_client_id` | **false** | 0 matches for `client_request`, `request_correlation`, `request_lookup`; `idempoten*` only teardown/billing/process — not create/submit |
| `run_id` | **false** | 0 `run_id` matches; create returns `session_id` / `stored_session_id` only |
| `event_id` / `event_cursor` | **false** | `_emit` (1140–1144): `{type, session_id, payload?}` only |
| `approval_*` | **false** | `approval.respond` takes `choice` / `all` only (10199–10216) |
| `stop_idempotent` / `stop_reconcilable` | **false** | `session.interrupt` clears flags / returns `interrupted`; no Run-scoped idempotent reconcile handle |
| `session_provider_override` | **true** | Proved separately (see item 1) |

Evaluator requires **both** primary and fallback immutability for `provider_policy_locked` (`test_primary_and_fallback_provider_policies_must_both_be_immutable`).

---

## Findings

### P0 — none

### P1 — none

### P2 / residual notes (non-blocking)

1. **Process identity is intentionally out of scope.** Installation probe matches CLI version string + source checkout + `server.py` hash + tracked cleanliness. It does **not** prove a live gateway process, PID, or handshake. Plan/docs already defer runtime process identity to a later bridge slice. Residual operational risk only.

2. **Custom-contract path comparison is string/`Path` equality, not resolved path equality.** `contract_path != config.HERMES_GATEWAY_CAPABILITIES_PATH` may treat a relative path to the same default file as “custom,” which is **fail-closed** (over-strict diagnostic), not an admission bypass. `verify-chat` never accepts a contract override.

3. **CLI unit-test install mock still uses plan-era upstream `e4ea0a0e`** in `tests/test_hermes_capability_cli.py::_contract()`, while the frozen live contract uses reconfirmed `b03c94db`. Mocks are isolated from production load paths; hygiene-only risk of reader confusion.

4. **Static contract endpoint forbids query strings** while some Hermes dashboard builders append auth tickets (`/api/ws?…`). Correct for a secrets-free frozen contract; a future bridge must not store tokens inside the capability snapshot.

---

## Security posture summary

| Area | Assessment |
|---|---|
| Injection / shell | `subprocess` uses `shell=False`, fixed argv; no user-controlled shell strings |
| Secrets in repo | None in contract/evidence |
| Error leakage | Install failures expose exception type only; endpoint errors do not echo URL secrets |
| AuthZ / admission | Multi-layer fail-closed; write/stream require evidence + trusted ready review + matching clean install |
| Least privilege | Approval/stop independent; resume not a read; custom contracts non-authoritative |
| Trading safety | No paper/live/trading surface introduced |

---

## Gate recommendation for Task 4

Tasks 1–3 are acceptable as the immutable inputs for Task 4 independent review recording.

Expected Task 4 machine record for this frozen snapshot:

- `verdict`: **`blocked`**
- Reason (plan-mandated): current Hermes contract lacks deterministic request recovery, replayable event identity, Run identity, immutable provider/fallback policy and actual-provider evidence.
- After commit of the review record: `verify-chat` should remain exit 3 with `contract_review_blocked` (trusted blocked) rather than `contract_unreviewed`, while read list/status/history may reopen under a trusted blocked review + matching install.

Do **not** set `verdict=ready` against the current 0.18.2 evidence.

---

STAGE_B_VERDICT: CLEAR
