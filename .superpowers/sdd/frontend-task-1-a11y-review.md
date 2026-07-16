# Frontend Task 1 — Accessibility Review (F0 Hermes prototypes)

**Scope:** `/Users/sunyibo/programs/ai-quant-platform/docs/design/hermes-workbench/f0/`  
**Files:** `shared.css`, `direction-a.html`, `direction-b.html`, `direction-c.html`  
**Platform:** Web (static HTML prototypes)  
**Standard:** WCAG 2.2 Level AA (POUR), plus F0 brief constraints (44×44 targets, single SafetyStrip, honest disabled composer, real breakpoints)  
**Date:** 2026-07-13  
**Reviewer role:** Senior Accessibility Architect (independent of implementation agent)

---

## Verdict

# **Ready for user selection**

All three directions meet the F0 accessibility gates that would block visual selection. Remaining issues are non-blocking polish for F1 production components; they do not invalidate hierarchy comparison or direction choice.

Do **not** mark any direction as F0-approved in product docs until the user writes an explicit selection. This review only clears a11y readiness for that gate.

---

## Review matrix (requested checks)

| Check | shared.css | Direction A | Direction B | Direction C |
| --- | --- | --- | --- | --- |
| Single safety status | Pass (strip styles only) | **Pass** | **Pass** | **Pass** |
| Focus order | Pass (`:focus-visible`, `display:none` panels) | **Pass*** | **Pass** | **Pass** |
| 44px targets | Pass (`min-height: 44px` on interactive set) | **Pass** | **Pass** | **Pass** |
| Reduced motion CSS | **Pass** | inherits | **Pass** (+ spark override) | inherits |
| ARIA / labels | Pass (`sr-only`, focus tokens) | **Pass*** | **Pass** | **Pass** |
| Disabled composer honesty | Pass (disabled + opacity) | **Pass** | **Pass** | **Pass** |
| No transform-scale fake responsiveness | **Pass** (media queries only) | **Pass** | **Pass*** | **Pass** |

\* See non-blocking findings below.

---

## 1. Single safety status

### Pass criteria
Only the global top strip may convey paper / live / kill / API. Strip must be a status landmark. No in-body duplicate safety chrome.

### Evidence

All three files use one strip:

```html
<div class="safety" role="status">
  仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK
</div>
```

| Criterion | Result | Notes |
| --- | --- | --- |
| U1 Single SafetyStrip | **Pass** | One `.safety` per document; no second banner |
| U2 No content duplicates | **Pass** | A sidebar says “仅全局顶栏展示 · 此处不重复 paper/live/kill” — meta copy, not a second status source |
| U3 Status landmark | **Pass** | `role="status"` ⇒ implicit `aria-live="polite"` |
| U4 Not mixed with tasks | **Pass** | Approval / automation / result cards do not restate kill or live flags |

**Accessibility tree (strip):** status — “仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK”

**WCAG:** 4.1.3 Status Messages; 1.3.1 Info and Relationships; 2.4.6 Headings and Labels (status is not nested under task chrome).

---

## 2. Focus order

### Expected order (all directions)

1. Review state-bar toggle buttons (F0 chrome only; not production TopBar)
2. Primary chrome / nav (if present and visible)
3. Visible main content controls (CTAs, `<summary>`, disabled approval button)
4. Composer region (disabled controls; typically skipped by Tab when `disabled`)
5. Secondary panel content (if visible and focusable)

Hidden compositions use `display: none` via `body[data-view=…]` / `[data-panel]`, so inactive panels are correctly removed from the accessibility tree and tab order.

### Per direction

| Direction | DOM / reading order | Result |
| --- | --- | --- |
| **A** | safety → state-bar → nav-rail (desktop) → main panels → composer-dock → secondary | **Pass** |
| **B** | safety → state-bar → top-band → stream → secondary composer **or** mobile-composer (one visible via breakpoint) | **Pass** |
| **C** | safety → state-bar → quiet chrome nav → left canvas (answers + thread + composer) → right canvas | **Pass** |

### Focus appearance

```css
:focus-visible {
  outline: 2px solid var(--hermes);
  outline-offset: 3px;
}
```

**Pass** for SC 2.4.7 Focus Visible and intent of 2.4.11 Focus Appearance (2px solid, high-contrast purple on dark).

### Non-blocking

| ID | Issue | Severity | Direction |
| --- | --- | --- | --- |
| F-1 | Mobile “tabs” are non-interactive `<span>`s with `aria-current="page"`, sized like buttons (44px). They look operable but are not in tab order and cannot be activated. | Low (prototype chrome) | A only |
| F-2 | `role="toolbar"` on state-bar without arrow-key toolbar pattern. Tab-through is acceptable for F0 review chrome; prefer a toggle group or plain buttons in production. | Low | A/B/C |

**WCAG:** 2.4.3 Focus Order; 2.1.1 Keyboard.

---

## 3. 44px targets

### shared.css contract

```css
button, a, input, textarea, summary, [role="button"], .hit {
  min-height: 44px;
}
```

