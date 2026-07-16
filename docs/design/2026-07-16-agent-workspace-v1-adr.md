# Agent Workspace v1 ADR — LIMITED-DEVICE CANDIDATE

> **状态：LIMITED-DEVICE CANDIDATE IN PROGRESS / PRIMARY VALIDATION PENDING / V0 NOT DONE。**
> 当前只有 targeted-only 合同文档候选；primary 三仓 full suite、executable contracts、runtime
> manifest、validation 与 cross-review 均待完成。本 ADR 不授权任何 live effect。

## 决策

Agent Workspace v1 只暴露三个概念：

```text
act(actor, UserActionV1) -> ActionReceipt
snapshot(actor, WorkspaceRef) -> WorkspaceSnapshot
follow(actor, WorkspaceRef, after?: WorkspaceCursor) -> EventPage / SSE
```

`act` 只接受下面这个关闭的 tagged union，v1 不接受 generic execute、任意 workflow 或额外 action：

```text
CreateManagedSession
ForkIntoManagedSession
ConversationTurn
StartResearch
ContinueResearch
ConfirmResearchPlan
RequestStop
DecideHermesCommandApproval
ConfirmFormulaSource
ReviewCandidateCAS
PreparePromotionReview
```

`snapshot` 是权威事实的可重建只读投影；`follow` 只跟随 durable observation。route、React hook
和 worker 不得各自实现恢复状态机。`client_action_id` 的 namespace 固定为
`owner_id + workspace_id + action_kind`；同 namespace 内再绑定 `action_digest`。必须先验证 signed
actor session 与 Workspace ownership，之后才能 lookup 或返回 cached receipt；同 ID 同 digest 返回
原 receipt，同 ID 不同 digest 冲突且零新增写入。超时后只按原 identity reconcile，禁止盲重发。

## Workspace ownership 与 session containment

- 每个 Workspace 恰有一个 immutable owner；owner 可拥有多个 Workspace。`act`、`snapshot`、
  `follow` 在读取 receipt、projection 或 event 前都必须验证 authenticated actor 是该 owner。
- 每个 `web_managed_session` 恰好 contained by 一个 Workspace，只有该 Workspace owner 可写。
  Workspace 可链接 external Session 作为只读 observation/lineage source，但链接不转移 ownership 或 writer。
- fork 的 managed child contained by actor-owned Workspace；parent 保持 external read-only 或原 managed
  owner 独占。Task/Attempt/Command/Run/Result 只有经 exact refs 属于该 Workspace 才可读写或 follow。
- `observed_external_session` 在 Web 始终只读；ownership 校验不能把它升级为 managed writer。

## Action 合同

| Action | 唯一语义与边界 |
|---|---|
| `CreateManagedSession` | 创建 Web 独占写入的新 Hermes Session，并一次性固定 provider policy 与 payload TTL。 |
| `ForkIntoManagedSession` | 从 external/managed parent 创建新的 managed child；保存 immutable lineage、fork point、source channel，并重新选择 provider policy。 |
| `ConversationTurn` | 创建 submission Command 和至多一个 Hermes Run；不创建 HQA Task/Attempt，不产生领域 candidate/artifact。 |
| `StartResearch` | 显式创建一个 Research Task 与首个 Attempt；首 Run 可以只生成 plan。 |
| `ContinueResearch` | 在同一 Task 下创建新的 Attempt；不得复用旧 Attempt 的 submission Command。 |
| `ConfirmResearchPlan` | 人类确认 exact plan version/digest；只属于 HQA plan authority，不是 command approval 或 Domain Gate。 |
| `RequestStop` | 对 exact Run/Attempt/platform job 发幂等 stop request；未知层保持 reconciling，不宣称全局 stopped。 |
| `DecideHermesCommandApproval` | 对 exact Hermes challenge 做 TTL、single-use、CAS 的 allow-once/deny；不接受“永久允许”。 |
| `ConfirmFormulaSource` | Gate 1；HQA 保存 exact reviewed source SHA-256、非空 note，之后绑定 exact candidate/manifest。 |
| `ReviewCandidateCAS` | Gate 2；平台 repository 只按人类提供的 candidate/digest/expected pending status/note 做 CAS，禁止自动 refetch/substitute。 |
| `PreparePromotionReview` | Gate 3 entry；HQA 重验 Gate 1 与同 candidate/digest 的 final receipt，再委托平台只准备 isolated diff/base/manifest；网页永不 commit。 |

