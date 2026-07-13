# Hermes 统一研究工作台设计 spec（D-31）

> 状态：**产品与架构设计已确认**（2026-07-13）；第一批三份正式 implementation
> plan 已选 wave：gateway capability 已冻结且 chat fail-closed；candidate
> integrity/Gate 3 已代码交付；professional frontend/read-only shell 已代码交付
> （2026-07-14）。本文仍不能直接当作 chat/bridge 或旧页退场的施工清单。
>
> 决策来源：2026-07-13 `superpowers:brainstorming`，逐节确认了产品范围、信息架构、
> Hermes 对接、provider 规则、研究生命周期、数据归属、故障恢复与迁移顺序。
>
> 上游：`docs/design/2026-07-01-roadmap-phases-0b-4.md` 的 D-17/D-19/D-20/D-25，
> 以及平台 `docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md`
> 的 Slice 0-8 交付记录。D-31 扩大并修订 D-17 的具体 UI 范围，但继承全部安全门。
>
> 双仓定位：`Hermes-quant-agent`（HQA）拥有研究编排；
> `/Users/sunyibo/programs/ai-quant-platform` 拥有领域后端、PostgreSQL 和平台前端。

---

## 1. 目的与现状

### 1.1 用户真正要解决的问题

用户不想继续在「因子实验室、回测器、实验管理、智能体工作室」四套彼此割裂、
参数密集且难理解的页面之间搬运上下文。目标是把 Hermes 变成平台的默认研究入口：

1. 用自然语言与本地 Hermes 讨论研究目标；
2. 先看到 Hermes 整理出的结构化计划，再经过必要的人审 Gate；
3. 由 Hermes 调 HQA，再调平台确定性 CLI/API/引擎执行；
4. 在同一个工作台查看执行过程、结果、审批与历史；
5. 保留平台成熟的因子、回测、实验、artifact、数据库和安全引擎，不把它们改写成
   一段不可审计的聊天文本。

### 1.2 2026-07-13 的实现事实

- Slice 9A-9H 已交付；当前 `/hermes` 是 feed schema 1.1 的六源只读工作台，能展示
  `portfolio_risk`、`prediction`、`market_foresight`、`weekly_review`、
  `opportunity_summary` 和 `automation_status`。
- 页面已有全局 `SafetyStrip`，Hermes 内容区又显示一张“仅模拟”警告，形成重复提示。
- `ArtifactShelf` 把来源状态、周复盘、机会、四个自动化任务及大量 cron/run/freshness
  技术字段铺成等权卡片，正常项与异常项没有清晰层级。
- 左侧“候选”实际是平台 `AgentRunner` 的研究候选，不是股票或期权候选；同时 HQA 的
  market-foresight 也使用 candidate 概念，语义冲突。
- 平台候选 API 当前按 `data/agent/candidates` 读取，而 CLI/HQA 的真实默认目录是
  `data/agent_run/agent/candidates`，会让 UI 假装“暂无候选”。
- `ComposerDock` 被 `allowSubmit=false` 硬禁用；`onSubmit` 没有真实网络调用。
- `POST /api/agent/tasks` 是旧平台同步 LLM runner，不具备 Hermes session、memory、
  run、SSE、stop、approval 或 provider 语义，不能复活成 Hermes 桥。
- 因子、回测、实验、智能体四个旧体验仍分别存在；其中结果图表、订单/持仓、归因、
  实验比较和候选审批具有价值，旧创建表单和重复导航则不应继续成为主工作流。

### 1.3 本设计成功的定义

完成后，用户打开平台即进入 `/hermes`，能在五秒内回答：

- 当前是否安全；
- 哪些事情需要我处理；
- 什么任务正在运行；
- 最近产生了什么结果；
- 从哪里开始或继续与 Hermes 对话。

网页 Hermes 对话链路必须真实经过本地 Hermes，并消耗该 Hermes session 实际使用的
provider；这条链路不得再由平台单独调用另一个 LLM，也不得伪造 provider、token 或
剩余额度。本约束不改变 AI 新闻等其他独立领域能力的既有数据来源。

---

## 2. 已确认的产品决策

| 主题 | 决策 |
|---|---|
| 默认首页 | `/` 默认进入 `/hermes`；保留全局平台侧栏，以便访问 paper、期权、AI 新闻、设置等非 Hermes 领域。 |
| 旧四页 | 因子实验室、回测器、实验管理、智能体工作室的**页面体验全部重做**并入 Hermes；后端引擎/API/artifact/安全门保留。 |
| 页面形态 | 采用自适应双状态：空闲时是“今日 COO 概览”，活跃时是“对话 + 执行 + 结果”工作区。完成任务后不强制跳回概览。 |
| Hermes 内导航 | `今日 / 对话 / 任务 / 待我确认 / 结果`；不再增加一条重量级侧栏。 |
| 安全提示 | 只保留全局顶部 `SafetyStrip`；移除 Hermes 内容区重复的“仅模拟”警告卡。 |
| 信息层级 | 一级为行动/异常，二级为结论摘要，三级为 cron、run ID、source freshness 和原始日志等技术细节。 |
| 候选命名 | 平台 AgentRunner candidate 的对象类型改称“研究审批项”，统一进入“待我确认”导航；HQA market-foresight candidate 改称“市场预测提案”。两者不可混为一类。 |
| Provider | 新 session 创建时选择 Grok 或 Codex 并锁定；切换 provider 必须新建或分叉 session。fallback 链必须由用户显式接受并在每个 Run 展示。 |
| 前端质量 | 当前 brainstorming HTML 只验证信息架构，禁止直接翻译成生产代码；必须由专业前端 Agent 重新做高保真、响应式与全状态设计，并经过用户确认。 |
| 安全范围 | 继续 read-only / proposal-only；不绕过 `paper_trading`、`live_trading_enabled=false`、`kill_switch` 或 Gate 1/2/3。 |

