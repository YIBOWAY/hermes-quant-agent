# Agent v0.2 · V8-M1 Adversarial Acceptance Prep

> 审计日期：2026-07-23。本文是 **V8-M1 PREP-ONLY** 交付：把 Slice V8 对抗矩阵展开为可执行
> TC 清单、现有 hermetic 证据映射、缺口（GAP）与后续切片顺序。  
> **不是** V8 release、不是 canary grant、不是 `chat_write_ready=true`、不是 M6 Gate2 decide
> 授权、不是 trading/paper/live 打开。  
> 前置：Plan-V6-Token-Stream-M1 ACCEPT@platform `5788379` / HQA docs `673ab11`；
> V7a–V7g-B-M5 ACCEPT；public write OFF；kill_switch true；gate_cascade_locked stays；
> **M5 ≠ M6 auth；token-stream ≠ M6 auth**。  
> Architect freeze：**FREEZE GO**（prep construction；this pack is the ACCEPT artifact）。

## 1. Verdict（prep）

| 字段 | 值 |
|---|---|
| Slice | `V8-M1 Adversarial Acceptance Prep` |
| 类型 | docs + evidence map + gap inventory（无 production flag flip） |
| Platform tip | `codex/agent-v0-2-platform-v1@5788379` |
| HQA tip | `codex/full-9h@673ab11`（本文提交后更新） |
| Hermes integration tip | `codex/v2-live-integration@2eb5fa27790f`（V2 SOURCE；live durable 仍 OFF） |
| Prep status | **ACCEPT**（matrix + gaps + order + exclusions sealed） |
| Full V8 gate 1–8 | **NOT STARTED**（见 plan § Slice V8 + §8） |
| release_authorized | **false** |
| Architect freeze | **FREEZE GO** → post-ACCEPT next = **V8-M2 only** |

## 2. Prep ACCEPT 定义（vs full V8）

### V8-M1 prep ACCEPT 当且仅当

1. 本文件矩阵 TC-V8-M1-01…29 + G01…G08 完整覆盖 plan § Slice V8 自动/本地场景表 + token-stream continuity。
2. 每条 TC 标注：`COVERED` / `PARTIAL` / `GAP` / `DEFERRED`（无 silent “probably covered”）。
3. COVERED/PARTIAL 指针指向 tip 上真实路径（platform `5788379` / HQA docs）。
4. GAP 列表可执行，且不偷偷引入 M6 / public write / canary。
5. 后续切片顺序冻结（V8-M2…M6）且 Architect ON_RAILS。
6. 明确 restamp：public flags OFF；kill_switch true；zero orders；M6 unauthorized。

### V8-M1 prep **不** 包含

- 独立 security CLEAR 终裁（full V8 G4 → V8-M4）
- 两轮从零冷启动 drill 实跑（G3 → V8-M3）
- canary grant 签发 / 用户两条纵切验收（G5–G6 → V8-M5 + user auth）
- 一次打开 public flag（G7 → V8-M6 + user auth）
- M6 Gate2 decide couple、V2 durable live ON、provider burn、paper/live 下单
- 新 product code / act kinds / migrations / flag flips

## 3. Standing non-goals / exclusions（整段 V8 直至另 freeze）

| ID | Exclusion | Standing reason |
|---|---|---|
| X1 | M6 Gate2 decide couple | M5 seal ≠ M6 auth；cascade stays `gate2_seeded` + `gate_cascade_locked` |
| X2 | Public composer / `chat_write_ready=true` / `agentV02WebChat` public ON | Plan: false until full V8 G5–G7 |
| X3 | Canary grant issuance | G5；needs G1–G4 + separate user auth |
| X4 | `kill_switch=false` | Safety default true |
| X5 | Paper/live broker orders / account mutation | Zero orders invariant |
| X6 | V2 DurableRunAuthority live ON | Source ACCEPT only |
| X7 | StartResearch public / non-dark research | Still dark |
| X8 | Provider-token passthrough on follow/SSE | Token-stream M1: body-free hints；messages BFF authority |
| X9 | Task invention from `conversation.turn` | Cardinality freeze |
| X10 | Always-allow approval | V7a invariant |
| X11 | Gate 3 web commit / Git write from UI | Gate3 prepare-only |
| X12 | platform `import hqa` | Process boundary |
| X13 | Discord / historical session Web write (must 409) | Fork-only；not M1 UX license |
| X14 | Treating M1 docs as release authorization | `release_authorized=false` until G7 |

