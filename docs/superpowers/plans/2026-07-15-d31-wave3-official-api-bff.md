# D-31 Wave 3 — Official API BFF、持久任务桥、统一 Results 与旧页退场

> **状态（2026-07-15）：PARTIAL。** Slice 3A「official API session-read BFF」已代码交付并
> 完成本机只读连通性验收；3B 之后仍是待执行计划。`chat_write`、Hermes approval mutation、
> unified Results 和 legacy redirects 继续关闭。是否已提交/推送必须以两仓 `git` 事实为准。

## 目标

用成熟、可恢复、不会让 LLM 空转的方式连接平台与本机 Hermes：浏览器只访问平台同源
BFF；PostgreSQL 保存平台拥有的命令/关联/事件投影；HQA 的确定性 connector worker 负责
跨系统交付与对账；Hermes official API Server 是会话/Run 的 upstream。先完成只读会话，
再搭耐久任务底座，最后才考虑真正 chat 写端、统一 Results 和旧四页退场。

## 当前架构与目标架构

```text
Browser
  -> ai-quant-platform same-origin BFF
      -> read: Hermes official API 127.0.0.1:8642
      -> future write intent: PostgreSQL command + outbox + event ledger
          -> HQA deterministic connector worker
              -> Hermes official API HTTP/SSE
```

关键点：**轮询的是确定性数据库队列/状态，不是让 Hermes 或 LLM 定时问“有没有任务”。**
空队列只做一次廉价 SQL/通知等待，不创建 Run、不提交 prompt、不消耗 provider 额度。

## 已冻结边界

- official API read-only 合同：
  [`../../contracts/hermes-api-server-0.18.2.md`](../../contracts/hermes-api-server-0.18.2.md)。
- 旧 TUI WebSocket 合同已经漂移，只保留历史审计；不得用于当前准入。
- 浏览器永远拿不到 Hermes bearer key、provider secret 或 HQA runtime token。
- 平台只绑定 loopback；远程访问必须先落 TLS、登录、授权、CSRF 和审计。
- `POST /api/agent/tasks` 不是 Hermes fallback。
- Gate 1/2/3、Hermes command approval 与未来 chat confirmation 是不同审批域，不能复用
  一个“批准”按钮互相授权。
- 候选 Gate 2 禁止浏览器 refetch digest/status 再代替人类提交；此前出现过的 mutation UI
  已因违反 Gate 1 binding/no-refetch 约束回退为只读证据面。
- `paper_trading=true`、`live_trading_enabled=false`、kill switch 和三道人类门继续有效。

## Slice 3A — Official API session-read BFF（已交付）

### 交付

- 平台服务端以固定 GET allowlist 访问 `127.0.0.1:8642`；Bearer key 只从 owner-only
  server-side file 读取，禁用环境代理继承与 redirect。
- 平台 server-side GET-only BFF 提供 gateway、session list、session detail、session messages
  四个只读资源；当前开发态 3001/8765 不能冒充已经具备同源认证，future mutation 仍必须
  落到 authenticated same-origin + CSRF 边界。
- `/hermes/sessions` 展示真实已持久化会话；详情页只展示有限的 user/assistant 文本，
  composer 继续禁用。
- session ID、upstream payload、响应大小/时间/条数、epoch 时间和错误 envelope 均做
  fail-closed 验证；upstream 不可用不会退回旧 agent task 或写路径。
- approvals 恢复为只读证据面；没有浏览器 Gate 2 mutation。

### 验收边界

- GET 读取不触发 Hermes LLM/provider；本 slice 没有新增 PostgreSQL migration/table。
- `session_read=true` 不意味着 `chat_write=true`。
- upstream 的 `run_submission=true` 是诊断事实，不是 D-31 写端准入。

## Slice 3B — Durable command / outbox / event ledger（下一实现切片）

这一 slice 只建立平台拥有的耐久事实，不向 Hermes 提交 prompt。

### 建议最小表

1. `hermes_commands`
   - `command_id`（平台生成、不可变）
   - `client_request_id`（用户操作幂等键，唯一）
   - `kind`、`payload_digest`、加密或最小化后的 payload reference
   - `state=queued|leased|delivered|outcome_unknown|succeeded|failed|cancelled`
   - `attempt_count`、`next_attempt_at`、`lease_owner`、`lease_until`
   - `hermes_session_id`、`hermes_run_id`（只有取得权威值后才写）
   - `created_at`、`updated_at`、`last_error_code`
2. `hermes_command_events`
   - 单调 `event_id`、`command_id`、`event_type`、`payload_digest`、`occurred_at`
   - append-only；状态投影可由事件重建。
3. `hermes_outbox`
   - 与命令创建同一事务写入；负责唤醒 connector，不把网络调用塞进 HTTP request 事务。
4. `hermes_run_links`
   - 精确绑定 platform task/candidate/experiment/result IDs 与 Hermes session/run；禁止按 ticker
     或标题相似度猜关联。

### 行为合同

- BFF mutation 必须 same-origin + authenticated session + CSRF；请求携带
  `client_request_id`，相同 ID/相同 digest 返回既有 command，相同 ID/不同 digest 冲突。
- 表先通过正式 migration 落地；启动自动迁移、downgrade/backup 和并发唯一性必须有测试。
- 创建命令只代表“平台已持久化意图”，不代表 Hermes 已收到，更不代表 Run 成功。
- payload 中不落 provider secret；敏感 prompt 如需离线保存，先定义字段最小化、加密、保留期
  和删除策略。

