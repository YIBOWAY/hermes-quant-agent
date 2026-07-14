# Hermes 个性化量化交易 Agent 设计方案

> 状态：修订草案（2026-07-01），已迁移到 `Hermes-quant-agent` 作为后续开发主目录。
> **路线与阶段以 `docs/design/2026-07-01-roadmap-phases-0b-4.md` 的决策台账（D-1…D-30）为准**；本文为背景调研与总设计，个别章节（如 §10 分阶段计划的细节）可能已被台账取代。当前执行状态先看 `docs/README.md`。
> 定位：用本机已安装的 Hermes 编排 `ai-quant-platform`，搭建一个以“数字员工 + 研究助手 + 人工审批交易助理”为核心的个人量化 agent。最终目标是 human-in-loop 半自动实盘，但实盘执行层必须独立设计、独立验收，不能靠打开旧开关实现。
> 安全红线：在实盘执行层完成前，保持 `paper_trading` / `live_trading_enabled=false` / `kill_switch` / 人工审批门。任何策略、agent、cron、MCP 都不得绕过这些边界。

---

## 0. 文档边界与调研方法

本项目后续开发目录为：

- Hermes 编排层：`/Users/sunyibo/programs/Hermes-quant-agent`
- 现有量化平台依赖：`/Users/sunyibo/programs/ai-quant-platform`

本文参考《用 Hermes 做量化交易，OPC 的复利飞轮》(HEXIN, 2026-05-31, 微信公众号)。原文不是技术蓝图，更像一份“OPC + AI Agent 投资工作流复盘”：作者用 Hermes 串起 HindSight、RapidAPI、TradingView MCP、Tavily、长桥模拟仓等工具，重点不是让 LLM 直接交易，而是让 agent 负责信息收集、分析、提醒、复盘和协调。

本方案目标不是照抄文章，而是结合：

- 微信原文全文（Firecrawl 抓取）
- 本机 Hermes CLI 能力（`cron` / `kanban` / `mcp` / `send`）
- 本机 `ai-quant-platform` 源码现状
- 券商官方文档（Longbridge、Futu/Moomoo）
- 业界项目 README（AI Hedge Fund、TradingAgents、FinRobot）

核心原则：Hermes 是编排大脑，不是交易内核；`ai-quant-platform` 是研究、回测、paper 账户和评审池的领域后端；券商执行层必须晚于数字员工和券商级模拟验证。

---

## 1. 参考文章的可迁移点与不可照抄点

### 可迁移

- **Hermes 当编排大脑 + 现成能力当手脚**：文章用 Hermes 编排 KOL 消息监控、TradingView MCP、Tavily 宏观周报、HindSight 长期记忆、长桥模拟仓和 MooMoo 实盘。这套“编排层 + 能力插槽”的思路适用。
- **一人 + 多 Agent 协作**：文章是 1 个碳基 + 多个 AI Agent，核心工具是 Codex + Hermes。用户处境相似：本机 Mac、单人、已安装 Hermes、已有量化平台。
- **宏观周报 prompt**：文章给出“20 年经验全球宏观对冲基金经理”角色 + 严格 workflow（广度数据扫描 -> 逻辑链推演 -> 结构化输出 -> 批判性风控），可改造成第一个只读数字员工。
- **错误日志 / 复盘系统**：文章最值得迁移的不是工具清单，而是“亏损不可怕，亏了什么都没留下才可怕”。每次回撤、错判、策略失效都要形成可检索复盘。
- **认知复利 × 资产复利**：系统不应只追求自动下单，还要沉淀个人交易偏好、失败样本、策略评审和复盘记忆，让 Hermes 逐渐成为“记得你如何做错过”的研究助理。

### 不可照抄

