# Stage A Independent Review — Hermes Gateway Capability Contract Tasks 1–3

**Role:** Stage A plan/spec compliance reviewer (isolated; no review.json)  
**Repo:** `/Users/sunyibo/programs/Hermes-quant-agent`  
**Branch:** `codex/full-9h`  
**Reviewed range:** `2939c04..HEAD`  
**Commits:**
- `1b461ef` feat(hqa): add fail-closed Hermes gateway capability contract
- `34713d8` feat(hqa): expose Hermes chat readiness as strict JSON
- `c767b75` docs(hermes): freeze gateway contract and chat admission gate

**Diff package:** `.superpowers/sdd/gateway-tasks-1-3-review.diff`  
**Plan:** `docs/superpowers/plans/2026-07-13-hermes-gateway-capability-contract.md`  
**Primary artifacts:**
- `docs/contracts/hermes-gateway-0.18.2.md`
- `config/hermes-gateway-capabilities.v1.json`
- `hqa/hermes_capabilities.py`
- `hqa/hermes_capability_cli.py`
- `tests/test_hermes_capabilities.py`
- `tests/test_hermes_capability_cli.py`
- `hqa/config.py` (admission anchors)
- `docs/README.md`, design §14 updates

**Live reconfirm (Stage A, 2026-07-13):**
- `hermes --version` → `Hermes Agent v0.18.2 (2026.7.7.2) · upstream b03c94db`
- checkout HEAD → `4281151ae859241351ba14d8c7682dc67ff4c126`
- tracked status → empty
- `tui_gateway/server.py` SHA-256 → `2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17`
- focused pytest → green (`tests/test_hermes_capabilities.py` + `tests/test_hermes_capability_cli.py`)
- live `python -m hqa.hermes_capability_cli verify-chat` → exit 3, `status=blocked`, `review.blocker=contract_unreviewed`, `installation.matches_snapshot=true`

**Note on plan-era upstream:** plan text freezes plan-era `e4ea0a0e`; preflight requires reconfirm and source-review update on drift. Implementation correctly reconfirmed live `b03c94db` in snapshot + evidence (checkout/server digest unchanged). This is plan-compliant process, not silent inventing of true capabilities.

---

## Checklist (11 items)

### 1. Every true capability is supported by an exact Hermes source/help reference — **PASS**

**True claims in the checked-in contract**

| Claim | Value | Exact reference |
|---|---|---|
| Hermes version / upstream | `0.18.2` / `b03c94db` | Evidence `docs/contracts/hermes-gateway-0.18.2.md:16-17,69-75`; live `hermes --version` |
| Source checkout | `4281151ae859241351ba14d8c7682dc67ff4c126` | Evidence `:18,81-85`; live `git rev-parse HEAD` |
| `server_source_sha256` | `2a05d…7d17` | Evidence `:19,93-97`; live `shasum -a 256 …/server.py` |
| Transport + loopback host/port | `websocket_jsonrpc`, `127.0.0.1:9119`, `loopback_only=true` | Evidence `:21,77-79`; live `hermes serve --help` |
| Allowlisted methods exist | 9 methods | Evidence method table `:99-130` with line numbers; live `@method` registrations at 5161/5307/5543/7759/7816/8114/8420/10199/10224 |
| Sole true evidence flag `session_provider_override` | `true` | Evidence `:155-160,159-161,188-190`; live `session.create` accepts `model`/`provider` as per-session override (`server.py` ~5200–5210) |

Snapshot evidence object (`config/hermes-gateway-capabilities.v1.json:22-38`) has **only** `session_provider_override: true`; every other evidence flag is `false`. No invented true recovery/replay/approval/stop capability.

**Minor note (not a FAIL):** evidence identity table cites default endpoint as `ws://127.0.0.1:9119` without restating path `/api/ws`. The path is plan-frozen and present in Hermes source (`hermes_cli/web_server.py` `@app.websocket("/api/ws")`, `tui_gateway/ws.py`). Host/port come from help; path is not inferred from UI.

