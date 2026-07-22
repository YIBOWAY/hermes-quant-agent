# Agent v0.2 V4–V7 对抗性修复审计

日期：2026-07-23

状态：**SOURCE + ISOLATED ACCEPT；live cutover 未授权、未执行。**

本记录优先于 2026-07-21…23 各增量切片里的 `ACCEPT` 字样。那些记录仍是当时的
交付证据，但不能单独证明当前 runtime 已具备安全写入能力。

## 1. 基线判断

修复前总评为 **4.8/10**：V4 的数据库地基和 V5 的 worker 框架有价值，V6/V7 也形成了
较完整的 UI/authority 形状；但“hermetic 测试通过”“曾在本机跑通”“当前生产路径可恢复”
被混为一谈。若直接按原状态打开 composer，存在权限放大、重复 Run、永久 queued、审计
证据不完整和故障时假健康等风险。

完成修复并通过整套隔离验证后，工程质量评分为 **8.2/10**，V4–V7 综合完成度为
**7.4/10**；但当前 live 可用度仍只有 **4.0/10**。差值不是测试覆盖不足，而是 009/010、
受限 runtime LOGIN、Hermes/HQA candidate install/restart/canary 与剩余 V7/V8 产品范围尚未
进入真实运行态。

## 2. 已关闭的问题

| 风险 | 修复后的合同 | 主要提交 |
|---|---|---|
| hermetic V7 authority 可能进入生产 workspace | production 只接真实 authority port；fake 仅测试可构造 | platform `2485f94` |
| loopback 被误当成用户身份 | signed owner session、Host/origin/Fetch-Metadata/CSRF、ownership 与 session 限流共同校验 | platform `19fe8b3`, `93cd3c5` |
| 浏览器可通过 HTTP 获取 bootstrap secret | 删除 secret-returning route；operator CLI 生成 0600 一次性 token，用户手工粘贴 | platform `c513980`, `f9f9816` |
| session create/fork 写入永不可 claim 的 command | action 幂等归 session registry；不创建 dispatch command；migration 010 审计式取消旧 queued control rows | platform `05e9f77` |
| create/fork 同 ID 重试可能重复 session | registry 保存 immutable client action ID/digest；same/same 返回原 session，same/different 409 | platform `05e9f77` |
| historical `quant` superuser 被当作 runtime writer | migration 009 引入 NOLOGIN role、FORCE RLS、exact policy/privilege probe；不合格 principal 一律 readiness=false | platform `132b46d` |
| schema flag 被误当成 dispatch operational | schema/runtime identity/durable dispatch/local/public readiness 分层；缺 heartbeat/capability 时 composer 关闭 | platform `132b46d` |
| Hermes ACK 丢失/进程重启可能重复提交 | ledger command UUID 作为 upstream idempotency key；submit-or-recover + exact managed session + replay fold | platform `3a5fd47` |
| bounded Run reconcile 会饿死后续 Run | 对账前用 DB version CAS + `updated_at` 持久化公平轮转，并追加非终态审计事件 | platform `bcaca80` |
| SSE 客户端共享游标/状态 | 每连接独立 delivery state；数据库 projection 故障显式 degraded/unavailable | platform `1df310b`, `cb4e2f7` |
| prompt/secret 可能进入 argv 或异常文本 | payload 只经 stdin/subprocess port；CLI error allowlist/redaction | HQA `5da935d`, `bc049b4` |
| final Run 完成与 receipt 落盘之间崩溃 | terminal v1.1 事实内嵌确定性 receipt，可恢复且 provider 只调用一次；冲突重试 fail closed | HQA `bc049b4` |
| Gate 3 可接受旧 schema 或弱 provenance | schema 1.0 仅历史只读；1.1 必须绑定真实 provider、配置、summary/report 与 reviewed source | platform `14b2c66`, `c513980`; HQA `ad90d7b`, `962bbbb` |
| 多 symbol 论文代理错误共享终月完整性 | 每个 symbol 独立验证终月；artifact 明示 `workflow_proxy` / `full_paper_replication=false` | platform `b939a31` |

## 3. 当前真实状态

| 层级 | 结论 |
|---|---|
| V4 源码 | V4-R role/RLS、owner session、registry v2、server-owned provider policy 与 TTL 已实现。 |
| V4 live | 只有既有 006/007/008 事实；009/010 未 apply，`quant_app_runtime` 未 provision/switch。 |
| V5 源码 | claim/dispatch/recovery、fair reconcile 和 fail-closed adapter 接线已实现；CLI 默认仍 `reconcile_only`。 |
| V5 live | 没有把本 remediation branch 部署为常驻 supervised worker。 |
| V6 源码 | managed session continuity、durable Run submit/recover/fold、浏览器 exact retry 已闭合。 |
| V6 live | live Hermes 未加载本次 reviewed durable candidate，因此本地 composer 也必须保持 OFF。 |
| V7 源码 | approvals/stop/Gates/results 的 hermetic contracts 可用于测试；production 不再注入 fake。Gate 3/receipt 已加固。 |
| V7 live | 没有 V7g-A-M2 live Futu RO 证据、完整论文复现或 public V8 cutover。真实交易/下单始终为零。 |

论文纵切只验证论文因子工作流和人类 Gate 合同，不冒充完整复现。合法 Gate 1 仍需要用户实际
取得并逐页审阅的论文 PDF；平台当前 artifact 已机器可读地声明未实现全球/国家/事件级完整
复现。

## 4. 最终验证证据

所有命令均在 remediation worktree 或 disposable PostgreSQL 16 容器中执行；没有连接或修改
live `quantplatform`：

- HQA：`1761 collected`，full pytest exit 0（2 skip），full Ruff clean；
- platform backend：`1926 collected`，连接 disposable PostgreSQL 的 full pytest exit 0
  （2 skip）；full Ruff `src/quant_system tests` clean；
- frontend：Vitest `56 files / 298 tests`、`tsc --noEmit`、ESLint（0 warning）和 Next
  production build 全部 exit 0；
- migration 009/010 isolated replay、role/RLS denial、registry action collision、legacy control
  retirement与 bounded reconcile fairness 均进入上述 PostgreSQL suite；
- live read-only preflight 曾得到 `outcome_unknown=0`、`delivered=7`、`queued=3`，但它只是
  时间点证据；cutover 当日必须停 writer 后重查。

剩余唯一测试告警来自 FastAPI TestClient 使用旧 `httpx` bridge 的 Starlette deprecation；它是
依赖栈升级提醒，不影响本次合同结论，后续应在独立 dependency-upgrade slice 处理。

任何 live 数据库 apply、runtime credential 切换、Hermes/HQA install、服务重启或 provider canary
都不属于本次源码修复授权，必须按 runbook 单独确认。

## 5. Release verdict

本次可以给出的最高结论是 **SOURCE + ISOLATED ACCEPT**，不是
`LIVE ACCEPT`，更不是 `PUBLIC RELEASE`。完整 cutover 顺序见
[`../runbooks/agent-v0-2-v4-v7-cutover.md`](../runbooks/agent-v0-2-v4-v7-cutover.md)。
