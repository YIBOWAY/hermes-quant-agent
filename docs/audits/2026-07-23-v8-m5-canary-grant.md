# V8-M5 — Hermetic canary grant + dual-vertical owner-accept (G5/G6)

**Date:** 2026-07-23  
**Verdict:** **ACCEPT**  
**Platform tip:** `codex/agent-v0-2-platform-v1@bb67fa3` (feat `013a2dc` + honesty-stamp fix; parent freeze `b570f94`)  
**HQA docs tip:** this seal  
**Depends:** V8-M1–M4 (CLEAR_WITH_NITS@a58c82d freeze b570f94); V7g-A/B dual vertical bind

## Scope delivered

Hermetic **release-candidate canary grant authority** for G5 + dual-vertical owner-accept binder for G6 (hermetic):

| Surface | Shape |
|--------|--------|
| Authority | `canary_grant_authority.py` — issue / revoke / accept_dual_vertical; single active grant; TTL 60–3600s; route locked `/hermes`; build_digest SHA-256 bind |
| Observe | `canary_observe.py` — `canary_grants[]` + acceptances; `authority_health.canary_grant=ready` |
| Acts | `canary.grant.issue` · `canary.grant.revoke` · `canary.dual_vertical.accept` |
| Saga | mutation-gated submit handlers; receipts carry `grant_id` / `grant_digest` / `canary_ref` / `acceptance_id` |
| Spine | `WorkspaceSnapshot.canary_grants` + follow/SSE `EventPage.canary_grants` |
| Honesty | every public grant/acceptance/receipt stamps `public_write_authorized=false`, `chat_write_ready=false`, `release_authorized=false` |

Dual-vertical accept binds existing hermetic `options_a` + `factor_b` task/result refs under the active grant, records in-process acceptance evidence, then **consumes** the grant. Failure paths never open public flags.

## Evidence

- Unit: `tests/test_v8_m5_canary_grant.py` — **17 passed**
  - parse/digest stable; route/TTL validation
  - issue → spine projection; mutation-off unavailable
  - second active conflict; idempotent replay
  - revoke CAS; digest mismatch conflict
  - TTL expiry → accept blocked
  - dual-vertical accept consumes grant; build mismatch; idempotent; missing vertical conflict
  - follow carries canary_grants; composer `chat_write_ready` stays false
- Regression cluster (M5 + V7g A/B + workspace + gates + composer): **196 passed / 7 skipped / 0 failed**
  - junit: `docs/audits/evidence/2026-07-23-v8-m5-canary-grant.junit.xml`
- Verdict JSON: `docs/audits/evidence/2026-07-23-v8-m5-canary-grant-verdict.json`

## Auth stamps (all false for release)

| Flag | Value |
|------|-------|
| `release_authorized` | **false** |
| `canary_public_write_authorized` | **false** |
| `chat_write_ready` | **false** (settings-gated; hermetic default OFF) |
| `public_write_authorized` | **false** |
| `m6_gate2_decide_authorized` | **false** |
| `v2_durable_live_on` | **false** |
| kill_switch default | **true** |

**M5 ≠ M6.** Hermetic canary grant construction is **not** public write cutover. G6 dual-vertical accept here is **owner evidence under canary**, not the M6 public flag flip, not Gate2 decide couple.

## NON-goals held

- No `LocalMutationSettings.composer_open` / public `chat_write_ready` flip as standing default
- No `agentV02WebChat` ON
- No kill_switch false; zero orders
- No M6 Gate2 decide couple; no StartResearch path open
- No V2 durable live ON smuggle
- No always-allow map
- No FE canary UI (spine projection only; workbench can render later)
- Unrelated dirty (brief/paper/options CSV) kept out of platform commit

## Residual GAP board (carry)

| Status | GAPs |
|--------|------|
| COVERED this slice | **GAP-16** (M5 canary grant) |
| OPEN next | **GAP-17** (M6 public) |
| PARTIAL carry | 01 / 03 / 04 / 07 / 13 |
| OPEN carry | 10 |
| DEFERRED | 12 (no V2 durable live smuggle) |
| COVERED prior | 02 / 08 / 09 / 11 / 14 |

## NEXT

**V8-M6 ACCEPT@a2953cb** — hermetic G7/G8 delivered; see `2026-07-23-v8-m6-public-cutover.md`. Standing default OFF; release_authorized still false.  
`release_authorized` remains **false** until full V8 gates (G1–G8) are honest.  
Do **not** treat M5 ACCEPT as M6 auth. Do **not** flip kill_switch. Do **not** open public write as standing default.

## Reviewer stamps (this seal)

- **Code Reviewer:** APPROVE_WITH_NITS — no must-apply; honesty triad on conflict receipts applied @`bb67fa3`; residual nits (TOCTOU outside lock, options-only receipt ids, test gaps) deferred
- **Reality Checker:** CERTIFIED_WITH_NITS **90/100** — commit pure; 17 unit + 196/7sk verified; public write never true; HQA package YES; M6 enter NO
- **Workflow Architect:** GO_WITH_NITS / ON_RAILS — NEXT ONLY V8-M6 public one-flag under safety rails; stop conditions held

## Nit applied post-review

`ActionReceipt.canary_honesty` forces `public_write_authorized=chat_write_ready=release_authorized=false` on **all** canary-kind receipts including conflict/unavailable (no grant_id yet). Covered by strengthened unit asserts.