---

## 3. 信息架构与路由

### 3.1 两种主状态

#### 空闲态：`/hermes`

首页按下列顺序组织：

1. 全局安全状态；
2. 今日结论与真正需要人的异常/待办；
3. 运行中的研究任务；
4. 最近结果；
5. 固定且可见的 Hermes composer。

四个自动化任务在全部正常时压缩成一行“自动化 4/4 正常”。只有失败、过期、部分
降级或需要人的项目展开；cron 表达式、run ID、last/next run 和来源 freshness 默认折叠。

#### 活跃态：`/hermes/sessions/{session_id}`

桌面宽屏使用可调整的对话/过程区与结果画布；中等宽度折叠次要面板；手机按“状态 →
对话 → 计划/执行 → 结果 → composer”顺序单列。任务完成后保持当前 session，用户自行
返回“今日”，避免上下文突然消失。

### 3.2 统一路由

| 类型 | 新路由 |
|---|---|
| 默认首页 | `/hermes` |
| 会话 | `/hermes/sessions/{session_id}` |
| 任务 | `/hermes/tasks`、`/hermes/tasks/{task_id}` |
| 审批 | `/hermes/approvals` |
| 因子结果 | `/hermes/results/factors`、`/hermes/results/factors/{run_id}` |
| 回测结果 | `/hermes/results/backtests`、`/hermes/results/backtests/{run_id}` |
| 实验结果 | `/hermes/results/experiments`、`/hermes/results/experiments/{run_id}`；候选阶段 1 必须先核验 stable ID 并定义 additive ID/backfill 合同，候选阶段 4 完成索引后才能启用详情深链。 |

路由示例省略 locale；实现必须保留平台现有的中英文 locale 选择、prefix/query 语义。

### 3.3 旧路由兼容

| 旧路由 | 兼容目标 |
|---|---|
| `/agent-studio` | `/hermes/approvals` |
| `/factor-lab` | `/hermes?intent=factor-research` |
| `/factor-lab/{run_id}` | `/hermes/results/factors/{run_id}` |
| `/experiments` | `/hermes/results/experiments` |
| `/backtest` | `/hermes?intent=backtest` |
| `/backtest/{run_id}` | `/hermes/results/backtests/{run_id}` |

切流初期使用可回滚的临时 redirect 和独立 feature flag。只有深链、locale、query、浏览器
前进后退及结果 parity 全部通过后，才固化兼容 redirect。任何旧数据和 run ID 都不能因
UI 合并而失效。

---

## 4. 首页与结果的信息层级

### 4.1 首页只提升“变化”和“需要人”

- 最高优先：kill switch、Hermes/平台离线、数据过期、任务失败、待审批、provider
  quota/fallback、部分结果。
- 第二优先：当天组合风险结论、市场推演变化、周复盘结论、机会状态、最近研究结果。
- 第三优先：正常自动化、来源 manifest、cron、run ID、时间戳、原始 stdout/stderr。

同一 source 的状态只能出现一次。列表、表格和可折叠详情优先于大量同尺寸微卡片。

### 4.2 “待我确认”中心

“待我确认”统一展示需要人工动作的对象，但不合并其语义：

- Hermes command approval；
- Gate 1 研究计划/公式确认；
- Gate 2 candidate 源码审批；
- Gate 3 promotion diff 人工审查；
- 需要补判断字段的复盘草稿。

market-foresight proposal 属于“市场预测提案”，只读且 proposal-only；它不能因为被展示
在同一工作台就获得行动资格。

### 4.3 统一结果页

结果页必须脱离聊天文本也能独立理解：

- 因子：定义、provenance、IC/分位数/信号证据、数据范围、trial/holdout；
- 回测：核心指标、benchmark、equity curve、orders、positions、blotter、attribution、
  数据源和限制；
- 实验：参数 sweep、walk-forward、run comparison、稳定性、试验预算和 agent summary；
- 共同：源码/配置、审计事件、Gate 历史、artifact 路径和可复现标识。

结果正文继续从平台 canonical artifact/repository 读取；Hermes 的总结是解释层，不是结果
真相源。

---

## 5. 真实 Hermes 桥

### 5.1 拓扑

```text
Browser
  -> ai-quant-platform same-origin BFF
      -> HQA bridge/task CLI + atomic read projection
      |    -> append-only bridge journal + research task ledger
      -> loopback-only dedicated Hermes API Server
          -> dedicated HQA Hermes profile/session
              -> HQA skill (all task mutations use the same HQA CLI boundary)
                  -> platform deterministic CLI/API/engines
```

