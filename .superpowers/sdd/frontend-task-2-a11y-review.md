# Frontend Task 2 — Accessibility Review (F1 full-state prototype)

**Scope:** `/Users/sunyibo/programs/ai-quant-platform/docs/design/hermes-workbench/f1/`  
**Files:** `prototype.html`, `prototype.css`, `states/*.json` (announcement copy only)  
**Platform:** Web (static HTML + local JSON catalogs)  
**Standard:** WCAG 2.2 Level AA (POUR) + F1 brief Step 3 gates  
**Date:** 2026-07-13  
**Reviewer role:** Senior Accessibility Architect (independent of implementation agent)

---

## Verdict

# **Ready for user approval**

The F1 prototype meets every requested hard a11y gate for design approval: one `aria-live="polite"` region for state transitions, `aria-pressed` on surface/state buttons, focus restore after approval detail closes, keyboard-operable chrome, 44px interactive floor, a single safety strip, and a visible **prototype data** label outside the simulated product.

Non-blocking polish remains (modal Tab containment, orphan read-only field labels, bare numeric badges, toolbar arrow-key pattern). None block the user written-approval gate. Do **not** record F1 approval in README or commit the approval message until the user states it explicitly.

---

## Requested focus (summary)

| # | Check | Result | Evidence |
| --- | --- | --- | --- |
| 1 | `aria-live` state announcements | **Pass** | One `#live-region` · `aria-live="polite"` · `aria-atomic="true"`; used for boot, surface/state, walkthrough, modal open/close |
| 2 | `aria-pressed` on state controls | **Pass** | Surface toolbar + dynamic State toolbar buttons; walk uses `aria-current="step"` (correct for steps) |
| 3 | Focus restore after detail | **Pass** | `state.lastFocus` on open → `el.focus()` on close; Escape + backdrop + 关闭 |
| 4 | Keyboard operable | **Pass** | Native buttons/summaries; Escape closes dialog; no product keyboard trap |
| 5 | 44px targets | **Pass** | Global `min-height: 44px` on interactive set; reinforced on nav, mobile tabs, `.btn`, review chrome, summaries |
| 6 | Single safety strip | **Pass** | One `.safety` + `role="status"`; body explicitly does not restated paper/live/kill/API as chrome |
| 7 | Prototype data label | **Pass** | `.proto-badge` **prototype data** in `.review-chrome` (outside product shell) |

---

## 1. `aria-live` (state transitions)

### Pass criteria (brief Step 3)
Announce state transitions through **one** `aria-live="polite"` region.

### Evidence

```html
<div id="live-region" class="sr-only" aria-live="polite" aria-atomic="true"></div>
```

```js
function announce(msg) {
  var region = byId("live-region");
  if (!region) return;
  region.textContent = "";
  window.setTimeout(function () {
    region.textContent = msg;
  }, 20);
}
```

| Criterion | Result | Notes |
| --- | --- | --- |
| Single dedicated polite region | **Pass** | One `#live-region`; not duplicated per surface |
| Atomic updates | **Pass** | `aria-atomic="true"` |
| Re-announce pattern | **Pass** | Clear → 20ms set (standard SR re-speak technique) |
| Surface / state change | **Pass** | `setSurfaceState(…, true)` → catalog `announcements[0]` or fallback `状态 surface / id` |
| Walkthrough steps | **Pass** | `setWalk(…, true)` → step `announce` string |
| Modal open/close | **Pass** | “已打开/已关闭准确摘要对话框。” |
| Boot / load failure | **Pass** | Boot success + `role="alert"` boot error path also announces |
| Visually hidden | **Pass** | `.sr-only` clip pattern |

**Related (not a second transition region):**  
`.safety` uses `role="status"` (implicit polite live) for **static** trading-safety copy — correct SafetyStrip pattern from F0, not a competing state-matrix announcer.

**Conversation `exec-banner` with `role="status"`:** presents execution status text inside the product view. Content is re-rendered with the view, not independently patched; primary transition speech still goes through `#live-region`. **Non-blocking** — production should keep one intentional live channel for transient toasts and avoid stacking multiple `role="status"` islands that re-announce on every paint.

**Accessibility tree:**  
`live region (polite, atomic)` — e.g. “状态 home / normal”, “Walkthrough：Gate 2 准确 manifest 摘要。”, “已关闭准确摘要对话框。”

**WCAG:** 4.1.3 Status Messages; 4.1.2 Name, Role, Value.

**Implementation note:** Separating a dedicated polite region for matrix/walk transitions from the permanent safety `role="status"` keeps SR users from conflating “trading posture” with “which catalog state is on screen.”

---

## 2. `aria-pressed` (state buttons)

### Pass criteria
State buttons expose pressed/unpressed for assistive tech.

### Evidence

