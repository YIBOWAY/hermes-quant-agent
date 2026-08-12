# Full-Stack Browser QA Re-Run — Hermes-quant-agent / ai-quant-platform

**Date:** 2026-08-11 (afternoon re-run)  
**Base URL:** `http://127.0.0.1:3001` (BFF/frontend) · Backend `:8765` · Hermes `:8642`  
**Overall verdict:** `PASS_WITH_WARNINGS`  
**Public release:** **UNAUTHORIZED** (`release_authorized=false`; no `release_stamp_id` / `public_cutover_id`)  
**Prior same-day report:** [`2026-08-11-full-stack-browser-qa-report.md`](./2026-08-11-full-stack-browser-qa-report.md)  
**Artifacts:** `artifacts/browser-qa-2026-08-11-rerun/`  
**Multi-agent workflow:** `wf_fca202d6-ecc` (14/16 agents done; research-surfaces + options-suite stream-errored — covered by primary live evidence)

---

## 1. Executive verdict

| Field | Value |
| --- | --- |
| **overall_verdict** | **PASS_WITH_WARNINGS** |
| **Public cutover** | **OFF / unauthorized** — local dark only |
| **Live trading risk** | **None observed** (`live_trading_enabled=false`, `kill_switch=true`) |
| **Journey FAIL count** | 0 (product); 2 workflow agents stream-errored, not product FAILs |
| **P0 / P1 findings** | 0 / 0 |
| **P2 / P3 findings** | 1 / 2 product · plus ops backlog (not elevated as product defects) |

Local full-stack surfaces under the owner session are healthy and **materially improved** vs the earlier same-day pass:

1. **Managed Web Chat write path proven end-to-end** (was explicitly untested before): 新建空白对话 → compose → 发送 → connector queue → durable Run → assistant reply. Workflow agent independently re-proved a second session (`web_c3a7e771…`) with flag-accurate safety wording.
2. **Prior P2 position-map freeze affordance is FIXED** (买入/卖出/新建模拟订单/提交模拟订单 disabled + freeze banners). Residual cosmetic P3 only (drawer side toggles).
3. **Unified results catalog no longer degraded** (`read_status=available`; automation 4/4 FRESH).
4. **Daily-close automation recovered** (workbench shows 4/4 FRESH; earlier report had daily_close failure).
5. **Mobile Hermes + EN locale** re-verified PASS by workflow (390×844, no H-overflow, secrets redacted).

Remaining product issue is **brief SAMPLE provenance honesty** (still P2; primary live + code evidence — workflow research agent did not complete). Residual product P3s: drawer side-toggle polish; one historical chat line saying「长桥 Paper」while account is local/default + Futu snapshot. Ops backlog (LaunchAgents idle, options scan stale, horizon standby empty) tracked separately.

This is **not** a public-release gate pass. `chat_write_ready=true` / `composer_write_ready=true` / connector liveness ready remain **gate-separated** from `release_authorized=false`.
---

## 2. Runtime identity & safety (health facts)

### 2.1 Probe summary

| Check | Result |
| --- | --- |
| `backend_ok` | true (`:8765/api/health`) |
| `frontend_ok` | true (`:3001` → `/en/hermes` 307, pages 200) |
| `hermes_ok` | true (`:8642/health` → hermes-agent **0.20.0**) |
| `database reachable` | true |
| `futu_opend reachable` | true |
| `docker postgres` | Up (43h) `127.0.0.1:5432` |
| Base URL | `http://127.0.0.1:3001` |

### 2.2 Hermes command ledger / admission

| Flag | Value | Interpretation |
| --- | --- | --- |
| `schema_ready` | true | Ledger schema ready |
| `mutation_enabled` | true | Local dark mutation path present |
| `composer_write_ready` | true | Local dark only — **not** public cutover |
| `chat_write_ready` | true | Local dark only — **not** public cutover |
| `admission_mode` | `local_trust` | Identity ritual bypass; **does not** authorize factor promotion |
| `candidate_admission_id` | null | No candidate identity under local_trust |
| `connector_mode` | `supervised_dispatch` | Supervised connector |
| `connector_liveness_ready` | true | Heartbeat fresh |
| `connector_worker_id` | `agent-v02-release-local-1` | |
| `release_authorized` | **false** | **No public release stamp/cutover** |