## 4. Identity snapshot（prep 时点）

| Repo | Branch | Head | Note |
|---|---|---|---|
| ai-quant-platform | `codex/agent-v0-2-platform-v1` | `5788379` | token-stream M1 code |
| HQA | `codex/full-9h` | `673ab11`+ | docs seal; this audit |
| Hermes integration | `codex/v2-live-integration` | `2eb5fa27790f` | V2 source; not live runtime |
| Live Hermes (context) | upstream main | historical | durable OFF; re-verify before any live drill |

Platform worktree may carry unrelated dirty (brief/paper/options). **V8 evidence commits must isolate.**

## 5. Adversarial matrix → TC-V8-M1-*

图例 coverage：`COVERED` / `PARTIAL` / `GAP` / `DEFERRED`。  
Exec：`hermetic` / `live-dark` / `deferred`。

### 5.1 Plan matrix → TCs

| TC ID | Scenario (plan row) | Required evidence | Coverage | Exec | Existing pointer / GAP |
|---|---|---|---|---|---|
| TC-V8-M1-01 | Double-submit same action | Same `client_action_id`/digest → one command/Run | PARTIAL | hermetic | M2@f5d41f4：payload binding composite+BFF COVERED；ledger command_id via PG mark（not re-run if no QS_TEST_DATABASE_URL）— **GAP-01 PARTIAL** |
| TC-V8-M1-02 | Same ID, different content | 409；zero new command/Run | COVERED | hermetic | M2@f5d41f4 composite+BFF same-id different prompt 409 + turn.call_count==1 — **GAP-02 COVERED** |
| TC-V8-M1-03 | BFF ack lost | Retry same ID recovers original receipt | PARTIAL | hermetic | dispatch ack-drop COVERED；M2 composite payload/outcome_unknown retry PARTIAL（command_id mocked）— **GAP-03 PARTIAL** |
| TC-V8-M1-04 | Worker crash after commit | Restart resumes existing command；no second Run | COVERED | hermetic | crash-after-claim / crash-after-hermes / idempotent recover + PG crash matrix in connector dispatch tests |
| TC-V8-M1-05 | Hermes accept then timeout | `outcome_unknown` → lookup；zero blind retry | COVERED | hermetic | `test_timeout_becomes_outcome_unknown_no_blind_retry_in_same_cycle`；PG timeout twin |
| TC-V8-M1-06 | SSE disconnect / refresh | Snapshot/replay: messages+events no loss/dup | PARTIAL | hermetic | L4b spine + workspace_bff follow；transcript_observe_v6_m1；**GAP-04** full refresh+replay integration |
| TC-V8-M1-07 | Hermes restart | Run/status/events/provider evidence readable or honest reconcile | PARTIAL | live-dark / deferred | durable source ACCEPT only；live durable OFF → **DEFERRED V8-M3**（may need separate V2 install auth） |
| TC-V8-M1-08 | Fallback chain | Only pre-auth chain；UI from/to/reason/usage | GAP | deferred | **GAP-05** no dedicated TC；inventory-first；do not invent UI |
| TC-V8-M1-09 | Stop repeat / partial success | Idempotent stop；no `stopped` before reconcile | COVERED | hermetic | `test_run_stop_v7c.py` idempotent + partial_stop heal + layered receipt |
| TC-V8-M1-10 | Command approval digest/TTL/single-use | stale/expired/repeat rejected；no always-allow | COVERED | hermetic | `test_command_approval_decide.py`；release V7b；projector V7d |
| TC-V8-M1-11 | Gate 1/2/3 target change | Old approve 409；Gate2 no substitute；Gate3 no web commit | COVERED | hermetic | `test_gate_surfaces_v7e.py`；B-M4/B-M5 cascade CAS |
| TC-V8-M1-12 | Plan confirm impersonates Gate1 | Reject；no Gate2 without exact source SHA / note / binding | COVERED | hermetic | `test_confirm_research_plan_is_not_gate1`；B-M2…M4 chain |
| TC-V8-M1-13 | Discord / historical session Web write | 409 zero mutation；fork → new managed Session | PARTIAL | hermetic / deferred | cross-origin/session fail-closed；**GAP-06** fork lineage product path DEFERRED |
| TC-V8-M1-14 | HQA journal/PG unavailable | Mutation fail-closed；no bypass to Hermes | PARTIAL | hermetic | mutation-off matrices；**GAP-07** explicit PG-down + HQA-down chaos pair |
| TC-V8-M1-15 | Cross-origin / no CSRF | Zero PG/HQA/Hermes mutation | COVERED | hermetic | workspace cross-origin fails；act with CSRF still mutation_disabled；`chat_write_ready is False` |
| TC-V8-M1-16 | Provider evidence missing | Result unverified；Task not normal `completed` | COVERED | hermetic | M2@f5d41f4 task `status==completed_degraded` — **GAP-08 COVERED** |
| TC-V8-M1-17 | Sample result marking | Conspicuous synthetic；never confused with real | COVERED | hermetic | V7f sample_vs_real + coerce；FE typedResultsV7f |
| TC-V8-M1-18 | Trading boundary | paper/live/kill_switch/Gates unchanged；real trade calls ≡ 0 | COVERED | hermetic | kill_switch default true；dispatch reject；vertical `zero_orders` / `not_tradeable` |

