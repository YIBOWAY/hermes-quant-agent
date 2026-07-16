# Frontend F0 Polish — Accessibility Review (Direction A)

**Scope:** Polished F0 COO desk at  
`/Users/sunyibo/programs/ai-quant-platform/docs/design/hermes-workbench/f0/`  
**Files under review:** `direction-a.html`, `shared.css`  
**Platform:** Web (static HTML prototype)  
**Standard:** WCAG 2.2 Level AA (POUR) + F0 polish gates  
**Date:** 2026-07-13  
**Reviewer role:** Senior Accessibility Architect (independent of polish implementer)

---

## Verdict

# **Pass**

Polished direction-a clears every requested hard gate: single safety strip, 44px targets, focus appearance/order, reduced motion, disabled-reason contrast, real mobile tab buttons, and honest breakpoints (no whole-UI `transform: scale`).

Non-blocking F1 carry-overs remain (orphan read-only field labels, one bare numeric nav badge, toolbar keyboard pattern). None fail F0 polish a11y.

---

## Requested checks (summary)

| # | Check | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Single safety strip | **Pass** | One `.safety` + `role="status"`; body does not restate paper/live/kill/API as chrome |
| 2 | 44px interactive targets | **Pass** | Global `min-height: 44px` on interactive set; reinforced on nav, mobile tabs, `.btn`, summaries |
| 3 | Focus | **Pass** | `:focus-visible` 2px Hermes outline; hidden panels via `display: none`; logical DOM order |
| 4 | Reduced motion | **Pass** | `prefers-reduced-motion: reduce` kills animation/transition/scroll-behavior |
| 5 | Disabled reason contrast | **Pass** | `--muted-readable: #b4b9c3` on `--surface`/`--bg`; note not under button opacity |
| 6 | Real mobile tab buttons | **Pass** | `.mobile-tabs` uses `<button type="button">`, not inert spans |
| 7 | No transform-scale fake RWD | **Pass** | Real media queries only; no layout `transform: scale` on A |

---

## 1. Single safety strip

### Pass criteria
Only the global top strip may convey paper / live / kill / API. Strip is a status landmark. No in-body second safety chrome.

### Evidence

```html
<div class="safety" role="status">
  仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK
</div>
```

| Criterion | Result | Notes |
| --- | --- | --- |
| One strip per document | **Pass** | Single `.safety` in `direction-a.html` |
| Status landmark | **Pass** | `role="status"` ⇒ implicit `aria-live="polite"` |
| No body duplicate chrome | **Pass** | Side rail: “仅全局顶栏展示 · 此处不重复 paper/live/kill” is meta instruction, not a second live status |
| Not mixed into task cards | **Pass** | Approval / automation / result use product status (`pending`, `stale`, `completed_degraded`), not kill/live flags |

**Out of scope as “duplicate safety chrome” (not failures):**
- Nav foot `<code>paper only</code>` — prototype label, not live trading status.
- Result note “不授予 paper/live 资格” — product eligibility copy, not a second SafetyStrip.

**Accessibility tree:** `status` — “仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK”

**WCAG:** 4.1.3 Status Messages; 1.3.1 Info and Relationships.

**Implementation note:** Keeping paper/live/kill/API exclusively in one live region prevents SR users from hearing conflicting or repeated safety state when scanning the desk.

---

## 2. 44px targets

### Pass criteria
Interactive elements meet F0 brief **44×44 CSS px** spirit (height + practical width); WCAG 2.5.8 AA minimum is 24×24.

### Evidence (`shared.css`)

```css
button,
a,
input,
textarea,
summary,
[role="button"],
.hit {
  min-height: 44px;
}
```

Reinforced in direction-a:

| Control class | min-height |
| --- | --- |
| `.nav-item` | 44px |
| `.mobile-tabs button` | 44px |
| `.btn` / `.state-bar button` | 44px (shared) |
| `details.tech summary` | 44px (shared) |
| Disabled 发送 / 在本壳批准 | inherit 44px |

| Criterion | Result | Notes |
| --- | --- | --- |
| Interactive height ≥ 44 | **Pass** | Global + local rules |
| Disabled controls included | **Pass** | Disabled CTAs keep hit area |
| Spacing | **Pass** | `gap: 8px` on action rows; flex-wrap at 390 |
| Icon-only empty buttons | **N/A** | No icon-only controls |

**Note:** Contract is `min-height`, not `min-width`. Visible CTAs use horizontal padding (`0 14–16px`) with multi-character labels; practical width exceeds 44px. No icon-only targets.

**WCAG:** 2.5.8 Target Size (Minimum); brief exceeds with 44px height.

---

## 3. Focus

### Expected order (direction-a)

1. Safety strip (status; not focusable)
2. State-bar view toggles (`aria-pressed`) — review chrome
3. Nav rail buttons (desktop ≥768) **or** mobile tab buttons (≤767)
4. Visible panel content (CTAs, `<summary>`, disabled approve when on approval)
5. Composer dock (disabled textarea/button typically skipped by Tab)
6. Secondary panel (wide only; no focusable controls in current markup)