**Surface toolbar (static markup + JS sync):**

```html
<button type="button" data-surface="home" aria-pressed="true">Home</button>
<!-- … Conversation / Tasks / Approvals / Results with aria-pressed="false" -->
```

```js
document.querySelectorAll("[data-surface]").forEach(function (btn) {
  var on = btn.getAttribute("data-surface") === state.surface;
  btn.setAttribute("aria-pressed", on ? "true" : "false");
});
```

**State catalog toolbar (built from JSON):**

```js
btn.setAttribute("aria-pressed", st.id === state.stateId ? "true" : "false");
btn.textContent = st.id; // empty/loading/normal/…
```

| Control set | Attribute | Result |
| --- | --- | --- |
| Surface (Home…Results) | `aria-pressed` | **Pass** |
| State IDs per surface | `aria-pressed` | **Pass** (rebuilt on each render; pressed tracks `state.stateId`) |
| Walkthrough steps 1–7 | `aria-current="step"` | **Pass** (step indicator, not toggle — correct pattern) |
| Product nav / mobile tabs | `aria-current="page"` | **Pass** (location, not multi-select) |

**Accessibility tree (review chrome):**  
`toolbar "状态表面切换"` → toggle buttons Home (pressed) / Conversation / …  
`toolbar "状态目录"` → toggle buttons for each catalog `id` with pressed on active.

**WCAG:** 4.1.2 Name, Role, Value.

### Non-blocking

| ID | Issue | Severity | Fix |
| --- | --- | --- | --- |
| P-1 | `role="toolbar"` on walk/surface/state rows without arrow-key toolbar pattern | Low (review chrome) | Drop toolbar role or implement roving tabindex in production |
| P-2 | State button accessible name is raw id (`digest_mismatch`) | Info | Optional `aria-label` with zh title for denser SR context |

---

## 3. Focus restore after approval detail

### Pass criteria
After modal-like approval detail closes, keyboard focus returns to the control that opened it.

### Evidence

```js
function openModal(fromEl) {
  // …
  state.lastFocus = fromEl || document.activeElement;
  // …
  root.hidden = false;
  window.setTimeout(function () { dialog.focus(); }, 0);
  announce("已打开准确摘要对话框。");
}

function closeModal() {
  // …
  root.hidden = true;
  announce("已关闭准确摘要对话框。");
  var el = state.lastFocus;
  state.lastFocus = null;
  if (el && typeof el.focus === "function") {
    window.setTimeout(function () { el.focus(); }, 0);
  }
}
```

| Criterion | Result | Notes |
| --- | --- | --- |
| Store opener | **Pass** | `openModal(btn)` from `data-action` handlers |
| Initial focus into dialog | **Pass** | `#modal-dialog` is `tabindex="-1"` + focused |
| Dialog semantics | **Pass** | `role="dialog"` · `aria-modal="true"` · `aria-labelledby="modal-title"` |
| Close paths restore focus | **Pass** | 关闭 button, backdrop (`data-modal-close`), Escape |
| Hidden when closed | **Pass** | `[hidden]` + CSS `display: none !important` removes from a11y tree |
| Escape | **Pass** | Document keydown → `closeModal()` |

**Accessibility tree (open):**  
`dialog "准确摘要 · Exact manifest summary"` → lead, fields, long error, `button "关闭"`, `button "批准（未开放）" disabled`.

**WCAG:** 2.4.3 Focus Order; 2.1.1 Keyboard; 2.4.7 Focus Visible (dialog receives focus; close is a normal button).

### Non-blocking

| ID | Issue | Severity | Fix |
| --- | --- | --- | --- |
| M-1 | No full Tab **focus trap** while open — keyboard can Tab past dialog into background (AT may honor `aria-modal`, pointer users less so) | Low–Med for production dialog pattern | Cycle Tab within dialog; optional `inert` on `#workbench` while open |
| M-2 | Escape always calls `closeModal` even when already closed (no-op) | Info | Fine |

Brief Step 3 requires **restore**, not full WAI-ARIA APG dialog containment. Restore is correctly implemented → **Pass** for F1 gate.

---

## 4. Keyboard

### Expected tab / activation path

1. Review chrome: Walkthrough steps + 下一步 → Surface toggles → State toggles  
2. Safety strip (status; not focusable)  
3. Desktop nav rail **or** mobile tab buttons (breakpoint)  
4. Main content CTAs / native `<summary>` disclosures  
5. Composer (disabled textarea + 发送 typically skipped by Tab)  
6. Secondary panel (wide only; static list, no focusables)  
7. When detail open: dialog → 关闭 / disabled 批准; Escape restores opener

