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
| P1 | Asia Radar（K型/泡沫监测器重写） | 4/5 | 1/5 | **独立页面 `/asia-radar`**；第一版用 Futu 12 国 ETF 真实闭环；不是完整泡沫判定器 |
| P2 | DiffsFormer | 3/5 | 0/5 | **仅研究思路**，作为隔离实验，验证通过后走候选因子 Gate 链路；不生成展示报告 |
| P3 | "花旗"板块轮动 | 2/5 | 0.5/5 | **只保留价格/成交量轮动概念**；修复前视/成本/复权后作为普通实验进统一结果页，不新增独立页面、不用花旗名称 |

## 0.7 Codex 第三轮收敛（2026-08-10，独立验证后采纳）

Codex 做了源码审查 + 联网检索 + **只读** Futu OpenD 行情实测，本机路径已核对：

1. **导航落点**：活跃副本 `navConfig.ts` 有 `marketsSection`（id=`markets`，含 aiNews/polymarket/agentStudio）。
   新路由 `/asia-radar` 加进该分组。原评估写的中文"市场与 AI"是产品名，代码 id 是 `markets`。
2. **Futu 12 ETF 实测成功**（2026-08-10，OpenD `127.0.0.1:11111`）：
   EWY/EWT/EWJ/ASHR/INDA/EIDO/EWH/EWS/THD/EWM/EWA/EPHE，各约 256 根日线（2025-08-01→2026-08-07），
   来源 `futu`、复权 `qfq`，共 3,072 行。**Phase 1 数据条件具备。**
3. **Futu 适配器只接受美股代码**（`futu.py:normalize_symbol` 对含 `.` 且非 `US.` 前缀的代码抛
   `invalid_symbol`）→ Phase 1 只用 12 个美股国家 ETF，不碰 `JP..N225`/`HK.800000`。
4. **通用 `/ohlcv` 有 sample 静默回退**（`api/routes/data.py:80-91`，provider 失败时用
   `SampleOHLCVProvider`）→ Asia Radar **必须走专用 endpoint**，显式指定 provider=futu，
   失败返回错误/stale，**绝不**静默 sample。
5. **演示数据比我们原先判断更深**：
   - 默认启动器：`start_dashboard.py` 根目录切到 `dashboard/`，网页请求 `../output/dashboard_data.json`
     会 404 → 自动 `getDemoData()`；双击 HTML 也因 `file:` 切 demo。
   - HTML 内还有直接写死的雷达图 `[88,70,55,0.5,0.3,0.2]`、正弦/余弦离散度、
     `Math.random()` 拥挤度历史、虚拟代码 MY0001 等。
   - 根目录 `dashboard_data.json` 的 `data_type:"real"` 与 demo_generator 默认种子结果一致
     （ERP/相关矩阵/动量PE/盈利修正/经济K型），标签不可信。
6. **龙头驱动映射（不是指数替代）**：
   - 韩国：三星+海力士等权篮子 vs KOSPI 日收益相关 0.956；缩放映射样本外 R² 0.945、年化误差 16.7%。
   - 台湾：台积电 vs TAIEX 相关约 0.901，比随意三股等权更好 → 不能统一"每市场两只股票"。
   - Phase 1 只预留"驱动"页签与映射质量字段，**不把原始篮子收益当指数收益**。
7. **其他链路**：TWSE 官方无密钥接口可用（Phase 2）；Twelve Data 覆盖 KRX/TWSE 但需 key（Phase 2）；
   Yahoo chart 实验可用但不作生产主链路；KRX 官方 REST 合同待澄清。
8. **法律**：仍无 LICENSE，不整目录复制；不使用伯恩斯坦/花旗品牌与研报原文。

## 1. 总体架构：三档接入

```
quark_program（外部源，只读参考，不整目录复制）
      │ 提炼方法论 + 按现有数据契约重写
      ▼
HQA 活跃副本 data/_runtime/agent-v02-work/
├─ ai-quant-platform（前端 Next.js + 后端 quant_system/FastAPI）
│   ├─ P1：/asia-radar 独立页面（markets 分组）+ 专用 API + Futu 12 ETF 真实数据
│   ├─ P3：板块价格/成交量动量 → 修复后作为普通实验 → /strategies + /backtest
│   └─ P2：DiffsFormer 思路 → 隔离研究实验 → Experiments / Factor Lab / Unified Results
└─ Hermes-quant-agent（后续：定时分析、告警、发布 market_foresight artifact；Phase 1 不做）
```