关键边界：

- 浏览器永远看不到 Hermes bearer key，不直接跨域访问 Hermes；
- Hermes API 只监听 loopback，使用专用 HQA profile、端口和凭证；
- BFF 做鉴权边界、capability 归一化、幂等、事件白名单和错误映射，不实现第二个 Agent；
- HQA 提供窄的 versioned bridge/task CLI：BFF 和 Hermes 都只能通过该入口写 journal；
  CLI 内部负责跨进程文件锁、expected-version CAS、稳定 event ID 和原子 projection；
- BFF 可在 Hermes 离线时通过 HQA 的只读 `list/show/events --json` 或严格校验的原子
  projection 读取 Task；平台不得直接修改 HQA ledger 文件；
- 平台旧 `POST /api/agent/tasks` 不作为 fallback；Hermes 离线时显式禁用提交；
- HQA skill 只提供批准范围内的 read-only/proposal-only 模板；平台执行仍走确定性接缝。

### 5.2 BFF 业务合同

精确 URL 可在 implementation plan 中按平台路由约定确定，但必须覆盖以下资源：

| 资源 | 能力 |
|---|---|
| capabilities/health | Hermes 是否在线、API 版本、可用 provider/model、SSE/approval/stop 能力；不返回秘密。 |
| sessions | 创建、列出、读取、分叉 session；创建时固化 provider policy。 |
| runs | 每条用户提交创建一个 Run；返回平台 public ID、Hermes run ID 和初始状态。 |
| events | SSE 白名单事件；支持稳定 `event_id`、cursor/`Last-Event-ID` 和快照对账。 |
| approval | 只处理 Hermes command approval；不能处理 Gate 1/2/3。 |
| stop | 幂等停止；已终态 Run 返回当前终态。 |

安装态 Hermes API 的精确 schema 必须在实施计划第一个 preflight 重新探测，adapter 只映射
真实存在的能力；不得先写前端假状态再倒逼不存在的接口。

session/Run 创建还必须探测至少一种确定性恢复能力：client-supplied idempotency key、
request correlation metadata，或按 `client_request_id` 查询。若三者都不支持，创建写端必须
fail closed；响应在返回 Hermes ID 前丢失时，禁止按时间戳、“最新 Run”或消息相似度猜测。

### 5.3 Provider 与额度

- 创建 session 时选择 primary provider/model，并可选择显式 fallback chain；随后不可变。
- 更改 primary 或 fallback chain 必须 fork/new session。
- 每个 Run 展示 `requested_provider/model`、`actual_provider/model`、fallback from/to/reason
  和 Hermes 实际返回的 token usage。
- provider 只允许使用 session 创建时已接受的链；链外 provider 不可静默启用。
- capability probe 若不能证明 Hermes 支持 per-session provider/fallback 固化，候选阶段 3
  必须 fail closed：不显示 provider selector，也不通过修改全局 Hermes 配置模拟 session 锁。
- subscription 剩余额度只有在 provider/Hermes 明确提供时才展示；未知就是 `unknown`，
  登录状态、token usage 或错误码不得被推导成伪造额度。
- 2026-07-13 现场快照为 Hermes 默认 `grok-4.5`、OpenAI Codex OAuth 已登录、未配置
  fallback；这是易变运行事实，UI 必须以 capability/run 返回值为准。

### 5.4 Hermes 工具权限

首版 profile 默认只开放：

- 普通对话；
- 已有 artifact/结果读取；
- 明确 allowlist 的 HQA/平台只读查询；
- 经本设计三 Gate 约束的 proposal-only 研究流程。

generic file write、patch、cron 修改、browser、自由 shell、delegation 和任何 paper/live 操作
均不因网页接通而自动获得授权。命令批准首版只支持 allow once/deny，不支持“永远允许”。

### 5.5 浏览器与本地 BFF 安全边界

首版是 local-only 单用户产品，不等于可以信任任意浏览器网页：

- 平台 backend/BFF 与 Hermes API 均只绑定 loopback；BFF 不开放 wildcard CORS；
- 所有 session、Run、stop、command approval 和 Gate mutation 必须校验 same-origin
  `Origin`/`Sec-Fetch-Site`、本地签名 session cookie 和 CSRF token；
- 浏览器 mutation 只进入 same-origin BFF；平台领域写端要求不下发浏览器的内部服务凭证
  或等价受保护通道，并拒绝从任意网页直接 POST 本机 API 端口。旧前端直连 mutation 必须
  在开放审批前迁移或加同等级 Origin/CSRF 防护；
- session cookie 使用 `HttpOnly`、`SameSite=Strict` 和短期轮换；所有 mutation 必须校验
  当前 session/task/target 所属关系，不能只凭 ID；
- API 响应、日志、错误和浏览器 bundle 不得包含 Hermes bearer、provider secret 或本地
  加密 key；
- remote access 不在本设计范围。一旦需要远程使用，TLS、强认证、逐动作授权和审计必须
  先于任何 chat、stop 或 approval 写端上线。

---

## 6. 统一研究生命周期