Hidden compositions use `display: none` via `body[data-view]` + `[data-panel]`, so inactive panels leave the a11y tree and tab order.

### Focus appearance

```css
:focus-visible {
  outline: 2px solid var(--hermes); /* #9085e9 */
  outline-offset: 2px;
}
```

| Criterion | Result | Notes |
| --- | --- | --- |
| Focus visible | **Pass** | 2px solid accent on dark canvas |
| Focus order logical | **Pass** | DOM ≈ visual reading order |
| No keyboard trap | **Pass** | Native controls only; no custom trap |
| Hidden panels excluded | **Pass** | `display: none` on inactive `[data-panel]` |

**WCAG:** 2.4.3 Focus Order; 2.4.7 Focus Visible; 2.4.11 Focus Appearance (intent); 2.1.1 Keyboard.

### Non-blocking

| ID | Issue | Severity | F1 fix |
| --- | --- | --- | --- |
| F-1 | `role="toolbar"` on state-bar without arrow-key toolbar pattern | Low (review chrome) | Toggle group or plain button group in production |
| F-2 | Mobile tabs are real buttons but not wired to view/nav state (static chrome) | Info | Wire or treat as decorative section labels in F1 |

---

## 4. Reduced motion

### Evidence (`shared.css`)

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation: none !important;
    transition: none !important;
    scroll-behavior: auto !important;
  }
}
```

| Criterion | Result | Notes |
| --- | --- | --- |
| prefers-reduced-motion honored | **Pass** | Global kill-switch |
| Motion not sole meaning | **Pass** | Status is text + semantic chips |
| No scroll hijack on view change | **Pass** | Script only sets `data-view` + `aria-pressed` |
| Direction-a transforms | **Pass** | Only disclosure caret `rotate(90deg)`; neutralized when reduced-motion |

**WCAG:** 2.3.3 Animation from Interactions (AAA spirit); 1.4.1 Use of Color.

---

## 5. Contrast of disabled reason

### Pass criteria
Disabled composer **reason text** ≥ **4.5:1** against its surface; reason must not inherit control `opacity` dimming.

### Token & structure

| Token / rule | Value |
| --- | --- |
| `--muted-readable` | `#b4b9c3` |
| Composer surface | `--surface` `#0f1011` |
| Canvas / textarea bg | `--bg` `#010102` / `#0a0a0b` |
| `.composer-note` | `color: var(--muted-readable)`; sibling of disabled button, not child |
| `button:disabled` | `opacity: 0.45` — **controls only** |
| `textarea:disabled` | `opacity: 1` + `--muted-readable` (not dimmed by 0.45) |

### Contrast estimate (WCAG relative luminance)

| Pair | Approx. ratio | AA 4.5:1 |
| --- | --- | --- |
| `#b4b9c3` on `#0f1011` (composer note) | **~9.7:1** | **Pass** |
| `#b4b9c3` on `#010102` / `#0a0a0b` (textarea value) | **≥ ~10:1** | **Pass** |

| Criterion | Result | Notes |
| --- | --- | --- |
| Reason text contrast | **Pass** | Dedicated readable mute, not `--muted` `#8a8f98` |
| Not dimmed by parent opacity | **Pass** | Note is outside disabled button; textarea opacity forced to 1 |
| Programmatic disabled | **Pass** | `disabled` on textarea + 发送 |
| Honest copy | **Pass** | “真实 Hermes 写入能力尚未通过 · 本切片不向 Hermes / tasks / provider 提交。” |
| Accessible name | **Pass** | `label.sr-only` + `for`/`id` + `aria-label` on textarea |

**Accessibility tree (composer):**  
`section "Hermes conversation"` → `textbox "和 Hermes 对话" disabled` (value restates boundary) → static note → `button "发送" disabled`.

**WCAG:** 1.4.3 Contrast (Minimum); 3.3.2 Labels or Instructions; 4.1.2 Name, Role, Value.

**Implementation note:** Separating “control opacity” from “reason ink” is the correct pattern so disabled affordance does not fail contrast for explanatory copy.

---

## 6. Real mobile tab buttons

### Prior defect (pre-polish)
Task-1 a11y review **F-1 / A-2**: mobile “tabs” were inert `<span>`s with `aria-current="page"` — looked operable, not in tab order.

### Post-polish evidence

```html
<div class="mobile-tabs" role="navigation" aria-label="移动端分区">
  <button type="button" aria-current="page">今日</button>
  <button type="button">任务</button>
  <button type="button">审批 · 1</button>
  <button type="button">结果</button>
</div>
```

```css
.mobile-tabs button {
  min-height: 44px;
  /* … */
}
@media (max-width: 767px) {
  .nav-rail { display: none; }
  .mobile-tabs { display: flex; }
}
@media (min-width: 768px) {
  .mobile-tabs { display: none; }
}
```

