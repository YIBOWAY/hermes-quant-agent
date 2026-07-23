# V8-M6 Public Flag Cutover — ACCEPT@2026-07-23@a2953cb

**Platform tip:** `codex/agent-v0-2-platform-v1@a2953cb` (honesty fix; feat parent `389efcb`; M5 parent `bb67fa3`; freeze ancestor `b570f94`)  
**HQA tip:** docs seal this session  
**Depends:** V8-M5 hermetic canary G5/G6 ACCEPT@bb67fa3; V8-M1–M4 CLEAR_WITH_NITS

## Delivered (hermetic G7 open + G8 rollback)

| Surface | Fact |
|---|---|
| Authority | `public_cutover_authority.py` — open/close; route=/hermes; build_digest CAS; single open; requires G6 `acceptance_id` |
| Observe | `public_cutover_observe.py` — `public_cutovers[]`; health `public_cutover=ready`; `workspace_public_flag_open` |
| Acts | `public.cutover.open` / `public.cutover.close` |
| Spine | WorkspaceSnapshot + EventPage `public_cutovers`; receipts `cutover_id`/`cutover_digest`/`cutover_ref`/`public_flag_open` |
| G7 open | surfaces `public_write_authorized=true` + `chat_write_ready=true` **only while status=open** (receipt/dict scoped; global composer_readiness separate) |
| G8 close | digest CAS rollback; append-only facts retained; flag off; Discord/kill_switch untouched |
| Honesty rails | every cutover receipt stamps `release_authorized=false`, `m6_gate2_decide_authorized=false`, `v2_durable_live=false`, `kill_switch_unchanged=true` |

## Honesty fix @a2953cb (Code Reviewer REQUEST_CHANGES → closed)

| Hole | Fix |
|---|---|
| Open-action replay after close claimed `public_flag_open=true` / write authorized while row closed | Authority conflicts `public_cutover_already_closed` on same open action after close; receipt uses `cutover.public_flag_open` (never hardcodes True) |
| G7 only checked acceptance_id existence | Saga CAS-binds `action.build_digest == acceptance.build_digest`; mismatch → `acceptance_build_digest_mismatch` conflict; flag OFF |

Regression tests: `test_open_replay_after_close_does_not_claim_write`, `test_open_requires_acceptance_build_digest_match`.

## Evidence

- **17** unit (`tests/test_v8_m6_public_cutover.py`) green
- Regression cluster **82** passed / 0 skipped / 0 failed (M6+M5+composer+gateway+session+submit_turn+transcript)
- junit: `docs/audits/evidence/2026-07-23-v8-m6-public-cutover.junit.xml`

## Auth stamps

| Flag | Value |
|---|---|
| `release_authorized` | **false** (full V8 release is a separate stamp; M6 ≠ release) |
| `m6_gate2_decide_authorized` | **false** |
| `v2_durable_live` | **false** |
| `kill_switch` | **unchanged true** (never flipped) |
| Standing default public write | **OFF** until operator issues open cutover |
| Hermetic open under mutation | YES (G7 path; requires G6 acceptance + build_digest CAS) |

## NON-goals held

- No kill_switch flip / paper / dry_run change
- No M6 Gate2 decide couple
- No V2 durable live ON
- No `release_authorized=true`
- No platform `import hqa`
- No lift `gate_cascade_locked`
- No bodies on follow
- No Task invention from conversation.turn
- Unrelated dirty (brief/paper/options CSV) excluded from commit
- Global composer_readiness not auto-composed with public flag (deferred to operator release stamp)

## GAP board

| GAP | Status |
|---|---|
| GAP-17 Public flag + rollback proof | **COVERED** (hermetic G7/G8 surface + honesty fix) |
| Standing operator open in live env | operator-local; not release evidence |
| Full V8 release stamp | OPEN — `release_authorized` stays false |
| Readiness composition (composer ∧ public_flag) | DEFERRED to operator release stamp |

## Reviewer stamps (this seal)

- **Code Reviewer:** REQUEST_CHANGES on `389efcb` (2 honesty/CAS holes) → holes closed @a2953cb; residual nits deferred (docstring tightened; note hooks no-op; list_observed limit=0 clamp) → **APPROVE_WITH_NITS**
- **Reality Checker:** CERTIFIED_WITH_NITS **91/100** on feat (re-run 15→17 unit + 80→82 regression green; tip pure M6; rails held; standing default OFF; YES commit docs; NO full release). Honesty fix re-verified green before seal.
- **Workflow Architect:** GO_WITH_NITS / ON_RAILS — hermetic ladder M1–M6 complete; NEXT only operator release stamp under fresh auth; stop conditions held; readiness-composition nit deferred to release stamp

## NEXT

V8 hermetic ladder M1–M6 complete (surfaces + honesty).  
`release_authorized` remains **false** until full V8 gates are honest in the operator environment under **fresh user auth**.  
Do **not** treat M6 hermetic ACCEPT as live standing public write ON. Do **not** flip kill_switch. Do **not** couple Gate2 decide.

Related: `docs/audits/2026-07-23-v8-m5-canary-grant.md`, plan D-32.