普通 turn 与 research action 使用同一 control plane；只有 research action 进入 HQA Task/Attempt/Gate
authority。请求线程不调用 Hermes/provider；durable receipt 先于异步 dispatch。

## 权威矩阵

| 权威 | 唯一拥有的事实 | 明确不得拥有 |
|---|---|---|
| Hermes | Session、Run 原始状态/事件、messages、actual provider/model/fallback/usage、command approval challenge | 平台 command lease、HQA plan/Gate、领域结果真相 |
| PostgreSQL | managed/external session registry 与 lineage、transport command/event/outbox/lease、client idempotency、exact Hermes Run link、可重建 observation cursor | prompt 正文、伪造的 actual provider、领域 artifact |
| HQA | Research Task/Attempt、plan version/digest、Gate 1 reviewed-source confirmation 与 candidate/manifest binding、Gate 3 entry/revalidation refs、result refs、payload retention/reconcile | 第二份 transport journal、Gate 2 CAS、回测指标正文 |
| 平台领域 repository/artifact | factor、candidate、backtest、experiment、options result、Gate 2 exact CAS、promotion prepare primitive 与 provenance | Hermes transcript、HQA Task、Gate 1 provenance、人的 Git commit |
| 人类 Git review/commit | Gate 3 最终完成事实：审阅 exact isolated diff 后产生 commit | 自动批准、网页代 commit、Hermes/HQA 推测完成 |
| Intent payload seam | owner-only、content-addressed、encrypted/TTL 的 chat/research 输入 | command lifecycle、result、secret |

Agent Workspace 不建第五份业务 journal；snapshot/event/cursor 必须可重建。未知事实显示 `unknown`，
不得跨权威推测或回写。

## Cardinality 矩阵

| Source | Cardinality | Target / 含义 |
|---|---|---|
| owner principal | 1:N | Workspace；每个 Workspace 恰有 1 个 immutable owner |
| Workspace | 1:0..N | contained managed Session；每个 managed Session 恰属 1 个 Workspace |
| Workspace | 1:0..N | linked external Session refs；只读且不转移 writer ownership |
| `observed_external_session` | 1:1 | Hermes Session；Web read-only |
| `web_managed_session` | 1:1 | Hermes Session；Web control plane 是唯一 writer |
| parent Session | 1:0..N | fork 后的 managed child；每个 child 只有 0..1 parent |
| Workspace | 1:N | Research Task |
| ConversationTurn action | 1:1 | submission Command；不创建 HQA Attempt |
| Research Task | 1:N | Research Attempt |
| Research Attempt | 1:0..1 | submission Command；prepare/reconcile 可暂缺，durable acceptance 后恰有 1 个 |
| submission Command | 1:0..1 | Hermes Run |
| Hermes Run | 1:0..1 | Research Attempt；ordinary conversation Run 为 0 |
| Hermes Run | 1:0..N | exact Result Link |
| Hermes Run | 1:0..N | control Command（stop/approval 等） |

## Session、lineage 与 provider

- Discord/历史 `observed_external_session` 在 Web 永久只读；任何 Web POST 都以 `conflict` 零写入。
- Web 写入只允许新建 `web_managed_session`，或显式 fork 到新的 managed Hermes Session；fork
  不接管 parent，不共享 writer，并保存 parent ID、source channel 与 fork point。
