# Frontend Task 4 — React Review

**Scope:** Hermes F2 Task 4 shell (`HermesWorkbenchShell`, single `SafetyStrip`, disabled `ComposerDock`)  
**Commit reviewed:** `bf82a76` — `feat(frontend): hermes workbench shell with single safety strip`  
**Platform path:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend`  
**Brief / report:** `frontend-task-4-brief.md` / `frontend-task-4-report.md`  
**Reviewer lane:** React-specific (hooks, a11y, RSC boundary, render correctness, React security)  
**Companion:** Invoke `typescript-reviewer` separately for pure TS concerns  

## Assessment: **Needs fixes**

One **HIGH** accessibility issue blocks approval. No CRITICAL React-security or hooks-rules findings. Task-contract items (single global safety strip, static `blocked_in_this_slice`, composer hard-disabled, no mutation paths) look correct.

## Verification run during review

| Check | Result |
|---|---|
| `npm run type-check` | pass |
| `npm run lint` (`eslint-config-next` → `eslint-plugin-react-hooks`) | pass |
| Production hermes tree: `fetch` / `apiPost` / `WebSocket` / `EventSource` | none |
| Duplicate inner safety Card / `ShieldCheck` / `safetyTitle` on `app/hermes/page.tsx` | removed |
| Global `SafetyStrip` attrs (`role="status"`, `data-global-safety-strip`, `data-testid="global-safety-strip"`) | present |
| Shell always mounts `ComposerDock` with `disabled` + `allowSubmit={false}` | present |
| CSS contracts (`.app-touch-target`, `:focus-visible`, reduced-motion, hermes tokens) | present |

---

## CRITICAL

_None._

- No `dangerouslySetInnerHTML`.
- No Server Actions / unvalidated mutations in hermes shell.
- No client-bundle secret env hooks under hermes production code.
- No conditional hooks, direct state mutation, or hooks outside components.

---

## HIGH

### [HIGH] Heading order inverted: capability notice `h2` before page `h1`

**File:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/hermes/shell/HermesCapabilityNotice.tsx:26`  
**Related:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/hermes/shell/HermesWorkbenchShell.tsx:35-36`  
**Related:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/app/hermes/page.tsx:111`

**Issue:** `HermesCapabilityNotice` renders an `<h2>` above `{children}`, while the page’s only workbench title is an `<h1>` inside those children. Document order is therefore `h2` → (later) `h1`.

```tsx
// HermesWorkbenchShell
<HermesCapabilityNotice ... />  // h2 first
{children}                      // page h1 later

// HermesCapabilityNotice
<h2 className="font-body-md font-semibold text-text-primary">{copy.title}</h2>

// app/hermes/page.tsx
<h1 className="font-headline-lg text-text-primary">{text.title}</h1>
```

**Why:** Assistive tech and outline navigation assume headings introduce nested sections under a prior higher-level heading. An `h2` before any `h1` breaks the page outline and fails the Task 4 a11y bar (heading-order gate in this review lane). On mobile column layout the candidates rail also surfaces a `SectionTitle` `<h2>` before the page `<h1>`, compounding the same outline problem on this route.

**Fix:** Demote the capability title to a non-heading element (e.g. `<p className="font-body-md font-semibold ...">` or `<div role="presentation">` with the same styles) and keep the section labeled via visible text only—or move a single page-level `<h1>` into the shell above the notice and demote the page title. Prefer not using `h2` for chrome notices that precede the primary page title. Optionally restructure the Today page so the workbench `<h1>` precedes any `SectionTitle` `h2` (rail after main, or change `SectionTitle` level on this surface).

---

## MEDIUM

### [MEDIUM] Unavailable Conversation control exposes reason only via `title`

**File:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/hermes/shell/HermesInternalNav.tsx:76-82`

**Issue:** Conversation is correctly non-navigable (`<span aria-disabled="true">`), but the unavailable reason lives only in `title={entry.unavailableLabel}`.

```tsx
<span
  aria-disabled="true"
  className="app-touch-target ..."
  title={entry.unavailableLabel}
>
  {entry.label}
