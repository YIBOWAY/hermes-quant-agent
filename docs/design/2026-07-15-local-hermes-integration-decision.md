# 本机平台连接本机 Hermes：集成方案调研与架构决定

> 状态：**ACCEPTED（2026-07-15）**。本文记录外部调研后的长期集成决定；具体交付状态仍以
> [`../README.md`](../README.md) 为入口，当前施工顺序以
> [`../superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md`](../superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md)
> 为准。Wave 3 plan 只保留为前序交付记录。

## 结论

`ai-quant-platform` 与本机 Hermes 的正式写链路采用：

```text
Browser
  -> platform same-origin BFF
  -> PostgreSQL command / event / outbox / exact run-link ledger
  -> deterministic HQA connector worker
  -> Hermes official loopback API
```

Worker 优先由 PostgreSQL `LISTEN/NOTIFY` 唤醒，并保留低频、有限的 periodic scan 作为通知
丢失和进程重启后的恢复兜底。**不让 Hermes agent 或 LLM cron 周期性询问“有没有任务”**；
空队列不创建 Hermes Run，也不消耗 Codex、Grok 或其他 provider 额度。

这不是某个现成开源插件的一键接入，而是由数据库 outbox、幂等命令、租约 worker 和
official API 组成的成熟工程模式。当前项目的 Wave 3B/3C 已经按这条路线交付了耐久底座；
chat 写端仍需补齐 upstream recovery、event replay、provider evidence 等语义，不能因为
“已经可以发 HTTP”就提前开启。

## 先回答“一般聊天有没有成熟现成方案”

有，但要把“能聊天”与“可作为量化研究业务链路”分开：

1. **Hermes 自带 Dashboard：最省事。** 适合直接查看和操作本机 Hermes，本项目不需要再造
   transport；但它不是平台的任务、结果和审批账本。
2. **Hermes official OpenAI-compatible API + Open WebUI/LobeChat：成熟的通用聊天 UI。**
   Hermes 官方 API Server 暴露 `/v1/chat/completions`、`/v1/responses` 等兼容入口；Open
   WebUI 也有 Hermes Agent 的官方接入说明。若目标只是“网页里跟本机 Hermes 聊天”，这是
   最快的现成路径。
3. **平台 BFF + outbox worker：本项目正式路径。** 用户的目标还包括研究计划、审批、回测、
   exact result link、恢复和 provider 证据；通用聊天 UI 不拥有这些领域事实，所以只能作为
   UX 参考，不能取代平台账本。