### 5.2 Message continuity（token-stream M1 fold-in）

| TC ID | Scenario | Required evidence | Coverage | Exec | Pointer / GAP |
|---|---|---|---|---|---|
| TC-V8-M1-19 | Follow SSE body-free `event:transcript` | No content/text/tokens/delta/messages on follow；`ready.scope` includes `transcript_hints` | COVERED | hermetic | `test_transcript_observe_v6_m1.py` project + seeded SSE body-ban + scope |
| TC-V8-M1-20 | Phase waiting → optional partial → final | BE `waiting\|final` only；FE `partial` from assistant length；UI **Updating…** not Streaming…；marker `data-hermes-token-stream=v6-m1` | COVERED | hermetic | transcriptHelpers TC-TS-07/08；spine tests；limitations honesty |
| TC-V8-M1-21 | Spine-refetch is text path | Text from messages BFF only；transport `spine-refetch` | COVERED | hermetic | WorkbenchTranscriptPanel coalesced refetch + 1.5s poll；limitations `messages_bff_is_text_authority` |
| TC-V8-M1-22 | Hint journal dedupe / stable revision | Same revision no re-bump dirty；reject `web_`/`wm_` | COVERED | hermetic | journal dedupe；spine reject web_/wm_ |
| TC-V8-M1-23 | Dual messages-refetch ownership nit | Single owner for in-flight when dirty+interval fire | COVERED | hermetic | M2@f5d41f4 `createQuietRefetchScheduler` pending-bit + vitest — **GAP-09 COVERED**（AbortController nit residual） |
| TC-V8-M1-24 | Disconnect mid-waiting then snapshot | Phase honest；resync restores；no dup user rows | PARTIAL | hermetic | L3b merge + L4b resync；**GAP-10** combined chaos |
| TC-V8-M1-25 | Delivered without assistant growth | No fake typing；final only with terminal + honest body rules | COVERED | hermetic | M2 characterization lock TC-V8-M2-11 — **GAP-11 COVERED** |

### 5.3 Vertical evidence map（prep only — no new couple）

