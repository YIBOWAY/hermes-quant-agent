# Hermes F0/F1 finance-crypto redesign v3 — report

**Date:** 2026-07-13  
**Status:** Delivered (design artifacts only; F1 **not** user-approved)  
**Platform commits (ai-quant-platform):**

| Commit | Message |
| --- | --- |
| `97b9221` | `docs(frontend): redesign Hermes F0 A as finance-crypto trading desk` |
| `3c00ab3` | `docs(frontend): align F1 prototype to finance-crypto desk shell` |

## What changed

### Layout
- Abandoned `nav | main | 288px secondary` squeeze.
- Shell: safety strip → horizontal top bar (brand · 今日/任务/审批/结果 · API/paper/kill chips) → full-width main stage → composer dock.
- Attention card is full stage width; automation | recent result as comfortable two-up.
- 值守 is a bottom strip (4 cells), not a permanent right rail.

### Visual DNA
- Canvas `#0b0e11`, surface `#1e2329` / `#2b3139` (Binance product).
- Primary CTAs amber `#F0B90B` / `#FCD535` (money/attention only).
- Blue `#0052FF` reserved for secondary links (not used as wallpaper).
- Hermes purple `#9085E9` only as flat brand mark (no glow, no radial haze).
- Flat exchange elevation; mono tabular IDs; no glass/mesh/emoji.

### Files
| Path | Action |
| --- | --- |
| `docs/design/hermes-workbench/f0/shared.css` | Finance token ladder rewrite |
| `docs/design/hermes-workbench/f0/direction-a.html` | Full shell + layout rewrite |
| `docs/design/hermes-workbench/f1/prototype.css` | Match F0 v3 |
| `docs/design/hermes-workbench/f1/prototype.html` | Top bar shell; home desk-stack; catalogs preserved |
| `docs/design/hermes-workbench/README.md` | v3 status note |

Preserved: content facts (safety, candidate id, automation 3/4, completed_degraded, disabled composer), four views, 44px targets, reduced motion, no CDN, no production React.  
Not touched: `earnings_calendar.csv`, `.understand-anything/`, B/C comparison HTML (still load shared tokens).

## Self-measure (headless Chrome)

Server: `python3 -m http.server 4173 --directory docs/design/hermes-workbench`

### F0 direction-a @ 1440×900
| Metric | Value |
| --- | --- |
| Viewport | 1440 |
| Main stage width | **1440px** |
| Content / attention usable | **1384px** (stage − 28px pad each side) |
| ≥1100 target | **pass** (1384 ≥ 1100; ~96% of viewport) |
| Permanent right rail | **none** |
| Side nav rail | **none** |
| Header purple radial | **none** (`background-image: none`) |
| Body canvas | `rgb(11, 14, 17)` = `#0b0e11` |
| Horizontal overflow | none |

### Other viewports (F0 A)
| Viewport | Stage w | Attention w | Overflow |
| --- | --- | --- | --- |
| 1280×800 | 1280 | 1232 | none |
| 768×1024 | 768 | 728 | none |
| 390×844 | 390 | 358 | none |

### F1 prototype @ 1440×900
| Metric | Value |
| --- | --- |
| Stage width | **1440px** |
| Attention usable | **1384px** |
| Rail / purple radial | none |
| Overflow 1440/1280/768/390 | none |

## Preview URLs
```
http://localhost:4173/f0/direction-a.html
http://localhost:4173/f1/prototype.html
```

## Concerns
1. **F1 not approved** — draft only; do not start F2/production shell from this package.
2. **direction-b / direction-c** still comparison artifacts; they inherit new shared tokens but keep their own layouts (may look mixed).
3. **State bar** for F0 is review chrome (amber selected), intentionally outside product hierarchy.
4. **Composer** remains honest-disabled; no write path.
5. Platform dirty tree still has unrelated `earnings_calendar.csv` / `.understand-anything/` — left uncommitted.

## Hierarchy preserved (COO)
safety → attention/action → status KPIs → work cards → result → disabled composer
