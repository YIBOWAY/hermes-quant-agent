# 文档导航与当前执行状态

这份文件只回答三个问题：**现在按哪份计划做、实际做到哪里、其他文档该怎么读**。
长期方向、历史实现细节和特定日期审计分别留在 roadmap、plan 和 audit 中。

> 事实快照：2026-07-19。易变的 branch、dirty、PID、端口与服务健康不写死在这里；交接时
> 必须重新检查 git、进程、HTTP smoke 和测试。

## 当前执行入口

| 层级 | 权威文档 | 当前含义 |
|---|---|---|
| 产品路线 | [`design/2026-07-01-roadmap-phases-0b-4.md`](design/2026-07-01-roadmap-phases-0b-4.md) | Hermes 是个人量化 COO；`ai-quant-platform` 是领域后端。D-31 定义工作台方向，D-32 冻结 Agent v0.2 / 完整 `/hermes` Web Chat 目标。 |
| 已批准设计 | [`superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md`](superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md) | `/hermes` 为默认首页，逐步吞并 Factor Lab / Backtester / Experiments / Agent Studio 的体验，但不删除领域引擎/API/CLI/artifact。 |
| 当前 implementation plan | [`superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md`](superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md) | 唯一 active backlog：只朝真正 Agent v0.2 + 完整 `/hermes` Web Chat 推进；不做临时网页 chat。V1 代码基线已对抗收口但 live DB role/RLS 仍 PARTIAL；V2 隔离代码已独立 ACCEPT，尚未安装 live。公共写端仍 OFF。 |
| V0 Workspace v1 candidate ADR | [`design/2026-07-16-agent-workspace-v1-adr.md`](design/2026-07-16-agent-workspace-v1-adr.md) | **HQA-side DONE / 三仓 PENDING → V0 NOT DONE**；HQA 侧 executable contracts 已交付（5 模块+622 测试绿），三仓 manifest/primary validation/cross-review 待完成（见 `audits/2026-07-17-v0-three-repo-cross-review.md`）。 |
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
v0.2 + 完整 `/hermes` Web Chat；公共网页写端仍关闭。** V0 已交付 HQA contracts，但三仓
manifest/primary validation/cross-review 尚未收口；V1 代码基线和 V2 isolated durable authority
已完成 fresh adversarial code acceptance。V1.2 的 live `quant` role 仍为 superuser/bypassrls，
V2 也尚未受控安装到 live Hermes，因此两者都不能被写成 live release。V0 将冻结最终 Interface、权威与
ordinary turn / Research Task / Attempt / submission Command / Run cardinality。已发现当前 migration 006 的 `UNIQUE(task_id)` 与一个
Task 多 Attempt 的目标冲突，因此不得继续按旧顺序单独 live apply 006；必须先完成 schema
修正、migration guard 和独立复核。Discord 保持当前可用入口，但不是临时网页方案或 fallback；
Discord/历史 session 在 Web 只读，网页写入只能新建或显式 fork 到新的 managed Hermes Session。

## D-31 当前事实

