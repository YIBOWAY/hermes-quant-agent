# Phase 1a-4 — 研究员工扩容 设计 spec（D-26）

> 状态：设计定稿（2026-07-07），经 brainstorming 对齐。
> 上游：`docs/design/2026-07-01-roadmap-phases-0b-4.md` §2.6b / D-26。
> 前置：Phase 1a-3 闭环补全已交付（含安全加固）；1a-0 平台接线包已交付。
> 本文定位：1a-4 的设计 spec；实现计划在 spec 批准后由 `superpowers:writing-plans` 单独产出。
> 安全红线（继承）：三员工全 read-only / proposal-only，零审批复杂度，不碰 paper mutation / 交易链路，凭证不进 LLM 上下文。

---

## 0. 范围与交付顺序

D-26 列了 5 个研究员工，本 phase 落 **3 个**（价值/成本比最高、零新外部依赖）：

| 员工 | 本 phase | 理由 |
|---|---|---|
| ④ 错过机会追踪 | ✅ | 最独立、成本最低、数据源现成 |
| ③ 组合风险日报 | ✅ | 真实价值，D-27 drop-in，带出 ② 的价格基础 |
| ② 市场推演 + 预测台账 | ✅ | 最高战略价值（玄学推演→可校准能力） |
| ① 公司/市场调研 | ❌ 留到工作台后 | 成本最高（firecrawl 新依赖），前端已能做调查类 |
| ⑤ 夜间预注册因子批测 | ❌ 按 D-26「可选」推迟 | 无人值守跑回测与反过拟合护栏张力最大 |

**交付顺序（按依赖）**：④ → ③（含平台 `data prices`）→ ②。③ 的 `data prices` 是 ② 对账的复用基础；④ 独立。

**频道分配**：③ → `#盘前digest`（附带）；④ → 入复盘库，`#复盘`；② → 新 `#预测台账`。

---

## 1. 架构总览

```
员工④ 错过机会追踪      信号台账 × paper 行动 → 复盘库 draft → #复盘
员工③ 组合风险日报       paper 持尸 → 敞口/集中度/相关性/beta → #盘前digest
  └─ 平台侧：data prices --json（只读，③的beta + ②的对账共用）
员工② 推演+预测台账      CLI/Hermes录入 → JSONL台账 → 到期对账评分 → #预测台账
```

**沿用现有架构纪律（不引入新模式）**：

- 每个员工 = `hqa/<name>.py` 的纯 `run(...)`（注入 callables + `now_iso` + `log_path`）+ `main(argv)` + 永不崩调度器的 `try/except`（异常只写 `{ts,job,error}` 到 JSONL + stdout，返回 0）+ `runlog.append_jsonl` 写 `logs/<job>.jsonl`
- 员工只 `print()`，推送交给 shell wrapper / `hqa-notify.sh`（保持 stdlib-only、push-agnostic）
- 每个员工配 `scripts/hermes/hqa-<name>.sh` wrapper，`install.sh` 的 glob 自动拾取（无需改 install.sh）
- Python 3.9 兼容（`from __future__ import annotations`）
- 复盘库走 `reviewlog.new_draft`，`weekly_review.py` 零改动即可拾取新 kind（除 ② 需小改加「预测对账」段）

**新基础设施（最小化）**：

- `hqa/predictions.py` + `hqa/prediction_cli.py`（prog `hqa-prediction`）—— 预测台账，镜像 `reviewlog.py` / `review_cli.py` 结构
- `hqa/quant_cli.py` 新增 `run_paper_account_show(account_id)`、`run_paper_ops_status(target_date)`、`run_data_prices(symbols, start, end, provider)`
- 平台侧 `src/quant_system/cli.py` 新增 `data prices` 只读命令（`--json`，复用 `load_ohlcv`）
- `hqa/missed_opportunities.py`、`hqa/portfolio_risk.py`、`hqa/market_foresight.py`（员工主体）

---

## 2. 价格数据源策略（取代 tiingo）

**事实**（2026-07-07 核验）：平台 `tiingo_api_token: null`、`.env` 空、`default_data_provider: futu`——tiingo 未设置，futu 是唯一在用数据源。

**策略**：futu 主 + longbridge 备，**不碰 tiingo**。

- **主路径**：平台 `data prices --provider futu --json`，复用 `load_ohlcv` + futu provider（`providers/futu.py` 已有 `request_history_kline`，`data/futu` 缓存已存在，凭证已在平台、不进 LLM）。
- **兜底**：futu 取不到（港股盘外、OpenD 断、额度用完）→ HQA 调 `longbridge-market-data` skill 的 K 线接口（`risk_level: read_only`、`requires_login: false`）取该标的历史 K 线。
- **缺失**：两源都失败 → 该标的 `beta=unavailable` / 对账 `status` 留 `open` + `price_source=unavailable`，**不造假数据**，下轮重试。
- **首期简化**：简单串行降级，不做两源混合计算。longbridge 凭证是实现期第一个探查点；若需 token 且未设，退回 futu 单源 + 缺失标注，不留半成品。
- **beta 基准**：SPY。

