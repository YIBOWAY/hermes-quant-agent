# Hermes 全阶段落地后 · 日常使用全景推演

> **状态：推演笔记（2026-07-02 初稿，2026-07-03 按 D-16~D-24 修订），不代表最终形态，也不代表一定要实现成这样。**
> 本文是对"如果所有阶段都按当前设计落地，用户日常会如何与 Hermes 量化 agent 协作"的一次想象实验。它不是 spec，不是承诺，不约束后续设计决策。它存在的意义是：让团队（目前就是你）在埋头实现具体模块时，有一个"这玩意儿最终是给人怎么用的"的直觉锚点。
> 随着项目演进，本文可能与实际路线产生偏差——届时以 `docs/design/hermes_quant_agent_plan.md` 和 `docs/design/2026-07-01-roadmap-phases-0b-4.md` 为准。

---

## 你的角色

你不再是一个"需要手动盯盘、手动跑回测、手动记复盘"的交易者。你变成了一个**审批者 + 决策者 + 经验沉淀者**。Hermes 是你的 COO（首席运营官），`ai-quant-platform` 是你的研究部门，数字员工是 7×24 值班的分析师团队。

---

## 一天的完整时间线

### 🌅 08:00 北京 — 盘前简报就位

你在 Discord `#盘前digest` 频道收到一条消息：

```
[HQA] Pre-market digest 2026-07-02T00:00:00Z
Safety baseline: NOMINAL (dry_run=true, paper_trading=true, live=false, kill_switch=true)
Options radar (futu): run_date=2026-07-01, universe=100, scanned=100, failed=0, candidates=847
Top AI headlines:
  - [industry] Meta 计划出售 20 亿美元 AI 算力冗余 (TechCrunch)
  - [ai-products] Cloudflare 发布 AI 流量路由新架构 (Cloudflare Blog)
  - [research] DeepMind 新论文：多模态模型在金融时序预测上的突破 (ArXiv)
Scope: read-only research digest. No trading action taken.
```

你花 2 分钟扫一眼。NOMINAL，没有异常。AI 新闻看起来没有直接影响你的持仓的东西。你喝咖啡去了。

**这背后发生了什么：** `hqa.premarket_digest` 在 cron 触发后，调用 `quant-system doctor` 检查安全基线，读取 23:00 collect 任务留下的 Futu 期权雷达 meta artifact，调 AI HOT API 拉取精选头条，组装成结构化简报，推送到 Discord。默认不现场重跑全量 Futu scan，因此可以快速完成；若 artifact 缺失或新闻源不可用，会明确标注 DEGRADED。

---

### 🕘 白天 — 你该干嘛干嘛

信号看门狗在后台沉默运行。每 30 分钟一次：读取当天 collect 任务已经落盘的 `data/options_scans/<date>.jsonl`，调 `factor refresh-lab --provider futu` 刷新因子数据，读扫描产物，算分布。显式 `--scan` 只作为人工全链路诊断，不是 cron 默认路径。

**没有信号的时候：** Discord 静默。什么都不推。但 JSONL 日志一直在写——每条记录的 `score_summary` 里存着当次扫描的 p50/p90/max 分布。

AI HOT 异动看门狗每 2 小时检查一次 AI 行业新闻，score < 70 的直接忽略，超过阈值的才推 `#盘中异动`。大多数时候它也是沉默的。

**这是关键设计：不刷屏。只有值得关注的事才占用你的注意力。**

---

### 🌙 21:30 — 美股开盘，信号看门狗进入高频模式

盘中每 30 分钟（已从 collect 模式切换到 alert 模式，阈值来自 ≥4 个交易日的 futu 扫描分布复盘），信号看门狗扫描期权链。今晚：

```
[HQA] Scene-A signals 2026-07-02T02:00:00Z
  - NVDA sell_put: score=91.5 iv_rank=0.88
  - AMD covered_call: score=87.3 iv_rank=0.82
Scope: read-only signal. No trading action taken.
```

你打开 Discord 看到这条。NVDA 的 sell put 触发了你的 p90 阈值（经过 2 周分布复盘后设定的 min_score=85, min_iv_rank=0.75）。你知道 NVDA 最近 IV 偏高，sell put 的逻辑是赚波动率溢价。

你决定深入研究一下。打开 Hermes 对话：

> "NVDA 这个 sell_put 信号，帮我看看最近的 IV 走势和财报日历"

Hermes 调平台数据，告诉你 NVDA 财报在 3 周后，当前 IV 处于 88 分位，但财报前 IV 通常会继续上升。你判断：**等财报后再做**。在 0b 复盘库里记一笔。

---

### 📅 周二 — 收到一篇论文，想试试因子

