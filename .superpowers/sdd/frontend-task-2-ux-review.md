# Hermes F1 UX Independent Review

**Reviewer:** frontend/UX (react-reviewer lane — independent of implementer)  
**Date:** 2026-07-13  
**Scope:** `ai-quant-platform/docs/design/hermes-workbench/f1/`  
  - `prototype.html`  
  - `prototype.css`  
  - `states/{home,conversation,tasks,approvals,results}.json`  
**Brief:** `.superpowers/sdd/frontend-task-2-brief.md`  
**Report claim:** `.superpowers/sdd/frontend-task-2-report.md`  
**Method:** Full artifact read + headless Chrome CDP at 1440×900, 1280×800, 768×1024, 390×844 (plus edge 1279 / 767); click full 7-step walkthrough and `下一步` cycle; visit all 34 catalog states; modal open/Escape/close focus restore; overflow / 44px / reduced-motion / network / console probes; craft token compare vs F0 `direction-a`.

**F1 decision:** **Not made.** This review does **not** approve F1 for the user. Written user approval is still required before F2 / any `src/frontend/app` work.

---

## F1 review

- Full lifecycle: **pass**
- State catalog: **pass**
- 1440/1280/768/390: **pass**
- Keyboard-only: **pass**
- Reduced motion: **pass**
- Horizontal overflow: **none**
- Console errors/warnings: **0 product script errors / 0 warnings** (browser favicon 404 only: 1 network 404 + 1 resource error)
- Visual craft vs F0 A: **pass** (token-matched premium dark COO craft)

**Verdict: Ready for user approval**

Caveats the user should weigh (none hard-fail the F1 gate):

1. **Review chrome density @390** — Walkthrough + Surface + State toolbars are intentionally dense for design review; must not ship as production TopBar (implementer already noted).
2. **Mobile section `order` classes are partially structural** — `.mobile-order-*` sit inside `#view-root`, not as flex children of `.main-col`. Practical order still matches status → conversation → plan → composer via DOM order + `composer-dock { order: 5 }`; CSS `order` on nested blocks is mostly inert. Acceptable for prototype; tighten in F2.
3. **Modal is focus-restore, not full focus-trap** — Escape / 关闭 / backdrop restore trigger focus; Tab is not contained. Fine for local prototype; production dialog needs trap/`inert`.
4. **Favicon 404** — static server only; not product script. Optional silent fix later.
5. **Gate 1/2/3 actions are demonstration-only** — Approve/submit remain disabled; CAS fields are display-only and never auto-filled for approval. Correct for F1 safety.

---

## Assessment

### Ready for user approval

The package delivers a keyboard-operable local COO desk that:

- Loads **only** `fetch("./states/*.json")` + HTML/CSS (network capture: prototype.html/css + five catalogs + browser favicon).
- Walks the exact research lifecycle:
  `提出目标 → 结构化计划 → Gate 1 → streaming → completed_degraded → Gate 2 → Gate 3`
- Exposes the exact state ID matrix from the brief (5+9+9+6+5).
- Keeps a visible **prototype data** badge outside product chrome.
- Disables composer send; no form submit; CAS approve buttons disabled.
- Uses real breakpoints (not whole-UI `transform: scale`), `prefers-reduced-motion` kill-switch, single safety strip, and F0-A visual DNA (`#010102` canvas, Hermes `#9085E9`, safety amber strip).

No CRITICAL/HIGH UX gate failures found under the F1 brief.

---

## Scorecard