Gateway BFF (`/api/hermes/gateway`): `connected=true`, `session_api_available=true`, run submission/events/stop features present, blockers empty.

### 2.3 Safety envelope (FE ↔ BE byte-consistent)

Adversarial verify: `:3001` and `:8765` returned **identical** bodies for `/api/health` (1296 B) and `/api/safety/effective` (362 B).

| Flag | Value |
| --- | --- |
| `dry_run` | true |
| `paper_trading` | true |
| `live_trading_enabled` | **false** |
| `kill_switch` | **true** |
| `canonical_account_frozen` | true |
| `current_paper_authority_epoch` | **197** |
| bind | `127.0.0.1` |

**UI banner (consistent across journeys):**  
`仅模拟 · 实盘交易已禁用 · 全局熔断开关 开 · 模拟账户冻结 开 · 论文安全权威 就绪 (纪元 197) · 接口 available`

### 2.4 Auth / mutation fail-closed samples

| Probe | Result |
| --- | --- |
| Unauthenticated `GET /api/workspace/ws-local-main/snapshot` | **401** `workspace_auth_failed` + safety envelope |
| Owner-session same endpoint (browser cookie) | **200** |
| `POST /api/paper/account/orders` under freeze | **409** `account_frozen` |
| `POST /api/paper/account/rebalance` under freeze | **409** `account_frozen` (journey agent) |

### 2.5 LaunchAgents / ops

| Service | State |
| --- | --- |
| `ai.hermes.gateway` | running |
| `com.aiquant.backend` | running |
| `com.aiquant.frontend` | running |
| `com.aiquant.agent-v02-connector` | running |
| `com.aiquant.factor-automation` | **loaded, not running** (`pid=none`) |
| `com.aiquant.asia-radar-refresh` | **loaded, not running** (`pid=none`) |

Workbench UI (live): **自动化 4/4 正常** · daily_close · freshness · weekly · notification_drain · **4/4 FRESH** · last success 2026-08-11 16:17.  
Results API: `read_status=available`, total=8, no degradation warnings.

---

## 3. Journey matrix (area → verdict)

| Area | Verdict | Console errors (product) | Critical network | Notes |
| --- | --- | --- | --- | --- |
| hermes-workbench + **chat write** | **PASS_WITH_WARNINGS** | none critical | 200 on session/act/messages | E2E write proven twice; residual historical「长桥」wording P3 |
| research-surfaces | **PASS_WITH_WARNINGS** | none | 200 | Brief SAMPLE gap remains P2 (primary evidence; WF agent stream-errored) |
| paper-trading / position-map | **PASS** | noise only | freeze 409 correct | Prior freeze P2 **fixed**; cosmetic drawer P3 |
| options-suite | **PASS_WITH_WARNINGS** | none | 200 | daily-scan still 1d stale; `/api/options/radar` 404 (API probe) |
| markets-quark | **PASS** | basket 400 noise | mostly 200 | Horizon standby + KS local_index claims **refuted** as product defects |
| system-settings + mobile | **PASS** | none | 200 | secrets redacted; 390px no H-overflow; EN clean |
| route crawl (26 pages) | **PASS** | — | 25/26 HTTP 200; polymarket 1× timeout then 200 | |

**Journey FAIL count (product):** 0  
**Workflow agent errors (harness):** research-surfaces, options-suite — `Stream error: error decoding response body` (not product FAILs; primary DOM/API still cover those areas).
---

## 4. Headline proof — managed Web Chat write path

Previously listed under “Not tested”. This re-run **proved** local-dark chat:

