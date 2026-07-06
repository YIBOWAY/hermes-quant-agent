# Hermes-quant-agent 后续路线设计 spec（Phase 0b → 4）

> 状态：定稿（2026-07-01），经 brainstorming + grilling 逐项对齐。
> 上游：`docs/design/hermes_quant_agent_plan.md`（总设计）。前置：Phase 0a 已交付（只读数字员工，见 `docs/plans/2026-07-01-phase-0a-readonly-digital-employee.md`）。
> 本文定位：把 0a 之后的全部阶段一次性对齐方向。**分层规划**——近期阶段给完整 TDD 计划，中期给设计 spec，远期给方向大纲。
> 安全红线（贯穿全程，继承总设计）：实盘执行层完成前，保持 `paper_trading` / `live_trading_enabled=false` / `kill_switch` / 人工审批门。任何策略、agent、cron、MCP 都不得绕过。
> **单一事实源**：本文决策台账（D-1…D-24）是 Hermes-quant-agent 与 `ai-quant-platform` 的唯一活跃路线图；平台 Phase 15 只保留素材价值。

---

## 0. 分层规划原则

后续阶段成熟度差异极大，规划详细度必须与确定性匹配，否则为远期写下的细节几乎必然返工（违反 YAGNI）。

| 层 | 阶段 | 产出形式 | 文档 |
|---|---|---|---|
| 近 | 0b, 1a-0, 1a-1, 1a-2, 1a-3, 工作台 | 完整 TDD 实现计划（可逐步执行） | `docs/plans/*.md` |
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
| D-13 | （2026-07-02）插入 **Phase 1a-0 平台接线包**：修复两个平台侧死胡同（`experiment run-config` 不透传 provider；已批准候选因子无法进入 FactorRegistry）+ 运维前提（OpenD/keys）+ 扫描分布收集 |
| D-14 | （2026-07-02，D-19 已修订 LLM 部分）真数据优先策略：真实运行用 `--provider futu`（盘中）/ `tiingo`（回测）；`sample`/`stub` 仅限单元测试；降级运行必须标注 `DEGRADED`，绝不静默假装真数据 |
| D-15 | （2026-07-02）场景 A 信号阈值不拍脑袋：看门狗默认 **collect 模式**（不报警只记录分布）；阈值来自 ≥4 个交易日的 futu 扫描分布复盘（建议 p90），决策落 0b 复盘库后才进 alert 模式 |
| D-16 | （2026-07-03）**闭环愿景定型：「两次点击的人在环」而非全自动**。论文→翻译（👤Gate1 确认公式）→propose 生成候选代码（只落 `.candidate`，绝不直写 src/）→👤Gate2 审代码 approve→tiingo 真实数据回测（自动）→结果落评审池+Discord→👤前端点击分配 sleeve（Phase 2 信封领地）。**无需热更新**：平台 registry 每次 run 请求重建，approved 候选按次加载，获批即可见，服务不重启。`promotion.py` 的 AST 白名单是纵深防御非沙箱，人工代码审查是唯一真安全闸。**（同日修订：核验发现「点击分配 sleeve」在批准态因子上不可行——sleeve 信号链路对候选 factor_id 直接 KeyError；分配资金前需经 D-20 转正门，闭环实为三道人工门）** |
| D-17 | （2026-07-03）**Hermes 工作台（平台前端）**：否决删除因子实验室/智能体工作室，改为**改造吞并**为单页面四区工作台（智能体工作室恰是 Gate2 审批 UI，不可丢）；吸收平台 phase_15 P4+P5；详见 §2.7；远程访问前置 1b 鉴权 |
| D-18 | （2026-07-03）**平台迭代治理：从产品路线驱动改为 Hermes 需求拉动**。Hermes-quant-agent 为主项目（COO），平台降级为领域后端。phase_15 处置：P0 永保持；P1 provenance 最小切片提前（信号可信前提）；P4/P5 改造为工作台（D-17）；P2/P3 推迟到 Phase 2 前；独立功能增长停止 |
| D-19 | （2026-07-03）**LLM 职责收归 Hermes，平台去 LLM 化**（取代 D-14 的 `--llm openai` 部分）：Scene-B 因子代码生成在 Hermes 会话内完成（Codex 订阅已覆盖，零额外 API 费；订阅端点不能也不应当作平台后端的裸 LLM API）。平台侧新增确定性接缝 `agent propose-factor --source-file <path>`（内部用固定内容 LLMClient 注入 `AgentRunner`，复用全部 task-id/audit/candidate-pool 链）；`QS_OPENAI_API_KEY` 不再需要；`stub` 仍限单元测试；proposal/backtest 段仍保留 Gate1+Gate2，端到端晋级链路见 D-20 三道门；`QS_TIINGO_API_TOKEN`（数据钥匙，非 LLM）仍必需 |
| D-20 | （2026-07-03）**闭环第三道门「转正 promote-to-code」**：候选因子回测满意后，`agent promote-candidate`（确定性、无 LLM）把**已批准**候选源码正式写入 `src/quant_system/factors/library/promoted/<factor_id>.py` + 重生成 `promoted/__init__.py` 注册表 + 生成测试脚手架，**只产工作区 diff、绝不自动 commit**；人工 `git diff` 审查并 commit 即 Gate 3。merge 后因子成为一等公民（前端目录/回测/sleeve 全可用；registry 每次请求重建，获批即可见，无需热更新——D-16 已证伪热更新需求）。**sleeve 信号链路永不 exec `.candidate` 文件**：受限 exec 只限一次性回测（`run-config --include-approved-candidates`），常驻交易路径只允许代码化、注册化、有测试的正式因子（与平台 phase_15「不做前端自由公式因子编辑器」纪律同源）。已核验断点：`paper_strategy_signal_service.py:188-192` 对候选 factor_id 直接 `KeyError`（`registry.py:31-36`）——转正是让新因子获得纸面资金的唯一路径 |
| D-21 | （2026-07-03）**反过拟合三纪律硬编码进流程**（参考文章「回测漂亮、模拟仓两周 -12%」翻车模式的系统级对策；当"提想法→回测报告"只要 10 分钟，人会天然迭代到回测好看为止）：① 试验计数——`hqa-factor-repro backtest` 每次运行按 factor_id 落 `logs/factor_trials.jsonl`，≥3 次显式告警「回测结果可信度随迭代次数下降」；② holdout——`backtest` 默认截断最近 6 个月数据，只有转正前的一次 `--final` 跑全窗口，holdout 段明显衰减 = 回炉；③ 满月门槛——`hqa-gate` 增加 `paper_days_completed >= 30` 必过项：回测 + holdout 通过 ≠ 晋级，纸面 sleeve 跑满月才有资格谈券商模拟 |
| D-22 | （2026-07-03）**HQA↔平台契约升级为 `--json`**：HQA 消费的平台 CLI 命令（`agent propose-factor` / `agent review` / `experiment run-config` / `doctor`）增加 `--json` 单行 JSON 输出；HQA 侧 JSON 解析优先、既有正则兜底（当前 `factor_repro.py` 靠 `candidate_id=(\S+)` 正则抓 stdout，平台输出格式一变即静默断裂）。业务 MCP server 仍按 D-9 推迟到 1b——只有订单/审批类高风险能力才值得 MCP 的 schema+鉴权成本，研究链路 CLI+JSON 足够 |
| D-23 | （2026-07-03）**注册表构建收敛单一工厂**：新增 `build_factor_registry(*, include_promoted=True, include_approved_candidates=False, candidates_dir=...)`，替换散落的 `build_default_factor_registry()` 调用点（已核验：`api/routes/factors.py:33`、`factors/lab.py:53`、`paper_strategy_signal_service.py:188`、`cli.py` run-config 分支）。`/factors` 目录可选返回已批准候选并带 `origin=builtin|promoted|candidate` 标记（修复断点：批准后的因子前端目录不可见）；转正因子经 `library/promoted/` 包进默认注册表（配合 D-20 修复断点：sleeve 无法使用新因子）。sleeve 信号服务硬编码 `include_approved_candidates=False` |
| D-24 | （2026-07-03）**文档单一事实源，消除上下文污染**：本 roadmap + 决策台账为两仓库唯一活跃路线图（D-18 的执行细则）。平台 `docs/phases/phase_11~14*` 移入 `docs/archive/phases/`；`phase_15_iteration_roadmap.md` 顶部标注「迭代治理已被 HQA D-18 取代，本文仅存 P0-P5 素材价值」；两仓库 AGENTS.md/CLAUDE.md 各加一行互指（平台=领域后端，活跃路线图在 HQA）。动机即参考文章的教训：过时文档是 agent 会话的上下文污染源 |

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

