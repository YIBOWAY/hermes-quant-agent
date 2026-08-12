# Four-Lane Delivery Record — 2026-08-12

Platform commit: `883b1cd feat(lanes): backup bars, market news, brief archive+auto-archive, driver baskets`
Repo: `ai-quant-platform` main; runtime clone fast-forwarded the same day.
Plan context: spec §2.9b Asia Radar Slice 2B + the 2026-08-11 data-source evaluation (Finnhub/AlphaVantage/Tiingo/TwelveData/Polygon/NewsAPI).

## What shipped

| Lane | Content | Activation |
| --- | --- | --- |
| Lane 1 backup bars | Opt-in disaster-recovery chain Futu → TwelveData → Tiingo, provider-tagged cache keyspace, fail-closed on exhaustion. Tiingo `strict_symbols` opt-in (default = per-symbol tolerance for the shared pipeline), BRK.B passthrough, typed errors. Chain reader accepts `as_of` for deterministic tests. | Set chain + keys via env; Futu primary is never silently replaced. |
| Lane 2 market news | Polygon → Finnhub failover with provider/served_from watermarking; `/api/news/market-topics` + `/api/news/status` (key-presence booleans); brief renders ≤3 market-topic headlines; fail-closed 503 `market_news_unavailable`. NewsAPI is dev-only, double-gated (`QS_MARKET_NEWS_NEWSAPI_DEV_ENABLED` + trust mode) — Developer tier ToS is localhost-only; never in any always-on/deployed path. | Env keys `QS_POLYGON_API_KEY` / `QS_FINNHUB_API_KEY`. |
| Lane 3 brief archive + auto-archive | `/api/brief/archive` daily/weekly/monthly grouped views (weekly/monthly are pure rollups over `brief_issues` rows — no new storage); `BriefArchiveSidebar` （日报/周报/月报 tabs, month-grouped collapsible, bilingual, honest empty/error states) on `/brief` and `/brief/[publicId]`; `brief auto-archive` CLI builds `brief_snapshot_v1` server-side from backend facts and upserts idempotently keyed by (owner, issue_date, locale); LaunchAgent template + install scripts + `docs/guides/brief-archive.md`. | Sidebar live now. **Auto-archive needs one manual step**: `scripts/install_brief_auto_archive_launchagent.sh` (daily 17:20 local). |
| Lane 4 driver baskets (Slice 2B) | `DRIVER_BASKET_SPECS`: EWH leaders HK.00700/09988/00005 via Futu local lane (HKD display-only); EWJ leaders TM/SONY/MUFG/HMC + EWT leaders TSM/UMC as US ADRs via Polygon grouped-daily (1 call/day steady state, isolated `provider="polygon"` cache keyspace). Pending markets honestly marked: south-korea `no_liquid_us_listing`, china-a `permission_not_granted`, 7 markets `no_verified_channel`. Overlays never raise; attach runs after ETF metrics; schema_version → 1.3; summary path skips the lane. | **JP/TW ADR leaders need ~20 trading days of accumulation** before flipping available (honest `insufficient_history` until then, by design). |

## Review-hardening folded into the same commit

- Test hermeticity: repo `.env` sets `QS_HERMES_GATEWAY_ENABLED=true`, which made every `create_app()` test fail startup validation (loopback bind declaration). `tests/conftest.py` now forces it off; the hermes gateway test pins `api_key_file=None` so the capability probe stays hermetic.
- Cache-expiry time-bomb: `EquityBarCache.write()` anchors `fetched_at` to `knowledge_ts.max()`; fixtures with pinned past knowledge_ts expired at knowledge_ts+TTL. Backup-cache tests pin `fetched_at`/`as_of`.
- Lane 3 review corrections: blocking performance payload without `requested_start`/`requested_end` raises typed `AutoArchiveUnavailable` (no mid-build KeyError); reachable-but-empty equity curve watermarked `unavailable` (not "available" over 0 points); dead `apiError` field dropped from `BriefArchiveViewResponse`; in-memory repository idempotency contract test added (mirrors the Postgres ON CONFLICT + version-bump path).
- Frontend/backend export contract completed (`BriefArchive*Response`, `AsiaRadarDriver*` aliases in `lib/api.ts`); `scripts/README.md` entries for the two new auto-archive scripts.

## Verification

- Backend: 3100 passed / 271 deselected (non-pg, non-provider, non-network), exit 0.
- Frontend: tsc exit 0; vitest 81 files / 503 tests passed; canonical `npm run lint` exit 0; ruff clean.
- Key-leak grep across all 52 changed files: zero matches (masked forms only; keys remain env-only).

## Paid-service recommendation (owner asked 2026-08-11)

**Twelve Data Grow ($79/mo)** is the only upgrade that fills the Asia-index/non-US hole (unlocks EWY leaders + KR/TW/SG/AU local indexes). Polygon Starter ($29) does not cover non-US; NewsAPI Business ($449/mo) is not worth it for this use case. No purchase has been made.
