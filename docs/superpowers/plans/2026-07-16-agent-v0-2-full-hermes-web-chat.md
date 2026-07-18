# Agent v0.2 — 完整 `/hermes` Web Chat 实施计划

> **V0 ADDENDUM（2026-07-17 更新）：** HQA 侧 Workspace v1 合同已交付（5 模块 + 622 测试全绿），
> 但三仓 source/runtime manifest 一致性、primary validation 与三仓 cross-review 仍 pending，V0 仍
> 未 DONE。HQA frozen base `a7428b6219ded4550f4c8951b6fabc4542a1724f`；platform
> `7b73b5f2fe9e80509f4762c3de696d1e2c58fc9d`；Hermes `a79b818360700d526c0a48107444810e3d6ecc2e`。
> 三仓现状核查见 `../../audits/2026-07-17-v0-three-repo-cross-review.md`。
> migration、browser mutation、worker claim/dispatch、provider、Gate、paper/live 与 public composer
> 等所有 live gates 保持 OFF；本 addendum 不构成任何 live 授权。

> **状态（2026-07-17）：CURRENT / PLAN ACCEPTED / V0 HQA-side DONE / 三仓 PENDING → V0 NOT DONE。** 本计划是 D-32 唯一 active
> implementation plan。此前的 Wave 3 文档保留为已交付事实与问题输入，不再从其中的旧顺序、
> unchecked checkbox 或“下一步”继续施工。
>
> **产品决策已冻结：** Discord 继续作为当前可用的 Hermes 原生自然语言入口，但不是网页端的
> 临时方案、fallback 或验收替身。项目不再交付临时 chat、直连 Hermes 的简化 composer、旧
> `/api/agent/tasks` 回退或第二套前端。所有内部切片都实现最终架构；对用户可见的 Web Chat
> 只在本计划全部 launch gate 通过后一次开放。
>
> **本计划本身不授权** migration apply、worker claim/dispatch、真实 provider smoke、浏览器
> mutation、Gate mutation、远程访问、paper/live 执行或旧页 redirect。涉及这些状态变化时，
> 仍须按本计划所列独立 Gate 获取明确授权。

## 1. 最终要交付什么

Agent v0.2 不是“网页上有个能发消息的输入框”，而是一个可以日常依赖的本地个人量化研究
Agent：用户在 `/hermes` 用自然语言提出问题或研究目标，能够看到真实 Hermes 输出、任务计划、
执行过程、provider 事实、结构化结果、精确审批和停止状态；刷新、断线或服务重启不会造成重复
执行、事实丢失或假完成。

### 1.1 v0.2 用户能力

1. 只读浏览 Discord/历史产生的 `observed_external_session`；新建
   `web_managed_session`，或显式 fork 到一个新的 managed session 后再从网页写入。两种入口
   永不共同写同一个 Hermes Session。
2. 进行普通量化问答；普通对话只允许普通对话和明确 allowlist 的只读工具。
3. 显式发起 read-only / proposal-only 研究 Task，查看 Task、Attempt、Hermes Run 和计划步骤。
4. 实时读取白名单流式事件；刷新、重连、BFF/Hermes 重启后按 cursor 恢复。
5. 查看请求与实际 provider/model、显式 fallback 原因和 Hermes 返回的 usage；未知事实显示
   `unknown`，不能推测。
6. 对 Hermes command approval 做 exact digest、TTL、single-use 的 allow-once / deny；首版
   不开放“永远允许”。
7. 对领域 Gate 1/2/3 使用各自独立、摘要绑定的入口；聊天里的“同意”不是 Gate。
8. 幂等请求停止，并分别看到 Hermes Run、HQA Attempt、平台异步作业的停止/未知/终态。
9. 查看 typed result、数据 provider/freshness、limitations 和 exact Task/Attempt/Run/artifact link。
10. Hermes、HQA 或 PostgreSQL 不可用时保留诚实的只读能力；所有新写入 fail closed。

### 1.2 v0.2 明确不包含

- 不下单，不修改 paper account，不自动分配 sleeve，不新增任何 live trading 能力。
- 不开放 generic shell、任意文件写、browser、delegation 或 cron 修改。
- 不把 Discord/TUI、`POST /api/agent/tasks`、浏览器 localStorage 或内存 queue 当恢复 fallback。
- 不让 Discord 与 Web control plane 共同写同一个 Hermes Session；外部会话在网页永远只读，
  写入前必须显式 fork 并保存 lineage。
- 不支持远程访问；仍为 loopback、local-only、单用户产品。
- 不做任意 workflow DSL、动态 task plugin system 或第二个 Agent runtime。
- 不在本版本捆绑四个 legacy 页面全局 redirect/物理删除；旧页退场继续是 v0.2 之后的独立
  cutover Gate。
- 不把 subscription 剩余额度、跨 authority 的“全局时钟”或所有历史结果的高保真 presenter
  作为 launch blocker。

## 2. 完成定义

只有同时满足下面这句话，才可以把 `chat_write_ready` 置为 `true`：

> 在 `/hermes` 完成一条真实“研究 AAPL 卖 Put”纵切和一条真实“论文因子复现 + Gate
> 1/2/3”纵切；刷新、断线、BFF/worker/Hermes 重启和提交回包丢失均不重复执行或丢失权威
> 事实；用户能看到 exact Task/Attempt/Run/provider/result/approval/stop 证据；任何未知结果
> 诚实停在 `reconciling/outcome_unknown`；全过程真实交易调用为零。

下面任意一项存在时，都不得称为 Agent v0.2：

- 只有消息流，没有 durable request recovery；
- 只有平台生成的 Run ID，没有 Hermes 可查询的 canonical Run；
- SSE 断开后只能看“从现在开始”的新事件；
- 页面把 requested provider 当 actual provider；
- `Run stopped` 被展示成整个 Task/平台作业都已停止；
- 普通聊天被 LLM 暗中升级为研究 artifact 写入；
- command approval、Gate 1/2/3 共用一个模糊的 `approve(id)`；
- 浏览器、日志、argv 或 PostgreSQL 明文保存 bearer/provider secret；
- 功能通过改一个 capability 布尔值开放，而没有相应的可执行恢复证据。

## 3. 2026-07-16 当前实现基线

| 能力 | 当前事实 | 与 v0.2 的差距 |
|---|---|---|
| `/hermes` production shell | 默认首页、Today/Tasks/Approvals/Results 和 disabled composer 已交付 | 没有提交、stream、resume、stop 或 mutation 状态机 |
| Hermes session read | official API Server + server-side GET-only BFF 可读真实 session/list/detail/messages | 只读合同不能证明 Run 写端可靠 |
| PostgreSQL transport authority | migration 005 已 live apply；command/event/outbox/lease/run-link primitives 已交付 | 当前无 browser writer、session registry、dispatch 或 workspace projection |
| Worker | `LISTEN/NOTIFY`、periodic scan、expired-lease reconcile 已交付 | 不 claim、不 heartbeat、不 dispatch，Hermes/provider mutation 为零 |
| HQA Task/Attempt foundation | append-only journal、payload authority、projection/replay、CAS、exact binding saga 已代码验收 | 只支持 `research_chat` + 预先存在的 plan；Attempt 仍停在 planned，缺 plan revision、Run/provider/result/stop/Gate lifecycle |
| migration 006 | 隔离 PostgreSQL 验收通过，live 未 apply | `UNIQUE(task_id)` 与 multi-Attempt research 模型冲突；当前 runner 又会重放旧 SQL，**不得按原样上线，也不能默认靠追加 007 修正** |
| Hermes `/v1/runs` | endpoint、内存 Run/SSE/approval/stop 实现存在 | Run/status/event queue/stop/approval 仍依赖进程内状态；九项 durable 语义没有成立 |
| Unified Results | 只读 catalog/detail/exact-link projection 已交付 | 独立 research Run typed result、sample/real 醒目标记和完整 presenter 未完成 |
| Browser security | 当前写端关闭 | signed local session、same-origin、CSRF、mutation ownership、prompt retention/DLP 未交付 |
| Feature flags | `chat_write_ready=false`、approval mutation off | 必须由 executable readiness 推导，最终一次开放 |
| Legacy cutover | Agent Studio 只有默认 OFF 的页面级 redirect 机制 | 不属于本计划完成前的关键路径 |

