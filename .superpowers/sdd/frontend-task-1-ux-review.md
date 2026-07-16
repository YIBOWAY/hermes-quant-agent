# Hermes F0 UX Independent Review

**Reviewer:** frontend/UX (react-reviewer lane — visual directions, read-only)  
**Date:** 2026-07-13  
**Scope:** `ai-quant-platform/docs/design/hermes-workbench/f0/`  
  - `shared.css`  
  - `direction-a.html` (COO desk)  
  - `direction-b.html` (research timeline)  
  - `direction-c.html` (quiet split canvas)  
**Checklist:** `.superpowers/sdd/frontend-task-1-ux-checklist.md`  
**Brief:** `.superpowers/sdd/frontend-task-1-brief.md`  
**Method:** Full artifact read + headless Chrome CDP at 1440×900, 1280×800, 768×1024, 390×844; idle Today first-screen probes; structural checks for safety uniqueness, disabled composer, reduced motion, 44px targets, overflow.

**F0 decision:** **Not made.** This review does not select or approve a direction.

---

## Assessment

### **Ready for user selection**

All three directions ship identical fixed fixture content, real breakpoint reflow (no whole-UI `transform: scale`), a single top SafetyStrip, honest disabled composers, collapsed technical detail, and distinct IA emphasis (A action/status · B change/progress · C conversation/result). No hard-fail class issues block comparative selection.

Caveats the user should weigh (none are “invented approvals”):

1. **Direction B @ 390** — first screen answers action / exception / current-work, but **recent result status (`completed_degraded`) is below the fold** under a tall stacked progress track. Not a global redesign trigger; weakens B’s mobile five-second scan.
2. **Direction A @ 390** — exception *name* `weekly_review` is below the fold; KPI/pills still surface “自动化 3/4 · 1 项已过期”. Acceptable for S3 with a note.
3. **Shared disabled-composer contrast** — `opacity: 0.55` on muted disabled text ≈ **3.95:1**, under WCAG AA 4.5:1 for the honest reason copy. Medium, all three.
4. **Direction A mobile “tabs”** — non-interactive `<span>`s styled as chips (`aria-current` on spans). Review chrome / false affordance; not a safety or hierarchy hard fail.

---

## Hard-fail gate (checklist)

| Hard fail | A | B | C | Evidence |
| --- | --- | --- | --- | --- |
| Duplicate safety chrome (paper/live/kill/API) | Pass | Pass | Pass | Exactly one `.safety` + `role="status"`; body mentions of `实盘交易已禁用` = 1 |
| Horizontal overflow at required viewport | Pass | Pass | Pass | CDP: `scrollWidth == innerWidth` at all four widths |
| Composer looks/behaves submittable | Pass | Pass | Pass | `disabled` on textarea + 发送; copy `真实 Hermes 写入能力尚未通过`; opacity/not-allowed |
| Idle cannot answer action/exception/work/result in 5s | Pass | **Warn @390** | Pass | See five-second section; B recent-result status off-screen at 390 |
| Interactive targets &lt; 44 CSS px | Pass | Pass | Pass | CDP: 0 sub-44 visible `button/a/input/textarea/summary` at all widths |

---

## Direction scorecard

| Check group | Direction A (COO desk) | Direction B (timeline) | Direction C (split canvas) |
| --- | --- | --- | --- |
| Hierarchy | **Pass** | **Pass** | **Pass** |
| 5-second scan | **Pass** (390: exception name below fold) | **Fail @390 S5** / Pass desktop | **Pass** |
| Safety uniqueness | **Pass** | **Pass** | **Pass** |
| Long Chinese + IDs | **Pass** | **Pass** | **Pass** |
| 1440 | **Pass** | **Pass** | **Pass** |
| 1280 | **Pass** | **Pass** | **Pass** |
| 768 | **Pass** | **Pass** | **Pass** |
| 390 | **Pass** with note | **Fail** S5 fold | **Pass** |
| Disabled composer | **Pass** (contrast medium) | **Pass** (contrast medium) | **Pass** (contrast medium) |
| Reduced motion | **Pass** | **Pass** | **Pass** |
| Contrast | **Pass** body / **Warn** disabled | same | same |
| 44px targets | **Pass** | **Pass** | **Pass** |
| **Overall** | **Pass** | **Pass with mobile caveat** | **Pass** |