| Step | Evidence |
| --- | --- |
| Open `/zh/hermes` | Safety banner + automation 4/4; composer locked until managed session |
| Click **新建空白对话** | `POST /api/workspace/ws-local-main/act` **200**; URL gains `hermes_session_id=web_557ad7c4…` |
| Composer unlock | Textbox enabled; status “新的受管 Web 对话已就绪。” |
| Send read-only safety question | User message appears; status “排队中 · 8c87f211…”; Run `run_87cf4565…` |
| Assistant completes | Status **已完成** / **已成功**; final Hermes line: **「当前为长桥 Paper Trading（模拟盘）账户，不允许实盘交易。」** |
| Screenshots | `artifacts/browser-qa-2026-08-11-rerun/hermes-workbench.png`, `hermes-chat-success.png` |

Constraints observed during run: composer disabled while turn in flight; spine-driven refresh (not provider token passthrough); tool/system messages collapsed in UI. **No live trading path opened.**

---

## 5. Confirmed findings (P0/P1 first)

Severity after primary live evidence **plus** adversarial workflow verification (`wf_fca202d6-ecc` synthesis). Ops backlog is listed separately and is **not** counted as product P2/P3 unless it misleads operators on an active path.

### Severity rollup

| Severity | Count | Titles |
| --- | --- | --- |
| **P0** | **0** | — |
| **P1** | **0** | — |
| **P2** | **1** | brief SAMPLE provenance still missing badge |
| **P3 product** | **2** | drawer side-toggle cosmetic; historical chat「长桥 Paper」wording |
| **Ops backlog** | **4** | options stale scan; horizon standby empty; LaunchAgents idle ×2 |

### P2 (open) — product

#### P2-1 · Brief run log still promotes SAMPLE backtest as “平台记录回测” without SAMPLE badge
- **Dimension:** ux-flow / provenance honesty  
- **Detail:** Daily brief links `backtest-20260809T194031Z-2f374376` as **平台记录回测 · Sharpe 19.01 · Return 4.85%** with **no** SAMPLE/NOT REAL badge. Dedicated backtest detail correctly shows `sample / not real` and “演示数据 — 以下指标来自合成的 sample 数据源…”. API confirms `metadata.source=sample`, `metadata.request.provider=sample`.  
- **Root (code):** `src/frontend/app/brief/page.tsx` `buildRunAction` hardcodes `平台记录回测` for `kind=backtest` without consulting sample/provider.  
- **Evidence:** live `/zh/brief` a11y snapshot; SSR HTML; `GET /api/backtests/backtest-20260809T194031Z-2f374376`; backtest detail SSR badges; code lines ~544–580.  
- **Note:** Workflow research-surfaces agent stream-errored; this finding stands on primary main-session evidence, not WF re-verify.

### P3 (open) — product

#### P3-1 · Position-map drawer direction toggles not individually `disabled` under freeze (cosmetic) · `PT-P3-01`
- Row 买入/卖出, 新建模拟订单, fieldset, 提交模拟订单 correctly disabled; freeze banners present (`data-position-map-trade-frozen`, `data-position-map-frozen`). Inside drawer, side toggle buttons report `disabled=false` / opacity 1 while parent `fieldset disabled` makes `:disabled` match and blocks interaction. **No submit path; API still 409.** Not a safety bypass.  
- **Source:** `QuickTradeDrawer.tsx` wraps side toggles in `fieldset disabled={formDisabled}` without per-button `disabled`.  
- **Workflow verdict:** confirmed real, severity P3.

#### P3-2 · Historical safety chat wording mentions「长桥 Paper」· `HW-P3-03`
- Session `web_557ad7c4…` assistant final says「当前为长桥 Paper Trading（模拟盘）账户，不允许实盘交易。」Platform paper account is `account_id=default` with `price_source=futu_snapshot` (no Longbridge fields). **Safety conclusion correct** (denies live). Later WF session `web_c3a7e771…` answered with flag-accurate wording without 长桥. LLM transcript hygiene only — not UI chrome, API mislabel, or safety bypass.  
- **Workflow verdict:** confirmed real, severity P3.

### Ops backlog (not product defects; track operationally)