| Criterion | Result | Notes |
| --- | --- | --- |
| All actions are native widgets | **Pass** | `<button type="button">`, `<summary>`, disabled form controls |
| No product keyboard trap | **Pass** | Escape exits dialog; no custom trap left open |
| Focus appearance | **Pass** | `:focus-visible { outline: 2px solid var(--hermes); outline-offset: 2px; }` |
| View/nav changes keyboard-driven | **Pass** | Click handlers on buttons; no pointer-only gesture UI |
| Disabled send honest | **Pass** | `disabled` + note; click path still preventDefault if forced |

**WCAG:** 2.1.1 Keyboard; 2.1.2 No Keyboard Trap; 2.4.3 Focus Order; 2.4.7 / 2.4.11 Focus Visible / Appearance (intent).

---

## 5. 44px targets

### Evidence (`prototype.css`)

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

Reinforced on:

| Control | Rule |
| --- | --- |
| `.review-row button` | `min-height: 44px` |
| `.nav-item` | `min-height: 44px` |
| `.mobile-tabs button` | `min-height: 44px` |
| `.btn` | `min-height: 44px` |
| `details.tech summary` | `min-height: 44px` |
| Disabled 发送 / 批准（未开放） | inherit 44px height |

| Criterion | Result | Notes |
| --- | --- | --- |
| Interactive height ≥ 44 | **Pass** | Global + local |
| Disabled included | **Pass** | Opacity dims look, not hit area height |
| Spacing | **Pass** | `gap: 8px` on action/review rows; wrap on narrow |
| Icon-only empty buttons | **N/A** | All controls have text names |
| Safety strip 36px min-height | **N/A** | Non-interactive status |

**Note:** Contract is `min-height`, not `min-width`. Multi-character labels + horizontal padding make practical width ≥ 44px for CTAs. Review chrome pills on 390 wrap rather than shrink below height floor.

**WCAG:** 2.5.8 Target Size (Minimum) AA 24×24 — exceeded; brief 44px height met.

---

## 6. Single safety strip

### Pass criteria
Only the global strip conveys paper / live / kill / API. One status landmark. No second safety chrome in the product body.

### Evidence

```html
<div class="safety" role="status">
  仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK
</div>
```

| Criterion | Result | Notes |
| --- | --- | --- |
| One strip | **Pass** | Single `.safety` in document |
| Status landmark | **Pass** | `role="status"` |
| No body duplicate chrome | **Pass** | Side panel: “仅全局顶栏展示 · 此处不重复 paper/live/kill” is meta instruction |
| Product states use product status | **Pass** | Pills use `status_text` (pending, degraded, streaming…), not kill/live flags |

**Out of scope as failures (same as F0):**

- Nav foot `<code>paper only · prototype data</code>` — prototype boundary label, not live trading posture.  
- Gate / result copy about paper eligibility — product semantics, not a second SafetyStrip.

**Accessibility tree:** `status` — “仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK”

**WCAG:** 4.1.3 Status Messages; 1.3.1 Info and Relationships.

---

## 7. Prototype data label

### Pass criteria (brief Step 2)
Visible “prototype data” label **outside** the simulated product chrome so the session cannot be mistaken for live Hermes.

### Evidence

```html
<div class="review-chrome" data-review-chrome>
  <div class="proto-banner">
    <span class="proto-badge" id="proto-data-label">prototype data</span>
    <p>本地 F1 全状态交互原型 · 仅 <code>fetch("./states/*.json")</code> + DOM · …</p>
  </div>
  …
</div>
```

| Criterion | Result | Notes |
| --- | --- | --- |
| Visible label | **Pass** | Uppercase mono badge, dashed Hermes border |
| Outside product shell | **Pass** | Sibling above `.safety` + `#workbench`; not inside `.prototype` |
| Reinforced copy | **Pass** | Banner paragraph, nav foot, side “原型”, composer note, boot announce |
| Stable id for review | **Pass** | `#proto-data-label` |

**Not a WCAG SC by itself** — product honesty / D-31 boundary. Supports Understandable (no false live-session affordance) and pairs with disabled composer.

---

## Supporting gates (carried from F0 polish)

| Check | Result | Notes |
| --- | --- | --- |
| Reduced motion | **Pass** | `prefers-reduced-motion: reduce` kills animation/transition/scroll-behavior |
| Disabled composer honesty | **Pass** | `disabled` textarea + 发送; note uses `--muted-readable`; no form submit (`submit` preventDefault) |
| No whole-UI `transform: scale` | **Pass** | Real breakpoints 1279 / 1024 / 767 / 430 |
| Mobile tabs are real buttons | **Pass** | Wired to `data-nav` → `setSurfaceState` (improves F0 polish N-4) |
| Color not sole status | **Pass** | Pills always carry text (`status_text`) |
| Long IDs reflow | **Pass** | `overflow-wrap` / `word-break` on mono fields |

---

## Accessibility tree (key paths)