最近的完整审计基线为 HQA 全量通过、平台 Python 全量通过、前端 lint/type-check/Vitest 通过；
但平台 standard verify 仍被 Gate 3 generator 的 Ruff 问题阻断，离线 production build 仍被
`next/font/google` 阻断。任何实施 slice 开始和收口时都必须重新获取 git、测试、进程、端口、
DB schema、Hermes source/runtime identity 的新鲜证据，不能复制本表的日期快照当当前事实。

### 3.1 当前最重要的两处结构性不匹配

#### A. migration 006 cardinality 错误

当前 `hermes_command_workflow_bindings` 同时约束：

```text
UNIQUE(task_id)
UNIQUE(attempt_id)
```

真正 Agent 的一个 Research Task 会经历计划生成、Gate 后继续、重试、恢复等多个 Attempt；每个
durably accepted Attempt 需要自己的 submission Command，并最多产生一个 Hermes Run。普通
conversation turn 也有 submission Command/Run，但没有虚假的 HQA Task/Attempt。`UNIQUE(task_id)`
会把 Research Task 永久限制在一次提交，因此旧计划中“下一步先 live apply 006”的顺序被本计划
明确撤销。

目标 cardinality 冻结为：

| Source | Cardinality | Target / 含义 |
|---|---|---|
| `observed_external_session` | 1:1 | Hermes Session；Web read-only |
| `web_managed_session` | 1:1 | Hermes Session；Web control plane 是唯一 writer |
| parent Session | 1:0..N | fork 后的新 managed child；每个 child 只有 0..1 parent |
| Workspace | 1:N | Research Task |
| ConversationTurn action | 1:1 | submission Command；不创建 HQA Attempt |
| Research Task | 1:N | Research Attempt |
| Research Attempt | 1:0..1 | submission Command；prepare/reconcile saga 中可暂缺，durable acceptance 后必须恰有 1 个 |
| submission Command | 1:0..1 | Hermes Run |
| Hermes Run | 1:0..1 | Research Attempt；ordinary conversation Run 为 0 |
| Hermes Run | 1:0..N | exact Result Link |
| Hermes Run | 1:0..N | control Command（stop/approval 等） |

本计划冻结采用 **A：直接修订从未 live apply 的 migration 006，并完整重做它的代码与验收
证据**。至少保留 `UNIQUE(attempt_id)`，并以 `UNIQUE(task_id, attempt_number)` 表达 Research
Task 内的 Attempt identity；普通 conversation command 不伪造 `task_id/attempt_id`。

不能在当前 migration runner 下默认追加 007：runner 会按序重放全部 migration，旧 006 会先
重新建立 `UNIQUE(task_id)` 和旧 readiness/claim 假设，数据库可能在到达 007 前就失败。若未来
治理要求已提交 migration 永不修改，必须先单独设计并验收 applied-version ledger/兼容 runner，
然后再选择 additive migration；不能把 007 当作当前逃生门。

修订 006 必须作为一个原子 co-change 重新审查：SQL、schema meta/version、readiness signature、
repository、claim SQL、reverse authority audit、rollback/restore runbook、空库/005 现有库/
concurrency/幂等测试和 delivery evidence。Git 历史与 D-32 change record 保留可追溯性；旧 3C.1
acceptance 只能称为历史 foundation evidence，不能继续为新 schema 背书。

#### B. 自然语言输入与预先存在的 plan 形成鸡生蛋问题

当前 HQA prepare 要求调用者先提供完整 plan；但真正的自然语言产品应先让用户提出目标，再由
Hermes 形成计划卡。网页、BFF 或本地规则不能伪装成 Hermes 生成研究计划。

v0.2 因此冻结两种显式 action，二者共用同一 durable control plane，但不互相冒充：

- `conversation.turn`：普通对话，只允许普通对话和 allowlisted read-only 查询；不创建领域
  candidate/artifact，不暗中升级为 Research Task。
- `research.start|continue`：用户显式进入研究模式；第一个 Run 可以只生成 plan。用户先对
  exact plan digest 做独立的 `ConfirmResearchPlan`；它不是 Scene-B Gate 1。后续遇到公式/来源
  时，Gate 1 仍必须绑定 exact reviewed source SHA-256、非空 note 以及后续 candidate/manifest。
  plan digest 绝不能替代 Gate 1 provenance。

普通对话不是直连 Hermes 的旁路：它同样经过 PostgreSQL command、immutable intent payload、
Hermes durable Run 和 event replay，只是不会伪造一个 HQA Research Task。研究 action 才额外
进入 HQA Task/Attempt/Gate authority。

## 4. 选择的架构：一个深的 Agent Workspace control plane

本轮并行评估了三类设计：按 endpoint 逐项增加能力、建立泛化 workflow engine、以及围绕用户
Workspace 建立窄 control plane。前两者分别会复制状态/恢复逻辑，或在只有一个真实 task kind
时过度抽象。最终选择第三种：**浏览器只学习提交动作、读取快照、跟随事件三个概念；复杂度留在
深 module 内。**

### 4.1 唯一公共 module

```text
Module: AgentWorkspace

act(actor, UserActionV1) -> ActionReceipt
snapshot(actor, WorkspaceRef) -> WorkspaceSnapshot
follow(actor, WorkspaceRef, after?: WorkspaceCursor) -> EventPage / SSE
```

`act` 不是 `execute(any)`。它只接受关闭的、versioned tagged union：

```text
CreateManagedSession / ForkIntoManagedSession
ConversationTurn
StartResearch / ContinueResearch
ConfirmResearchPlan
RequestStop
DecideHermesCommandApproval
ConfirmFormulaSource
ReviewCandidateCAS
PreparePromotionReview
```

FastAPI route 可以按安全域保持分开，不能因为内部共用 control plane 就暴露一个模糊的
`POST /approve`，也不能通过运行时 `gate_kind` 分支复用 Gate payload：

```text
POST /api/hermes/managed-sessions
POST /api/hermes/sessions/{id}/forks-to-managed
POST /api/hermes/managed-sessions/{id}/turns
POST /api/hermes/research-tasks
POST /api/hermes/research-tasks/{id}/attempts
POST /api/hermes/research-tasks/{id}/plan-confirmations
GET  /api/hermes/workspaces/{id}
GET  /api/hermes/workspaces/{id}/events
POST /api/hermes/runs/{id}/stop-requests
POST /api/hermes/command-approvals/{id}/decisions
POST /api/hermes/gate1/formula-confirmations
POST /api/hermes/gate2/candidates/{candidate_id}/reviews
POST /api/hermes/gate3/candidates/{candidate_id}/promotion-preparations
```

Gate 3 preparation body 必须携带 human-reviewed expected candidate digest、exact final receipt 和
base commit；成功响应才产生 `promotion_id`。此后 status/cleanup 只按该 `promotion_id` 操作。

Discord/历史 Session 由现有只读 GET 面观察；任何 POST 到 external session 都返回冲突且零写入。
`forks-to-managed` 创建新的 Hermes Session，要求用户重新选择 immutable provider policy，并保存
parent session ID、source channel 和 fork point。它不是让 Web 接管原 Session。