- 文章作者没有自建量化平台，所以依赖 TradingView MCP 做技术面和回测。用户已有回测引擎、因子实验室、期权工具、AI News、paper account 和人工评审池，不该复刻文章工具栈。
- 文章的长桥模拟仓是单层模拟。本方案保留平台内置 paper account 作为快速内环，再引入券商级模拟作为实盘预演外环。
- HindSight 不需要第一天接入。Hermes 本机已有记忆和项目上下文机制，先用 Hermes 自带 memory + 本项目结构化日志跑通，再考虑外部记忆服务。
- 文章里的“模拟满 1 个月”不能只当时间门。必须补充回撤、拒单、滑点、审批延迟、复盘完整性、越权检查等验收指标。

---

## 2. 业界个人量化 Agent 的共识

| 项目 | 编排 | 回测 | 实盘边界 |
|---|---|---|---|
| AI Hedge Fund (virattt/ai-hedge-fund) | 自研 Python，多投资人格 agent + Risk Manager + Portfolio Manager | 有 `backtester.py` | 明确不实际下单，偏研究 |
| TradingAgents (TauricResearch/TradingAgents) | LangGraph，分析师 -> 看多/看空辩论 -> Trader -> Risk -> PM | 有，且强调 LLM 决策不可完全复现 | 模拟撮合，非真实券商 |
| FinRobot (AI4Finance-Foundation/FinRobot) | AI Agents / Financial LLM Algos / LLMOps / 多源数据 | 策略 notebook | 主要是数据和研究平台 |
| quant-trade (Hermes 社区项目) | Hermes + tool/skill + 手动确认工作流 | 自研回测和因子库 | crypto 有执行示例，股票区仍强调 signal-only / 人工确认 |

横向共识：

1. 角色分层是通用范式：研究/分析 -> 辩论/反方 -> 信号 -> 风控 -> 组合决策 -> 审批。
2. 主流开源项目对实盘非常保守，通常停在研究、模拟、测试网或强人工确认。
3. LLM 决策存在不可复现性，所以要把结构化数据、固定指标、审计日志和人工 gate 放在提示词之前。
4. 真正的系统价值不在“AI 替你拍脑袋”，而在持续沉淀研究流程、复盘和失败案例。

---

## 3. `ai-quant-platform` 当前真实状态

最关键的判断：平台“不能实盘”的原因不是安全开关没打开，而是代码里根本没有券商执行层。

已核验的事实：

- Futu 只使用 `OpenQuoteContext` 做行情，没有 `unlock_trade`、`place_order`、`OpenSecTradeContext` 或真实 trade context。
- `kill_switch` 已在 risk engine、account service、strategy sleeve、API/CLI 层多处强制。
- `dry_run` / `paper_trading` / `live_trading_enabled` / `no_live_trade_without_manual_approval` 主要是配置和展示字段，进入实盘前必须变成真实 enforcement。
- 当前 API 层没有 Authorization / Bearer / API key 依赖。
- `.mcp.json` 只有开发用 codegraph，没有业务 MCP server。
- `quant-system` 不一定在全局 PATH 内；当前可用调用方式是：

```bash
/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/quant-system doctor
```

已有可编排接口面：

- CLI：`doctor`、`config`、`data`、`factor`、`backtest`、`experiment`、`paper`、`agent`、`prediction-market`、`options`、`serve`
- FastAPI：16 个 router，统一 `/api` 前缀
- AI 评审池：候选池 pending -> 人工 review -> 只写锁文件，不自动生效。D-19 之后 Scene-B 入口为 `agent propose-factor --source-file <path>`；平台侧 `POST /agent/tasks`/LLM 表单只作历史能力，不再作为 Hermes 因子生成主入口。
- async backtest jobs + run metadata/index
- persistent paper account + strategy sleeves + account-level kill switch
- AI News 是只读 AI HOT 集成，不能连接交易链路

含义：走向半自动实盘 = 从零新建券商执行层、真实风控 enforcement、API 鉴权、审计日志和人工审批工作流。这是好事，安全边界可以重新做对。

---

## 4. 三层模拟保真度

