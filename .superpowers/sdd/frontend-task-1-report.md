# Frontend Task 1 Report — F0 visual directions

**Status:** complete (draft directions committed; **F0 not approved**)  
**Platform commit:** `e24246f` — `docs(frontend): draft Hermes F0 high-fidelity visual directions`  
**Repo:** `/Users/sunyibo/programs/ai-quant-platform`  
**Date:** 2026-07-13  

## Deliverables

| Path | Role |
| --- | --- |
| `docs/design/hermes-workbench/README.md` | Status, directions, review placeholder; **no F0 decision** |
| `docs/design/hermes-workbench/f0/shared.css` | Exact brief tokens + real breakpoints (1279 / 767 / 430) |
| `docs/design/hermes-workbench/f0/direction-a.html` | COO desk — action/status first |
| `docs/design/hermes-workbench/f0/direction-b.html` | Research timeline — change/progress first |
| `docs/design/hermes-workbench/f0/direction-c.html` | Quiet split canvas — conversation/result first + idle 5s answers |

## Content parity (fixed brief facts)

- Safety strip only: `仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK`
- Candidate: `factor-momentum_20d_reversal-323b045e4b`
- Automation 3/4 + stale `weekly_review` + collapsed tech detail
- Recent result: AAPL plan · `completed_degraded`
- Disabled composer: `真实 Hermes 写入能力尚未通过` + disabled 发送
- Local JS toggles: idle / conversation / approval / result  
- No CDN/remote assets

## Self-check

Served: `python3 -m http.server 4173 --directory docs/design/hermes-workbench`  

Playwright Chromium matrix: 3 directions × 4 viewports (1440 / 1280 / 768 / 390) × 4 views = **48/48 pass**

- `scrollWidth <= innerWidth`
- visible interactive targets ≥ 44px
- single `.safety`; no in-main safety duplicate
- no whole-UI transform scale
- zero remote network requests
- idle fixed facts present

## Gates

- Independent UX review table in README: **placeholder only**
- User F0 selection: **not recorded** (do not start F1 until written approval)
- Dirty files preserved (not staged): `data/options_universe/earnings_calendar.csv`, `.understand-anything/`

## How to open

```bash
cd /Users/sunyibo/programs/ai-quant-platform
python3 -m http.server 4173 --directory docs/design/hermes-workbench
# http://localhost:4173/f0/direction-a.html
# http://localhost:4173/f0/direction-b.html
# http://localhost:4173/f0/direction-c.html
```

## Concerns

1. Independent reviewer has not filled pass/fail in README yet.  
2. Direction B stacks dual composers (side vs mobile) via CSS display — fine for F0, simplify in F1.  
3. Prototype state-bar is review chrome only; must not ship as production TopBar.  
4. Platform production palette is warmer/editorial; F0 uses brief tokens (`#0c0d10` / `#8b7cf6`) — align or deliberately diverge at F1/F2 token freeze.