| Criterion | Result | Evidence |
| --- | --- | --- |
| Full lifecycle walkthrough | **Pass** | Steps 0–6 land home/empty → conversation/streaming+plan → tasks/waiting_gate+Gate1 → conversation/streaming+events → results/partial (`completed_degraded`) → approvals/available (Gate2 CAS fields) → approvals/approved Gate3 four-field payload |
| `下一步` cycle | **Pass** | Advances 1→…→7 then restarts to step 1/goal |
| State catalog IDs | **Pass** | Exact brief IDs; each state has zh title + en title + non-color `status_text` + `long_error` |
| Local-only data | **Pass** | Network = html/css + 5 JSON; composer disabled; submit/approve disabled |
| prototype data label | **Pass** | `#proto-data-label` in `.review-chrome` outside `.prototype` |
| Viewport 1440 | **Pass** | nav flex + secondary block; overflow none on all walk steps + long states |
| Viewport 1280 | **Pass** | no overflow; secondary still visible at 1280 (collapses at `max-width: 1279` — confirmed side=`none` at 1279) |
| Viewport 768 | **Pass** | secondary hidden; honest stack; overflow none |
| Viewport 390 | **Pass** | nav hidden, mobile tabs flex; overflow none; safety wraps (not ellipsis-truncated) |
| Keyboard / aria-pressed | **Pass** | Surface + State buttons `aria-pressed`; walk `aria-current="step"`; native `<button>`s |
| Modal focus restore | **Pass** | Open focuses `#modal-dialog`; Escape + 关闭 restore trigger; approve stays disabled |
| aria-live | **Pass** | Single `#live-region` `aria-live="polite"`; walk announcements observed |
| Reduced motion | **Pass** | Under `prefers-reduced-motion: reduce`, transitions/animations forced to `0s` / `none` |
| Horizontal overflow | **none** | `scrollWidth <= innerWidth` at all four required widths × walk steps × surface extremes |
| 44px targets | **Pass** | 0 sub-44 visible interactive targets measured |
| Safety uniqueness | **Pass** | Exactly one body match for `实盘交易已禁用`; strip `role="status"` |
| Streaming event labels | **Pass** | `run.started`, `plan.drafted`, `tool.factor_probe`, `stream.delta` |
| Gate 2 exact summary | **Pass** | Candidate ID / expected status / manifest digest / integrity; approve disabled |
| Gate 3 scoped diff | **Pass** | `promotion_id` + worktree + patch/diff + manifest; submit disabled; “never commits” copy |
| Craft vs F0 A | **Pass** | Matching bg / text / Hermes / safety tokens; radial header wash; 12px cards; system font stack |
| Console | **0/0 product** | Exceptions []; warnings []; only favicon 404 noise |

---

## Lifecycle detail (CDP)

| Step | Walk meta | Surface / state | Content check |
| --- | --- | --- | --- |
| 1 提出目标 | `step 1/7 · goal` | Home / `empty` | Empty desk + start goal CTA path |
| 2 结构化计划 | `step 2/7 · plan` | Conversation / `streaming` + plan mode | Structured plan card + plan_hash |
| 3 Gate 1 | `step 3/7 · gate1` | Tasks / `waiting_gate` | Gate 1 formula/plan confirmation hero |
| 4 Streaming | `step 4/7 · streaming` | Conversation / `streaming` | Real event labels list |
| 5 completed_degraded | `step 5/7 · completed_degraded` | Results / `partial` | Status text includes `completed_degraded`; non-trading eligibility copy |
| 6 Gate 2 | `step 6/7 · gate2` | Approvals / `available` | Exact manifest field grid + view-summary modal |
| 7 Gate 3 | `step 7/7 · gate3` | Approvals / `approved` + gate3 mode | Scoped diff / four-field promote payload |

Live announcements (sample):  
`Walkthrough：提出研究目标。` … `Walkthrough：Gate 3 范围 diff 摘要。`

---

## State catalog detail

| Surface | IDs (exact) | Count | Matrix render |
| --- | --- | --- | --- |
| home | empty/loading/normal/degraded/hermes_offline | 5 | Pass |
| conversation | sending/queued/streaming/reconnecting/stopping/reconciling/failed/quota/fallback | 9 | Pass |
| tasks | queued/running/waiting_gate/stop_requested/reconciling/completed/partial/failed/stopped | 9 | Pass |
| approvals | available/approved/rejected/expired/stale/digest_mismatch | 6 | Pass |
| results | loading/partial/no_data/audit_warning/source_missing | 5 | Pass |

Each visited state exposed bilingual titles, non-color status text (e.g. `partial · completed_degraded · 结果可阅读但不授予交易资格`), and a long error string. Schema root shape matches brief (`schema_version`, `surface`, `default_state`, `states[]`).

---

## Viewport / motion / overflow