1. **Options daily-scan stale:** `run_date=2026-08-10`, `is_stale=true`, `snapshot_age_days=1`; universe 100 / 50 candidates. Also `/api/options/radar` → **404** on API probe (UI route `/zh/options-radar` still 200).  
2. **News standby `horizon_stale_or_empty`:** aihot primary ON and serving; Horizon is idle backup. WF **refuted** elevating missing UI banner to product P3 (failover banners only on active failover by design).  
3. **LaunchAgent `com.aiquant.factor-automation`:** loaded, `state=not`, `pid=none`. Workbench automation jobs still 4/4 FRESH via other path.  
4. **LaunchAgent `com.aiquant.asia-radar-refresh`:** loaded, `state=not`, `pid=none`.

### Refuted / not elevated (workflow adversarial pass)

| Claim | Disposition |
| --- | --- |
| Research task write ledger unwired (`HW-P3-01`) | **Not a defect** — honest incomplete dark surface with explicit UI banner |
| Residual console 404 on Hermes (`HW-P3-02`) | **Not product** — clean nav has zero 404s; residual from forced favicon/manifest or intentional 409 probe |
| Results/HQA degraded INFO (`HW-INFO-CLEARED-01`) | **Clearance only** — live `read_status=available`, automation 4/4 |
| Parallel browser tab contention (`PT-NOTE-01`) | **Harness noise** — not product routing |
| Horizon backup stale without strong UI banner (`MQ-P3-001`) | **Ops standby only** — primary AI HOT healthy |
| Asia radar KS local_index unavailable (`MQ-P3-002`) | **Intentional OpenD gap** — `market_format_unsupported`; ETF proxy (EWY) usable |

### Fixed / improved vs earlier same-day report

| Prior finding | Re-run status |
| --- | --- |
| P2 position-map freeze controls UI-enabled | **FIXED** — disabled + banners + API 409 |
| P2 results catalog / HQA feed degraded | **FIXED** — `read_status=available`, automation fresh |
| P3 daily_close automation failure | **FIXED** — 4/4 FRESH |
| Chat write E2E untested | **NOW PROVEN** (×2 sessions under local_trust) |
| Mobile / EN Hermes | **Re-verified PASS** by workflow |
| factor-automation not running | **Still idle** (ops) |
| asia-radar-refresh not running | **Still idle** (ops) |
| Brief SAMPLE provenance | **Still open** (P2) |
| Options scan stale | **Still open** (ops; age still 1d) |
| horizon_stale_or_empty | **Ops only** (refuted as product P3) |

### Positive controls (not defects)

- Unauthenticated workspace snapshot → 401.  
- FE/BE health & safety byte-identical.  
- `release_authorized=false` while connector/chat ready (intentional gate separation).  
- Settings secrets redacted (`database.url`, gateway key file).  
- Settings safety cards: DRY_RUN 开 · PAPER 开 · LIVE 已禁用 · KILL 已布防 · bind 127.0.0.1 — no write controls.  
- Approvals page: 网页审批写端已安全关闭; candidates read-only.  
- Tasks page: honest「研究任务写入账本尚未接入」banner.
---

## 6. What works

### Hermes workbench (`/zh/hermes/*`)
- Today workbench, subnav (今日/会话/任务/审批/结果), safety banner, dock panels.
- Composer honestly locked until managed session; unlock after 新建空白对话.
- **Full local-dark turn:** submit-turn → queue → Run → assistant answer about paper-only / no live trading.
- Recent results list (automation, opportunity_summary, portfolio_risk, factor_candidate, backtest).
- HQA conclusion cards; automation 4/4 FRESH.
- Gateway features: session resources, run submission/events/status/stop.

### Research surfaces
- **Brief:** morning paper layout, equity $994,759, positions DRAM/MU/SNDK, markets SPY/QQQ/SOXX/IGV (Futu), AI digest items, range links 7d/1m/3m, archive links. *(SAMPLE gap on run log — P2)*
- **Backtest detail:** SAMPLE / 演示数据 badges correct for sample run.
- **Backtest list** with `include_sample=1`: SAMPLE labeling present.
- Data explorer / strategies / factor-lab / experiments: HTTP 200 in crawl (spot + SSR).