所有 HTTP 名称在 Slice V0 ADR 中最终冻结；无论路由如何命名，implementation 只能通过
`AgentWorkspace` 三个入口，不允许 route、React hook 或 worker 各自实现恢复状态机。

### 4.2 四个机器权威、一个人类完成事实和一个 payload seam

| 权威 | 唯一拥有的事实 | 不允许拥有 |
|---|---|---|
| Hermes | Session、Run 原始状态/事件、消息、actual provider/model/fallback/usage、command approval challenge | 平台 command lease、HQA plan/Gate、领域结果真相 |
| PostgreSQL | managed/external session registry 与 lineage、transport command/event/outbox/lease、client idempotency、exact Hermes Run link、可重建 workspace observation cursor | prompt 正文、Hermes actual provider 的伪造值、领域 artifact |
| HQA | Research Task/Attempt、plan version/digest、**Gate 1 reviewed-source confirmation 与 candidate/manifest binding**、Gate 3 entry/revalidation refs、result refs、payload retention/reconcile | 第二份 transport command journal、Gate 2 candidate CAS、回测指标正文 |
| 平台领域 repository/artifact | factor、candidate、backtest、experiment、options result、**Gate 2 exact candidate CAS**、promotion prepare primitive 与 provenance | Hermes transcript、HQA Task、Gate 1 provenance、人的 Git commit |
| 人类 Git review/commit | Gate 3 的最终完成事实：审阅 exact isolated diff 后产生的 commit | 自动批准、网页代 commit、Hermes/HQA 推测完成 |
| Intent payload seam | owner-only、content-addressed、加密/TTL 的普通 chat 与 research 输入 | command lifecycle、result、secret |

`AgentWorkspace` 自己不建立第五份业务 journal。snapshot、workspace event merge 和 cursor 都必须
可以从上述权威重建。

### 4.3 Production adapter 与 hermetic fake

| Seam | Production adapter | 测试替身 |
|---|---|---|
| Hermes Run | reviewed official loopback HTTP adapter | scripted fake：支持 accept 后丢包、重启、event gap、quota/fallback、approval stale、partial stop |
| PostgreSQL transport | 现有 repository + 后续 additive schema | 独立临时 PostgreSQL；不使用 SQLite 冒充 lease/transaction |
| HQA authority | 固定绝对 executable、argv 数组、strict JSON stdin、限时限输出 | temp-dir `ResearchWorkflowStore` / contract fake |
| Platform domain | 现有 repositories、CLI、artifact reader | immutable fixture repositories，paper/live 永远无 adapter |
| Key/clock/ID | macOS Keychain、system clock/ID | deterministic key、frozen clock/ID |

fake adapter 只服务 contract、fault injection 和完整 UI 状态测试；生产和 fake 必须实现同一个
interface。fake 不是临时产品路径，也不能通过 feature flag 面向用户开放。

## 5. 冻结的提交、恢复、事件和控制语义

### 5.1 每个 user action

1. 校验 accepted Host、signed local session、same-origin、`Sec-Fetch-Site`、CSRF 和 actor ownership；
   loopback 本身不等于登录。
2. 先验证 actor 对 Workspace 的 ownership，再在
   `owner_id + workspace_id + action_kind + client_action_id` namespace 内 canonicalize action 并计算
   digest；只有授权后才可返回 cached receipt，同 ID 不同 digest 返回 409 且零新增写入。
3. 校验 session 类型与 immutable provider policy；`observed_external_session` 拒绝写入，改变
   provider 或从 Discord/历史继续必须 fork 到新的 `web_managed_session`。
4. 将 prompt 写入 intent payload authority；prompt 不进入 argv、stdout、日志或 PostgreSQL。
5. 对 research action，由 HQA prepare/advance Task/Attempt；普通 turn 不伪造 Task。
6. PostgreSQL 单事务写 exact command/binding、version-1 event、outbox 和 notify。
7. HQA 观察 exact transport binding；第二权威观察失败则返回 `reconciling`，不让浏览器换 ID
   重提。
8. HTTP 返回 durable `ActionReceipt`；请求线程内不调用 Hermes/provider。
9. worker 短事务 claim，释放 transaction 后再 resolve payload、调用 Hermes。
10. Hermes 使用同一 durable request identity 执行 `submit-or-recover`；timeout 后先 lookup，禁止
    盲重发。
11. PostgreSQL 写 exact session/run link；HQA 观察 Attempt/Run/provider/result refs。
12. 终态前完成跨权威 reconcile；unknown 不能自动变成 failed 或重新创建 Attempt。

### 5.2 Provider policy 与 evidence

- provider policy 只在 create/fork managed session 时设置并持久化；同一 session 内不可修改。
- Discord/历史 session 保持 independent external writer、Web read-only；fork 时不继承可变写权，
  而是显式选择新 policy、创建新 Hermes Session 并保存 immutable lineage。
- requested policy 是请求事实；actual provider/model 只能来自 exact Hermes Run/event。
- fallback 只允许 session 创建时明确批准的链；链外切换必须失败。
- UI 展示 requested、actual、fallback from/to/reason、usage 和 evidence source；缺失就是
  `unknown`，且正常研究 Task 不能进入无条件 `completed`。

### 5.3 Workspace event 与 SSE

每个 source 保留自己的稳定 cursor。平台在 PostgreSQL 建立一个**可删除重建的 observation
projection**，用 `UNIQUE(source_authority, source_event_id)` 去重，并给“平台观察到事件的顺序”
分配 workspace cursor。这个 cursor 不宣称三份 authority 的真实全局因果顺序，也不能反向更新
任何 source；projection 删除后必须能从 PG command events、HQA events 和 Hermes per-Run
cursor replay 重建。

恢复顺序固定为：

```text
snapshot -> 获得 snapshot_workspace_cursor
         -> replay workspace projection 中 cursor 之后的 durable observations
         -> ingestion worker 按各 source checkpoint 补缺/去重
         -> 进入 live wait
```

每个 UI event 必须带 `workspace_cursor + source_authority + source_event_id + source_cursor +
observed_at`。SSE `id:` 使用 workspace cursor。cursor 未知、过期或 source checkpoint 出现 gap 时
返回 `resync_required`，重新 snapshot/rebuild；不得静默跳到“现在”。BFF 只能在 observation 已
durable append 后向浏览器发送；SSE 断开不停止 Run。

### 5.4 Approval

Hermes command approval 至少绑定：

```text
approval_id + run_id + canonical command digest + expires_at + expected_status=pending
```

只支持 allow-once / deny，必须 TTL、single-use、CAS。Domain Gate 不使用通用 `gate_kind` payload：

- Gate 1 `ConfirmFormulaSource` 由 HQA 权威保存 exact reviewed source SHA-256、非空 confirmation
  note，并在 candidate 产生后保存 exact candidate/manifest binding；research plan digest 不是
  Gate 1，也不能替代 source bytes provenance。
- Gate 2 `ReviewCandidateCAS` 由平台 repository 对
  `candidate-id + expected-digest + expected-status=pending + note` 做人类 CAS；批准时严禁
  list/refetch/substitute digest/status。
- Gate 3 `PreparePromotionReview` 由 HQA wrapper 重验 Gate 1 binding 和同 candidate/digest 的
  content-addressed successful final receipt，再委托平台 primitive 产 isolated diff/base
  commit/manifest；最终完成事实仍只能是人类 Git review + commit，网页永不代 commit。

### 5.5 Stop

Stop receipt 不能是一个布尔值，必须逐层展示：

```text
Hermes Run: requested | confirmed | already_terminal | unknown
HQA Attempt: requested | confirmed | already_terminal | unknown
platform async job: requested | confirmed | not_applicable | unknown
overall: requested | reconciling | stopped | already_terminal
```