---

### 2. No missing capability is inferred from UI behavior — **PASS**

Missing/false capabilities are derived from:

1. Targeted `server.py` searches and zero-result tables (`docs/contracts/hermes-gateway-0.18.2.md:132-148`)
2. Inspected line ranges for create/submit/resume/interrupt/approval/config/events (`:150-175`)
3. Explicit semantic rule that token presence in billing/teardown/internal resolver code is **not** a D-31 guarantee (`:60-63,133`)

Help text is cited as headless / no browser UI (`:78`). No checklist claim depends on desktop composer behavior alone. Method existence is from `@method` registrations, not UI labels.

---

### 3. `verify-chat` cannot become ready merely because method names exist or a stale snapshot was once ready — **PASS**

**Method names alone never open write/stream**

Evaluator write path (`hqa/hermes_capabilities.py:164-192`) requires:
- chat methods present **and**
- at least one of client idempotency / correlation / lookup recovery **and**
- `run_id` **and**
- provider policy lock (override + primary immutable + fallback immutable) **and**
- `run_provider_evidence`

Stream additionally requires `event_id ∧ event_cursor` (`:175,193-195`).

Known snapshot methods are present but recovery/run/policy/evidence/replay are false → declared gate remains closed:

```text
blockers = missing_request_recovery, missing_run_identity,
           missing_provider_policy_lock, missing_actual_provider_evidence,
           missing_event_replay
```

Evidence: `tests/test_hermes_capabilities.py:56-82`; live load of default contract.

**`verify-chat` readiness is stricter still**

`hqa/hermes_capability_cli.py:308-313` exits 0 only when **effective** `chat_write_enabled` and `stream_enabled` are both true after:

1. declared evaluation
2. review provenance (`_apply_review_gate`, `:190-201`)
3. installation fingerprint (`_apply_installation_gate`, `:253-284`)

**Stale / once-ready cannot reopen on drift**

- Review digests exact contract bytes; digest mismatch → `contract_unreviewed` (`:101-104`, tests `digest_mismatch`)
- Reviewed commit must contain identical contract bytes (`:137-138`, test `reviewed_contract_differs`)
- Working/HEAD contract must match (`:135-136`, test `working_differs_from_head`)
- Review HEAD blob must match working review bytes (`:139-140`, test `review_bytes_differ_from_head`)
- Installation drift closes even ready+matching-methods (`:253-284`, test `test_matching_ready_snapshot_stays_blocked_when_installation_drifted:121-140`)

Live `verify-chat` today: exit 3 with `contract_unreviewed` despite methods present and install match.

---

### 4. `session.resume` is not classified as read; bridge admission requires both safe submit recovery and replayable stream identity — **PASS**

**Resume ≠ read**

```59:60:hqa/hermes_capabilities.py
_READ_METHODS = frozenset({"session.list", "session.status", "session.history"})
_CHAT_METHODS = frozenset({"session.create", "prompt.submit"})
```

`session.resume` is absent from `_READ_METHODS`. Read gate ignores resume. Resume gate starts from stream blockers and additionally requires the method (`:196-198`). Test: `tests/test_hermes_capabilities.py:101-111` (`test_resume_is_never_classified_as_a_read`).

Evidence doc (`:181-184`) states resume rebinds transport / may restore agent and is not authorized by `chat_read_enabled`.

**Bridge admission = write + stream (recovery + replay)**

```308:313:hqa/hermes_capability_cli.py
enabled = (
    document["gate"]["chat_write_enabled"] is True
    and document["gate"]["stream_enabled"] is True
)
```

Write embeds request recovery (`:168-174,184-185`); stream embeds event replay (`:175,193-195`). Test: `test_verify_chat_requires_replay_even_when_submit_is_safe` (`tests/test_hermes_capability_cli.py:91-100`) keeps exit 3 when write is open but stream is not. Resume remains an independent, stricter gate and is not used as the admission predicate.

