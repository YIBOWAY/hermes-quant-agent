# 设计：quark_program 三个外部项目接入 HQA（分三档）

日期：2026-08-10
状态：已与用户对齐范围（全部接入、分三档）与工作目录（直接在活跃副本 `data/_runtime/agent-v02-work/` 上改）
安全红线：全程只读研究/展示用途，不触发交易；`kill_switch=true`、`live_trading_enabled=false` 不变。

## 0. 背景与评估结论

用户拷贝了三个外部项目到 `programs/quark_program/`，要求评估并接入当前量化助手（HQA）。
源码与 dashboard 实际效果均已人工核查，结论：

| 项目 | 实质 | 真实性核查 | 接入价值 |
|---|---|---|---|
| 伯恩斯坦 K型分化监测器（文件夹名"AI泡沫实时监测器·亚洲12个市场"） | 复现 Bernstein 2026-07-03 研报：亚洲 12 市场 K型分化/泡沫监测。5 个分析模块（市场K型、因子K型、行业拥挤、动量泡沫、综合信号），约 2700 行 | 默认跑 demo 数据（`main.py:10`），`--real` 走 yfinance/akshare/baostock 真实取数；dashboard 真实渲染但依赖 `../echarts.min.js` 相对路径；数据来源标记诚实 | **最高**：因子工程有真逻辑（估值 z-score、拥挤度百分位、ERP 预警），与 HQA 现有 market_foresight 互补 |
| 花旗板块资金流轮动 | 美股 11 板块 ETF 动量（70%价格+30%成交量）月度轮动，多 TOP3 空 BOTTOM3，回测引擎 v2.0 约 900 行 | 回测引擎诚实：T+1 shift、佣金+滑点、walk-forward、参数敏感性；结果是**负 alpha**（年化 3.99% vs SPY 12.02%，Sharpe 0.105，最大回撤 -49%）——不是造假的好看数字；取数靠 yfinance（易被限流）+ 东方财富/腾讯裸接口（`direct_fetch.py`） | 中：策略本身不赚钱，但"诚实复现 + 完整归因"是策略库的好教材 |
| 阿里达摩院 DiffsFormer AI选股 | 复现 arXiv:2402.06656 扩散 Transformer 因子增强：全A训练扩散模型→CSI300 样本编辑式增强→MLP/LSTM/GRU 下游预测→Top30Drop30 日频回测，约 4200 行 | 模型文件是真实训练产物（.pt 共 7MB）；raw pkl 为 2019→2025-12 真实日线（pandas 版本兼容问题待解）；**取数依赖 `westock-data` CLI，本机不存在，无法增量更新**；汇总指标有两个版本（54.29%/25.27% vs dashboard 27.91%/10.56%/Sharpe 0.63），以后者全量口径为准；回测有 T+1、涨跌停、印花税，较专业 | 中低（当前形态）：硬核 ML 管线但数据链断裂、结果口径不一致 |

**统一原则：copy 的是代码和方法，不是数据快照。** 所有页面都要标注数据来源与更新口径，demo 数据必须醒目降级提示。

## 1. 总体架构：三档接入

```
quark_program（外部源，保持只读）
      │ copy + 改造
      ▼
HQA 活跃副本 data/_runtime/agent-v02-work/
├─ ai-quant-platform（前端 Next.js + 后端 quant_system/FastAPI）
│   ├─ A档：新 tab  /k-shape-monitor（深度整合，每日刷新）
│   ├─ B档：花旗轮动策略入策略库（重跑 → 落库 → /strategies 详情 + /backtest 展示）
│   └─ C档：/docs 研究院新增"复现档案"（达摩院管线报告 + 拆解文档）
└─ Hermes-quant-agent（hqa 侧：定时任务/数据落盘，若架构归属需要）
```

## 2. A档：K型分化监测器 → 新页面 `/k-shape-monitor`（深度整合）

**归属**：后端进 `quant_system`（ai-quant-platform），因为页面、API、数据管线都在这里；hqa 侧只复用其产出的 JSON（如需 Hermes 对话引用）。

