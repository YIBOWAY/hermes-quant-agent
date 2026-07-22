# ADR: L2a-Send Thin Browser Write Rail

- **Status:** Accepted (design freeze) + **M1+M2 implementation ACCEPT@2026-07-22**
- **Date:** 2026-07-22
- **Context:** Agent v0.2 after local dark enablement (real Hermes adapter +
  mutation flags). ComposerDock is still `preventDefault`-only. Plan-V6 UI and
  public chat cutover are **out of scope** for this package.
- **Grilling:** `/grill-with-docs` session; decisions Q1–Q25 locked with user.
- **Follow-on:** L2b-Observe M1+M2 ACCEPT@2026-07-22 (lifecycle + messages preview);
  L3a-Transcript M1 ACCEPT@2026-07-22 (workbench Conversation canvas);
  L3b-Transcript-Polish M1 ACCEPT@2026-07-22 (no-flicker / stick / optimistic user /
  shared canvas); L4a-Task-Drawer M1 ACCEPT@2026-07-22 (command Activity from
  snapshot `commands[]`; Task/Attempt authority still empty). Plan-V6 full UI /
  SSE / public V8 still open.

## 1. Problem

The browser cannot yet:

1. obtain a loopback owner gate and ensure a managed session;
2. submit one user turn such that the prompt is encrypted in the HQA
   Intent Payload Store;
3. record `conversation.turn` on the platform ledger with store-authoritative
   payload binding;
4. have the supervised worker bind/resolve that payload and dispatch the real
   prompt to Hermes.

Without this rail, local `chat_write_ready` only unlocks a draft UI.

## 2. Decision summary

Deliver **L2a-Send** as one construction package with two milestones:

| Milestone | Meaning |
|---|---|
| **M1** | Contract + failure shapes: composite BFF, FE clients, owner gate, receipt/snapshot reconcile. Store may be faked in tests. |
| **M2** | Live local dark: real Keychain-backed store put, worker `bind`→`resolve`, Hermes delivered with user prompt marker. |

**Critical path after L2a-Send:** L2b observe spine → L3 workbench UI → L4a Activity →
L4b SSE follow spine → remaining Plan-V6 (approvals/a11y/richer projections) → V7
verticals (after contract freeze) → V8 public cutover. Plan-V6 remains the
official UI slice name; L2a-Send is **not** Plan-V6 acceptance.

## 3. Locked decisions

### Sequencing and package (Q1–Q4, Q10, Q12)

- All of Plan-V6 UI, observe, and submit are needed eventually; sequence is
  **thin-rail-first**, not “V6 vs submit” dichotomy.
- Next cut is **L2a-Send only** (not full Plan-V6).
- Exit line: M1 shapes green + M2 live dark green (see §7).
- L2a.1 payload is **inside** L2a-Send M2, not a later bolt-on after L2b.
- One package, two milestones (M1/M2); do not ship “FE-only submit” as done.

### Browser flow (Q5–Q9, Q13, Q17–Q18, Q20, Q23)

- **Owner gate:** loopback auto bootstrap cookie + CSRF (not a multi-user
  login/user module).
- **Create then turn:** if no managed session, FE calls existing
  `POST …/act` `create_managed_session` first; composite **requires**
  `managed_session_ref`.
- **Composite Turn Submit (A2):** one browser POST; BFF puts then turns.
  Public put-then-act is rejected.
- **HTTP contract:**
  - `POST /api/agent/workspace/submit-turn`
  - Body: `{ workspace_id, managed_session_ref, client_action_id, prompt }`
  - Same CSRF rules as `/act`
  - **`/act` stays prompt-free** forever in this design
- **Idempotency:** FE generates one UUID per send gesture =
  `client_action_id` ≡ store `client_intent_id`. Retries reuse the same id;
  a new click gets a new id. Create keeps its own `client_action_id`.