| TC ID | Scenario | Required evidence | Coverage | Exec | Pointer |
|---|---|---|---|---|---|
| TC-V8-M1-26 | Vertical A hermetic bind → typed options result | Task/Attempt/Run on spine + sample honesty + zero orders | COVERED | hermetic | `test_vertical_binding_v7g.py` + V7f options sample |
| TC-V8-M1-27 | Vertical A authorized live Futu RO overlay | Exact ticker/fields/budget/timeout；still zero orders | COVERED | live-dark (historical) | `test_vertical_binding_v7g_m2.py` + A-M2 state；re-run needs fresh user auth if live — M1 only maps |
| TC-V8-M1-28 | Vertical B cascade through gate2_seeded | bind→…→gate2_seed；lock stays；no auto Gate2 decide | COVERED | hermetic | B-M1…M5 modules；M6 excluded |
| TC-V8-M1-29 | Gate2 decide couple absent | V7e `gate2.candidate.review` alone does not advance past `gate2_seeded` | COVERED | hermetic | B-M5 seal；must stay green in M2 |

### 5.4 Final-gate prep rows（documentation slots only）

| TC ID | Gate | M1 deliverable | Later close |
|---|---|---|---|
| TC-V8-M1-G01 | G1 suites+build | Command inventory + cluster→TC map（§7） | **V8-M2** |
| TC-V8-M1-G02 | G2 backup/restore | Drill outline：PG / HQA authority / Hermes Run store；backup≠silent TTL revive | **V8-M3** |
| TC-V8-M1-G03 | G3 dual cold-start | Boot script outline；deep-link list | **V8-M3** |
| TC-V8-M1-G04 | G4 security+code CLEAR | Surface checklist（CSRF/origin、intent crypto、approval/Gate digests、no always-allow、no web commit、provider evidence、kill_switch） | **V8-M4** |
| TC-V8-M1-G05 | G5 canary grant | Grant shape：owner-only、short TTL、exact build digest、same `/hermes`；revoke-on-done/fail | **V8-M5**（separate user auth） |
| TC-V8-M1-G06 | G6 dual vertical owner accept | Evidence template binding A+B receipts under canary | **V8-M5** |
| TC-V8-M1-G07 | G7 one public flag | Single flag cutover checklist；no half-open | **V8-M6** |
| TC-V8-M1-G08 | G8 mutation rollback | Control inventory：flag off keeps append-only facts；Discord unaffected | **V8-M6** |

**Rule：** M1 closes the *map*. M2–M6 close the *gates*. No gate may be marked DONE inside an M1 artifact.

## 6. GAP backlog

| GAP | Severity | Blocks | Close path |
|---|---|---|---|
| GAP-01 Double-click FE+BFF race | High | G1 | V8-M2 hermetic（submit-turn + ledger single command） |
| GAP-02 submit-turn same-id different body 409 | High | G1 | V8-M2 hermetic |
| GAP-03 BFF ack-loss receipt recover | High | G1 | V8-M2 hermetic（mirror dispatch accept_drop_ack） |
| GAP-04 Full refresh replay integration | Medium | G1/G3 | V8-M2 hermetic FE+BFF |
| GAP-05 Fallback chain pre-auth only | Medium | G1 / product? | Inventory in M1；implement only if surface exists — else DEFERRED product |
| GAP-06 Discord/historical session fork lineage | Medium | G6 completeness | DEFERRED until fork UX authorized；keep 409 fail-closed green |
| GAP-07 PG-down + HQA-down BFF chaos pair | High | G1/G2 | V8-M2 hermetic fault injection |
| GAP-08 Task not completed without provider evidence | High | Vertical honesty / G6 | V8-M2 status machine assert |
| GAP-09 Dual messages-refetch ownership | Medium | Continuity polish | V8-M2 FE fix + test（token-stream nit） |
| GAP-10 Disconnect mid-waiting combined chaos | Medium | G1/G3 | V8-M2 |
| GAP-11 Delivered without assistant growth honesty | Low-Med | Continuity | V8-M2 |
| GAP-12 Live Hermes restart under durable OFF | High（for G3 live claim） | G3 live | V8-M3；may need separate V2 install auth — do not smuggle |
| GAP-13 Fresh full-suite green at release tips | High | G1 | V8-M2 campaign |
| GAP-14 Backup/restore executed proof | High | G2 | V8-M3 |
| GAP-15 Independent CLEAR | High | G4 | V8-M4 |
| GAP-16 Canary + owner dual vertical | Critical（release） | G5–G6 | V8-M5 + user auth |
| GAP-17 Public flag + rollback proof | Critical（release） | G7–G8 | V8-M6 + user auth |