---

## 3. 员工④ 错过机会追踪

**目的**：信号触发但无对应 paper 行动 → 自动记复盘 draft，周复盘汇总，提醒「该分配 sleeve 了」。

**「未行动」定义**：信号 × paper 交易未对应。

**数据流**：

```
读 logs/signal_watchdog.jsonl (since=今日, has_signal=True)
  → 当日信号集 [{ts, symbol, signal_type, score, ...}]
读 paper strategies ops-status --target-date <date> --format json
  → 当日行动 {sleeves, pending_executions, blocked, ...}

sleeves=0 守卫:
  → 只记一条汇总 draft: "本日 N 个信号，sleeves=0，全部未行动，建议分配 paper sleeve"
sleeves>0:
  → 逐信号交叉：该 symbol 当日是否有 pending_execution / execution？
     无 → 记 missed-opportunity draft (kind="missed-opportunity",
          event=f"{symbol} {signal_type} 信号未行动",
          data={signal, ops_status}, source="missed-opportunities")
     有 → 跳过

经 reviewlog.new_draft (fingerprint=当日+symbol 去重)
  → logs/missed_opportunities.jsonl (run 记录)
  → stdout (cron → #复盘)
```

**新模块** `hqa/missed_opportunities.py`：

- `run(run_read_signals, run_ops_status, now_iso, log_path, review_dir=None, date=None) -> tuple[int, str]` —— 返回 `(n_missed, message)`
- `cross_reference(signals: list[dict], ops_status: dict) -> list[dict]` —— 纯函数，返回 missed 列表
- `summarize(missed: list[dict], ops_status: dict, ts: str) -> str` —— sleeves=0 / 正常两态消息
- `main` flags: `--date --log --review-dir`

**新 quant_cli**：`run_paper_ops_status(target_date: str | None = None) -> tuple[int, str]` —— 跑 `paper strategies ops-status --format json [--target-date ...]`，复用 `_run` 模式。

**只读白名单**：`hqa-quant-readonly.sh` 新增 `"paper strategies ops-status"`（只读、无副作用）。

**复用**：`reviewlog.new_draft`（零改动）；`weekly_review.py` 零改动（`list_entries` 全 kind 拾取，新 kind 自动出现）。

---

## 4. 员工③ 组合风险日报

**目的**：每日盘前，paper 账户敞口/集中度/相关性/beta → `#盘前digest`。

**数据流**：

```
读 paper account-show --account default --json   (新增 quant_cli.run_paper_account_show)
  → 解析 {cash, realized_pnl, positions: [{symbol, qty, avg_cost}], kill_switch}
读 data prices --symbol <sym> ... --symbol SPY --start <lookback> --end <today> --provider futu --json
  → 每个持仓标的 + 基准 SPY 的历史收盘
  → futu 失败 → longbridge skill 兜底 → 都失败标 unavailable

算:
  敞口      gross_exposure = Σ(qty*last_price), net = gross - cash
  集中度    单标的权重, top1/top3 占比, HHI
  相关性    持仓间相关矩阵 (历史日收益)
  beta      每标的 vs SPY: cov(ri, rm)/var(rm)

positions=0 守卫:
  → 输出 "paper 账户无持仓，仅现金 cash=...；分配 sleeve 后启用风险日报"

写 logs/portfolio_risk.jsonl + stdout (cron → #盘前digest 附带)
```

**新模块** `hqa/portfolio_risk.py`：

- `parse_account(output: str) -> dict` —— 解析 `account=… cash=… positions=N` + 逐行 `symbol: qty avg_cost`
- `compute_risk(positions, prices: dict[str, list[float]], benchmark: list[float]) -> dict` —— 纯函数：敞口/集中度/相关性/beta；价格缺则该标的 `beta=unavailable`
- `build_report(risk, account, ts, provider) -> str` —— 多态（无持仓/有持仓/部分价格缺失）
- `run(run_account_show, run_prices, now_iso, log_path, account_id="default", benchmark="SPY", provider="futu") -> str`
- `main` flags: `--account --benchmark --provider --log`

**新 quant_cli**：`run_paper_account_show(account_id="default")` + `run_data_prices(symbols, start, end, provider="futu")`。longbridge 兜底在 `portfolio_risk.py` 内调 longbridge skill CLI（注入便于测试）。