```text
自然语言目标
  -> Hermes 结构化研究计划
  -> Gate 1（需要时确认公式/计划摘要）
  -> HQA Task + Hermes Run attempt
  -> 平台确定性研究执行
  -> 统一结果与 provenance
  -> Gate 2（candidate 源码摘要绑定审批）
  -> 一次性研究回测
  -> Gate 3（promotion diff 人工审查 + commit）
  -> 复盘与 Hermes 长期上下文
```

### 6.1 结构化计划卡

计划至少包含：

- 研究目标和因子/策略定义；
- 数据 provider、universe、日期区间、benchmark；
- trial budget、holdout 和 final run 纪律；
- 允许执行的动作与禁止动作；
- 预期 artifact 和成功/降级判定；
- 仍需用户回答的问题。

普通只读查询可以直接执行；公式翻译、候选生成或会影响后续研究解释的计划必须先经过
Gate 1。计划内容变化会产生新 `plan_version` 和 `plan_hash`，旧确认立即失效。

### 6.2 执行过程

UI 显示用户能理解的步骤（读取数据、验证字段、生成 proposal、运行一次性回测、整理
稳定性、发布结果），tool call、stdout/stderr、artifact path 和原始事件折叠在“技术详情”。
进度必须由后端事件驱动，前端不得使用计时器伪造百分比。

### 6.3 结果与继续研究

任务完成后，Hermes 给出解释和建议，但结构化 artifact 决定 `completed`、
`completed_degraded` 或 `failed`。用户可以在同一 session 继续讨论、修改计划、开启新
attempt，或进入正式 Gate；旧手工表单不作为旁路保留。

---

## 7. 数据归属与持久化

### 7.1 各层唯一拥有的事实

| 层 | 真相源 | 唯一拥有的事实 |
|---|---|---|
| Hermes | Session/Run store | 消息上下文、Hermes Run 原始状态/事件、实际 provider/model、command approval。 |
| HQA bridge journal | append-only integration ledger | platform↔Hermes session correlation、已确认 provider policy、request digest/idempotency、Hermes run correlation 和观察游标。 |
| HQA task ledger | append-only research ledger | 研究计划版本、步骤、attempt、Gate refs、result refs、派生任务阶段。 |
| 平台 | 现有 repositories/artifacts/locks/git diff | 因子、回测、实验、日报、candidate 源码、领域 review、promotion diff。 |

bridge journal 只拥有集成关联事实，不拥有对话、研究结果或领域审批。PostgreSQL 和 UI 是
它们的 adapter/projection，不得成为另一套领域真相。

provider 归属必须明确：不可变的**会话请求策略**由 HQA bridge journal 在 Hermes 确认
session 创建后记录；每个 Run 的**实际 provider/model**只以 Hermes Run/event 为准。
HQA Attempt 和 PostgreSQL 只能保存带 `source_run_id/source_event_id/observed_at` 的只读证据
快照，不能反向覆盖 Hermes。

### 7.2 HQA bridge/task 单一写入边界

HQA 提供一个窄的 versioned CLI/模块作为 bridge journal 与 research task ledger 的唯一
mutation implementation。BFF、Hermes skill 和人工 CLI 都必须调用该入口，不得自行 append
文件。入口负责：

- 使用 OS 级跨进程锁串行化 journal 写入；
- 对每个 aggregate 做 `expected_version` CAS；
- 以稳定 `event_id` 去重；
- 原子更新只读 projection；
- 损坏、未知 schema、版本冲突时 fail closed。

BFF 读取任务时调用固定参数的 HQA `list/show/events --json`，或读取由 HQA 原子发布并经
严格 schema 校验的 projection；即使 Hermes 离线，这条只读路径仍然可用。跨仓调用必须
使用配置的绝对 executable path、参数数组和 JSON stdin，不经过 shell 字符串拼接。

最小对象：

```text
BridgeSession
  schema_version, platform_session_id, hermes_session_id,
  parent_session_id, provider_policy, created_at

BridgeRequest
  session_id, client_request_id, canonical_request_digest,
  request_intent_event_id, hermes_run_id, observed_state, observed_at

Task
  schema_version, task_id, session_id, parent_task_id, goal,
  plan_version, plan_hash, derived_state,
  active_attempt, gate_refs[], result_refs[], created_at, updated_at

Attempt
  attempt_id, attempt_number, hermes_run_id, state, step_refs[],
  provider_evidence{source_run_id, source_event_id, actual_provider, actual_model, observed_at},
  started_at, finished_at

Event
  event_id, sequence, aggregate_id, attempt_id, kind, payload, created_at
```

ledger 不复制回测指标、candidate 正文或审批状态；`result_refs` 只保存 repository、kind、
stable ID。projection 损坏时从 journal replay。领域审批先在平台 canonical repository 完成，
再由同一 HQA mutation boundary 记录“observed”事件；若第二步失败，下次 reconcile 从 Gate ref
重新读取平台事实并补写观察，不回滚或伪造领域审批。

### 7.3 平台 PostgreSQL 投影与离线缓存

平台通过 additive、幂等 migration 镜像 HQA bridge/task journal 和 Hermes 可查询历史：