**P1 垂直切片（第一个可开工交付）**：Asia Radar Phase 1 —— 12 市场真实 ETF 排名/收益/
波动/回撤/K型分化独立页面。平台负责页面、API、数据适配；HQA 后续才接定时与 foresight。

## 2. P1：Asia Radar（独立页面 `/asia-radar`）

### 2.0 状态

- **Phase 1（2026-08-10，Codex 交付，我方复审通过）**：12 Futu ETF 真实闭环、fail-closed、
  无模拟估值、动态 K 型、三页签空壳、markets 导航、徽章。验收清单见 §2.5。
- **Phase 1.1（同日，我方补强）**：timezone 契约、k_shape 口径文案、EquityBarCache 复用
  （futu vs futu_cache 可审计）、最新共享 session 对齐、盘中 bar 规则、空 K 型态、负例测试、
  晨报导语“平台模板提示”泄漏修复。

### 2.1 产品定位

> 亚洲 12 市场表现、AI 驱动分化和数据质量雷达

**不是**完整泡沫判定器。价格/波动/回撤/K型分化可真实闭环；PE/PB、ERP、行业拥挤度、
个股风险名单在可靠跨市场数据到位前**不展示**（或标"待接入"占位，绝不显示模拟结论）。

### 2.2 页面结构（Phase 1）

1. 12 市场热力图 + 排名
2. 周/月/YTD 收益、波动率、最大回撤
3. AI 赢家 vs 落后市场的**动态** K 型分化（禁止硬编码赢家/输家名单）
4. 市场详情三页签：**指数**（Phase 1 可空/待接入）、**ETF 代理**、**龙头驱动**（Phase 1 仅预留字段与 UI 壳）
5. 数据质量栏：provider、symbol、币种、时区、截至时间、是否代理、覆盖范围、限制
6. 每张图强制徽章：`真实 / 代理 / 静态 / 演示` + 数据截至时间

### 2.3 数据模式（显式三分）

| 模式 | Phase 1 | 说明 |
|---|---|---|
| 跨市场可比 | ✅ 12 个 Futu 美股国家 ETF | 统一美元、美国收盘时间 |
| 本地市场 | ❌ 延后 | 日经/恒指/TAIEX 等；需扩展 Futu 多市场代码或 TWSE/Twelve Data |
| 龙头驱动 | ⬜ UI 预留 | 三星+海力士 / 台积电等；展示相关/Beta/R²/跟踪误差/训练截止日；**不替换指数收益** |

12 ETF 映射（第一版代理）：

| 市场 | ETF |
|---|---|
| 韩国 | EWY |
| 台湾 | EWT |
| 日本 | EWJ |
| 中国沪深300 | ASHR |
| 印度 | INDA |
| 印尼 | EIDO |
| 香港 | EWH |
| 新加坡 | EWS |
| 泰国 | THD |
| 马来西亚 | EWM |
| 澳大利亚 | EWA |
| 菲律宾 | EPHE |

### 2.4 技术归属与改造点

- **前端**：`app/asia-radar/page.tsx` + 侧栏 `marketsSection` 增项；按 HQA 设计体系重做，
  参考原 dashboard 信息架构与视觉密度，**不 iframe、不 copy HTML/JS**。
- **后端**：
  - 新增专用 API（建议 `/api/asia-radar/*`），**不得**复用通用 `/ohlcv` 的 sample 静默回退路径；
  - 强制 `provider=futu`（或显式白名单），失败 → 400/stale + 前端错误态，永不 sample；
  - 指标计算在 `quant_system/factors/asia_radar/`（或等价路径）**重写**：YTD/周/月收益、
    波动、回撤、跨市场 K 型分化指数；不引入 demo_generator。
- **数据适配**：Phase 1 只用现有 Futu 美股适配器（plain ticker）；不改 `normalize_symbol`
  去接本地指数（那是 Phase 2）。
- **HQA 侧**：Phase 1 **不做**定时任务与 foresight 发布；先把页面/API 真实闭环做通。

### 2.5 验收标准（Phase 1 必须全过）

