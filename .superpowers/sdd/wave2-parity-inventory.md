# D-31 Wave 2 Task F remainder — Page parity inventory

**Date:** 2026-07-14  
**Scope:** Inventory only. **No** deletion, **no** hard redirects, **no** capability removal.  
**Soft banners:** platform `3400659` (`HermesParityBanner` on the four legacy research pages).

Locale note: production routes are under `/zh/...` or `/en/...` via `localizePath`. Paths below are the unlocalized app routes.

---

## Hermes workbench surfaces (target home)

| Surface | Route(s) | Provides | Legacy counterpart | Cutover readiness |
|---|---|---|---|---|
| **Today** | `/hermes` | Default research home (when shell enabled). SafetyStrip; action / exception / conclusion hierarchy; feed schema 1.1 six-source artifacts (`portfolio_risk`, `prediction`, `market_foresight`, `weekly_review`, `opportunity_summary`, `automation_status`); candidate-derived attention. Composer **hard-disabled**. | Partial overlap with Dashboard + multi-page research entry; not a 1:1 of any single legacy page | **soft banner only** (legacy pages point *to* Hermes; no reverse redirect) |
| **Tasks** | `/hermes/tasks` | Read-only **platform evidence**: automation status + jobs, weekly review summary, opportunity summary. Honest banner that research **task write ledger is not connected**. No create/submit. | No true Hermes research-task write UI; not a replacement for Backtester/Experiments **run forms** | **not ready** to replace any write-capable research surface |
| **Approvals** | `/hermes/approvals` | Candidate list with integrity/binding evidence; **Gate 2 CAS** Approve/Reject only when `approval_enabled` + `verified` + `pending`; detail re-fetch digest + required note → platform `POST /api/agent/candidates/{id}/review` | Supersedes Agent Studio for **review mutations** (Agent Studio no longer mounts approve/reject). Does **not** replace HQA Gate 1 source confirmation or Gate 3 git commit | **soft banner only** vs Agent Studio; CAS path is live for verified rows but Studio remains the source-preview/audit surface |
| **Results** | `/hermes/results` | Read-only 9H artifact index (non-automation conclusions) + **outbound links** to existing platform routes (`/factor-lab`, `/backtest`, `/experiments`, `/agent-studio`, `/paper-trading`). **No** `/hermes/results/*` unified detail (`unifiedResults` hard-off) | Explicitly defers to Factor Lab / Backtester / Experiments / Agent Studio / Paper for run detail | **not ready** — by design still a hub, not a sink for legacy detail |

Related hard-offs (unchanged Wave 2): `chat`, `execution`, `unifiedResults`, `legacyRedirects` are source-literal `false`.

---

## Legacy research pages vs Hermes

### 1. Factor Lab

| Field | Value |
|---|---|
| **Routes** | `/factor-lab`, `/factor-lab/[runId]` |
| **Provides** | Factor health / single-symbol timing dashboard; provider/universe/symbol/date/lookback params; factor run list + detail; sample-source controls; full research UI (not retired) |
| **Hermes equivalent** | **none** for interactive factor lab / run detail. Partial: `/hermes/results` links *to* Factor Lab; Today may surface related artifacts if present |
| **Soft banner** | Yes (`HermesParityBanner` → Hermes home) |
| **Cutover readiness** | **soft banner only** — not ready-to-redirect |

### 2. Backtester

| Field | Value |
|---|---|
| **Routes** | `/backtest`, `/backtest/[runId]` |
| **Provides** | Strategy / universe / factor-weight backtest config form; run list; equity comparison / metrics; run detail |
| **Hermes equivalent** | **none** for launch/configure/detail UI. HQA Scene-B one-shot `backtest --final` is CLI/wrapper authority, not a Hermes page. `/hermes/results` only deep-links here |
| **Soft banner** | Yes |
| **Cutover readiness** | **soft banner only** — not ready-to-redirect |

### 3. Experiments

| Field | Value |
|---|---|
| **Routes** | `/experiments` |
| **Provides** | Local experiment directory browser; parameter sweeps; best/latest run summary; experiment run form; ties to backtest listings |
| **Hermes equivalent** | **none** for sweep UI / experiment namespaces. Final one-shot receipts bind experiments under HQA authority roots, not this page |
| **Soft banner** | Yes |
| **Cutover readiness** | **soft banner only** — not ready-to-redirect |

### 4. Agent Studio

| Field | Value |
|---|---|
| **Routes** | `/agent-studio` |
| **Provides** | **Transitional read-only** candidate pool inspection: list/detail, plain-text source preview, audit/review event display, registry context. **No** task submit; **no** approve/reject controls; copy directs operators to Hermes / Scene-B |
| **Hermes equivalent** | **Partial:** `/hermes/approvals` for Gate 2 CAS on verified pending; `/hermes` Today for candidate attention. Source preview + full audit timeline still richer on Agent Studio |
| **Soft banner** | Yes |
| **Cutover readiness** | **soft banner only** — Approvals can own **mutations**, but Studio is not ready-to-redirect until Hermes has equivalent source/audit detail |

---

## Cross-matrix (capability → surface)

| Capability | Primary surface today | Hermes coverage | Redirect/delete? |
|---|---|---|---|
| Default research entry | `/hermes` (shell on) | Self | N/A |
| 9H automation / weekly / opportunity read | `/hermes`, `/hermes/tasks` | Yes (read) | N/A |
| Candidate Gate 2 CAS approve/reject | `/hermes/approvals` | Yes (platform review API) | Do not delete Studio yet |
| Candidate source/audit inspect | `/agent-studio` | Partial (list/digest on Approvals) | **not ready** |
| Factor lab interactive analysis | `/factor-lab` | none | **not ready** |
| Backtest form + run detail | `/backtest` | none (CLI final separate) | **not ready** |
| Experiment sweeps | `/experiments` | none | **not ready** |
| Unified result detail under Hermes | — | hard-off | N/A until `unifiedResults` plan |
| Hermes chat write | — | blocked (`verify-chat` exit 3) | N/A |
| Scene-B Gate 1/3 | HQA CLI + isolated worktree | not a page | N/A |

---

## Cutover readiness summary

| Page | Ready-to-redirect? | Notes |
|---|---|---|
| Factor Lab | **not ready** | Soft banner only |
| Backtester | **not ready** | Soft banner only |
| Experiments | **not ready** | Soft banner only |
| Agent Studio | **not ready** | Soft banner only; mutations already live on Hermes Approvals for verified CAS rows |
| Hermes Today/Tasks/Approvals/Results | N/A (targets) | Chat write still blocked; Results still hub-links |

**Explicit non-actions for this inventory file:** no route removal, no `legacyRedirects=true`, no nav retirement, no automatic 301/307 from the four pages.

---

## Evidence refs

| Item | Ref |
|---|---|
| Soft banners commit | platform `3400659` |
| Gate 2 CAS + Tasks read model | platform `8052fe6` |
| Wave 2 plan | HQA `docs/superpowers/plans/2026-07-14-d31-wave2-bridge-approvals-parity.md` |
| Parity banners report | `.superpowers/sdd/wave2-parity-banners-report.md` |
| Approvals/Tasks report | `.superpowers/sdd/wave2-approvals-tasks-report.md` |
