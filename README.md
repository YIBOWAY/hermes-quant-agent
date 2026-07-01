# Hermes-quant-agent

Hermes orchestration layer for the local `ai-quant-platform`. Phase 0a ships two
read-only digital employees that never touch the trading chain:

- **Safety watchdog** (`hqa.doctor_watchdog`) — `[SILENT]`; alerts only if a
  `safety.*` invariant deviates or `quant-system doctor` fails.
- **Pre-market digest** (`hqa.premarket_digest`) — daily summary of platform
  safety status + `options daily-scan --provider sample`.

Logic lives in `hqa/` (Python 3.9, stdlib only). Hermes cron runs thin wrappers
copied into `~/.hermes/scripts/` by `scripts/install.sh`.

Tests: `./.venv/bin/pytest`

See `docs/plans/2026-07-01-phase-0a-readonly-digital-employee.md`.
