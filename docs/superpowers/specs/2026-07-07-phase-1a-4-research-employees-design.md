# Phase 1a-4 — 研究员工扩容 设计 spec（D-26）

> 状态：设计修订版（2026-07-07），**已被 v2 实现计划替代，仅保留历史产品素材**。
> 当前唯一实现入口是
> `docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md`；其 Slice 9A-9G + mini 9H 已完成，
> 完整 9H cron/notify 是下一待展开切片。不得按本文旧模板或顺序继续实现。
> 上游：`docs/design/2026-07-01-roadmap-phases-0b-4.md` §2.6b / D-26。
> 前置：Phase 1a-3 闭环补全已交付（含安全加固）；1a-0 平台接线包已交付。
> 本文定位：1a-4 的历史设计 spec；当前进度和验收事实只在 v2 计划维护。
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

### 0.1 审批修订要点

本 spec 进入实现计划前，必须先修正以下设计约束；否则不得把相关命令加入 Hermes 预授权 allowlist：

1. **平台 paper 查询必须真只读**：HQA 消费的 `paper account-show` 和 `paper strategies ops-status` 不得创建账户、finalize/discard pending sleeve、写账户/策略文件，缺失状态只能以 JSON 表达。
2. **HQA 只消费 JSON 契约**：本 phase 不再新增靠 stdout 文本解析的业务接缝；文本输出可保留给人看，HQA wrapper 只读最后一行/完整 JSON。
3. **错过机会追踪必须有明细**：信号和 paper 行动都要有 symbol / signal_id / execution_id 级别结构化数据；只有计数不够判定 missed opportunity。
4. **Longbridge 是运行时 CLI adapter，不是 Python 代码里的 skill 依赖**：skill 只作为人工/agent 使用说明；HQA 代码通过注入的 `run_longbridge_kline(...)` 调 `longbridge kline history ... --format json`。
5. **预测评分拆开方向与区间**：`up/down/flat` 和 `in_range` 是两个维度，避免“上涨且落在区间内”时类别重叠。

---

## 1. 架构总览

```
员工④ 错过机会追踪      信号台账 × paper 行动 → 复盘库 draft → #复盘
员工③ 组合风险日报       paper 持仓 → 敞口/集中度/相关性/beta → #盘前digest
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
- `hqa/quant_cli.py` 新增 `run_paper_account_show(account_id)`、`run_paper_ops_status(target_date)`、`run_data_prices(symbols, start, end, provider)`，三者都走 JSON
- `hqa/price_series.py`（或同等小模块）—— 统一价格序列 adapter：平台 futu → Longbridge CLI → unavailable
- 平台侧 `src/quant_system/cli.py` 增/改三个纯读 JSON 接缝：`paper account-show --json`、`paper strategies ops-status --format json`、`data prices --json`
- `hqa/missed_opportunities.py`、`hqa/portfolio_risk.py`、`hqa/market_foresight.py`（员工主体）

---

## 2. 价格数据源策略（取代 tiingo）

**事实**（2026-07-07 核验）：平台 `tiingo_api_token: null`、`.env` 空、`default_data_provider: futu`——tiingo 未设置，futu 是唯一在用数据源。

**策略**：futu 主 + Longbridge CLI 备，**不碰 tiingo**，也不静默退回 sample。

- **主路径**：平台 `data prices --provider futu --json`，复用 `build_ohlcv_provider(..., requested="futu")` / futu provider（`providers/futu.py` 已有 `request_history_kline`）。显式 provider 失败时输出错误 JSON / 非 0，绝不 fallback 到 sample。
- **兜底**：futu 取不到（港股盘外、OpenD 断、额度用完）→ HQA 调注入的 `run_longbridge_kline(symbol, start, end)`，底层命令形如 `longbridge kline history NVDA.US --start YYYY-MM-DD --end YYYY-MM-DD --period day --format json`。`longbridge-market-data` skill 只作为人/agent 的命令说明，不作为 HQA 运行时代码依赖。
- **缺失**：两源都失败 → 该标的 `beta=unavailable` / 对账 `status` 留 `open` + `price_source=unavailable`，**不造假数据**，下轮重试。
- **首期简化**：简单串行降级，不做两源混合计算。若 Longbridge CLI 不存在、未登录、无权限或无数据，退回 futu 单源 + 缺失标注，不留半成品。
- **beta 基准**：默认 SPY；实现计划可允许 `--benchmark` 覆盖，但首期不做多基准混合。

**平台 `data prices --json` 契约**（只读、无副作用）：

```json
{
  "ok": true,
  "provider": "futu",
  "start": "2026-01-01",
  "end": "2026-07-07",
  "symbols": ["NVDA", "SPY"],
  "series": {
    "NVDA": [
      {"date": "2026-07-06", "close": 148.5, "source": "futu"}
    ],
    "SPY": [
      {"date": "2026-07-06", "close": 620.1, "source": "futu"}
    ]
  },
  "unavailable": {}
}
```

错误时仍输出机器可读 JSON（最后一行即可）：

```json
{"ok": false, "provider": "futu", "error": "opend_unavailable", "series": {}, "unavailable": {"NVDA": "opend_unavailable"}}
```

HQA `run_data_prices(...)` 只负责拿平台 JSON；是否进入 Longbridge 兜底由 `hqa/price_series.py` 决定。

---

## 3. 员工④ 错过机会追踪

**目的**：信号触发但无对应 paper 行动 → 自动记复盘 draft，周复盘汇总，提醒「该分配 sleeve 了」。

**「未行动」定义**：信号 × paper 交易未对应。

**数据流**：

```
读 logs/signal_watchdog.jsonl (since=今日, has_signal=True)
  → 当日信号集 [{ts, symbol, signal_type, score, signal_id?, ...}]
