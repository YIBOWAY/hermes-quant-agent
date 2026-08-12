# Full-Stack Browser QA Report — Hermes-quant-agent / ai-quant-platform

**Date:** 2026-08-11  
**Base URL:** `http://127.0.0.1:3001` (BFF/frontend) · Backend `:8765`  
**Overall verdict:** `PASS_WITH_WARNINGS`  
**Public release:** **UNAUTHORIZED** (`release_authorized=false`; no `release_stamp_id` / `public_cutover_id`)

---

## 1. Executive verdict

| Field | Value |
| --- | --- |
| **overall_verdict** | **PASS_WITH_WARNINGS** |
| **Public cutover** | **OFF / unauthorized** — local dark only |
| **Live trading risk** | **None observed** (`live_trading_enabled=false`, `kill_switch=true`) |
| **Journey FAIL count** | 0 |
| **P0 / P1 findings** | 0 / 0 |
| **P2 / P3 findings** | 3 / 4 (actionable + ops) |

Local full-stack surfaces under the owner session are broadly healthy: core chrome loads, safety banners match FE/BE health envelopes, critical XHR/fetch returned 200 (or intentional 401/409 fail-closed), and console errors were empty across all journey areas.

This is **not** a public-release gate pass. Runtime explicitly reports `release_authorized=false` while local dark flags may show `chat_write_ready=true` / `composer_write_ready=true` / connector liveness ready. Those are **gate-separated** facts — connector readiness must not be read as public cutover.

Operator-visible degradation remains: daily-close automation failed, HQA artifact feed degraded, two LaunchAgents loaded-but-not-running, and several P2 UX honesty issues (position-map controls under freeze; brief SAMPLE provenance). Prefer **NEEDS_WORK for public or promotion decisions**; for **local dark browser surface acceptance**, **PASS_WITH_WARNINGS** is evidence-correct.

---

## 2. Runtime identity & safety (health facts)

### 2.1 Probe summary

| Check | Result |
| --- | --- |
| `backend_ok` | true |
| `frontend_ok` | true |
| `hermes_ok` | true |
| `database reachable` | true |
| `futu_opend reachable` | true |
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
| `connector_liveness_ready` | true | Heartbeat fresh (~1.5s at probe) |
| `release_authorized` | **false** | **No public release stamp/cutover** |

### 2.3 Safety envelope (FE ↔ BE byte-consistent)

Adversarial verify: `:3001` and `:8765` returned **identical** bodies for `/api/health`, `/api/settings`, `/api/safety/effective`.

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
| Owner-session same endpoint | **200** `workspace_id=ws-local-main` |
| `POST /api/paper/account/orders` under freeze | **409** `account_frozen` |

### 2.5 Ops blockers (probe)

1. `com.aiquant.factor-automation` LaunchAgent **loaded but not running** (`pid=none`)
2. `com.aiquant.asia-radar-refresh` LaunchAgent **loaded but not running** (`pid=none`)

Workbench also reported: **系统部分降级** · automation **3/4** normal · **每日收盘研究 失败** · HQA 产物源 **DEGRADED · 4**.

---

## 3. Journey matrix (area → verdict)

| Area | Verdict | Console errors | Network 4xx/5xx (critical paths) | Notes |
| --- | --- | --- | --- | --- |
| hermes-workbench | **PASS_WITH_WARNINGS** | none | none (critical 200) | Composer locked until managed session; automation/results degraded honest |
| research-surfaces | **PASS_WITH_WARNINGS** | none | none | Brief/data-explorer/factor-lab/backtest/experiments OK; SAMPLE badge gap on brief |
| paper-trading | **PASS_WITH_WARNINGS** | none | none | paper-trading disables orders; position-map controls UI-enabled (P2) |
| options-suite | **PASS_WITH_WARNINGS** | none | none | Radar works; scan 1-day stale (P3) |
| markets-quark | **PASS_WITH_WARNINGS** | none | none | Asia/cross-section/news/polymarket/agent-studio OK; horizon secondary warn |
| system-settings | **PASS** | none | none | Read-only safety export; secrets redacted |
| mobile-hermes | **PASS_WITH_WARNINGS** | none | none | Hamburger nav, no H-overflow; viewport measure 500 vs requested 390 |

**Journey FAIL count:** 0  
**Strict all-PASS journeys:** 1 (`system-settings` only)

---

## 4. Confirmed findings (P0/P1 first)

### Severity rollup

| Severity | Count | Titles |
| --- | --- | --- |
| **P0** | **0** | — |
| **P1** | **0** | — |
| **P2** | **3** | position-map freeze UX; results catalog degraded; brief SAMPLE provenance |
| **P3** | **4** | options stale scan; news horizon; workspace auth (positive); health consistency (positive) |

### P2