- session correlation、provider policy、request digest/idempotency 和 Hermes run correlation；
- 每个 Run 作用域内的白名单 event cursor/快照；
- task/run 到既有 artifact stable ID 的索引；
- 用于 Hermes 暂时离线时展示的 transcript 缓存。

前 3 类都必须能从 HQA journal/Hermes/平台 artifact 重建；PostgreSQL 丢失不能解除幂等、
重新提交 Run 或改变 Gate。HQA journal 不可写时禁用新提交，而不是让 PostgreSQL 临时成为
权威。

离线 transcript 只缓存 user/assistant 的用户可见文本和白名单状态摘要，排除 raw tool
payload、文件正文、secret、bearer、账户凭证和 broker 数据；默认保留 30 天。完整文本使用
本机 keychain/secret store 提供的 key 做应用层加密，key 不进入数据库或日志；安全 key
不可用时只缓存 session metadata/最近 task/result 摘要，不落完整 transcript。用户清除
session 时同步删除 PostgreSQL 缓存，并将 Hermes canonical 删除作为单独、明确的操作。
所有离线显示必须带 `last_synced_at` 和 `stale`。

### 7.4 Task、Attempt 与 Run 状态

Task（跨多轮、多个 Run 和长时间 Gate）：

```text
draft
 -> awaiting_plan_confirmation
 -> ready
 -> running
 -> reconciling | stop_requested
 -> awaiting_domain_approval
 -> running (new attempt)
 -> completed | completed_degraded | failed | stopped
```

HQA Attempt：

```text
planned
 -> running
 -> reconciling | stop_requested
 -> succeeded | completed_degraded | failed | stopped
```

BFF 归一化的 Hermes Run（单轮、短生命周期；adapter 映射真实 API 状态）：

```text
queued
 -> running <-> awaiting_command_approval
 -> stopping | reconciling(outcome_unknown)
 -> succeeded | failed | stopped
```

Gate 1/2/3 可能等待数小时或数日，因此不能让一个 Hermes Run 跨天悬挂：当前阶段结束后
Run 进入终态，Task 保持 `awaiting_domain_approval`；批准后创建新 attempt。终态 Run 不可
改写，重试永远是新 attempt。

### 7.5 幂等、持久化顺序与关联

- 浏览器每次发送生成 `client_request_id`；BFF 以 `(session_id, client_request_id)` 唯一，
  并绑定 canonical request digest（消息、provider policy、附件引用和目标 task）。相同 ID +
  相同 digest 返回既有状态；相同 ID + 不同 digest 返回 409。
- 同一 session 首版最多一个 active Hermes Run；同一 Task 最多一个 active attempt。
- 平台步骤使用稳定
  `operation_id = hash(task_id, plan_hash, step_id, normalized_inputs)`。
- 调用 Hermes 前，先把 `request_intent + digest` 写入 HQA bridge journal；创建 artifact 的平台
  操作前，先把 `operation_intent + operation_id` 写入 HQA task ledger；外部调用完成后再写
  observed run/result ref。
- 如果外部调用成功但观察事件写失败，状态进入 `reconciling/outcome_unknown`；恢复时先按
  client request correlation、run/operation ID 查询 Hermes 或平台 canonical artifact，再
  补写观察，禁止盲目重发；没有确定性 correlation 能力的创建写端不开放。
- 每个 SSE event 有稳定 `event_id` 与**该 Run 作用域内**单调 cursor；客户端和 BFF 去重。

session fork 记录 `parent_session_id`。只讨论旧结果时沿用只读 result refs；若要用新 provider
继续执行，必须显式“fork task”，创建带 `parent_task_id` 的新 Task 和新 plan version，任何
旧 Gate approval 都不继承。

### 7.6 Stop 与 cancel 语义

一个“停止”动作必须分别报告四层结果：

1. 停止 Hermes 文本/工具 Run；
2. 请求停止当前 HQA Attempt；
3. 对可取消的 platform async job 调用其既有 cancel；
4. 对不可取消或结果未知的操作标记 `stop_requested/reconciling` 并继续对账。

Hermes Run 已停止不代表平台回测已取消，也不代表 Task 已终止。只有所有仍可能产生 artifact
的操作完成对账后，Task 才能进入 `stopped`；已发布的部分 artifact 保留并明确标注限制。

---

## 8. 两套审批与摘要绑定

### 8.1 Hermes command approval

绑定规范化 `command + args + working_dir` 摘要，短 TTL、single-use，只允许本次工具调用。
它不能升级为 Gate 1/2/3，也不能因为用户在聊天里说“同意”而自动创建。

### 8.2 领域 Gate

| Gate | 必须绑定的 revision |
|---|---|
| Gate 1 | 完整 plan/formula canonical payload 的 hash；计划变化立即失效。 |
| Gate 2 | candidate_id、artifact_type、goal、universe、有序相对文件路径、每个文件 exact-bytes SHA-256、metadata digest。 |
| Gate 3 | candidate digest、promotion base commit、promotion manifest 和 scoped-path diff digest；目标路径或 scoped diff 变化即失效，无关 dirty diff 不进入摘要。 |

审批提交时服务端重新读取 canonical target 并做 compare-and-set 校验。过期、已决或 digest
不同统一返回 stale/409，要求刷新和重新审批。

