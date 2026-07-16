# Hermes F0 A + F1 density craft pass — report

**Date:** 2026-07-13  
**Commit (platform):** `docs(frontend): densify Hermes finance desk cards and composer dock`  
**Scope:** F0 `direction-a.html` + `shared.css`; F1 `prototype.css` + `prototype.html` renderHome. No push. Unrelated dirty (`earnings_calendar.csv`, `.understand-anything/`) preserved.

## Problem

After the finance-crypto redesign, stage **width** was fixed (≥1384 usable @1440) but the critic residual was **vertical sparseness**: two-up cards ~686×142 with little internal structure, marketing-scale lede, large empty canvas under the stack, and composer often below the fold @900.

## Changes

1. **Vertical rhythm** — ops-header / KPI strip / content / desk gaps tightened (e.g. KPI pad 10×12, min-height 68; content pad 10–12; desk/two-up gap 8).
2. **Two-up density** — desktop min-height **168px**; added exchange-style **`.meta-grid`** second rows (job / last_ok / schedule · run / window / limit) in F0 HTML and F1 home render; card type 13/12px with tighter line-height.
3. **Attention / KPI** — denser padding and mono blocks; KPI values 18px (mono 13); labels 10px uppercase.
4. **Lede** — marketing clamp ~1.375–1.75rem → desk **clamp(1.125rem … 1.375rem)**; F1 `.lede-en` margin/size reduced.
5. **Composer dock** — `position: sticky; bottom: 0; z-index: 8` with compact chrome (textarea min 48px) so the honest disabled dock stays visible while scrolling.
6. **Preserved** — Binance canvas `#0b0e11`, amber CTAs, no purple atmosphere, full-width stage geometry, Gate/product copy facts.

## Files

| File | Role |
| --- | --- |
| `docs/design/hermes-workbench/f0/shared.css` | Shared lede/card/meta-grid/composer tokens |
| `docs/design/hermes-workbench/f0/direction-a.html` | Idle densify + sticky dock + meta rows |
| `docs/design/hermes-workbench/f1/prototype.css` | F1 parity densify + sticky dock |
| `docs/design/hermes-workbench/f1/prototype.html` | Home two-up meta-grid render |

## Preview

```
http://localhost:4173/f0/direction-a.html
http://localhost:4173/f1/prototype.html
```

## Expected look check

Desk should read closer to exchange ops: packed KPI + attention + filled two-up, smaller title, composer dock sticky at bottom; still finance DNA (amber, Binance surfaces), still full-width stage.
