# Hermes F0/F1 finance-crypto redesign — independent craft critique

**Date:** 2026-07-13  
**Reviewer role:** Independent craft critique (not implementer self-check)  
**Recipe:** `.superpowers/sdd/frontend-hermes-coo-token-recipe.md`  
**Brief:** `.superpowers/sdd/frontend-f0-finance-redesign-brief.md`  
**Implementer report:** `.superpowers/sdd/frontend-f0-finance-redesign-report.md`  

**Artifacts reviewed**
- `ai-quant-platform/docs/design/hermes-workbench/f0/direction-a.html`
- `ai-quant-platform/docs/design/hermes-workbench/f0/shared.css`
- `ai-quant-platform/docs/design/hermes-workbench/f1/prototype.html`
- `ai-quant-platform/docs/design/hermes-workbench/f1/prototype.css`

**Method:** Static token/HTML audit + headless Chrome CDP (`--remote-debugging-port`, device metrics) at **1440×900**, **1280×800**, **390×844**. Screenshots + `getBoundingClientRect` under `/tmp/hermes-finance-critique/`.

---

## Verdict

# **Ready for user look**

Hard gates from the user rejection + brief are met:

| Hard gate | Result |
| --- | --- |
| Purple AI atmosphere gone | **Pass** — only flat brand glyph |
| Main stage ≥ 1100px usable @1440 | **Pass** — attention **1384px** |
| No permanent 288px right rail | **Pass** — rail `absent` / `display:none` |
| Full-width trading-desk shell | **Pass** — horizontal top nav, no mid squeeze |
| F1 visual parity with F0 A | **Pass** — same DNA, same stage geometry |

This is **not** a product/F2 approval. F1 remains draft. Residual craft notes below are **optional density polish**, not ship-blockers for a user taste check. If the user still says “thin” or “AI 味”, the next pass targets are listed at the end — do not invent a new redesign until that feedback lands.

---

## Scorecard (binding questions)

| # | Question | Score | Evidence |
| --- | ---: | --- | --- |
| 1 | Purple AI atmosphere gone? | **4.5 / 5** | CDP purpleHits = brand-mark only (`rgb(144,133,233)`). Top bar `background-image: none`. Glass count 0. No radial haze on header. Selected nav is amber soft, not lavender. |
| 2 | Main stage wide enough (≥1100 @1440)? | **5 / 5** | F0/F1 stage **1440**; attention/content usable **1384** (pad 28px×2). ~96% of viewport. |
| 3 | Middle still feels thin? | **3.5 / 5** | **Width thinness is fixed.** Residual “thin” is *vertical / content density*: two-up cards ~142px tall with sparse copy; large empty black field; composer often below fold @900. Not the old 288px tube. |
| 4 | Trading desk vs AI SaaS? | **4 / 5** | Reads exchange-adjacent (Binance canvas, amber money CTAs, mono IDs, KPI strip, sys chips). Still some ops-dashboard residue (marketing-scale lede, soft empty cards, “Research COO” SaaS subtitle). Not Linear-lavender AI product. |
| 5 | F1 matches F0? | **4.5 / 5** | Same tokens, top bar, KPI/attention/two-up/watch geometry (±1–2px). F1 review chrome is taller (expected). Minor content label diffs (EN lede line, badge counts from state JSON). |

**Overall craft vs brief:** **4.1 / 5** — ready for human taste gate.

---

## CDP geometry (independent re-measure)

Server: `http://127.0.0.1:4173` (hermes-workbench static).

### F0 `direction-a` idle

| Viewport | Stage w | Attention w | Two-up w | Rail | Overflow-x | Header purple radial |
| --- | ---: | ---: | ---: | --- | --- | --- |
| 1440×900 | **1440** | **1384** | 1384 | absent | none | none |
| 1280×800 | **1280** | **1232** | 1232 | absent | none | none |
| 390×844 | 390 | 358 | 358 | absent | none | none |

### F1 `prototype` home (normal)

| Viewport | Stage w | Attention w | Two-up w | Rail | Overflow-x | Header purple radial |
| --- | ---: | ---: | ---: | --- | --- | --- |
| 1440×900 | **1440** | **1384** | 1384 | absent | none | none |
| 1280×800 | **1280** | **1232** | 1232 | absent | none | none |
| 390×844 | 390 | 358 | 358 | absent | none | none |

### Token / atmosphere probes (F0 & F1 @1440)

| Probe | Observed |
| --- | --- |
| `body` canvas | `rgb(11, 14, 17)` = `#0b0e11` ✓ |
| `--accent` | `#f0b90b` ✓ |
| `--hermes` | `#9085e9` — solid only on `.brand-mark` ✓ |
| Brand box-shadow | `none` ✓ |
| Top bar bg image | `none` ✓ |
| Glass / backdrop-filter | 0 ✓ |
| Purple solid elements | 1 → `DIV.brand-mark` only ✓ |
| Gradients in computed styles | 0 on product chrome ✓ |

**vs previous polish critique:** old desktop grid inversion (main crushed to **288px**, secondary stole `1fr`) is **gone**. That was the ship-blocker; this redesign actually fixed it.

---

## What works (keep)