| Criterion | Result | Notes |
| --- | --- | --- |
| Real widgets | **Pass** | Native `<button type="button">` |
| Keyboard operable | **Pass** | In tab order when visible |
| 44px height | **Pass** | Explicit rule |
| Named navigation | **Pass** | `role="navigation"` + `aria-label="移动端分区"` |
| Current page indicated | **Pass** | `aria-current="page"` on active tab |

**WCAG:** 2.1.1 Keyboard; 4.1.2 Name, Role, Value; 2.4.6 Headings and Labels.

---

## 7. No transform-scale fake RWD

| Check | Result | Evidence |
| --- | --- | --- |
| Whole-UI `transform: scale` | **Pass** | None on `html` / `body` / `.prototype` / `.proto-a` |
| Real breakpoints | **Pass** | ≤1279 secondary collapse; ≤1024 desk/KPI stack; ≤767 mobile nav; ≤430 type tighten |
| Viewport honesty | **Pass** | `width=device-width`, `min-width: 320px`, `minmax(0, …)` grids, `overflow-wrap` / `word-break` on IDs |
| Decorative scale only | **N/A for A** | Direction B spark `scaleY` is out of this review scope |

**WCAG:** 1.4.10 Reflow (intent); 1.4.4 Resize Text (reflow, not scale).

---

## WCAG 2.2 AA checklist (direction-a polish)

### Perceivable
- [x] **1.1.1 Text Alternatives** — decorative brand/nav marks `aria-hidden`
- [x] **1.3.1 Info and Relationships** — landmarks, headings, lists, native details
- [x] **1.3.2 Meaningful Sequence** — DOM matches visual scan order
- [x] **1.4.1 Use of Color** — pills pair color with text labels
- [x] **1.4.3 Contrast (Minimum)** — disabled reason uses high-contrast mute; primary ink on near-black
- [x] **1.4.10 Reflow** — real breakpoints; no whole-UI scale

### Operable
- [x] **2.1.1 Keyboard** — buttons, summaries; mobile tabs are real controls
- [x] **2.4.3 Focus Order** — logical; inactive panels excluded
- [x] **2.4.7 Focus Visible** — `:focus-visible` outline
- [x] **2.5.8 Target Size (Minimum)** — ≥24px; brief 44px height met

### Understandable
- [x] **3.2.1 On Focus** — no context change on focus alone
- [x] **3.3.2 Labels or Instructions** — composer named; disabled reason visible and high-contrast

### Robust
- [x] **4.1.2 Name, Role, Value** — buttons named; `aria-pressed` / `aria-current` / disabled exposed
- [x] **4.1.3 Status Messages** — safety `role="status"`

---

## Hard-fail gate (F0 polish a11y)

| Hard fail | Status |
| --- | --- |
| Duplicate safety chrome | **Clear** |
| Composer looks/behaves submittable | **Clear** |
| Disabled reason contrast &lt; 4.5:1 | **Clear** |
| Interactive targets under 44px height | **Clear** |
| Mobile tabs inert / non-widget | **Clear** (fixed vs pre-polish) |
| Whole-UI transform scale | **Clear** |
| Missing reduced-motion kill-switch | **Clear** |
| No focus indicator | **Clear** |

---

## Non-blocking F1 carry-overs

| ID | Issue | Severity | Fix |
| --- | --- | --- | --- |
| N-1 | Nav **审批** badge bare `1` (今日 has `aria-label="1 项待确认"`) | Low | Mirror descriptive `aria-label` |
| N-2 | Read-only CAS fields use `<label>` without control association | Low | Use `<dt>/<dd>` or `<span class="k">` |
| N-3 | Review `role="toolbar"` without arrow-key pattern | Low | Drop toolbar role or implement pattern |
| N-4 | Mobile tabs not wired to state (static prototype chrome) | Info | Wire nav or demote to non-interactive section headers |
| N-5 | Safety strip 11px / 10px at ≤767 | Info | Keep ≥12px for essential status if production QA flags |

---

## Accessibility tree (key paths)

**Safety**  
`status` — 仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK

**View toggles**  
`toolbar "F0 状态切换（设计评审）"` → toggle buttons with `aria-pressed`

**Desktop nav**  
`navigation "Hermes 主导航"` → buttons “今日” (current, badge “1 项待确认”), “任务”, “审批”, “结果”

**Mobile nav (≤767)**  
`navigation "移动端分区"` → buttons “今日” (current), “任务”, “审批 · 1”, “结果”

**Composer**  
`section "Hermes conversation"` → disabled textbox “和 Hermes 对话” + reason text + disabled “发送”

**Approval**  
`button "查看准确摘要"` → `button "在本壳批准（未开放）" disabled`

---

## Sign-off

| Role | Result |
| --- | --- |
| Accessibility Architect (polish a11y) | **Pass** |

**Related:** `frontend-f0-polish-brief.md`, `frontend-f0-polish-report.md`, `frontend-f0-craft-checklist.md`, prior `frontend-task-1-a11y-review.md` (pre-polish baseline).
