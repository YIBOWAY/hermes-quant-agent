# D-31 Wave 2 Task F (partial) — Soft Hermes parity banners

**Date:** 2026-07-14  
**Repo:** `/Users/sunyibo/programs/ai-quant-platform`  
**Status:** Delivered (code + light vitest). Not pushed.  
**Commit:** `3400659` — `feat(frontend): soft Hermes parity banners on legacy research pages`

## Scope

Honest soft banners only. **No** page deletion, **no** redirects, **no** capability removal.

| Page | Route | File |
|------|-------|------|
| Factor Lab | `/factor-lab` | `src/frontend/app/factor-lab/page.tsx` |
| Backtester | `/backtest` | `src/frontend/app/backtest/page.tsx` |
| Experiments | `/experiments` | `src/frontend/app/experiments/page.tsx` |
| Agent Studio | `/agent-studio` | `src/frontend/app/agent-studio/page.tsx` |

## Shared component

- `src/frontend/components/HermesParityBanner.tsx`
- ZH/EN honest copy: Hermes is default research entry; page keeps full capability; merge/redirect incomplete ≠ retired
- Link: `hermesHomeHref(locale, {})` → `/zh/hermes` or `/en/hermes`
- Tokens: `border-info/40`, `bg-info/10`, `text-info` (QUANTUM_CORE info)
- Not dismissible (`role="status"`, `data-testid="hermes-parity-banner"`)

## Tests

| Suite | Result |
|-------|--------|
| `vitest` `lib/hermesParityBanner.test.ts` | 6 passed (ZH/EN markup + four page hosts) |

## Intentionally not done

- Legacy page retirement / redirects
- Removing Factor Lab / Backtester / Experiments / Agent Studio nav or forms
- Unrelated dirty tree (`earnings_calendar`, `options/data_refresh`, `.understand-anything`) left untouched