1. **Shell rewrite is real, not cosmetic.** Safety → top bar (brand | horizontal 今日/任务/审批/结果 | sys chips) → full-width stage → composer dock. No `nav | main | 288` squeeze.
2. **Attention is full stage width** with amber left edge — exchange alert language, not half-column AI card.
3. **Amber money CTAs** on primary actions; Coinbase blue reserved (not wallpaper); Hermes purple constrained to glyph.
4. **KPI strip** (3 equal cells) scans like a desk header strip; warn KPI left-rail amber is intentional and readable.
5. **值守 as bottom strip** (4 cells) — does not steal mid-width.
6. **Product facts preserved:** safety copy, candidate id, automation 3/4 + stale, `completed_degraded`, honest disabled composer (content audit; composer below fold at 900 but present in DOM).
7. **F1 home surface** is recognizably the same desk as F0 A — walkthrough chrome is clearly *outside* the product.

---

## Residual craft notes (non-blocking for user look)

### R1 — “Thin” may reappear as *density*, not width
Two-up cards measure ~**686×142** @1440 with little internal structure. Watch items are quiet 69px chips. After fixing the skinny tube, the desk can still feel **under-filled** — more “sparse SaaS dashboard” than Binance/Kraken data density.

**If user still says 中间细/空:**  
- Raise two-up min-height or add a second data row (last run, next due, digest short).  
- Consider 4 KPI cells or denser mono metadata under KPI values.  
- Tighten vertical rhythm (ops-header + kpi + content gaps) so composer docks in first screen @1440×900.

### R2 — Mild ops-SaaS residue (not purple AI)
- Lede is still product-marketing scale (`clamp` ~1.375–1.75rem) rather than desk ticker density.  
- Subtitle “Research COO” reads startup chrome more than exchange.  
- Large empty `#0b0e11` field under the stack is honest but not “busy desk.”

These are **taste**, not gate failures. Do not reintroduce purple to “add identity.”

### R3 — Token landmines still in `:root`
`--hermes-soft / -mid / -border / -text` remain defined in `shared.css` and F1 `prototype.css` but are **unused** on A/F1 product chrome (CDP confirms). Safe today; easy to re-abuse later.

`--approval` coral is defined on F0 shared and **unused** — gates use amber (`btn-warn` / `pill-warn`) instead. Recipe allows coral for human-approve only; optional future Gate-2 accent, not required for this look.

### R4 — F1 review chrome height
@1440 product stage starts ~**y=314** (walkthrough + surface + state + safety). F0 product starts ~**y=158**. Geometry inside the product matches; first impression of F1 is “prototype cockpit,” which is correct for draft review but makes the desk feel smaller on one screen.

### R5 — B/C comparison stems (out of A/F1 scope)
`direction-b.html` / `direction-c.html` still use hermes gradients / purple rails against the new shared tokens. They are comparison artifacts; do not show them as the v3 finance desk.

### R6 — Composer below fold @900
Idle stack (header + KPI + attention + two-up + 值守) pushes composer off the first screen. Acceptable for scrollable desk; if user wants “honest disabled composer always visible,” sticky composer dock is the fix — not a width fix.

---

## Anti-pattern kill list (brief) — audit

| Kill target | F0 A | F1 |
| --- | --- | --- |
| Purple ambient glow / radial hermes haze | Dead | Dead |
| Lavender selected nav as identity | Dead (amber selected) | Dead |
| AI mesh / glass / emoji | Dead | Dead |
| Three-column squeeze + 288 rail | Dead | Dead |
| Thin card column mid tube | Dead (width) | Dead (width) |
| Brand-mark glow shadow | Dead (`box-shadow: none`) | Dead |

---

## F0 ↔ F1 parity detail

| Surface | Match? | Notes |
| --- | --- | --- |
| Canvas / surface / line tokens | Yes | Duplicate ladders, same hex |
| Top bar structure | Yes | Brand mark + nav + chips |
| KPI / attention / two-up / watch | Yes | Same grid math |
| Amber CTA + warn edges | Yes | |
| Purple only on glyph | Yes | |
| Review chrome | F1 only | Intentional |
| Content labels | Minor diffs | F1 EN lede; badge from live state |

---

## Recommendation

1. **Show the user F0 A @1440 and 1280 first** (`direction-a.html`), then F1 home if F0 taste lands.  
2. Ask explicitly against the two prior complaints:  
   - “还有 AI 味吗？”  
   - “中间还窄/细吗？”  
3. Only if either returns no: do a **density pass** (R1/R2/R6) — not another full DNA redesign.  
4. Do **not** start F2 / production shell until F1 written approval (README already fail-closed).

---

## Preview

```
http://localhost:4173/f0/direction-a.html
http://localhost:4173/f1/prototype.html
```

CDP dumps: `/tmp/hermes-finance-critique/metrics.json` + `f0_*.png` / `f1_*.png`.

---

## Bottom line

The v3 redesign **answered the rejection**: purple atmosphere is gone, the mid-stage is wide (≥1100), F1 tracks F0, and the shell reads much closer to a finance/crypto desk than a lavender AI SaaS. Residual risk is **taste on density** (sparse cards / below-fold composer), not geometry failure.

**Verdict: Ready for user look.**