社区项目如 [`lotsoftick/hermes_client`](https://github.com/lotsoftick/hermes_client)、
[`nesquena/hermes-webui`](https://github.com/nesquena/hermes-webui) 和
[`EKKOLearnAI/hermes-web-ui`](https://github.com/EKKOLearnAI/hermes-web-ui) 也证明直接 Web
client 是可行的。前者当前以启动本机 `hermes chat`、SSE 转发 stdout 的 CLI wrapper 为主；
这种方式对个人聊天很直接，但 subprocess、session 恢复与平台业务账本仍由 wrapper 自己负责。
这些项目适合试用或参考交互；是否支持当前 Hermes 版本、鉴权、幂等、恢复和工具审批，仍需
逐项验证，不能仅凭页面能发消息就认定满足 D-31。

## 为什么不采用“让 Hermes 自己轮询平台接口”

“轮询”需要区分两类完全不同的实现：

1. **确定性 worker 轮询数据库队列：接受。** 一次空扫描只是廉价 SQL；不会调用模型。
2. **Hermes/LLM cron 定时读取页面或 API 再判断有没有工作：拒绝。** 即使没有工作也会
   启动 agent/model，带来额度、重复执行、并发和恢复问题。

Hermes Kanban daemon 的官方 RFC 也明确记录：早期每 60 秒用 cron 唤起 agent 的方式会
无谓消耗 token，正确方向是常驻的确定性 daemon/state machine。这和本项目选择的 connector
原则一致，但 Kanban 自身仍是 Hermes 内部任务机制，不能替代平台 PostgreSQL 的 transport
command authority。

## 方案比较

| 方案 | 适合做什么 | 主要问题 | 本项目决定 |
|---|---|---|---|
| Browser 直接调用 Hermes | 快速原型 | 暴露 bearer/provider 边界；无同源会话、CSRF、平台审计 | **拒绝** |
| 平台 BFF 同步转发一次 chat HTTP | 简单对话 demo | HTTP 超时后 outcome unknown；没有可靠恢复、事件补播与 stop 对账 | **写端暂缓**；GET 只读已采用 |
| Hermes/LLM cron 轮询平台 | 低代码触发 | 空转消耗 provider；重复执行与状态漂移 | **拒绝** |
| Webhook 触发 Hermes | 外部系统把事件推入 Hermes | Webhook 是触发面，不是 durable command/outcome authority | **可作未来入站触发器** |
| Dashboard/TUI WebSocket bridge | 人工诊断、已有会话观察 | 端口/协议随运行时漂移；不是稳定 public contract | **仅诊断** |
| PostgreSQL outbox + deterministic worker + official API | 耐久交付、幂等、租约、恢复、审计 | 实现量更大；仍依赖 upstream 暴露足够语义 | **正式方案** |

## Official API 能给什么、当前还不能证明什么

当前安装的 official API capability 能暴露 Session/Run submission、status、event stream、
approval 和 stop 等接口，这是正式 transport 的正确起点。`/v1/responses` 还有 SQLite
response store，可持久读取 Responses API 对象。

但对当前 `0.18.2` 源码的检查显示，兼容 chat/Responses 路径使用的 idempotency cache 是
进程内、带 TTL 的缓存，而 `/v1/runs` 提交处理器没有应用这份 cache；也没有找到可持久恢复
相同 Run request 的权威 lookup，或 `Last-Event-ID` / durable event ID replay 合同。这个结论
是依据当前源码作出的**版本性推断**，不是断言 Hermes 永远不会支持。因此：official API
可以作为网络面，却仍不能代替平台 outbox，也不能让平台在 timeout 后盲目重发 prompt。

## 权威边界

| 事实 | 唯一权威 | 不能由谁冒充 |
|---|---|---|
| transport command、幂等键、event/outbox、lease、exact run link | platform PostgreSQL | HQA 内存、浏览器或 Hermes 标题匹配 |
| Session、Run、messages、actual provider/model/usage | Hermes | 平台的 requested provider 或全局配置 |
| research plan、Attempt、Gate、result refs 与 immutable payload | HQA append-only Task/Attempt/plan/payload authority（代码已验收；live activation pending） | platform command state；平台只保存 exact immutable metadata binding，不保存 prompt |
| factor/backtest/experiment/candidate 领域详情 | platform authoritative artifact/API | Unified Results 摘要副本 |

## 正式网络面

- Hermes official API Server：loopback `127.0.0.1:8642`，用于稳定的服务端 API 合同。
- Hermes Dashboard/TUI gateway：`9119` 或运行时动态 WebSocket 只作本机诊断，不写进正式
  connector 合同。
- Browser 只访问 platform BFF；Hermes bearer key 和 provider secret 永不下发浏览器。
- 远程访问不属于当前本机方案；未来必须先增加 TLS、登录、授权、CSRF 和审计。

## Webhook 的正确位置

Hermes 官方 webhook 能把外部 HTTP 事件映射成 Hermes 输入，适合告警、邮件、GitHub 事件等
“外部系统主动推入”的场景。它不能自动提供平台需要的 command idempotency、outcome recovery、
event cursor/replay、Run-scoped stop 和 actual provider evidence。因此 webhook 可以位于入口边缘，
不能取代数据库账本或作为完成状态的权威来源。

## Reddit / 社区方案怎么看

社区里已经有独立 Web client，以及用 state machine/poller 包装 Hermes 的实践讨论。这说明
“本地 Web UI + 本地 agent”是常见需求，也印证了显式状态机比盲目 cron 更可靠；但这些项目
不是 Hermes 官方稳定协议，安全边界、幂等、恢复和 provider 证据质量各不相同。它们适合作为
UX/adapter 参考，不宜直接当本项目的生产真相层。

另外，社区已有 Open WebUI 接入时“一个用户动作额外创建多个 session”的报告；常见原因是
标题、标签、追问建议等后台辅助请求也被转发给 agent。对本项目的直接启示是：BFF 必须给
**用户明确提交**和 UI 辅助请求分流，只有前者才可创建 durable command / Hermes Run。

## Chat 写端仍需满足的准入条件

在以下每项都有可测试、可恢复、可审计的实现前，composer 必须保持关闭：

1. `client_request_id` 幂等提交与相同请求恢复；
2. 不可变 Hermes Run identity；
3. durable event ID/cursor 和断线补播；
4. 持久 Run state 与重启后 reconciliation；
5. immutable requested provider policy；
6. actual provider/model/fallback/usage evidence；
7. approval identity/digest/TTL/single-use/CAS；
8. Run-scoped、幂等且可对账的 stop；
9. authenticated same-origin BFF、CSRF、审计与字段最小化。

上面 1–8 中与 Hermes capability/recovery 相关的缺口属于 upstream blocker；平台本身还必须
独立补齐 authenticated mutation BFF、CSRF、prompt retention boundary、workflow-binding live
readiness/BFF integration、dispatch adapter、composer/resume/stop UI、独立安全审查和用户
cutover 批准。两组
条件都是必要条件，九个 upstream blocker 清零也**不会自动**让网页 chat 变成 ready。

平台本地 ledger 解决的是“平台有没有耐久保存意图”，不能伪造 Hermes upstream 是否接收、
是否执行或实际用了哪个 provider。

## 当前实现映射

| 能力 | 当前状态 |
|---|---|
| official API session list/detail/messages | DONE，真实本机只读已验收 |
| PostgreSQL command/event/outbox/run-link ledger | DONE，正式 migration 与 live DB 已验收 |
| deterministic worker + LISTEN/NOTIFY + scan fallback | FRAMEWORK DONE，reconcile-only；ledger 有 claim/lease/heartbeat primitives，当前 worker 只做 notify/scan/expired-lease reconcile，不 claim queued command |
| 3C.1 HQA Task/Attempt/payload + exact cross-authority binding/audit | CODE ACCEPTED，隔离 PostgreSQL 实跑通过；platform migration 006 尚未 live apply，浏览器 BFF/worker 尚未消费 |
| chat/SSE/resume/provider evidence | BLOCKED，live capability gate 仍失败 |
| Unified Results | Wave 3E-A 只读目录、真实数据与 UI 验收 DONE；完整 cutover 仍未批准，独立 Hermes Run 证据仍等 3D |
| legacy page retirement | Agent Studio 已具独立可回滚开关但默认 OFF；另三页仍有写任务，不能一次切掉 |

## 3C.1 已代码交付；原 live-acceptance 顺序已被 D-32 修订

在任何 queued-command claim/dispatch 之前，**Slice 3C.1 — workflow identity、payload 与 exact
binding foundation** 已完成代码、故障注入、全量/目标测试和隔离 PostgreSQL 验收，并继续保持
零 Hermes/provider mutation：

1. HQA append-only Task/Attempt ledger 与窄 CLI（stable event ID、expected-version CAS、
   projection/replay、损坏与未知 schema fail closed）；
2. content-addressed immutable payload envelope（最小化 prompt、provider policy digest、TTL、
   删除/审计边界，不保存 provider secret）；
3. command → Task/Attempt/plan version 的 exact digest binding；
4. PostgreSQL 与 HQA 两个单写权威之间可在每个 crash point 恢复的幂等 saga/reconcile；
5. 在 3C.1 验收期间 browser POST、worker claim、Hermes mutation 和 provider call 全部保持 0。

后续 v0.2 复核发现当前 migration 006 对 `task_id` 做唯一约束，无法支持一个 Research Task 的
多个 Attempt，因此原“下一步直接请求 migration 006 授权并 live apply”的顺序已撤销。当前
migration runner 会先重放旧 SQL，不能默认追加 007 事后修补；D-32 选择直接修订从未 live
apply 的 006，并同步 schema meta/readiness/repository/claim/reverse audit/rollback/tests。先关闭
默认 startup auto-migration，并重新完成
空库/现有 005 库/幂等/权限/backup-restore/独立 review；只有这些全部通过后，才重新请求一次
明确 live migration 授权。apply 后仍只激活 authority foundation，不自动启用 browser POST、
worker claim 或 Hermes/provider mutation。

最终施工顺序是 Agent Workspace Interface/cardinality → stop-the-line baseline → Hermes durable
Run contract 与 HQA lifecycle → 修正后的 schema/authenticated BFF → supervised dispatch → 完整
workspace/SSE/approval/stop/results → 对抗验收后一次打开 Web Chat。逐页 cutover 仍独立后置。

## 调研来源

- [Hermes Agent 官方仓库](https://github.com/NousResearch/hermes-agent)
- [Hermes API Server 官方说明](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/api-server.md)
- [Hermes Programmatic Integration](https://github.com/nousresearch/hermes-agent/blob/main/website/docs/developer-guide/programmatic-integration.md)
- [Hermes API Server 源码](https://github.com/NousResearch/hermes-agent/blob/main/gateway/platforms/api_server.py)
- [Open WebUI 的 Hermes Agent 接入说明](https://github.com/open-webui/docs/blob/main/docs/getting-started/quick-start/connect-an-agent/hermes-agent.mdx)
- [Hermes Webhooks 官方文档源码](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/messaging/webhooks.md)
- [Hermes Web Dashboard 官方文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard)
- [Hermes Kanban daemon RFC / issue](https://github.com/NousResearch/hermes-agent/issues/16102)
- [PostgreSQL LISTEN](https://www.postgresql.org/docs/15/sql-listen.html)
- [PostgreSQL NOTIFY](https://www.postgresql.org/docs/16/sql-notify.html)
- [Reddit：Hermes Web client 讨论](https://www.reddit.com/r/hermesagent/comments/1svdr1l/web_client_for_hermes_agent/)
- [Reddit：state machine / poller 讨论](https://www.reddit.com/r/hermesagent/comments/1tukg0p/state_machine_for_statebased_integration/)
- [Reddit：Open WebUI 额外 session 讨论](https://www.reddit.com/r/hermesagent/comments/1srkszc/using_open_web_ui_creates_few_sessions_each_time/)
