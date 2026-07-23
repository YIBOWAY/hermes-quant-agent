# 文档导航与当前执行状态

这份文件只回答三个问题：**现在按哪份计划做、实际做到哪里、其他文档该怎么读**。
长期方向、历史实现细节和特定日期审计分别留在 roadmap、plan 和 audit 中。

> 事实快照：2026-07-22。易变的 branch、dirty、PID、端口与服务健康不写死在这里；交接时
> 必须重新检查 git、进程、HTTP smoke 和测试。

## 当前执行入口

| 层级 | 权威文档 | 当前含义 |
|---|---|---|
| 产品路线 | [`design/2026-07-01-roadmap-phases-0b-4.md`](design/2026-07-01-roadmap-phases-0b-4.md) | Hermes 是个人量化 COO；`ai-quant-platform` 是领域后端。D-31 定义工作台方向，D-32 冻结 Agent v0.2 / 完整 `/hermes` Web Chat 目标。 |
| 已批准设计 | [`superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md`](superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md) | `/hermes` 为默认首页，逐步吞并 Factor Lab / Backtester / Experiments / Agent Studio 的体验，但不删除领域引擎/API/CLI/artifact。 |
| 当前 implementation plan | [`superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md`](superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md) | 唯一 active backlog：只朝真正 Agent v0.2 + 完整 `/hermes` Web Chat 推进；不做临时网页 chat。V0–V5 DONE（V2 live durable 仍 OFF）；**V6 本地 dark enablement ACCEPT@2026-07-21**；**L2a–L5c thin rail ACCEPT@2026-07-22**；**V7a–V7g-B-M5 ACCEPT@2026-07-22…23**（exact `allow_once|deny` CAS + hermetic `respond_approval` release/signal + hermetic Run-scoped stop + §5.5 layered receipt + durable approval projector + Domain Gate 1/2/3 surfaces + typed results on spine + **Vertical A bind** hermetic+live Futu RO + **Vertical B hermetic factor bind + plan-confirm + Gate1 seed + Gate1 confirm + Gate2 seed** → `cascade_stage=gate2_seeded` + pending Gate2；`gate_cascade_locked` stays；sample/real fail-closed；无 always-allow；Gates ≠ command-approval ≠ results；不发明 Task from conversation.turn；zero orders；kill_switch true；public write 仍 OFF；M5 ≠ M6 Gate2 decide auth）。**Plan-V6-Token-Stream-M1 ACCEPT@5788379**（hints-only SSE + spine-refetch）；**V8-M1 prep ACCEPT** + **V8-M2 ACCEPT_WITH_NITS@f5d41f4** + **V8-M3 cold-start/backup-restore ACCEPT@b570f94**（audit §15；GAP-14 COVERED）；NEXT V8-M4 CLEAR；full V8 gates 1–8 NOT STARTED；M6 未授权；public write OFF。 |
| V0 Workspace v1 candidate ADR | [`design/2026-07-16-agent-workspace-v1-adr.md`](design/2026-07-16-agent-workspace-v1-adr.md) | **SOURCE + FORMAL EVIDENCE + INDEPENDENT CLOSE-OUT DONE**；这只冻结 interface/cardinality/authority，不授权 runtime/live effect。 |
| L2a-Send thin write rail ADR | [`design/2026-07-22-l2a-send-thin-write-rail-adr.md`](design/2026-07-22-l2a-send-thin-write-rail-adr.md) | Browser composite `submit-turn` → HQA Intent Payload Store → ledger `conversation_turn` → worker bind/resolve → Hermes；**M1+M2 ACCEPT@2026-07-22**。≠ Plan-V6 全 UI。 |
| V0/V2 release closure | [`audits/2026-07-19-v0-v2-release-closure.md`](audits/2026-07-19-v0-v2-release-closure.md) | 三仓 source、live identity、validation binding 与 independent `CLEAR` 的事实源；verdict 明确 `release_authorized=false`。 |
| V3 acceptance | [`audits/2026-07-19-agent-v0-2-v3-acceptance.md`](audits/2026-07-19-agent-v0-2-v3-acceptance.md) | encrypted intent + multi-Attempt workflow authority 已 source-accepted、本地暗态安装并注册唯一 no-agent retention；不等于 Web Chat 可写。 |
| V3 运维 | [`runbooks/agent-v0-2-v3-authorities.md`](runbooks/agent-v0-2-v3-authorities.md) | authority 路径、只读 Hermes CLI、retention、backup/restore、audit/rebuild 与回滚边界。 |
| Wave 3 前序交付记录 | [`superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md`](superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md) | 3A/3B、reconcile-only 3C、3C.1 code acceptance、3E-A 与 3F mechanism 的历史交付证据和 blocker 输入；不是当前执行队列。 |
| 本机 Hermes 集成决策 | [`design/2026-07-15-local-hermes-integration-decision.md`](design/2026-07-15-local-hermes-integration-decision.md) | 正式方向是 platform BFF → PostgreSQL durable ledger → deterministic HQA worker → official Hermes API；禁止 Hermes/LLM cron 空轮询。 |
| 当前 Hermes 合同 | [`contracts/hermes-api-server-0.18.2.md`](contracts/hermes-api-server-0.18.2.md) | official API Server 的 health/capabilities/sessions/detail/messages 只读合同；chat/run/stream/approval/stop 全部 fail-closed。 |
| 旧 TUI 合同 | [`contracts/hermes-gateway-0.18.2.md`](contracts/hermes-gateway-0.18.2.md) | 历史 WebSocket JSON-RPC 快照；当前 checkout/source 已漂移，不再匹配安装，不能用于准入。 |
| Wave 2 验收事实 | [`audits/2026-07-15-d31-wave2-evidence.md`](audits/2026-07-15-d31-wave2-evidence.md) | Scene-B 三道人类门与 Gate 3 commit 已真实闭合；同时记录仍未完成的 D-31 范围。 |
| Wave 2 原计划 | [`superpowers/plans/2026-07-14-d31-wave2-bridge-approvals-parity.md`](superpowers/plans/2026-07-14-d31-wave2-bridge-approvals-parity.md) | 历史执行清单；顶部 delivery addendum 优先于原 success criteria。 |
| Candidate / Gate 3 计划 | [`superpowers/plans/2026-07-13-candidate-integrity-and-gate3.md`](superpowers/plans/2026-07-13-candidate-integrity-and-gate3.md) | repo-anchored immutable candidate、Gate 1 binding、Gate 2 CAS、final receipt 与隔离 Gate 3 的实现记录；顶部 acceptance addendum 是最新事实。 |
| Phase 1a-4 v2 完成记录 | [`superpowers/plans/2026-07-10-phase-1a-4-v2.md`](superpowers/plans/2026-07-10-phase-1a-4-v2.md) | 9A–9H 已完成；不是当前 backlog。 |
| 完整 9H 完成记录 | [`superpowers/plans/2026-07-12-full-9h-automation-notifications.md`](superpowers/plans/2026-07-12-full-9h-automation-notifications.md) | 只读 automation、weekly、freshness、feed 1.1 与 local notification 的交付/运行验收。 |
| 平台 Slice 0–8 | `/Users/sunyibo/programs/ai-quant-platform/docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md` | 已完成的前端/数据库历史交付与 parity 输入，不是独立路线图。 |