普通聊天文本不能形成 Gate 1/2/3。所有领域 Gate 只能通过专用 same-origin mutation，携带
CSRF、target ID、revision digest 和 expected status，由服务端 CAS 后写入 canonical
repository。Gate 3 的最终完成事实仍是人类审查后的 git commit；网页只能展示/刷新 diff，
不能代为 commit。

### 8.3 Candidate integrity baseline（2026-07-13 已代码交付）

历史 TOCTOU（同 ID 覆写、仅 lock 存在即授权、promotion 再读可变源码）已由
`2026-07-13-candidate-integrity-and-gate3` 修复。**当前实现事实**：

1. Canonical root 统一到 `resolve_candidates_dir(resolve_agent_output_dir())` →
   默认 `data/agent_run/agent/candidates`；仅 `QS_AGENT_OUTPUT_DIR` 可覆盖；
   CWD/`QS_DATA_DIR` 不迁移候选池。
2. `agent migrate-candidates` 默认 dry-run；仅当 manifest digest 一致时合并，冲突
   不覆盖。真实 `--apply` 需单独授权 + `--backup-dir`。本机 dry-run 仍为
   `applied=false`，一个 canonical-unversioned pending 项待加 v1 manifest。
3. candidate 目录独占创建；相同 ID + 相同 digest 幂等返回；相同 ID + 不同 digest
   冲突且零写入；发布后 metadata/artifacts 不可覆写。
4. `approved.lock` 绑定 candidate ID + manifest digest；review 为
   expected-digest + `expected_status=pending` CAS。
5. 一次性研究加载、回测和 Gate 3 prepare 都在最后责任点再校验 digest。
6. 旧无摘要批准为 `legacy_unbound`，永不授权执行/晋级，必须重新审批。

manifest 构建拒绝路径穿越、symlink、非普通文件和目录外引用；dirfd/no-follow/
no-replace 发布。读状态互斥：`verified` / `migration_required` / `corrupt`。

Gate 3 公共 CLI 需要 `--candidate-id`、`--expected-digest`、`--base-commit`，在
隔离 managed review worktree 生成四字段
`{promotion_id, worktree, patch, manifest}` scoped patch；status/cleanup 只认
`--promotion-id`；abandon 仅显式；系统永不自动 commit。主工作树无关 dirty 不碰。

**仍未开放（D-31 后续）**：新 Hermes 工作台审批/执行 UI、真实 migration apply、
chat/bridge mutation。在 professional frontend/bridge gates 完成前，不得把新
`/hermes` 审批面接到这些写路径。

---

## 9. 故障与降级合同

| 故障 | 用户体验与系统行为 |
|---|---|
| Hermes 离线 | 今日概览、平台结果、HQA Task 和带 last-synced 标记的 transcript 缓存可读；新消息、新研究、command approval 禁用；不回退旧 AgentRunner。 |
| SSE 断开 | 显示“重连/对账中”和最后事件时间；服务端 Run 默认继续；先取 Run snapshot，再从 cursor 补事件。断线不等于 failed/stopped。 |
| BFF/Hermes 调用超时 | 标记 `outcome_unknown`，按 idempotency/correlation key 确定性查询；确认不存在后才允许新 attempt。没有 Hermes ID 且 API 又不支持 request correlation 时保持 fail closed，不能猜测。 |
| Provider quota/unavailable | 展示 requested/actual provider、失败原因和已发生的显式 fallback；无预授权 fallback 时失败并提供“用另一 provider 分叉 session”。 |
| Stop/cancel 部分成功 | 分别展示 Hermes Run、HQA Attempt、platform async job 和对账状态；任何仍运行或未知的层都不能显示“任务已停止”。 |
| 部分 artifact | 有合法 artifact + limitations 才能 `completed_degraded`；没有可验证 artifact 就是 failed，聊天总结不能补成成功。 |
| 审批过期/目标变化 | 重新读取 canonical target 并比较 digest；返回 stale，禁止沿用旧批准。 |
| HQA journal/ledger 不可写或损坏 | 新 session/Run、artifact 和审批全部 fail closed；只读 projection/artifact 浏览继续；损坏 journal 不自动截断或猜测修复。 |
| PostgreSQL 投影不可用 | 既有领域 artifact 与 HQA projection 继续读取；若 HQA journal 和 Hermes 正常，普通提交仍可安全进行，但离线 transcript/搜索标记为不可用且不静默丢缓存。 |
| Origin/CSRF/session 校验失败 | 所有 mutation 返回拒绝且不触碰 Hermes/HQA/平台；只记录不含 secret/request body 的安全审计摘要。 |

任何失败都不能被折叠成 `approved` 或 `completed`。

---

## 10. 专业前端交付门槛

### F0：视觉发现与高保真方向

- 审计现有真实页面、截图、token、字体/图标、数据长度和常用视口；
- 在已批准信息架构内给 2-3 个真正有差异的高保真方向；
- 每个方向覆盖空闲首页、活跃 session、统一结果和审批态；
- 同时展示 1440、1280、768、390 宽度；不裁切、不横向溢出；
- 用户书面确认视觉方向后才进入生产组件。

### F1：可点击全状态原型

