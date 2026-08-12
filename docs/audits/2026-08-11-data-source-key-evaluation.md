# 第三方数据源 API Key 实测评估 — Hermes Quant Agent

**Date:** 2026-08-11
**Scope:** Finnhub / Alpha Vantage / Tiingo / Twelve Data / Polygon / NewsAPI — 用户提供 key 的文档调研 + 真实 API 冒烟测试
**Method:** 12-agent 对抗工作流（每 provider 1 个实测 agent + 1 个对抗复核 agent，~45 万 subagent token，147 次工具调用；原始响应落盘 `$TMPDIR/probe-<provider>/`，复核 agent 逐份重读并部分重放调用）
**Result:** 6/6 key 全部有效；5/6 报告经复核确认（`refuted=false`），Twelve Data 报告被部分推翻（`refuted=true`），修正项已并入本文
**Key hygiene:** 所有 key 仅经 `$TMPDIR` env 文件注入，未写入任何仓库/文档/memory；本文只出现掩码标识

---

## 1. 结论一览

| Provider | Key 有效 | 档位（实测） | 最强用途 | 致命短板 | 接入建议 |
|---|---|---|---|---|---|
| **Twelve Data** `321a…50fb` | ✅ | Basic 免费（8 credits/min、800/日，`/api_usage` 实测） | **ETF 日 bars 灾备**（11.6 年复权 OHLCV，1 credit/symbol，当日补齐前一 session）；免费 `/statistics` 基本面快照 | 非美市场数据全部 plan-gated（HSI/N225/000300 均 404 伪装成"无效 symbol"）；无新闻端点 | **P1 接入**：ETF bars 备份 + 估值快照 lane |
| **Tiingo** `5a4a…8e46` | ✅ | 非标准/legacy 档（含 fundamentals add-on；**News 403**） | **ETF 日 bars 主备份**（EWH 自 1996 年 inception 全史，raw+CRSP 复权+divCash/splitFactor 同行返回） | 零国际覆盖（HK 404、A 股 .SS 404、无任何指数）；本 key 无新闻权限 | **P1 接入**：ETF bars 深历史灾备 + 基本面日频时序（市场 cap/PE/PB/EV） |
| **Polygon** `U9MS…mhye` | ✅ | Stocks Basic 免费（5 req/min） | **美股全市场 grouped daily 一把抓**（一次调用 12,408 ticker，12 ETF 全覆盖）；实时新闻流（当日文章）；原始财报三表 | 仅 2 年历史（2015 请求 403 NOT_AUTHORIZED）；EOD T+1；零亚洲指数/港股；financials 免费可用但与付费矩阵不符（随时可能收紧） | **P2 接入**：basket 批量刷新 lane（1 次/日 grouped 调用即可刷全部 12 ETF） |
| **Finnhub** `d1hm…11a0` | ✅ | 免费档（60 req/min） | **免费基本面最丰富**（AAPL 实测 133 个 metric：cap/PE(TTM)/PB/EV/forward PE/beta…）；美股实时 quote；通用新闻（100 条） | **无任何历史 K 线**（`/stock/candle` 403）；亚洲指数按"CFD indices"要付费订阅；ETF holdings、全部指数成分股 403 | **P2 接入**：估值字段首选免费源（PE/PB/cap）；bars 不可用 |
| **Alpha Vantage** `BZET…3C1W` | ✅ | 免费档（25 req/日硬顶） | **意外亮点：A 股个股**（600104.SHH 实测当日刷新，.SHH/.SHZ 后缀）；OVERVIEW 基本面 55 字段免费；NEWS_SENTIMENT 带情感分 | 25 请求/日烧不起多 symbol 日刷；免费版只给 100 根原始 bar（复权与全史均 premium）；港股/日韩台新澳全无；错误一律 HTTP 200+`Information` 字段 | **P3 限定接入**：低频估值/情感字段；A 股个股观察仓（每日 ≤20 只预算内） |
| **NewsAPI** `2eca…4a38` | ✅ | Developer 免费档（100 req/日） | 晨报新闻 lane 可原型化（`hang seng` 检索 201 条、business headlines 68 条） | **ToS 仅限 localhost 开发用途**（技术不拦，部署即违约；生产档 $449/月）；24h 延迟、1 个月历史硬顶（HTTP 426）、正文截断 214 字符；business 源仅 13 家、无 HK 本地英文源 | **只用于本地晨报原型**；不进任何常驻服务路径 |