| 层 | 是什么 | 撮合 | 做空/期权 | 多账户 | 用途 |
|---|---|---|---|---|---|
| 1. 平台内置 paper account | `ai-quant-platform` 进程内账户模型，`account.json` 落盘 | 自研 `paper_broker.py` | 当前不支持做空/期权执行 | 单一 default，带 strategy sleeves | 研究级内环：信号/因子快速验证、零外部依赖 |
| 2. Longbridge 券商模拟仓 | 券商服务器端 paper account | Longbridge 模拟撮合，按真实市场 bid/ask 匹配 | 支持美股做空、美股期权等，以账户权限为准 | 可多账户并行 | 实盘预演外环：贴近真实券商行为，跑满月 |
| 3. 双券商实盘 | Longbridge + Futu/Moomoo 真实资金账户 | 真实成交 | 以账户和实体权限为准 | 可多账户 | Phase 3 之后，human-in-loop 半自动实盘 |

为什么两层模拟都要：

1. 平台内置 paper account 适合快速内环，成本低、可控、可测试。
2. 券商级模拟更接近真实订单生命周期、权限、拒单、撮合、订单查询和账户状态。
3. 真正进入实盘前，策略必须经过券商级模拟满月，并通过验收指标，而不是只通过回测。

---

## 5. 券商 / 数据源选型

| 维度 | Longbridge | Futu/Moomoo | IBKR |
|---|---|---|---|
| 美股股票/期权实盘 | 支持 | 支持，期权生态更强 | 支持 |
| 券商级模拟盘 | 支持，官方文档确认 paper account 支持港/美股票、ETF、港股窝轮、美股期权，美股支持做空 | 支持 paper trading，OpenD + SDK；paper 不需 unlock trade | 支持 |
| 期货 | 当前 Longbridge OpenAPI 文档未作为主线能力 | 视实体：Moomoo US / Futu HK / Moomoo SG/MY 权限不同 | 强项 |
| Python SDK | 使用 `longbridge`；旧 `longport` 已 deprecated | `futu-api`，本机已用于行情 | TWS API |
| 适合本方案 | Phase 1b/2 券商模拟，Phase 3 备选实盘 | 当前行情，Phase 3 实盘/期权备选 | Phase 4 期货数据/执行评估 |

修订后的决策：

- Longbridge：先做券商级模拟 adapter，再评估实盘。
- Futu/Moomoo：保持行情与期权数据优势；实盘执行等 Phase 3 单独设计。
- IBKR：期货相关延后到 Phase 4，不进入当前 MVP。

---

## 6. Hermes 集成面

本机 Hermes 可用，核心能力：

- `hermes cron create <schedule> [prompt] --workdir <abs path>`：定时数字员工
- `--script` + `--no-agent`：脚本型 watchdog；空 stdout = 静默
- `hermes send --to discord "..."`：无需 LLM 的投递通道（渠道决策见下）
- `hermes kanban swarm`：并行 worker -> verifier -> synthesizer
- `hermes mcp add` / `hermes mcp serve`：消费或暴露 MCP
- Hermes memory / skills / hooks：沉淀偏好、复盘和可复用流程

注意：Phase 0 中不要假设裸 `quant-system` 在 PATH。脚本和 cron 应使用绝对路径：

```bash
cd /Users/sunyibo/programs/ai-quant-platform
/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/quant-system doctor
```

### 6.1 通知渠道决策：local 默认，Discord 可选外发

已核验本机 Hermes 源码（`hermes_cli/platforms.py` / `send_cmd.py`）真实支持的平台，结论如下：

| 渠道 | Hermes 原生支持 | 结论 |
|---|---|---|
| **Discord** | 一等公民（与 telegram/slack/signal 同级完整实现） | **首选外部渠道**：用户常用、bot 生态成熟、支持频道分流（宏观/期权/异动分开）、代码块/表格/图表友好 |
| 微信（个人 weixin） | 源码有条目，但个人微信无官方 bot API，靠非官方 hack，极易封号 | 不用（封号风险，不适合挂量化通知） |
| 企业微信 WeCom | 有 `wecom` / `wecom_callback`（官方机器人 webhook） | 备选（需用户有企业微信） |
| 飞书 Feishu / 钉钉 DingTalk | 官方支持 | 备选（用户未使用） |
| QQ | 源码零命中 | 放弃（原生不支持，自写 adapter 不值当） |

