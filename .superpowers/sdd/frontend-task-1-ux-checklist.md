# Hermes F0 UX Evaluation Checklist (Read-Only)

**Scope:** F0 high-fidelity directions only (`docs/design/hermes-workbench/f0/`).  
**Goal (D-31):** `/hermes` as default home; read-only shell; honest disabled chat; one safety strip; action / exceptions / current work / recent results clear within 5 seconds.  
**Use:** Independent pass/fail critique of Directions A/B/C. Mark each item `Pass` / `Fail` / `N/A` with a one-line note. Do not score content differences that the brief fixed as identical.

---

## How to evaluate

1. Serve the three directions at full size (no transform scale of the whole UI).
2. For each direction, inspect **idle Today**, then toggle **active / approval / result** states.
3. At each of the four viewports, re-run the 5-second scan and overflow checks.
4. Fail any direction that cannot answer the five-second questions without scrolling the safety strip or hunting duplicate status chrome.

**Viewports (required):** 1440×900 · 1280×800 · 768×1024 · 390×844

---

## 1. Hierarchy

| # | Criterion | Pass if… |
|---|-----------|----------|
| H1 | Primary attention first | The strongest visual weight is the human action (e.g. pending research approval), not decoration, chrome, or healthy automation. |
| H2 | Secondary = exceptions | Failures, staleness, degraded, quota/fallback sit below action but above routine success. |
| H3 | Tertiary = current work + recent results | “What is running / last meaningful outcome” is visible without opening technical detail. |
| H4 | Compression of normal automation | Healthy automation is **one row / one summary**, never four equal status cards. |
| H5 | Technical detail collapsed | cron, run IDs, paths, raw errors live under `<details>` or equivalent; not competing with the headline. |
| H6 | Direction identity without IA drift | A = action/status-first; B = change/progress-first; C = conversation/result-first **while idle still answers safety/action/current-work/recent-result**. |

---

## 2. Five-second scan

From a cold load of **idle Today**, without clicking, the reviewer can answer:

| # | Question | Pass if… |
|---|----------|----------|
| S1 | Am I safe? | Paper/sim, live disabled, kill switch, API status are immediately legible. |
| S2 | What needs me? | The pending approval (or clear “nothing needs you”) is obvious. |
| S3 | What is wrong? | Exceptions (e.g. overdue weekly_review) surface without expanding technical detail. |
| S4 | What is current work? | At least one line conveys ongoing/normal research state. |
| S5 | What just finished? | Recent result (title + status, e.g. `completed_degraded`) is scannable. |

**Fail** if any of S1–S5 requires opening a panel, scrolling past a full viewport of chrome, or decoding color alone.

---

## 3. Safety uniqueness

| # | Criterion | Pass if… |
|---|-----------|----------|
| U1 | Single SafetyStrip | Only the global top strip shows paper / live / kill / API. |
| U2 | No content duplicates | No in-body safety card, sidebar paper-only footer, or second kill/API banner. |
| U3 | Status landmark | Strip is a clear status region (`role="status"` or equivalent landmark treatment). |
| U4 | Not mixed with tasks | Safety copy is never nested inside automation, approval, or result cards. |

---

## 4. Long Chinese + long IDs

Use the brief’s fixed copy, including long Chinese headlines and IDs such as `factor-momentum_20d_reversal-323b045e4b` and run strings under technical detail.

| # | Criterion | Pass if… |
|---|-----------|----------|
| L1 | No truncation of meaning | Headlines and action titles remain readable; ellipsis only on secondary metadata, never on the sole action label. |
| L2 | Long IDs don’t blow layout | IDs wrap, break, or sit in mono blocks without horizontal page overflow. |
| L3 | Mixed zh/en rhythm | Chinese body + English/code tokens remain aligned and legible at all four widths. |
| L4 | Collapsed tech strings | Long cron/run/path lines stay inside collapsed detail and still wrap safely when opened. |

---

## 5. Four viewports (real widths, not scaled screenshots)

At **each** of 1440 / 1280 / 768 / 390:

| # | Criterion | Pass if… |
|---|-----------|----------|
| V1 | No horizontal overflow | `document.documentElement.scrollWidth <= window.innerWidth`. |
| V2 | No whole-UI scale | Layout reflows via breakpoints; not `transform: scale` on the prototype root. |
| V3 | Primary stack preserved | Action → exceptions → current work / recent results remain discoverable; secondary panels may hide, content must not. |
| V4 | Touch width (390) usable | Idle Today answers S1–S5 without multi-column squeeze or clipped CTAs. |
| V5 | Tablet (768) honesty | Hidden secondary chrome does not hide the only path to approval or recent result. |

---

## 6. Disabled composer honesty

| # | Criterion | Pass if… |
|---|-----------|----------|
| C1 | Visually disabled | Composer control and send affordance look non-interactive (not “loading” or “ready”). |
| C2 | Programmatically disabled | `disabled` (or equivalent) on input and send; no submit handler / no network path. |
| C3 | Honest reason | Copy states capability is not available yet (e.g. 真实 Hermes 写入能力尚未通过)—not a fake offline glitch, not “try again”. |
| C4 | No false affordance | Placeholder, focus, or hover does not imply chat will send. |
| C5 | Boundary clear in active states | Active/approval/result compositions still show the same honest disabled boundary. |

---

## 7. Reduced motion

| # | Criterion | Pass if… |
|---|-----------|----------|
| M1 | `prefers-reduced-motion: reduce` | Animations and transitions are disabled or instantaneous. |
| M2 | No motion-only meaning | State changes (approval, failure, degraded) remain understandable with motion off. |
| M3 | No scroll hijack | Toggles/state switches do not force scroll or parallax that fights the user. |

---

## 8. 44px targets

| # | Criterion | Pass if… |
|---|-----------|----------|
| T1 | Interactive minimum | Buttons, links, summary toggles, and other hit targets are ≥ **44×44 CSS px**. |
| T2 | Disabled controls included | Disabled send/composer chrome still meets target size (large enough to read and not mis-tap adjacent controls). |
| T3 | Spacing | Adjacent targets have enough separation that 390-width thumbs don’t activate the wrong control. |
| T4 | Focus visible | `:focus-visible` (or equivalent) is high-contrast and not clipped by overflow containers. |

---

## Direction scorecard (fill per review)

| Check group | Direction A (COO desk) | Direction B (timeline) | Direction C (split canvas) |
|-------------|------------------------|------------------------|----------------------------|
| Hierarchy | | | |
| 5-second scan | | | |
| Safety uniqueness | | | |
| Long Chinese + IDs | | | |
| 1440 | | | |
| 1280 | | | |
| 768 | | | |
| 390 | | | |
| Disabled composer | | | |
| Reduced motion | | | |
| 44px targets | | | |
| **Overall** | | | |

**Hard fails (any one blocks recommendation):** duplicate safety chrome; horizontal overflow at a required viewport; composer that looks or behaves submittable; idle view that cannot answer action/exceptions/current-work/recent-result in five seconds; interactive targets under 44px.

---

## Out of scope for F0 critique

- Production Next.js components, feature flags, or root redirect.
- Live Hermes, Gate 1/2/3 approval UI, chat submit, execution, or legacy page removal.
- Changing fixed fixture copy or inventing a selected direction before written user approval.
