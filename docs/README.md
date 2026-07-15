# 文档导航与当前执行状态

这份文件只回答三个问题：**现在按哪份计划做、实际做到哪里、其他文档该怎么读**。
长期方向、历史实现细节和特定日期审计分别留在 roadmap、plan 和 audit 中。

> 事实快照：2026-07-15。易变的 branch、dirty、PID、端口与服务健康不写死在这里；交接时
> 必须重新检查 git、进程、HTTP smoke 和测试。

## 当前执行入口

| 层级 | 权威文档 | 当前含义 |
|---|---|---|
| 产品路线 | [`design/2026-07-01-roadmap-phases-0b-4.md`](design/2026-07-01-roadmap-phases-0b-4.md) | Hermes 是个人量化 COO；`ai-quant-platform` 是领域后端。D-31 是当前产品主线。 |
| 已批准设计 | [`superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md`](superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md) | `/hermes` 为默认首页，逐步吞并 Factor Lab / Backtester / Experiments / Agent Studio 的体验，但不删除领域引擎/API/CLI/artifact。 |
| 当前 implementation plan | [`superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md`](superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md) | 3A official API session-read 已交付；下一开发切片是 3B durable ledger/outbox。chat、统一 Results 与旧页退场仍受 Gate。 |
| 当前 Hermes 合同 | [`contracts/hermes-api-server-0.18.2.md`](contracts/hermes-api-server-0.18.2.md) | official API Server 的 health/capabilities/sessions/detail/messages 只读合同；chat/run/stream/approval/stop 全部 fail-closed。 |
| 旧 TUI 合同 | [`contracts/hermes-gateway-0.18.2.md`](contracts/hermes-gateway-0.18.2.md) | 历史 WebSocket JSON-RPC 快照；当前 checkout/source 已漂移，不再匹配安装，不能用于准入。 |
| Wave 2 验收事实 | [`audits/2026-07-15-d31-wave2-evidence.md`](audits/2026-07-15-d31-wave2-evidence.md) | Scene-B 三道人类门与 Gate 3 commit 已真实闭合；同时记录仍未完成的 D-31 范围。 |
| Wave 2 原计划 | [`superpowers/plans/2026-07-14-d31-wave2-bridge-approvals-parity.md`](superpowers/plans/2026-07-14-d31-wave2-bridge-approvals-parity.md) | 历史执行清单；顶部 delivery addendum 优先于原 success criteria。 |
| Candidate / Gate 3 计划 | [`superpowers/plans/2026-07-13-candidate-integrity-and-gate3.md`](superpowers/plans/2026-07-13-candidate-integrity-and-gate3.md) | repo-anchored immutable candidate、Gate 1 binding、Gate 2 CAS、final receipt 与隔离 Gate 3 的实现记录；顶部 acceptance addendum 是最新事实。 |
| Phase 1a-4 v2 完成记录 | [`superpowers/plans/2026-07-10-phase-1a-4-v2.md`](superpowers/plans/2026-07-10-phase-1a-4-v2.md) | 9A–9H 已完成；不是当前 backlog。 |
| 完整 9H 完成记录 | [`superpowers/plans/2026-07-12-full-9h-automation-notifications.md`](superpowers/plans/2026-07-12-full-9h-automation-notifications.md) | 只读 automation、weekly、freshness、feed 1.1 与 local notification 的交付/运行验收。 |
| 平台 Slice 0–8 | `/Users/sunyibo/programs/ai-quant-platform/docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md` | 已完成的前端/数据库历史交付与 parity 输入，不是独立路线图。 |

## 一句话项目阶段

**Phase 1a-4 / 9H 已收口；当前处于 D-31 Wave 3，真实 Hermes 已接通到“已有会话只读”层，
但网页还不能向 Hermes 提交对话。** 下一步不是直接打开 composer，而是先实现 durable
command/outbox/event ledger，再接确定性 connector worker，最后才评估 chat 写端。

## D-31 当前事实