- provider policy 只在 create/fork 时选择并持久化，同一 managed Session 内 immutable。fork 必须
  重新选择，不能继承可变写权或把 requested provider 当 actual provider。
- actual provider/model/fallback/usage 只来自 exact Hermes Run evidence；缺失就是 `unknown`。

## 五类互不替代的决定

| 决定 | Exact binding | 权威 / 完成事实 |
|---|---|---|
| Plan confirmation | Task、plan version、plan digest、expected status、human note | HQA；只允许继续该 exact plan |
| Hermes command approval | approval ID、Run ID、canonical command digest、expiry、expected pending status | Hermes challenge + single-use CAS；allow-once/deny |
| Gate 1 | reviewed source SHA-256、非空 note，随后 exact candidate ID/manifest digest | HQA provenance；plan digest 不能替代 source bytes |
| Gate 2 | candidate ID、expected digest、expected status `pending`、note | 平台 repository 人类 CAS；严禁 list/refetch/substitute |
| Gate 3 | Gate 1 binding、same candidate/digest final receipt、base commit、isolated patch/manifest | HQA revalidation + 平台 prepare；最终只有人类 Git review/commit |

不得提供通用 `approve(id)` 或运行时 `gate_kind` payload。Gate 3 的 prepare 只返回待人工审阅材料；
它不是 promotion 完成事实。

## 稳定错误与恢复

| `code` | 含义 | 唯一允许的恢复动作 |
|---|---|---|
| `validation` | schema、大小或字段不合法 | 修正输入；未 durable accept 前可复用原 client action identity |
| `auth` | owner session 缺失、伪造或过期 | 重新完成 owner authentication；原 mutation 不视为成功 |
| `forbidden` | actor、ownership、origin 或 action 不被允许 | 停止重试；更正 owner/target 后发起新的显式 action |
| `conflict` | 同 ID 不同 digest、external write、immutable policy 冲突 | 保留零写入；用户显式选择合法 target/新 action，禁止自动改写 |
| `stale` | expected version/status/digest 已漂移 | 只读 snapshot 展示冲突并要求新的人工决定；Gate 2 禁止自动替换 CAS 值 |
| `capability` | readiness/manifest/capability gate 未满足 | 保持 read-only，修复并重新验证 capability；不降级到旁路 |
| `unavailable` | 某权威暂时不可达 | read 可退避重试；mutation 只按原 identity lookup/reconcile |
| `outcome_unknown` | accept 后丢包或跨权威结果未知 | follow/reconcile exact receipt；禁止换 ID、重建 Attempt 或盲重发 |
| `expired` | approval、payload 或 action TTL 已过 | 重新获取事实并经人类重新审阅后创建新的显式 action |
| `integrity` | digest、lineage、manifest 或权威冲突 | stop-the-line，保持只读并独立审计；不得自动修复 |
| `quota` | provider/rate budget 不可用 | 展示 `retry_after`/policy；仅以原 identity 安全恢复或等待新的人类 action |

cursor 过期或 source gap 以 `resync_required` recovery detail 触发新 snapshot/rebuild；不得静默跳到
“现在”。SSE 断线不停止 Run。

## Owner、认证、CSRF 与 retention

- owner bootstrap 使用 macOS Keychain 或 owner-only `0600` 一次性 token；交换后立即轮换。签名
  key、bearer/provider secret 不进入仓库、日志或浏览器脚本。
- BFF 只接受配置中 exact loopback Host + port；`127.0.0.1`、`localhost` 或 `[::1]` 仅在逐项配置
  时有效，禁止 wildcard/suffix match。loopback binding 不是 authentication。
- sensitive GET、`snapshot` 与 SSE/`follow` 都要求 accepted Host、signed actor session 和 Workspace
  ownership。浏览器 API 请求的 `Origin` 必须缺失或 exact accepted origin，`Sec-Fetch-Site` 必须是
  `same-origin`；foreign/inconsistent metadata fail closed，`none` 只允许顶层文档、不得用于 API/SSE。