**决策**：自动化通知默认走 **local**，形成可审计收据且不依赖外部渠道。Discord 是首选
外部渠道，但只有人工显式配置并启用后才发送；完整 9H 运行验收没有实际外发 Discord。
个人微信因封号风险排除；QQ 因 Hermes 不支持排除。若用户后续有企业微信，可加
`wecom` 作为第二外部渠道。

Discord 频道建议分流：`#盘前digest`、`#盘中异动`、`#期权radar`、`#回测结果`、`#复盘`、`#审批`（Phase 2+）。

---

## 7. Hermes 怎么接平台：混合演进

| | A: cron/script 直调 CLI | B: 业务 MCP server 包装 |
|---|---|---|
| 新代码量 | 低 | 中 |
| 上手速度 | 立即 | 需要设计 tool schema |
| 权限边界 | 较大，取决于脚本和 workdir | 较小，只暴露精选 tool |
| 适合 | 只读扫描、digest、报告、复盘草稿 | 下单、rebalance、审批、券商 adapter |
| 风险等级 | 低到中 | 中到高 |

决策：

- Phase 0/1a 用 cron/script 快速跑通只读数字员工。
- Phase 1b 起，凡是涉及订单、账户、rebalance、券商模拟执行的能力，都进入 MCP/server-side adapter，而不是让 Hermes 自由 shell 调用。
- 高风险 tool 必须内置审批、kill_switch、幂等、审计和最小权限。

---

## 8. 系统定位图

```text
Hermes-quant-agent
  Hermes 编排大脑：cron 数字员工 + memory + kanban 自主 loop + 后续 MCP
      |
      | Phase 0/1a: CLI/script, read-only
      v
ai-quant-platform
  研究/数据/回测/因子/期权/AI News/评审池/paper account
      |
      | Phase 1b/2: execution adapter, audited
      v
Longbridge paper account
  券商级模拟满月 + 订单生命周期 + 错误日志
      |
      | Phase 3: independent live-trading design, human-in-loop
      v
Longbridge + Futu/Moomoo live accounts
```

---

## 9. 典型场景（Phase 1 验收目标）

以下两个用户高频用例，作为 Phase 1 的具体、可验收的交付目标。它们定义了"数字员工 + 按需研究助手"到底要做到什么程度。

### 场景 A：晚间盯盘看门狗——"不错过美股机会"

用户需求：每天晚上（美股盘时段）自动盯盘，有机会才提醒，不刷屏。

- 触发：`hermes cron`，按美股交易时段调度（北京时间约 21:30–次日 04:00，夏令时/冬令时各差 1h，需按季节切换 cron）。
- 频率：盘中每 N 分钟（默认 30 min，可调）跑一次扫描。
- 数据源：复用 `ai-quant-platform` 本地能力——期权 radar 扫描、因子/动量信号、异动检测。**不依赖外部 API**（相比文章作者用 RapidAPI 的方案更自主）。
- 投递：`[SILENT]` 模式——无信号时静默，有信号才投递到显式 target；默认 local，
  人工启用 Discord 后可投 `#盘中异动`。
- 输出示例：`NVDA 触发动量信号 + 期权 IV 分位 85%，详情…`。

验收标准：
- 盘时段稳定运行，无信号不打扰。
- 每条提醒带：标的、触发的信号类型、关键指标、数据时间戳、平台链接/run id。
- 全程 read-only，不触碰交易链路。
- 需用户在 Phase 1 前确认：盯盘频率（15/30/60 min？）、关注信号（动量/期权/财报？）、时段（盘前/盘中/盘后）。

### 场景 B：论文因子/策略复现回测——"看到好因子发给它就能跑"

用户需求：把论文里的因子/策略公式发给 Hermes，自动复现并在真实历史数据上回测。