朋友分享了一篇关于"流动性枯竭预警因子"的论文。你把 PDF 发给 Hermes：

> "帮我把这个因子的逻辑翻译成可回测的配置"

Hermes 读完论文，输出：

```
因子定义（请确认）：
  流动性枯竭因子 = (Amihud illiquidity 周度变化率) × (换手率衰减因子)
  其中 Amihud = |daily_return| / dollar_volume，取周均值
  换手率衰减 = 1 - exp(-lambda * turnover_ma_20d)

目标字符串（确认后将用于 propose-factor）：
  "Amihud illiquidity weekly change × turnover decay; universe SPY QQQ components;
   long bottom-decile, short top-decile; rebalance weekly"

⚠️ 因子涉及 dollar_volume 计算，平台上是否有该字段？需人工确认。
```

你检查了平台数据字典，确认 `dollar_volume` 可用。回复"确认"。然后：

```bash
# Hermes 会话内先把已确认的公式翻译成源码，并写入临时文件（Gate 1 后）
python3 -m hqa.factor_repro_cli propose \
  --goal "Amihud illiquidity weekly change × turnover decay..." \
  --source-file /tmp/factor_src.py \
  --expected-source-digest "$(shasum -a 256 /tmp/factor_src.py | awk '{print $1}')" \
  --confirmation-note "已核对论文公式、字段与源码翻译" \
  --paper-doi 10.1093/rfs/hhaf057 \
  --paper-file /tmp/reviewed-paper.pdf \
  --expected-paper-digest "$(shasum -a 256 /tmp/reviewed-paper.pdf | awk '{print $1}')"
# → candidate_id=factor-amihud_liquidity-a1b2c3d4e5
# → HUMAN GATE: inspect the generated candidate factor...

# 你打开生成的 factor.py.candidate，仔细读了代码逻辑，确认翻译正确
cat .../factor-amihud_liquidity-a1b2c3d4e5/factor.py.candidate

# Gate 2：人工 digest CAS approve（四值均由人类从 verified 明细抄写，禁止 refetch）
python3 -m hqa.factor_repro_cli approve \
  --candidate-id factor-amihud_liquidity-a1b2c3d4e5 \
  --expected-digest <sha256-from-verified-detail> \
  --expected-status pending \
  --note "Amihud 公式翻译确认无误，dollar_volume 字段已验证"

# 真实数据回测（默认 Futu QFQ；保留最近 183 天 holdout 不参与迭代——D-21）
python3 -m hqa.factor_repro_cli backtest \
  --candidate-id factor-amihud_liquidity-a1b2c3d4e5 \
  --expected-digest <sha256-from-verified-detail> \
  --symbol SPY --symbol QQQ --start 2020-01-02 --end 2026-06-30
```

几分钟后，回测完成。当前 CLI 已把 holdout、`--final` receipt 与 Gate 3 串成受约束状态链：

```
HOLDOUT: last 183 days reserved; run --final ONCE before promotion (D-21)
experiment_id=factor-repro-factor-amihud_liquidity-a1b2c3d4e5-20260714T120000123456Z-<12hex> best_run_id=run-001
sharpe=1.18 total_return=0.42 max_drawdown=0.14
report=/Users/.../reports/factor_repro_.../experiment_comparison_report.md
Results are research evidence; a successful --final receipt is required before the separate Gate 3 code-review workspace.
```

夏普 1.18，回撤 14%。还不错但不算惊艳。你调整了一次参数重跑（trial 2）。如果你忍不住再调第三次，系统会打印 `OVERFIT WARNING: trial 3`——提醒你正在走"迭代到回测好看为止"的翻车老路。

假设两周后你决定真的要用这个因子。此时走第三道门（D-20 转正）：

```bash
# 1a-3 落地后：转正前唯一一次全窗口回测（含 holdout 段）——holdout 明显衰减就回炉
python3 -m hqa.factor_repro_cli backtest \
  --candidate-id factor-amihud_liquidity-a1b2c3d4e5 \
  --expected-digest <sha256-from-verified-detail> ... --final
# stdout: final_backtest_receipt=backtest-<content-address>
# 注意：系统在调用 provider 前就持久占用这次 final attempt；失败或未知结果也不能重试。

# Gate 3：在隔离 review worktree 生成 scoped patch（绝不自动 commit）
cd /Users/sunyibo/programs/Hermes-quant-agent
python3 -m hqa.factor_repro_cli promote \
  --candidate-id factor-amihud_liquidity-a1b2c3d4e5 \
  --expected-digest <sha256-from-verified-detail> \
  --final-backtest-receipt backtest-<content-address> \
  --base-commit "$(git -C /Users/sunyibo/programs/ai-quant-platform rev-parse HEAD)"
# stdout: {promotion_id, worktree, patch, manifest}
# 在返回的 worktree 中审查 scoped patch，人工 git switch/commit 完成 Gate 3
```

