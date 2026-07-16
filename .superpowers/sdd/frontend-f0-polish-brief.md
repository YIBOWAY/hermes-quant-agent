# Hermes F0 direction-a visual polish brief

## Decision
User approved **direction-a** (COO desk hierarchy) with mandatory visual redesign.

## Non-negotiable product content (keep exact facts)
- Single top SafetyStrip only: `仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK`
- Candidate id: `factor-momentum_20d_reversal-323b045e4b`
- Automation 3/4, weekly_review stale, collapsed technical detail
- Recent result: `AAPL 风险与新因子计划 · completed_degraded`
- Disabled composer: `真实 Hermes 写入能力尚未通过` + disabled send
- Four local state views: idle / conversation / approval / result
- Viewports: 1440, 1280, 768, 390 with real breakpoints (no whole-UI transform scale)
- 44px interactive targets, reduced motion, no CDN remote fonts required (system + optional local-safe stacks OK; no network font loads preferred for hermetic design artifacts)
- Platform brand purple: `#9085E9` / hermes glow available

## Layout hierarchy (direction-a — keep)
1. Global safety strip
2. Dense COO desk: KPI/status → attention (approval) → automation one-row → recent result
3. Secondary values/context rail on wide screens
4. Honest disabled conversation boundary (not a live chat)

## Visual craft bar (raise massively)
Synthesize a **Hermes COO** product look from awesome-design-md (local copies under `.superpowers/sdd/design-refs/`):

Primary DNA:
- **Linear**: near-black canvas `#010102`–`#0f1011`, hairline borders `#23252a`, single lavender accent (map to Hermes `#5e6ad2`→`#9085E9`), charcoal cards, precise type tracking, no decorative noise
- **Raycast**: dark product chrome as hero, refined control density, subtle gradients only as atmosphere not rainbow slop
- **Superhuman**: premium dark, tight rounded controls, keyboard-first feel
- **VoltAgent**: void canvas + one electric accent discipline (one accent only)
- **Vercel**: Geist-like geometric clarity, monochrome labels for technical chips

Anti-patterns (forbidden):
- AI purple-pink gradient soup
- Emoji as icons
- Left-border rainbow cards everywhere
- Busy glassmorphism stacks
- Inter as display without careful tracking (body OK)
- Fake stock illustrations

Craft requirements:
- 8px rhythm, consistent radii (8–12px cards, 6–8px controls)
- Hairline 1px borders, soft elevation (max 1–2 shadow levels)
- Monospace chips for IDs/run codes with break-all
- Status via color + text label (never color alone)
- Disabled composer contrast ≥ 4.5:1 for the reason text
- Mobile: real nav tabs (buttons, not inert spans)
- Typography: large headline hierarchy (title ≥ 2.2× body), negative tracking on titles
- Micro-interactions: soft hover/focus only; respect prefers-reduced-motion

## Deliverables
1. Rewrite `f0/shared.css` and `f0/direction-a.html` to production-prototype quality
2. Optionally light-touch shared tokens used by B/C so they don't break, but A is the approved path
3. Update README status notes for polish
4. Self-check four viewports
5. Commit: `docs(frontend): polish Hermes F0 direction-a to premium dark COO craft`

## Out of scope
- F1 full state catalogs (next task after polish lands)
- Production React under src/frontend/app
