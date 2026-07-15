# D-31 Wave 3 — Official API BFF、持久任务桥、统一 Results 与旧页退场

> **状态（2026-07-15）：PARTIAL。** Slice 3A「official API session-read BFF」已交付；3B
> durable ledger/outbox 已完成数据库实装，3C deterministic worker 框架也已完成本机
> reconcile-only 验收。平台提交 `efb10d5`、`9bc940f` 已推送。3D 仍被九项 live gateway
> blocker 阻断；`chat_write`、Hermes approval mutation、unified Results 和 legacy redirects
> 继续关闭。下一项可独立、安全推进的是只读 3E，而不是打开 composer。

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

### 2026-07-15 command authority / transport amendment

- PostgreSQL 是 transport command、`client_request_id` 幂等、command event/outbox、delivery
  lease 和 exact Run link 的**唯一权威**。HQA connector 只消费这份队列，不另写一份
  BridgeRequest command journal，也不把内存状态当恢复依据。
- Hermes Session、Run、messages 和未来 actual provider evidence 仍只归 Hermes；HQA task
  ledger 只拥有 research plan、Attempt、Gate 和 result refs。三个真相源不得互相冒充。
- 当前唯一正式 Hermes 网络协议是 official API Server 的 loopback HTTP
  `http://127.0.0.1:8642`。旧 `9119` TUI gateway 和运行时动态 Dashboard WebSocket 只保留为
  历史/诊断面，不能用作 connector transport、写端准入证据或固定服务发现地址。
- HQA worker 的安装入口固定为
  `~/.hermes/scripts/hqa-hermes-command-worker.sh`，内部只执行平台叶子命令
  `ai-quant/bin/quant-system hermes connector-worker`。wrapper 不读取 prompt、provider、Bearer
  或 secret；未知参数和非数值 lifecycle 参数 fail closed，且错误消息不回显输入。

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

## Slice 3B — Durable command / outbox / event ledger（DONE）

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

### 2026-07-15 交付与运行证据

- 平台实现已由提交 `efb10d5`、`9bc940f` 推送到远端开发分支。
- 对 live `quantplatform` 应用前先生成
  `data/_runtime/db_backups/quantplatform-pre-wave3-20260715T182203+0800.dump`；SHA-256 为
  `3bbf5f3be83e6aeb348c83986e42cfed49e844e467b51305abf87a39d3733a3b`。
- migration `005_hermes_command_ledger.sql` 已对 live 数据库成功 apply，并重复 apply 验证
  幂等；当前 schema version `1`，五张 ledger 表和四个 append-only trigger 均通过结构核验。
- 平台 `/api/health` 报告
  `database_configured=true, schema_ready=true, schema_version=1, mutation_enabled=false`。
- 验收后 `hermes_commands`、`hermes_command_events`、`hermes_outbox`、`hermes_run_links`
  均为零行；本轮没有向 Hermes 提交 mutation，也没有调用任何 provider。
- 44 个平台目标测试通过；HQA full suite 通过。这里的测试/运行证据证明 ledger 底座可用，
  **不授权** chat、approval、stop 或任何交易写路径。

## Slice 3C — Deterministic connector worker（框架 DONE；reconcile-only）

### Worker 机制

- 优先用 PostgreSQL `LISTEN/NOTIFY` 唤醒；同时保留低频 periodic scan，解决通知不是持久队列、
  worker 重启或通知丢失的问题。
- 多 worker 使用短事务 `FOR UPDATE SKIP LOCKED` claim，写入 lease/heartbeat；网络调用在事务外。
- 指数退避 + jitter；明确区分可重试、永久失败与 `outcome_unknown`。
- lease 到期只允许重新进入 reconcile；不能在 upstream 是否已执行不明时盲目重提。
- worker 是纯确定性程序，不调用 LLM 来决定“取哪个任务、是否重试、状态是什么”。

### HQA wrapper / CLI 合同

HQA 只提供一个物理安装 wrapper；业务状态与状态机实现仍位于平台 PostgreSQL/repository：

```bash
# 单个 reconcile-only cycle；stdout 为 JSON Lines
~/.hermes/scripts/hqa-hermes-command-worker.sh --once

# 确定性循环；LISTEN/NOTIFY 唤醒并有 periodic scan 兜底
~/.hermes/scripts/hqa-hermes-command-worker.sh \
  --poll-interval-seconds 30.0 \
  --max-cycles 10 \
  --reconcile-limit 100
```

允许参数只有 `--once`、`--poll-interval-seconds`、`--max-cycles`、`--reconcile-limit` 和
`--help`；wrapper 始终固定到 `quant-system hermes connector-worker`，不能借透传切换到其他
平台命令。默认无 `--once` 时是循环；`--once` 与 `--max-cycles` 互斥，由平台 CLI 继续做语义
校验。当前 slice 不暴露 prompt/provider/secret/capability-probe 参数，也不调用 Hermes
chat/run/approval/stop endpoint。

### 2026-07-15 交付与运行证据

- 安装后的 `~/.hermes/scripts/hqa-hermes-command-worker.sh --once` 已在 live 环境成功完成
  一个 reconcile-only cycle。