**Review chrome**  
`toolbar "研究生命周期 walkthrough"` → step buttons (`aria-current="step"` on active) + 下一步  
`toolbar "状态表面切换"` → `aria-pressed` toggles  
`toolbar "状态目录"` → per-state `aria-pressed` toggles  
static badge “prototype data”

**Safety**  
`status` — 仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK

**Live region**  
polite atomic — transition strings only

**Desktop nav**  
`navigation "Hermes 主导航"` → 今日 / 对话 / 任务 / 审批 / 结果 (`aria-current="page"`)

**Mobile nav (≤767)**  
`navigation "移动端分区"` → same destinations as buttons

**Composer**  
`section "Hermes conversation"` → `textbox "和 Hermes 对话" disabled` + reason + `button "发送" disabled`

**Approval detail**  
`dialog "准确摘要 · Exact manifest summary"` → fields + `button "关闭"` + `button "批准（未开放）" disabled`  
On close → focus returns to opener (e.g. `button "查看准确摘要"`)

---

## WCAG 2.2 AA checklist (F1 prototype)

### Perceivable
- [x] **1.1.1 Text Alternatives** — decorative brand/nav marks `aria-hidden`
- [x] **1.3.1 Info and Relationships** — landmarks, headings, lists, native details, dialog labelling
- [x] **1.3.2 Meaningful Sequence** — DOM order ≈ visual; mobile stack classes do not invert SR order vs composer sibling
- [x] **1.4.1 Use of Color** — status pills always include text
- [x] **1.4.3 Contrast (Minimum)** — primary ink + `--muted-readable` reason copy; disabled controls intentionally muted
- [x] **1.4.10 Reflow** — real breakpoints; no whole-UI scale

### Operable
- [x] **2.1.1 Keyboard** — buttons, summaries, Escape
- [x] **2.1.2 No Keyboard Trap** — dialog exits via Escape/关闭
- [x] **2.4.3 Focus Order** — logical; focus restore after detail
- [x] **2.4.7 Focus Visible** — Hermes `:focus-visible` outline
- [x] **2.5.8 Target Size (Minimum)** — ≥24px; brief 44px height met

### Understandable
- [x] **3.2.1 On Focus** — no context change on focus alone
- [x] **3.3.2 Labels or Instructions** — composer named; prototype boundary visible; disabled reason present

### Robust
- [x] **4.1.2 Name, Role, Value** — `aria-pressed` / `aria-current` / disabled / dialog
- [x] **4.1.3 Status Messages** — safety status + polite live region for transitions

---

## Hard-fail gate (F1 a11y)

| Hard fail | Status |
| --- | --- |
| Missing / multiple competing transition `aria-live` regions | **Clear** (one dedicated polite region) |
| State buttons without `aria-pressed` | **Clear** |
| Modal closes without restoring focus | **Clear** |
| Keyboard cannot operate walk / surface / state / CTAs | **Clear** |
| Interactive targets under 44px height | **Clear** |
| Duplicate paper/live/kill/API safety chrome | **Clear** |
| No visible prototype data label outside product | **Clear** |
| Composer looks/behaves as live Hermes submit | **Clear** |
| Whole-UI transform scale | **Clear** |
| Missing reduced-motion kill-switch | **Clear** |

---

## Non-blocking follow-ups (do not block user approval)

| ID | Issue | Severity | Production / F2 fix |
| --- | --- | --- | --- |
| N-1 | Modal lacks full Tab focus containment while open | Low–Med | `inert` background or roving Tab cycle; keep restore |
| N-2 | Read-only CAS fields use `<label>` without associated control | Low | `<dt>/<dd>` or `<span class="k">` |
| N-3 | Nav badges are bare numbers (`1` / `2`) without descriptive `aria-label` | Low | e.g. `aria-label="1 项待确认"` |
| N-4 | Review `role="toolbar"` without arrow-key pattern | Low | Plain button group or full toolbar pattern |
| N-5 | Extra `role="status"` on conversation `exec-banner` may re-speak on re-render | Info | Prefer static text + single live channel for deltas |
| N-6 | Safety strip drops to 10px at ≤767 | Info | Keep ≥12px if production QA flags essential status |
| N-7 | Dense review chrome on 390 | Info | Must not ship as production TopBar (brief already implies) |

---

## Sign-off

| Role | Result |
| --- | --- |
| Accessibility Architect (F1 a11y) | **Ready for user approval** |

**Related:** `frontend-task-2-brief.md`, `frontend-task-2-report.md`, prior `frontend-task-1-a11y-review.md`, `frontend-f0-polish-a11y.md`.

**Next gate:** Independent UX review table (lifecycle / viewports / reduced motion / overflow / console) + **written user approval** in `docs/design/hermes-workbench/README.md`. Do not create anything under `src/frontend/app`, `components`, or `lib` before that approval.
