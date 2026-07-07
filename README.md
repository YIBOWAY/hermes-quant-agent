# Hermes-quant-agent

Hermes orchestration layer for the local `ai-quant-platform`. Current Phase
0/1a work ships read-only / proposal-only digital employees that never touch the
trading chain:

Active roadmap: `docs/design/2026-07-01-roadmap-phases-0b-4.md` is the single
fact source for cross-repo direction. Phase 1a-3 (close-the-loop, incl.
`agent promote-candidate` Gate-3) and D-25 (latency triple + artifact-first)
are delivered; the next implementation slice is
`docs/superpowers/plans/2026-07-07-phase-1a-4-research-employees.md`
(research-employee expansion). Platform Phase 15 is reference material only.

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
  `propose|approve|backtest` flow covering the three human gates: factor
  formula confirm → candidate source approve → `agent promote-candidate`
  Gate-3 diff (human `git diff` review + commit). Factor code is generated in
  the Hermes session, ingested via platform `agent propose-factor --source-file`,
  approved only by an explicit human command, then backtested through
  `experiment run-config --provider futu --include-approved-candidates` (futu
  is the only configured provider; tiingo is not set up). Anti-overfit
  guardrails: per-factor trial counter (warns at 3rd run), 183-day holdout by
  default (`--final` runs the full window), and `hqa-gate` requiring
  `paper_days_completed >= 30` before broker-sim promotion.
- **Options radar summary** (`hqa.options_radar`) — daily structured summary
  for the latest collected Futu scan artifact; fresh Futu scans require
  explicit `--scan`.
- **AI-HOT alerts** (`hqa.aihot_alerts`) — `[SILENT]` notable-news watchdog;
  prints only when score/category filters find something worth attention.

Hermes-facing affordances (D-25): read-only platform queries run through
`scripts/hermes/hqa-quant-readonly.sh` (allowlist-gated, pre-authorized so
they don't prompt for approval); `hqa-notify.sh` pushes async completions to
Discord with a local JSONL fallback; the `hqa-quant` skill card gives Hermes
artifact-first command templates and a >30s triage convention.

Logic lives in `hqa/` (Python 3.9, stdlib only). Hermes cron runs thin wrappers
copied into `~/.hermes/scripts/` by `scripts/install.sh`.

Tests: `./.venv/bin/pytest`

Install/update Hermes script wrappers:

```bash
bash scripts/install.sh
```

See `docs/design/hermes_quant_agent_plan.md` and
`docs/design/2026-07-01-roadmap-phases-0b-4.md`.