| 能力 | 状态 | 真实含义 |
|---|---|---|
| `/hermes` 专业只读首页 | **DONE** | 默认首页、SafetyStrip、Today/Tasks/Approvals/Results 只读框架已存在。 |
| Tasks 证据面 | **DONE** | 展示 automation、weekly、opportunity 等平台事实；没有 research task create/submit。 |
| Candidate integrity | **DONE** | canonical root、immutable manifest、verified/migration_required/corrupt、digest/status CAS、legacy_unbound 非授权。 |
| Scene-B Gate 1/2/final/Gate 3 | **DONE** | 人类 Gate 3 commit `524e791e5e3e22cec12a4166ad8fc3617c735566` 已进入 promoted registry 并 cleanup。 |
| Hermes official API session read | **DONE（代码 + 本机只读验收）** | 平台 BFF 能读真实 session list/detail/messages；浏览器不持有 Hermes key。 |
| Browser Gate 2 mutation | **ROLLED BACK / OFF** | 初版会 refetch digest/status，违反 HQA Gate 1 exact binding 与 Gate 2 no-refetch；Approvals 当前只读。 |
| Hermes chat/stream/resume/stop | **BLOCKED** | 缺 durable request recovery、Run identity、event replay、provider evidence、approval/stop 对账语义。 |
| Unified Results | **NOT DONE** | 仍缺统一动态详情、exact Run/result linking 与旧页面 parity。 |
| Legacy page redirects/deletion | **NOT DONE** | 旧四页仍完整保留；soft banner 不等于 redirect 或 retirement。 |
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
本次 session-read slice 没有新增 PostgreSQL migration/table；数据库只复用既有迁移。

### 下一条成熟链路

```text
Browser -> same-origin BFF
        -> PostgreSQL command + outbox + event ledger
        -> HQA deterministic connector worker
        -> Hermes official API HTTP/SSE
```

轮询只用于数据库 queue claim/lease/heartbeat/reconcile，并以 `LISTEN/NOTIFY` 唤醒、周期 scan
兜底；**禁止让 Hermes/LLM cron 空转询问“有没有任务”**。空队列不创建 Run、不调用 provider。

写端只有在 request idempotency/recovery、Run identity、event cursor/replay、provider policy lock、
actual provider/fallback/usage evidence、approval TTL/digest/single-use 和幂等 stop/reconcile 均有
审查证据后才能打开。当前 `chat_write=false`、`approval_mutations=false`。

## 接下来按什么顺序做

1. **Wave 3 / Slice 3B：durable ledger/outbox。** 先做 migration、幂等 command、append-only
   events、exact run/result links；不提交 Hermes prompt。
2. **Slice 3C：deterministic worker。** DB claim/lease/backoff/reconcile；写 Hermes 仍受合同 Gate。
3. **Slice 3D：chat/stream/resume。** 只有能力审计、认证/CSRF、安全 review 和用户批准通过才做。
4. **Slice 3E：unified Results。** 建统一索引/详情与 exact provenance，不复制领域真相。
5. **Slice 3F：legacy retirement。** parity matrix + 真实 E2E + 用户确认后，先导航切流/可回滚
   redirect，最后才删除旧 UI；领域 API/CLI/engine 保留。

不得从旧 1a-4 计划、历史 audit 或 unchecked checkbox 自行增加当前步骤。

## 阅读顺序

1. 本文件：确定当前主线、已完成与明确关闭项。
2. D-31 design spec：核对产品目标与安全模型。
3. Wave 3 plan：只执行当前 slice；不要越过写端 Gate。
4. official API contract：核对当前安装身份、GET allowlist 与 provider 语义。
5. Wave 2 audit / candidate plan：需要追溯 Gate 1/2/3 时再读。
6. roadmap：核对长期阶段；历史计划只作证据，不作待办。

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

## 双仓职责与安全边界

- `Hermes-quant-agent`：编排、记忆、cron、通知、三门 provenance 与未来 connector worker。
- `ai-quant-platform`：行情、因子、回测、期权、paper account、PostgreSQL、BFF 与前端领域实现。
- Gate 1/2/3 与 Hermes command approval 互不替代；机会决策也不产生执行资格。
- action 只按 exact platform signal/execution IDs 关联；ticker/symbol 相似不是因果证明。
- 不绕过 `paper_trading`、`live_trading_enabled=false`、kill switch 或人工审批门。
- `/api/agent/tasks` 不是 Hermes fallback；upstream unavailable 时必须诚实 unavailable。

## 历史材料

- `plans/2026-07-01-phase-0a-*`、`phase-0b-*`、`phase-1a-*` 与 D-25 记录用于追溯。
- `2026-07-07-phase-1a-4-research-employees.md` 已被 v2 替代，不能逐项继续执行。
- 平台 `docs/phases/phase_15_iteration_roadmap.md` 只有参考价值，不是第二路线图。
- 历史审计中的优先级和“下一步”只对当日快照有效；当前状态回到本文件、代码、git 和测试。
