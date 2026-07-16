# Hermes F0 direction-a polish report

**Date:** 2026-07-13  
**Scope:** Visual craft redesign of approved COO desk hierarchy (direction-a)  
**Workspace:** `ai-quant-platform/docs/design/hermes-workbench/f0/`

## Status

**Complete.** Direction-a rewritten to premium dark COO craft; shared tokens upgraded without breaking B/C variable contracts; README decision + polish notes updated; commit staged for hermes-workbench design files only.

## Commit

```
docs(frontend): polish Hermes F0 direction-a to premium dark COO craft
```

Files:

- `docs/design/hermes-workbench/f0/shared.css`
- `docs/design/hermes-workbench/f0/direction-a.html`
- `docs/design/hermes-workbench/README.md`

Not staged: `data/options_universe/earnings_calendar.csv`, `.understand-anything/`.

## Preview URLs

With:

```bash
cd /Users/sunyibo/programs/ai-quant-platform
python3 -m http.server 4173 --directory docs/design/hermes-workbench
```

- http://localhost:4173/f0/direction-a.html  
- http://localhost:4173/f0/direction-b.html (token lift only)  
- http://localhost:4173/f0/direction-c.html (token lift only)

Viewports: 1440, 1280, 768, 390 — real CSS breakpoints (no whole-UI scale).

## Product facts preserved

| Fact | Value |
| --- | --- |
| Safety strip (only) | `仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK` |
| Candidate id | `factor-momentum_20d_reversal-323b045e4b` |
| Automation | 3/4, `weekly_review` stale, tech detail collapsed |
| Recent result | `AAPL 风险与新因子计划 · completed_degraded` |
| Composer | Disabled + `真实 Hermes 写入能力尚未通过` |
| Views | idle / conversation / approval / result with `aria-pressed` |

## Craft notes

**DNA synthesis**

- **Linear:** canvas `#010102`, surface `#0f1011`, hairline `#23252a`, negative tracking on lede (~2.1–2.125rem / ≥2.2× 14px body), charcoal cards, soft inset edge highlight only.
- **Raycast:** dense chrome, hairline elevation ladder (no heavy drop shadows), calm control density.
- **Superhuman:** tight 6–8px control radii, keyboard-review feel on state bar.
- **VoltAgent:** single accent discipline — Hermes `#9085E9` only for brand mark, focus, active nav, hermes pills; warning amber reserved for pending/stale (status, not second brand).
- **Vercel:** mono chips for IDs/runs; monochrome technical labels.

**Anti-patterns removed**

- No CDN / network fonts (system + PingFang SC).
- No emoji icons; no left-border rainbow card grid; no gradient soup on brand mark (solid Hermes + subtle glow).
- Mobile nav: inert `<span>` tabs → real `<button>` elements with 44px min-height.
- Disabled reason contrast: dedicated `--muted-readable: #b4b9c3` on surface/bg; composer note not dimmed by control opacity.

**A11y / responsive**

- 44px interactive targets retained globally.
- `prefers-reduced-motion: reduce` kills transitions/animations.
- Secondary rail collapses ≤1279; nav → mobile buttons ≤767; KPI/desk stack ≤1024.
- Single `role="status"` safety strip; body does not restate paper/live/kill/API.

## Self-check

| Check | Result |
| --- | --- |
| Four views toggle `aria-pressed` | Yes |
| Facts unchanged | Yes |
| Shared vars for B/C | Yes (`--bg`, `--surface`, `--hermes`, etc.) |
| No remote fonts | Yes |
| Composer reason contrast intent | ≥4.5:1 via `--muted-readable` |
| Automation one-row + collapsed tech | Yes |

## Out of scope (next)

- F1 full state catalogs  
- Production React under `src/frontend/app`

---

## Critique remediation (2026-07-13)

**Commit:** `67ed590` `fix(frontend): correct F0 direction-a desktop grid and craft nits`  
**Repo:** `ai-quant-platform`  
**Files:** `docs/design/hermes-workbench/f0/direction-a.html`, `f0/shared.css`  
(Preserved dirty: `earnings_calendar.csv`, `.understand-anything/`)

### Fixes applied (top 5)

| # | Fix | Result |
| --- | --- | --- |
| 1 | Explicit `grid-column` 1/2/3 on nav / main / secondary + `grid-row: 1 / -1` | Main owns `1fr` |
| 2 | Idle degraded pill `pill-hermes` → `pill-warn` | Brand ≠ status |
| 3 | Dropped `.kpi.warn` `inset 2px` left rail | Attention only on `.attention-card` |
| 4 | Machine KPI `.v.mono` → mono 13px/500 | `completed_degraded` not display type |
| 5 | Disabled textarea `#0a0a0b` → `var(--bg)` | Surface ladder only |

### Layout verify (CDP getBoundingClientRect)

| Viewport | nav | main | secondary | main > secondary |
| --- | ---: | ---: | ---: | --- |
| **1440×900** | x0 w**228** | x228 w**924** | x1152 w**288** | **yes** |
| **1280×900** | x0 w**228** | x228 w**764** | x992 w**288** | **yes** |

Also: `kpi.warn` box-shadow no left rail; degraded pill class `pill pill-warn`; mono KPI 13px; textarea bg `rgb(1,1,2)` = `--bg`.
