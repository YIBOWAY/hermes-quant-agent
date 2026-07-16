# Hermes F0 Craft Checklist — Quant COO Desk

**Scope:** Visual craft only for F0 direction-a (COO desk). Synthesized from Linear + Raycast + VoltAgent dark product DNA, mapped to Hermes brand `#9085E9`.  
**Use:** Implementer self-check before polish review. Fail any row that cannot be answered “yes” with a concrete CSS/token proof.  
**Not in scope:** Platform React, capability wiring, copy changes to product facts.

---

## Sources (what each system donates)

| Source | Keep | Leave behind |
| --- | --- | --- |
| **Linear** | Near-black canvas ladder, hairline charcoal panels, single lavender accent, negative tracking on titles, quiet luxury | Marketing display scale (80px), multi-surface marketing cards |
| **Raycast** | Product chrome as hero, tight control density, 1px hairlines, rare semantic accent chips, monochrome UI first | Category rainbow tiles, hero red gradient stripes |
| **VoltAgent** | Void canvas + **one** electric accent discipline, code-like mono chips, documentation clarity | Green brand primary (Hermes owns purple), marketing display weight |

Hermes mapping: Linear lavender `#5e6ad2` → brand purple `#9085E9`. Semantic success/warn/danger stay functional, never brand.

---

## 1. Surface hierarchy

Quiet depth, not glass stacks. Elevation is mostly value steps + hairlines; shadows are rare.

| # | Check | Pass criteria |
| --- | --- | --- |
| 1.1 | Canvas is the darkest plane | One near-black root (`#010102`–`#07080a` band). No mid-gray full-page fill. |
| 1.2 | ≤ 4 surface steps | e.g. canvas → panel → raised row/card → input/control. No freehand one-off greys. |
| 1.3 | Safety strip is distinct but not a second brand bar | Sits on canvas or a single step above; never competing gradient banner. |
| 1.4 | Attention (approval) outranks automation/recent | Clear visual weight: larger title block, stronger border or surface step — not equal card grid of three equal tiles. |
| 1.5 | Secondary rail is quieter | Context/values rail uses lower contrast ink and no accent borders on idle. |
| 1.6 | Disabled composer reads as boundary, not broken UI | Surface slightly inset or muted; reason text remains readable (≥ 4.5:1). |
| 1.7 | Max 1–2 shadow levels | Soft ambient only; prefer hairline over drop shadow. No stacked glow layers. |

**Anti-pass:** Nested translucent panels, backdrop-blur everywhere, every block at the same surface level.

---

## 2. Hairlines

Raycast/Linear product chrome: structure from 1px edges, not thick frames.

| # | Check | Pass criteria |
| --- | --- | --- |
| 2.1 | Default edge is 1px | `border: 1px solid` on cards, strips, inputs, chips. No 2–3px “card frames”. |
| 2.2 | Hairline token is stable | ~`#23252a` / `rgba(255,255,255,0.08–0.12)` family; one soft + one strong variant max. |
| 2.3 | Dividers are hairlines | KPI row separators and section rules use the same token family, not pure white or brand purple. |
| 2.4 | Focus is not a hairline substitute | Focus ring is separate (accent or high-contrast outline), ≥ 2px visible, never only color shift. |
| 2.5 | No left-border rainbow | Forbidden: 3–4px colored left rails on every card. One intentional attention treatment max if needed. |

**Anti-pass:** Double borders, inset + outset simultaneously, neon outlines on idle cards.

---

## 3. Accent discipline

VoltAgent rule: one brand electric; Linear rule: accent is intentional, never decorative soup.

| # | Check | Pass criteria |
| --- | --- | --- |
| 3.1 | Single brand accent | Hermes `#9085E9` (and one hover/focus step) only for primary interactive emphasis, focus, and rare key CTAs. |
| 3.2 | Brand ≠ status | Success / warn / danger / stale / degraded use separate semantic tokens — not recolored brand purple. |
| 3.3 | Accent area budget | On idle desk, brand color appears on ≤ ~5% of chrome (e.g. focus, one link, one active nav). Not full-card fills. |
| 3.4 | Gradients are atmosphere only | Optional single subtle void gradient; no multi-stop purple→pink→blue. No AI “glow orbs”. |
| 3.5 | White/ink primary actions allowed | Raycast-style white pill CTA is OK for primary; do not force purple buttons everywhere. |
| 3.6 | Soft accent fills are rare | If used (chip bg, focus wash), opacity ~10–18%; never saturated full-bleed panels. |

**Anti-pass:** Purple-pink gradient soup, brand glow on every card, accent used as decoration without meaning.

---

## 4. Type scale

Linear precision + product density (not marketing display).

| # | Check | Pass criteria |
| --- | --- | --- |
| 4.1 | Clear hierarchy | Desk title ≥ ~2.2× body size; section labels distinct from body and caption. |
| 4.2 | Negative tracking on titles | Large titles use measured negative letter-spacing; body stays ~0. |
| 4.3 | Weight restraint | Prefer 400/500/600. Avoid 800–900 display shouting. |
| 4.4 | Mute ladder for ink | At least: primary ink, secondary, tertiary/mute. Labels and meta never same weight as values. |
| 4.5 | Mono for machine strings | Candidate IDs, digests, run codes: monospace chip, `break-all` / wrap, not proportional body. |
| 4.6 | No remote font dependency | System / local-safe stacks; hermetic artifacts load without CDN fonts. |
| 4.7 | Caption ≠ illegible | Smallest UI text still readable (≈12–13px floor for essential status). |