---

## Detailed findings by criterion group

### 1. Hierarchy

| # | A | B | C | Notes |
| --- | --- | --- | --- | --- |
| H1 Primary = human action | Pass | Pass | Pass | A: warn KPI + `attention-card`. B: first timeline card `action` + progress “人工确认”. C: hero card + `answer-chip.action` + pulse “待确认 1”. |
| H2 Secondary = exceptions | Pass | Pass | Pass | Overdue automation below action; warn/danger pills with text, not color alone. |
| H3 Tertiary = work + recent result | Pass | Pass | Pass | Present without opening `<details>`. |
| H4 Automation compression | Pass | Pass | Pass | One summary row/card/item; never four equal healthy-automation cards. |
| H5 Tech detail collapsed | Pass | Pass | Pass | cron/run under `details.tech`. |
| H6 Direction identity | Pass | Pass | Pass | A desk/KPI; B pipeline+stream; C split conversation/result while idle still answers S1–S5. |

**No FAIL.** A’s KPI strip + attention card + side panel repeat the same facts (redundancy, not hierarchy inversion).

### 2. Five-second scan (idle Today, no click)

| # | Question | A | B | C |
| --- | --- | --- | --- | --- |
| S1 Am I safe? | Pass — strip first, mono, warning tint, not truncated at 390 | same | same |
| S2 What needs me? | Pass — lede + 研究审批项 | Pass — first TL card | Pass — chip + hero |
| S3 What is wrong? | Pass desktop; @390 name below fold but “1 项已过期 / 3/4” visible | Pass — exception card in view @390 | Pass — chip + card |
| S4 Current work? | Pass — “其余研究运行正常” / pipeline context | Pass | Pass — “当前” chip |
| S5 What just finished? | Pass — KPI + pill `completed_degraded` | **Fail @390** — `completed_degraded` not in first viewport (progress chrome + action + exception push result down) | Pass — chip includes status |

**B@390 S5** is the only five-second fail. Desktop/tablet B passes (result card in view at 1440).

### 3. Safety uniqueness

| # | A | B | C |
| --- | --- | --- | --- |
| U1 Single SafetyStrip | Pass | Pass | Pass |
| U2 No content duplicates | Pass | Pass | Pass |
| U3 Status landmark | Pass (`role="status"`) | Pass | Pass |
| U4 Not mixed with tasks | Pass | Pass | Pass |

A’s secondary “安全” list item explicitly says status lives only in the top strip (meta, not a second kill/API banner). C pulse pills are task/result summaries, not paper/live/kill/API.

### 4. Long Chinese + long IDs

| # | A | B | C |
| --- | --- | --- | --- |
| L1 No meaning truncation on action titles | Pass | Pass | Pass |
| L2 Long IDs don’t blow layout | Pass (`word-break` / mono blocks) | Pass | Pass |
| L3 Mixed zh/en rhythm | Pass | Pass | Pass |
| L4 Collapsed tech strings wrap | Pass (`word-break: break-all` on `code`) | Pass | Pass |

Safety strip uses ellipsis **only** if overflow; CDP confirmed **not** truncated at 390 for the fixed safety sentence.

### 5. Four viewports

CDP summary (`scrollWidth <= innerWidth`, no whole-UI scale):

| Viewport | A | B | C |
| --- | --- | --- | --- |
| 1440×900 | Pass | Pass | Pass |
| 1280×800 | Pass (secondary collapses per shared rule) | Pass (side composer → mobile composer path) | Pass (split kept; stacks ≤1279) |
| 768×1024 | Pass | Pass | Pass |
| 390×844 | Pass reflow; S3 name note | Pass reflow; **S5 fold fail** | Pass reflow + full S1–S5 |