commit 之后，因子成为平台一等公民：前端因子目录可见、回测可用、可以创建 strategy config 绑定它、开一个 strategy sleeve、分配一笔 sleeve cash——纸面模拟开始跑。跑满 30 天、通过 `hqa-gate check`，才有资格进入券商模拟的讨论。

**关键：因子进入你资金链路（哪怕是纸面资金）之前有三道人工 gate——确认翻译、审候选代码、审转正 diff。LLM 不能自己理解完就直接跑回测，更不能绕过 git 审查进入常驻交易路径。这是防"AI 把公式理解偏"和防过拟合流水线的核心防线。**

---

### 🔴 某天凌晨 02:30 — 安全基线偏离

你睡着了。但 Hermes 没睡。

```
[HQA][ALERT] safety-invariant watchdog 2026-07-03T18:30:00Z
  - live_trading_enabled=true (expected false)
  action: STOP. Do not run any execution path until the safety baseline is restored.
```

你被 Discord 的高优先级通知吵醒（你设置了 `#审批` 和 watchdog 告警为强制通知）。打开一看，`live_trading_enabled` 被人（或者某个 bug）改成了 `true`。

你立刻 SSH 到 Mac，检查平台配置，发现是某次实验脚本不小心写了一个 `config.set(live_trading_enabled=true)`。你改回去，然后在复盘库里确认这条告警：

```bash
python3 -m hqa.review_cli confirm 2026-07-03-001 \
  --judgment "实验脚本误改 live_trading_enabled" \
  --basis "config.set() 缺少 scope 限制" \
  --result "已回滚，无交易发生" \
  --failure_point "实验脚本无配置写入权限隔离" \
  --next_rule "所有实验脚本禁止直接调 config.set()；加入 scope=dry_run 强制"
```

**同一天，复盘库里自动生成了一条 draft（看门狗告警触发），你手动补全了判断字段。这就是"每次风险都有记录"。**

---

### 📊 周日 09:00 — 周复盘报告

你在 Discord `#复盘` 频道收到：

```
[HQA] Weekly review 2026-07-07T01:00:00Z
- safety alerts: 1
- signals fired: 4
- review entries: 3
  · 2026-07-03-001 [confirmed] safety-invariant deviation → next: 实验脚本禁止直接调 config.set()
  · 2026-07-02-001 [confirmed] NVDA sell_put signal deferred → next: 财报前 IV 通常继续上升，等财报后
  · 2026-07-01-001 [confirmed] Scene-A thresholds chosen → next: revisit after 2 weeks
```

你花 10 分钟回顾。本周：
- 1 次安全基线偏离，已修复并沉淀规则
- 4 次盘中信号触发，你做了 2 次深入分析，错过了 2 次（其中一个回头看是个不错的机会——记入复盘）
- 3 条复盘记录从 draft 变为 confirmed

你手动加了一条 weekly 复盘：

```bash
python3 -m hqa.review_cli draft --kind weekly --event "本周错过的机会" \
  --data "ticker=AAPL, signal=momentum breakout, reason=没有及时查看 Discord"
python3 -m hqa.review_cli confirm <id> \
  --judgment "AAPL 动量突破信号在周二触发，我直到周四才看到" \
  --basis "Discord 通知被淹没在其他频道中" \
  --result "错过了 +3.2% 的move" \
  --failure_point "通知优先级不足；#盘中异动 频道未设强提醒" \
  --next_rule "#盘中异动 频道开启强制通知；信号触发后 30min 未查看则重复推送"
```

---

### 🏦 Phase 2-3 阶段——半自动实盘

几个月后，你有一个策略通过了满月验收：
- Longbridge 券商模拟运行 35 天
- 夏普 1.4，最大回撤 8%
- 拒单率 0%，滑点 < 0.5%
- 每次回撤都有复盘日志
- 无越权行为

你决定给它分配一小笔资金（$5,000）进入半自动实盘。

**此时的日常变成了：**

1. 信号看门狗触发 → 你评估后决定"这个信号值得做"
2. 你通过 Discord `#审批` 频道发送审批指令（或在 Hermes 对话中说"批准"）
3. MCP server 校验 kill_switch + 风险信封 + 人工审批 token → 提交给 Longbridge 实盘
4. 成交结果 + 滑点报告推回 Discord
5. 如果日亏损触及日亏损上限 → kill_switch 自动触发，关闭当日所有后续下单
6. 每次成交自动落审计日志 + 复盘草稿