**平台侧跨仓库改动**：`src/quant_system/cli.py` 新增 `data prices` 只读命令（`--symbol` 可多次、`--start --end --provider futu --json`，复用 `load_ohlcv`），走 `--json` 契约（1a-3 P4 同款）。`hqa-quant-readonly.sh` 白名单新增 `"data prices"`。

---

## 5. 员工② 市场推演 + 预测台账

**目的**：推演判断落结构化预测，到期自动对账评分（Brier），把「玄学推演」变「可校准能力」。周复盘并入「预测对账」段。

**台账存储**：`predictions/entries.jsonl`（`config.PREDICTION_DIR`，env `HQA_PREDICTION_DIR`），镜像 `reviewlog.py`（JSONL append-only、`id=YYYY-MM-DD-NNN`、`sort_keys=True`、load dedup by id last wins）。

**Schema（一条预测，status=open）**：

```json
{
  "id": "2026-07-07-001",
  "ts": "<ISO8601 UTC>",
  "status": "open",
  "subject": "NVDA",
  "direction": "up",
  "range_low": 145.0,
  "range_high": 160.0,
  "horizon": "2026-07-14",
  "confidence": 0.7,
  "falsifier": "到期收盘 < 140 即证伪",
  "rationale": "...",
  "entry_close_price": 148.5,
  "entry_close_source": "futu"
}
```

- `entry_close_price` / `entry_close_source`：`create` 时抓录入日收盘（futu 优先、longbridge 兜底、都失败则 `entry_close_price=null` 且 `create` 拒绝并提示「取不到录入日价，无法定方向基准」——不存无基准的预测）。对账定实际方向需要它。
- `falsifier`：**人读辅助字段**，不参与自动评分（评分模型保持确定性，不解析自然语言证伪条件）。`rationale` 同理。

**Schema（status=scored，对账后写新行，同 id last-write-wins）**：

```json
{
  "id": "2026-07-07-001",
  "ts": "<原 ts>",
  "status": "scored",
  "subject": "NVDA",
  "direction": "up",
  "range_low": 145.0,
  "range_high": 160.0,
  "horizon": "2026-07-14",
  "confidence": 0.7,
  "falsifier": "...",
  "rationale": "...",
  "outcome_price": 152.3,
  "outcome_direction": "range",
  "direction_score": 0,
  "range_score": 0.85,
  "brier": 0.09,
  "price_source": "futu",
  "scored_ts": "<ISO>"
}
```

**评分模型**（写死，可在实现期微调）：

- 实际方向：`up`=到期收盘 > 录入日收盘；`down`=<；`range`=落在 [range_low, range_high]
- 方向分 = `1 if 预测方向 == 实际方向 else 0`
- Brier = `(confidence - direction_score) ** 2`
- 区间分（仅 `direction=range`）：落在区间 `1.0`；区间外 `max(0, 1 - |price - center| / halfwidth)`；非 range 预测不评
- 价格取不到（futu+longbridge 都失败）→ `status` 留 `open`、`price_source=unavailable`、下轮重试，**不造假分**

**模块** `hqa/predictions.py`（镜像 reviewlog）：

- `new_prediction(subject, direction, horizon, confidence, *, range_low=None, range_high=None, falsifier=None, rationale=None, ts, prediction_dir, entry_close_price, entry_close_source) -> str` —— 返回 id；`entry_close_price` 必填（取不到则 raise，不存无基准预测）
- `load_entries(prediction_dir) -> list[dict]`
- `list_due(prediction_dir, today) -> list[dict]` —— status=open 且 horizon<=today
- `score(prediction_id, *, outcome_price, price_source, scored_ts, prediction_dir) -> dict` —— 读 open 条目的 `entry_close_price`/`direction`/`range_*`/`confidence`，算 direction/range/brier，写 scored 行（同 id last-write-wins）
- `render_markdown(prediction_dir) -> str` / `write_markdown` → `predictions/entries.md`

**CLI** `hqa/prediction_cli.py`（prog `hqa-prediction`，镜像 `review_cli.py`）：

- `create --subject --direction --horizon --confidence [--range-low --range-high --falsifier --rationale --prediction-dir]` → 抓录入日收盘（复用 ③ 的 `run_data_prices` + longbridge 兜底）、存 open 条目、打印 id、rewrite md；取不到收盘则拒绝（exit 2，提示「无法定方向基准」）
- `list [--status] [--since] [--prediction-dir]`
- `reconcile [--date] [--prediction-dir]` → 对所有 due 预测取到期价（复用 ③ 的 `run_data_prices` + longbridge 兜底）、score、rewrite md
- `render [--prediction-dir]`

**Hermes wrapper**：`scripts/hermes/hqa-prediction.sh`。你在会话里说推演判断 → Hermes 调 `hqa-prediction create` 录入；`reconcile` 走每日盘后 cron。