只有所有仍可能产生 artifact 的 target 都确认终态，Task 才能显示 `stopped`。重复 stop 使用同一
stop request identity；任一层未知都继续 reconcile，不能新建 Run。

### 5.6 本地认证、威胁模型与数据保留

V0 冻结合同，V4 实现以下边界：

- 首次 owner bootstrap 使用 macOS Keychain 或 owner-only `0600` 文件中的一次性 token；交换后
  立即轮换，签名 key 不进仓库、日志或浏览器脚本。平台签发 12 小时的 `HttpOnly`、
  `Secure`（适用时）、`SameSite=Strict` signed cookie，并配独立 CSRF token。
- 防护范围明确包括恶意外站诱导访问 loopback、跨 Origin 请求、伪造/过期 cookie、错误 owner、
  浏览器扩展读取 DOM 后的最小暴露和重放。恶意 same-UID 本地进程可读取用户文件/进程内存，
  不在 v0.2 可可靠防御范围；仍通过 Keychain/0600、最小权限和不记录 secret 降低暴露。
- 所有 mutation 必须同时通过 actor session、Origin/`Sec-Fetch-Site`、CSRF、ownership、action
  digest 和速率/大小限制；只绑定 `127.0.0.1` 不是认证替代品。

| 数据面 | v0.2 冻结策略 | 删除/恢复语义 |
|---|---|---|
| Intent payload | owner-only 加密；managed session 默认 TTL 7 天，可在创建时选 1–30 天且之后不可放宽 | 到期删除正文并留 digest tombstone；reconcile 不得从 transcript/backup 偷偷复活正文 |
| Hermes transcript | Hermes canonical store 按其已审查的 session policy 保留；v0.2 不自动随 payload TTL 删除 | export/delete 是独立显式操作；payload 删除不等于 transcript 删除 |
| PostgreSQL | 只存 digest、refs、command/event/audit 与 lineage，禁止 prompt/message 正文 | append-only 事实按 workspace 审计保留；v0.2 不提供隐式 GC |
| Operational log | 禁止 request body、prompt、assistant body、bearer/provider secret；轮转上限 14 天 | 日志不能作为恢复 authority |
| Browser | `Cache-Control: no-store`；正文只在页面内存，禁止 localStorage/IndexedDB/service-worker cache | 关闭/刷新后不保留 plaintext；恢复只从 authenticated BFF |

backup/restore drill 必须证明已到期 payload 不会被旧备份无声复活；若 restore 包含仍在 TTL 内的
密文，恢复后继续遵守原 `expires_at`，不得重新计时。

## 6. 九项 upstream blocker 如何进入最终架构

九项不是“恢复/事件/provider 的仪式性要求”，也不需要一次写成一个巨型模块；它们分成五个
可独立开发的 capability Gate。但用户已明确不要临时产品，所以每个 Gate 只做 dark tracer
bullet，公共 composer 保持 OFF，C1-C5 全绿后才一次发布。

| Gate | 能力 | 必须清零的现有 blocker |
|---|---|---|
| C1 | 可恢复的非流式 turn | submission idempotency、request recovery、persistent Run、immutable provider policy、actual provider evidence |
| C2 | stream / reconnect / resume | C1 + stable event ID + cursor replay |
| C3 | 长任务研究生命周期 | C2 + HQA Task/Attempt lifecycle、worker dispatch、exact Run/result link |
| C4 | exact command approval + Domain Gates | C2/C3 + approval exact binding；两类审批保持分离 |
| C5 | stop / reconcile | C2/C3 + Run-scoped idempotent stop、HQA/platform 分层对账 |

平台侧的 auth/CSRF、prompt retention、dispatch adapter、Task binding、composer 状态机、独立安全
review 和用户 cutover approval 也必须全部清零。平台本地 ledger 不能替代 Hermes canonical
能力；capability JSON 写成 `true` 不是验收证据。

## 7. 实施切片

### Slice V0 — Interface、cardinality 与计划权威冻结

**目标：** 在任何 migration 或写端实现前，先固定三入口、action union、状态机、错误、权威、
cardinality 和三仓交付边界。

交付：

- 新增 Agent Workspace ADR / versioned contract；覆盖 ordinary turn、research start/continue、
  external→managed fork、stop、command approval、plan confirmation 和三种不同 Domain Gate action。
- 把本计划已经选择的 migration 方案 A 写入 ADR：直接修订从未 live apply 的 006；同步 SQL、
  schema meta/version、readiness、repository、claim、reverse audit、rollback 和全部合同测试。当前
  replay-all runner 下禁止用“006 后补 007”规避问题。
- 冻结 external/managed session 所有权：Discord/历史 session 在 Web 只读；任何 Web 写入只能
  使用新建或显式 fork 的 managed Hermes Session，并保存 lineage 与 immutable provider policy。
- 冻结 owner bootstrap、cookie/CSRF threat model 和 §5.6 retention matrix。
- 冻结 stable error taxonomy：validation/auth/conflict/stale/capability/unavailable/
  outcome_unknown/expired/integrity/quota/forbidden，以及明确 recovery action。
- 建立三仓 source/runtime manifest：HQA、ai-quant-platform、本机 Hermes checkout/installed process；
  开发不得直接在未固定身份的 live Hermes checkout 上随手改代码。
- 把本计划登记为唯一 active backlog；旧 Wave 3 顶部标记 predecessor delivery record。

验收：

- contract test 证明同一 Research Task 的 Attempt #1/#2 可 exact-bind 不同 submission
  Command，且一个 Attempt 不能绑定两个 submission Command；ordinary turn 有 Command/Run
  而没有 HQA Attempt。
- 普通 turn 与 research action 都通过同一个 control plane，但普通 turn 不产生虚假 HQA Task。
- 三种 Gate action/route/payload 在类型和物理 route 上互不兼容；plan confirmation 不能冒充
  Gate 1。
- migration、Hermes mutation、provider call、browser mutation 均为零。

状态：**HQA-side DONE / 三仓 PENDING → V0 不是 DONE。** HQA 侧 executable model/contract tests 已
交付（5 模块 + 622 测试全绿）；三仓 source/runtime manifest 一致性、primary validation 与三仓
cross-review 均 pending。

**V0 交付记录（§8.2，2026-07-17）：**

- **HQA commit/branch**：`codex/full-9h` @ `5775d9a`（`3a95dd0` 已 fully merged，`merge-base = 3a95dd0`；
  其上修复 `5775d9a` = contract.py astimezone `OverflowError` fail-closed + 回归测试）。frozen base
  `a7428b6219ded4550f4c8951b6fabc4542a1724f`。
- **工作树**：HQA 干净。platform（`audit-remediation-2026-06-23` @ `7b73b5f2`）dirty（options 数据/代码，
  与 V0 无关，未处置）；Hermes（`main` @ `9baa7d467`）干净但落后 origin/main 385 提交。
- **新增 contract/schema version**：5 个 `hqa/agent_workspace_*` 合同模块（`UserActionV1` / WorkspaceSnapshot /
  cardinality / 错误分类 / retention），无 migration schema 变更（006 修订属 V1+，本 Slice 未触碰 SQL）。
- **测试命令与结果**：`python -m pytest tests/test_agent_workspace_*.py` → **622 passed**；全量
  `python -m pytest tests/`（JUnit 统计）→ **1442 tests / 1439 passed / 1 failed / 2 skipped**；唯一失败
  `test_hermes_read_bridge::test_loopback_ws_roundtrip_session_list` 为沙箱禁 socket bind 的环境限制（基线同样失败，非回归）。
- **三仓 cross-review**：见 `../../audits/2026-07-17-v0-three-repo-cross-review.md`（只读核查；platform 恰在
  冻结 commit 但分支名不符且 dirty、Hermes candidate 分支与冻结 base 未落地 → 三仓一致性未闭环）。