**你仍然对每一笔真实订单有最终决定权。系统只是把"研究 → 信号 → 候选 → 执行 → 复盘"的机械劳动全部自动化了。**

---

## 系统全景：你得到了什么

```

                    ┌──────────────────────────────────┐
                    │        Hermes 编排大脑            │
                    │  cron · memory · kanban · MCP     │
                    └──────────┬───────────────────────┘
                               │
          ┌────────────────────┼───────────────────────┐
          │                    │                       │
     ┌────▼─────┐      ┌──────▼───────┐       ┌───────▼──────┐
     │ 数字员工  │      │  复盘系统     │       │  通知/审批    │
     │          │      │  (0b)        │       │  Discord     │
     │ 盘前digest│      │  JSONL + MD  │       │  频道分流     │
     │ 信号看门狗│      │  自动草稿     │       │              │
     │ 期权雷达  │      │  人工确认     │       │              │
     │ AI新闻   │      │  周复盘       │       │              │
     │ 周复盘   │      │  验收门       │       │              │
     └────┬─────┘      └──────────────┘       └───────────────┘
          │
     ┌────▼─────────────────────────────────────┐
     │        ai-quant-platform 研究后端         │
     │  doctor · factor · backtest · options    │
     │  paper account · 评审池 · risk engine    │
     └────┬─────────────────────────────────────┘
          │
     ┌────▼──────────┐    ┌──────────────────┐
     │ Longbridge    │    │ Futu/Moomoo      │
     │ 模拟 → 实盘    │    │ 行情 + 期权数据    │
     └───────────────┘    └──────────────────┘
```

### 数字层面，你得到了：

| 能力 | 自动化程度 | 你的参与 |
|------|-----------|---------|
| 安全基线监控 | 全自动，30min/次 | 只在告警时介入 |
| 盘前简报 | 全自动，每日 | 2 分钟扫读 |
| 盘中信号扫描 | 全自动，30min/次 | 只在触发时评估 |
| AI 行业异动 | 全自动，2h/次 | 只在有高分条目时看到 |
| 期权雷达摘要 | 全自动，每日 | 1 分钟扫读 |
| 论文因子复现 | 半自动（三 gate：翻译确认/审码 approve/转正 diff） | 三次确认，合计约 10 分钟 |
| 回测 | 自动化执行（默认 holdout 截断 + 试验计数告警） | 设置参数 + 解读结果 |
| 周复盘 | 自动汇总 | 10 分钟补充判断 |
| 错误/回撤复盘 | 自动起草骨架 | 人工填判断字段 |
| 策略晋级验收 | 自动校验 | 人工决策 |
| 模拟交易 | 信封内自动，超出人工 | 异常审批 |
| 实盘交易 | 逐单人工审批 | 最终决策 |

### 认知层面，你得到了：

1. **注意力过滤** — 不需要盯盘、不需要刷新闻、不需要手动跑扫描。系统帮你筛选，只推值得看的东西。

2. **经验不流失** — 每次错判、每次回撤、每次"我应该做但没做"，都变成结构化的复盘条目。半年后回顾，你能看到自己所有的决策模式和进化轨迹。

3. **研究加速度** — 看到一个因子 idea，从"发给我"到"回测报告"可能只需 10 分钟（其中 8 分钟是你在确认翻译正确性）。不再需要手动写因子代码、配数据源、跑回测、整理报告。

4. **安全不依赖记忆力** — 不是"我记得我设了 kill_switch"，而是每 30 分钟有一个看门狗在检查，并且异常时有告警 + 自动复盘草稿 + 审计日志。

5. **可撤退** — 如果实盘出问题，kill_switch 切断当日交易。如果整个系统让你不安，停掉所有 cron 就回到纯手动模式。你永远比系统多一层控制权。

---

## 你和它的关系

项目初期（Phase 0a-1a），它更像一个**不知疲倦的研究助理**——帮你盯着安全基线、每天早上告诉你平台状态、盘中提醒你值得看的信号、每周帮你回忆这周发生了什么。

到了 Phase 2-3，它变成一个**有纪律的交易副驾驶**——它帮你把研究变成候选、把候选推过评审池、把通过评审的策略在模拟盘上跑满月、把满月数据整理成验收报告。但最终"这笔钱投不投"永远是你自己的决定。

**你失去的是机械劳动。你保留的是判断、直觉和最终决策权。**

---

> ⚠️ 再次提醒：本文是推演，不是 spec。所有提到的功能、命令、交互方式都可能在实际实现中调整。以 `docs/design/` 下的正式设计文档和 `docs/plans/` 下的 TDD 计划为准。