读 paper strategies ops-status --target-date <date> --format json
  → 当日行动 {counts, sleeves, signals, executions, pending_journals}

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

**结构化信号前置**：

- `signal_watchdog` 需要在原 `signals: list[str]` 之外，增写 `signal_records: list[dict]`。旧 `signals` 文本保留给人看；④ 只消费 `signal_records`。
- `signal_records` 最小字段：`symbol`、`signal_type`、`score`、`iv_rank`、`strategy`、`source_run_date`、`ts`；若有上游 signal_id 则带 `signal_id`，没有则用 `date+symbol+signal_type+strategy` 生成稳定 fingerprint。
- 历史旧日志没有 `signal_records` 时，④ 只能输出 `signals_unstructured` 并跳过逐条 missed 判定，不能从字符串猜 symbol。

**平台 `paper strategies ops-status --format json` 修订契约**（只读、无副作用）：

```json
{
  "target_date": "2026-07-07",
  "execution_window": "next_open",
  "counts": {
    "sleeve_count": 1,
    "running_sleeve_count": 1,
    "pending_execution_count": 1,
    "filled_count": 0,
    "blocked_count": 0
  },
  "sleeves": [
    {"sleeve_id": "sleeve-1", "status": "running", "strategy_config_id": "cfg-1"}
  ],
  "signals": [
    {"sleeve_id": "sleeve-1", "signal_id": "sig-1", "signal_date": "2026-07-07", "symbols": ["NVDA"], "status": "ready"}
  ],
  "executions": [
    {"sleeve_id": "sleeve-1", "execution_id": "exec-1", "signal_id": "sig-1", "target_date": "2026-07-07", "status": "pending", "symbols": ["NVDA"]}
  ],
  "pending_journals": []
}
```

关键约束：默认 `ops-status` 只能调用 storage 的 load/list 方法；不得调用 `reconcile_pending_sleeves()`。如平台仍需要带 reconcile 的运维命令，必须另设显式写路径（例如 `--reconcile`），且不得加入 HQA read-only allowlist。

**新模块** `hqa/missed_opportunities.py`：

- `run(run_read_signals, run_ops_status, now_iso, log_path, review_dir=None, date=None) -> tuple[int, str]` —— 返回 `(n_missed, message)`
- `cross_reference(signals: list[dict], ops_status: dict) -> list[dict]` —— 纯函数，返回 missed 列表
- `summarize(missed: list[dict], ops_status: dict, ts: str) -> str` —— sleeves=0 / 正常两态消息
- `main` flags: `--date --log --review-dir`

**新 quant_cli**：`run_paper_ops_status(target_date: str | None = None) -> tuple[int, str]` —— 跑 `paper strategies ops-status --format json [--target-date ...]`，复用 `_run` 模式，返回值必须是 JSON。

**只读白名单**：`hqa-quant-readonly.sh` 只有在平台默认 `ops-status` 通过“无写盘”测试后，才新增 `"paper strategies ops-status"`。

**复用**：`reviewlog.new_draft`（零改动）；`weekly_review.py` 零改动（`list_entries` 全 kind 拾取，新 kind 自动出现）。

---

## 4. 员工③ 组合风险日报

**目的**：每日盘前，paper 账户敞口/集中度/相关性/beta → `#盘前digest`。

**数据流**：