V2: no `transform: scale` on prototype roots. B’s spark `scaleY` is decorative bars only; neutralized under `prefers-reduced-motion`.

V3/V5: secondary panels may hide; primary action/exception/result remain in main stream (C correctly keeps `.canvas-right` out of `.secondary-panel` hide).

### 6. Disabled composer honesty

| # | A | B | C |
| --- | --- | --- | --- |
| C1 Visually disabled | Pass | Pass | Pass |
| C2 Programmatically disabled | Pass | Pass (desktop + mobile instances both disabled) | Pass |
| C3 Honest reason | Pass | Pass | Pass |
| C4 No false affordance | Pass (`cursor: not-allowed`) | Pass | Pass |
| C5 Boundary in active states | Pass (composer dock persists across views) | Pass | Pass |

**Medium:** shared `button:disabled, textarea:disabled { opacity: 0.55 }` drops estimated contrast of the reason string to ~3.95:1. Prefer full-opacity muted color or `aria-disabled` styling without dimming the legal/honest copy.

### 7. Reduced motion

| # | Result |
| --- | --- |
| M1 `prefers-reduced-motion: reduce` | Pass — global animation/transition kill in `shared.css` |
| M2 No motion-only meaning | Pass — states use text pills/borders |
| M3 No scroll hijack | Pass — view toggles only set `data-view` |

B extra rule zeros spark transforms under reduced motion.

### 8. 44px targets + focus

| # | A | B | C |
| --- | --- | --- | --- |
| T1 Interactive ≥44×44 | Pass (height enforced; measured widths ≥44 for visible controls) | Pass | Pass |
| T2 Disabled controls size | Pass | Pass | Pass |
| T3 Spacing @390 | Pass | Pass | Pass |
| T4 `:focus-visible` | Pass — 2px hermes outline, offset 3 | Pass | Pass |

### Contrast (shared tokens)

| Pair | Ratio | Verdict |
| --- | --- | --- |
| text `#f1f3f6` / bg `#0c0d10` | 17.48:1 | Pass |
| muted `#9ca3af` / bg | 7.65:1 | Pass |
| muted / surface | 7.19:1 | Pass |
| safety `#f5b942` / dark amber strip | ~10:1 | Pass |
| success / surface | 8.82:1 | Pass |
| hermes / surface | 5.49:1 | Pass (UI chrome) |
| disabled muted @0.55 | ~3.95:1 | **Warn** |

---

## Per-direction narrative

### Direction A — COO desk

**Strengths:** Clearest ops hierarchy (KPI → attention → exception → result). Action CTA and Gate 2 language are unmistakable. Secondary “值守面板” reinforces scan without duplicating safety values. Strong desktop COO identity.

**Weaknesses:** Fact triple-repeat (KPI + cards + side). Mobile nav chips are inert spans (false affordance for F1). @390, full automation card (with `weekly_review`) sits below fold after stacked KPIs—mitigated by KPI “1 项已过期”.

**Overall:** **Pass** — best pure “action/status first” read on desktop; acceptable on phone.

### Direction B — research timeline

**Strengths:** Distinct progress-first identity; chronological action → exception → result matches research change log. Automation stays one timeline row + optional healthy summary. Side summary mirrors stream.

**Weaknesses:** @390, vertical progress steps (4× min-height 44) consume first-screen budget; **`completed_degraded` / recent result card leave the initial viewport** → S5 fail on phone. Dual composer DOM (side + mobile) is fine via CSS but is duplicate markup for later production.

**Overall:** **Pass with mobile caveat** — selectable if user prioritizes timeline metaphor; recommend F1 fix to compress progress track on narrow widths so result status stays above the fold.

### Direction C — quiet split canvas

