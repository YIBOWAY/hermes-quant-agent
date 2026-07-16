# Gateway Task 1 Review — Strict capability snapshot and fail-closed evaluator

**Reviewer role:** Task-scoped gate + Python quality  
**Base:** `2939c0487268acc0546e999b26b55d49dbebdae8`  
**Head:** `1b461efa2ac00ecfb1d3f29453149b746335f9c9`  
**Diff scope:** 4 files, +521 lines (exactly the Task 1 file set)

---

### Spec Compliance

- ✅ **Files delivered** — Creates `tests/test_hermes_capabilities.py`, `hqa/hermes_capabilities.py`, `config/hermes-gateway-capabilities.v1.json`; modifies `hqa/config.py` only. Commit is single-purpose with the prescribed message.
  - Evidence: commit `1b461ef` name-only list matches brief file set; no Hermes checkout edits; no Task 2+ CLI/docs/review-record files.

- ✅ **Interfaces** — `load_capabilities(Path) -> HermesGatewayCapabilities` and `evaluate_chat_gate(...) -> HermesChatGate` present with exact field sets from the brief.
  - Evidence: `hqa/hermes_capabilities.py:121-163`, `188`, `271`.

- ✅ **Strict parser / fail-closed schema** — Exact top-level keys, exact evidence keys, schema `1.0`, transport `websocket_jsonrpc`, non-empty identity strings, boolean evidence (exact `bool`), loopback-only WebSocket endpoint (`ws`/`wss`, host `127.0.0.1`/`::1`, path `/api/ws`, no userinfo/query/fragment/params, valid port), no credential leakage in errors.
  - Evidence: `hqa/hermes_capabilities.py:188-268`; rejection tests `tests/test_hermes_capabilities.py:549-577`.

- ✅ **Independent gates** — Read (list/status/history methods), write (chat methods + recovery + run_id + provider policy lock + actual provider evidence), stream (+ event_id∧event_cursor), resume (+ `session.resume`, never under read), approval (chat contract + digest/ttl/single-use), stop (run_id + interrupt + idempotent/reconcilable).
  - Evidence: `hqa/hermes_capabilities.py:271-337`; tests `tests/test_hermes_capabilities.py:399-547`.

- ✅ **Known snapshot fails closed for mutations, read open** — Committed JSON has only `session_provider_override: true`; all recovery/run/event/approval/stop evidence false.
  - Evidence: `config/hermes-gateway-capabilities.v1.json:41-56`; smoke load yields `chat_read_enabled=True`, all mutation gates `False` with expected blocker tuples.

- ✅ **Controller-approved source-review exception** — `upstream_commit` is `b03c94db` (not plan-frozen `e4ea0a0e`); checkout/server digest unchanged; `observed_at` reconfirm timestamp. No invented `true` evidence flags.
  - Evidence: snapshot + test `_document()` use `b03c94db` / `2026-07-13T09:13:45Z`; `source_checkout_commit` and `server_source_sha256` match plan values.

- ✅ **Config admission anchors** — `HERMES_GATEWAY_CAPABILITIES_PATH` / `HERMES_GATEWAY_REVIEW_PATH` not env-overridable; `HERMES_BIN_PATH` / `HERMES_SOURCE_DIR` env-overridable as specified.
  - Evidence: `hqa/config.py` (post-`SIGNAL_THRESHOLDS_PATH` block in commit).

- ✅ **Global constraints respected for this slice** — No browser secret path; loopback enforced; no platform POST fallback; write/stream disabled without recovery/replay evidence; resume not authorized by read; hermetic tests (`tmp_path` only); safety baseline constants untouched; dirty worktree / installed Hermes not mutated.

- ✅ **TDD GREEN** — Focused suite: 19 passed (`./.venv/bin/pytest -q tests/test_hermes_capabilities.py`).

- ⚠️ **Cannot verify from diff alone** — Preflight live `hermes --version` / checkout HEAD / empty tracked status / server SHA were reported by implementer; not re-executed as part of this review (controller already approved source exception; digest values in snapshot match plan).

---

### Strengths

- Near line-faithful implementation of the prescribed parser/evaluator; little room for silent behavioral drift from the plan.
- Fail-closed defaults are real: known production snapshot keeps write/stream/resume/approval/stop closed with stable, test-pinned blocker codes.
- Endpoint validation is careful about secrets (generic errors; no echo of query/userinfo) and rejects `localhost` / non-loopback / non-`/api/ws`.
- Pure functions + frozen dataclasses: easy to unit-test, no I/O beyond `path.read_text`, no network.
- Scope discipline: one commit, four files, Tasks 2–4 left alone.
- Python 3.9-safe (`from __future__ import annotations` with modern generics).

---

### Issues

#### Critical
None.

#### Important
None.

#### Minor

1. **Committed snapshot not loaded by unit tests**  
   File: `tests/test_hermes_capabilities.py` (uses `tmp_path` + `_document()` only)  
   Issue: A drift between `_document()` and `config/hermes-gateway-capabilities.v1.json` would not fail this suite. Behavior currently matches (smoke-checked), and the brief does not require a file-path test; Task 2 `verify-chat` likely covers live anchors.  
   Fix (optional later): one hermetic test that `load_capabilities(HERMES_GATEWAY_CAPABILITIES_PATH)` yields the known fail-closed gate.

2. **`HermesChatGate.to_dict` return type is bare `dict`**  
   File: `hqa/hermes_capabilities.py:162`  
   Issue: Minor typing imprecision (`dict` vs `dict[str, object]`). Matches brief; non-blocking.

3. **`type(evidence[key]) is not bool`**  
   File: `hqa/hermes_capabilities.py:228`  
   Issue: Usually prefer `isinstance`, but exact-`bool` is intentional here (reject truthy non-bools) and is prescribed. Leave as-is.

4. **`blockers` is stream-level, not write-level**  
   File: `hqa/hermes_capabilities.py:333`  
   Issue: Name can mislead callers (`blockers` includes `missing_event_replay` even when write would be open). Correct per brief/tests; document in Task 2 CLI output if exposed.

---

### Assessment

**Task quality:** Approved  
**Reasoning:** The implementation matches the Task 1 brief and global constraints, including the controller-approved `b03c94db` snapshot update; gates fail closed correctly, tests are hermetic and green, and scope stayed within the four prescribed files with no Important/Critical defects.