- `LISTEN/NOTIFY` 唤醒加 periodic-scan 兜底已完成 live 两周期验收；空队列保持零 command、
  event、outbox、run-link 行。
- worker 统计与数据库事实共同确认 `hermes_mutation_count=0`；没有 prompt、Hermes Run、
  approval/stop mutation 或 provider 消耗。
- 因而 3C 的准确状态是“确定性 claim/lease/reconcile 框架已交付”，不是“真实 Hermes 写端
  已接通”。在下列准入门满足前，worker 必须继续 reconcile-only。

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

2026-07-15 live `GET /api/hermes/gateway` 仍返回 `chat_write_ready=false`，九项 blocker 为：

1. `run_submission_not_idempotent`
2. `request_recovery_unavailable`
3. `event_id_unavailable`
4. `event_replay_unavailable`
5. `run_status_not_persistent`
6. `provider_policy_not_immutable`
7. `actual_provider_evidence_unavailable`
8. `approval_exact_binding_unavailable`
9. `stop_reconciliation_unavailable`

3B/3C 只解决平台侧耐久意图与确定性 worker 底座，不能伪造这些 upstream 语义；因此 3D
保持 **BLOCKED**，不能用轮询、内存 ID 或重试 prompt 绕过。

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

### 2026-07-15 parity 审计结论

3E 可在不等待 chat 写端的前提下，以纯只读切片推进：

- 当前 `/hermes/results` 只是 9H/HQA artifact 展示面；通用 recent-runs 又只覆盖
  backtest/factor/paper/replication，不能给其中任一现有 API 换名后冒充统一结果中心。
- 新索引必须按引用聚合各自权威源：run repository、独立 experiment 目录、repo-anchored
  CandidatePool 和 HQA ArtifactCatalog；只保存跨系统 ID、状态、freshness、provenance 与深链，
  不复制领域详情。
- 最小详情覆盖 factor run、backtest、experiment、candidate 和六类 HQA artifact，并为
  missing/corrupt/degraded/empty/upstream-unavailable 提供显式状态。
- 在 3E 真实数据 E2E 与用户验收完成前，`unifiedResults=false`，旧页继续提供原能力。

## Slice 3F — Legacy page retirement

采用 expand → parity → cutover → contract：

1. 保留 Factor Lab / Backtester / Experiments / Agent Studio，记录使用与 parity 缺口。
2. Hermes 等价入口通过功能、可访问性、响应式与真实数据 E2E；用户书面确认。
3. 先从导航移除并加可回滚 redirect；保留后端 API/CLI 与深链兼容观察期。
4. 观察期无回退后才删除旧页面组件；绝不删除因子/回测/实验领域引擎。

在 3E 验收前，`legacyRedirects=false`；soft banner 不能冒充旧页已退场。

本次 parity 审计把 3F 拆成页面级 Gate：

- **Agent Studio** 已是只读过渡页；Hermes Approvals 补齐任意 candidate 的 source preview、
  audit/reviews、digest/integrity/binding 和 promoted registry 上下文后，可独立移除导航并可逆
  redirect 到 `/hermes/approvals`。
- **Factor Lab、Backtester、Experiments** 仍分别承载因子执行、回测执行和实验 sweep 等真实
  写任务。chat 写端关闭且没有另一获批结构化执行入口时，这三页不可退休；3E 只能先接管其
  历史查看与详情入口。
- 因此不得用一个全局 redirect 同时切掉四页；每页都需独立 parity、E2E、用户确认和回滚开关。

## 验证矩阵

每个 slice 至少覆盖：

- hermetic unit/contract tests；无外网、无 provider、无交易；
- API/OpenAPI/generated client 与前端 type/lint/build；
- loopback 真实 Hermes read smoke；写端未准入时必须断言 composer/POST 不存在或被拒绝；
- PostgreSQL migration、并发 claim、进程崩溃、lease 过期、通知丢失、网络 timeout 和重启恢复；
- 浏览器真实用户路径，包括空/错/部分/离线状态；
- 独立 code review、安全 review、workflow review 和 reality check。

3C wrapper 的 hermetic 复核（不连接数据库、Hermes 或 provider）：

```bash
./.venv/bin/pytest -q \
  tests/test_hermes_command_worker_wrapper.py \
  tests/test_install.py
```

## 当前完成度

| Slice | 状态 |
|---|---|
| 3A official API session-read BFF | **DONE（代码 + 本机只读验收）** |
| 3B durable ledger/outbox | **DONE（migration 005 + live DB 验收）** |
| 3C connector worker | **FRAMEWORK DONE / reconcile-only；Hermes mutation BLOCKED** |
| 3D chat/stream/resume | **BLOCKED（live gateway 九项）** |
| 3E unified Results | **PLANNED；可作为下一只读切片独立推进** |
| 3F legacy retirement | **PARTIAL GATE：Agent Studio 可先行；另三页 BLOCKED on write parity + user approval** |

因此当前产品阶段应表述为：**D-31 已有真实 Hermes 会话只读连接和平台 durable
ledger/reconcile worker 底座，但完整 Hermes 对话工作台仍未接通；下一安全开发切片是只读
3E unified Results。3D composer 仍被九项 live blocker 明确阻断。**
