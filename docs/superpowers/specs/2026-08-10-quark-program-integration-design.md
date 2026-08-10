# 设计：quark_program 三个外部项目接入 HQA（分三档）

日期：2026-08-10
状态：已与用户对齐范围（全部接入、分三档）与工作目录（直接在活跃副本 `data/_runtime/agent-v02-work/` 上改）
安全红线：全程只读研究/展示用途，不触发交易；`kill_switch=true`、`live_trading_enabled=false` 不变。

## 0. 背景与评估结论

用户拷贝了三个外部项目到 `programs/quark_program/`，要求评估并接入当前量化助手（HQA）。
源码与 dashboard 实际效果均已人工核查，结论：

| 项目 | 实质 | 真实性核查 | 接入价值 |
|---|---|---|---|
| 伯恩斯坦 K型分化监测器（文件夹名"AI泡沫实时监测器·亚洲12个市场"） | 复现 Bernstein 2026-07-03 研报：亚洲 12 市场 K型分化/泡沫监测。5 个分析模块（市场K型、因子K型、行业拥挤、动量泡沫、综合信号），约 2700 行 | 默认跑 demo 数据（`main.py:10`），`--real` 走 yfinance/akshare/baostock；dashboard 真实渲染但依赖 `../echarts.min.js` 相对路径。**⚠️ 修正：真实链路有致命缺陷，见 §0.5-1** | 产品形态/指标设计最高价值，但**代码需重写**（真实链路坏、demo 可标 real） |
| 花旗板块资金流轮动 | 美股 11 板块 ETF 动量（70%价格+30%成交量）月度轮动，多 TOP3 空 BOTTOM3，回测引擎 v2.0 约 900 行 | 结果负 alpha（年化 3.99% vs SPY 12.02%，Sharpe 0.105，回撤 -49%）。**⚠️ 修正：前视偏差+成本失真+伪 walk-forward，且 `neodata_fetch.py` 含明文 TOKEN，见 §0.5-2/3** | 仅保留轮动概念；修复口径后作普通实验，不用花旗名称 |
| 阿里达摩院 DiffsFormer AI选股 | 复现 arXiv:2402.06656 扩散 Transformer 因子增强：全A训练扩散模型→CSI300 样本编辑式增强→MLP/LSTM/GRU 下游→Top30Drop30 日频回测，约 4200 行 | 模型是真实训练产物；取数依赖本机不存在的 `westock-data` CLI。**⚠️ 修正：预测(symbol,date)对齐错位、测试集选择偏差、dashboard 基准/IC 系 np.random 合成，见 §0.5-4** | 仅研究思路；不生成展示报告；走正式实验 Gate 链路 |

**统一原则：吸收的是方法论和产品形态，不是代码/数据/成品页面。** 所有展示必须标注数据来源与更新口径，demo 数据必须醒目降级提示。

## 0.5 与第二份评估（另一 agent）对齐后的修正

另一份更深入的评估发现了多处我漏掉的硬伤，逐条独立验证后全部属实，
本 spec 据此收敛。验证记录：

1. **K型监测器真实链路是坏的（颠覆我"最高价值"的前提）**
   - `main.py:95` 之后 `run_factor_monitor` 读 `self.data['stock_data']`、
     `run_sector_analyzer` 读 `self.data['sector_data']`，但 `--real` 路径
     （`main.py:69-84`）只写了 `market_data`，从未构造这两个键 → **真实模式必崩**。
   - `main.py:238` `data_type = 'real' if self.use_real_data else 'demo'` 只看启动参数；
     取数失败静默降级到 `generate_all_demo_data()` 后仍标 `real` → **demo 数据可被标成真实**。
   - `fetcher.py` 真实抓取只有 7 个 ETF，无个股/行业数据，PE/PB 全空 → 现有页面
     展示的"真实结果"无法由当前真实链路复现。
   - 结论修正：**产品形态和指标设计仍是最高价值，但代码不能 copy**；五个模块按现有
     数据契约重写，不沿用其 demo 降级逻辑。

2. **明文凭据（安全问题，最高优先）**
   - `花旗策略Python复现源码/neodata_fetch.py:11` 有明文 `TOKEN = "tk_jnEQ..."`，
     请求发往 `copilot.tencent.com/agenttool/v1/neodata`。**不得复制进任何仓库**；
     接入实现不涉及该文件；是否撤销/轮换由用户决定（token 不是我这边的资产）。

3. **花旗引擎的"专业特性"有水分（修正我"引擎诚实"的过高评价）**
   - 前视偏差：信号用月末收盘生成，`run_backtest` 直接 `signals.reindex(ffill)`
     同日生效（`backtest_engine.py:616,632`），无下一交易日执行 → **已验证属实**。
   - 成本失真：按 `avg_turnover`（总换手/调仓次数）回填每个调仓日（`:629,638`），
     非每次实际换手 → **属实**。
   - walk-forward：只把训练期最后一个信号带入测试期，无滚动重估 → **属实**。
   - 结论修正：花旗从"策略库成员"**降级为仅保留价格/成交量轮动概念**；如保留需先修
     对齐/成本/复权/真实基准，作为普通实验，不使用花旗名称与标识（报告限制再分发）。