### Paper trading
- Account metrics, 3 Futu-priced positions, freeze copy, disabled order/rebalance controls.
- Position-map tabs: positions / empty open orders / order-history 7 / balance-history 12 / trade-log 12.
- Freeze ledger entry 2026-07-31.
- Backend rejects frozen mutations with 409.

### Options / markets / settings
- Options routes load; radar page 200; daily-scan API returns candidates (stale date).
- Asia radar, market cross-section, AI news, polymarket, agent-studio: 200 (polymarket one slow timeout under parallel load, later 200).
- Settings: full read-only export, redacted secrets, safety mirror.

### Cross-cutting
- Safety rail consistent on exercised paths.
- Live trading disabled everywhere observed.
- FE rewrite parity for health/safety/results.
- Route crawl: hermes, brief, data-explorer, strategies, factor-lab, backtest(+sample), experiments, paper-trading, position-map, options×4, asia-radar, market-cross-section, ai-news, polymarket, agent-studio, settings, docs, en/hermes — **200**.

---

## 7. Not tested / blocked

| Item | Status |
| --- | --- |
| **Public cutover / release stamp** | **Not authorized** — do not claim PASS for public |
| **Live trading path** | Intentionally OFF; not exercised |
| **Multi-turn chat / exact-message fork / Run-stop UI** | Single-turn proven only |
| **Paper intake `hqa.paper_intake/v1` / typed tool receipts** | Out of this browser surface; not re-accepted here |
| **Gate 1/2/3 / D-33 auto promote** | Not browser-exercised |
| **True 390px device chrome mobile pass** | Not re-run this afternoon (prior mobile PASS_WITH_WARNINGS stands) |
| **English locale full parity** | Spot only (`/en/hermes` 200) |
| **Unfreezing account / successful paper fill** | Intentionally not done (keep freeze) |
| **Migration apply** | Not in scope |
| **Upstream Hermes full suite** | Not an Agent v0.2 release gate |

**QA harness note:** Parallel chrome-devtools agents sharing one browser caused tab contention (`navigate_page` flakiness). Product routes are fine; prefer isolatedContext per journey or serial browser ownership next time.

---

## 8. Recommended next actions

### Immediate ops
1. Refresh **options daily-scan** for current day; investigate `/api/options/radar` **404** vs UI route 200.  
2. Decide: restore or intentionally unload LaunchAgents `factor-automation` and `asia-radar-refresh`.  
3. Optional: seed horizon inbox or accept aihot-only with documented warn (standby-only).

### Product fix
1. **P2 — Brief `buildRunAction`:** if run `source`/`provider` is sample (or metrics are demo), badge **SAMPLE / NOT REAL** (or omit from “平台记录”). Align with backtest detail provenance.  
2. **P3 polish — QuickTradeDrawer:** add `disabled={formDisabled}` on side toggles so disabled styles apply under freeze.  
3. **P3 hygiene:** do not treat historical「长桥 Paper」transcript as current system truth; newer safety chats already flag-accurate.

### Release / identity (hard stops)
1. **Do not** set or claim `release_authorized=true` from this report.  
2. `admission_mode=local_trust` ≠ promotion authority; keep Gate 1/2/3 explicit.  
3. Chat write success is **local dark only** — not public composer cutover.

### Follow-on browser QA
1. Multi-turn + fork + stop under local dark.  
2. Brief SAMPLE badge re-test after fix.  
3. Prefer isolated browser contexts / serial DevTools ownership (parallel multi-agent tab contention is harness noise).
---

## Appendix A — Routes exercised

