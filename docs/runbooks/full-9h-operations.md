# Full 9H operations runbook

This runbook operates the read-only/proposal-only automation delivered by
[`2026-07-12-full-9h-automation-notifications.md`](../superpowers/plans/2026-07-12-full-9h-automation-notifications.md).
The versioned desired state is [`config/hermes-cron.v1.json`](../../config/hermes-cron.v1.json).

## Safety contract

- All jobs are Hermes `--no-agent --deliver local` jobs.
- Full-9H jobs omit `--workdir`; their wrappers already change to this repo and
  omission keeps them out of the serial legacy workdir pool.
- The default notification target is `local`. Do not set
  `HQA_FULL9H_NOTIFY_TARGET=discord:<channel>` or run an external canary without
  explicit user authorization.
- The automation may read account/market/platform observations and append HQA
  receipts. It never generates a strategy, runs a backtest, mutates a paper
  account, creates an execution, sends an order or changes a safety flag.
- Never edit `~/.hermes/cron/jobs.json` directly.

## Install wrappers

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent
bash scripts/install.sh
```

Confirm all four installed files are physical executable files under
`~/.hermes/scripts/` and contain no `__HQA_*__` placeholders.

## Reconcile schedules

First inspect existing jobs:

```bash
hermes cron list --all
```

Create each missing new job exactly once:

```bash
hermes cron create '15,25 8 * * 2-6' --name hqa-full-9h-daily-close --script hqa-full-9h-daily-close.sh --no-agent --deliver local
hermes cron create '17 */2 * * *' --name hqa-full-9h-freshness --script hqa-full-9h-freshness.sh --no-agent --deliver local
hermes cron create '7,22,37,52 * * * *' --name hqa-full-9h-notification-drain --script hqa-full-9h-notification-drain.sh --no-agent --deliver local
```

Do not create a second weekly job. Find the existing `hqa-weekly-review` ID and
edit it in place:

```bash
hermes cron edit <existing-weekly-id> --schedule '0,10 9 * * 0' --name hqa-full-9h-weekly --script hqa-full-9h-weekly.sh --no-agent --deliver local --workdir ''
```

The three `create` commands intentionally omit `--workdir`. The weekly edit
explicitly clears the legacy value.

The second daily/weekly minute is a same-slot idempotent retry, not a second
logical run. The drain minutes are deliberately offset from source-job starts,
and each drain handles at most five 15-second remote attempts (75 seconds), so
it cannot occupy both source-job retry slots.

## One-shot acceptance

Run in this dependency order:

```bash
hermes cron run <daily-close-id>
hermes cron run <weekly-id>
hermes cron run <freshness-id>
hermes cron run <notification-drain-id>
```

Keep this order for an afternoon/manual acceptance. Automatic `as_of` values
use each job's latest non-future primary slot, so weekly 09:00 must be recorded
before a later same-day freshness slot. Run and poll each job to a terminal
result before triggering the next one; all four deliberately share one
non-blocking coordinator lock.

`cron run` queues work for the next ticker tick. Poll `hermes cron list --all`
until each job has a terminal result. A successful local acceptance has:

- one job per desired name, correct cron expression, no-agent, local delivery,
  and blank workdir;
- `automation/runs.jsonl` receipts with four current job IDs;
- `automation/notification-outbox.jsonl` containing a local `delivered` weekly
  receipt and no remote attempt;
- `artifacts/hermes-feed/manifest.v1.json` at schema 1.1 with six exact sources;
- `automation-status.v1.json` reporting `overall_status=fresh` after all four
  jobs have run;
- existing options signals folded idempotently. A `not_actionable` row remains
  `not_actionable`; it does not call platform observations or become `missed`.

## Diagnosing a degraded run

Read structured artifacts before rerunning anything:

```bash
python3 -m hqa.research_automation_cli freshness
python3 -m hqa.hermes_artifacts_cli show
python3 -m hqa.opportunity_cli list --limit 100
```

Exit code `0` means available/replay, `1` means degraded/failed/busy, and `2`
means invalid arguments or an idempotency conflict. Receipts expose stable error
codes only. Raw exceptions, credentials and local sensitive paths are never
persisted.

Notification semantics are conservative:

- `delivered`: local receipt or explicit remote success;
- `retryable`/`dead_letter`: local fallback is durable;
- `delivery_unknown`: the remote outcome was ambiguous and is never
  automatically retried.

Use a new explicit request ID only after understanding a failure. Do not delete
or hand-edit ledgers to force a replay.