**Anti-pass:** One flat 14px grey wall; Inter display with default tracking; emoji standing in for labels.

---

## 5. Density

COO desk is an ops surface: tight, scannable, not a landing page.

| # | Check | Pass criteria |
| --- | --- | --- |
| 5.1 | 8px rhythm | Padding/gap snap to 4/8px grid. No 7/11/13px one-offs. |
| 5.2 | Radii consistency | Cards ~8–12px; controls ~6–8px; pills only for chips/status. |
| 5.3 | Automation is one row when healthy | Compress normal automation; expand only on failure/stale/degraded/human action. |
| 5.4 | Technical detail collapsed | cron, paths, raw errors, run IDs behind disclosure — not permanent clutter. |
| 5.5 | KPI/status → attention → automation → recent | Vertical scan order matches product hierarchy (see polish brief). |
| 5.6 | Touch targets still 44px | Density does not shrink hit areas; pad invisible hit boxes if visual control is smaller. |
| 5.7 | Viewport honesty | Real breakpoints at 1440 / 1280 / 768 / 390 — no `transform: scale` of the whole UI. |

**Anti-pass:** Marketing section gaps (~96px) inside the desk body; equal-height card dashboards that hide priority.

---

## 6. Status chips

Vercel monochrome technical chips + Raycast semantic color reserved for meaning.

| # | Check | Pass criteria |
| --- | --- | --- |
| 6.1 | Color + text always | Status never color-only. Chip includes readable label (`completed_degraded`, `stale`, `pending`, etc.). |
| 6.2 | Chip anatomy | Hairline or soft fill + label; optional 6–8px dot. Radius pill or 6px — consistent. |
| 6.3 | Semantic map is fixed | e.g. healthy/success, attention/warn, danger/fail, stale/muted, offline/neutral. No ad-hoc hex per card. |
| 6.4 | ID chips ≠ status chips | Mono ID chips are neutral charcoal; status chips carry semantic color. |
| 6.5 | Safety strip language separate | Global paper/live/kill/API lives only in SafetyStrip — not duplicated as decorative chips in every panel. |
| 6.6 | Degraded is visible but calm | `completed_degraded` / weekly_review stale: warn semantic + text, not red alarm unless action-required. |

**Anti-pass:** Rainbow tag clouds; emoji status; green/red without words; purple used as “special status”.

---

## 7. Anti-AI-slop

If it looks like a generic AI dashboard template, it fails.

| # | Forbidden | Replace with |
| --- | --- | --- |
| 7.1 | Purple–pink–blue mesh / aurora backgrounds | Flat void canvas + optional single soft vignette |
| 7.2 | Emoji as icons | Lucide-style line icons or pure text labels |
| 7.3 | Glassmorphism card stacks | Opaque surface ladder + hairlines |
| 7.4 | Fake stock charts / decorative sparklines | Real product facts only (or empty honest states) |
| 7.5 | “Click here” / vague CTA glow blobs | Specific actions; quiet hover; visible focus |
| 7.6 | Every panel accent-bordered | One attention emphasis; rest monochrome |
| 7.7 | Interlocking gradient buttons | Solid primary (white or brand) + ghost secondary |
| 7.8 | Ornamental hero illustration | Desk content is the hero |
| 7.9 | Unearned motion | Soft hover/focus only; honor `prefers-reduced-motion` |
| 7.10 | Invented “AI confidence” meters | Truthful automation counts, approval state, result status |

**Smell test (10 seconds):** Does it look like Linear issue chrome or a Midjourney “fintech AI” mock? Prefer the former.

---

## Quick review pass (reviewer)

Run top-to-bottom after implementer polish:

1. **Surfaces:** Count distinct greys in the main column — ≤ 4 steps?
2. **Hairlines:** Zoom 200% — are edges 1px and consistent?
3. **Accent:** Screenshot idle desk — is brand purple sparse and intentional?
4. **Type:** Can you name title / body / meta / mono without measuring?
5. **Density:** Is automation one line when healthy? Is technical detail collapsed?
6. **Chips:** Every status readable in greyscale?
7. **Slop:** Zero gradient soup, emoji icons, glass stacks, fake charts?

Any “no” blocks F0 polish approval until fixed.

---

## Token hints (non-binding reference)

Align tokens to existing F0 polish brief; do not invent a second palette.

| Role | Direction |
| --- | --- |
| Canvas | `#010102`–`#07080a` |
| Panel | `#0f1011`–`#121212` |
| Raised / control | `#141516`–`#18191a` |
| Hairline | `#23252a` / soft white alpha |
| Ink primary | `#f4f4f6`–`#f7f8f8` |
| Ink mute | `#8a8f98` band |
| Brand | `#9085E9` (+ one hover/focus) |
| Semantic | success / warn / danger / stale — separate from brand |

Radii: cards 8–12px · controls 6–8px · chips pill.  
Spacing: 8px base.  
Shadows: 0–2 levels, low opacity.

---

## Sign-off

| Role | Result | Notes |
| --- | --- | --- |
| Implementer self-check | ☐ pass / ☐ fail | |
| Design critique review | ☐ pass / ☐ fail | |

Related: `frontend-f0-polish-brief.md`, `design-refs/linear.app.DESIGN.md`, `design-refs/raycast.DESIGN.md`, `design-refs/voltagent.DESIGN.md`.
