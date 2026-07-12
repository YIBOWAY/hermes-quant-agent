# Hermes-quant-agent 对抗性审查报告

> **历史审计快照**：本文记录 2026-07-09 当时的代码、运行与优先级。部分止血项
> 随后进入工作树，当前工程主线也已切到平台前端/Hermes/PostgreSQL 集成。
> 不要从本文的“下一步”继续开发；当前状态先看 [`../README.md`](../README.md)。
>
> **日期**：2026-07-09
> **范围**：`Hermes-quant-agent`（编排/COO 层）+ 对照 `ai-quant-platform`（领域后端/前端/存储）
> **审查方式**：通读 `docs/design/*`、`docs/plans/*`、`docs/superpowers/*`；CodeGraph 索引 HQA 源码；git 状态；运行日志与真实 CLI 核验；HQA 测试套件
> **Git HEAD**：`f9d8191`（`docs(neat-freak): sync HQA knowledge base to 1a-3/D-25 delivered + 1a-4 planned state`）
> **HQA 测试**：全绿（少量 skip）
> **性质**：对抗性审查 + 个人量化助手合格性评估 + 止血 PR 清单 + 后续建议
> **不构成投资建议**；本报告不改变安全红线（paper / live=false / kill_switch / 人工门）

---

## 0. 执行摘要

### 一句话结论

> **工程纪律与安全哲学明显优于业余 AI 交易 bot；作为「可演进的个人量化 COO 骨架」合格。作为「每天替你过滤信息、逼你复盘、抓住机会」的助手，目前约 6/10——骨架强、肌肉弱、日常闭环未闭合。**

### 总评分数卡

| 维度 | 分 | 说明 |
|---|---|---|
| 愿景与安全哲学 | 9/10 | 一流个人项目水准 |
| 文档与治理 | 9/10 | 决策台账、分层规划出色 |
| HQA 代码质量 | 8/10 | 可测、可注入、stdlib 干净；契约脆弱点已知 |
| 平台后端成熟度 | 8/10 | 研究栈完整 |
| 前端产品一致性 | 5/10 | 功能多，未对齐 COO 叙事 |
| 数据库策略 | 7/10 | file-first 对；可选层膨胀中 |
| 日常可靠性 | 5/10 | cron 在跑，信号/扫描/复盘闭环断 |
| 功能相对愿景 | 4/10 | 停在 1a 中段，价值曲线前半 |
| **作个人量化助手总评** | **6/10** | **合格骨架，未到可靠副驾驶** |

### 合格性分阶段判定

| 角色期望 | 判定 |
|---|---|
| Phase 1a 研究助理（盯安全、扫盘、做因子实验、沉淀复盘） | **基础合格，日常体验未及格** |
| 可靠「不错过机会」的盯盘副驾驶 | **不合格**（阈值未设、扫描有洞、iv_rank 空） |
| 可校准判断 / 组合风控助手 | **不合格**（1a-4 未做） |
| 半自动交易助手 | **远未到，且不应现在宣称** |

### 最亮点

1. 安全与过拟合写进产品结构，不是 README 口号
2. 文档/计划/决策台账可对抗审计，利于单人 + 多 agent 长期维护
3. 真有 cron 在跑，不是 PPT
4. 双仓治理（HQA 拉平台）方向对，避免平台乱长独立路线

### 最危险幻觉

1. 「数字员工在值班」≠「会提醒你」——多数是沉默 collect
2. 「三道门」≠「过拟合免疫」——trial 只 warning
3. 「paper 有钱」≠「策略在跑」——几乎无 sleeve 运营证据
4. 「doctor 绿」与「扫描在更新」解耦——一个绿一个空很常见

### 必须立刻止血的三条

1. **doctor 安全解析 JSON-first**，并区分 infra 失败 vs 安全偏离
2. **Scene-B 默认 provider → futu**（tiingo 显式 opt-in）
3. **只读白名单去掉/降级 `options daily-scan`**（以及刷新 skill 卡契约）

---

## 1. 审查范围与方法

### 1.1 文档