</span>
```

**Why:** `title` tooltips are not reliably announced by screen readers; `aria-disabled` on a non-interactive span also does little. Keyboard and AT users may see “对话 / Conversation” without learning it is closed for this delivery.

**Fix:** Prefer a disabled `<button type="button" disabled>` or keep the span and set  
`aria-label={`${entry.label}. ${entry.unavailableLabel}`}`  
(and drop redundant `aria-disabled` if the control is not focusable). Keep it out of the tab order.

---

### [MEDIUM] Second live region inside Hermes (`ComposerDock` `role="status"`)

**File:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/hermes/ComposerDock.tsx:74-77`  
**Related:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/SafetyStrip.tsx:48`

**Issue:** Global safety strip is correctly the unique paper/live banner (`role="status"` + `data-global-safety-strip`). `ComposerDock` still mounts a second `role="status"` for the unavailable hint whenever submit is locked (always, in F2).

```tsx
{!submitEnabled ? (
  <p className="font-body-sm text-text-secondary" role="status">
    {unavailableHint}
  </p>
) : null}
```

**Why:** Task brief: do not add a second live announcement inside Hermes; keep the global safety banner structurally unique. Multiple polite live regions compete on load. E2E only asserts uniqueness of the “仅模拟” safety copy, so this slipped past tests.

**Fix:** Render the unavailable hint as static helper text (`<p>` without `role="status"`), or use `aria-describedby` on the textarea pointing at a non-live description id. Reserve `role="status"` for the global `SafetyStrip`.

---

### [MEDIUM] Composer keeps editable draft state while permanently disabled from shell

**File:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/hermes/ComposerDock.tsx:37-63`  
**Related:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/hermes/shell/HermesWorkbenchShell.tsx:41-48`

**Issue:** Shell correctly forces `disabled` + `allowSubmit={false}` with `submitEnabled = !disabled && allowSubmit` and `preventDefault` on submit. The dock still allocates `useState("")` draft state and an `onChange` handler behind `disabled`/`readOnly`.

**Why:** Not a safety hole (native `disabled` blocks input), but dead client state in a read-only delivery invites later accidental unlock paths and adds an unnecessary client boundary cost for a non-interactive control.

**Fix:** Acceptable to leave for a later write-enabled slice; if keeping the visual affordance only, consider omitting draft state until `!disabled` (or a single controlled `value=""` with no setter while disabled).

---

### [MEDIUM] Internal nav links to routes with no App Router pages yet

**File:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/components/hermes/shell/HermesInternalNav.tsx:47-63`  
**Related:** `/Users/sunyibo/programs/ai-quant-platform/src/frontend/lib/hermes/routes.ts` (`/hermes/tasks|approvals|results`)

**Issue:** Nav exposes real `<Link>`s to `/hermes/tasks`, `/hermes/approvals`, and `/hermes/results`, but only `app/hermes/page.tsx` exists under `app/hermes/` today.

**Why:** Expected by Task 6 sequencing, but today those controls are keyboard-reachable links that 404. Slightly worse than the Conversation “unavailable” treatment for routes that are not ready.

**Fix (when not blocking Task 4):** Either ship Task 6 stubs immediately after shell, or temporarily mark Tasks/Approvals/Results the same way as Conversation until pages land. Out of Task 4 write-path scope; track for Task 6.

---

## What looks solid (no action)

1. **Single safety strip:** Inner warning `Card` / `ShieldCheck` / safety copy removed from `app/hermes/page.tsx`; Sidebar paper-only footer removed; global `SafetyStrip` is the sole structural safety banner.
2. **RSC boundary:** `app/hermes/layout.tsx` and `HermesWorkbenchShell` stay Server Components; only pathname nav + composer are `"use client"`. No server-only/DB imports in client leaves. Static `deliveryState="blocked_in_this_slice"` — no live capability probe props.
3. **Composer safety contract:** `submitEnabled = !disabled && allowSubmit`; shell hard-codes both off; form always `preventDefault`; no network APIs under `components/hermes` / `app/hermes`.
4. **Hooks:** `TopBar` menu Escape listener cleans up; no conditional hooks; dep arrays clean under project lint.
5. **Touch / focus / motion contracts:** Production `.app-touch-target`, global `:focus-visible`, and `prefers-reduced-motion` rules match the brief; TopBar / LocaleToggle / Sidebar / Hermes controls use the shared class rather than sub-44px fixed boxes.
6. **Internal nav semantics:** Landmark `aria-label`, `aria-current="page"` on active links, Conversation not a live chat entry point.
7. **Scroll region:** Single `data-page-scroll-region` on the shell content scroller as specified.
8. **eslint-plugin-react-hooks:** Present via `eslint-config-next`; lint clean on the Task 4 tree.

---

## Approval checklist (React lane)

| Criterion | Status |
|---|---|
| No CRITICAL React security issues | pass |
| No CRITICAL hook-rules violations | pass |
| No HIGH issues | **fail** — heading order |
| MEDIUM only would be Warning | n/a (HIGH present) |
| Task 4 product contracts (safety uniqueness, disabled composer, static delivery) | pass |

## Recommended fix order

1. **Required for Approve:** Fix capability-notice heading level / page outline (`HermesCapabilityNotice` + optional page rail order).
2. **Should fix in same slice or immediate follow-up:** Conversation unavailable naming for AT; drop Composer `role="status"`.
3. **Track:** Task 6 pages or unavailable treatment for Tasks/Approvals/Results links.

## Final call

**Needs fixes** — re-review after the HIGH heading-order change; expected to Approve once the outline is corrected and (ideally) the two MEDIUM a11y nits above are cleaned up.