```
读 paper account-show --account default --json   (新增 quant_cli.run_paper_account_show)
  → JSON {exists, cash, realized_pnl, positions: [{symbol, qty, avg_cost}], kill_switch}
读 data prices --symbol <sym> ... --symbol SPY --start <lookback> --end <today> --provider futu --json
  → 每个持仓标的 + 基准 SPY 的 [{date, close, source}]
  → futu 失败 → Longbridge CLI 兜底 → 都失败标 unavailable

算:
  敞口      gross_exposure = Σ(qty*last_close), net = gross - cash
  集中度    单标的权重, top1/top3 占比, HHI
  相关性    按 date inner join 后的持仓间日收益相关矩阵
  beta      按 date inner join 后，每标的 vs SPY: cov(ri, rm)/var(rm)

positions=0 守卫:
  → 输出 "paper 账户无持仓，仅现金 cash=...；分配 sleeve 后启用风险日报"

写 logs/portfolio_risk.jsonl + stdout (cron → #盘前digest 附带)
```

**新模块** `hqa/portfolio_risk.py`：

- `parse_account(output: str) -> dict` —— 解析 `paper account-show --json`；文本输出只作为人工兜底，不进入 HQA 主路径
- `compute_risk(positions, price_series: dict[str, list[dict]], benchmark_symbol: str) -> dict` —— 纯函数：敞口/集中度/相关性/beta；价格缺或 date 对齐样本不足则该标的 `beta=unavailable`
- `build_report(risk, account, ts, provider) -> str` —— 多态（无持仓/有持仓/部分价格缺失）
- `run(run_account_show, run_prices, now_iso, log_path, account_id="default", benchmark="SPY", provider="futu") -> str`
- `main` flags: `--account --benchmark --provider --log`

**平台 `paper account-show --json` 修订契约**（只读、无副作用）：

```json
{
  "account_id": "default",
  "exists": true,
  "cash": 1000000.0,
  "realized_pnl": 0.0,
  "kill_switch": false,
  "positions": [
    {"symbol": "NVDA", "qty": 10.0, "avg_cost": 148.5}
  ],
  "pending_orders": []
}
```

若账户不存在，必须返回 `exists=false`、`cash=null`、`positions=[]`，且不得调用 `load_or_open()` 创建账户。HQA 把 `exists=false` 当成“无持仓/尚未启用 paper account”提醒。

**新 quant_cli**：`run_paper_account_show(account_id="default")` + `run_data_prices(symbols, start, end, provider="futu")`。Longbridge 兜底在 `hqa/price_series.py` 内通过注入的 CLI callable 完成，便于测试。

**平台侧跨仓库改动**：`src/quant_system/cli.py` 新增 `data prices` 只读命令（`--symbol` 可多次、`--start --end --provider futu --json`，复用 OHLCV provider；显式 provider 失败不 fallback sample），并给 `paper account-show` 加 `--json` 且改成真只读。`hqa-quant-readonly.sh` 只有在平台只读测试通过后，才白名单 `"paper account-show"` 与 `"data prices"`。

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
  "flat_threshold_pct": 0.005,
  "horizon": "2026-07-14",
  "confidence": 0.7,
  "falsifier": "到期收盘 < 140 即证伪",
  "rationale": "...",
  "entry_close_price": 148.5,
  "entry_close_source": "futu"
}
```

- `direction`：只允许 `up | down | flat`。区间判断由 `range_low/range_high` 独立表达，不能再用 `direction="range"`。
- `range_low/range_high`：可选，但必须同时出现且 `range_low < range_high`；它们是区间命中评估，不参与方向 Brier。
- `flat_threshold_pct`：默认 `0.005`（0.5%），用于把小幅波动归为 `flat`，避免“相等才 flat”的伪精确。
- `entry_close_price` / `entry_close_source`：`create` 时抓录入日收盘（futu 优先、Longbridge CLI 兜底、都失败则 `entry_close_price=null` 且 `create` 拒绝并提示「取不到录入日价，无法定方向基准」——不存无基准的预测）。对账定实际方向需要它。
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
  "flat_threshold_pct": 0.005,
  "horizon": "2026-07-14",
  "confidence": 0.7,
  "falsifier": "...",
  "rationale": "...",
  "outcome_price": 152.3,
  "outcome_return": 0.0256,
  "outcome_direction": "up",
  "direction_score": 1,
  "outcome_in_range": true,
  "range_score": 1.0,
  "brier": 0.09,
  "price_source": "futu",
  "scored_ts": "<ISO>"
}
```

**评分模型**（写死，可在实现期微调）：

