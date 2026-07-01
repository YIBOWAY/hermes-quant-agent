# Hermes-quant-agent 后续路线设计 spec（Phase 0b → 4）

> 状态：定稿（2026-07-01），经 brainstorming + grilling 逐项对齐。
> 上游：`docs/design/hermes_quant_agent_plan.md`（总设计）。前置：Phase 0a 已交付（只读数字员工，见 `docs/plans/2026-07-01-phase-0a-readonly-digital-employee.md`）。
> 本文定位：把 0a 之后的全部阶段一次性对齐方向。**分层规划**——近期阶段给完整 TDD 计划，中期给设计 spec，远期给方向大纲。
> 安全红线（贯穿全程，继承总设计）：实盘执行层完成前，保持 `paper_trading` / `live_trading_enabled=false` / `kill_switch` / 人工审批门。任何策略、agent、cron、MCP 都不得绕过。

---

## 0. 分层规划原则

后续阶段成熟度差异极大，规划详细度必须与确定性匹配，否则为远期写下的细节几乎必然返工（违反 YAGNI）。

| 层 | 阶段 | 产出形式 | 文档 |
|---|---|---|---|
| 近 | 0b, 1a-1, 1a-2 | 完整 TDD 实现计划（可逐步执行） | `docs/plans/*.md` |
| 中 | 1b, 2 | 设计 spec（架构 / 接口契约 / 验收门；不到步骤级） | 本文 §3、§4 |
| 远 | 3, 4 | 方向大纲（硬约束 / 开放问题 / 决策标准；不做实现设计） | 本文 §5、§6 |

近期阶段的 TDD 计划在本文定稿后单独产出；1a-1/1a-2 计划在写作前需先核验平台 CLI 面（`factor` / `backtest` / `experiment` / `agent` / `options`）、AI HOT 公开 API 形状、Discord 投递配置，以保证「无占位符」。

## 0.1 决策台账（本次对齐结论）

| 编号 | 决策 |
|---|---|
| D-META-1 | 分层规划：0b+1a 完整计划、1b+2 spec、3+4 大纲 |
| D-1 | Phase 0b 重定位为「可观测与治理底座」；API/MCP 鉴权从 0b **移到 1b 开头** |
| D-2 | 复盘日志放 **Hermes 层专用 append-only 库**，与 0a run-log、平台评审池分开；喷给 Hermes memory |
| D-3 | 复盘日志 **JSONL + Markdown 双格式**；固定 schema |
| D-4 | 复盘触发 **混合式**：自动起草骨架（机器字段预填）+ 人工补判断字段并确认；LLM 不代写推理 |
| D-5 | Phase 1a = 5 员工 + 场景 A/B，全 read-only/proposal-only；写作时拆 **1a-1 核心 / 1a-2 进阶** |
| D-6 | 1a 数据：行情/因子/期权走平台本地 CLI；AI HOT 走独立公开 REST API（非平台 HTTP）；**KOL 推迟** |
| D-7 | **1a 引入 Discord** + §6.1 频道分流；local 默认兜底 |
| D-8 | 记忆底座 = Hermes memory + 0b 复盘库 + 0a run-log；**推迟 HindSight** |
| D-9 | Phase 1b：adapter 建在平台内，暴露为**新业务 MCP server**；只读 probe 先行；变更走鉴权+审批+幂等+状态机+审计 |
| D-10 | Phase 2 审批：**模拟单在风险信封内自动批**、超出人工；Phase 3 真钱逐单人工；采纳 §10 满月指标集 |
| D-11 | Phase 3：锁死总设计 §10 八条硬约束；首实盘 = Longbridge（升级 1b/2 adapter）；单券商单策略小资金低频 |
| D-12 | Phase 4：延后；IBKR 期货；硬门槛 = Phase 3 实盘链路稳定 |

---

## 1. Phase 0b — 可观测与治理底座（→ 完整 TDD 计划）

目标：把「记得你如何做错过」的复盘系统做成一等对象，并把「策略进券商模拟的验收门」定义清楚。全程 Hermes 层、只读、纯 stdlib，不碰平台、不碰交易链路。

### 1.1 复盘/错误日志系统

- **存放层**：Hermes-quant-agent 仓库内，专用 append-only 库，独立于 0a 的 `logs/*.jsonl` run-log 与平台评审池（D-2）。
- **双格式**（D-3）：
  - 权威源：`review/entries.jsonl`（一条一行，机器可检索）。
  - 人读镜像：`review/entries.md`（从 JSONL 渲染，按时间倒序，可读可分享）。