- **未触发**：migration / Hermes mutation / provider / paper / live / broker / Gate / redirect / browser
  mutation / live apply 均未触发；零 live effect。
- **未清零 blocker**：三仓 candidate 分支/manifest 一致性 + primary validation 签名（见上"关闭 V0 还需"）。

### Slice V1 — Stop-the-line launch baseline

**目标：** 先消除“只要启动服务就可能越权改变状态”和已知会让最终验收失真的基础问题。

交付：

- 将 `DatabaseSettings.auto_migrate` 默认值改为 false；startup 不得扫描并自动 apply 所有 SQL。
  新 migration 只允许显式命令 + allowlist + dry-run/plan + 单独授权。
- 在允许任何 browser writer 前收紧本地 DB writer 权限，验证 RLS/append-only trigger 对运行角色
  有效；不得依赖 superuser/bypassRLS。
- 修复 Gate 3 generator 产物的 Ruff/standard verify；修复前端离线 build 对 Google font 网络的
  依赖。
- 修复 session UI 的 internal compaction/空消息泄露，建立 transcript allowlist 与 DLP fixture。
- 修复 Options minimum APR 语义，增加真实/样本数据醒目标记；paper account UI fail closed，不用
  fallback 数据伪装真实账户。
- 清理 `.superpowers/brainstorm/.last-token` 等运行噪声的 tracked/untracked 治理，但不删除用户
  现有 `.superpowers` 证据。

可并行但不阻塞 C1 开发、必须在最终 launch 前完成：daily-close `skipped_busy` retry/projection
与当前 automation 操作可见性。

验收：

- backend/frontend 启动不会自动 apply 任何尚未授权 migration；迁移前后 schema 指纹不变。
- 标准 verify、离线 production build、APR fixture、sample warning、transcript/DLP 测试全绿。
- browser bundle/API/log/argv 无 Hermes bearer、provider secret 或 prompt 泄露。

**V1 交付状态（2026-07-17，platform 分支 `codex/agent-v0-2-platform-v1`）：**

- **V1.1 migration auto-apply stop-line — DONE**（`ce79d38`）。`auto_migrate` 默认 false；新增 fail-closed
  `quant-system migrate`（dry-run 默认 + `--allow` allowlist + `--yes` + 前后 schema 指纹）。startup 不再自动 apply。
- **V1.2 收紧本地 DB writer 权限 — PARTIAL（V1.2A = `code_hardened / live_role_unprovisioned`，`9185c45`）。**
  仅代码加固：005 四个 append-only trigger 幂等 `ENABLE ALWAYS`（never-live 006），writer readiness 只接受
  `tgenabled='A'`。隔离库对抗测试证明：持 DML 的 NOSUPERUSER 角色仍被 trigger 拒、不能 ALTER/DISABLE TRIGGER、
  不能 `session_replication_role=replica`，superuser replica 模式仍被拒。**live schema/role 零变更、零 RLS、
  browser writer / worker claim-dispatch / composer 全 OFF。live role provisioning + 逐表 RLS 属 V4（见 §7 Slice V4
  live activation Gate），本 Slice 不勾 DONE。**
- **V1.3 Gate 3 generator Ruff — DONE**（`c7db84d`）。抽出纯确定性 `_render_promoted_init`，模块级 import +
  ≤100 列折行；scaffold 写失败原子恢复旧 `__init__.py`。整库 `ruff check src/quant_system tests` 由红转绿。
- **V1.4 前端离线 build / 本地字体 — DONE**（`58d395f`）。4 族字体 vendor 为 woff2 + `next/font/local`，保留四个
  CSS var；离线 production build 成功、零 Google-Fonts 请求。
- **V1.5 transcript 空消息/compaction + DLP — DONE**（`16f4bc1`）。丢空/纯空白/compaction 行；保留消息 DLP
  脱敏（redact 非 drop，bounding 前应用防截断泄露）。
- **V1.6 Options min-APR 语义 + provenance 徽标 + paper account fail-closed — DONE**（`a95b37c` / `e7fb8ca` /
  `df7d725`）。min_apr 百分数语义仅澄清+测试（不动 API）；screener/radar 接 `DataSourceBadge`（sample 醒目警告）；
  paper account available-cash 经 `resolvePaperAccountAvailableCash` 在 apiError 时 fail-closed（不显 $1M fallback）。
- **V1.7 `.superpowers` git 治理 — DONE-by-inspection**（零改动，`.gitignore` 已覆盖运行噪声）。

**端到端验证（2026-07-17 全绿）：** 后端 `pytest` 1570 passed / 0 failed；`ruff check src/quant_system tests`
All checks passed；前端 `eslint`/`tsc --noEmit`/Vitest 224 passed；离线 `next build` 成功；隔离 pg 加固 80 passed；
`migrate` CLI dry-run/fail-closed/allowlist-apply 冒烟通过。3 个无关 options 文件全程保持 dirty 未提交。

### Slice V2 — Hermes `DurableRunAuthority`（C1 + C2 foundation）

**目标：** 在 Hermes canonical authority 内解决九项语义，不让平台投影冒充 upstream。

交付：

- 先固定 installed version、checkout commit、进程加载身份并审查 upstream delta；不得假定
  2026-07-16 本机快照仍是最新，也不得直接 `pull`/覆盖带本机状态的 live checkout。若新 upstream
  已有部分 durable 语义，优先复用并用同一 contract matrix 验证，不重复实现。
- 在单独受控 Hermes 开发 branch/worktree 中实现：
  - caller-supplied idempotency/correlation key 与 canonical request digest；
  - `submit-or-get` 和按 request identity lookup/recovery；
  - 持久 Run identity/status/session policy；
  - per-Run stable event ID、monotonic cursor、page replay + SSE；
  - requested policy 与 actual provider/model/fallback/usage 证据；
  - exact approval challenge、TTL、single-use、CAS；
  - idempotent stop intent 和 restart 后 reconcile。
- 更新 reviewed Hermes API contract 和 capability probe；probe 必须用行为证据，不只读 flags。
- 交付 `OfficialHermesHttpAdapter` 与同合同的 scripted fake。
- 通过受控 install/restart 将 reviewed commit 装入本机；记录 source commit、installed stamp、运行
  进程身份，不直接覆盖未知 live state。**install/restart 之前另向用户请求明确授权**；先备份
  Hermes config、state、installed stamp 和可恢复的启动配置，记录 rollback commit/package，
  并在授权范围内做 Discord 低成本 pre/post smoke。失败立即回滚并复验 Discord，不把用户当前
  可用入口当实验环境。

不可伪造验收：

1. Hermes 已接受请求但回包前 kill；重启后同一 request identity 找回同一 Run。
2. 重复 submit 只产生一个 Run；同 ID 不同 digest 冲突。
3. Run/status/event/provider policy/evidence 重启后仍在。
4. 任意 cursor replay 无 gap、无重复；SSE disconnect 不删除 canonical events。
5. fallback 只走预授权链并记录原因；无授权 fallback 明确失败。
6. approval 和 stop 重复请求幂等；stale/expired/digest mismatch 不改变原事实。

任一项失败，production adapter 只能报告 unavailable，后续 dispatch 继续关闭。

**V2 交付记录（§8.2，2026-07-19）：DONE_WITH_DOCUMENTED_RESIDUALS**

三仓坐标（重新验证，非旧文档抄写）：