**对账 cron**：`hqa-prediction reconcile` 每日盘后跑一次，到期才推 `#预测台账`（新建频道）。

**周复盘并入**：`weekly_review.py` 小改——加读 `predictions/entries.jsonl` 的 scored 条目，`build_report` 增「预测对账」段（近 7 天 Brier 均值、命中率、按 subject 聚合）。

---

## 6. 错误处理与测试

**永不崩调度器**（沿用现有纪律）：每个员工 `main` 包 try/except，异常只写 `{ts, job, error}` 到 `logs/<job>.jsonl` + stdout，返回 0。

**数据缺失诚实标注**（贯穿三员工）：

- ④ `ops-status` 取不到 → 标 `ops_unavailable`，不臆造「未行动」
- ③ 价格 futu 失败 → longbridge 兜底 → 都失败 `beta=unavailable`，**不填假 beta**；无持仓 → 输出提醒而非空表
- ② 到期价取不到 → `status` 留 `open`、`price_source=unavailable`，下轮重试，**不造假分**

**降级链**（③/② 共用）：futu → longbridge skill → 标缺失。首期简单串行，不做两源混合计算。longbridge 凭证是实现期第一个探查点；若需 token 且未设，退回 futu 单源 + 缺失标注。

**安全红线**（贯穿）：三员工全 read-only / proposal-only；只读白名单新增 `paper strategies ops-status`、`data prices`；不碰 paper mutation / 交易链路；凭证不进 LLM 上下文。

**测试纪律**（沿用 1a-1/1a-2 house style）：

- 纯函数 + 注入 callables → 单元测试用 canned fixtures，零网络/零 subprocess
- `run(...)` 注入 `run_*` 假 callable，断言 argv 构造 + 输出格式 + JSONL 记录
- 真网络/真 CLI 测试 `skipif` 守卫（无 token/无 OpenD 跳过）
- 平台侧 `data prices` 命令独立单测（`load_ohlcv` mock）
- 评分函数：手造预测 + 已知到期价，断言 Brier / 区间分精确值
- sleeves=0 / positions=0 / 价格缺失 三态各有测试
- Python 3.9 兼容（`from __future__ import annotations`）

---

## 7. 文件结构

```
hqa/
  config.py                # + PREDICTION_DIR (predictions/)
  quant_cli.py             # + run_paper_account_show, run_paper_ops_status, run_data_prices
  missed_opportunities.py  # NEW: 员工④
  portfolio_risk.py        # NEW: 员工③ (含 longbridge 兜底)
  predictions.py           # NEW: 预测台账 (镜像 reviewlog)
  prediction_cli.py        # NEW: hqa-prediction CLI (镜像 review_cli)
  weekly_review.py         # MODIFY: + 预测对账段
scripts/hermes/
  hqa-missed-opportunities.sh   # NEW wrapper
  hqa-portfolio-risk.sh         # NEW wrapper
  hqa-prediction.sh             # NEW wrapper
  hqa-quant-readonly.sh         # MODIFY: + "paper strategies ops-status", "data prices"
tests/
  test_missed_opportunities.py  # NEW
  test_portfolio_risk.py        # NEW
  test_predictions.py           # NEW
  test_prediction_cli.py        # NEW
  test_weekly_review.py         # MODIFY: + 预测对账段
  test_quant_cli.py             # MODIFY: + 3 个新 wrapper
  test_install.py               # MODIFY: + 3 个新 wrapper
# 平台侧 (ai-quant-platform 仓库)
  src/quant_system/cli.py       # MODIFY: + data prices 只读命令 (--json)
  tests/test_data_prices.py     # NEW
```

---

## 8. 验收

- ④：有信号且 sleeves=0 → 记一条汇总 draft；有 sleeve 后逐条交叉，missed 记 draft；`weekly_review` 零改动拾取新 kind。
- ③：有持仓 → 输出敞口/集中度/相关性/beta（futu 优先、longbridge 兜底、缺失标 unavailable）；无持仓 → 提醒。
- ②：CLI/Hermes 录入预测 → JSONL；到期对账算 Brier/区间分；价格缺失留 open 不造假；`weekly_review`「预测对账」段。
- 三员工永不崩调度器；数据缺失诚实标注；HQA 测试套件全绿。
- 平台 `data prices --json` 只读、无副作用；只读白名单放行、写命令仍审批。

---

**关联**：① 调研留到工作台后（前端已能做调查类）；⑤ 夜间批测按 D-26「可选」推迟（无人值守跑回测与反过拟合护栏张力大，晋级仍走三道人工门）。D-27 Longbridge 只读 probe 落地后，③ 的 paper 持仓无缝切真实账户。