## 2. Phase 1a — 数字员工 MVP（→ 完整 TDD 计划，拆 1a-0 / 1a-1 / 1a-2 / 1a-3）

目标：让 Hermes 成为真正有用的个人研究助理。全部 read-only / proposal-only。

### 2.0 Phase 1a-0 — 平台接线包（D-13/D-14/D-15，2026-07-02 追加）

前置于 1a-1：把数字员工从合成数据（sample/stub）切换到真实数据面。详见 `docs/plans/2026-07-02-phase-1a-0-platform-wiring.md`：

1. **平台侧（ai-quant-platform 仓库）**：`experiment run-config` 透传 `--provider`（seam 已在 `run_experiment(provider=...)`，纯 CLI 接线）；新增 `agent/promotion.py` —— `SafetyGate` 的第一个消费者，把**人工已批准**的候选因子加载进 `FactorRegistry`（`--include-approved-candidates`），从而闭合场景 B 链路。
2. **Hermes 侧**：`hqa-options-collect.sh` 包装 `options daily-task --provider futu`，每交易日收集真实扫描产物。
3. **运维前提（人工 gate）**：`QS_TIINGO_API_TOKEN` 入平台 `.env`（凭证不过 LLM；`QS_OPENAI_API_KEY` 已按 D-19 取消）；OpenD 盘时段运行 + Mac 不睡眠；平台本身是按需 CLI，**不需常驻**。
4. **阈值复盘（D-15）**：≥4 交易日后看 `global_score`/`iv_rank` 分布，定 `--min-score`/`--min-iv-rank`，决策写入 0b 复盘库。