| Width | Nav | Secondary | Mobile tabs | Overflow | Sub-44 targets |
| --- | --- | --- | --- | --- | --- |
| 1440 | flex | block | none | none | 0 |
| 1280 | flex | block | none | none | 0 |
| 1279 (edge) | flex | **none** | none | none | — |
| 768 | flex | none | none | none | 0 |
| 767 (edge) | **none** | none | **flex** | none | — |
| 390 | none | none | flex | none | 0 |

`prefers-reduced-motion: reduce` → test element `transition-duration: 0s`, `animation-name: none`.

Long IDs (`factor-momentum_20d_reversal-…`, 64-char digest) wrap via `overflow-wrap: anywhere` / `word-break: break-all`; no horizontal blowout.

---

## Keyboard / a11y (F1 bar)

| Check | Result |
| --- | --- |
| State buttons `aria-pressed` | Pass (dynamic toolbar rebuilt per surface) |
| Surface buttons `aria-pressed` | Pass |
| Walkthrough `aria-current="step"` | Pass |
| One `aria-live="polite"` region | Pass |
| Modal focus move + restore | Pass (dialog focus; Escape + close restore trigger) |
| Approve disabled in modal | Pass |
| Composer non-submitting | Pass (textarea + 发送 disabled) |
| Focus-visible outline | Present (`:focus-visible` Hermes ring) |
| Full modal focus trap | Not required for F1; note for F2 |
| Toolbar arrow-key pattern | Not implemented on `role="toolbar"`; mouse/Tab sufficient for prototype |

---

## Visual craft vs F0 direction-A

| Token / cue | F0 A | F1 | Match |
| --- | --- | --- | --- |
| Canvas bg | `rgb(1,1,2)` | `rgb(1,1,2)` | Yes |
| Text | `rgb(247,248,248)` | same | Yes |
| Hermes mark | `rgb(144,133,233)` | same | Yes |
| Safety strip | amber on dark `#12100a` | same | Yes |
| Header treatment | premium radial wash | present | Yes |
| Card radius / hairline | polished dark cards | 12px + `#23252a` line | Yes |
| Hierarchy | COO desk action/status first | KPI + attention + rail | Yes |

Craft is at F0-A polish level, not a pre-polish wireframe. Review chrome is visually separated (darker review band + dashed prototype badge) so it cannot be mistaken for a live Hermes session.

---

## Report claim audit

| Implementer claim | Independent finding |
| --- | --- |
| Full walkthrough 1–7 | Confirmed |
| Exact state IDs | Confirmed |
| Local fetch catalogs only | Confirmed (plus favicon browser request) |
| aria-live / aria-pressed / modal focus | Confirmed |
| Mobile order status→…→composer | Pass in practice; nested `order` classes weak (see caveats) |
| Real breakpoints / reduced motion | Confirmed |
| Overflow none @ four widths | Confirmed |
| Console: no product script errors | Confirmed |
| F1 not approved / no production shell touch | Honored in package; this review also does not approve |

---

## Non-blocking follow-ups (optional before or during F2)

1. Make `#view-root` a column flex container (or hoist section shells) so `.mobile-order-*` orders are real, not documentation-only.  
2. Add dialog focus trap + initial focus on first actionable control for production.  
3. Silence favicon 404 on the static design server.  
4. Keep review chrome out of any production TopBar composition.  
5. Consider slightly collapsing walkthrough chip labels on 390 for reviewer comfort (not a product requirement).

---

## Hard stops still in force

- **Do not** record F1 approval in `docs/design/hermes-workbench/README.md` until the user writes explicit approval.  
- **Do not** run the approval commit message until that written approval exists.  
- **Do not** create anything under `src/frontend/app`, `components`, or `lib` from this package yet.

---

## How re-verified

```bash
cd /Users/sunyibo/programs/ai-quant-platform
python3 -m http.server 4173 --directory docs/design/hermes-workbench
# http://127.0.0.1:4173/f1/prototype.html
# Headless Chrome CDP @ 1440 / 1280 / 768 / 390 (+ 1279 / 767 edges)
```

**Outcome:** **Ready for user approval** — independent F1 pass table above.  
**Not approved.** User gate remains open.