- **固定 schema**（每条复盘）：
  - `id`（时间戳+序号）、`ts`、`kind`（alert / manual / weekly）、`status`（draft / confirmed）
  - 机器字段（自动预填）：`event`、`data`（run-id、指标、来源）、`source`
  - 人类判断字段（人工补全）：`judgment`（我当时怎么判断）、`basis`（依据）、`result`（结果）、`failure_point`（失误环节）、`next_rule`（下次规则）
- **触发=混合式**（D-4）：
  - 自动起草：0a 看门狗告警时、或周复盘时，生成一条 `status=draft` 的骨架，机器字段填好，人类字段留空。
  - 人工补全+确认：用户填人类字段后置 `status=confirmed`。**LLM 不代写 `judgment/basis/failure_point/next_rule`**——只可提示「此处需人工补充」。
  - 随手手动：可直接新建一条 manual 复盘。
- **接口面**（CLI，供人和 cron 用）：
  - `hqa-review draft --kind alert --event "..." --data k=v ...` → 追加一条 draft，返回 id。
  - `hqa-review confirm <id> --judgment .. --basis .. --result .. --failure-point .. --next-rule ..` → draft→confirmed。
  - `hqa-review list [--status draft] [--since 7d]` → 列表。
  - `hqa-review render` → 从 JSONL 重建 Markdown 镜像。
- **喂记忆**：`render` 产出的 Markdown 供 Hermes memory / 周复盘读取（D-8）。
- **与 0a 集成**：看门狗 `main()` 在 `alert=True` 时，除了 stdout 告警，再调用 `hqa-review draft --kind alert`（幂等：同一告警指纹当天只草拟一条）。

### 1.2 券商模拟验收门定义

- 交付物是**文档 + 一个校验器**，不是执行代码。
- 固定一份「策略进入券商模拟」的验收清单（对应 §10 满月指标的前置门）：策略必须先通过回测基线、有明确风险信封参数、有 kill-switch 挂钩、有复盘钩子。
- 校验器 `hqa-gate check <strategy-config>` 读策略配置，逐项判定 pass/fail，输出结构化结果；**只读、只判定、不放行**（放行是 Phase 2 人工决定）。

### 1.3 Phase 0b 验收

- 复盘库双格式一致（JSONL 为权威，MD 可从 JSONL 无损重建）。
- 人类判断字段永远不被 LLM/自动流程填充。
- 看门狗告警能自动落一条 draft，且幂等。
- 验收门校验器只读、纯判定。
- 全程不碰平台交易链路，不需鉴权。

---

## 2. Phase 1a — 数字员工 MVP（→ 完整 TDD 计划，拆 1a-1 / 1a-2）

目标：让 Hermes 成为真正有用的个人研究助理。全部 read-only / proposal-only。

### 2.1 员工清单与拆分（D-5）

**1a-1 核心**（先落地、依赖最少）：
1. **盘前 digest 升级**：在 0a 基础上加宏观日历/新闻摘要（AI HOT 源）、当日关注标的、安全状态。
2. **场景 A 信号看门狗**：盘中每 N 分钟扫描**交易信号**（动量 / 期权 IV 分位 / 异动），`[SILENT]` 无信号不打扰，有信号推 Discord `#盘中异动`。**注意区别于 0a 的安全不变量看门狗**——那个看 `safety.*`，这个看市场信号。
3. **周复盘报告**：读 0b 复盘库 + 0a run-log，汇总本周信号/错判/空过机会/风险事件，推 `#复盘`。

**1a-2 进阶**：
4. **期权 radar 摘要**：`options daily-scan` 结果的结构化摘要 + 分位提醒，推 `#期权radar`。
5. **AI HOT / 个股异动提醒**：独立公开 REST API（D-6），异动才推。
6. **场景 B 论文因子复现**：人工把因子/公式发来 → Hermes 调平台 AI 因子生成把它翻译成平台配置 → **人工确认翻译无误（关键 gate）** → 调 `backtest`/`factor run` 在真实历史数据回测 → 结果落评审池 + 推 `#回测结果` → 人工决定 promote。

### 2.2 数据自主性（D-6）

- 行情 / 因子 / 期权 / 回测：全走平台本地 CLI（`/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/quant-system`，`cwd=平台目录`），不依赖外部行情 API。
- AI HOT / 新闻：走独立公开 REST API（aihot skill / 直接 curl），**不为它起平台 HTTP**（鉴权在 1b 才引入）。
- KOL / 社交监控：**推迟**（需单独定源，1a 不做）。