- **Mid-flight failure:** put ok + turn unknown/fail → receipt
  `outcome_unknown` (+ optional `reason_code`). FE may retry **same** body.
  No compensating delete of payload; orphans expire via TTL.
- **UI reconcile:** action receipt card + snapshot refresh (not toast-only).
- **Size:** chat rail hard cap **16 KiB UTF-8** at FE, BFF, and dispatch
  adapter. Empty/whitespace → 400, no put. No silent truncation. Store’s
  256 KiB ceiling remains for future research kinds only.

### Payload authority (Q11, Q14–Q16, Q19, Q21–Q22, Q24)

- **Sole body authority:** HQA `IntentPayloadStore` (reuse, do not fork a
  platform blob table).
- **Digest:** store envelope content address (canonical envelope including
  timestamps/policy), **not** `sha256(textarea)`.
- **Crypto:** live M2 = `MacOSKeychainCrypto` via
  `HQA_INTENT_PAYLOAD_CRYPTO_HELPER` (same posture as `intent_retention_cli`).
  Tests = `DeterministicCryptoFake`. **No plaintext mode; no silent downgrade
  to Fake on live.**
- **Platform ↔ HQA:** subprocess CLI Port only; platform must not import
  `hqa`.
- **CLI surface** (`python -m hqa.intent_payload_cli`):
  - `put` — stdin put-request JSON → stdout metadata receipt
  - `bind_resolve` — stdin ref+scope+`consumer_ref` → in-process bind
    (idempotent) + resolve → stdout `{ok, prompt}` **only** on parent pipe
  - Secrets never on argv/env/logs. Not a public ops dump tool.
  - `intent_retention_cli` unchanged.
- **Worker path:** before Hermes POST, worker calls `bind_resolve` with
  `consumer_ref = command:<ledger_command_id>`. Plaintext exists only inside
  `input_resolver` → Hermes request. BFF never resolves.
- **Default resolvers:** `metadata_input_resolver` / `fixed_input` remain for
  smoke and non-chat paths; **M2 acceptance must not use them as the chat path.**

### Dark Identity Profile (Q14, Q21–Q22)

Single shared module/constants used by BFF put **and** worker resolve:

| Field | Value |
|---|---|
| Platform workspace id | `ws-local-main` |
| Store `owner_id` | `owner-local-root` (not the UUID string) |
| Store `workspace_id` | `workspace:ws-local-main` |
| Store `session_id` | `managed_session_ref` if already `session:…`, else `session:` + bare platform session id |
| `kind` | `conversation_turn` |
| `schema_version` | `2.0` |
| `ttl_days` | `7` |
| `provider_policy` | `{"primary":{"provider":"openai","model":"gpt-5"},"fallbacks":[]}` |
| `provider_policy_digest` | SHA-256 of store canonical JSON **without** trailing newline — locked value: `be9265ec683224ba28643b01938dba87d2642944f3a0516ccb9ff0126f872e31` |

Rules:

- FE never sends store owner/policy/ttl.
- Create managed session uses the **same** `provider_policy_digest` as put.
- L2a only admits workspace `ws-local-main` on this profile (fail closed otherwise).

### Payload ref normalization

| Surface | Form |
|---|---|
| Store receipt | `payload:sha256:<digest>` |
| Workspace action binding | `payload:sha256:<digest>` + `payload_digest` |
| Platform ledger / helper | `platform-payload://sha256/<digest>` via existing mapper |
| Worker → store CLI | normalize any of the above to digest, then `payload:sha256:<digest>` |

## 4. Non-goals (this package)

- Plan-V6 full Web Chat UI polish, follow completeness, research_* execution
- Public chat write cutover (V8) / treating local flags as public ready
- Live trading; kill_switch stays true
- Multi-user accounts, signup, OAuth
- In-process platform import of HQA
- BFF saga table / distributed put-turn transaction
- Raising chat limit to 256 KiB
- Always-on launchd supervised daemon (optional follow-up)
- Commit/push (await explicit user request)

## 5. Component plan (implementation order when unblocked)