贯通“提出目标 → 计划 → Gate 1 → 流式执行 → 结果 → Gate 2/3”，并建立可切换的
状态目录：

- 首页：empty/loading/normal/degraded/Hermes offline；
- 对话：sending/queued/streaming/reconnecting/stopping/reconciling/failed/quota/fallback；
- 任务：queued/running/waiting_gate/stop_requested/reconciling/completed/partial/failed/stopped；
- 审批：available/approved/rejected/expired/stale/digest mismatch；
- 结果：loading/partial/no data/audit warning/source missing。

### F2-F5：生产壳、真实接入、结果审批、旧页退场

- F2：语义 token、响应式壳、Hermes 内导航、composer、结果画布和折叠技术详情；
- F3：接 fake Hermes/BFF 状态，再做受控本地真实 smoke；前端不得伪造进度；
- F4：实现 Gate 1/2/3、统一结果和旧页证据 parity；
- F5：导航、深链、E2E parity 完成后才移除旧入口和组件。

横向门槛：语义 HTML、完整键盘路径、可见 focus、WCAG AA、触控目标至少 44px、
`prefers-reduced-motion`、状态不只靠颜色、console 0 error/warning、流式消息不滚动劫持。
视觉回归固定覆盖 1440×900、1280×800、768×1024、390×844，并使用中英文长文本、
长 run ID 和长错误消息。snapshot 差异必须人工确认，不能盲目更新。

专业前端 Agent 负责设计与实现；另一名前端/UX reviewer 在 F1、F3、F5 独立复审。

---

## 11. 候选交付阶段与迁移顺序

以下 0-7 只是设计层的依赖顺序和验收 Gate，**不是已选定的 implementation slices**；
逐文件步骤、提交边界和最终 slice 名称由后续 `writing-plans` 产生。

### 候选阶段 0：专业视觉定稿

完成 F0/F1，不修改生产能力；用户批准真实尺寸、真实内容、全状态原型。

### 候选阶段 1：安全与合同基线

修 candidate root/manifest digest/legacy approval/TOCTOU；探测并冻结已安装 Hermes API
capability 合同，包括 session/Run 创建的 client idempotency/correlation 恢复能力；核验历史
experiment stable ID，缺失时先定义 additive durable ID/backfill；建立 fake Hermes
fixtures。此项可与视觉工作并行，但必须先于审批和执行。

### 候选阶段 2：只读 Hermes 新外壳

实现 F2 和新的 Hermes 路由，先消费现有 9H feed 与 fixtures；覆盖完整 loading/error/offline
状态。通过视觉与可访问性验收后，`/` 默认进入 `/hermes`，但执行 feature flag 仍关闭。

### 候选阶段 3：真实 Hermes 普通对话

接 dedicated profile/API、BFF、HQA bridge journal、session/provider、Run/SSE/stop、幂等和
离线缓存；完成 loopback、Origin/CSRF、本地 session 和 secret-leak 测试。只开放普通对话与
安全只读能力，不开放研究 artifact 写端，不 fallback 到 `/api/agent/tasks`。

### 候选阶段 4：HQA Task 与统一只读结果

交付 research task ledger 和 bridge projection；迁移历史 factor/backtest/experiment 的读取、
深链、图表和审计证据。同步 `dashboardRuns`、factor handoff、experiment “Send to Backtest”
等消费者。此阶段仍不启动新研究。

### 候选阶段 5：受控研究与三 Gate

按 factor → experiment → backtest 顺序逐条交付 tracer bullet。实现计划卡、Gate 1、确定性
执行、统一结果、Gate 2 摘要绑定、一次性研究回测与 Gate 3 diff review。

### 候选阶段 6：逐页切流

按 `agent-studio → factor-lab → experiments → backtest` 顺序，每页独立 feature flag 和
临时 redirect；backtest 最后迁移，因为它仍被 dashboard、experiment handoff、factor
handoff、async job/cancel 和详情深链消费。

### 候选阶段 7：硬化与物理删除

至少两轮独立冷启动 smoke，覆盖 Hermes 断线恢复、平台/HQA 重启和历史 artifact 深链；
再删除旧 page/form，将旧 E2E 改写为新路由 parity 断言。API、CLI、领域引擎、artifact、
async status/cancel 和安全 Gate 继续保留。

独立开关至少分为 `shell / chat / execution / unified-results / legacy-redirects`。任何失败只
关闭新能力和切流，不回滚 append-only 数据或删除领域产物。

---

## 12. 测试与验收

### 12.1 自动测试（完全 hermetic）

- fake Hermes Server 覆盖 session、Run、SSE、approval、stop、quota、fallback、超时；
- BFF contract 测试覆盖 loopback bind、跨源拒绝、CSRF、伪造/过期 session、bearer 隔离、
  provider lock、request-digest 幂等、per-Run event cursor 和错误映射；
- HQA 测试覆盖 bridge/task CLI 单一写边界、跨进程锁、CAS、ledger atomic write、replay、
  损坏拒绝、attempt、operation intent/result 对账和 idempotency；
- 平台测试覆盖 candidate root、manifest digest、`legacy_unbound`、stale/409 和 promotion
  TOCTOU，并覆盖 symlink、路径穿越、非普通文件、canonical 排序、审批/生成并发和
  promotion 期间 scoped working-tree 变化、目标冲突和无关 dirty 隔离；
