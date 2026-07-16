# Frontend Task 2 Report — F1 full-state interaction prototype

**Status:** draft complete — **F1 not approved** (user gate)  
**Platform commit:** `b0dab2b` — `docs(frontend): draft Hermes F1 full-state interaction prototype`  
**Repo:** `/Users/sunyibo/programs/ai-quant-platform`  
**Date:** 2026-07-13  

## Deliverables

| Path | Role |
| --- | --- |
| `docs/design/hermes-workbench/f1/prototype.html` | Clickable COO desk + walkthrough + state matrix |
| `docs/design/hermes-workbench/f1/prototype.css` | Premium dark F0-A craft (Linear DNA, Hermes `#9085E9`) |
| `docs/design/hermes-workbench/f1/states/home.json` | 5 states |
| `docs/design/hermes-workbench/f1/states/conversation.json` | 9 states |
| `docs/design/hermes-workbench/f1/states/tasks.json` | 9 states |
| `docs/design/hermes-workbench/f1/states/approvals.json` | 6 states |
| `docs/design/hermes-workbench/f1/states/results.json` | 5 states |
| `docs/design/hermes-workbench/README.md` | F1 draft status; **no approval recorded** |

## State catalog IDs (exact)

- home: `empty/loading/normal/degraded/hermes_offline`
- conversation: `sending/queued/streaming/reconnecting/stopping/reconciling/failed/quota/fallback`
- tasks: `queued/running/waiting_gate/stop_requested/reconciling/completed/partial/failed/stopped`
- approvals: `available/approved/rejected/expired/stale/digest_mismatch`
- results: `loading/partial/no_data/audit_warning/source_missing`

Each state includes zh/en copy, non-color `status_text`, `long_error`, actions, technical details.

## Walkthrough

```
提出目标 → Hermes 结构化计划 → Gate 1 formula/plan confirmation
→ streaming (real event labels) → completed_degraded result
→ Gate 2 exact manifest summary → Gate 3 scoped diff summary
```

## Constraints honored

- Local `fetch("./states/*.json")` only; no production imports; no form submit; composer disabled
- Visible **prototype data** badge outside product chrome
- `aria-live="polite"` state announcements; state buttons `aria-pressed`; modal focus restore + Escape
- Mobile order: status → conversation → plan/execution → result → composer
- Real breakpoints (not whole-UI scale); `prefers-reduced-motion` kill-switch
- Safety strip only for paper/live/kill/API
- No touch of `src/frontend/app` / components / lib
- Dirty paths preserved: `data/options_universe/earnings_calendar.csv`, `.understand-anything/`

## Self-check (Chrome DevTools)

- Walkthrough steps 1–7 render correct surfaces/copy
- Modal open/close restores focus to trigger
- Network: only html/css + five JSON catalogs (favicon 404 is browser chrome, not product)
- Overflow none at 1440 / 1280 / 768 / 390 emulation
- Visible interactive targets ≥ 44px (spot check)
- Console: no product script errors

## Gates

- Independent F1 UX review table: implementer self-check only in README
- User F1 approval: **not recorded** — stop here
- Do not run approval commit message until user writes approval

## How to open

```bash
cd /Users/sunyibo/programs/ai-quant-platform
python3 -m http.server 4173 --directory docs/design/hermes-workbench
# http://127.0.0.1:4173/f1/prototype.html
```

## Concerns

1. Independent reviewer has not yet filled formal F1 pass/fail beyond implementer self-check.  
2. Review chrome (walkthrough + state bars) is dense on 390; intentional for design review, must not ship as production TopBar.  
3. Gate 1/2/3 actions are demonstration-only; CAS fields never pre-filled for approve.  
4. Default boot is home/`normal` desk; walkthrough step 1 jumps to `empty` goal state — intentional lifecycle start.