**Strengths:** Best idle five-second coverage (dedicated answer chips + right work surface). Conversation/result-first identity without abandoning safety/action/work/result. Composer always present and honest. @390 still keeps S1–S5 probes in view. Right canvas not classified as `.secondary-panel`, so stacking does not drop the only approval path.

**Weaknesses:** Quieter visual weight on action than A’s attention card (still clearly marked). Idle left column + right column can feel content-heavy; mitigated by chips.

**Overall:** **Pass** — strongest mobile scan integrity of the three.

---

## Issues list (severity format)

```
[MEDIUM] Disabled composer reason contrast under AA
File: docs/design/hermes-workbench/f0/shared.css:80-84
Issue: opacity 0.55 on disabled textarea/button dims the honest capability message to ~3.95:1.
Why: Users may miss why chat cannot send; honesty requires readable copy.
Fix: Keep disabled semantics but style reason text at full muted contrast (≥4.5:1); dim only chrome borders/icons if needed.

[MEDIUM] Direction B phone first screen loses recent-result status
File: docs/design/hermes-workbench/f0/direction-b.html:439-444 (progress-track), idle timeline order
Issue: At 390×844, completed_degraded / recent result card are below the fold.
Why: Five-second S5 fails on the required phone viewport.
Fix: On ≤767px, collapse progress to a single summary row (e.g. “进度：人工确认”) or pin a result status chip in the top band.

[MEDIUM] Direction A mobile tabs are non-interactive
File: docs/design/hermes-workbench/f0/direction-a.html:548-553
Issue: Styled spans with aria-current look like navigation but do nothing.
Why: False affordance; assistive tech may treat as current page chrome without a target.
Fix: F1 — real buttons or remove aria-current from decorative chips.

[LOW] Direction A fact repetition
File: direction-a.html KPI strip + attention/auto/result cards + secondary panel
Issue: Same four facts appear three times on wide desktops.
Why: Dilutes hierarchy slightly without hiding the primary action.
Fix: Optional F1 densify — KPI or side rail, not both at full prose.
```

No CRITICAL React-security or safety-strip duplication issues in these static HTML prototypes.

---

## Score table for platform README

| Criterion | A | B | C | Notes |
| --- | --- | --- | --- | --- |
| Hierarchy (action / exception / work / result) | Pass | Pass | Pass | Identities distinct; automation compressed |
| Five-second scan (idle Today) | Pass | Fail@390 S5 | Pass | B recent result below fold on phone |
| Safety uniqueness (strip only) | Pass | Pass | Pass | Single `role="status"`; no body paper/live/kill/API |
| Long Chinese + long IDs | Pass | Pass | Pass | wrap/break-all; no page overflow |
| Reduced motion | Pass | Pass | Pass | shared kill-switch; B spark neutralized |
| Contrast | Pass* | Pass* | Pass* | *disabled copy ~3.95:1 medium warn |
| Viewport 1440 | Pass | Pass | Pass | no overflow; secondary present |
| Viewport 1280 | Pass | Pass | Pass | secondary collapses; content preserved |
| Viewport 768 | Pass | Pass | Pass | stack honest |
| Viewport 390 | Pass | Fail S5 | Pass | no overflow; B fold issue only |
| 44px targets + focus order | Pass | Pass | Pass | 0 sub-44 targets measured |
| Automation compression | Pass | Pass | Pass | one row/summary |
| Direction identity (A/B/C distinct) | Pass | Pass | Pass | desk / timeline / split |

---

## Outcome

| Direction | Result |
| --- | --- |
| A `direction-a` | **Pass** — ready for selection consideration |
| B `direction-b` | **Pass with caveat** — ready for selection; plan mobile progress compression if chosen |
| C `direction-c` | **Pass** — ready for selection consideration |

### Package verdict: **Ready for user selection**

**Not approved.** No direction is selected. No F0 decision block should be written until the user states a written choice (filename stem under `f0/`, approver `user`, date, and only user-requested adjustments).

F1 should not start from a presumed winner.