4. **DiffsFormer 结果不可信（比我"口径不一致"更严重）**
   - 预测对齐错误：`run_2026.py:126-133` 把扁平预测数组按 `len//n_stocks` 顺序切块
     赋给各 symbol，再 `backtest_engine.py:68-75` 从回测首日起按位置对齐，
     无可靠 `(symbol, date)` 映射 → **属实，回测分数基本是错位的**。
   - 选择偏差：同一测试集上挑"提升最大"的模型再报同一测试集结果（`run_2026.py:113`）。
   - dashboard 数字造假：`generate_dashboard_v3.py:83-99` 基准曲线是 `np.random`
     合成、IC 时序是 `np.cumsum(np.random.randn...)` 合成 → **属实**；页面正文
     年化 12.8%/Sharpe 0.88 与其摘要 10.56%/0.63 自相矛盾。
   - 另有约 377MB 未知 `.pkl` + 多个 `.pt`（pickle/torch.load 可执行任意代码），
     **未在本机加载**；之前一次 read 失败其实是 pandas `datetime64[us]` 版本兼容问题。
   - 结论修正：DiffsFormer 从"复现档案/静态报告"**降级为纯研究思路**；不生成展示报告
     （会把编造的数字正当化），只把论文思路作为一个隔离实验构想，走平台正式
     `experiment → factor_candidate → Gate 1/2/3 → paper` 链路。

5. **法律/合规**：三个目录均无标准 LICENSE；指南提到的 README 实际缺失；花旗原始 PDF
   明确限制再分发 → **不整目录复制**，只提炼方法论重写。

## 0.6 修正后的优先级与形态

| 优先级 | 项目 | 产品契合 | 可直接复制 | 修正后形态 |
|---|---|---|---|---|
| P1 | K型/泡沫监测器 | 4/5 | 1/5 | **保留产品形态+页面布局+指标设计，按现有数据契约重写**；universe 先做你常用的美股/AI 范围（SPY/QQQ/SOXX/IGV + 持仓行业与重点个股），亚洲 12 市场后续补数据源 |
| P2 | DiffsFormer | 3/5 | 0/5 | **仅研究思路**，作为隔离实验，验证通过后走候选因子 Gate 链路；不生成展示报告 |
| P3 | "花旗"板块轮动 | 2/5 | 0.5/5 | **只保留价格/成交量轮动概念**；修复前视/成本/复权后作为普通实验进统一结果页，不新增独立页面、不用花旗名称 |

## 1. 总体架构：三档接入

```
quark_program（外部源，只读参考，不整目录复制）
      │ 提炼方法论 + 按现有数据契约重写
      ▼
HQA 活跃副本 data/_runtime/agent-v02-work/
├─ ai-quant-platform（前端 Next.js + 后端 quant_system/FastAPI）
│   ├─ P1：K型/拥挤度监测 → 重写 → Hermes 今日页摘要卡片 + market_foresight 详情
│   ├─ P3：板块价格/成交量动量 → 修复后作为普通实验 → /strategies + /backtest（不新增首页入口）
│   └─ P2：DiffsFormer 思路 → 隔离研究实验 → Experiments / Factor Lab / Unified Results
└─ Hermes-quant-agent（hqa 侧：定时任务、只读研判、发布 artifact）
```

**P1 垂直切片（推荐的第一个交付）**：真实数据的 K型/拥挤度监测 → HQA 定时任务 →
`market_foresight` artifact → Hermes 页面卡片 + 详情。平台已有可复用组件
`components/hermes/artifacts/ForesightSummary.tsx` 与 `app/hermes/results/page.tsx`，
因此第一步是**扩充现有数据契约，而不是复制三份静态 HTML**。
验收必须包含：数据来源、时间、复权方式、覆盖范围、降级状态；禁止把模拟数据标成真实。

## 2. P1：K型/泡沫监测器 → 重写进 market_foresight（不新建孤立 tab）

**归属**：数据源/指标计算/持久化/GET API 在 `quant_system`（ai-quant-platform）；
定时运行、形成只读研判、发布 artifact 在 hqa 侧。前端优先落在现有 Hermes 今日页摘要 +
统一结果详情，而非另起 `/k-shape-monitor` 孤立页。

