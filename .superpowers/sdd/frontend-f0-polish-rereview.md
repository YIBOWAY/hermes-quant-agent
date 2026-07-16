# Hermes F0 direction-a — grid re-review (post `67ed590`)

**Date:** 2026-07-13  
**Scope:** Desktop three-column placement only (prior ship-blocker).  
**Artifacts:**  
- `ai-quant-platform/docs/design/hermes-workbench/f0/direction-a.html`  
- `ai-quant-platform/docs/design/hermes-workbench/f0/shared.css`  
- Commit: `67ed590` `fix(frontend): correct F0 direction-a desktop grid and craft nits`

**Method:** Static CSS audit + headless Chrome CDP `getBoundingClientRect` at 1440×900 and 1280×900.

---

## Verdict

# **Ship to F1**

Desktop grid inversion is fixed. Main owns the `1fr` track; secondary is the quiet 288px rail. Residual craft nits from the prior critique (degraded pill semantics, mono KPI status) are also present in `67ed590` and do not re-block.

---

## Layout measurements (CDP)

| Viewport | `grid-template-columns` | nav | main | secondary | main > secondary |
| --- | --- | ---: | ---: | ---: | --- |
| **1440×900** | `228px 924px 288px` | x0 **w228** col1 | x228 **w924** col2 | x1152 **w288** col3 | **yes** |
| **1280×900** | `228px 764px 288px` | x0 **w228** col1 | x228 **w764** col2 | x992 **w288** col3 | **yes** |

Acceptance from prior critique:

- 1440 main ~924 → **pass** (exact **924**)
- 1280 main still larger than secondary → **pass** (764 > 288)
- KPI `completed_degraded` not glyph-stacked → **pass** (mono chip, ~1 line at both widths)

Placement:

```css
.nav-rail        { grid-column: 1; grid-row: 1 / -1; }
.main-col        { grid-column: 2; grid-row: 1 / -1; }
.secondary-panel { grid-column: 3; grid-row: 1 / -1; }
```

Root cause of the prior inversion (definite-row items auto-placed before fully auto `main-col`) is closed by explicit columns.

---

## Gate status vs prior critique

| Prior item | Status |
| --- | --- |
| CRITICAL desktop column inversion | **Resolved** |
| H1 brand pill on degraded status | **Resolved** (`pill-warn`) |
| H2 mono machine KPI value | **Resolved** (`.kpi .v.mono`) |
| warn KPI inset 2px left rail | **Resolved** (removed) |

Non-blocking residuals (spacing one-offs, etc.) may ride into F1 craft polish; they are not F0 ship blockers.

---

## Recommendation

Promote **direction-a** F0 polish through the F1 implementation gate. No further grid re-pass required unless subsequent commits reopen `grid-column` / `grid-template-columns` on `.proto-a`.