## 7. Suite inventory（G1 prep — commands bind TC clusters）

Run from platform tip `5788379` unless noted. **M1 does not require fresh green campaign**；M2 does.

### 7.1 Hermetic pytest clusters（platform）

| Cluster | Suggested command | TC bind |
|---|---|---|
| Token-stream / transcript | `pytest tests/test_transcript_observe_v6_m1.py -q` | 19–22 |
| Workspace BFF / follow / CSRF | `pytest tests/test_workspace_bff.py tests/test_local_session_security.py -q` | 06, 13–15 |
| Submit-turn / composite | `pytest tests/test_submit_turn_bff.py tests/test_composite_turn_submit.py -q` | 01–03（PARTIAL） |
| Approvals decide/release/observe | `pytest tests/test_command_approval_decide.py tests/test_approval_release_v7b.py tests/test_approval_observe_v7d.py -q` | 10 |
| Stop | `pytest tests/test_run_stop_v7c.py -q` | 09 |
| Gates / results | `pytest tests/test_gate_surfaces_v7e.py tests/test_typed_results_v7f.py -q` | 11–12, 16–17 |
| Vertical A/B | `pytest tests/test_vertical_binding_v7g*.py -q` | 01–02, 26–29, 18 |
| Dispatch crash/timeout | `pytest tests/test_hermes_connector_dispatch.py -q` | 04–05 |
| Composer / write readiness | `pytest tests/test_composer_readiness.py tests/test_api_hermes_gateway.py -q` | 15, 18 |
| Settings kill_switch | `pytest tests/test_settings.py -q` | 18 |

### 7.2 FE vitest clusters（platform）

| Cluster | Suggested command | TC bind |
|---|---|---|
| Transcript helpers + spine | `npx vitest run src/frontend/lib/hermes/transcriptHelpers.test.ts src/frontend/lib/hermes/workspaceFollowSpine.test.ts` | 19–25 |
| Typed results FE | `npx vitest run src/frontend/lib/hermes/typedResultsV7f.test.ts`（path may vary） | 17 |

### 7.3 Offline prod build

| Step | Command | Note |
|---|---|---|
| Frontend build | platform `npm run build`（or project equivalent） | G1；M2 campaign |
| Python import smoke | `python -c "import quant_system"` under venv | sanity |

### 7.4 HQA regression（optional at M2）

| Cluster | Command | Note |
|---|---|---|
| Research workflows fail-closed | `pytest tests/test_research_workflows.py -q` | TC-14 partial |

**Last known green (token-stream seal session):** transcript_observe 9 passed；workspace_bff 8 passed；vitest transcript+spine 35 passed. Full warehouse re-run = **V8-M2 GAP-13**.

## 8. Recommended slice order after V8-M1 prep ACCEPT

```
V8-M1 prep (this doc) ACCEPT
  → V8-M2 hermetic adversarial suite close (GAP-01–04, 07–11, 13; tip green; no flags)
  → V8-M3 cold-start / backup-restore drills (local; public OFF; GAP-12/14)
  → V8-M4 independent security + code CLEAR package (GAP-15; freeze SHAs after M3)
  → V8-M5 canary grant + owner dual-vertical (GAP-16; **fresh user auth**)
  → V8-M6 one-shot public open + rollback verify (GAP-17; **fresh user auth after M5**)
```

**Ordering rules**

1. Do not start M3 until M2 hermetic adversarial cluster is green (or waivers listed).
2. Do not start M4 on moving tips — freeze SHAs after M3.
3. M5/M6 each need **explicit user authorization**；M1–M4 do not imply them.
4. **M6 Gate2 decide** remains a **non-V8** product couple unless separately frozen — not inserted between M1–M6.
5. If M2 discovers a missing product surface (e.g. fallback chain GAP-05), stop and re-freeze — do not silently expand V8.
6. Never open public write in M1–M5；never flip kill_switch；never smuggle V2 durable live ON.

## 9. Full V8 final gates（checklist only； not M1 execution）

