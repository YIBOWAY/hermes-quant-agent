# Hermes F0 direction-a — independent craft critique

**Date:** 2026-07-13  
**Reviewer role:** Design craft + UX (Linear / Raycast bar), independent of implementer self-check  
**Artifacts:**  
- `ai-quant-platform/docs/design/hermes-workbench/f0/direction-a.html`  
- `ai-quant-platform/docs/design/hermes-workbench/f0/shared.css`  
- Checklist: `.superpowers/sdd/frontend-f0-craft-checklist.md`  
- Polish report: `.superpowers/sdd/frontend-f0-polish-report.md`  

**Method:** Static token/HTML audit + WCAG contrast math + headless Chrome screenshots (1440 / 1280 / 768 / 390) + CDP `getBoundingClientRect` layout measurement.

---

## Verdict

# **Needs another polish pass**

Token craft, type hierarchy, accent restraint, a11y scaffolding, and product-fact fidelity are largely at the intended bar. **Desktop three-column layout is inverted and ship-blocking** — the main COO desk is crushed into the 288px rail while the secondary “值守” panel occupies the `1fr` track. That fails the Linear/Raycast product-chrome bar on the primary review viewport (1440).

Do **not** promote to F1 until the grid placement fix is verified at ≥1280.

---

## Score vs Linear / Raycast bar

| Axis | Score (1–5) | Note |
| --- | ---: | --- |
| Surface hierarchy | 4 | Canvas `#010102` → surface ladder is quiet and correct when layout works |
| Hairlines / chrome | 4 | 1px edges, soft inset highlight; one left-rail exception on warn KPI |
| Accent discipline | 3.5 | Hermes mostly sparse; idle `pill-hermes` on degraded status is brand≠status |
| Type scale | 4 | Lede negative tracking + mute ladder + mono IDs read product-grade |
| Density / scan order | 3 | Hierarchy intent is right; desktop geometry destroys scan order |
| Status chips | 4 | Labels present; degraded/stale calm; one purple misuse |
| Anti-AI-slop | 4.5 | No mesh/emoji/glass/fake charts; subtle header vignette only |
| Responsive honesty | 3 | Real breakpoints; 768/390 healthy; 1440/1280 layout fail |
| A11y craft | 4.5 | 44px targets, focus ring, reduced-motion, composer reason contrast |
| **Overall craft** | **2.5** | **Blocked by desktop grid inversion** |

Smell test (10s at 1440): currently reads as a **broken three-column shell**, not Linear issue chrome. After grid fix, residual craft is close to “quiet premium ops desk.”

---

## Checklist pass/fail (quick)

| Section | Result | Blocking? |
| --- | --- | --- |
| 1 Surface hierarchy | **Partial** — tokens pass; main column not the hero plane at desktop | Yes (via layout) |
| 2 Hairlines | **Pass−** — 1px default; `kpi.warn` uses inset 2px left rail | No |
| 3 Accent discipline | **Fail (soft)** — brand purple on degraded status pill | No |
| 4 Type scale | **Pass** — lede ≥2.2× body; mono IDs; no remote fonts | No |
| 5 Density | **Fail** — automation row OK, but desk unusable when main is 288px | Yes |
| 6 Status chips | **Pass−** — color+text; brand pill misused once | No |
| 7 Anti-AI-slop | **Pass** | No |
| Contrast (composer / muted-readable) | **Pass** — `#b4b9c3` on `#0f1011` ≈ **9.7:1** | No |
| Product facts | **Pass** — safety strip, candidate id, 3/4, stale, degraded, disabled composer | No |

---

## CRITICAL — Desktop grid inversion

**Evidence (CDP, 1440×900):**

| Item | x | width | Track role (intended) | Actual role |
| --- | ---: | ---: | --- | --- |
| `.nav-rail` | 0 | 228 | col 1 nav | col 1 nav ✓ |
| `.secondary-panel` | 228 | **924** | col 3 quiet rail (288) | **took `1fr` middle** ✗ |
| `.main-col` | 1152 | **288** | col 2 hero `1fr` | **crushed into 288px** ✗ |

KPI cells measured **~71×272** — `completed_degraded` stacks **one character per line**. Lede width **~232px**. Headless screenshots at 1440 and 1280 match this geometry.

**Root cause:** CSS Grid placement order. Both `.nav-rail` and `.secondary-panel` set `grid-row: 1 / -1` with **no `grid-column`**. Items with a definite row are placed **before** fully auto items. Placement order becomes:

1. nav → column 1  
2. secondary (definite row) → column 2 (`1fr`)  
3. main-col (auto) → column 3 (`288px`)

There are **zero** `grid-column` declarations in `direction-a.html`.

**Why this blocks F1:** F0 is the craft gate for the COO desk. At the primary desktop width the hierarchy is inverted, type is destroyed, and attention/automation/recent cannot be reviewed honestly. 1100px (secondary `display:none`) and 768/390 look fine — the bug is specifically the three-column band.

**Fix direction (concrete):** explicit columns + full-height main:

```css
.nav-rail        { grid-column: 1; grid-row: 1 / -1; }
.main-col        { grid-column: 2; grid-row: 1 / -1; }
.secondary-panel { grid-column: 3; grid-row: 1 / -1; }
```

At `max-width: 1279px` (2-column template), keep secondary `display: none` and either omit `grid-column: 3` via the same media query or set `.main-col { grid-column: 2; }` only.

**Verify:** re-measure main width ≥ ~700px at 1280 and ≥ ~900px at 1440; KPI value for `completed_degraded` on one line (or intentional wrap at word boundary, not glyph stack).