### 验收

- 两个并发相同 request 只产生一个 command；进程在事务后、网络前崩溃不丢意图。
- 没有任何 Hermes/provider 调用；只验证 ledger、outbox、状态机和权限。
- migration 在空库、既有库和回滚演练均可重复验证。

## Slice 3C — Deterministic connector worker（先交付框架，写端仍受 Gate）

### Worker 机制

- 优先用 PostgreSQL `LISTEN/NOTIFY` 唤醒；同时保留低频 periodic scan，解决通知不是持久队列、
  worker 重启或通知丢失的问题。
- 多 worker 使用短事务 `FOR UPDATE SKIP LOCKED` claim，写入 lease/heartbeat；网络调用在事务外。
- 指数退避 + jitter；明确区分可重试、永久失败与 `outcome_unknown`。
- lease 到期只允许重新进入 reconcile；不能在 upstream 是否已执行不明时盲目重提。
- worker 是纯确定性程序，不调用 LLM 来决定“取哪个任务、是否重试、状态是什么”。

### Hermes 写端准入门

在下列能力有可审计证据前，worker 只能执行 health/session GET 和本地 ledger reconcile：

- request idempotency + lookup/recovery；
- immutable Run ID；
- durable event ID/cursor/replay；
- provider policy lock 与 actual provider/fallback/usage evidence；
- Run-scoped idempotent stop；
- approval identity/digest/TTL/single-use/CAS。

如果 upstream 尚未提供这些语义，可以另写 adapter 设计，但不能仅靠“本地记了一个 ID”掩盖
网络超时后的重复执行风险。任何超时先落 `outcome_unknown`，由 recovery 证据处理。

### Provider 语义

- worker 的 claim、heartbeat、poll/reconcile 与 session GET 不消耗 provider。
- 真正被准入的 prompt/run 才会消耗 Hermes 当前配置的 Codex/Grok 等 provider；Run 必须记录
  requested 与 actual provider/model、fallback from/to/reason 和 usage，不能只显示全局配置。

## Slice 3D — Chat composer / stream / resume（条件式，当前 BLOCKED）

仅在 3B/3C 与写端准入门通过、独立安全 review CLEAR、用户再次批准后实施：

- composer 先支持“研究对话”，不支持交易、paper mutation、Gate 2/3 或任意 shell。
- 提交立即返回平台 `command_id`；页面状态来自 ledger，不把一次 HTTP 长连接当真相。
- SSE 可用于低延迟显示，但每个 event 必须可按 cursor 从 durable store 补播；断线重连不丢、
  不重复展示。
- stop 是 Run-scoped request，必须可重试、可对账；UI 不把按钮点击当已停止。
- 页面明确展示 session、Run、provider、fallback、usage 和 outcome provenance。

## Slice 3E — Unified Results

在不删除领域 API/CLI/artifact 的前提下，建立一个统一结果索引和详情抽屉：

- 统一索引只保存跨系统 ID/摘要/状态，领域详情仍回源 platform authoritative endpoint 或
  immutable artifact。
- 覆盖 factor candidate、backtest、experiment、weekly review、risk、prediction、opportunity、
  automation 与 Hermes research run；每一项带明确来源、生成时间、freshness 和深链接。
- Hermes session/run 与 result 只按 `hermes_run_links` 的精确 ID 关联，绝不按标题/标的猜测。
- 错误、空状态、部分数据、过期、无权限和 upstream unavailable 都有显式状态。

验收必须先形成四个旧页面的 parity matrix，并让用户能从 Hermes 完成其仍有价值的只读查看、
筛选、追溯与跳转任务。

## Slice 3F — Legacy page retirement

采用 expand → parity → cutover → contract：

1. 保留 Factor Lab / Backtester / Experiments / Agent Studio，记录使用与 parity 缺口。
2. Hermes 等价入口通过功能、可访问性、响应式与真实数据 E2E；用户书面确认。
3. 先从导航移除并加可回滚 redirect；保留后端 API/CLI 与深链兼容观察期。
4. 观察期无回退后才删除旧页面组件；绝不删除因子/回测/实验领域引擎。

在 3E 验收前，`legacyRedirects=false`；soft banner 不能冒充旧页已退场。

## 验证矩阵

每个 slice 至少覆盖：

- hermetic unit/contract tests；无外网、无 provider、无交易；
- API/OpenAPI/generated client 与前端 type/lint/build；
- loopback 真实 Hermes read smoke；写端未准入时必须断言 composer/POST 不存在或被拒绝；
- PostgreSQL migration、并发 claim、进程崩溃、lease 过期、通知丢失、网络 timeout 和重启恢复；
- 浏览器真实用户路径，包括空/错/部分/离线状态；
- 独立 code review、安全 review、workflow review 和 reality check。

## 当前完成度

| Slice | 状态 |
|---|---|
| 3A official API session-read BFF | **DONE（代码 + 本机只读验收）** |
| 3B durable ledger/outbox | **PLANNED** |
| 3C connector worker | **PLANNED；Hermes mutation BLOCKED** |
| 3D chat/stream/resume | **BLOCKED** |
| 3E unified Results | **PLANNED** |
| 3F legacy retirement | **BLOCKED on parity + user approval** |

因此当前产品阶段应表述为：**D-31 已有真实 Hermes 会话只读连接，完整 Hermes 对话工作台仍未
接通；下一开发切片是 3B durable ledger/outbox，不是直接打开 composer。**