- **指标实现**：参考其五个模块的方法论（市场K型、因子K型、行业拥挤、动量泡沫、综合信号），
  按 `quant_system/factors/` 现有契约**重写**，不 copy 代码：
  - 不引入 `demo_generator`；任何样本/降级数据必须显式标注，API 默认拒绝 demo；
  - 取数走 `quant_system/data/providers/` 现有 provider（tiingo/csv 等），universe 先做
    美股/AI 范围（SPY/QQQ/SOXX/IGV + 持仓行业与重点个股）；亚洲市场作为后续数据源扩展，
    缺源时显式降级并标注，**不静默退回 demo**；
  - 指标输出对齐 `market_foresight` artifact schema（扩充该契约容纳拥挤度/泡沫维度）。
- **API**：扩充现有 foresight/results GET endpoint，而非另起 `/api/kshape/*`。
- **前端**：复用 `ForesightSummary.tsx` 卡片 + `hermes/results` 详情，按 HQA 设计体系
  呈现拥挤度/泡沫/分化视图；echarts 走 npm 依赖。
- **刷新**：HQA 定时任务每日运行（对齐现有 automation 范式），失败保留上一版并标记 stale。

## 3. P3：板块价格/成交量动量 → 修复后作为普通实验（不用花旗名称）

- 只保留"板块动量轮动"概念；**重写**信号与执行对齐：
  - 修复前视：月末信号 → 下一交易日开盘执行（原为同日收盘直接生效）；
  - 修复成本：按每次实际换手计费，不用平均换手率回填；
  - 复权处理、真实基准（SPY 而非合成）、样本外 walk-forward 需真正滚动重估；
  - 不使用花旗名称/标识/原始报告内容，命名为"行业价格/成交量动量代理策略"。
- 回测执行用平台 `quant_system/backtest/` 统一引擎，与库内其他策略同口径；
  取数走平台 data provider。
- 展示：作为普通实验进 `/strategies` + `/backtest` 统一结果页，**不新增首页/独立 tab**；
  附口径说明（代理 vs 原报告、负 alpha 归因）。
- **凭据处理**：`neodata_fetch.py` 含明文 TOKEN，任何情况下不复制进仓库；实现不涉及该文件。

## 4. P2：DiffsFormer → 仅研究思路，走正式实验链路

- **不做展示报告**（其净值/IC/消融/基准均含合成或错位数据，生成报告会正当化假数字）。
- 仅把论文思路（arXiv:2402.06656 扩散 Transformer 因子增强）登记为一个隔离研究实验构想，
  记录其原实现的对齐错误与选择偏差作为反面教材（docs 备注）。
- 若要真正验证，走平台正式链路并满足：
  1. 可信原始数据 → Parquet、安全模型格式（不加载来源不明的 .pkl/.pt）；
  2. 每条样本显式保存 (symbol, date, 预测窗口)；
  3. 每日横截面 IC，而非混合样本算相关性；
  4. 独立 holdout + walk-forward + 交易成本 + 试验预算；
  5. 进入现有 `experiment → factor_candidate → Gate 1/2/3 → paper` 链路。
- **明确不做**：实时选股页、每日推理、加载其交付的模型权重。

## 5. 数据流与错误处理

- 三档统一：取数失败 → 显式降级（stale 标记 / 报错），**绝不静默退回 demo 数据**；前端展示数据来源徽章（real/stale/demo）。
- P1 universe 优先复用现有美股数据 provider；亚洲市场数据源作为后续扩展，缺源显式降级并标注。
- 不加载来源不明的 `.pkl`/`.pt`（pickle/torch.load 可执行任意代码）；不把任何凭据复制进仓库。
- 所有新增写操作（refresh、重跑）遵循本地 trust mode；对外 public write 默认 OFF 不变。

## 6. 测试

- P1：重写后的拥挤度/泡沫指标单元测试（录制样本，不依赖外网）；foresight/results API 契约测试；前端 Hermes 卡片与详情渲染测试。
- P3：轮动信号单元测试（固定输入→固定持仓，验证次日执行对齐）；回测集成测试与库内基准同口径；结果落库 schema 校验。
- P2：实验登记与 Gate 链路元数据校验（无回测断言，因本期不实现训练）。
- 全部改动过现有 pytest gate 与前端 lint/build。

## 7. 交付顺序（建议，一个 plan 内分批）

1. **P1 垂直切片**（最高价值）：真实数据 K型/拥挤度监测 → HQA 定时任务 → market_foresight artifact → Hermes 页面卡片 + 详情。
2. P3 板块动量实验（修复口径后重跑，进统一结果页）。
3. P2 DiffsFormer 实验构想登记（仅文档 + 元数据，不实现训练）。

## 8. 明确不做（YAGNI）

- 不做达摩院实时选股页、不生成其展示报告、不加载其模型权重；
- 不做三个静态 HTML 的原样 iframe 嵌入、不整目录复制（无法律依据且含凭据/坏链路）；
- 不为板块动量单独建首页 tab；不动 kill_switch/live_trading 任何配置；
- P1 本期不做亚洲 12 市场数据源扩展（先做美股/AI universe）。