### 一句话接入定位

- **能补的**：ETF 日 bars 灾备（Twelve Data / Tiingo / Polygon 三选一+互备）、估值字段 PE/PB/cap（Finnhub 免费最划算，Tiingo 有日频时序）、晨报新闻（NewsAPI 本地原型 / Finnhub / Polygon 当日新闻）、A 股个股轻观察（Alpha Vantage，25 req/日预算内）。
- **补不了的**：**亚洲本地指数 lane 全军覆没**——HSI/N225/CSI300/KOSPI/TWII/STI 在六家的免费档要么 plan-gated（Finnhub CFD 订阅、Twelve Data Grow $79/月起）、要么根本不存在（Tiingo/Polygon/NewsAPI），要么静默空响应（Alpha Vantage）。Slice 2A 的 HK.800000/JP..N225 继续依赖 Futu；韩/台/新/澳等白名单外市场维持诚实 pending，不靠这批 key 填。
- **Futu 主链路地位不变**：第三方源一律作为带独立 provenance 徽章的备份/补盲 lane（契约见 spec §2.9a）。

---

## 2. 分 Provider 实测详情

### 2.1 Twelve Data — 推荐 P1（ETF bars 灾备 + 估值快照）

- **档位实证**：`/api_usage` 返回 `plan_category="basic"`，`plan_limit=8 credits/min`、`plan_daily_limit=800/day`；`/profile` 403 明示 "available exclusively with grow or pro or ultra…"。
- **ETF 日 bars**：`/time_series?symbol=EWH&interval=1day` 实测取回 **2015-01-02 → 2026-08-10 共 2,917 根**（单次调用，outputsize 上限 5000）；最新 bar 为前一 session，复权默认 `adjust=splits`（`all/dividends/none` 可选）；1 credit/symbol。
- **基本面**：`/statistics` 免费返回 market_cap / trailing_pe / forward_pe / price_to_book_mrq / margins / ROE / revenue_ttm 等；注意**财报三表端点 100 credits/symbol**（免费档 8 次就烧光日额）。⚠️ 复核修正：官方 pricing 页把 "Fundamentals data" 列为 Grow+ 功能——今日免费可用属实但属"宽于矩阵"，不可依赖其长期稳定。
- **国际覆盖**：参考目录免费（HSI、N225 都能搜到 plain symbol），但 `time_series` 对 HSI/N225/000300 一律 **404 plan-gate**（伪装成 symbol 无效，不是 403——客户端必须把 404 当额度问题处理）。复核修正：全球 EOD 实际价格为 **Grow $79/月**（年付 $66/月），非报告原述 $29。
- **配额可见性**：复核修正——每个响应头带 `api-credits-used` / `api-credits-request` / `api-credits-left`，无需单独调 `/api_usage`。
- **无新闻端点**（任何档位都没有，最近的是 Fundamentals 下的 Press releases）。

### 2.2 Tiingo — 推荐 P1（ETF 深历史灾备）

- **档位**：非标准 legacy 档——Fundamentals add-on（现行付费附加项）可用返回 200，但 `/tiingo/news` 403 "You do not have permission to access the News API"（现行文档称全档位含 News）。账户权利与公开矩阵不完全对应，集成时应以实测为准。
- **ETF 日 bars**（本 key 最强项）：EWH **自 1996-03-12 inception 起全史**（复核 agent 重放确认）；raw 与 CRSP 方法论复权值同行返回，附 `divCash`/`splitFactor`；EOD 每日 17:30 EST 前齐；EWJ/ASHR/MCHI 同测可用。
- **基本面日频时序**：`/tiingo/fundamentals/<t>/daily` 返回 marketCap / enterpriseVal / peRatio / pbRatio / trailingPEG1Y 的时间序列——六家中唯一能直接做"估值时序因子"的源（新免费账户需付费 add-on，本 key 已有）。
- **国际覆盖**：0700.HK 404、600519.SS 404（pricing 页仍宣传 "US & Chinese Stocks"，实测格式失败，疑已弃用）、无任何指数 ticker。亚洲敞口只能走美股 ETF 代理。
- **限额**（pricing 页）：50 req/hr、1,000 req/日、500 unique symbols/月、1 GB/月；无 x-ratelimit 头。

