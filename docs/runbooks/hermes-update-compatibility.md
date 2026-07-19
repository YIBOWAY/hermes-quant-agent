# Hermes manual-update compatibility watcher

## Purpose

Hermes may be updated manually. HQA does **not** auto-update, patch, roll back,
restart, or reconfigure it. Instead, the desired Hermes cron contract runs one
deterministic local watcher every 15 minutes. When the re-probe identity has
not changed since the last successful check, the watcher exits silently without
making an HTTP request. After a checkout or re-probe-trigger change, it checks
that the existing read-only integration is still compatible.

This is a `--no-agent` job. Hermes cron schedules a local script; no Hermes
conversation, model, provider, prompt, token, or agent loop participates.

## Frozen desired cron entry

The versioned desired state is
[`config/hermes-cron.v1.json`](../../config/hermes-cron.v1.json):

```json
{
  "job_id": "hermes_compatibility_watch",
  "name": "hqa-hermes-compatibility-watch",
  "schedule": "*/15 * * * *",
  "script": "hqa-hermes-compatibility-watch.sh",
  "no_agent": true,
  "deliver": "local"
}
```

Install the physical wrapper with the normal HQA installer:

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent
bash scripts/install.sh
```

After reviewing `hermes cron list --all`, an operator may reconcile the desired
entry explicitly:

```bash
hermes cron create '*/15 * * * *' \
  --name hqa-hermes-compatibility-watch \
  --script hqa-hermes-compatibility-watch.sh \
  --no-agent \
  --deliver local
```

Do not edit `~/.hermes/cron/jobs.json` directly. The repository change itself
does not mutate the live cron registry.

## What triggers a re-probe

The watcher derives a canonical re-probe identity from:

- the Hermes checkout HEAD, tree and tracked-worktree status;
- the watcher module, CLI, cron contract and deployed-wrapper source;
- a closed list of HQA Agent Workspace / Hermes adapter files;
- a closed list of platform health, safety, Hermes BFF schema/route/client
  files.

The HQA/platform file digests are **re-probe triggers only**. They make a local
change invalidate an old successful baseline, but they do not prove which
source bytes an already-running process loaded. Likewise, checkout identity is
useful change detection, not runtime attestation. Runtime compatibility comes
only from the fixed local-service and HTTP observations made during that check.

No HQA-specific install stamp is required. A normal official Hermes manual
update changes the checkout identity and therefore causes the next cron tick to
probe. If the service definition is then stale, the check remains incompatible;
after the operator separately reconciles the Hermes gateway service, the next
tick can establish a successful read-compatibility baseline without editing a
JSON stamp.

## Fixed compatibility probes

Only after the re-probe identity changed or lacks a successful baseline, the watcher
runs one fixed local status command and four fixed HTTP GETs:

1. `hermes gateway status` (local, bounded output, no shell);
2. `GET http://127.0.0.1:8642/health`;
3. `GET http://127.0.0.1:8765/api/health`;
4. `GET http://127.0.0.1:8765/api/hermes/gateway`;
5. `GET http://127.0.0.1:8765/api/hermes/sessions?limit=1&offset=0`.

The HTTP client accepts numeric loopback origins only, disables environment
proxies and redirects, sets short timeouts, and caps response bytes. It never
reads a Hermes API-key file and never sends `Authorization`. Responses must
match closed schemas. In particular:

- Hermes health must identify `hermes-agent` and a non-empty version;
- all four platform safety facts remain `dry_run=true`,
  `paper_trading=true`, `live_trading_enabled=false`, `kill_switch=true`;
- the platform bind address remains loopback;
- the gateway remains `read_status=available`, connected, and advertises
  `session_resources=true`;
- `session_api_available=true` while `chat_write_ready=false`;
- platform command-ledger mutation remains disabled;
- the session-list response remains the bounded read model;
- a stale or unsupervised Hermes launchd service definition is incompatible.

The watcher does not call POST/PATCH/PUT/DELETE, a provider, a broker, a paper
account, a trading path, an approval gate, `hermes gateway start`, or any update
command.

## State, reports and output

Default state lives under
`data/_runtime/hermes-compatibility/` with a `0700` directory and `0600` files.
Writes are atomic, files are opened without following symlinks, and a process
lock prevents overlapping cron executions.

- `baseline.json` points to the **last successful** re-probe identity/report only.
- `reports/<sha256>.json` is canonical, content-addressed compatibility
  evidence.
- `latest.json` is the most recent attempt, successful or failed.

At most 128 owned, regular, canonically named reports are retained. Cleanup
protects the current report and last-good baseline report. It never follows or
deletes symlinks, foreign-owned files, directories, or non-canonical names.

Reports contain only digests, fixed probe names, booleans and bounded error
codes. Session IDs, titles, previews/messages, model names, response bodies,
PIDs, command output, paths from the service-status output and secrets are
discarded.

An unchanged successful re-probe identity produces no stdout and no HTTP. A
changed identity prints one small JSON status line. Incompatibility exits non-zero,
preserves the previous compatible baseline, and is retried at the next cron
tick until a compatible check succeeds.

## Manual recovery

1. Read `latest.json` and its content-addressed report.
2. Confirm the Hermes checkout reflects the intended manual update.
3. If the report says `gateway_service_definition_stale`, review the installed
   Hermes service definition separately. The watcher intentionally does not run
   the suggested start/restart command.
4. Fix the underlying installation or contract drift without enabling any HQA
   write gate.
5. Re-run the fixed wrapper with **no arguments**:

   ```bash
   ~/.hermes/scripts/hqa-hermes-compatibility-watch.sh
   ```

6. Require a new `compatible` report before treating the observed runtime API
   as read-compatible at that point in time. This is not source attestation and
   does not authorize `chat_write_ready`, public composer submission, worker
   claim/dispatch, Durable Runs, or any other write path.