---

### 5. Endpoint parsing rejects credentials, query/fragment, wrong paths, non-loopback hosts and invalid ports without reflecting secret text — **PASS**

Parser (`hqa/hermes_capabilities.py:122-143`):

- scheme ∈ `{ws, wss}`
- hostname ∈ `{127.0.0.1, ::1}` (rejects `0.0.0.0`, `localhost`)
- port required and ∈ `[1, 65535]` (rejects `99999`)
- path must be exactly `/api/ws`
- rejects username/password, params, query, fragment
- fixed error text: `"Hermes endpoint must be loopback WebSocket"` (no endpoint echo)

Tests (`tests/test_hermes_capabilities.py:206-234`) parametrize unsafe endpoints including:

- `ws://0.0.0.0:9119/api/ws`
- `ws://localhost:9119/api/ws`
- `ws://127.0.0.1:9119/other`
- `ws://127.0.0.1:9119/api/ws?token=secret#fragment`
- `ws://user:pass@127.0.0.1:9119/api/ws`
- `ws://127.0.0.1:99999/api/ws`

and assert `"secret"` / `"pass"` never appear in `CapabilityContractError` text.

---

### 6. Custom contract, missing/mismatched review record, uncommitted review edit, tracked Hermes source change, or installation drift closes the effective gate — **PASS**

| Condition | Blocker / behavior | Evidence |
|---|---|---|
| Custom `--contract` on `show` | `custom_contract_unreviewed`; closes read+mutations | CLI `:76-82`; test `:48-70` |
| `verify-chat --contract` | argparse reject exit 2 | CLI subparser has no `--contract`; test `:180-184` |
| Missing / invalid review schema / fields | `contract_unreviewed`, `trusted=false`, closes read | CLI `:83-154`; table tests missing/unknown fields |
| Digest / commit mismatch, non-ancestor, reviewed bytes differ | `contract_unreviewed` | tests cases `invalid_digest`, `invalid_commit`, `digest_mismatch`, `reviewed_not_ancestor`, `reviewed_contract_differs` |
| Uncommitted review edit (working ≠ HEAD review blob) | `contract_unreviewed` | test case `review_bytes_differ_from_head` (`:384-395`) |
| Working contract ≠ HEAD blob | `contract_unreviewed` | test case `working_differs_from_head` |
| Tracked Hermes source dirty | `installation_source_dirty`, closes read+mutations | CLI `:266-267`; test `:161-177` |
| Installation fingerprint drift | `installation_fingerprint_mismatch`, closes read+mutations | CLI `:269-273`; test `:121-140` |
| Probe exception | `installation_probe_failed`, no stderr leak | CLI `:274-277`; test `:187-217` |

`_close_gate` (`:169-187`) forces write/stream/resume/approval/stop false and optionally read false; appends blocker to all blocker lists.

Trusted but non-ready review (`verdict=blocked`) yields `contract_review_blocked` and keeps read open while closing mutations (`:155-159,195`) — also fail-closed for bridge admission.

---

### 7. Approval and stop stay independently closed without blocking otherwise-safe ordinary chat — **PASS**

Evaluator separates gates (`hqa/hermes_capabilities.py:199-216`):

- Approval: requires chat contract **and** `approval.respond` + digest/ttl/single-use
- Stop: requires `run_id` **and** `session.interrupt` + stop_idempotent/reconcilable
- Neither is required for `chat_write_enabled` / `stream_enabled`

Test `test_safe_chat_does_not_open_approval_or_stop_from_method_names` (`tests/test_hermes_capabilities.py:157-178`): full chat evidence true, approval/stop evidence false → write/stream true, approval/stop false with `missing_approval_binding` / `missing_stop_contract`.