### 2.3 Polygon — 推荐 P2（basket 批量刷新 + 当日新闻）

- **档位实证**：2015 年历史请求 403 `NOT_AUTHORIZED "Your plan doesn't include this data timeframe"`（对应 Basic 2 年窗口；精确边界未做二分探测，实测只证明"封顶在 ~2016-2026 之间，官方称 2 年"）；5 req/min，无 429。
- **Grouped daily**（独家亮点）：`/v2/aggs/grouped/locale/us/market/stocks/<date>` 一次调用返回 **12,408 个 ticker 全市场日 bar**（~1.35 MB）——横截面 basket 刷新成本 = 1 次调用/日，12 ETF + 任意自定义 basket 全包。
- **单 ticker bars**：`/v2/aggs/ticker/EWH/range/1/day/...` adjusted/raw 均可，T+1 EOD。
- **新闻**：实测返回**当日文章**（2026-08-11T10:10Z），带 publisher/published_utc/ticker 标签——六家中唯一"当日"新闻源（对照 NewsAPI 24h 延迟、Tiingo 403）。
- **基本面**：`/vX/reference/financials` 返回原始三表 line items（TTM 至 2026-06-27），**但与付费矩阵不符**（pricing 页列为 Advanced $199/月 或 $29/月 add-on）——能用但不写死依赖。
- **国际覆盖**：XHKG 空、指数宇宙纯美系（Dow Jones Americas），HSI/N225 检索为空；KOSPI/TWII/STI 未逐个实测（按宇宙构成推断不存在）。
- **注意**：polygon.io/pricing 已 301 到 massive.com（品牌更名），API base `api.polygon.io` 不受影响。

### 2.4 Finnhub — 推荐 P2（免费估值字段首选）

- **免费档实证**：US quote 实时（EWH c=22.8，t=2026-08-10 20:00 UTC 收盘）；`/stock/metric?symbol=AAPL&metric=all` **133 个字段**（marketCapitalization=4.47T、peTTM=34.72、pbAnnual=50.98、EV、forwardPE、beta、52 周高低、股息、利润率…）；`/news?category=general` 100 条。
- **硬门槛**：`/stock/candle`（历史 K 线）403——**免费档零历史 bars，无法进入 bars lane**；`/etf/holdings` 403；`/index/constituents` 连 ^GSPC 都 403；0700.HK 403；^N225/^HSI 返回 HTTP 200 + body "Market data subscription required for CFD indices"（**错误语义不一致**：403 JSON vs 200+错误体，客户端必须检查载荷）。
- 韩国 ^KS11 未实测（复核修正：verdict 中不应把 KS11 的 gate 当作已观测事实；按同一 CFD gating 推断）。
- 限额：60 req/min（官方）；无 x-ratelimit 头。

### 2.5 Alpha Vantage — 推荐 P3（低频限定）

- **免费档实证**：`TIME_SERIES_DAILY_ADJUSTED` 与 `outputsize=full` 均返回 "premium endpoint/feature"；免费版 = **100 根原始（未复权）bar**，EOD（Last Refreshed=前一交易日）。
- **意外亮点——A 股个股**：`600104.SHH`（上汽）当日刷新实测成功，`.SHH`/`.SHZ` 后缀可用；CSI300 指数本身不支持；**港股 0700.HKG 报 Invalid API call，日/韩/台/新/澳无后缀**；`^N225` **静默返回空 JSON `{}`**（无错误字段——最危险的一种失败模式）。
- **基本面**：`OVERVIEW` 55 字段免费（MarketCap/PERatio/PriceToBookRatio/EPS/Beta/DividendYield/AnalystTargetPrice…），一次调用一 ticker。
- **新闻**：`NEWS_SENTIMENT` 免费，带 per-ticker relevance + sentiment 分数/标签（quirk：`limit=5` 实际返回 50 条，最小批次 50）。
- **配额**：25 req/日硬顶（多来源佐证 5 req/min 软限）——12 ETF 一次日刷就烧掉一半，只配做低频估值/情感字段与 ≤20 只 A 股个股观察。
- **错误模型**：一切错误/拒绝都是 HTTP 200 + `Error Message`/`Information` 字段——基于状态码的错误处理会静默漏判。