- 平台签发 12 小时 `HttpOnly`、`SameSite=Strict` signed cookie（适用时 `Secure`）。mutation 在上述
  read policy 之外还必须验证独立 CSRF token、action digest 与 rate/size limit。
- v0.2 防跨站 loopback 诱导、重放、错误 owner 与最小 DOM 暴露；恶意 same-UID 本地进程不在
  可可靠防御范围。limited-device 候选不执行 bootstrap 或签发 cookie。

| 数据面 | 冻结策略 | 删除 / 恢复语义 |
|---|---|---|
| Intent payload | owner-only 加密；managed Session 默认 7 天，创建时可选 1–30 天且之后不可放宽 | 到期删正文、留 digest tombstone；不得从 transcript/backup 复活 |
| Hermes transcript | Hermes canonical policy 保留；不随 payload TTL 自动删除 | export/delete 是独立显式操作 |
| PostgreSQL | 只存 digest、refs、command/event/audit、lineage；禁存 prompt/message 正文 | 审计事实保留；v0.2 无隐式 GC |
| Operational log | 禁止 body、prompt、assistant body、bearer/provider secret；轮转上限 14 天 | 不能作为恢复 authority |
| Browser | `Cache-Control: no-store`；plaintext 只在页面内存；禁 localStorage/IndexedDB/service-worker cache | 刷新后只从 authenticated BFF 恢复 |

restore 必须保留原 `expires_at`，不得重新计时；已过期 payload 不能被旧备份无声复活。

## Migration 决策：Scheme A

直接修订**从未 live apply** 的 migration 006，并将 SQL、schema metadata/version、readiness、
repository、claim、reverse audit、rollback/restore runbook、空库/005 现有库/concurrency/idempotency
测试作为一个原子 co-change 重新审查。保留 per-Attempt uniqueness，并表达一个 Task 的多 Attempt；
ordinary conversation 不伪造 task/attempt binding。

当前 replay-all runner 下禁止追加 007 绕过旧 006。旧 3C.1 验收只是历史 foundation evidence。
本 ADR **无 SQL、不改 migration、不授权 live apply**；实现和独立 PostgreSQL/full validation 属于
后续任务，live apply 仍需新的明确授权。

## 三仓 source/runtime manifest（fail closed）

每次 build/install/start/smoke/release 必须生成同一份 manifest；每仓至少记录 repo、absolute checkout、
branch、base/source commit、dirty、artifact digest、runtime command/version/commit、PID/start time 和环境；
Hermes 还须同时固定 checkout、installed package 与 running process identity。

| Repo | Candidate branch | Frozen base |
|---|---|---|
| HQA | `codex/agent-v0-2-limited-device` | `a7428b6219ded4550f4c8951b6fabc4542a1724f` |
| ai-quant-platform | `codex/agent-v0-2-platform-limited-device` | `7b73b5f2fe9e80509f4762c3de696d1e2c58fc9d` |
| Hermes | `codex/agent-v0-2-durable-runs` | `a79b818360700d526c0a48107444810e3d6ecc2e` |

manifest 缺失、source 不匹配、dirty 未声明、artifact/runtime identity 不匹配，或 Hermes checkout/install/process 任两者漂移时，所有 write readiness、claim/dispatch、provider
与 live Gate 必须 fail closed；不得使用未知 live checkout、旧 TUI gateway、fake adapter 或手工覆盖
来继续。read-only 诊断可以保留，但必须明确显示 identity mismatch。

## Candidate 验收边界

此 ADR candidate 已存在，但 executable action/cardinality/auth/retention contracts、runtime manifest、
primary validation、三仓 full suite 与独立 cross-review 均 pending；V0 不是 DONE。在此之前 public
composer、`chat_write_ready`、browser mutation、worker claim/dispatch、provider、Gate 与 migration
live apply 全部保持 OFF。