- [x] 12 个 ETF 全部来自 Futu 真实日线，响应 meta 含 provider/symbol/currency/as_of/adjustment
- [x] 关闭 OpenD 或强制 provider 失败时，页面显示错误/stale，**不会**出现 sample 曲线
- [x] 无 PE/PB/ERP/拥挤度/个股风险名单的模拟数字；若有占位，明确标"待接入"
- [x] K 型赢家/输家由当期收益动态计算，非硬编码
- [x] 侧栏 markets 分组可见 `/asia-radar`；不引入原项目品牌/研报原文/LICENSE 风险文件
- [x] 现有 pytest gate + 前端 lint/build 通过；新增 API/指标单测用录制样本，不依赖外网 CI

Phase 1.1 附加：
- [x] overview 与 market.meta 含 `timezone=America/New_York` 与 `provenance=futu|futu_cache`
- [x] 所有市场对齐到最新**共享** session 的 as_of；短历史/缺 ETF/非 Futu provenance → 503
- [x] 响应体瘦身：history 仅保留最近 90 根 sparkline；K 型空序列显示明确空态
- [x] 晨报导语不再出现“平台模板提示”；半导体/软件相对强弱按当日真实差值生成

Phase 1.2（同日交付，只读扩展）：
- [x] `GET /api/asia-radar/summary` 只读摘要（同一 fail-closed Futu 契约），供晨报/通知使用
- [x] 晨报导语在确定性市场手记后追加 1 句亚洲雷达概括；数据不可用时明示“亚洲雷达数据暂不可用”
- [x] 归档 payload 新增可选 `asia_radar` / `asia_radar_note`（含 provenance）
- [x] `quant-system data asia-radar-refresh` 日更 CLI：暖 12 ETF bar 缓存并持久化 `<as_of>.json` 快照
- [x] `com.aiquant.asia-radar-refresh` LaunchAgent（17:05 本地，calendar interval）接入 `local_mac_stack` start/stop/status/logs
- [x] CLI 测试覆盖快照写入、provider 失败 fail-closed、`--no-write-snapshot`

### 2.5b Phase 1 复审 findings（已处理/留档）

| ID | 级别 | 处理 |
|---|---|---|
| AR-B01 跨 ETF 最新 bar 不对齐放行 | medium | **已修**：对齐 min(last_dates)，缺共享 session 即 503 |
| AR-B02 短历史静默 clamp 出周/月收益 | medium | **已修**：`_MIN_HISTORY_BARS=64`，不足即 503 |
| AR-B03 盘中未完成日 bar 无过滤 | medium | **已修**：按 America/New_York 16:00 收盘裁剪 end；当日未收盘不纳入 |
| AR-B05/B06 负例少、串行直打 OpenD | low/medium | **已修**：补负例；默认接 `EquityBarCache`（TTL 1 天），provenance 区分 `futu`/`futu_cache` |
| FE-01 空 K 型仍画空图 | low | **已修**：显示“当前自然年尚无可用的 K 型序列” |
| FE-02/FE-05/FE-07 前端口径展示与测试 | low/nit | **已修**：徽章显示 timezone/provenance；methodology 折叠层展示口径表；新增动态赢家/空态/视图源测试 |
| F2/F3/F4/F5 测试可糊弄 | medium | **已修**：非 futu provenance、缺 ETF、短历史、赢家翻转、as_of 对齐均有断言；API 成功路径要求 timezone/provenance |

### 2.6 后续阶段（本期 plan 可写清，不在 Phase 1 交付）

- **Phase 2**：扩展 Futu 多市场代码适配；接入日经/恒指/TWSE；韩国评估 Twelve Data 或 KRX 合同
- **Phase 3**：样本外验证的龙头映射（点时权重）、估值数据；HQA 定时 + market_foresight 告警

### 2.7 数据日更落库与晨报接入（Phase 1.2 已交付最小闭环）

用户提出的方向，最小只读闭环已落地；后续可在此之上扩展：

1. **日更落库**：`quant-system data asia-radar-refresh`（默认）把 12 ETF QFQ 日线写入
   `EquityBarCache`，并把当日 overview 快照写到 `data/api_runs/asia_radar/<as_of>.json`；
   `com.aiquant.asia-radar-refresh` LaunchAgent 每日 17:05 本地运行。页面默认优先读缓存，
   provenance 标 `futu_cache`；失败保留上一版并标 stale。hqa 侧如另需自有调度，
   只须在同一 CLI 上挂 automation，不再重复实现取数。
2. **晨报接入**：晨报导语在“平台市场手记”后追加 1 句确定性亚洲雷达概括
   （动态赢家/输家、YTD 前三后三分化、截至日期、provenance）。复用同一 fail-closed
   `/api/asia-radar/summary`，缺数据时明示“亚洲雷达数据暂不可用”，绝不生成模拟句子。