流程（**半自动，human-in-loop**）：
1. 用户把论文 PDF/链接/因子公式发进 Discord 或直接对 Hermes 说。
2. Hermes 在会话内把论文翻译成因子定义与 Python 源码，先让用户确认公式和字段语义（Gate 1）。
3. Hermes 将确认后的源码写入临时文件，调用平台 `agent propose-factor --source-file <path>`，只生成 `.candidate` 候选。
4. 用户审候选源码并手动 Gate 2 approve（必须显式提供
   `candidate-id + expected-digest + expected-status=pending + note`；禁止在
   approve 路径 refetch/替换观测值），Hermes 再调用
   `experiment run-config --provider futu --candidate-id <id>
   --expected-digest <sha256>` 做
   一次性真实历史回测（digest 在 compile 前再校验）；HQA 只接受 Futu/Tiingo，
   并复核唯一实验命名空间、persisted config、exact summary/run 和完整报告。
5. 结果（夏普/回撤/IC/holdout/试验次数）→ 评审池 pending + 投递到显式通知 target；
   默认 local，人工启用 Discord 后可投 `#回测结果`。
6. 用户满意后先运行一次 `backtest --final` 并取得绑定 exact
   candidate/digest/run 的 content-addressed receipt，再通过 HQA 调用
   `factor_repro_cli promote --candidate-id --expected-digest
   --final-backtest-receipt --base-commit`，
   在隔离 managed review worktree 生成四字段
   `{promotion_id, worktree, patch, manifest}` scoped patch；人工 `git diff` +
   commit 是 Gate 3，之后才能进入 paper sleeve。HQA 与 platform status 会共同
   复核 actual 三文件、dirty set、patch 与 provenance；timeout 保持 outcome unknown，
   只允许按恢复证据核查。系统永不自动 commit。

关键优势：平台提供候选池、评审池、回测引擎和转正落代码机制；LLM 生成职责收归 Hermes，会话外的平台后端保持确定性接缝。

验收标准：
- 能把一个中等复杂度的论文因子跑通到回测出报告。
- 因子翻译步骤有人工确认 gate，不允许 LLM 理解直接进回测。
- 结果落评审池，不自动生效。
- 复杂因子若 LLM 无法可靠翻译，明确报告"需人工补充定义"，而不是猜。

---

## 10. 分阶段计划

### Phase 0a - 项目接线与只读数字员工

目标：验证 Hermes 能稳定编排本机平台，但不触碰交易链路。

任务：

1. 在 `Hermes-quant-agent` 建脚本目录和运行日志目录。
2. 用绝对路径调用 `ai-quant-platform/ai-quant/bin/quant-system doctor`。
3. 建第一个 `[SILENT]` watchdog：只有异常或重要信号才投递。
4. 建每日盘前 digest：AI News + 宏观日历 + 期权 radar 摘要 + 当前安全状态。
5. 所有输出落结构化日志，供 Hermes memory / 后续复盘读取。

验收：

- 不触发 `paper account` mutating API。
- 不触发 backtest / rebalance / strategy sleeves execution。
- 不访问真实交易 API。
- 输出有时间戳、数据来源、风险提示和安全状态。

### Phase 0b - 最小安全底座

目标：为后续 HTTP/API/MCP 接入做安全地基。

任务：

1. 给 `ai-quant-platform` API 增加最小鉴权方案设计。
2. 明确本地-only、Discord、webhook、MCP 各自的权限边界。
3. 把“错误日志 / 复盘日志”提前设计为一等对象。
4. 定义策略进入券商模拟的验收门。

验收：

- 只读数字员工不需要鉴权即可通过 CLI 安全运行。
- 任何外部入口访问 HTTP API 前必须有鉴权。
- 复盘日志格式固定，至少包含：事件、判断、依据、结果、失误环节、下次规则。

### Phase 1a - 数字员工 MVP

目标：让 Hermes 成为真正有用的个人研究助理。

数字员工：