| 类别 | 路径 |
|---|---|
| 活跃路线图 | `docs/design/2026-07-01-roadmap-phases-0b-4.md`（D-1…D-27） |
| 总设计 / 愿景 | `docs/design/hermes_quant_agent_plan.md`、`vision-daily-life.md` |
| 已交付计划 | `docs/plans/2026-07-01-phase-0a…` 至 `1a-3`、`D-25 latency` |
| 下一刀 | `docs/superpowers/specs|plans/2026-07-07-phase-1a-4-*` |
| 代理规则 | `AGENTS.md`、`README.md` |

### 1.2 代码与运行面

| 表面 | 证据 |
|---|---|
| HQA 源码 | CodeGraph：41 files / 439 nodes（`hqa/*` + `tests/*`） |
| 测试 | `./.venv/bin/pytest` 全绿 |
| 运行日志 | `logs/doctor_watchdog.jsonl` ~298 行；`signal_watchdog` ~86 行；`premarket_digest`；`review/entries.jsonl` 7 条全 draft |
| 平台 | doctor 实跑；`promote-candidate` 存在；前端 Next.js 20+ 页；DB `enabled=false`；`tiingo.token=unset` |
| Hermes | `~/.hermes/scripts/hqa-*.sh` 已装；`command_allowlist` 含 `hqa-quant-readonly.sh *` |

### 1.3 不在本报告范围内

- 平台全量测试矩阵与性能 profiling
- 真实 Discord 端到端延迟复测（沿用 D-25 文档中 2026-07-05 数据）
- 投资收益评估

---

## 2. 项目定位与交付现状

### 2.1 分层角色

```
你（审批 / 判断 / 经验沉淀）
  ↕ Discord / CLI /（将来）Hermes 工作台
Hermes（cron · memory · skill · allowlist）
  ↕ shell wrappers + hqa Python（stdlib-only）
ai-quant-platform（CLI / API · 因子 · 回测 · paper · 期权）
  ↕ Futu 行情（只读）
（远期）Longbridge 模拟 → 半自动实盘
```

| 层 | 角色 | 状态 |
|---|---|---|
| **HQA** | Hermes 编排 / COO | Phase 0a→1a-3 + D-25 **已交付** |
| **ai-quant-platform** | 领域后端 + 研究前端 | 研究栈完整；**无实盘执行层** |
| **下一刀** | 1a-4 研究员工 | **仅有 design + plan，未实现** |

### 2.2 已交付 vs 未交付

**已有：**

- 安全 invariant watchdog（`doctor_watchdog`）
- 盘前 digest（安全 + options meta + AI HOT）
- 信号 collect / alert 框架（`signal_watchdog` + D-15 阈值语义）
- 周复盘、期权 radar 摘要、AI HOT 异动
- Scene-B：`propose | approve | backtest` + 平台 `promote-candidate`（Gate 3）
- 反过拟合：trial 计数、183 日 holdout、`hqa-gate` ≥30 paper days
- D-25：只读预授权、HQA skill 卡、异步 notify + artifact-first

**未有：**

- 1a-4：错过机会 / 组合风险日报 / 预测台账
- D-17：Hermes 工作台前端吞并
- Phase 1b+：Longbridge 模拟 adapter、满月闭环、实盘
- 信号阈值实际落地（配置层）
- 复盘 confirmed 闭环（人侧运营）

### 2.3 运行快照（2026-07-09 核验）

| 指标 | 观察 |
|---|---|
| doctor 基线 | `dry_run=true`, `paper_trading=true`, `live=false`, 配置层 `kill_switch=true` |
| tiingo | `token=unset`；`default_data_provider=futu` |
| database | `enabled=false` |
| options scans | 有 07-01…07-03、07-06、07-07；**缺 07-08**。07-09 是否算缺口取决于美股交易时段与 `hqa-options-collect` cron（工作日 23:00 CST）是否已跑完——审查当日午间可能尚未到 collect 窗口 |
| signal thresholds | **全部 run 为 `min_score=null, min_iv_rank=null`**（永久 collect） |
| 有候选时 iv_rank | `iv_rank_known: 0`（686 候选时仍为 0） |
| review entries | 7 条，**0 confirmed**；多条 doctor 假警报草稿 |
| paper account | ~$1M，1 股 AAPL；账户层 `kill_switch=false`（与配置层不同语义） |

---

## 3. 架构评价

### 3.1 整体分层 —— 强

正确之处：