Also reinforced on `.btn`, `.state-bar button`, `details.tech summary`, nav items, quiet-nav buttons, progress steps (non-interactive but tall), answer chips.

| Criterion | Result | Notes |
| --- | --- | --- |
| T1 Interactive ≥ 44 CSS px | **Pass** | All real buttons / summaries / textareas use `min-height: 44px` |
| T2 Disabled controls included | **Pass** | Disabled 发送 and approve keep 44px height |
| T3 Spacing | **Pass** | `gap: 8px` on action rows; flex-wrap prevents thumb collision at 390 |
| T4 Focus visible | **Pass** | See §2 |

**Note:** Only `min-height` is enforced, not `min-width`. Visible CTAs (“查看准确摘要”, “发送”, state-bar pills) have horizontal padding sufficient to exceed 44px width. No icon-only controls exist in F0.

**WCAG:** 2.5.8 Target Size (Minimum) AA is 24×24 — exceeded; brief requires 44×44 (AAA 2.5.5 spirit) — met for height and practical width.

---

## 4. Reduced motion CSS

### shared.css (all directions)

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation: none !important;
    transition: none !important;
  }
}
```

| Criterion | Result | Notes |
| --- | --- | --- |
| M1 prefers-reduced-motion | **Pass** | Global kill-switch present |
| M2 No motion-only meaning | **Pass** | State uses text pills / labels (pending, degraded, stale), not animation |
| M3 No scroll hijack | **Pass** | View toggles only set `data-view`; no forced scroll |

### Direction B decorative spark

Result composition uses `transform: scaleY(…)` on decorative bars (`aria-hidden="true"`). Not whole-UI scaling. Extra reduced-motion rule zeros those transforms:

```css
@media (prefers-reduced-motion: reduce) {
  .spark div { transform: none !important; }
}
```

**Pass** — decorative only; meaning remains in adjacent text (“completed_degraded”).

**WCAG:** 2.3.3 Animation from Interactions (AAA spirit); 1.4.1 Use of Color (motion not sole cue).

---

## 5. ARIA labels and semantics

### Shared strengths

| Pattern | Where | Assessment |
| --- | --- | --- |
| `lang="zh-Hans"` | all | Correct document language |
| `role="status"` safety | all | Status messages |
| State toggles `aria-pressed` | all | Toggle button state for review views |
| `aria-label` on nav / regions | all | Landmarks for conversation, work canvas, progress |
| `aria-labelledby` + `h1`/`h2` | all | Today / approval / result titles |
| `aria-hidden` on decorative marks | A/B/C | Brand dots, nav dots, spark |
| Composer `aria-label="和 Hermes 对话"` | all | Accessible name on disabled textarea |
| A: `label.sr-only` + `for`/`id` | A | Best of three for composer naming |
| Native `<details>` / `<summary>` | all | Tech disclosure without custom ARIA |
| Disabled approve with visible text “未开放” | all | Name + disabled state honest |

### Accessibility tree examples

**Composer (all directions):**  
`section "Hermes conversation"` → `textbox "和 Hermes 对话" disabled, value="真实 Hermes 写入能力尚未通过"` → `button "发送" disabled` + supporting note text.

**Approval CTA:**  
`button "查看准确摘要"` → `button "在本壳批准（未开放）" disabled`.

**Progress (B):**  
`group/region "研究流水线进度"` → static text steps “研究运行 / 结果产出 / 人工确认 / 后续路径” (color + text; not color-only).

### Non-blocking ARIA gaps

| ID | Issue | Severity | Direction | F1 fix |
| --- | --- | --- | --- | --- |
| A-1 | Nav badge on **审批** is bare `1` without `aria-label` (今日 badge correctly has `aria-label="1 项待确认"`) | Low | A | Mirror descriptive label |
| A-2 | Mobile tab strip uses `aria-current` on non-widgets | Low | A | Use real buttons or plain text without `aria-current` |
| A-3 | Read-only CAS fields use `<label>` without associated control (`div.val`) | Low | A/B/C | Prefer `<div class="field"><span class="k">` or description list |
| A-4 | B/C composer lacks visible/`for` label (aria-label only — acceptable) | Info | B/C | Optional parity with A’s `sr-only` label |
| A-5 | Duplicate `aria-label="Hermes conversation"` on B side + mobile composers | Info | B | One live region in production layout |

**WCAG:** 4.1.2 Name, Role, Value; 1.3.1 Info and Relationships; 2.5.3 Label in Name (N/A — no icon-only).

---

## 6. Disabled composer honesty

| Criterion | A | B | C |
| --- | --- | --- | --- |
| C1 Visually disabled | **Pass** (`opacity: 0.55`, `cursor: not-allowed`) | **Pass** | **Pass** |
| C2 Programmatically disabled | **Pass** (`disabled` on textarea + 发送; no submit/network) | **Pass** (×2 layouts, both disabled) | **Pass** |
| C3 Honest reason | **Pass** — “真实 Hermes 写入能力尚未通过 · 本切片不向 Hermes / tasks / provider 提交。” | **Pass** — “真实 Hermes 写入能力尚未通过 · 时间线只读。” | **Pass** — “真实 Hermes 写入能力尚未通过” |
| C4 No false affordance | **Pass** | **Pass** | **Pass** |
| C5 Boundary in all states | **Pass** (composer dock persists across views) | **Pass** | **Pass** |

Value text inside the disabled textarea restates the capability boundary (not a fake “try again” / offline glitch).

**WCAG:** 3.3.2 Labels or Instructions; 4.1.2 Name, Role, Value (disabled state exposed).

---

## 7. No transform-scale fake responsiveness

| Check | Result | Evidence |
| --- | --- | --- |
| Whole-UI `transform: scale` | **Pass** — none on `html` / `body` / `.prototype` | Grep clean for layout scale |
| Real breakpoints | **Pass** | `1279` secondary collapse; `767` mobile stack; `430` tight phone; A also `1024` desk-grid |
| Decorative transform only | **Pass** | B spark `scaleY` + `aria-hidden` + reduced-motion override |
| `min-width: 320px` + `max-width: 100%` / `minmax(0, …)` grids | **Pass** | Overflow-safe long IDs (`word-break` / `overflow-wrap`) |

Matches brief Step 2 and UX checklist V2 (“no whole-UI scale”).

**WCAG:** 1.4.10 Reflow (intent); 1.4.4 Resize Text (layout reflows, not scales).

---

## WCAG 2.2 AA checklist (F0 aggregate)

### Perceivable
- [x] **1.1.1 Text Alternatives** — decorative marks `aria-hidden`; no information-only icons without text
- [x] **1.3.1 Info and Relationships** — headings, landmarks, lists, details
- [x] **1.3.2 Meaningful Sequence** — DOM order matches visual reading order
- [x] **1.4.1 Use of Color** — pills/steps pair color with text
- [x] **1.4.3 Contrast (Minimum)** — primary text/tokens meet dark-theme AA intent; disabled opacity is expected muted (note for design QA)
- [x] **1.4.10 Reflow** — breakpoints reflow; no horizontal fake scale

### Operable
- [x] **2.1.1 Keyboard** — native buttons/summaries; no custom widgets requiring pointer
- [x] **2.4.3 Focus Order** — logical; hidden panels excluded
- [x] **2.4.7 Focus Visible** — `:focus-visible` outline
- [x] **2.5.8 Target Size (Minimum)** — ≥24px; brief 44px height met

### Understandable
- [x] **3.2.1 On Focus** — no surprise context change on focus
- [x] **3.3.2 Labels or Instructions** — composer named; disabled reason visible

### Robust
- [x] **4.1.2 Name, Role, Value** — buttons named; pressed state; disabled state
- [x] **4.1.3 Status Messages** — safety `role="status"`

---

## Direction scorecard (a11y only)

| Check group | A (COO desk) | B (timeline) | C (split canvas) |
| --- | --- | --- | --- |
| Single safety | Pass | Pass | Pass |
| Focus order | Pass (mobile tab chrome caveat) | Pass | Pass |
| 44px targets | Pass | Pass | Pass |
| Reduced motion | Pass | Pass | Pass |
| ARIA / labels | Pass (badge + mobile tabs) | Pass | Pass |
| Disabled composer | Pass (strongest note copy) | Pass | Pass |
| No fake scale | Pass | Pass (decorative spark only) | Pass |
| **Overall a11y** | **Pass** | **Pass** | **Pass** |

No direction fails a hard a11y gate. Prefer A’s composer labeling pattern (`sr-only` + `id`) as the production reference. Prefer B’s dual-composer CSS pattern only as temporary F0 layout, not as dual live regions in F1.

---

## Hard-fail gate (from F0 UX checklist, a11y-relevant)

| Hard fail | Status |
| --- | --- |
| Duplicate safety chrome | **Clear** |
| Composer looks/behaves submittable | **Clear** |
| Interactive targets under 44px | **Clear** |
| Whole-UI transform scale | **Clear** |

---

## Recommended F1 carry-overs (do not block selection)

1. Replace A mobile tab `<span>`s with real controls or non-affordance text; drop `aria-current` on non-widgets.
2. Add descriptive `aria-label` to every numeric nav badge.
3. Replace orphan `<label>` on read-only CAS fields with non-label semantics.
4. Keep single SafetyStrip as a platform invariant in React shell.
5. Preserve `prefers-reduced-motion` kill-switch and 44px interactive floor in design tokens.
6. Composer: `disabled` + visible capability copy + no network path (D-31 honesty).

---

## Implementation note

F0 prototypes correctly prioritize **Name / Role / Value** and **status uniqueness** over production completeness. Screen reader users hear a single safety status, named regions, collapsed technical detail under native disclosures, and an unambiguously disabled conversation boundary. Keyboard users get a logical tab path through review toggles and visible CTAs, with inactive compositions removed via `display: none`.

---

## Verdict (repeat)

**Ready for user selection**

Proceed to user visual/hierarchy selection among A / B / C. Do not write F0 `approved` or commit an F0 decision until the user states a direction explicitly.