- 实际收益：`outcome_return = outcome_price / entry_close_price - 1`
- 实际方向：`up` = `outcome_return > flat_threshold_pct`；`down` = `< -flat_threshold_pct`；其余为 `flat`
- 方向分 = `1 if 预测方向 == 实际方向 else 0`
- Brier = `(confidence - direction_score) ** 2`
- 区间命中与方向独立：只要有 `range_low/range_high` 就评 `outcome_in_range` 与 `range_score`
- 区间分：落在区间 `1.0`；区间外 `max(0, 1 - |price - center| / halfwidth)`；无区间则 `range_score=null`
- 价格取不到（futu+longbridge 都失败）→ `status` 留 `open`、`price_source=unavailable`、下轮重试，**不造假分**

**模块** `hqa/predictions.py`（镜像 reviewlog）：

- `new_prediction(subject, direction, horizon, confidence, *, range_low=None, range_high=None, flat_threshold_pct=0.005, falsifier=None, rationale=None, ts, prediction_dir, entry_close_price, entry_close_source) -> str` —— 返回 id；`entry_close_price` 必填（取不到则 raise，不存无基准预测）；校验 direction / confidence / range / horizon
- `load_entries(prediction_dir) -> list[dict]`
- `list_due(prediction_dir, today) -> list[dict]` —— status=open 且 horizon<=today
- `score(prediction_id, *, outcome_price, price_source, scored_ts, prediction_dir) -> dict` —— 读 open 条目的 `entry_close_price`/`direction`/`range_*`/`confidence`/`flat_threshold_pct`，算 direction / range / brier，写 scored 行（同 id last-write-wins）
- `render_markdown(prediction_dir) -> str` / `write_markdown` → `predictions/entries.md`

**CLI** `hqa/prediction_cli.py`（prog `hqa-prediction`，镜像 `review_cli.py`）：

- `create --subject --direction {up,down,flat} --horizon --confidence [--range-low --range-high --flat-threshold-pct --falsifier --rationale --prediction-dir]` → 抓录入日收盘（复用 ③ 的价格 adapter + Longbridge CLI 兜底）、存 open 条目、打印 id、rewrite md；取不到收盘则拒绝（exit 2，提示「无法定方向基准」）
- `list [--status] [--since] [--prediction-dir]`
- `reconcile [--date] [--prediction-dir]` → 对所有 due 预测取到期价（复用 ③ 的价格 adapter + Longbridge CLI 兜底）、score、rewrite md
- `render [--prediction-dir]`

**Hermes wrapper**：`scripts/hermes/hqa-prediction.sh`。你在会话里说推演判断 → Hermes 调 `hqa-prediction create` 录入；`reconcile` 走每日盘后 cron。

**对账 cron**：`hqa-prediction reconcile` 每日盘后跑一次，到期才推 `#预测台账`（新建频道）。

**周复盘并入**：`weekly_review.py` 小改——加读 `predictions/entries.jsonl` 的 scored 条目，`build_report` 增「预测对账」段（近 7 天方向 Brier 均值、方向命中率、区间命中率、按 subject 聚合）。

---

## 6. 错误处理与测试

**永不崩调度器**（沿用现有纪律）：每个员工 `main` 包 try/except，异常只写 `{ts, job, error}` 到 `logs/<job>.jsonl` + stdout，返回 0。

**数据缺失诚实标注**（贯穿三员工）：

- ④ `ops-status` 取不到 → 标 `ops_unavailable`，不臆造「未行动」；信号只有旧文本、没有 `signal_records` → 标 `signals_unstructured`，跳过逐条判定
- ③ 价格 futu 失败 → Longbridge CLI 兜底 → 都失败 `beta=unavailable`；date 对齐样本不足也标 unavailable，**不填假 beta**；无持仓/账户不存在 → 输出提醒而非空表
- ② 到期价取不到 → `status` 留 `open`、`price_source=unavailable`，下轮重试，**不造假分**

**降级链**（③/② 共用）：平台 futu JSON → Longbridge CLI JSON → 标缺失。首期简单串行，不做两源混合计算。若 Longbridge CLI 不存在、需登录、无权限或返回空数据，退回 futu 单源 + 缺失标注。

**安全红线**（贯穿）：三员工全 read-only / proposal-only；只读白名单只有在平台命令通过“无写盘”测试后，才新增 `paper account-show`、`paper strategies ops-status`、`data prices`；不碰 paper mutation / 交易链路；凭证不进 LLM 上下文。

**测试纪律**（沿用 1a-1/1a-2 house style）：