1. **编排与领域分离** —— HQA 不碰交易内核；平台不做 LLM 主路径（D-19）
2. **三道人工门 + 反过拟合** —— 比多数「AI 炒股」玩具严肃
3. **Artifact-first / [SILENT]** —— 匹配个人注意力预算
4. **文件优先 + 可选 Postgres 镜像** —— 单机合理，可降级
5. **文档单一事实源（D-24）** —— 决策台账清晰，agent 不易被过时 roadmap 污染

### 3.2 「前后端」要拆开看

| 表面 | 实际 | 评价 |
|---|---|---|
| HQA「后端」 | 薄 Python + subprocess CLI | 合适；不是业务服务 |
| HQA「前端」 | Discord + CLI + skill 卡 | 个人助手正确形态 |
| 平台前端 | Next.js 全研究 UI（20+ 页） | 能力强，**与 Hermes COO 叙事未统一** |
| 平台 API | FastAPI 本地，**零鉴权** | localhost OK；远程/公网危险 |

D-17「Hermes 工作台」未做 → 当前是 **两套心智模型**：Discord 数字员工 vs 浏览器研究台。能用，但不像一个产品。

### 3.3 数据库 / 持久化设计

**HQA：** 无 RDB。权威源：

- `logs/*.jsonl`（run-log）
- `review/entries.jsonl`（复盘；append-only + 同 id 覆盖语义）
- 平台侧 `data/options_scans/`、`data/api_runs/` 等

**平台四层存储并存：**

1. 文件事实源（runs / paper / scans）
2. DuckDB 期权缓存
3. 可选 Postgres：runs 索引、AI HOT 缓存、brief/日报、paper mirror
4. Parquet 等附属产物

设计哲学 **file-first + optional index** 对个人正确。对抗性风险：

- schema 在涨（`app_users`、owner-scoped reports），但 `database.enabled=false` → **复杂度已付、收益未收**
- dual-write 路径一多，易产生「文件 vs DB 谁为准」的认知税
- HQA JSONL **无校验、无 compaction、无跨 job 关联 id**；半年后检索会痛

---

## 4. 功能完备性矩阵（相对愿景）

| 能力（vision） | 现状 | 合格线 |
|---|---|---|
| 安全 7×24 | 跑着；误报与 doctor 失败纠缠 | ⚠️ 半合格 |
| 盘前 digest | 可用；options 常 DEGRADED | ⚠️ |
| 盘中信号 | collect only，从不 alert | ❌ |
| 期权 radar 摘要 | 有 | ✅ |
| AI 新闻异动 | 有 | ✅ |
| 论文因子 → 回测 | 链路代码在；默认数据源错 | ⚠️ |
| 转正 Gate 3 | 平台命令在 | ✅ 机制 |
| 周复盘 | 能汇总；人侧确认断 | ⚠️ |
| 错过机会 | 无 | ❌ |
| 组合风险 | 无 | ❌ |
| 预测可校准 | 无 | ❌ |
| 券商模拟满月 | 无 | ❌（阶段未到） |
| 实盘 | 无 | ❌（正确延后） |
| 统一工作台 UI | 无 | ❌ |

---

## 5. 对抗性发现（按严重度）

### 5.1 P0 — 直接伤害「日常是否可信」

#### F1. 安全解析脆弱：文本耦合；纯 JSON 路径假警报

- `quant_cli.run_doctor()` 走 `doctor --json`
- `doctor_watchdog.parse_safety` 仍只匹配 `safety.key=value` 文本行
- 当前平台输出 = **文本 + 末行 JSON**，故暂时可用
- 若只剩 JSON：`parse_safety → {}` → 全 key missing → **假阳性 ALERT**
- 历史复盘已有多条：`doctor exited 1` + `safety: {}`（07-03…07-07）
- **基础设施抖动被当成安全基线被攻破**

**期望修复：** JSON-first 读最后一行 `safety`；布尔规范化；`infra_fail` 与 `safety_breach` 分通道。

#### F2. 信号链路实质未进入「提醒」态

- 全部 `signal_watchdog` 记录 `thresholds` 为 null → 永久 collect（D-15 语义）
- 即使 `n_candidates=686`，`has_signal` 仍 false
- 近期多次 `n_candidates=0`（无当日 scan）
- 场景 A「不错过机会」在产品层等于 **关闭**
- 另：`iv_rank_known: 0` 即使 686 候选 → 用 iv_rank 定阈值的路径 **无数据可复盘**