### 2.1 员工清单与拆分（D-5）

**1a-1 核心**（先落地、依赖最少）：
1. **盘前 digest 升级**：在 0a 基础上加宏观日历/新闻摘要（AI HOT 源）、当日关注标的、安全状态。
2. **场景 A 信号看门狗**：盘中每 N 分钟扫描**交易信号**（动量 / 期权 IV 分位 / 异动），`[SILENT]` 无信号不打扰，有信号推 Discord `#盘中异动`。**注意区别于 0a 的安全不变量看门狗**——那个看 `safety.*`，这个看市场信号。
3. **周复盘报告**：读 0b 复盘库 + 0a run-log，汇总本周信号/错判/空过机会/风险事件，推 `#复盘`。

**1a-2 进阶**：
4. **期权 radar 摘要**：`options daily-scan` 结果的结构化摘要 + 分位提醒，推 `#期权radar`。
5. **AI HOT / 个股异动提醒**：独立公开 REST API（D-6），异动才推。
6. **场景 B 论文因子复现**：人工把因子/公式发来 → Hermes 会话生成源码 → 平台 `agent propose-factor --source-file <path>` 确定性摄入候选 → **人工确认翻译/审码（关键 gate）** → `experiment run-config --provider tiingo --include-approved-candidates` 在真实历史数据回测 → 结果落评审池 + 推 `#回测结果`。是否进入 paper sleeve 由 1a-3 的 D-20 转正门决定。

### 2.2 数据自主性（D-6，D-14 修订）

- 行情 / 因子 / 期权 / 回测：全走平台本地 CLI（`/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/quant-system`，`cwd=平台目录`），不依赖外部行情 API。**真实运行一律 `--provider futu`（盘中链）/ `tiingo`（EOD 回测）；`sample` 仅限单元测试（D-14）。LLM 生成全部在 Hermes 会话内完成，平台只收确定性产物（D-19）。**
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

### 2.6 Phase 1a-3 — 闭环补全包（D-20/D-21/D-22/D-23，2026-07-03 追加；排在 1a-2 之后）

1a-2 交付后闭环仍有两个已核验断点：批准候选在前端因子目录不可见（`api/routes/factors.py:33` 只构建默认注册表）；批准候选无法进入 sleeve 纸面模拟（`paper_strategy_signal_service.py:188-192` 对候选 factor_id 直接 `KeyError`）。本包补全「回测报告 → 分配纸面资金」的最后一段，并落反过拟合纪律：

1. **平台侧**：D-23 注册表工厂收敛 + `/factors` 展示候选（带 `origin` 标记）；D-20 `agent promote-candidate` 转正命令（只产 diff，人工 commit = Gate 3）；D-22 关键 CLI 加 `--json`。
2. **Hermes 侧**：`factor_repro_cli` 接 `--json` 解析（正则兜底）；D-21 试验计数 + holdout 默认截断；`hqa-gate` 加满月必过项。
3. **验收**：一篇论文从 Hermes 会话出发，经 Gate1（确认公式）→ Gate2（approve 代码）→ 回测报告 → Gate3（审 diff 转正）→ 前端可见 → 创建 sleeve 分配 cash 跑纸面模拟，全程零手写代码、三道人工门皆不可绕过；`hqa-factor-repro backtest` 同一 factor_id 第 3 次运行输出过拟合告警；holdout 段默认不参与迭代回测。