### 2.3 通知渠道（D-7）

- 1a 引入 Discord，频道分流按 §6.1：`#盘前digest` / `#盘中异动` / `#期权radar` / `#回测结果` / `#复盘` / `#审批`（审批频道 Phase 2+ 才用）。
- **local 默认兜底**：Discord 未配置则自动退回 local；1a-1 含一个可选的「配置 Discord」一次性任务，脚本对「未配置」优雅降级。

### 2.4 记忆底座（D-8）

- Hermes 原生 memory + 0b 复盘库 + 0a run-log 作为底座；周复盘员工把要点喷给 Hermes memory。不接 HindSight。

### 2.5 Phase 1a 验收

- 全部 read-only / proposal-only：不触发 paper account mutating、不触发 backtest 之外的执行、不碰真实交易 API。
- 场景 A：盘时稳定运行、无信号静默、每条提醒带标的/信号类型/关键指标/时间戳/run-id。
- 场景 B：能把一个中等复杂度论文因子跑到回测出报告；**因子翻译有人工确认 gate**，不允许 LLM 理解直接进回测；结果落评审池不自动生效；无法可靠翻译时明确报「需人工补充定义」。
- Discord 未配置时全链路仍能以 local 工作。

---

## 3. Phase 1b — Longbridge 券商模拟 adapter（设计 spec）

目标：把券商级模拟作为执行外环，仍不进入实盘。这是架构从「CLI 编排」转向「server-side / MCP adapter」的转折点。

### 3.1 架构（D-9）

- **adapter 建在 ai-quant-platform 内**（领域后端，已有 persistent paper account + risk engine + 评审池），不在 Hermes 层。
- 对外暴露一个**新的业务 MCP server**（§7 所指），Hermes 用 `hermes mcp add` 消费；高风险能力只经此面，不走自由 shell。
- 用 `longbridge` SDK；**弃用 deprecated `longport`**。
- 先做**只读 account/status probe**，跑通后再开变更类操作。

### 3.2 MCP 工具面（契约）

只读 probe（无副作用，可随时调）：
- `broker_sim.account_status()` → `{cash, buying_power, currency, updated_at}`
- `broker_sim.positions()` → `[{symbol, qty, avg_price, market_value, unrealized_pnl}]`
- `broker_sim.orders(status?)` → `[{client_order_id, symbol, side, qty, type, state, filled_qty, avg_fill_price}]`
- `broker_sim.order_status(client_order_id)` → 单订单当前状态

变更类（每次必须带 `approval_token` + `client_order_id` 幂等键）：
- `broker_sim.submit_order(client_order_id, symbol, side, qty, type, limit_price?, approval_token)` → ack
- `broker_sim.cancel_order(client_order_id, approval_token)` → ack

每个变更调用的服务端不可绕过校验链：**kill_switch 检查 → 风险信封校验 → 幂等去重 → 人工审批 token 校验 → 审计日志落盘 → 才提交给券商模拟**。

### 3.3 订单状态机与恢复

- 状态：`NEW → PENDING_SUBMIT → SUBMITTED → (PARTIALLY_FILLED) → FILLED | CANCELLED | REJECTED | ERROR`。
- 幂等：`client_order_id` 为幂等键，服务端去重；重复提交同键返回既有订单，绝不重复下单。
- 恢复：进程重启后，用 `order_status` 与券商对账，本地状态可重建、可查询。
- 所有失败路径写入审计日志与（经 0b）复盘草稿。

### 3.4 鉴权（从 0b 移来，D-1）

- MCP server / 平台 API 入口需 bearer token / API key；**凭证由 Hermes 管理、绝不进入 LLM 上下文**。
- 最小权限：读、写分离的 token；probe 用只读 token，变更用写 token。
- 本地-only 默认；任何外部入口访问前必须鉴权。

### 3.5 审计日志

- 每个变更操作 → append-only 审计记录（时间、approval-token 指纹、参数、结果、幂等键），独立于 run-log 与复盘库。

### 3.6 Phase 1b 验收

- 无真实资金权限。
- 订单状态可恢复、可查询、可审计；所有失败路径入审计+复盘。
- Hermes 只能提出/转交候选，不能绕过审批直接执行。
- 只读 probe 与变更操作 token 权限分离。

---

## 4. Phase 2 — 策略闭环 + 满月（设计 spec）

目标：研究 → 信号 → 风控 → 候选 → 人工审批 → Longbridge 模拟执行 → 复盘，跑满月并通过量化验收。