| 能力 | 状态 | 真实含义 |
|---|---|---|
| `/hermes` 专业只读首页 | **DONE** | 默认首页、SafetyStrip、Today/Tasks/Approvals/Results 只读框架已存在。 |
| Tasks 证据面 | **DONE** | 展示 automation、weekly、opportunity 等平台事实；没有 research task create/submit。 |
| Candidate integrity | **DONE** | canonical root、immutable manifest、verified/migration_required/corrupt、digest/status CAS、legacy_unbound 非授权。 |
| Scene-B Gate 1/2/final/Gate 3 | **DONE** | 人类 Gate 3 commit `524e791e5e3e22cec12a4166ad8fc3617c735566` 已进入 promoted registry 并 cleanup。 |
| Hermes official API session read | **DONE（代码 + 本机只读验收）** | 平台 BFF 能读真实 session list/detail/messages；浏览器不持有 Hermes key。 |
| 3B durable ledger/outbox | **DONE（live DB 验收）** | migration 005 已 apply 并重复验证幂等；schema v1、五表、四个 append-only trigger，health `schema_ready=true`。 |
| 3C deterministic worker | **FRAMEWORK DONE / reconcile-only** | 安装 wrapper `--once` 与 live `LISTEN/NOTIFY` 两周期通过；零 Hermes mutation/provider。 |
| 3C.1 Task/Attempt + payload + exact binding | **FOUNDATION ACCEPTED / SCHEMA REVISION REQUIRED** | HQA append-only journal、projection/replay/CAS、payload、跨权威 saga/reverse audit 已代码验收；但 migration 006 的 `UNIQUE(task_id)` 不能支持 multi-Attempt research。live 未 apply；当前 runner 会重放旧 SQL，因此须修订未上线的 006 并重做完整验收，不能默认追加 007；worker 仍不 claim。 |
| Browser Gate 2 mutation | **ROLLED BACK / OFF** | 初版会 refetch digest/status，违反 HQA Gate 1 exact binding 与 Gate 2 no-refetch；Approvals 当前只读。 |
| Hermes chat/stream/resume/stop | **V2 ISOLATED CODE ACCEPTED / LIVE OFF** | 九项 canonical durable 语义、HQA adapter 和 approval/provider evidence 已在 integration worktree 对抗验收；live Hermes 仍是旧安装且 durable OFF，所以 Web write/release 继续 BLOCKED。 |
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
  trigger 已核验，`/api/health` 报告 `schema_ready=true`。
- 44 个平台目标测试和 HQA full suite 通过；安装 wrapper `--once` 与 live
  `LISTEN/NOTIFY` 两周期通过。
- 验收后 command/event/outbox/run-link 仍各为零行，Hermes mutation/provider 调用均为零。
  这证明 reconcile-only 基础设施可用，不证明 chat/run 写端已准入。

live gateway 仍报告九项 3D blocker：提交非幂等、请求不可恢复、无 event ID、无 event replay、
Run 状态不持久、provider policy 不可变、无 actual provider 证据、approval 无 exact binding、
stop 不可对账。这里描述的是仍运行 `916f5fbf5452`、durable OFF 的 live 进程，不是最新
integration worktree。V2 已在隔离代码中闭合这些语义并获独立 ACCEPT，但未获 install/canary
授权，因此 3D/public composer 仍保持 **BLOCKED/OFF**。

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

1. **V0 Interface/cardinality/authority freeze：HQA-side DONE / 三仓 PENDING → V0 不是 DONE。**
   HQA 侧 executable contracts 已交付（5 模块 + 622 测试全绿）；三仓 manifest 一致性、primary
   validation 与三仓 cross-review 均 pending（见 `audits/2026-07-17-v0-three-repo-cross-review.md`），
   当前零 live mutation。
2. **V1 Stop-the-line baseline：代码收口，live DB role PARTIAL。** startup migration、语义
   fingerprint、fail-closed migrate、transcript/DLP 与浏览器 metadata 泄漏已修复并全量验收；
   migration 006 仍未 apply，`quant` role provisioning/RLS 需独立任务和授权。
3. **V2 Hermes DurableRunAuthority：isolated code ACCEPTED / live OFF。** canonical Run、
   idempotency/replay、provider response receipt、approval release/signal 与 stop 已收口；最新代码
   仍是 integration dirty worktree。先完成提交/三仓 manifest 对齐；受控 live install/canary 必须
   另获授权。V3 HQA WorkflowAuthority 尚未开始。
4. **V4 PostgreSQL schema/BFF/security。** 先完成代码、cardinality 与隔离 PostgreSQL
   验收，再请求修正后 migration 的单独 live 授权；apply 后仍不开放 dispatch。
5. **V5 supervised worker、V6 最终 Workspace UI、V7 decisions/results/two vertical
   slices。** 所有切片只落最终架构，公共 Web Chat 保持 OFF。
6. **V8 adversarial acceptance/release。** 两轮冷启动、独立 security review、真实用户验收
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