- 前端状态目录、component test、Playwright 全生命周期、固定视口视觉回归；
- 离线、断线、partial、DB 故障、provider capability 缺失、四层 stop/cancel、长文本、
  locale 和旧深链 redirect；
- 跨仓测试验证没有 strategy signal、paper account mutation、broker 或 live 路径副作用。

CI/常规测试不得调用真实 Grok/Codex、不得外网、不得触发回测以外的 paper/live 执行。
研究测试默认使用 sample/fixture；真实 provider smoke 只能人工显式启动。

### 12.2 本地真实验收

在用户明确授权后：

1. 启动 ai-quant-platform backend/frontend、Docker PostgreSQL、Hermes API/gateway；
2. Grok 与 Codex 各做一条低成本普通对话，核对实际 provider/model 和 usage；
3. 验证 stop、页面刷新、SSE 重连和 Hermes 重启恢复；
   stop 验收必须分别确认 Hermes Run、HQA Attempt 和 platform async job，不得只看聊天停止；
4. 用 sample/read-only 数据完成一条 proposal-only 研究链路；
5. 在独立临时 git worktree 演练 Gate 1/2/3，修改 candidate、污染 scoped path 或制造目标
   冲突后必须 stale/fail closed；用户主工作树指纹保持不变；
6. 核对 `paper_trading`、`live_trading_enabled=false`、kill switch 和人工 Gate 指纹未变化；
7. 验证所有旧动态 URL、locale、书签和浏览器前进后退；
8. 运行两仓和前端/数据库约定的完整测试门。

真实 smoke 可能消耗所选 provider 的订阅额度，必须在执行前明示；不会同时消耗未实际
使用的 provider。

### 12.3 完成门槛

- 网页对话真实经过本地 Hermes，provider/run 状态可证实；
- `/hermes` 是默认首页且五秒信息目标成立；
- 一个研究任务能跨 Run/Gate 恢复，刷新和断线不重复执行；`outcome_unknown` 在对账前
  不能重试；
- Gate 1/2/3 与 command approval 不能互相替代；
- 因子/回测/实验结果达到旧页关键证据 parity；
- 旧四页入口按序退场，动态深链兼容，后端能力未删除；
- Hermes/DB/provider 故障均诚实降级，不出现假完成或假批准；
- 专业前端与独立 reviewer 的视觉、响应式、可用性和无障碍 Gate 全部通过；
- 文档、迁移、启动方式、当前状态与实际 git/test/runtime 证据同步。

---

## 13. 明确不做

- 不把浏览器 localStorage 当任务数据库；
- 不把聊天 transcript 当研究 artifact、任务状态或审批记录；
- 不让网页直接持有 Hermes/provider secret；
- 不把旧 `/api/agent/tasks` 包装成“真实 Hermes”；
- 不在 provider quota 后静默切换未授权 provider；
- 不把 SSE 断线判成 Run 失败；
- 不让一个 Hermes Run 跨数日等待领域 Gate；
- 不保留旧手工研究表单作为绕过三 Gate 的旁路；
- 不因 UI 合并删除平台领域引擎、CLI、API、artifact 或安全链；
- 不在本阶段接入 paper/live 自动执行，也不改变 Phase 2/3 的授权边界。

---

## 14. 下一步

The first implementation wave is split into three independently testable plans:
gateway capability contract, candidate integrity/Gate 3, and professional
frontend/read-only shell. The bridge/chat plan is admitted only when
verify-chat returns ready against a Git-reviewed default contract and current
installed Hermes evidence.

1. 第一批正式计划已经拆为 Hermes gateway capability contract、candidate
   integrity/Gate 3、professional frontend/read-only shell 三个独立子系统（已选
   wave；真实 Hermes chat mutation 不在本波次）；
2. 用户选择执行方式后，优先并行执行 capability/candidate 基线与专业前端 F0；
3. F0、F1 都必须单独取得用户书面确认，candidate 真实数据 migration 也必须另行授权；
4. 只有 capability evaluator 针对 Git 绑定、独立审查为 `ready` 的默认合同和当时干净安装态
   Hermes 返回 chat ready（`hqa.hermes_capability_cli verify-chat` exit 0，
   `review.verdict=ready` 且 `installation.matches_snapshot=true`），才能根据真实合同
   另写 bridge/chat plan；不得提前实现，也不得把旧 `/api/agent/tasks` 或 AgentRunner
   当作 fallback；
5. 后续 HQA Task/统一结果、受控研究/三 Gate、逐页切流、硬化删除仍按各自前置证据
   just-in-time 写独立 implementation plan。

当前状态是“D-31 已批准；gateway capability 合同已冻结且 chat 写端 fail-closed；
candidate integrity/Gate 3 已代码交付；professional frontend F2 只读壳与可回滚默认
首页已代码交付”，不是任何新 chat/execution 生产能力已交付。能力提示仍是静态
`blocked_in_this_slice`。指纹与缺失语义以 `docs/contracts/hermes-gateway-0.18.2.md`
与 `config/hermes-gateway-capabilities.v1.json` 为准。