| # | Gate | Prep-time status |
|---|---|---|
| 1 | HQA/platform/frontend/Hermes suites + offline production build green | PARTIAL — tip suites green for agent-v0.2 slices；full warehouse = M2 |
| 2 | DB/HQA/Hermes backup/restore drill | NOT RUN this session |
| 3 | Two cold starts；deep-link restore | NOT RUN |
| 4 | Independent security + code CLEAR | NOT RUN（prior slice CLEAR ≠ V8 CLEAR） |
| 5 | public flags still OFF；canary grant only after user auth | flags OFF **held** |
| 6 | User two-vertical acceptance under canary；revoke grant | NOT AUTHORIZED |
| 7 | One-shot public flag open | NOT AUTHORIZED |
| 8 | One-click Web mutation rollback retained | design exists；not re-verified |

## 10. Token-stream continuity note for V8 operators

- SSE `event:transcript` = **hints only**（phase/revision/transport/limitations）。
- Assistant text = **messages BFF** via spine-refetch（`data-hermes-transcript-transport=spine-refetch`）。
- Backend hint phases：`waiting|final` only；FE may show `partial` only when assistant content length > 0。
- UI label is **Updating… / 更新中…**，not provider Streaming。
- Known nit：dirty coalesce + 1.5s interval dual fetch — must not be misread as dual authority（GAP-09）。
- Reject `web_`/`wm_` session ids on messages/hint paths。

## 11. Operator checklist（prep → M2 handoff）

1. [x] Architect FREEZE GO ingested  
2. [x] Matrix TC-01…29 + G01…G08 written  
3. [x] GAP-01…17 inventoried  
4. [x] Suite inventory bound  
5. [x] Exclusions X1–X14 restated  
6. [x] Next slice = V8-M2 only  
7. [x] Reality Checker（light）：key pointers resolve at platform `5788379`（transcript/stop/approval/gate/dispatch/vertical/Updating label）  
8. [x] Neat-freak：plan banner / README / AGENTS / memory  
9. [x] HQA commit + push（docs only；no platform flag changes）— M1@f17c27b  
10. [x] Enter V8-M2：high GAPs closed ACCEPT_WITH_NITS @f5d41f4；still no flags  

## 12. Explicit non-authorization stamp

```
release_authorized = false
chat_write_ready = false
composer_write_ready = false
m6_gate2_decide_authorized = false
v2_durable_live_released = false
canary_grant_issued = false
kill_switch = true   # expected default; re-verify live before any drill
zero_orders_required = true
next_authorized_slice = V8-M3  # cold-start / backup-restore drills only
# (V8-M2 ACCEPT_WITH_NITS @f5d41f4; release_authorized still false)
```

## 13. Seal evidence（this session）

| Check | Result |
|---|---|
| Architect freeze | **FREEZE GO** prep-only；next V8-M2 |
| Matrix completeness | plan V8 18 rows + token-stream 19–25 + vertical 26–29 + G01–G08 |
| Coverage honesty | COVERED/PARTIAL/GAP/DEFERRED tags；no silent covered |
| Exclusions | X1–X14 + §12 stamp |
| Code / flags | **none** in this slice |
| Reality Checker（light） | **PASS** — critical paths resolve at `5788379`（dispatch crash/timeout/ack-drop；stop；approval single-use/expired；gate1≠plan；transcript body-ban；Updating label；vertical B-M1…M5 modules present）。Weak needles were path-location only（Updating in panel not helpers；stale/expired present in approval decide） |
| Neat-freak | plan banner + table row + README + AGENTS + memory |
| release_authorized | **false** |

---

**END V8-M1 PREP ACCEPT** — next construction **V8-M2 hermetic adversarial suite close only**.

## 14. V8-M2 close status（2026-07-23）— **ACCEPT_WITH_NITS**

| Field | Value |
|---|---|
| Platform tip | `codex/agent-v0-2-platform-v1@f5d41f4`（code `71b6fb6` + residual honesty `f5d41f4`） |
| HQA tip (M1 prep) | `codex/full-9h@f17c27b` |
| Slice | V8-M2 hermetic adversarial suite close |
| Seal grade | **ACCEPT_WITH_NITS**（not full CERTIFIED warehouse green；not release） |
| Code Reviewer | **APPROVE_WITH_NITS**（71b6fb6）+ residual pending-bit accepted |
| Reality (first pass) | **NEEDS WORK 71/100** on inflated COVERED → residual close @f5d41f4 |
| Architect | prior SEAL GO_WITH_NITS；re-seal after residual |

