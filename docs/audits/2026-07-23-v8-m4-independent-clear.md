# V8-M4 Independent Security + Code CLEAR

> 审计日期：2026-07-23。本文是 Agent v0.2 **V8 gate G4** 的独立 security + code CLEAR 包。  
> 配套 verdict：`evidence/2026-07-23-v8-m4-independent-clear-verdict.json`。  
> **不是** canary 授权、**不是** public write 授权、**不是** M6 Gate2 decide 授权、**不是** V2 durable live ON、**不是** `release_authorized=true`。

## 结论

- **V8-M4：CLEAR_WITH_NITS（G4 surface CLEAR）。**
- Frozen tips at campaign：
  - Platform `codex/agent-v0-2-platform-v1@b570f94`（V8-M3 tip；本切片无 product code 变更）
  - HQA `codex/full-9h@c86fdb9`（V8-M3 seal tip；本切片仅 docs+evidence+verdict）
  - Hermes integration SOURCE `codex/v2-live-integration@2eb5fa27790f`（live durable OFF；未 re-install）
- **`release_authorized=false`**（硬约束；本 CLEAR ≠ full V8 gates 1–8 done）。
- **NEXT：** V8-M5 canary grant **仅在用户明确授权后**；M4 不蕴含 M5/M6。

## G4 checklist（surface）

| Surface | Result | Evidence |
|---|---|---|
| CSRF / origin / owner session | **PASS** | `test_local_session_security` + `test_workspace_bff` cross-origin 403；act 无 session fail |
| Intent crypto fail-closed | **PASS** | HQA `test_intent_payload_crypto` + `test_intent_payloads`（含 backup/TTL） |
| Approval digest/TTL/single-use；no always-allow | **PASS** | `test_command_approval_decide`（rejects always_allow）+ release V7b + observe V7d |
| Gate 1/2/3；no web commit from UI | **PASS** | `test_gate_surfaces_v7e`；Gate3 note `human_git_commit_required`；no git write path |
| Provider evidence honesty | **PASS** | V7g vertical + M2 GAP-08 `completed_degraded` |
| kill_switch default true | **PASS** | `test_settings` + `SafetySettings.kill_switch` default `True`；live default true |
| chat_write hermetic pin false | **PASS** | `test_composer_readiness` + hermetic Settings pin `mutation/composer OFF` → `chat_write_ready=False` |
| Process boundary（no platform `import hqa`） | **PASS** | platform hermes tree comments + no import in M3/M4 commits |
| zero_orders / not_tradeable vertical | **PASS** | vertical A/B suites limitations |
| gate_cascade_locked stays | **PASS** | B-M1…M5 cascade suites |
| Cold-start / backup≠TTL（G2/G3 carry） | **PASS** | M3@b570f94 / binder@c86fdb9 |

## Campaign results（this session）

| Campaign | Result |
|---|---|
| Platform G4 bound cluster | **357 passed, 5 skipped, 0 failed** @`b570f94` |
| HQA G4 bound cluster | **271 passed, 0 failed** @`c86fdb9` |
| FE vitest（routes+transcriptHelpers+workspaceFollowSpine） | **51 passed**（claim-only；no junit artifact in this package） |

JUnit artifacts（SHA-256 in verdict JSON）：
- `docs/audits/evidence/2026-07-23-v8-m4-platform-g4.junit.xml`
- `docs/audits/evidence/2026-07-23-v8-m4-hqa-g4.junit.xml`

### Platform file list（bound）
`test_local_session_security`, `test_workspace_bff`, `test_composer_readiness`, `test_command_approval_decide`, `test_approval_release_v7b`, `test_approval_observe_v7d`, `test_run_stop_v7c`, `test_gate_surfaces_v7e`, `test_typed_results_v7f`, `test_vertical_binding_v7g*`（A + B-M1…M5）, `test_hermes_connector_dispatch`, `test_hermes_http_dispatch_adapter`, `test_settings`, `test_transcript_observe_v6_m1`, `test_composite_turn_submit`, `test_submit_turn_bff`, `test_v8_m3_cold_start`, `test_api_hermes_gateway`.

### HQA file list（bound）
`test_agent_workspace_security`, `test_intent_payload_crypto`, `test_intent_payloads`, `test_workflow_authority`, `test_workflow_authority_backup`, `test_v8_m3_backup_restore_binder`, `test_research_workflows`, `test_workflow_contract`.

## Operator-env honesty

Operator machine may have `QS_LOCAL_MUTATION_*` ON（local-dark enablement V6）。  
**CLEAR hermetic pin** forces `LocalMutationSettings(enabled=False, composer_open=False)` → `chat_write_ready=False`。  
Live operator env readiness is **not** release evidence and must not be cited as public-write ready.

## Residuals（known open — do not silent COVERED）

| GAP | Status | M5 treatment |
|---|---|---|
| GAP-01 double-submit ledger command_id | PARTIAL | known residual |
| GAP-03 ack-loss command_id | PARTIAL | known residual |
| GAP-04 full FE refresh chaos | PARTIAL | known residual |
| GAP-07 full PG-down + HQA-down | PARTIAL | known residual |
| GAP-10 disconnect mid-waiting | OPEN | known open |
| GAP-12 live Hermes restart durable OFF | DEFERRED | needs separate V2 install auth |
| GAP-13 warehouse full-suite | PARTIAL | bound ≠ warehouse |

COVERED carry from M2/M3: GAP-02/08/09/11/14；G2 backup binder；G3 cold-start hermetic analog.

## Non-goals / exclusions

- not canary grant  
- not public write / `agentV02WebChat`  
- not M6 Gate2 decide couple  
- not V2 durable live ON  
- not `kill_switch=false`  
- not full warehouse green claim  
- not live Hermes OS restart drill  
- platform unrelated dirty（brief/paper/options）**excluded** from freeze tips  

## Authorization stamp

```
release_authorized              = false
canary_authorized               = false
public_write_authorized         = false
m6_gate2_decide_authorized      = false
v2_durable_live_authorized      = false
kill_switch_default             = true
chat_write_hermetic             = false
next_authorized_slice           = V8-M5 ACCEPT@bb67fa3 (see 2026-07-23-v8-m5-canary-grant.md); next open = V8-M6 public flag (careful gate)
```

## Relation to prior V0/V2 CLEAR

Prior `2026-07-19-v0-v2-release-closure.md` CLEAR is **source/formal identity** only。  
V8-M4 CLEAR is **G4 security+code surface** on agent-v0.2 hermetic ladder after M1–M3。  
Neither authorizes canary/public/release.

## NEXT

**Stop here for automated construction.**  
V8-M5 canary grant + owner dual-vertical requires **fresh explicit user authorization**.  
Do not auto-enter M5/M6.