### 2.6 NewsAPI — 仅限本地晨报原型

- **免费档实证**（三重证据）：旧历史查询 HTTP 426 "as far back as 2026-07-10"（恰 1 个月）；最新文章 ~24h 前；content 截断 214 字符 `[+N chars]`。
- 功能：`/everything`（`hang seng` 201 条、`hong kong stocks` 350 条）、`/top-headlines`（business 68 条）、`/sources`（business 仅 13 家，无 SCMP/HKET 等港媒）。
- **ToS 红线**：Developer 档契约上 localhost/开发专用——技术上从本机调用未被拦（非 IP 级强制），但**任何常驻 HQA 服务路径使用即违约**；生产档 Business $449/月。晨报原型阶段可用 title+description+url（正文拿不到）。

---

## 3. 对 HQA 需求矩阵的映射

| HQA 需求 | 现状 | 本批 key 能否补 | 首选源 |
|---|---|---|---|
| 12 ETF 日 bars（Asia Radar / 横截面） | Futu OpenD 主链路 ✅ | ✅ 可灾备 | Tiingo（深历史）/ Twelve Data（11.6y）/ Polygon（grouped 1 次抓全） |
| 本地指数 lane（HK/JP 已有 Futu） | HK.800000 + JP..N225 ✅ | ❌ 无需替换 | Futu 保持 |
| 韩/台/新/澳等 pending 市场 | 诚实 pending | ❌ 全部 plan-gated 或不存在 | 维持 pending；可选项：Twelve Data Grow $79/月 |
| A 股指数 CSI300 | 权限未开通 pending | ❌（指数本体都不行） | Alpha Vantage 仅个股（.SHH/.SHZ），Futu 开权限仍为正解 |
| 估值字段 PE/PB/cap | 无（spec Phase 1 禁模拟） | ✅ | Finnhub `/stock/metric`（免费 133 字段）；Tiingo 有日频时序 |
| 龙头驱动映射（Slice 2B） | 未开工 | ⚠️ 部分 | Polygon grouped 覆盖美股龙头；Finnhub 成分股 403 不可用 |
| 晨报新闻 lane | 无 | ✅（限定） | Polygon（当日）；Finnhub（100 条）；NewsAPI（本地原型，ToS 限 localhost） |
| 情感分字段 | 无 | ✅ | Alpha Vantage NEWS_SENTIMENT（25 req/日预算） |

## 4. 落地契约（接入时必须满足）

与 spec §2.9a 一致：

1. **永不静默顶替**：第三方数据带 `provider`/`provenance` 字段 + 前端徽章；切换备份源显式记录降级原因。
2. **fail-closed 不变**：专用 API 仍禁 sample 回退；备份源失败 = 诚实 unavailable。
3. **配额建模**：AV 25 req/日、Twelve Data 800 credits/日（响应头可读余量）、Tiingo 1,000 req/日、Polygon 5 req/min、NewsAPI 100 req/日——调度层显式预算，超出排队/降级。
4. **错误模型适配**：Alpha Vantage 全 200+字段、Finnhub 200+错误体、Twelve Data 404=plan-gate——每个 connector 必须做载荷级错误检测，不得只看 HTTP 状态。
5. **合规**：NewsAPI 只进本地原型路径；Polygon/Twelve Data "宽于矩阵"的免费功能（financials、statistics）不写死依赖。
6. **Key 管理**：明文永不入仓/入文档/入 memory（本报告仅掩码）；集成时放 gitignored `.env`。

## 5. 复核声明（对抗验证记录）

- 5/6 报告 `refuted=false, confidence=high`；全部原始响应落盘可重放，复核 agent 对部分关键声明做了真实重放（Tiingo fundamentals 200、EWH 1996 深度、NewsAPI 426 等）。
- **Twelve Data 报告 `refuted=true`**，已并入修正：Grow 价格 $79/月（非 $29）；响应头带 `api-credits-*` 余量（非"无配额头"）；`/statistics` 免费可用与官方矩阵不符（Grow+ 功能）。
- 次要修正（不改结论）：Finnhub ^KS11 未实测（verdict 已降级为推断）；Polygon 历史边界未二分探测；Alpha Vantage "EOD-only" 为文档推断（探测在盘前执行，无法区分实时与前收）。