CLI admission test (`tests/test_hermes_capability_cli.py:103-118`) opens `status=ready` while asserting `approval_enabled` and `stop_enabled` remain false.

---

### 8. No secret, profile credential, state.db content, transcript, or provider token is checked into the contract — **PASS**

`config/hermes-gateway-capabilities.v1.json` contains only:

- identity fingerprints (version, commits, server source digest)
- transport/endpoint/loopback
- allowlisted method names
- boolean evidence flags

No API keys, bearer tokens, profile credentials, `state.db` payloads, transcripts, or provider secrets.

Evidence doc references paths and source semantics (including that resume may open profile `state.db`) as **behavioral description**, not checked-in secret material (`docs/contracts/hermes-gateway-0.18.2.md`). CLI installation actual emits only version/upstream/checkout/sha/clean or `{"error": "<ExceptionType>"}` — never subprocess stderr (`hqa/hermes_capability_cli.py:244-250,274-276`).

---

### 9. No test invokes Grok, Codex, `prompt.submit`, `session.create`, `session.resume`, paper, or live paths — **PASS**

Scanned `tests/test_hermes_capabilities.py` and `tests/test_hermes_capability_cli.py`:

- Method names appear **only as JSON fixture strings** in `relevant_methods_observed` (and removals for negative tests)
- No WebSocket client, no Hermes RPC invoke, no provider SDK call
- No paper/live trading path, no Grok/Codex references
- CLI tests monkeypatch `_read`, `_probe_review`, `_probe_installation` (or use temp git repos for review provenance only)
- Subprocess usage in CLI unit tests is limited to local temp `git` for review probes — not Hermes session mutation

This matches plan global constraint: hermetic tests, no provider/network/session mutation.

---

### 10. `relevant_methods_observed` is explicitly an allowlisted subset, not a claim to freeze the complete server registry — **PASS**

- Plan (`docs/superpowers/plans/2026-07-13-hermes-gateway-capability-contract.md:36,112`): audited allowlist, never complete registry
- Snapshot lists exactly 9 methods (`config/hermes-gateway-capabilities.v1.json:11-21`)
- Evidence doc (`:99-130`) prints a wider method table and **bolds only the allowlisted subset**, explicitly labeling non-contract methods (`session.most_recent`, `session.usage`, `prompt.background`, `config.get`, etc.)
- Live `@method` search shows additional registrations beyond the nine — contract does not claim completeness
- Evaluator only checks allowlisted membership for read/chat/resume/approval/stop method requirements; it never asserts “registry equals snapshot”

---

### 11. Primary-provider/model immutability, fallback-policy immutability, and complete per-Run requested/actual/fallback/usage evidence are proved separately; targeted source searches support every false value — **PASS**

**Separate fields (not collapsed)**

Snapshot/evidence keys are distinct (`config/hermes-gateway-capabilities.v1.json:24-32`):

- `session_primary_provider_policy_immutable: false`
- `session_provider_fallback_policy_immutable: false`
- `run_provider_evidence: false`

Evaluator requires **both** immutability flags (plus override) for policy lock and separately requires `run_provider_evidence` (`hqa/hermes_capabilities.py:176-191`). Test `test_primary_and_fallback_provider_policies_must_both_be_immutable` falsifies primary alone and expects `missing_provider_policy_lock` (`tests/test_hermes_capabilities.py:129-141`).

Plan public interface note (`plan:112`) defines `run_provider_evidence=true` as one immutable Run-scoped record of requested/actual provider+model, fallback from/to/reason, and usage.

**Targeted searches / line inspections for every false evidence value**