#### P2-1 · position-map paper order controls still UI-enabled under freeze and kill_switch
- **Dimension:** safety-gates / ux-flow  
- **Detail:** With `kill_switch=true` and banner `模拟账户冻结 开`, `/zh/paper-trading` correctly disables 提交订单 / 再平衡 / 运行模拟交易. `/zh/position-map` leaves 买入/卖出 and 提交模拟订单 **UI-enabled** (`disabled=false`; SSR lacks `disabled`). Submit still **409 `account_frozen`** — **not** a live-trading bypass — but fail-closed affordances are inconsistent and can mislead operators.  
- **Evidence:** health/safety re-check; DOM evaluate; POST toast `下单失败：[account_frozen]`.

#### P2-2 · Unified results catalog partially degraded (honest API)
- **Dimension:** api-integration / ops  
- **Detail:** `GET /api/hermes/results` → 200, FE/BE bodies identical; `read_status=degraded`; `hqa_artifact_feed` degraded (4) while platform runs/candidates available. UI correctly shows 部分结果来源已降级 / HQA DEGRADED · 4 / Automation · degraded. Source health issue, not BFF break.  
- **Evidence:** curl `:8765` vs `:3001` BODIES_IDENTICAL size 5307; browser catalog labels.

#### P2-3 · Brief run log promotes SAMPLE backtest as platform record without SAMPLE badge
- **Dimension:** ux-flow / provenance honesty  
- **Detail:** Daily brief links `backtest-20260809T194031Z-2f374376` as **平台记录回测** (Sharpe 19.01 / Return 4.85%) with no SAMPLE/NOT REAL badge. Dedicated backtest list/detail correctly labels SAMPLE / 演示数据 / 数据源 sample. Crossing brief → backtest rewrites perceived provenance. Root: `buildRunAction` hardcodes 平台记录回测 for `kind=backtest` without source check.  
- **Evidence:** brief a11y/HTML vs `/backtest?include_sample=1` and detail pages.

### P3

#### P3-1 · Options daily-scan snapshot is one day stale
- **Detail:** `run_date=2026-08-10`, `is_stale=true`, `snapshot_age_days=1` on 2026-08-11. UI shows old-snapshot guidance. Integration OK; ops gap (today’s scan not run). Related: asia-radar-refresh LaunchAgent not running.

#### P3-2 · News secondary provider warns `horizon_stale_or_empty`
- **Detail:** `/api/news/status` 200; `research_only=true`; aihot primary ON, no last_error; warnings `['horizon_stale_or_empty']`; items still 50 via aihot. Horizon inbox empty. Failover secondary degraded only.

#### P3-3 · Workspace snapshot correctly fail-closed without owner session
- **Detail:** Cookie-less snapshot → 401 auth; owner session → 200. **Correct behavior**, not a regression. Logged for auth-gate evidence.

#### P3-4 · Core health and safety envelope consistent across FE/BE
- **Detail:** Byte-identical health/settings/safety; banner matches epoch 197 / kill / freeze / live off; `release_authorized=false` with connector ready. Intentional gate separation — not drift.

### Not elevated to findings (still noted)
- Mobile viewport request 390×844 measured `innerWidth≈500` (tooling limit).  
- Screenshot save to `artifacts/browser-qa-live` blocked by chrome-devtools workspace roots.  
- Factor-lab empty metrics cells for some factors (honest, not crash).  
- Hermes research task write ledger “尚未接入” (expected incomplete dark surface).  
- Session fork ineligibility `source_session_not_external` (honest product rule).

---

## 5. What works

### Hermes workbench (`/zh/hermes/*`)
- Today workbench, nav tabs, safety banner, activity drawer (read-only follow spine).
- Composer **honestly disabled** until 新建空白对话 / managed session.
- Sessions: real read-only Hermes sessions, 只读已连接.
- Session detail transcript + fork rule honesty.
- Tasks: honest empty research ledger + platform automation/weekly/opportunity evidence.
- Results: unified catalog, filters (`?kind=backtest`), backtest detail COMPLETED/AVAILABLE + provenance JSON.
- No console errors; critical network 200.

### Research surfaces
- **Brief:** 每日晨报, equity/markets/AI digest, `range=3m` works.
- **Data explorer:** SPY FUTU OHLCV + chart, range presets.
- **Strategies:** 4 strategies, honest empty results, param switch.
- **Factor-lab:** 7/7 health rows + timing tab.
- **Backtest:** default hides sample; `include_sample=1` labels SAMPLE/NOT REAL; detail OK.
- **Experiments:** empty-state honest, research-only disclosure.

### Paper trading
- Paper account metrics, positions (SNDK/MU/DRAM), ledger activity.
- Historical replay kill_switch-disabled 运行模拟交易.
- Manual order/rebalance **disabled on paper-trading page**.
- Position-map tabs: positions / empty open orders / order-history 7 / trade-log 12 + freeze filter.
- Backend rejects frozen mutations with 409.

### Options suite
- Screener empty pre-run honest; Radar live Futu scan + expand detail (CRWD etc.); Tools 8 tabs; Buyside research-only pre-run form.

### Markets / quark
- Asia Radar Futu overview; Market cross-section basket switch; AI news 50 items; Polymarket 12 read-only markets + live integration intentionally disabled; Agent Studio read-only with APPROVED candidates and closed approve/deny.

### Settings
- Full PASS: read-only backend export, redacted secrets, safety cards match API, no write controls on safety flags.