1. **HQA** `intent_payload_cli` (`put`, `bind_resolve`) + unit tests (Fake crypto).
2. **Platform** Dark Identity Profile module + subprocess Port
   (`put_intent`, `bind_and_resolve_prompt`).
3. **BFF** `POST /api/agent/workspace/submit-turn` + wire owner gate;
   reuse `submit_conversation_turn` after put.
4. **Worker** chat `input_resolver` → Port `bind_and_resolve_prompt`
   (feature/settings gated; keep fixed_input for explicit smoke).
5. **FE** owner bootstrap if needed; create-then-submit; `submitTurn`;
   receipt + snapshot reconcile; 16 KiB preflight.
6. **M1 tests** then **M2 live smoke** per §7.

## 6. Failure and receipt map

| Situation | Receipt / HTTP |
|---|---|
| Validation (empty, >16KiB, bad session ref) | 400; no put |
| CSRF / owner gate fail | existing 401/403 |
| Store crypto/helper down | `unavailable` or mapped retryable; no turn |
| Store idempotency conflict (same id, different body) | `conflict` |
| Put ok, turn conflict | `outcome_unknown` or `conflict` with reason |
| Put ok, turn transport/commit unknown | `outcome_unknown` → retry same id / follow |
| Happy path | `accepted` + `command_id` + digests |
| Worker resolve fail after accepted | command path marks dispatch rejected/unavailable per existing worker matrix; not a second browser put |

## 7. Acceptance

### M1 (automated; Fake store allowed)

1. With session: FE/client `submit-turn` sends four fields + CSRF.
2. Without session: create via `/act` then `submit-turn`.
3. BFF enforces 16 KiB/non-empty; profile mapping; put-then-turn order.
4. Put ok + turn raise → `outcome_unknown`; identical retry → `accepted`.
5. `/act` with prompt field → rejected.
6. No Keychain/Hermes required.

### M2 (local dark live)

1. Real Keychain put; receipt `payload_digest` / `payload_ref` non-empty.
2. `submit-turn` → ledger command `accepted`.
3. Supervised worker one cycle: bind `command:<id>` → resolve → Hermes
   **delivered** without `--fixed-input`.
4. Prompt: `Reply with exactly: L2a-pong`; assert model output contains
   `L2a-pong` (rejects metadata-ack false positive).
5. Public cutover still closed as a release gate; local flags may show
   write-ready.
6. Short audit note; **no** auto-commit.

## 8. Glossary anchors

Platform `CONTEXT.md` terms: L2a-Send, Thin Browser Write Rail, Composite Turn
Submit, Intent Payload Store, Payload Binding, Action Receipt, Owner Gate,
Plan-V6 vs Local Dark Enablement.

Add when implementing docs touch:

- **Dark Identity Profile** — shared BFF/worker constants mapping platform
  workspace/session/owner to store scope and fixed policy/digest.
- **Intent Payload CLI Port** — subprocess `put` / `bind_resolve` pipe protocol.

## 9. Consequences

- Positive: browser → encrypted store → ledger → real Hermes prompt under
  existing safety defaults; `/act` remains a pure ledger bus.
- Negative: two new trust boundaries (BFF→CLI put, worker→CLI resolve) need
  timeouts and error mapping; Keychain helper becomes a hard M2 dependency.
- Follow-ups: L2b observe, L3 UI, launchd daemon, Plan-V6 remainder, V8.

## 10. References

- `docs/design/2026-07-16-agent-workspace-v1-adr.md`
- `docs/superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md`
- `hqa/intent_payloads.py`, `hqa/intent_payload_crypto.py`, `hqa/intent_retention_cli.py`
- platform `submission_saga.py`, `dispatch_adapter.py`, `agent_workspace_actions.py`
- platform `CONTEXT.md` (Agent Workspace glossary)
- audit `ai-quant-platform/docs/audits/2026-07-21-v6-local-off-to-on.md`