| 仓 | branch / commit | 角色 |
|---|---|---|
| HQA | `codex/full-9h` @ `a186c62`（gate）/ `b2d5edb`（live acceptance） | OfficialHermesHttpAdapter + ScriptedFake + 6 项不可伪造验收 + line-528 availability gate |
| Hermes durable-runs worktree | `codex/agent-v0-2-durable-runs`（九语义 + V2.13 opt-in store + V2.6b evidence + SSE terminal） | 开发权威 |
| Hermes integration | `codex/v2-live-integration` @ `916f5fbf5` | merge of durable-runs onto live base |
| Hermes live install | `codex/v2-live-installed` @ `916f5fbf5`；rollback `main@8f657b8f7` | 受控 install；**durable flag OFF/dormant** |
| ai-quant-platform | 本 Slice 零改动；3 个无关 options dirty 文件全程保留 | — |

**九语义 + 交付项（Hermes worktree → integration → live install）：**

| 子项 | 状态 | 证据锚 |
|---|---|---|
| V2.1 固定 installed identity / upstream delta / 不 pull live | DONE | install stamp `~/.hermes/install_stamps/v2.12-installed.json`；rollback `main@8f657b8f7` 未动 |
| V2.2 idempotency key + canonical digest | DONE | Hermes `DurableRunStore.submit_or_get`；HQA fake+live conflict/duplicate |
| V2.3 submit-or-get / identity recovery | DONE | fake A1 kill-before-ack；live restart+resubmit same key |
| V2.4 持久 Run identity/status/session policy | DONE | store + GET `/v1/runs/{id}` 跨重启 |
| V2.5 stable event ID + monotonic cursor + page replay + SSE | DONE | store `event_id`+`seq`；SSE `id: {seq}`；cursor replay 无 gap/dup |
| V2.6 / V2.6b requested vs actual / fallback / usage 证据 | DONE | `set_requested_policy` + `record_run_outcome(agent=)`；fallback 写真实 agent.model |
| V2.7 approval challenge TTL / single-use / CAS | DONE | fake+live digest mismatch / expired 不消费 |
| V2.8 idempotent stop + restart reconcile | DONE | fake+live stop 幂等跨重启 |
| V2.9 capability probe 行为证据（非仅 flag） | DONE | 六 probe `supported+grounded`；异常 → grounded=False |
| V2.10 OfficialHermesHttpAdapter + ScriptedFakeHermesAdapter 同接口 | DONE | HQA `hqa/hermes_run_adapter.py`；fake 脚本化故障注入 |
| V2.11 六项不可伪造验收（hermetic fake） | DONE | `tests/test_hermes_run_acceptance.py` 19 |
| V2.12 受控 install（backup → swap branch → durable OFF → Discord pre/post smoke） | DONE | stamp + backup `~/.hermes/v2.12-backups/20260719T000836`；post_smoke **GREEN**；listen `127.0.0.1:8642`；Discord Hermes-bot#0306 |
| V2.12-A hermetic real-Hermes live acceptance | DONE | `tests/test_hermes_run_acceptance_live.py` 13；IsolatedHermes + MockLLM SSE + white-box sqlite3 |
| V2.12-B line-528 availability gate（dispatch closed when dormant） | DONE | `evaluate_durable_run_availability` / `require_durable_available`；`durable_unavailable`→503；live `:8642` 实测 `durable_block_absent` |
| V2.13 `build_durable_store` opt-in default-OFF | DONE | Hermes `3ace5b380`；broker 仅 store non-None 时启用 |

**HQA 测试基线（2026-07-19 重新跑，exit 0）：**

```
tests/test_hermes_run_adapter.py          48
tests/test_hermes_run_acceptance.py       19
tests/test_hermes_run_acceptance_live.py  13
合计                                       80 green
```

**Live 运行态（重新验证）：**

- 进程：`python -m hermes_cli.main gateway run --replace`，listen `127.0.0.1:8642`，launchd `ai.hermes.gateway`
- `GET /health` → `{"status":"ok","platform":"hermes-agent","version":"0.18.2"}`
- `GET /v1/capabilities` **无** `durable` 块（flag OFF）→ gate `available=False, blockers=('durable_block_absent',)`
- `require_durable_available()` → `HermesRunError(code=durable_unavailable, http_status=503)` —— **dispatch 关闭，符合 line 528**
- **未** 启用 live durable ON；**未** 触发 provider / paper / live / broker / Gate / redirect
- 用户当前 Discord 入口保留；失败路径有 stamp 内 rollback 步骤

**Documented residuals（不阻塞 V2 DONE；显式不声称已清零）：**

1. **SSE wire 上 `event_id` 字符串**：store 有 `evt_<hex>`，SSE 帧目前用 numeric `id: {seq}` 作 resume cursor；HTTP adapter `event_id=None`。Resume/replay 已由 monotonic seq 落地。可选后续把 store `event_id` 放进 SSE data payload。
2. **状态名 completed/cancelled vs succeeded/stopped**：store 与 broker 双名兼容（`_broker_is_terminal` 已含两侧）；对外契约以 API 返回值为准。
3. **Approval TTL 白盒**：live 用加速时钟/短 TTL 路径验证过期不消费；生产默认 300s 未做 wall-clock 长等。
4. **Live durable ON canary**：install 刻意 flag OFF。打开需**单独 canary 授权**（备份→ON→短冒烟→OFF/rollback）。当前 gate 保证 OFF 时 dispatch 关闭。
5. **Fake capabilities 恒 grounded**：scripted fake 构造上 broker-on，`grounded=True` 硬编码；真实 Hermes 由 live suite + V2.9 probe 覆盖。
6. **Live A1 弱于 plan 字面**：live 是 terminal 后重启再同 key 恢复，不是 accept-before-ack 中途 SIGKILL；后者由 hermetic fake A1 覆盖。
7. **V2.6 无 agent 路径**：无 agent/`_model_name` fallback 仍可能与 `_resolve_gateway_model()` 有细微差；V2.6b 在有 agent 时已写真实 model/provider。
8. **真 TCP RST disconnect**：现覆盖 client-drop reconnect；mid-stream TCP kill 可选加固。

**明确未做 / 红线遵守：**

- 不实盘；不 provider smoke；不 paper/live/broker/Gate/redirect
- 不把用户当前工作入口当实验环境；Discord pre/post smoke 后保留
- live durable 保持 OFF，直至另行 canary 授权
- ai-quant-platform 3 个无关 options dirty 文件未触碰
- 不启动 V3（本记录关闭 V2 后另开）

### Slice V3 — HQA Intent / Workflow Authority 深化（C3 foundation）

**目标：** 把已交付的 prepare/binding 地基扩成完整多 Attempt 研究生命周期，同时为普通 turn
提供共享 intent payload seam，而不复制 transport authority。

交付：

- 从当前 payload code 提炼 versioned `IntentPayloadStore`：owner-only、content-addressed、
  Keychain-backed encryption、TTL/delete/reconcile；普通 turn 与 research 共用。
- HQA `WorkflowAuthority` 只暴露 typed command + snapshot + events；实现：
  - Task draft/plan_proposed/awaiting_plan_confirmation/awaiting_formula_confirmation/ready/
    running/awaiting_domain_gate/terminal；
  - Attempt planned/running/reconciling/stop_requested/terminal；
  - plan revision/digest、new Attempt、Run link observation；
  - provider evidence、Gate refs、result refs、stop observation；
  - expected-version CAS、stable event ID、replay、projection rebuild。
- 安装 `hqa-research-task` 和对应 Hermes skill；加入 supervised payload retention/reconcile。
- 建 authority backup/restore、projection destroy/replay 和 reverse audit runbook。

验收：

- Research Task 1:N Attempt 的完整 reducer/contract tests；终态 Attempt 永不改写；ordinary
  conversation 不创建 Task/Attempt。
- 两个进程并发更新、commit-ack 丢失、payload expiry、journal 损坏、projection 删除/重建均
  收敛或 fail closed。
- backup -> restore -> replay 后 Task/event/payload digest 一致。
- prompt 不出现在 argv、journal、projection、stdout、platform binding 或错误信息。

### Slice V4 — PostgreSQL schema、BFF submission saga 与安全边界