- **后端**：新增 `quant_system/factors/kshape/` 包，copy 五个分析模块并改造：
  - 删除 `demo_generator.py` 默认值，改为显式 `demo=True` 参数才可用，API 默认拒绝 demo；
  - 取数层改写为适配器：优先复用 `quant_system/data/providers/`（tiingo/csv 等现有 provider），缺亚洲 ETF/个股源时新增 akshare provider（可选依赖，import 失败降级并明示）；
  - 输出为 `output/kshape_dashboard_data.json`（结构沿用原 `dashboard_data.json`，前端消费不变）。
- **API**：新增 `GET /api/kshape/dashboard`（读最新 JSON + 元信息）、`POST /api/kshape/refresh`（异步重跑，防重入）。范式对齐现有 endpoint。
- **前端**：新增 `app/k-shape-monitor/page.tsx`，按 HQA 设计体系（深色、卡片、现有图表封装）重排 14 个视图；echarts 走 npm 依赖，不 copy `echarts.min.js`。
- **刷新**：每日定时（对齐现有 scheduler/automation 范式），失败保留上一版并标记 stale。

## 3. B档：花旗轮动 → 策略库成员（重跑 + 落库展示）

- 策略代码 copy 至 `quant_system/strategies/citi_sector_flow/`，信号生成与回测解耦：
  - 回测执行改用平台 `quant_system/backtest/` 引擎（与库内其他策略同口径），原 `backtest_engine.py` 仅作参考实现保留在 docs；
  - 取数走平台 data provider（不再裸调东财/腾讯）；yfinance 限流问题由 provider 层重试/降级解决。
- 跑通 2018-01→至今（含 2026 年新数据），结果落策略库（experiments/strategies 表，按现有 schema）。
- 展示：**不新建 tab**，在 `/strategies` 增加该策略详情页入口 + `/backtest` 结果视图；附"复现说明"（研报口径 vs 平台口径差异、负 alpha 的归因结论）。

## 4. C档：达摩院 DiffsFormer → 复现档案（研究院文档 + 静态报告）

- 源码归档至 `quant_system/replication/diffsformer/`（已有 replication 目录，归属一致），加 README 说明 westock-data 依赖缺失与复现步骤；
- 用其已交付的 models/results 生成一份静态研究报告（净值、IC、消融对比、两个口径差异说明），入 `/docs` 研究院"复现档案"栏目；
- pandas `datetime64[us]` 读取问题：用其对应版本环境或 `pd.read_pickle` 兼容参数解决，仅用于报告生成，不进生产链路；
- **不做**：实时选股页面、每日推理（数据链断裂，成本远超收益）。

## 5. 数据流与错误处理

- 三档统一：取数失败 → 显式降级（stale 标记 / 报错），**绝不静默退回 demo 数据**；前端展示数据来源徽章（real/stale/demo）。
- 亚洲市场取数新依赖 akshare：声明为 optional extra；CI/测试用录制样本，不依赖外网。
- 所有新增写操作（refresh、重跑）遵循本地 trust mode；对外 public write 默认 OFF 不变。

## 6. 测试

- A档：kshape 因子模块单元测试（样本数据）；API 契约测试；前端页面渲染测试（对齐现有 vitest/playwright 范式）。
- B档：策略信号单元测试（固定输入→固定持仓）；回测集成测试与库内基准策略同口径；结果落库 schema 校验。
- C档：报告生成脚本冒烟测试。
- 全部改动过现有 pytest gate 与前端 lint/build。

## 7. 交付顺序（建议，一个 plan 内分批）

1. A档页面（价值最高，1-2 天量级）
2. B档策略库（复用平台引擎，1 天量级）
3. C档复现档案（半天）

## 8. 明确不做（YAGNI）

- 不做达摩院实时选股页；不做三个静态 HTML 的原样 iframe 嵌入；
- 不为花旗策略单独建 tab；不动 kill_switch/live_trading 任何配置。