#### F3. Scene-B 默认 provider 与现实数据面冲突

```text
HQA CLI 默认: tiingo
平台 doctor:  tiingo.token=unset, default_data_provider=futu
```

文档 erratum 已承认 tiingo 未配置；**CLI 默认未改**。
按 skill/README 默认回测 → 高概率失败。

### 5.2 P1 — 契约 / 安全边界 / 运营闭环

#### F4. 「只读」白名单含写盘重操作

`hqa-quant-readonly.sh` 放行 `options daily-scan` / `buyside-screen`：

- daily-scan **写** `data/options_scans/`，消耗 Futu 额度，可能与 collect 抢锁
- skill 卡写明 writes snapshot，却标在 read-only 区
- 与 D-25「只放行无副作用」**自相矛盾**

#### F5. Skill 卡过时

- 写 `doctor --json` 不存在、勿加 `--json`
- 平台现状：`--json` 可用
- 会教坏 agent，重新引入探索/重试回合

#### F6. Gate 2 无 OS 级人机隔离

- `approve` 只是 CLI；cron/agent 若被提示即可执行
- 「human-only」是 **社会/产品约束**，不是强制隔离
- 对个人可接受，文档需诚实

#### F7. 复盘认知飞轮未转

- 7 条全 draft，0 confirmed
- 假警报草稿污染库
- D-2/D-4「记得你如何做错过」**尚未发生**

#### F8. Collect 缺口静默

- 07-08、07-09 无 scan
- digest/signal 降级为空 options，**不强制告警**
- Mac 睡眠 / OpenD / cron 失败 → 表现为「一切正常，只是没信号」

### 5.3 P2 — 完备性与可维护性

| ID | 项 | 说明 |
|---|---|---|
| F9 | 1a-4 未实现 | 错过机会 / 组合风险 / 预测台账 |
| F10 | Hermes 工作台未做 | agent-studio 僵尸 LLM UI 仍在（D-17） |
| F11 | API 零鉴权 | 1b 前可接受；禁止公网暴露 |
| F12 | Paper sleeve 运营弱 | 有账户，几乎无真实 sleeve 证据 |
| F13 | 满月 gate 无真实喂入 | 校验器有，无 30 天策略数据 |
| F14 | 硬编码本机路径 | 可 env 覆盖，可移植性弱 |
| F15 | signal 默认 refresh-lab | collect 也刷 lab，重且非必要 |
| F16 | 日期时区风险 | load 用 UTC 日 vs 扫描可能美东日 |

### 5.4 正确克制（不是 bug）

- 无实盘、无券商下单 —— 设计如此
- 候选因子不进常驻 sleeve，须 promote —— 正确
- HQA stdlib-only —— 正确
- 过拟合只 warn 不 hard-block —— 可接受（可再加硬挡）

---

## 6. 作为个人量化 Agent 助手的评价

### 6.1 你得到了什么

| 已兑现 | 未兑现 |
|---|---|
| 安全基线巡检骨架 | 可靠、低噪的安全告警 |
| 盘前信息组装骨架 | 稳定的 options 数据段 |
| 因子实验三门机制 | 默认就能跑通的真数据回测 |
| 日志与复盘 schema | 人会确认的认知复利 |
| 静默 collect 哲学 | 真正触发的盘中提醒 |

### 6.2 与业界个人量化 agent 对比（定性）

相对开源「研究人格辩论 / 不实盘」类项目：

- **更强**：真实数据接线（Futu）、paper 账户、评审池、promote 落代码、反过拟合流程、cron 运营
- **更弱于愿景文案**：交互延迟虽有 D-25，但机会捕获与复盘运营未闭环

### 6.3 总评

| 问题 | 答案 |
|---|---|
| 是否值得继续投？ | **是**——方向、纪律、接线都对 |
| 今天能否当日常副驾驶？ | **否**——先止血 + 阈值 + collect 健康度 |
| 是否「合格」？ | **骨架合格（B）；日常助手未及格（C+/B-）** |

---

## 7. 止血 PR 清单

> 原则：每个 PR 小而可测、不扩 scope、不碰交易链路。
> 建议顺序：PR-1 → PR-2 → PR-3 → PR-4 → PR-5（可 1+2 并行）。

### PR-1 — doctor 安全解析 JSON-first + 分型告警（HQA）

