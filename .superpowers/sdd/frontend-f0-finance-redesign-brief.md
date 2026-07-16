# Hermes F0/F1 visual redesign v3 — anti-AI-slop, finance/crypto DNA

## User feedback (binding)
1. Still too much **AI 味** — not approved.
2. **Middle layout bad**: feels too narrow/thin, visually uncomfortable.
3. Re-reference awesome-design-md with focus on **AI + finance + crypto** (not just Linear/Raycast purple).

## Keep
- Direction-A **COO hierarchy**: safety → attention/action → status → work → result → honest disabled composer
- Exact content facts (safety text, candidate id, automation, completed_degraded, disabled composer)
- Four view states, 44px targets, reduced motion, no CDN, no production React
- Hermetic static HTML/CSS/JS under `docs/design/hermes-workbench/`

## Kill (explicit anti-patterns)
- Purple ambient glow / radial hermes haze on headers
- Lavender-soft selected nav chrome as primary identity
- “AI product” mesh gradients, glass stacks, emoji icons
- Three-column layout that **squeezes the main desk** between nav + 288px rail
- Thin card columns that make the center feel anorexic
- Decorative brand-mark glow shadows

## Layout rewrite (required)
Abandon skinny `nav | main | secondary` COO clone.

Use a **trading-desk / exchange dashboard** shell (Binance / Kraken / Coinbase product density + Revolut black canvas):

```
┌─ Safety strip (full width) ─────────────────────────────┐
├─ Top bar: brand | horizontal nav (今日/任务/审批/结果) |  │
│           compact system chips (API OK · paper · kill)   │
├─ Full-width main stage (min ~960px free at 1440) ───────┤
│  KPI row 4 equal cells OR 3+1 spanning                  │
│  Attention (full width, not half-column)                │
│  Two comfortable cards: automation | recent result      │
│  Optional “值守” as bottom strip or drawer, NOT right    │
│  rail that steals mid-width                             │
├─ Composer dock full width ──────────────────────────────┤
```

Hard geometry targets at **1440×900**:
- Main stage content width **≥ 1100px** (or ≥ 76% of viewport)
- No fixed 288px permanent right rail on desktop
- Horizontal padding 24–32px; card max readable width OK, but stage is not a thin tube
- At 1280: still one strong main column (no crushed 288px middle)

## Visual DNA (synthesize — do not clone logos)

### Primary (finance/crypto dark product)
- **Binance**: canvas `#0b0e11`, surface `#1e2329` / `#2b3139`, hairline subtle, **amber-yellow** `#F0B90B` / `#FCD535` for primary money/attention CTAs only
- **Coinbase**: institutional calm; use **blue** `#0052FF` only for links/secondary actions, not wallpaper
- **Revolut**: pure black product chrome, dense cards, no purple haze
- **Kraken / exchange dashboards**: data-first density, tabular numbers, clear buy/sell-like status (adapt to risk/approval language)

### Secondary (AI that is NOT purple-slop)
- **xAI**: monochrome white-on-near-black, geometric restraint, warm accent only as thin edge
- **Claude**: warm coral/terracotta `#CC785C` as *human approval* accent alternative to purple
- **Ollama / OpenCode**: terminal honesty, mono for IDs, paper or ink — no fantasy gradients
- **ElevenLabs**: editorial restraint if any light surfaces appear

### Brand Hermes
- Logo wordmark “Hermes” may keep a small solid mark in **muted steel** or single flat `#9085E9` **only on brand glyph** — never as page atmosphere.
- Status colors: success green, warn amber (Binance yellow family), danger red — **brand ≠ status**.

## Type & density
- Prefer geometric system UI + tabular mono for prices/IDs/digests
- Titles: strong weight, little tracking drama (avoid “AI marketing” mega tracking)
- KPI values: tabular nums, 14–16px mono for machine strings; 20–24px for human counts
- Borders: 1px `#2b3139`-class; elevation almost flat (exchange UI, not glass SaaS)

## Files to rewrite
1. `f0/shared.css` — new token ladder (finance dark, not Linear lavender)
2. `f0/direction-a.html` — full shell + layout rewrite
3. `f1/prototype.css` + `f1/prototype.html` — **must match** new shell (no regression to old purple AI look)
4. Update `docs/design/hermes-workbench/README.md` status note: “v3 finance/crypto redesign after user craft rejection”

## Verification
- CDP/manual at 1440, 1280, 768, 390
- Measure: main stage width ≥ 1100 at 1440
- No purple radial gradients in computed styles of header
- Single safety strip; disabled composer honest
- Commit messages:
  - `docs(frontend): redesign Hermes F0 A as finance-crypto trading desk`
  - `docs(frontend): align F1 prototype to finance-crypto desk shell`

## Report
`/Users/sunyibo/programs/Hermes-quant-agent/.superpowers/sdd/frontend-f0-finance-redesign-report.md`