### 2.7 Hermes 工作台（平台前端，D-17；排在 1a-3 之后、1b 之前）

平台前端（Next.js 15，`src/frontend`）的因子实验室与智能体工作室两页**改造吞并**为单一「Hermes 工作台」页面（建议作为首页），四区：

| 区 | 内容 | 数据源（大都现成） |
|---|---|---|
| ① 安全状态条 | safety 四开关 + gateway/OpenD/数据新鲜度 | `/api/health` + doctor |
| ② 数字员工时间线 | digest、信号、告警、采集、回测完成——Hermes 全部工作过程/记录 | Hermes `logs/*.jsonl` + `review/entries.jsonl` + 平台 `/api/runs/recent`（需新增一个只读聚合端点 `/api/hermes/timeline`，读取路径可配置、只读） |
| ③ 待办审批队列 | 待 approve 因子候选（含源码 diff 预览）+ 待转正因子（D-20，链接到 diff）+ 待补判断字段的复盘 draft | `/api/agent/candidates?status=pending` + 0b 复盘库 —— **吞并智能体工作室（Gate2 审批 UI：候选池列表/源码纯文本预览/审计时间线/批准对话框全部复用现有组件）** |
| ④ 产出货架 | 回测报告（含试验计数标注，D-21）、期权 radar 摘要、周复盘归档、sleeve 状态卡 | 现有 runs/reports/sleeves 端点 |

改造要点（2026-07-03 核验补充）：

- **agent-studio 有两块 D-19 之后的僵尸 UI 需在吞并时清除**：页面顶部 LLM provider/model/API-key 状态徽章（平台已去 LLM 化，展示 stub 只会误导）；`AgentTaskForm` 中调 `POST /api/agent/tasks` 的「运行 agent 任务」表单（已被 `--source-file` 流程取代）。审批对话框（approve 仅写 `approved.lock`）是要保留的核心。
- **factor-lab 页面本体只有 73 行薄壳**，真正有价值的是 `FactorLabDashboard` 组件（IC/分位数图）——按原案降级为 run 详情页（从时间线点入），组件保留，路由从一级导航摘除。
- **导航同步收敛**：`Sidebar.tsx` 摘除 factor-lab、agent-studio 两项；现有 464 行 Dashboard 首页与工作台合并（它已拉取 factors/paper runs/candidates/recent runs，正是工作台骨架）。
- 此页同时是 Phase 2 满月运营面板底座（phase_15 P3 届时并入时间线）。

**安全前置**：平台 API 零鉴权（`apiClient.ts` 指向 `127.0.0.1:8765`），工作台仅限 localhost；一旦需要远程点 approve，1b 鉴权必须先行。进入实现前单独走 brainstorming→plan 流程。

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
   - `2026-07-02-phase-1a-0-platform-wiring.md`（D-13 追加；任务主体在 ai-quant-platform 仓库）
   - `2026-07-01-phase-1a-1-core-digital-employees.md`（已按 D-14/D-15 修订：futu 默认、扫描产物信号语义、collect 模式）
   - `2026-07-01-phase-1a-2-advanced-digital-employees.md`（已按 D-19 修订：Hermes 会话生成源码、平台 `--source-file` 接缝、run-config 真数据回测；局部链路为 Gate1+Gate2，完整闭环三道门见 1a-3）
   - `2026-07-03-phase-1a-3-close-the-loop.md`（D-20/D-21/D-22/D-23 闭环补全包；§2.6；任务横跨两仓库）
   - Hermes 工作台（D-17，§2.7）：排在 1a-3 之后、1b 之前；进入实现前单独走 brainstorming→plan 流程产出独立计划（平台仓库 Next.js 前端 + 一个只读聚合端点）。
3. 1b / 2 的 spec 即本文 §3 / §4；3 / 4 大纲即本文 §5 / §6。它们进入实现前各自再展开为独立计划。

## 投资与安全声明

本项目是个人研究与自动化辅助系统，不构成投资建议。任何真实资金操作必须经过独立风控、人工审批、小资金验证和可回滚上线流程。