### Mobile Hermes
- Loads, hamburger full tree, subnav, no horizontal overflow, composer lock + primary CTA visible, network 200.

### Cross-cutting
- Safety rail consistent on all exercised paths.
- Live trading disabled everywhere observed.
- FE rewrite parity for health/settings/results (where compared).

---

## 6. Not tested / blocked

| Item | Status |
| --- | --- |
| **Public cutover / release stamp** | **Not authorized** — do not claim PASS for public |
| **Live trading path** | Intentionally OFF; not exercised |
| **New managed Web Chat write end-to-end** (create session → send → durable Run → paper intake contract) | Not proven in this journey set; composer required new blank chat; historical intake errors noted only |
| **Paper intake / execution_contract `hqa.paper_intake/v1`** | Out of browser surface scope; prior audit: not accepted |
| **Gate 1/2/3 manual Scene-B / D-33 auto promote** | Not browser-exercised |
| **Multi-turn, restart, exact-message fork, Run-stop, Vertical A browser flows** | Still unproven per product boundary |
| **Migration apply** | Not in scope; 028/029 must not be re-applied |
| **Screenshot artifact archive** | Blocked (workspace root restriction) |
| **True 390px device chrome** | Tooling measured ~500px width |
| **LaunchAgent recovery** | factor-automation & asia-radar-refresh not running — not remediated in QA |
| **Unauthenticated full surface crawl** | Only workspace snapshot 401 checked |
| **English locale parity** | Spot only (brief EN noted for SAMPLE gap) |
| **Discord channel** | Independent; not this FE matrix |
| **Upstream Hermes 40k suite** | Not an Agent v0.2 release gate; not run |

---

## 7. Recommended next actions

### Immediate ops (local health)
1. **Investigate daily_close automation failure** (`hqa9h:daily_close:…`, 最近成功=从未运行) — workbench DEGRADED banner.  
2. **Restore or intentionally unload** LaunchAgents: `com.aiquant.factor-automation`, `com.aiquant.asia-radar-refresh`.  
3. **Refresh options daily-scan** for 2026-08-11 (clear P3 stale snapshot).  
4. **HQA artifact feed:** diagnose why 4 items degraded; keep UI honesty until source healthy.  
5. Optional: seed/repair horizon news secondary or accept aihot-only with documented warn.

### Product / UX fixes (P2)
1. **position-map:** When `canonical_account_frozen` or `kill_switch`, disable 买入/卖出 / 新建模拟订单 / 提交模拟订单 and surface the same freeze copy as paper-trading (fail-closed **affordance**, not only API 409).  
2. **Brief run log:** If run source is SAMPLE/demo, badge **SAMPLE / NOT REAL** (or omit from “平台记录”); align `buildRunAction` with backtest provenance.  
3. Do **not** treat results `read_status=degraded` as FE bug; track as source SLO.

### Release / identity (hard stops)
1. **Do not** set or claim `release_authorized=true` from this report.  
2. Public composer/cutover remains a **separate** authorized Gate after new candidate identity, suites, sealed preflight — never reuse revoked AlphaZeroBeta-era manifests.  
3. `admission_mode=local_trust` ≠ promotion authority; keep Gate 1/2/3 or dual-Flag paper automation policy explicit.  
4. Before another paper-research acceptance: bind `execution_contract=hqa.paper_intake/v1`, typed tool receipts, HQA verifier — **not** model prose.

### Follow-on browser QA
1. Explicit **new blank conversation → send → Run lifecycle** under local dark.  
2. Re-test position-map after freeze-disable fix.  
3. Multi-turn / fork / stop / Vertical A per active plan.  
4. Persist screenshots once artifact path is inside chrome-devtools workspace roots.

---

## Appendix A — Routes exercised

`/zh/hermes`, `/zh/hermes/sessions` (+ detail), `/zh/hermes/tasks`, `/zh/hermes/results` (+ kind filter + backtest detail), `/zh/brief`, `/zh/data-explorer`, `/zh/strategies`, `/zh/factor-lab`, `/zh/backtest` (+ sample + detail), `/zh/experiments`, `/zh/paper-trading`, `/zh/position-map` (+ tabs), `/zh/options-screener`, `/zh/options-radar`, `/zh/options-tools`, `/zh/options-buyside`, `/zh/asia-radar`, `/zh/market-cross-section`, `/zh/ai-news`, `/zh/polymarket`, `/zh/agent-studio`, `/zh/settings`, mobile `/zh/hermes`.

## Appendix B — Verdict rule application

```
FAIL              ← any P0                          → not met
NEEDS_WORK        ← any P1 OR any journey FAIL      → not met
PASS_WITH_WARNINGS← only P2/P3 findings             → MET
PASS              ← all journeys PASS + zero findings → not met
```

**Applied overall_verdict: `PASS_WITH_WARNINGS`**

---

*Evidence sources: live probe 2026-08-11; seven journey packages; adversarial re-verify of safety/API/UX findings. Prefer NEEDS_WORK over fantasy PASS for any release or promotion decision. Public release remains unauthorized.*