**目标：** 完成普通 turn 和研究 Task 的 durable acceptance；HTTP ack 不等待 Hermes。

交付：

- additive platform session registry：明确 `observed_external_session` 与 `web_managed_session`、
  1:1 exact Hermes Session、immutable provider policy、fork point/parent/channel lineage 和 owner；
  external session 的 mutation 在 application/repository 两层都 fail closed。
- general intent payload binding 与 research workflow binding；按方案 A 修订 006 cardinality，确保
  unbound/expired/mismatched command 永不可 claim。
- 一个深的 `AgentWorkspace` application module；FastAPI routes 只做 transport adapter。
- owner-only one-time bootstrap、Keychain signing key、signed `HttpOnly` / `SameSite=Strict` local
  session cookie、same-origin/Origin/`Sec-Fetch-Site`、CSRF、ownership、rate/size limits 和不含
  request body 的安全审计；按 §5.6 明确 hostile web origin 与 same-UID 边界。
- action digest/idempotency、HQA↔PG crash-safe saga、commit-ack recovery、stable error envelope。
- schema/authority readiness；任一 authority 不可写时 composer 整体 fail closed。

live activation Gate：

1. V1 migration guard 已运行验收；
2. 修订后的 006 与 migration runner 已完成空库、005 现有库、幂等 apply、权限、
   backup/restore、concurrency
   和独立 review；
3. 再向用户请求**一次明确 migration 授权**；
4. 在同一受控窗口 backup、apply 全部已批准 migration、幂等重放、readiness、零行/预期行审计；
5. apply 完仍保持 worker reconcile-only、browser mutation OFF。

验收：

- 双击同 ID/digest 返回同 receipt；同 ID/不同 digest 409，零第二条 command。
- 分别在 HQA prepare 后、PG commit 前、PG commit 后、HQA observe 前 kill，reconcile 后只有一套
  exact authorities。
- cross-origin、缺 CSRF、伪造/过期 cookie、错误 owner、超限 prompt 对 PG/HQA/Hermes 零写入。
- 对 external session 发 turn/stop/approval 返回冲突且零写入；显式 fork 创建新的 managed
  Hermes Session，保存 lineage，不改变原 Discord/历史 session。

### Slice V5 — Supervised claim / dispatch / reconcile worker（C3）

**目标：** 将 reconcile-only worker 深化为最终 dispatch worker；没有另一个临时 daemon。

交付：

- claim/lease/fencing/heartbeat/backoff/supervision/readiness/liveness；网络调用永远在 DB 事务外。
- claim 后重新验证 binding、payload TTL、session policy、capability 和 kill switch。
- `submit-or-recover` Hermes adapter；timeout 进入 durable `outcome_unknown`，禁止盲重发。
- exact session/run link、HQA Attempt start/terminal/provider/result observation。
- terminal、expired lease、provider quota、worker/Hermes restart 和 partial result reconcile。
- 空队列只做 SQL/notify wait；Hermes/provider 调用严格为零。

crash matrix 必须逐点 kill：

```text
PG claim commit 后
Hermes submit 前
Hermes 已接受但回包前
PG exact Run link 前
HQA observe Run 前
result link 前
terminal reconcile 前
```

每个场景最终满足：一个 action -> 一个 submission command -> 最多且最终一个 Run；research
action 还有一个 exact Attempt；零盲重发、authority audit consistent。只有 fake fault matrix
全绿后，才向用户单独请求一次低成本真实 provider smoke 授权；计划批准本身不授权该调用。

### Slice V6 — Workspace snapshot/follow 与完整 Web Chat UI（C2）

**目标：** 直接把现有 production `/hermes` shell 变成最终 workspace；不另写临时 frontend。

交付：

- `WorkspaceSnapshot` 并列展示 command、Task、Attempt、Run、provider evidence、approval、
  result refs 和各 authority health；冲突派生为 `reconciling`，不覆盖 source facts。
- durable workspace observation cursor、snapshot -> replay -> live SSE；BFF 重启不依赖内存
  buffer，projection 可从 source cursors 重建。
- composer 只对 managed session 启用；external session 显示只读来源和“fork 到 Web managed”
  入口。composer 支持新 managed session/fork、普通 turn、显式研究模式；发送状态区分
  submitting/checking/accepted/reconciling/conflict/unavailable。
- transcript + assistant stream、Task drawer、plan/step、typed result canvas、provider/usage、
  source/freshness；技术事件默认折叠。
- connection state 与 Run/Task state 正交；用户向上阅读时不抢滚动。
- 1440/1280/768/390、中文英文长文本、长 ID、键盘/focus/reduced-motion/WCAG AA。

验收：

- 任意事件边界断网 30 秒，重连后不丢、不重；未知 cursor 明确 resync。
- 浏览器刷新、BFF/worker/Hermes 重启后同一 workspace 可恢复。
- internal compaction、空 assistant、system/tool/reasoning、secret 永不进入用户 transcript。
- 前端只调用 `AgentWorkspace` adapter；无 direct Hermes、provider 或旧 agent-task fallback。

本 Slice 完成后仍保持公共 `chat_write_ready=false`；只允许 hermetic fake 和受控 dark smoke。

### Slice V7 — Decisions、typed results 与两条最终纵切（C4 + C5）

**目标：** 补齐完整 Agent 所需的 command approval、Gate 1/2/3、stop 和可独立理解的量化结果。

#### 纵切 A：研究 AAPL 卖 Put

```text
自然语言研究目标
-> durable action receipt
-> Task/Attempt/Run
-> Futu read-only 查询
-> streaming + replay
-> typed options result
-> actual provider evidence
-> exact links
-> completed / completed_degraded
```

typed result 至少包含 ticker、expiry、strike、bid/ask、Delta、IV、APR、数据时间/freshness、筛选
条件、排除原因、风险/limitations、requested/actual provider 和 exact IDs。APR 语义必须由独立
fixture 和真实只读 smoke 验证；结果不能触发订单或账户 mutation。

真实 Futu read-only 查询仍是外部 provider 调用：hermetic/fixture 验收全绿后，必须为 exact
ticker、字段、次数和时间窗单独请求授权；不得把“只读”解释为本计划已授权真实调用。

#### 纵切 B：论文因子复现

```text
受限 PDF/URL ref + 自然语言目标
-> plan-only Run
-> ConfirmResearchPlan exact plan digest（不是 Domain Gate）
-> Gate 1 exact reviewed formula/source SHA-256 + non-empty note
-> new proposal Attempt/Run
-> candidate
-> Gate 1 exact candidate/manifest binding
-> Gate 2 exact candidate/digest/pending/note，no-refetch
-> content-addressed final backtest receipt
-> Gate 3 isolated diff/base commit/manifest
-> 人类 Git review + commit
-> HQA observe canonical completion
```

网页不代 commit；Gate 3 commit 之前 Task 不能伪装 completed。Gate/command approval route、类型、
digest、TTL 和审计必须做互不兼容的独立安全 review。

本纵切的真实 final backtest、Gate 1 HQA mutation、Gate 2 platform CAS、Gate 3 preparation，以及
最终人类 Git commit 是五个独立状态变化；每一步只在前置证据绑定后展示 exact action，并分别
取得用户当次明确确认。此前 Scene-B 的批准、批准本计划或启用 canary 都不能复用为这些授权。

Stop 验收覆盖 running text、awaiting approval、平台作业不可取消、重复点击、Hermes 已终态和
部分成功；任一未知层都保持 reconciling。

### Slice V8 — 对抗验收、冷启动与一次发布

**目标：** 用故障而不是 happy path 证明 v0.2 可以真正日常使用。

自动与本地真实验收矩阵：