`/zh/hermes` (+ managed session write), `/zh/hermes/sessions`, `/zh/hermes/tasks`, `/zh/hermes/approvals`, `/zh/hermes/results`, `/zh/brief`, `/zh/data-explorer`, `/zh/strategies`, `/zh/factor-lab`, `/zh/backtest`, `/zh/backtest?include_sample=1`, `/zh/backtest/backtest-20260809T194031Z-2f374376`, `/zh/experiments`, `/zh/paper-trading`, `/zh/position-map` (+ tabs), `/zh/options-screener`, `/zh/options-radar`, `/zh/options-tools`, `/zh/options-buyside`, `/zh/asia-radar`, `/zh/market-cross-section`, `/zh/ai-news`, `/zh/polymarket`, `/zh/agent-studio`, `/zh/settings`, `/zh/docs/reversal-momentum`, `/en/hermes`.

## Appendix B — Method

- Live API probes + FE/BE byte compare (main session).  
- Chrome DevTools MCP browser journeys (main + multi-agent workflow `wf_fca202d6-ecc`).  
- Adversarial verify agents on candidate findings; synthesis agent for overall rollup.  
- SSR/DOM freeze & SAMPLE marker probes.  
- Code confirmation for `buildRunAction` and position-map freeze wiring.  
- Fail-closed mutation probes only (409 under freeze).  
- No service restarts, no migrations, no live trading, no account unfreeze.

Workflow usage: 16 agents attempted · 14 done · 2 stream-errored · ~1.04M subagent tokens · 453 tool uses · ~40 min wall.  
Structured dump: `artifacts/browser-qa-2026-08-11-rerun/workflow_synthesis.json`.

## Appendix C — Verdict rule application

```
FAIL              ← any P0                          → not met
NEEDS_WORK        ← any P1 OR any journey FAIL      → not met
PASS_WITH_WARNINGS← only P2/P3 findings             → MET
PASS              ← all journeys PASS + zero findings → not met (P2 SAMPLE remains)
```

**Applied overall_verdict: `PASS_WITH_WARNINGS`**  
(Workflow synthesis independently also concluded `PASS_WITH_WARNINGS`; this report additionally retains P2 SAMPLE from primary evidence the WF research agent could not re-verify.)

---

## Appendix D — Delta vs morning report (same day)

| Topic | Morning | Afternoon re-run |
| --- | --- | --- |
| Overall | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS (stronger) |
| Chat write E2E | Not tested | **PASS (proven ×2)** |
| Position-map freeze UI | P2 open | **Fixed → PASS** (+ cosmetic P3) |
| Results/HQA degraded | P2 open | **Fixed** |
| Automation | 3/4 + daily_close fail | **4/4 FRESH** |
| Mobile / EN | PASS_WITH_WARNINGS | **PASS** (WF re-verify) |
| Brief SAMPLE | P2 open | **Still open** |
| Options stale | P3 product-ish | **Ops backlog** |
| Horizon stale | P3 | **Ops standby only** (refuted as product) |
| LaunchAgents idle | 2 | 2 (ops) |
| Hermes version | (gateway up) | **0.20.0** confirmed |

---

## Appendix E — Workflow agent outcomes (`wf_fca202d6-ecc`)

| Agent package | Outcome |
| --- | --- |
| api-probe | OK — full health/safety/ops snapshot |
| hermes-workbench | PASS_WITH_WARNINGS — chat write OK; 4 candidate P3s (2 refuted, 1 clearance, 1 confirmed wording) |
| paper-trading | PASS — freeze fixed; PT-P3-01 cosmetic confirmed |
| markets-quark | PASS after verify — both original P3s refuted |
| system-settings-mobile | PASS |
| research-surfaces | **Stream error** (agent died) — primary evidence retained |
| options-suite | **Stream error** (agent died) — API probe + primary crawl retained |
| adversarial verifiers | 8 votes — synthesis kept 2 product P3s, refuted 6 claims |
| synthesize | overall `PASS_WITH_WARNINGS`, public unauthorized |

---

*Evidence sources: live probe 2026-08-11 afternoon; direct browser chat E2E; API/DOM probes; multi-agent workflow wf_fca202d6-ecc (14/16); code inspection. Prefer NEEDS_WORK over fantasy PASS for any release or promotion decision. Public release remains unauthorized.*