### 4.1 闭环各段与承接组件

| 段 | 承接 |
|---|---|
| 研究 | 平台 factor / backtest（含 1a-2 场景 B 复现流水线） |
| 信号 | 平台 strategy sleeve |
| 风控 | 平台 risk engine + **风险信封**（见下） |
| 候选 | 平台评审池（pending） |
| 审批 | **信封内自动批 / 超出人工**（D-10） |
| 模拟执行 | 1b MCP adapter（券商模拟） |
| 复盘 | 0b 复盘库（每次回撤/拒单自动起草 draft） |

### 4.2 风险信封模型（D-10）

- 预注册参数：`{per_order_max_notional, per_order_max_qty, symbol_whitelist, daily_loss_cap, weekly_loss_cap, max_position_per_symbol, max_gross_exposure}`。
- 模拟单落在信封内 → 自动批准并经 1b adapter 执行；任一项越界 → 需人工审批。
- kill-switch + 审计全程在；越权尝试记审计+复盘。
- **数值阈值 = 按策略在 kickoff 设定**，不写死在 spec。

### 4.3 满月验收门（采纳总设计 §10 指标集）

需持续记录并达标：模拟运行天数 ≥ 30；最大回撤；日/周亏损；拒单率 / 撤单率 / 部分成交；预期价格 vs 实际模拟成交价（滑点）；人工审批延迟；策略是否越权；每次回撤是否有复盘日志。只有通过满月验收的策略才允许进入 Phase 3 讨论。

### 4.4 Phase 2 验收

- 闭环端到端可跑，候选不自动生效。
- 信封机制可自动批/拦截并留痕。
- 满月指标齐全、可导出；每次回撤都有对应复盘条目。

---

## 5. Phase 3 — 半自动实盘（方向大纲）

Phase 3 不是「把模拟改成 real」，是从零设计的实盘执行系统。**大纲只锁方向，实现在 kickoff 从零设计。**

### 5.1 不可谈判的八条硬约束（锁定，D-11）

1. 独立券商执行层。
2. 真正强制的 `live_trading_enabled` / `dry_run` / `paper_trading` / `no_live_trade_without_manual_approval`。
3. **每一笔真实订单人工审批**（区别于 Phase 2 的信封自动批）。
4. 仓位、单笔、日亏损、总回撤、标的白/黑名单。
5. 全链路审计日志。
6. 紧急 kill switch。
7. 凭证隔离，密码/令牌不进入 LLM 上下文。
8. 小资金、低频、可撤退的上线方案。

### 5.2 方向

- 首个实盘券商 = **Longbridge**（把 1b/2 的模拟 adapter 升级为实盘 adapter：加真凭证 + 逐单人工审批）；单券商、单策略、小资金、低频。
- Futu/Moomoo 期权实盘作为更后的子阶段。

### 5.3 kickoff 时才解的开放问题

- 具体上线资金规模与单笔上限。
- 哪个（哪些）策略够格上实盘（须过满月验收）。
- 逐单人工审批的交互形态（Discord `#审批` 卡片？CLI 确认？双因子？）。
- 凭证存储机制（keychain / vault / 环境隔离）与轮换。
- 灰度与回滚：从多小、跑多久、什么条件下扩大或撤退。

---

## 6. Phase 4 — 期货与多资产（方向大纲，延后）

- **硬门槛**：Phase 3 股票/期权实盘链路已证明稳定（D-12）。未达门槛不启动。
- 方向：IBKR 做期货数据/执行评估（TWS API）。
- 现在不做任何实现设计。
- kickoff 时才解：期货合约/保证金/结算差异、IBKR 权限与实体、与现有 Longbridge/Futu 链路的账户与风控隔离。

---

## 7. 产出物清单

本 spec 定稿后产出：

1. 本文（路线 spec）——`docs/design/2026-07-01-roadmap-phases-0b-4.md`。
2. 完整 TDD 计划（`docs/plans/`，0a 风格）：
   - `2026-07-01-phase-0b-observability-governance.md`
   - `2026-07-01-phase-1a-1-core-digital-employees.md`
   - `2026-07-01-phase-1a-2-advanced-digital-employees.md`
3. 1b / 2 的 spec 即本文 §3 / §4；3 / 4 大纲即本文 §5 / §6。它们进入实现前各自再展开为独立计划。

## 投资与安全声明

本项目是个人研究与自动化辅助系统，不构成投资建议。任何真实资金操作必须经过独立风控、人工审批、小资金验证和可回滚上线流程。