| 场景 | 必须观察到的证据 |
|---|---|
| 双击发送 | 同 action ID/digest 只有一套 command/Run；research action 才另有一个 exact Attempt |
| 同 ID 不同内容 | 409，零新 command/Run |
| BFF ack 丢失 | 同 ID 找回原 receipt |
| worker 在 commit 后崩溃 | 重启恢复 existing command，不重复 Run |
| Hermes 接受后 timeout | outcome_unknown -> request lookup 找回；零盲重试 |
| SSE 断线/刷新 | snapshot/replay 后消息和事件不丢不重 |
| Hermes 重启 | Run/status/events/provider evidence 仍可读或诚实 reconcile |
| fallback | 仅预授权链；UI 显示 from/to/reason/usage |
| stop 重复/部分成功 | request 幂等；对账前不显示 stopped |
| command approval | exact digest/TTL/single-use；stale/expired/repeat 全拒绝 |
| Gate 1/2/3 target 变化 | 旧批准 409；Gate 2 不 refetch/substitute；Gate 3 网页不 commit |
| plan confirmation 冒充 Gate 1 | 拒绝；没有 exact source SHA/non-empty note/binding 就不能进入 Gate 2 |
| Discord/历史 session Web 写入 | 409 且零 mutation；fork 后产生新 managed Session 和 immutable lineage |
| HQA journal/PG 不可用 | mutation fail closed，不绕过直调 Hermes |
| cross-origin/无 CSRF | 零 PG/HQA/Hermes mutation |
| provider evidence 缺失 | 结果未验证，Task 不进入正常 completed |
| sample result | 醒目 synthetic 标记，不与真实结果混淆 |
| 交易边界 | paper/live/kill switch/Gates 未变化，真实交易调用恒为零 |

最终 Gate：

1. HQA、platform、frontend、Hermes contract/full suites 和离线 production build 全绿。
2. DB migration/权限、HQA authority、Hermes Run store 均完成 backup/restore drill。
3. 两轮从零冷启动；历史 workspace/session/task/run/result 深链可恢复。
4. 独立 security review 和 code review 为 CLEAR。
5. 此时 public `agentV02WebChat` / `chat_write_ready` 仍为 OFF；用户另行授权后，只给 owner 签发
   一个短时、exact build digest 绑定的 **release-candidate canary grant**。它使用最终生产代码、
   同一个 `/hermes` route、同一 AgentWorkspace/PG/HQA/Hermes authority 和同一数据，不是备用
   页面、第二套 architecture 或临时 chat。
6. 用户凭 canary 从 `/hermes` 完成两条纵切并明确接受；成功证据 durable 落账后立即撤销 canary
   grant。任一异常则撤销、保持 public OFF、执行 rollback/reconcile，不能靠换 route 绕过。
7. 只有步骤 1–6 全绿，才一次打开单一 public flag；没有 C1/C2 等面向用户的半成品开关组合。
8. 打开后保留一键关闭 Web mutation 的 rollback；关闭不删除 append-only facts，不影响 Discord。

## 8. 计划治理：避免再次偏航

### 8.1 唯一 active queue

- 产品方向：roadmap D-32。
- 唯一 implementation backlog：本文件。
- `2026-07-15-d31-wave3-official-api-bff.md`：predecessor delivery record，只提供已完成事实和
  blocker 输入。
- D-31 design spec：产品/安全设计约束，不用其中候选阶段的旧顺序替换本计划。
- platform `phase_15_iteration_roadmap.md`：参考材料，不是第二路线图。

### 8.2 每个 Slice 的必填交付记录

完成一个 Slice 时必须在本文件顶部进度表和该 Slice 下追加：

- HQA / platform / Hermes exact commit 和 branch；
- 工作树是否有用户 dirty，是否被保留；
- 新增/修改的 contract 和 migration schema version；
- hermetic tests、isolated PostgreSQL、frontend、offline build 的完整命令与结果；
- 如发生 live apply/install/smoke：授权、备份、restore 验证、运行进程 identity、前后行数和
  provider 消耗；
- 尚未清零的 blocker；
- 明确说明没有触发的 provider、paper/live、broker、Gate 或 redirect。

checkbox、代码存在、测试通过、live 运行和用户 cutover 是不同状态，必须分别写。任何旧文档的
测试计数、PID、端口、branch、dirty 或 health 在下一轮开始前都要重新验证。

### 8.3 进度表

| Slice | 状态 | 下一准入 |
|---|---|---|
| V0 Interface/cardinality/authority freeze | HQA-side DONE / 三仓 PENDING → not DONE | executable contracts 已交付（5 模块+622 测试绿）；三仓 manifest 一致性 + primary validation + cross-review 见 `../../audits/2026-07-17-v0-three-repo-cross-review.md` |
| V1 Stop-the-line baseline | platform DONE（V1.2A PARTIAL = code_hardened / live_role_unprovisioned） | V1.2 live role+RLS 属 V4 Gate；其余 V1.1–V1.7 见 §7 V1 交付状态 |
| V2 Hermes DurableRunAuthority | DONE_WITH_DOCUMENTED_RESIDUALS | 九语义+adapter+6 验收+受控 install（durable OFF）+line-528 gate；live durable ON canary 另授权；见 §7 V2 交付记录 |
| V3 HQA Intent/WorkflowAuthority | NOT STARTED | Research Task 1:N Attempt + backup/restore green |
| V4 PG schema/BFF saga/security | NOT STARTED | code/isolated DB accepted；再请求 live migration 授权 |
| V5 supervised dispatch worker | NOT STARTED | crash matrix green；再请求 provider smoke 授权 |
| V6 final workspace UI | NOT STARTED | fake/real dark E2E green；public chat 仍 OFF |
| V7 decisions/results/vertical slices | NOT STARTED | 两纵切 + exact approvals + stop green |
| V8 adversarial acceptance/release | NOT STARTED | independent CLEAR + user acceptance + one-time cutover |

## 9. 当前立即执行顺序

1. 完成本计划、roadmap D-32、`docs/README.md`、`AGENTS.md` 和 predecessor banner 的同步复核。
2. V0 的 executable contract 子步骤 **已在 HQA 侧交付**（“修订未 live 006”方案、ordinary
   turn/research cardinality、三种 Gate 类型、external/managed session、owner auth/retention、
   `act/snapshot/follow` 已固化成 ADR + 5 模块 + 622 model/contract 测试）。仍 pending 的是三仓
   source/runtime manifest 一致性、primary validation 与三仓 cross-review（见
   `../../audits/2026-07-17-v0-three-repo-cross-review.md`）。
3. V1 stop-the-line **已在 platform 分支交付**（V1.2A = `code_hardened / live_role_unprovisioned`
   PARTIAL；live role+RLS 属 V4）。startup 不再 auto-migrate。
4. V2 Hermes DurableRunAuthority **已交付**（`DONE_WITH_DOCUMENTED_RESIDUALS`，见 §7 V2 交付记录）：
   九语义 + OfficialHermesHttpAdapter/fake + 六项验收 + 受控 install（durable OFF）+ line-528
   availability gate。**live durable ON canary 需单独授权**；未授权前 dispatch 保持关闭。
5. 下一施工入口 = **V3 HQA Intent/WorkflowAuthority**（hermetic fake/隔离状态）；V3 code accepted
   后与 V2 一并进入 V4 schema/BFF。修订 006 与 runner 通过独立 review 后再请求 migration 授权，
   不能默认追加 007。
6. V5 worker、V6 UI、V7 两纵切按 Gate 逐步集成，但公共 Web Chat 始终 OFF。
7. V8 完成后一次开放 v0.2；legacy redirect 仍另开后续计划。

这条顺序不再以“把九个 blocker 做完”为模糊任务，而是以最终用户路径、三入口 Interface、四份
权威和不可伪造的故障验收为施工边界。