| 项 | 内容 |
|---|---|
| **修** | F1 |
| **仓库** | Hermes-quant-agent |
| **目标** | doctor 输出无论「纯文本 / 文本+JSON / 纯 JSON」都能稳定解析；infra 失败不再伪装成安全基线被攻破 |
| **文件** | `hqa/doctor_watchdog.py`、`hqa/premarket_digest.py`（若共用）、`tests/test_doctor_watchdog.py`、`tests/test_premarket_digest.py` |
| **行为** | ① `parse_safety`：优先 `parse_json_payload` 取 `safety` dict，bool→小写字符串；② 文本 regex 兜底；③ `evaluate` 拆 `infra_errors` vs `safety_deviations`；④ 消息前缀区分 `[INFRA]` / `[SAFETY]`；⑤ review draft fingerprint 分型 |
| **测试** | 纯 JSON 样本不误报；文本样本兼容；exit≠0 且无 safety 行 → infra 通道；真实 `run_doctor` 集成（可选 skip） |
| **验收** | 手动：`python -m hqa.doctor_watchdog` 在当前环境 silent；模拟只 JSON 输出的 unit 绿 |
| **风险** | 低；行为变更仅告警语义更准 |
| **估时** | 0.5–1 天 |

**建议 commit：**

```text
fix(hqa): JSON-first doctor safety parse + infra vs safety channels
```

---

### PR-2 — Scene-B 默认 provider 改 futu（HQA）

| 项 | 内容 |
|---|---|
| **修** | F3 |
| **仓库** | Hermes-quant-agent |
| **目标** | 默认回测路径与真实数据面一致，避免 tiingo unset 静默失败 |
| **文件** | `hqa/quant_cli.py`（`run_experiment_config` 默认）、`hqa/factor_repro_cli.py`（`--provider` default）、相关 tests、`README.md`、`skills/hermes/hqa-quant/SKILL.md` |
| **行为** | ① default=`futu`；② help 文案注明 tiingo 需 token 且显式传入；③ 可选：provider=tiingo 且可检测 unset 时打印明确 ERROR（不猜 token） |
| **测试** | CLI argv 默认断言；monkeypatch 调用参数含 `futu` |
| **验收** | `hqa-factor-repro backtest ...` 无 `--provider` 时打到 futu |
| **风险** | 低；若有人依赖 tiingo 默认需显式改 |
| **估时** | 0.5 天 |

**建议 commit：**

```text
fix(hqa): default Scene-B backtest provider to futu
```

---

### PR-3 — 收紧只读白名单 + skill 卡同步（HQA）

| 项 | 内容 |
|---|---|
| **修** | F4、F5 |
| **仓库** | Hermes-quant-agent（安装后需 `bash scripts/install.sh`） |
| **目标** | 预授权路径真正无重副作用；skill 不再教错契约 |
| **文件** | `scripts/hermes/hqa-quant-readonly.sh`、`tests/test_install.py`、`skills/hermes/hqa-quant/SKILL.md` |
| **行为** | ① **移除** `options daily-scan`、`options buyside-screen` 出只读白名单（或仅允许带明确只读子命令若平台存在）；② skill §1 改为：扫描走 artifact / 走需审批的 wrapper；③ skill 更新 doctor `--json` 已支持、默认 provider=futu；④ 文档注明「全量 scan 不走 pre-auth」 |
| **测试** | install/白名单负向：`daily-scan` → exit 2；`doctor` 仍通过 |
| **验收** | 装完后 Hermes allowlist 下无法免审批烧 scan |
| **风险** | 中低：Hermes 对话里「扫一下期权」会变需审批——符合安全意图 |
| **估时** | 0.5 天 |

**建议 commit：**

```text
fix(d-25): drop scan side-effects from read-only gate; refresh skill card
```

---

### PR-4 — Collect / 扫描健康度显式 DEGRADED（HQA）