## 一句话项目阶段

**Phase 1a-4 / 9H 已收口；D-31 已交付真实 Hermes 会话只读、durable ledger、reconcile-only
worker、3C.1 代码地基和 3E-A 只读 Unified Results。当前执行主线已由 D-32 收敛为真正 Agent
v0.2 + 完整 `/hermes` Web Chat；公共网页写端仍关闭。** V0 source/formal freeze 和 V3 encrypted
intent / multi-Attempt workflow 暗态地基已完成独立验收；V1.2 live role/RLS 仍 PARTIAL，V2
candidate 仍未被 live Hermes 加载。**V4 code + isolated + live schema ACCEPT**（修订 006 Scheme A、007 session registry、
owner session/CSRF、AgentWorkspace/saga、thin BFF、`composer_readiness`；live
`quantplatform` 已于 2026-07-21 apply 006/007，fingerprint `4d952fe…`，业务行仍 0，
write flags 仍 false）。**V5 dark supervised claim/dispatch 已代码+crash-matrix 验收**
（`FakeHermesDispatchAdapter`；CLI 默认仍 `reconcile_only`）。**V6 本地 dark enablement
ACCEPT@2026-07-21**：真实 `HttpHermesDispatchAdapter`、supervised CLI、provider smoke、
settings-gated local mutation/composer；交易 `kill_switch` 仍 true。**L2a-Send M1+M2
ACCEPT@2026-07-22**（composite submit-turn + live `L2a-pong` delivered）。**L2b-Observe
M1+M2 ACCEPT@2026-07-22**（command-aware snapshot/follow + delivered 后 messages 预览）。
**L3a-Transcript M1 ACCEPT@2026-07-22**（workbench Conversation canvas；live assistant
`L3a-pong` + FE marker；无 SSE）。
**L3b-Transcript-Polish M1 ACCEPT@2026-07-22**（no-flicker refresh、soft stick scroll、
optimistic user bubble、sessions detail 复用 `TranscriptCanvas`；仍无 SSE）。
**L4a-Task-Drawer M1 ACCEPT@2026-07-22**（workbench 只读 Activity：workspace
`commands[]` lifecycle；Task/Attempt 权威投影仍空；≠ `/hermes/tasks` 研究任务页）。
**L4b-SSE-Follow M1 ACCEPT@2026-07-22**（BFF `GET …/follow/stream` + FE 共享 spine；
SSE 优先 / poll 回退；Activity 消费 spine；delivered bind/bump；follow/SSE 无
assistant body）。
**L5a-Hermes-Approval-Observe M1 ACCEPT@2026-07-22**（snapshot `approvals=[]` +
`command_approval=unavailable`；Composer `waitForCommandTerminalOnSpine`；
只读 Approvals 面板 `data-hermes-approval-observe=l5a-m1`；无 allow/deny 写；
≠ Gate 1/2/3、≠ `/hermes/approvals` 候选页）。
**L5b-Authority-Projection M1 ACCEPT@2026-07-22**（snapshot/spine 诚实空
Task/Attempt/Run/result + health；只读 Authority 面板
`data-hermes-authority-observe=l5b-m1`；conversation_turn 不伪造 Attempt；
≠ `/hermes/tasks`；无 stop/gate 写）。
**L5c-Workbench-A11y M1 ACCEPT@2026-07-22**（FE-only：`data-hermes-workbench-a11y=l5c-m1`、
`data-hermes-workbench-main` region landmark、responsive pad、collapse/long-id contracts、composer focus-visible；
断点 1440/1280/768/390；无 mutation 路由）。
**V7a-Hermes-Approval-Decide M1 ACCEPT@2026-07-22**（hermetic `CommandApprovalAuthority` +
`hermes.command_approval.decide` → `/act`；CAS = approval_ref+run_ref+digest+pending+
expires_at；`allow_once|deny` only；single-use + idempotent same action；snapshot
`command_approval=ready` + empty-honest `approvals[]`；FE marker
`data-hermes-approval-decide=v7a-m1`；mutation 关则按钮不出现；≠ Gate 1/2/3、≠ always-allow、
≠ live Hermes projector）。
**V7b-Hermes-Approval-Release M1 ACCEPT@2026-07-22**（hermetic `FakeHermesApprovalReleaseAdapter`
+ `project_pending_challenge` dual-seed；saga CAS 后 `respond_approval`；choice
`allow_once→once` / `deny→deny`；events `approval.responded|release_committed|signalled`；
idempotent replay 不双 signal；release fail → `reconciling` 且不复活 pending；
**无** always-allow / Gate / stop / live HTTP / `import hqa`）。
**V7c-Hermes-Stop M1 ACCEPT@2026-07-22**（hermetic `FakeHermesRunStopAdapter` + typed `run.stop.request` / `RequestStop`；terminal-honest already_terminal；`run.cancelled` + status stopped；exact client_action_id+digest 幂等；`partial_stop` → `reconciling` 后 replay 自愈；receipt `stop_layers` 按 plan §5.5；unknown Attempt 时 overall 保持 `reconciling`（不发明 Task stopped）；**无** FE stop 控件 / Gate / live HTTP / `import hqa` / public write）。
**V7d-Durable-Approval-Projector M1 ACCEPT@2026-07-22**（hermetic `list_observed` + `ApprovalObserveJournal`；snapshot/follow/`EventPage.approvals` + SSE `event:approvals` fingerprint-gated；pending+decided facts on L4b spine；FE `data-hermes-approval-projector=v7d-m1`；canDecide 仍 pending-only；empty honest；**无** Gate UI / dual private poll / always-allow / live HTTP / Task invention / public write）。
**V7e-Gate-Surfaces M1 ACCEPT@2026-07-23**（hermetic Domain Gate 1/2/3 observe+typed act：`gates[]` + `authority_health.gate_1|2|3` + SSE `event:gates`；kinds `gate1.formula_source.confirm` / `gate2.candidate.review` / `gate3.promotion_review.prepare`；Gate3 prepare-only + `human_git_commit_required`；FE `data-hermes-gate-*=v7e-m1`；Gate1/2 human note required；post-CAS ledger conflict → accepted；mutation-off fail-closed；empty honest；**≠** command-approval；**无** always-allow / public write / live HQA rebind / `import hqa` / dual private poll / Task invention；hermetic ≠ final domain authority）。
**V7f-Typed-Results M1 ACCEPT@2026-07-23**（hermetic typed results on spine：`results[]` typed public objects + `authority_health.result=ready` + SSE `event:results`；sample/real fail-closed；`read_status` fail-closed；Vertical A options fields + filters/exclusions/limitations/provider_evidence；exact links only when known；empty honest；FE `data-hermes-typed-results-*=v7f-m1`；**≠** Gate/approvals/**HermesResultsCatalog page**；**无** live Futu / public write / Task invention / catalog-on-spine / `import hqa`；hermetic ≠ live quote authority）。
**V7g-A-M1 hermetic Vertical A binding ACCEPT@2026-07-23**（honesty re-seal platform `116c456`：race-safe bind + Task/Attempt/Run ids on follow/SSE）（typed act `vertical.options_a.bind` → Task/Attempt/Run + V7f typed options result → `completed|completed_degraded`；receipt task/attempt/run/result ids；snapshot ids + linked result；`authority_health.task|attempt|run=ready`；always sample + `not_live_futu_quote`；idempotent；mutation OFF fail-closed；**Not** StartResearch；**无** live Futu / orders / public write / Task invention from conversation.turn）。
**V7g-A-M2 authorized live Futu RO ACCEPT@2026-07-23**（platform `575eb89`）（thin overlay on same `vertical.options_a.bind`：`provider_mode` + request-carried `auth_envelope`；live path envelope-enforce → RO façade → `real` only with verifiable `provider_evidence`；else sample + `completed_degraded`；never `real`+`not_live_futu_quote`；RO façade surface only quote helpers；grant budget；hermetic regression green；**Not** StartResearch；**zero orders**；kill_switch true；**无** public write / Task invention / `import hqa`）。
**V7g-B-M1 hermetic Vertical B factor binding ACCEPT@2026-07-23**（platform `0868c41`）（typed act `vertical.factor_b.bind` → Task/Attempt/Run `vertical=factor_b` + typed `factor` result → `completed|completed_degraded`；always sample；limitations lock cascade；race-safe；**Not** StartResearch/Confirm/Gate；reject live-grant smuggle；**无** live backtest/Git/orders/public write/`import hqa`；≠ full 纵切 B）。
**V7g-B-M2 hermetic factor_b plan-confirm cascade ACCEPT@2026-07-23**（platform `18f06ad`）（typed act `vertical.factor_b.plan_confirm` CAS on bound factor_b Task → `cascade_stage=plan_confirmed`；new attempt/run/result；lifts only `plan_confirm_required`；keeps `gate_cascade_locked`；always sample；StartResearch/global ConfirmResearchPlan 仍 dark；**无** Gate auto-seed/orders/Git/live/`import hqa`）。
**V7g-B-M3 hermetic factor_b Gate1 seed cascade ACCEPT@2026-07-23**（platform `ae8e885`）（typed act `vertical.factor_b.gate1_seed` CAS on plan_confirmed factor_b Task → `cascade_stage=gate1_seeded` + pending Gate1 on `gates[]`；new attempt/run/result；keeps `gate_cascade_locked`；always sample；**Not** Gate1 decide/StartResearch/auto-seed/orders/Git/live；V7e confirm may decide surface while cascade stays locked）。
**V7g-B-M4 hermetic factor_b Gate1 confirm cascade ACCEPT@2026-07-23**（platform `1cdbed1`）（typed act `vertical.factor_b.gate1_confirm` dual-path CAS on gate1_seeded factor_b Task → pending Gate1 confirm+cascade **or** V7e-already-confirmed cascade-only → `cascade_stage=gate1_confirmed`；keeps `gate_cascade_locked`；always sample；**Not** auto Gate2/StartResearch/orders/Git/live；V7e surface stays independent）。
**V7g-B-M5 hermetic factor_b Gate2 seed cascade ACCEPT@2026-07-23**（platform `ecec75e`）（typed act `vertical.factor_b.gate2_seed` CAS on gate1_confirmed factor_b Task → `cascade_stage=gate2_seeded` + pending Gate2 on `gates[]`；new attempt/run/result；keeps `gate_cascade_locked`；always sample；**Not** Gate2 decide/StartResearch/orders/Git/live；V7e review surface-only while cascade stays locked；M5 ≠ M6 auth）。
**Plan-V6-Token-Stream-M1 ACCEPT@2026-07-23**（platform `5788379`）（SSE `event:transcript` body-free hints + FE phase machine + spine-refetch messages BFF；markers `data-hermes-token-stream=v6-m1`；limitations honesty；**Not** provider-token passthrough / public write / M6 Gate2 decide / Task invention；token-stream ≠ M6 auth）。
**V8-M1 Adversarial Acceptance Prep ACCEPT@2026-07-23**（docs `f17c27b`；`docs/audits/2026-07-23-v8-m1-adversarial-acceptance-prep.md`）（TC matrix + GAPs；Architect FREEZE GO；`release_authorized=false`）。
**V8-M2 hermetic adversarial suite close ACCEPT_WITH_NITS@2026-07-23**（platform `f5d41f4`）（GAP-02/08/09/11 COVERED；01/03/07/13 PARTIAL；04/10→M3；bound pytest+vitest green；**Not** cold-start/canary/public/M6/release）。

**V8-M3 cold-start/backup-restore ACCEPT@2026-07-23**（platform `b570f94`）（G3 dual cold-start + empty spine honesty；deep-link observe-only；GAP-14 HQA backup≠TTL-revive binder 10 green；GAP-04 PARTIAL lite；GAP-12 DEFERRED no V2 durable smuggle；**Not** canary/public/M6/release；NEXT **V8-M4 CLEAR**）。
**launchd 常驻 daemon / public V8 仍未完成**；public write 仍 OFF。Discord 保持当前可用入口，
但不是临时网页方案或 fallback；Discord/历史 session 在 Web 只读，网页写入只能新建
或显式 fork 到新的 managed Hermes Session。

## D-31 当前事实

| 能力 | 状态 | 真实含义 |
|---|---|---|
| `/hermes` 专业只读首页 | **DONE** | 默认首页、SafetyStrip、Today/Tasks/Approvals/Results 只读框架已存在。 |
| Tasks 证据面 | **DONE** | 展示 automation、weekly、opportunity 等平台事实；没有 research task create/submit。 |
| Candidate integrity | **DONE** | canonical root、immutable manifest、verified/migration_required/corrupt、digest/status CAS、legacy_unbound 非授权。 |
| Scene-B Gate 1/2/final/Gate 3 | **DONE** | 人类 Gate 3 commit `524e791e5e3e22cec12a4166ad8fc3617c735566` 已进入 promoted registry 并 cleanup。 |
| Hermes official API session read | **DONE（代码 + 本机只读验收）** | 平台 BFF 能读真实 session list/detail/messages；浏览器不持有 Hermes key。 |
| 3B durable ledger/outbox | **DONE（live DB 表已 apply）** | migration 005 已 apply 并重复验证幂等；schema v1、五表、四个 append-only trigger 存在且业务行数为 0。2026-07-20 smoke：表在、`hermes_ledger_meta.schema_version=1`，但 V1.2A readiness 要求 trigger `ENABLE ALWAYS`（`'A'`），live 仍为 origin-only（`'O'`），故 `/api/health` 现报 `schema_ready=false`；不得误读为 005 未 apply。`workflow_binding_schema_ready=false`（006 未 live）。 |
| 3C deterministic worker | **FRAMEWORK DONE / reconcile-only** | 安装 wrapper `--once` 与 live `LISTEN/NOTIFY` 两周期通过；零 Hermes mutation/provider。 |
| 3C.1 Task/Attempt + payload + exact binding | **FOUNDATION ACCEPTED / SCHEMA REVISION REQUIRED** | HQA append-only journal、projection/replay/CAS、payload、跨权威 saga/reverse audit 已代码验收；但 migration 006 的 `UNIQUE(task_id)` 不能支持 multi-Attempt research。live 未 apply；当前 runner 会重放旧 SQL，因此须修订未上线的 006 并重做完整验收，不能默认追加 007；worker 仍不 claim。 |
| V3 Intent / WorkflowAuthority | **SOURCE ACCEPTED / LOCAL DARK INSTALL DONE** | AES-GCM/Keychain intent、TTL/tombstone、Task `1:N` Attempt、CAS/replay/backup 与只读 Hermes skill 已交付；唯一 retention cron 为 local no-agent。无 Web/Hermes mutation/provider/DB/交易。 |
| Browser Gate 2 mutation | **ROLLED BACK / OFF** | 初版会 refetch digest/status，违反 HQA Gate 1 exact binding 与 Gate 2 no-refetch；Approvals 当前只读。 |
| Hermes chat/stream/resume/stop | **V2 SOURCE ACCEPTED / LIVE NOT RELEASED** | 九项 canonical durable 语义、HQA adapter 和 approval/provider evidence 已在 pushed integration source 对抗验收；live 运行 upstream `main` 而非 candidate，且 install/launch identity 不一致、durable module 未安装，所以 Web write/release 继续 BLOCKED。 |
| Unified Results 3E-A | **DONE（只读实现 + 本机验收）** | 统一索引、动态详情、权威源回链和 exact Run-link 投影已交付；不复制领域真相。独立 Hermes research Run 结果与 full cutover 仍受 3D/用户验收门阻断，`unifiedResultsCutoverAccepted=false`。 |
| Legacy page redirects/deletion | **MECHANISM ONLY / DEFAULT OFF** | Agent Studio 有独立可回滚 redirect 机制但默认 OFF；exact digest-bound audit parity 与用户 cutover 批准仍缺。Factor Lab / Backtester / Experiments 仍承载写任务，不可退；全局 `legacyRedirects=false`。 |
| 交易执行 | **OFF** | `paper_trading` / `live_trading_enabled=false` / kill switch / 人工门不变。 |

完整 D-31 仍是**部分完成**。不要把“session 列表能读”表述为“网页已能和 Hermes 对话”，
也不要把 upstream `/v1/runs` 存在表述为写端已达到可靠性与审计要求。

## Gate 3 已完成的权威事实

| 字段 | 值 |
|---|---|
| candidate | `factor-wave2_scene_b_smoke_v3_loadable_factor-da01df1188` |
| manifest digest | `5ca064d597778b45f1a718047becf5b67b30cf9b24d441632b3a408cfd1c227d` |
| final receipt | `backtest-f4da78d66b4ee6eaab6e7226740ac6ac` |
| promotion | `promo-b7bbab8cf571a5f4ff43aa652aebf3bc` |
| reviewed commit | `524e791e5e3e22cec12a4166ad8fc3617c735566` |
| factor | `agent_candidate_wave2_sceneb_mom20_v3` |
| lifecycle | `reviewed` → `cleaned`；已 registered/promoted |

旧 promotion 因 base commit 漂移被显式 abandon，随后在当前 HEAD 重新 prepare；没有盲目重试。
人工授权只覆盖隔离 worktree 的 exact 三文件 diff，之后 fast-forward 合入平台开发分支。

Candidate/Gate 规则仍然是：

- 唯一默认候选目录是平台 repo-anchored
  `/Users/sunyibo/programs/ai-quant-platform/data/agent_run/agent/candidates`；只有
  `QS_AGENT_OUTPUT_DIR` 可显式覆盖，CWD / `QS_DATA_DIR` 不迁移候选池。
- Gate 1 由 HQA Scene-B wrapper 保存 reviewed source SHA-256 + 非空说明，并绑定 exact
  candidate ID / manifest digest；平台原始 review API 只是 Gate 2 primitive。
- Gate 2 必须由人类提供
  `candidate-id + expected-digest + expected-status=pending + note`；HQA 不 list/refetch/替换。
- Gate 3 只通过 HQA wrapper 进入，重验 Gate 1 与同 candidate/digest 的 content-addressed
  successful `--final` receipt；prepare 只产隔离 worktree/patch/manifest，永不自动 commit。
- 常驻 paper/live 路径只可使用 promoted、registered、tested factor；approved candidate 只限
  digest-reverified one-shot research。

## Hermes 接入现状

### 当前只读链路

```text
Browser -> ai-quant-platform Next page
        -> platform API/BFF http://127.0.0.1:8765
        -> Hermes official API Server http://127.0.0.1:8642
        -> persisted sessions
```

平台 BFF 当前只允许：

- `GET /api/hermes/gateway`
- `GET /api/hermes/sessions`
- `GET /api/hermes/sessions/{session_id}`
- `GET /api/hermes/sessions/{session_id}/messages`

Hermes Bearer key 只在服务端 owner-only 文件中；HTTP client 禁用环境代理继承与 redirect，
session ID / payload / 响应大小和时限都 fail-closed。平台和 Hermes 都必须只绑定 loopback；
远程访问前另做 TLS、登录、授权、CSRF 与审计。

这些 GET 只读已有本地状态，不启动 Hermes 推理，所以不消耗 Codex/Grok provider 额度。
3A session-read slice 本身没有新增 PostgreSQL migration/table；后续 3B 已通过 migration 005
单独落地 durable ledger，不能把两项交付混为一个写端授权。

### 已落地的 durable 底座（写端仍关闭）

下图是目标链路。当前已落地 PostgreSQL ledger、GET-only session BFF 与 worker
notify/scan/expired-lease reconcile；3C.1 payload/Task binding 已完成代码与隔离数据库验收，
但 live migration 006 尚未获单独授权。authenticated mutation、claim/dispatch 及 HTTP/SSE
写边均未准入。

```text
Browser -> same-origin BFF
        -> PostgreSQL command + outbox + event ledger
        -> HQA deterministic connector worker
        -> Hermes official API HTTP/SSE
```

当前轮询只执行 expired-lease reconcile，并以 `LISTEN/NOTIFY` 唤醒、周期 scan 兜底；
claim/lease/heartbeat 是已测试的 ledger primitives，尚未由 runnable worker 消费 queued
command。**禁止让 Hermes/LLM cron 空转询问“有没有任务”**。空队列不创建 Run、不调用 provider。

这条链路定义三个明确的权威边界：PostgreSQL 唯一拥有 transport command/event/outbox/lease
和 exact Run link；Hermes 唯一拥有 Session/Run/messages/actual provider evidence；HQA
Task/Attempt ledger 唯一拥有 research plan/Attempt/Gate/result refs。HQA ledger/CLI 已在代码中
实现，需待 migration 006 的单独 live 授权和激活验收后才成为当前运行事实。HQA connector 是 PostgreSQL command
的消费者，不保存第二份 BridgeRequest command journal。

connector 的物理入口是
`~/.hermes/scripts/hqa-hermes-command-worker.sh`，固定调用平台
`quant-system hermes connector-worker`；只允许 worker lifecycle 参数，不接受 prompt/provider/
secret。正式 Hermes 网络协议只使用 loopback official API `127.0.0.1:8642`；旧 `9119` TUI
gateway 与动态 Dashboard WebSocket 只作历史诊断，不是固定 transport 或准入证据。

写端只有在 request idempotency/recovery、Run identity、event cursor/replay、provider policy lock、
actual provider/fallback/usage evidence、approval TTL/digest/single-use 和幂等 stop/reconcile 均有
审查证据后才能打开。当前 `chat_write=false`、`approval_mutations=false`。

### 3B/3C 权威验收事实

- 平台提交 `efb10d5`、`9bc940f`、`b00a654`、`337e9d2` 已推送；最后一项收口
  Unified Results、候选/文件边界加固、前端切流机制与事实文档。
- live `quantplatform` 应用前备份位于
  `data/_runtime/db_backups/quantplatform-pre-wave3-20260715T182203+0800.dump`，SHA-256
  `3bbf5f3be83e6aeb348c83986e42cfed49e844e467b51305abf87a39d3733a3b`。
- migration 005 live apply 与重复幂等 apply 均成功；schema v1、五张表、四个 append-only
  trigger 已核验（2026-07-15/16 验收当时 `/api/health` 报 `schema_ready=true`）。
  **2026-07-20 smoke 更新：** 表与 `hermes_ledger_meta.schema_version=1` 仍在，但 V1.2A
  之后 readiness 只认 append-only trigger `ENABLE ALWAYS`；live 四个 trigger 仍为
  origin-only，故现报 `schema_ready=false`。这是 live role/trigger residual，不是 005
  回滚。正确 pin 应随修订后的 006 / V4 live activation Gate 另授权执行。
- 44 个平台目标测试和 HQA full suite 通过；安装 wrapper `--once` 与 live
  `LISTEN/NOTIFY` 两周期通过。
- 验收后 command/event/outbox/run-link 仍各为零行，Hermes mutation/provider 调用均为零。
  这证明 reconcile-only 基础设施可用，不证明 chat/run 写端已准入。

V2 source 已闭合九项 3D 语义并获独立 ACCEPT，但 2026-07-19 live 进程运行的是手工更新后的
upstream `main`，不是 integration candidate。live health 为 green，但 launchd 定义与 install
stamp 已漂移，且 durable module 未安装。因此 source acceptance 不能升级为 runtime acceptance；
durable、3D/public composer 与全部写端继续 **BLOCKED/OFF**。Hermes 维护频率由操作者决定，采用
periodic/manual update + no-agent watcher；watcher 只报告漂移，不得 install/restart/merge/开 gate。40k upstream full suite
不是 Agent v0.2 release gate；精确 source/runtime 快照见
`audits/2026-07-19-v0-v2-release-closure.md`。

### 3C.1 代码验收与 live 激活边界（2026-07-16）

- HQA 已实现 `hqa-research-task prepare|submit|show|events|reconcile-binding|reconcile-payloads|audit-authorities`；prompt 仅经 strict JSON stdin 进入 owner-only、content-addressed payload authority，不进入 argv、journal、projection、stdout 或平台 binding。
- 平台 migration 006 新增独立 workflow-binding schema，并以单事务写入 bound command、exact binding、version-1 event、outbox 与 `NOTIFY`；claim 在最终更新时重验 binding 和 expiry。
- reverse authority audit 使用平台 read-only、repeatable-read NDJSON inventory，能够区分 consistent、awaiting binding、platform-only、缺失与 exact conflict；不会凭一侧猜回另一侧事实。
- 3C.1 当时的 HQA 全量验收为 `816 passed, 2 skipped`；这是历史 foundation evidence，不是
  修订后 schema 或当前工作树的 fresh suite。平台当时的目标 PostgreSQL、CLI/unit、Ruff 与独立
  对抗复核均通过；跨仓隔离数据库实跑覆盖 `uninitialized`、`platform_only` 与真实 saga
  `consistent`，且没有 prompt/provider/model 泄漏或 Hermes/provider mutation。
- live `quantplatform` 预检确认 migration 006 尚未存在，现有 Hermes command/event/outbox/run-link 均为零行。apply 前备份 `data/_runtime/db_backups/quantplatform-pre-006-20260716T051758Z.dump`（平台仓库内，SHA-256 `fc70a22f2aae6070d7de4256372e5d4fce7078a4a006dfd64fd6960136785c79`）已完成并通过独立临时库 restore 验证；**这不等于已获授权或已应用 migration 006**。
- 后续复核发现 migration 006 的 `UNIQUE(task_id)` 把一个 Research Task 限制为一个 Command，
  与 v0.2 multi-Attempt 模型冲突。原“先授权并 apply 006”的下一步已撤销：D-32 选择修订从未
  live apply 的 006，并同步 schema meta/readiness/repository/claim/reverse audit/rollback/tests；
  当前 replay-all runner 下不能默认追加 007。先完成 migration auto-apply guard、隔离数据库与独立复核，
  然后才可重新请求一次明确 live migration 授权。即使修正后 apply，worker 也仍保持
  reconcile-only，不能自动 claim/dispatch。

## 接下来按什么顺序做

1. **V0 Interface/cardinality/authority freeze：DONE。** 三仓 identity、validation binding 与
   independent `CLEAR` 已闭合；verdict 明确不授权 live release。
2. **V1 Stop-the-line baseline：代码收口，live DB role PARTIAL。** startup migration、语义
   fingerprint、fail-closed migrate、transcript/DLP 与浏览器 metadata 泄漏已修复并全量验收；
   migration 006 仍未 apply，`quant` role provisioning/RLS 需独立任务和授权。
3. **V2 Hermes DurableRunAuthority：source ACCEPTED / live NOT RELEASED。** canonical Run、
   idempotency/replay、provider response receipt、approval release/signal 与 stop 已收口并推送；
   live 当前运行 upstream main，candidate 未安装，runtime identity chain 也未闭合。受控 live
   install/canary 必须另获授权。
4. **V3 HQA Intent/WorkflowAuthority：DONE（source accepted + local dark install）。** production
   bodies 加密、Task `1:N` Attempt、expiry/backup/replay、只读 skill 与 no-agent retention 已闭合；
   这不开放 composer/dispatch。
5. **V4 PostgreSQL schema/BFF/security：CODE + ISOLATED + LIVE SCHEMA ACCEPT（2026-07-21）。**
   修订 006/007 已 live apply（backup + idempotent replay + readiness 证据见 platform
   `docs/audits/2026-07-21-v4-live-migrate-006-007.md`）。research.* 仅 typed fail-closed。
6. **V5 supervised worker：DARK CODE + CRASH-MATRIX ACCEPT（2026-07-21）。** CLI 默认仍
   `reconcile_only`；`supervised_dispatch` + Fake adapter hermetic/PG green。
7. **V6 本地 dark enablement + L2a–L5c thin rail：ACCEPT（2026-07-21…22）。** 真实 adapter、
   local mutation/composer flags、composite `submit-turn`、command-aware snapshot/follow、
   delivered 后 Hermes messages 预览已通；L3a–L5c（含 L5a Approvals observe + L5b Authority
   projection + L5c workbench a11y）ACCEPT。**不等于** Plan-V6 完整 Web Chat UI / public cutover。V7a–V7g-B-M5 decide/release/stop/projector/Gate-surfaces/typed-results/hermetic+authorized-live-RO Vertical A + hermetic Vertical B bind+plan-confirm+Gate1 seed+Gate1 confirm+Gate2 seed ACCEPT。下一施工：**V8-M4 CLEAR**（V8-M1+M2+M3 ACCEPT@f17c27b/`f5d41f4`/`b570f94`；token-stream M1 ACCEPT@5788379；M6 未授权；full V8 gates NOT STARTED）；ops restart 纪律；public write 始终 OFF 直至 full V8。
8. **V8 adversarial acceptance/release。** 两轮冷启动、独立 security review、真实用户验收
   全绿后一次开放 Agent v0.2；legacy redirect 仍另行审批。

不得从旧 Wave 3、旧 1a-4、历史 audit 或 unchecked checkbox 自行增加/重排当前步骤。

## 阅读顺序

1. 本文件：确定当前主线、已完成与明确关闭项。
2. Agent v0.2 plan：唯一 implementation backlog、顺序、Gate 与 DoD。
3. D-31 design spec：核对产品目标与安全模型，不抽取旧候选顺序。
4. Wave 3 predecessor record：只追溯已交付事实和 blocker，不执行旧下一步。
5. local Hermes integration decision：核对 durable queue/worker 方案与禁止空轮询的边界。
6. official API contract：核对当前安装身份、GET allowlist 与 provider 语义。
7. Wave 2 audit / candidate plan：需要追溯 Gate 1/2/3 时再读。
8. roadmap：核对长期阶段；历史计划只作证据，不作待办。

## 文档状态用词

- **已实现**：代码存在，可能仍在工作树。
- **已提交**：本地 commit 存在。
- **已推送**：远端分支包含 commit。
- **代码交付**：实现与约定测试完成；不自动等于运行验收。
- **运行验收**：目标进程已加载目标代码，并对真实本地依赖完成 smoke/E2E。
- **BLOCKED / OFF**：边界故意关闭；不是靠展示一个入口就能变为完成。
- **历史记录**：只说明当时发生过什么，不维护当前 backlog。

计划 checkbox、旧测试计数和旧 PID 都不是当前事实源。每次交接至少重跑：
`git status --short --branch`、目标测试、前后端 health、Hermes health/session GET 和真实浏览器路径。

## 三仓职责与安全边界

- `Hermes-quant-agent`：编排、记忆、cron、通知、三门 provenance 与 connector worker 物理入口；
  不复制平台 PostgreSQL command authority。
- `ai-quant-platform`：行情、因子、回测、期权、paper account、PostgreSQL、BFF 与前端领域实现。
- 本机 Hermes source/installed runtime：Session、Run、messages、durable Run event 与 actual
  provider/approval/stop canonical facts。v0.2 开发须固定 source/install/process identity，在受控
  branch/worktree 中实现；不能直接随手修改未知 live checkout。
- Gate 1/2/3 与 Hermes command approval 互不替代；机会决策也不产生执行资格。
- action 只按 exact platform signal/execution IDs 关联；ticker/symbol 相似不是因果证明。
- 不绕过 `paper_trading`、`live_trading_enabled=false`、kill switch 或人工审批门。
- `/api/agent/tasks` 不是 Hermes fallback；upstream unavailable 时必须诚实 unavailable。

## 历史材料

- `plans/2026-07-01-phase-0a-*`、`phase-0b-*`、`phase-1a-*` 与 D-25 记录用于追溯。
- `2026-07-07-phase-1a-4-research-employees.md` 已被 v2 替代，不能逐项继续执行。
- 平台 `docs/phases/phase_15_iteration_roadmap.md` 只有参考价值，不是第二路线图。
- 历史审计中的优先级和“下一步”只对当日快照有效；当前状态回到本文件、代码、git 和测试。