---

## What already meets the bar

These should not be reworked away in the next pass:

1. **Void canvas + hairline ladder** — `#010102` / `#0f1011` / `#141516` / `#18191a` / `#23252a` reads Linear product, not marketing dark.
2. **Lede craft** — `clamp(1.75rem … 2.125rem)`, `letter-spacing: -0.035em`, weight 600 — clear title/body/meta separation.
3. **Single safety strip** — paper/live/kill/API only in top mono strip; body does not restate.
4. **Composer boundary** — control opacity does not dim reason copy; `--muted-readable` holds ≥4.5:1.
5. **Automation compression** — one row + `stale` pill + collapsed `details.tech`.
6. **No remote fonts / no emoji icons / no glass stacks / no fake charts.**
7. **44px targets, `:focus-visible` Hermes ring, `prefers-reduced-motion`.**
8. **Real breakpoints** (no whole-UI `transform: scale`); mobile tabs are real `<button>`s.
9. **Product facts preserved** per polish report (candidate id, 3/4, weekly_review stale, degraded result, disabled write path).

---

## HIGH / MEDIUM residual craft (after grid fix)

### H1 — Brand accent used as status (idle)

```html
<span class="pill pill-hermes">最近结果 · degraded</span>
```

Checklist **3.2 / 6.3**: brand ≠ status. Degraded/stale are warning semantics; Hermes purple is for brand/focus/active nav. On idle this also spends accent budget on a non-action chip.

**Fix:** `pill-warn` (or neutral mono chip + separate warn status), reserve `pill-hermes` for composition/Hermes-owned chrome (conversation banner is fine).

### H2 — Dual attention treatments

- `.kpi.warn` — amber border + wash + **`box-shadow: inset 2px 0 0 var(--warning)`** (left rail)  
- `.attention-card` — amber border + wash  

Checklist **2.5** forbids left-border rainbow and asks for **one** intentional attention treatment. Rail + large attention card both shout “act.” Prefer: keep **attention-card** as the chromatic lift; demote KPI warn to border/text only (drop inset rail).

### M1 — KPI machine string as display type

`.kpi .v` is 17px / 600 / proportional. Values like `completed_degraded` are machine status — checklist **4.5** wants mono chips for machine strings. Even after grid fix, three-up KPIs at ~280px can wrap awkwardly.

**Fix:** for status/code values, `.kpi .v` → `font-family: var(--mono); font-size: 13px; font-weight: 500;` (keep 17px only for short human counts like `3 / 4`).

### M2 — Freehand surface outside ladder

```css
textarea:disabled { background: #0a0a0b; }
```

Checklist **1.2** — ≤4 surface steps from tokens. `#0a0a0b` is a one-off between `--bg` and `--surface`.

**Fix:** `background: var(--bg);`

### M3 — 8px rhythm drift (minor)

One-offs: `22px` ops-header top, `18px` attention padding, `14px` gaps/margins, `10px` gaps, `6px` margins. Most are near-grid; not blocking after layout fix. Prefer snap to 16/20/24 and 8/12.

### M4 — Brand mark glow

```css
box-shadow: 0 0 0 1px …, 0 0 20px rgba(144, 133, 233, 0.18);
```

Acceptable as the single brand focal; do not spread glow to cards. No change required if glow stays on the mark only.

### M5 — Secondary rail at ≤1279

Correctly hidden; good. After explicit `grid-column: 3`, confirm 2-col media query does not leave an empty third track or overflow.

---

## Viewport notes

| Width | Observation |
| --- | --- |
| **1440** | **Broken** — main 288px, secondary owns middle; fails craft review |
| **1280** | **Broken** — same inversion (still 3-col; hide starts at 1279) |
| **1100** | Secondary gone; main ~900px — structure OK; good regression target |
| **768** | Nav + stacked KPIs + attention — readable COO stack |
| **390** | Mobile tabs, stacked desk, safety wraps — acceptable F0 phone |

---

## Top 5 concrete CSS/HTML fixes only

If the next pass does nothing else, do these five (in order):

1. **Explicit grid columns** on `.nav-rail` / `.main-col` / `.secondary-panel` (`1` / `2` / `3`) with `grid-row: 1 / -1` on all three so main owns `minmax(0,1fr)`. Re-screenshot 1440 + 1280.
2. **Demote idle degraded pill** from `pill-hermes` → `pill-warn` (or neutral + warn text).
3. **Remove** `.kpi.warn { box-shadow: inset 2px 0 0 var(--warning); }` — keep border/wash or neither; leave chromatic weight on `.attention-card` only.
4. **KPI machine values** — mono 13px for `completed_degraded`-class strings; keep larger type for short human metrics.
5. **Replace** disabled textarea `#0a0a0b` with `var(--bg)`.

---

## Approval criteria mapping

| Gate | Status |
| --- | --- |
| Implementer self-check (polish report) | Complete — but did not catch grid placement order |
| Design critique (this doc) | **Fail** — CRITICAL layout |
| Ship to F1? | **No** |
| Re-review trigger | Grid fix + 1440/1280 screenshots showing main width ≈ `1fr` and single-line (or soft-wrap) KPI status |

---

## Sign-off

| Role | Result | Notes |
| --- | --- | --- |
| Implementer self-check | claimed pass | Tokens/a11y/facts strong |
| Design critique review | **fail** | Desktop column inversion; 2–3 residual accent/KPI nits |

**Verdict: Needs another polish pass**