| 项 | 内容 |
|---|---|
| **修** | F8（部分 F2） |
| **仓库** | Hermes-quant-agent |
| **目标** | 当日无 scan artifact 时不再「安静假装正常」 |
| **文件** | `hqa/premarket_digest.py`、`hqa/signal_watchdog.py`、`hqa/options_radar.py`（若适用）、tests |
| **行为** | ① 默认路径：目标 date 无 `*_meta.json` / 空 candidates → 消息含 `DEGRADED: no scan artifact for <date>`；② signal collect 可仍 silent 于「无阈值」，但对「无产物」写 log 字段 `artifact_missing=true`；③ 可选：连续 N 次 missing 才 stdout（防睡眠时段刷屏）——首版可对 digest 总是打印 DEGRADED |
| **测试** | 空 scan-dir → digest 含 DEGRADED；有 meta → 正常 |
| **验收** | 模拟缺文件可观测 |
| **风险** | 低；可能增加 digest 噪音（比静默丢数据好） |
| **估时** | 0.5–1 天 |

**建议 commit：**

```text
fix(hqa): surface missing options-scan artifacts as DEGRADED
```

---

### PR-5 — 信号阈值配置落地（最小）（HQA + 运维）

| 项 | 内容 |
|---|---|
| **修** | F2 主因 |
| **仓库** | Hermes-quant-agent（+ 可选 Hermes cron 参数） |
| **目标** | 结束「永久 collect」；至少 score 阈值可配置并进入 alert |
| **文件** | `hqa/config.py` 或 `data/_runtime/signal_thresholds.json`；`signal_watchdog` main 读配置；`scripts/hermes/hqa-signal-watchdog.sh`；tests；一条 review draft 记录阈值决策（D-15） |
| **行为** | ① 支持 env / 文件：`min_score`（必填才能 alert）；`min_iv_rank` 可选（当前 iv 全空则先不强制）；② wrapper 传参或读默认配置；③ 无配置文件时保持 collect + 日志注明 `mode=collect`；④ README 写：如何从 `score_summary` p90 定阈值 |
| **建议初值（需你确认）** | 基于 07-07 样本 p90≈145、max=160：可试 `min_score=140` 或更保守 `150`；**iv_rank 暂不启用** 直至 F-iv 修复 |
| **测试** | 配置存在时 evaluate 会 fire；不存在时 collect |
| **验收** | 对历史 07-07.jsonl 回放能产出非空 signals（给定阈值下） |
| **风险** | 阈值拍偏会刷屏或过静——先偏静，再降阈值 |
| **估时** | 1 天 |

**建议 commit：**

```text
feat(hqa): load Scene-A signal thresholds from config (exit permanent collect)
```

---

### PR-6（可选同批）— signal 默认不 refresh-lab（HQA）

| 项 | 内容 |
|---|---|
| **修** | F15 |
| **文件** | `hqa/signal_watchdog.py`、tests |
| **行为** | 默认跳过 `factor refresh-lab`；`--refresh-lab` 显式打开；日志保留 `factor_exit` 为 skipped 语义 |
| **估时** | 0.25 天 |

---

### 止血 PR 总览表

| PR | 标题 | 修 | 估时 | 依赖 |
|---|---|---|---|---|
| PR-1 | doctor JSON-first + 分型 | F1 | 0.5–1d | 无 |
| PR-2 | backtest default futu | F3 | 0.5d | 无 |
| PR-3 | 只读白名单 + skill | F4/F5 | 0.5d | 无 |
| PR-4 | scan missing → DEGRADED | F8 | 0.5–1d | 无 |
| PR-5 | 信号阈值配置 | F2 | 1d | 建议先有 scan 稳定（PR-4） |
| PR-6 | 默认不 refresh-lab | F15 | 0.25d | 无 |

**止血完成定义（DoD）：**

1. 假警报通道可区分，纯 JSON doctor 不误报
2. 无 `--provider` 回测默认 futu
3. 预授权无法免审批全量 scan
4. 缺扫描产物时 digest 可见 DEGRADED
5. 至少能进入 alert 模式（配置了 min_score），或明确仍 collect 且日志可见
6. HQA pytest 全绿；`bash scripts/install.sh` 后 wrappers 同步

**明确不做进止血批次：**

- 1a-4 三员工
- Hermes 工作台前端
- 平台 API 鉴权 / 1b adapter
- Postgres 启用与 schema 扩张
- 自动 approve / promote

---

## 8. 后续建议路线

### 8.1 本周运营（非代码或半代码）