- 纯函数 + 注入 callables → 单元测试用 canned fixtures，零网络/零 subprocess
- `run(...)` 注入 `run_*` 假 callable，断言 argv 构造 + 输出格式 + JSONL 记录
- 真网络/真 CLI 测试 `skipif` 守卫（无 token/无 OpenD 跳过）
- 平台侧 `data prices` 命令独立单测（provider mock），并断言显式 futu 失败不会 fallback sample
- 平台侧 `paper account-show --json` 测试账户不存在时不创建文件；`paper strategies ops-status --format json` 测试不调用 `reconcile_pending_sleeves()`、不改 pending sleeve 文件
- HQA 侧 JSON schema 测试：account / ops-status / data prices 的最小 payload 都能解析；缺字段给清晰错误，不回退猜文本
- 评分函数：手造预测 + 已知到期价，断言方向 Brier / 区间命中 / 区间分精确值
- sleeves=0 / positions=0 / 价格缺失 三态各有测试
- Python 3.9 兼容（`from __future__ import annotations`）

---

## 7. 文件结构

```
hqa/
  config.py                # + PREDICTION_DIR (predictions/)
  quant_cli.py             # + run_paper_account_show, run_paper_ops_status, run_data_prices
  price_series.py          # NEW: futu JSON -> Longbridge CLI -> unavailable adapter
  signal_watchdog.py       # MODIFY: + signal_records structured log field
  missed_opportunities.py  # NEW: 员工④
  portfolio_risk.py        # NEW: 员工③ (复用 price_series)
  predictions.py           # NEW: 预测台账 (镜像 reviewlog)
  prediction_cli.py        # NEW: hqa-prediction CLI (镜像 review_cli)
  weekly_review.py         # MODIFY: + 预测对账段
scripts/hermes/
  hqa-missed-opportunities.sh   # NEW wrapper
  hqa-portfolio-risk.sh         # NEW wrapper
  hqa-prediction.sh             # NEW wrapper
  hqa-quant-readonly.sh         # MODIFY: + "paper account-show", "paper strategies ops-status", "data prices"
tests/
  test_price_series.py           # NEW
  test_signal_watchdog.py        # MODIFY: signal_records
  test_missed_opportunities.py  # NEW
  test_portfolio_risk.py        # NEW
  test_predictions.py           # NEW
  test_prediction_cli.py        # NEW
  test_weekly_review.py         # MODIFY: + 预测对账段
  test_quant_cli.py             # MODIFY: + 3 个新 wrapper
  test_install.py               # MODIFY: + 3 个新 wrapper
# 平台侧 (ai-quant-platform 仓库)
  src/quant_system/cli.py       # MODIFY: paper account-show --json 真只读; ops-status 真只读; + data prices --json
  tests/test_cli_data_prices.py # NEW/EXTEND
  tests/test_cli_paper_readonly.py # NEW/EXTEND: no account create, no sleeve reconcile
```

---

## 8. 验收

- 平台只读前置：`paper account-show --json` 在账户不存在时不创建账户文件；`paper strategies ops-status --format json` 不 reconcile / 不 finalize / 不 discard pending sleeve；`data prices --provider futu --json` 显式失败不 fallback sample。
- JSON 契约前置：HQA 新增接缝只消费 JSON；account / ops-status / data prices 都有最小 schema 测试和缺失字段错误测试。
- ④：有信号且 sleeves=0 → 记一条汇总 draft；有 sleeve 后逐条交叉，missed 记 draft；`weekly_review` 零改动拾取新 kind。
- ④ 的逐条判定只基于 `signal_records` + ops-status 明细；旧文本信号只标 `signals_unstructured`，不猜。
- ③：有持仓 → 输出敞口/集中度/相关性/beta（futu 优先、Longbridge CLI 兜底、缺失/对齐不足标 unavailable）；无持仓/账户不存在 → 提醒。
- ②：CLI/Hermes 录入预测 → JSONL；到期对账算方向 Brier + 区间命中/区间分；价格缺失留 open 不造假；`weekly_review`「预测对账」段。
- 三员工永不崩调度器；数据缺失诚实标注；HQA 测试套件全绿。
- 只读白名单只放行已通过无副作用测试的三个读命令；写命令仍审批。

---

**关联**：① 调研留到工作台后（前端已能做调查类）；⑤ 夜间批测按 D-26「可选」推迟（无人值守跑回测与反过拟合护栏张力大，晋级仍走三道人工门）。D-27 Longbridge 只读 probe 落地后，③ 的 paper 持仓无缝切真实账户。