1. 盘前宏观/新闻 digest。
2. AI HOT / 个股 / KOL 异动提醒。
3. 期权 radar 扫描摘要。
4. 因子/回测任务建议，但只产出候选，不自动执行高风险操作。
5. 每周复盘报告：本周信号、错判、空过机会、风险事件。

注意：这里仍然是 read-only / proposal-only。

### Phase 1b - Longbridge 券商模拟 adapter 设计与接入

目标：把券商级模拟作为执行外环，但仍不进入实盘。

任务：

1. 使用 `longbridge` SDK，不再使用 deprecated `longport` 包。
2. 建 Longbridge paper account adapter：账户、持仓、订单、撤单、订单状态查询。
3. 设计订单幂等键、状态机、错误恢复和审计日志。
4. 接入前先做 read-only account/status probe。
5. 接入后只允许人工批准的模拟订单进入 adapter。

验收：

- 无真实资金权限。
- 订单状态可恢复、可查询、可审计。
- 所有失败路径写入错误日志。
- Hermes 只能提出/转交候选，不能绕过审批直接执行。

### Phase 2 - 策略闭环 + 券商级模拟满月

目标：研究 -> 信号 -> 风控 -> 候选 -> 人工审批 -> Longbridge 模拟执行 -> 复盘。

满月不是只看时间，至少需要记录：

- 模拟运行天数 >= 30 天
- 最大回撤
- 日亏损和周亏损
- 拒单率 / 撤单率 / 部分成交情况
- 预期价格 vs 实际模拟成交价格
- 人工审批延迟
- 策略是否发生越权行为
- 每次回撤是否有复盘日志

只有通过满月验收的策略，才允许进入 Phase 3 设计讨论。

### Phase 3 - 半自动实盘（独立安全设计阶段）

Phase 3 不是“把模拟改成 real”。它是一个从零设计的实盘执行系统。

必须包含：

1. 独立券商执行层。
2. 真正强制的 `live_trading_enabled`、`dry_run`、`paper_trading`、`no_live_trade_without_manual_approval`。
3. 每一笔真实订单的人工审批。
4. 仓位、单笔、日亏损、总回撤、标的白名单/黑名单。
5. 全链路审计日志。
6. 紧急 kill switch。
7. 凭证隔离，密码/令牌不进入 LLM 上下文。
8. 小资金、低频、可撤退的上线方案。

### Phase 4 - 期货与多资产扩展

IBKR 和期货相关能力延后处理。只有当股票/期权链路稳定后，再评估期货数据与执行。

---

## 11. 当前执行入口

本文是原始总设计，不再维护逐日实现进度。Phase 0a 到 1a-3、D-25 的计划与
实现记录已迁入 roadmap 和对应 implementation plan。

现在先读 `docs/README.md`。Phase 1a-4 v2 的 Slice 9A-9H 已全部完成：
`docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md` 是完成顺序记录，
`docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md` 是当前交付与
运行验收记录。当前没有选定下一 slice；平台仓库的 2026-07-08 前端计划只保留
Slice 0-8 实现记录与未来 UI backlog，不得把本节旧顺序或 backlog 当作待执行指令。

第一阶段的成功标准不是赚钱，而是：

- 每天稳定运行。
- 不打扰，只有重要信息才通知。
- 不触碰交易链路。
- 每次风险/错误都有记录。
- Hermes 开始沉淀你的研究偏好和复盘模式。

---

## 12. 已迁移的早期开放问题

这些早期问题已经进入 roadmap 决策台账和后续 plan，不在本文重复维护：通知与
Discord 见 D-7/D-25/D-30，复盘双格式见 D-2/D-3，CLI/MCP/鉴权边界见 D-9/D-22，
Phase 1a-4 v2 完成事实见 D-26/D-29/D-30。尚未定案的运营参数应在未来单独选定的
slice kickoff 时记录，不在 `AGENTS.md` 或本总设计中追加会话流水账。

---

## 投资与安全声明

本项目是个人研究与自动化辅助系统，不构成投资建议。任何真实资金操作必须经过独立风控、人工审批、小资金验证和可回滚上线流程。