| False flag | Support |
|---|---|
| `client_idempotency_key` / `request_correlation_metadata` / `request_lookup_by_client_id` | 0 matches for `client_request`, `request_correlation`, `request_lookup`; create/submit params lack recovery fields (evidence `:137-139,159-168`; live reconfirm 0 hits) |
| `run_id` | 0 matches; submit returns `{"status":"streaming"}` only (`:140,165-168`) |
| `event_id` / `event_cursor` | 0 matches; `_emit` carries `type`+`session_id` only (`:141-142,152-154`; live `_emit` 1138–) |
| `session_primary_provider_policy_immutable` | create accepts model/provider override; `config.set` can switch model (`:155-160,174-175,188-190`) |
| `session_provider_fallback_policy_immutable` | `_resolve_runtime_with_fallback` / internal fallback chain; not frozen session policy (`:145,155-158`) |
| `run_provider_evidence` | `actual_provider` 0; no Run-bound requested/actual/fallback/usage tuple (`:143-144,198-200`) |
| `approval_command_digest_binding` / `approval_ttl` / `approval_single_use` | approval pattern 0; `approval.respond` takes `choice`/`all` only (`:147,172-173`; live 10199–) |
| `stop_idempotent` / `stop_reconcilable` | interrupt pattern 0; interrupt clears flags, returns interrupted (`:148,169-171`; live 8114–) |

Evidence explicitly warns that unrelated `idempoten*` / `fallback` / billing hits are not D-31 recovery (`:146-147,60-63`).

---

## P0 / P1 defects

### P0
None.

### P1
None.

### Non-blocking notes (P2 / informational; do not block Stage A)

1. **Evidence endpoint path citation incomplete:** identity table omits `/api/ws` while snapshot requires it. Path is real in Hermes source; host/port are help-backed. Consider citing `web_server.py` / `tui_gateway/ws.py` in a later doc polish.
2. **Unit suite does not load the committed JSON path:** capability tests rebuild `_document()` in `tmp_path`. Currently bytes match; a drift test against `HERMES_GATEWAY_CAPABILITIES_PATH` would harden Task 1 further (optional).
3. **`rg` may be missing from default PATH** on this host; evidence commands still list `rg`. Reproducers can use equivalent `grep`/bundled ripgrep (already noted in Task 3 report).
4. **Task 4 still required:** live gate correctly stays `contract_unreviewed` until independent review JSON is committed. Not a defect of Tasks 1–3.

---

## Plan delivery cross-check (Tasks 1–3)

| Task | Required deliverables | Status |
|---|---|---|
| 1 | `hqa/hermes_capabilities.py`, tests, snapshot JSON, config anchors | Present; fail-closed evaluator matches plan implementation |
| 2 | `hqa/hermes_capability_cli.py`, CLI tests, review/install gates | Present; `show`/`verify-chat` JSON exit codes match plan |
| 3 | evidence doc, README admission language, design §14 | Present; bridge plan gated on `verify-chat` ready + install match; `/api/agent/tasks` not fallback |

No platform production files changed. No Hermes checkout edits. Review record intentionally deferred to Task 4.

---

## Summary table

| # | Checklist item | Verdict |
|---|---|---|
| 1 | True capabilities have exact Hermes source/help refs | **PASS** |
| 2 | Missing capabilities not inferred from UI | **PASS** |
| 3 | `verify-chat` not ready from method names / stale ready | **PASS** |
| 4 | Resume not read; bridge needs recovery + stream identity | **PASS** |
| 5 | Endpoint rejects unsafe forms without secret reflection | **PASS** |
| 6 | Custom/unreviewed/dirty/drift closes effective gate | **PASS** |
| 7 | Approval/stop independent; do not block safe chat | **PASS** |
| 8 | No secrets/credentials/transcripts in contract | **PASS** |
| 9 | Tests invoke no Grok/Codex/submit/create/resume/paper/live | **PASS** |
| 10 | `relevant_methods_observed` is allowlisted subset | **PASS** |
| 11 | Primary/fallback immutability and Run evidence proved separately | **PASS** |

| Severity | Count |
|---|---|
| P0 | 0 |
| P1 | 0 |
| P2 notes | 4 (non-blocking) |

---

STAGE_A_VERDICT: CLEAR — no unresolved P0/P1