3. **导语文案纪律**：刊出语不出现“平台模板提示/确定性模板”等实现性措辞；
   半导体 vs 软件与亚洲概括均按当日真实数据差值输出。

### 2.8 行情浏览页热力化 → 定稿并交付：独立“市场横截面”视图（Phase 1.5）

`data-explorer` 保持单标的 OHLCV 诊断面，**不**在原页硬塞热力图。横截面做成独立只读视图，
避免污染 K 线页、也避免和 Asia Radar 的固定 12 国宇宙混淆。

三个边界已按推荐定案：

1. **标的池来源**：Phase 1.5 用**预设篮子**（无自选/无持仓依赖、无写路径）：
   - `ai_watch`：SPY QQQ SOXX IGV SMH NVDA MSFT GOOGL AMZN META AAPL TSLA
   - `us_sectors`：SPY XLB XLE XLF XLI XLK XLP XLU XLV XLY XLC XLRE
   - 另支持显式 symbol 列表（白名单、≤16 只）
2. **provider 策略**：**强制严格 Futu**（与 Asia Radar 相同），失败 400/503，不回退 sample。
   复用 `read_historical_prices(provider="futu")` + `EquityBarCache`，provenance 区分
   `futu` / `futu_cache`。
3. **与 Asia Radar 边界**：Asia Radar = 固定 12 国 ETF 代理宇宙，用于跨国家观察；
   横截面 = 自定义/预设标的篮子（主题/板块），用于自选维度。两者共享数据通路，
   不共享宇宙、不互替产品位。

**已交付（2026-08-11，commit `844626e`）**：
- 后端 `quant_system/factors/market_cross_section.py` + `GET /api/market-cross-section?basket=…&symbols=…`。
- 指标与 Asia Radar 同口径：YTD/周/月收益、63 日波动、YTD 最大回撤、rank；共享 session 对齐。
- 前端 `/market-cross-section` 视图（markets 分组入口）：热力图 + 排序表 + 徽章
  （Futu 真实/缓存、as_of、America/New_York）。无估值/拥挤/风险名单。
- 测试：篮子合法性、缺 symbol fail-closed、provenance 缓存区分、排名动态性、前端渲染/错误态。

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

- 三档统一：取数失败 → 显式降级（stale 标记 / 报错），**绝不静默退回 demo/sample 数据**；
  前端展示数据来源徽章（真实/代理/静态/演示 + as_of）。
- P1 Asia Radar 专用 API **禁止**走通用 `/ohlcv` 的 sample 回退；强制 provider=futu。
- 不加载来源不明的 `.pkl`/`.pt`；不把任何凭据（含 neodata TOKEN）复制进仓库。
- 所有新增写操作遵循本地 trust mode；对外 public write 默认 OFF；不动 live_trading。

## 6. 测试

- P1：12 ETF 指标单测（录制样本）；专用 API 契约测试（含"provider 失败不得 sample"负例）；
  `/asia-radar` 前端渲染与数据质量栏断言；OpenD 不可用时的错误态 E2E（可选）。
- P3：轮动信号单测（次日执行对齐）；回测集成与库内基准同口径。
- P2：实验登记元数据校验（本期不实现训练）。
- 全部改动过现有 pytest gate 与前端 lint/build。

## 7. 交付顺序

1. **P1 Asia Radar Phase 1**（本轮可开工）：`/asia-radar` + 专用 API + Futu 12 ETF 真实闭环。
2. P1 Phase 2/3（本地指数、龙头映射、HQA 定时）—— 另开 plan。
3. P3 板块动量实验（修复口径后重跑）。
4. P2 DiffsFormer 实验构想登记（仅文档 + 元数据）。

## 8. 明确不做（YAGNI）

- 不 copy 原项目源码/HTML/JS/JSON/品牌/研报原文；不整目录复制；
- 不 iframe 原 dashboard；不把 demo/sample 标成真实；
- Phase 1 不展示 PE/PB/ERP/行业拥挤度/个股风险名单的模拟结论；
- Phase 1 不做 HQA 定时、不做 market_foresight 发布、不扩展 Futu 多市场代码；
- 不为板块动量单独建首页 tab；不做达摩院实时选股/展示报告/加载模型权重；
- 不动 kill_switch / live_trading / public write 默认。