### GAP board after residual close @f5d41f4

| GAP | Coverage | Evidence (honest) |
|---|---|---|
| GAP-01 double-submit same body | **PARTIAL** | Composite: `test_v8_m2_double_submit_same_body_stable_payload_binding` — FakeIntent single binding + stable payload_ref/digest（**not** unmocked ledger command_id）. BFF: `test_v8_m2_bff_double_post_same_body_stable_payload`. Ledger single command_id: existing PG `test_external_turn_conflicts_managed_turn_idempotent_and_conflict`（`pytest.mark.pg`；needs `QS_TEST_DATABASE_URL`；not re-run this session if URL unset）. |
| GAP-02 same id different prompt 409 | **COVERED** | Composite `test_v8_m2_same_id_different_prompt_conflicts_zero_turn` + BFF `test_v8_m2_bff_same_id_different_prompt_409`（turn.call_count==1）. |
| GAP-03 ack-loss / outcome_unknown retry | **PARTIAL** | `test_v8_m2_ack_loss_retry_recovers_same_payload_binding` + `test_v8_m2_outcome_unknown_then_retry_same_id` — payload binding + retry path real；command_id still under turn mock. Dispatch-layer ack-drop remains COVERED pre-M2. |
| GAP-07 intent/HQA port down | **PARTIAL** | `test_v8_m2_port_unavailable_fail_closed_no_turn` — intent-port slice only. Full PG-down + HQA-down BFF pair still open. |
| GAP-08 missing provider evidence | **COVERED** | `test_v8_m2_missing_provider_evidence_task_not_normal_completed` asserts public task `status=="completed_degraded"`（≠ `"completed"`）. |
| GAP-09 dual messages-refetch | **COVERED**（with known non-blocking nits） | `createQuietRefetchScheduler` pending-bit sole owner（no recursive re-arm while hung）+ panel wire + sessionId drift guard；vitest 4 cases. Residual nit: quiet path still no AbortController（pre-existing soft-fail shape）. |
| GAP-11 delivered without growth | **COVERED** | transcriptHelpers TC-V8-M2-11 characterization lock（behavior pre-existed；M2 pins it）. |
| GAP-04 full refresh replay | **OPEN** → waive to M3 | written residual |
| GAP-05 fallback chain | **DEFERRED** product | unchanged |
| GAP-06 Discord/historical fork | **DEFERRED** | unchanged |
| GAP-10 disconnect mid-waiting | **OPEN** → waive to M3 | written residual |
| GAP-12 live Hermes restart | **DEFERRED V8-M3** | freeze ladder |
| GAP-13 warehouse full-suite green | **PARTIAL** | Bound cluster green @f5d41f4：composite+submit_turn_bff+vertical_binding_v7g+transcript_observe_v6_m1+run_stop_v7c（`-m 'not pg'`）+ vitest transcriptHelpers 18. Full warehouse / PG matrix not claimed. |
| GAP-14…17 | later Mn | freeze ladder |

### Bound green evidence @f5d41f4
- pytest：composite + submit_turn_bff + vertical GAP-08 + transcript_observe_v6_m1 + run_stop_v7c → all green（not pg）
- vitest：`transcriptHelpers.test.ts` **18 passed**（incl. 4 GAP-09 scheduler）
- Unrelated dirty（brief/paper/options）**not** in M2 commits

### Non-goals held
public write OFF；canary OFF；M6 Gate2 decide unauthorized；kill_switch true；`release_authorized=false`；no platform `import hqa`；no flag flips；zero orders.

### NEXT after M2 ACCEPT_WITH_NITS
**V8-M3 cold-start / backup-restore drills**（local dark；public OFF）。  
Do **not** treat M2 as release/canary auth. Residual OPEN GAPs 04/10 waived into M3 polish only if they fit cold-start scope；else stay residual board.
