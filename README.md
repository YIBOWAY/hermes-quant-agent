# Hermes-quant-agent

Hermes orchestration layer for the local `ai-quant-platform`. Current Phase
0/1a work ships read-only / proposal-only digital employees that never touch the
trading chain:

Active roadmap: `docs/design/2026-07-01-roadmap-phases-0b-4.md` is the single
fact source for cross-repo direction. The next implementation slice is
`docs/plans/2026-07-03-phase-1a-3-close-the-loop.md`; platform Phase 15 is now
reference material only.

- **Safety watchdog** (`hqa.doctor_watchdog`) — `[SILENT]`; alerts only if a
  `safety.*` invariant deviates or `quant-system doctor` fails.
- **Pre-market digest** (`hqa.premarket_digest`) — daily summary of platform
  safety status, the latest collected Futu options-radar artifact, and AI HOT
  headlines with explicit degraded labels when sources are unavailable.
- **Review log** (`hqa.reviewlog`, `hqa.review_cli`) — append-only JSONL
  cognition store with Markdown rendering and human-filled confirmation fields.
- **Signal watchdog** (`hqa.signal_watchdog`) — consumes collected scan
  artifacts in collect/alert mode; it does not launch expensive Futu scans by
  default.
- **Weekly review** (`hqa.weekly_review`) — summarizes the last 7 days of
  review-log and run-log records.
- **Scene-B factor reproduction** (`hqa.factor_repro_cli`) — human-gated
  `propose|approve|backtest` flow. Factor code is generated in the Hermes
  session, ingested via platform `agent propose-factor --source-file`, approved
  only by an explicit human command, then backtested through
  `experiment run-config --provider tiingo --include-approved-candidates`.
  Current CLI covers Gates 1-2; Gate 3 promote-to-code is the next 1a-3 slice.
- **Options radar summary** (`hqa.options_radar`) — daily structured summary
  for the latest collected Futu scan artifact; fresh Futu scans require
  explicit `--scan`.
- **AI-HOT alerts** (`hqa.aihot_alerts`) — `[SILENT]` notable-news watchdog;
  prints only when score/category filters find something worth attention.

Logic lives in `hqa/` (Python 3.9, stdlib only). Hermes cron runs thin wrappers
copied into `~/.hermes/scripts/` by `scripts/install.sh`.

Tests: `./.venv/bin/pytest`

Install/update Hermes script wrappers:

```bash
bash scripts/install.sh
```

See `docs/design/hermes_quant_agent_plan.md` and
`docs/design/2026-07-01-roadmap-phases-0b-4.md`.