| # | 行动 | 目的 |
|---|---|---|
| O1 | 复盘库假警报 draft 批量关闭/标注 | 清认知污染 |
| O2 | 用 07-01…07-07 score 分布写一条 **confirmed** 阈值决策复盘 | 完成 D-15 人侧 |
| O3 | 查 Mac 睡眠 / OpenD / options-collect cron 为何 07-08+ 断档 | 恢复数据供血 |
| O4 | 查平台 radar **iv_rank 全 null** 根因 | 解锁 iv 阈值 |
| O5 | 确认 Discord 频道分流与 notify 是否真达 | 注意力通道 |

### 8.2 下一产品切片（代码，按路线图）

| 顺序 | 切片 | 理由 |
|---|---|---|
| 1 | **止血 PR-1…5** | 先让现有员工可信 |
| 2 | **Phase 1a-4**（D-26） | 错过机会 + 组合风险 + 预测台账 = 个人量化脑差异化 |
| 3 | **D-27** 只读 Longbridge probe | 真实账户视图，零下单风险 |
| 4 | **Hermes 工作台**（D-17） | 统一审批/时间线，消双前端 |
| 5 | **Phase 1b** MCP + 鉴权 + 模拟下单 | 仅当 1a 日常稳定后 |
| 6 | Phase 2 满月 → 3 半自动实盘 | 硬门槛不降 |

### 8.3 刻意不要做

- 不要急着实盘 / MCP 写单
- 不要先上复杂 Postgres 业务中心；先把 JSONL 运营好
- 不要让 agent 自动 approve / promote
- 不要为列表好看开 KOL / HindSight / 多券商
- 不要在 doctor 误报未修前扩大告警面

### 8.4 成功标准（3–4 周后复评）

| 标准 | 度量 |
|---|---|
| 安全告警可信 | 一周内 false positive ≤ 1；infra 与 safety 可分 |
| 扫描供血 | 交易日 options collect 成功率 ≥ 90% |
| 信号有用 | alert 模式开启；有信号推送且可回看 log |
| 复盘飞轮 | 每周 ≥1 条 **confirmed**（含 next_rule） |
| 因子路径 | 默认 futu 跑通一次 propose→approve→backtest（不必 promote） |
| 助手体感 | 盘前 2 分钟扫 digest 即够；无信号不吵 |

---

## 9. 附录

### 9.1 关键路径速查

| 主题 | 路径 |
|---|---|
| 路线图 | `docs/design/2026-07-01-roadmap-phases-0b-4.md` |
| 1a-4 设计 | `docs/superpowers/specs/2026-07-07-phase-1a-4-research-employees-design.md` |
| 只读闸门 | `scripts/hermes/hqa-quant-readonly.sh` |
| 安全看门狗 | `hqa/doctor_watchdog.py` |
| 信号 | `hqa/signal_watchdog.py`、`hqa/signals.py` |
| Scene-B | `hqa/factor_repro_cli.py`、`hqa/quant_cli.py` |
| 复盘 | `hqa/reviewlog.py`、`review/entries.jsonl` |
| Skill | `skills/hermes/hqa-quant/SKILL.md` |

### 9.2 运行命令（复现审查）

```bash
# HQA
cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest -q
python3 -m hqa.doctor_watchdog --log /tmp/dw.jsonl
python3 -c "from hqa import quant_cli, doctor_watchdog as d; c,o=quant_cli.run_doctor(); print(d.parse_safety(o), d.evaluate(d.parse_safety(o),c))"

# Platform
cd /Users/sunyibo/programs/ai-quant-platform
./ai-quant/bin/quant-system doctor --json
./ai-quant/bin/quant-system doctor | grep -E 'tiingo|safety|provider|database'
```

### 9.3 历史相关事故线索（复盘库）

- `2026-07-03-001`：工作区半回滚事故（manual draft）
- `2026-07-03-002` … `2026-07-07-001`：doctor 失败导致的 safety draft（疑似假警报通道）

---

## 10. 签署栏（可选）

| 角色 | 姓名 | 日期 | 意见 |
|---|---|---|---|
| 审查 | Agent（对抗性审查） | 2026-07-09 | 见正文；建议先合并止血 PR-1…3 |
| 所有者 | | | 批准止血优先级 / 阈值初值 / 是否进入 1a-4 |

---

*本报告归档于 `docs/audits/`，不修改活跃路线图决策台账；若止血 PR 落地后行为变更，请在对应 `docs/plans/` 或 neat-freak 同步中勾选验收项。*
