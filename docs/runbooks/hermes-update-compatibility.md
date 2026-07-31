# Hermes manual-update compatibility watcher

## Purpose

Hermes may be updated manually. HQA does **not** auto-update, patch, roll back,
restart, or reconfigure it. Instead, the desired Hermes cron contract runs one
deterministic local watcher every 15 minutes. When the re-probe identity has
not changed since the last successful check for the selected profile, the
watcher exits silently without making an HTTP request. After a checkout,
profile, shared-contract, or re-probe-trigger change, it checks the selected
compatibility profile.

This is a `--no-agent` job. Hermes cron schedules a local script; no Hermes
conversation, model, provider, prompt, token, or agent loop participates.

Two profiles are intentionally distinct:

- `dark_readonly` preserves the historical session-read-only compatibility
  check and requires Platform mutation/chat readiness to remain off.
- `local_agent_v0_2` is the installed wrapper default. It validates the
  versioned Platform/HQA contract manifest plus the native Hermes durable Run
  and managed Session capability surface needed by the local Agent.

A result is observation, not authority: neither profile opens a gate, changes
database roles, starts a worker, or authorizes public write.

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
HQA_HERMES_SOURCE_DIR=/absolute/path/to/the/installed/hermes-worktree \
  bash scripts/install.sh
```

`HQA_HERMES_SOURCE_DIR` defaults to `~/.hermes/hermes-agent`. The installer
requires it to be the absolute, physical, owner-controlled root of a readable
Git checkout/worktree and freezes that exact path into the installed watcher.
The cron job does not infer a checkout from Python imports or accept a later
environment override; re-run the installer when the intended Hermes worktree
changes.

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

- the selected profile;
- the Hermes checkout HEAD, tree and tracked-worktree status;
- the watcher module, CLI, cron contract and deployed-wrapper source;
- a closed list of HQA Agent Workspace / Hermes adapter files;
- a closed list of platform health, safety, Hermes BFF schema/route/client
  files.
- for `local_agent_v0_2`, the canonical digest and schema version of
  `src/quant_system/hermes/agent_v02_hermes_compatibility.v1.json` under the
  explicit Platform root, plus the closed set of Platform settings,
  admission, connector, release, ledger, registry, binding, evidence and
  database modules that produce the canonical 26-key health projection. These
  v0.2-only files are not required by the legacy `dark_readonly` profile.

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

The Platform manifest is the only machine contract shared by Platform and the
watcher. Unknown schema versions, duplicate JSON fields, extra root fields,
missing files, symlinks, changed HQA CLI operations, or a write-contract
mismatch fail closed as drift.

## Fixed compatibility probes

Only after the re-probe identity changed or lacks a successful baseline, both
profiles run one fixed local status command and four fixed HTTP GETs:

1. `hermes gateway status` (local, bounded output, no shell);
2. `GET http://127.0.0.1:8642/health`;
3. `GET http://127.0.0.1:8765/api/health`;
4. `GET http://127.0.0.1:8765/api/hermes/gateway`;
5. `GET http://127.0.0.1:8765/api/hermes/sessions?limit=1&offset=0`.

`local_agent_v0_2` additionally performs exactly one direct Hermes read:

6. `GET http://127.0.0.1:8642/v1/capabilities`.

The HTTP client accepts numeric loopback origins only, disables environment
proxies and redirects, sets short timeouts, and caps response bytes. For the
local Agent profile it may read
`HQA_HERMES_COMPAT_HERMES_API_KEY_FILE` (default:
`<HQA repo>/data/_runtime/hermes-api.key` when present). The file must be a
physical, owner-owned regular file with mode `0600` or stricter. Its value is
sent only as the loopback capabilities Bearer token and is never written to a
report, stdout, stderr, argv, or environment. Responses must match closed
schemas. In particular:

- Hermes health must identify `hermes-agent` and a non-empty version;
- all four platform safety facts remain `dry_run=true`,
  `paper_trading=true`, `live_trading_enabled=false`, `kill_switch=true`;
- the platform bind address remains loopback;
- the gateway remains `read_status=available`, connected, and advertises the
  manifest-required boolean feature inventory;
- `session_api_available=true`; the dark profile additionally requires
  `chat_write_ready=false`;
- the local profile requires ready command-ledger, workflow-binding, and
  session-registry authorities and the exact canonical 26-key health ledger;
  admission/candidate/connector/release identities, digests, liveness age and
  release cursor must have bounded types and internally consistent states—the
  watcher observes these facts but never changes them;
- the session-list response remains the bounded read model;
- a stale or unsupervised Hermes launchd service definition is incompatible.
- native Hermes `contract_version` meets the manifest minimum;
- every required durable capability is `supported=true`, `grounded=true`, and
  carries the exact `store.transactional_probe:<capability>` evidence;
- `managed_run_sessions=true`, history authority is
  `hermes_session_db`, and fork mode is
  `preserve_source_exact_message_cursor`;
- advertised HTTP method/path pairs cover Run submit/status/events/approval/
  stop plus Session create/get/messages/exact fork. The watcher observes these
  advertisements; it never calls the POST routes.

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
changed identity prints one small JSON status line. Exit codes are fixed:

- `0`: compatible, unchanged compatible baseline, or another check owns the lock;
- `2`: invalid CLI usage;
- `3`: observed contract/readiness drift (`incompatible`);
- `4`: watcher/configuration/evidence collection unavailable.

Incompatibility preserves the previous compatible baseline and is retried at
the next cron tick until a compatible check succeeds.

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

   Or invoke the exact no-agent CLI from an HQA checkout:

   ```bash
   python3 -m hqa.hermes_compatibility_cli check \
     --no-agent \
     --profile local_agent_v0_2 \
     --platform-root /Users/sunyibo/programs/ai-quant-platform
   ```

6. Require a new `compatible` local-Agent report before treating the observed
   runtime contract as compatible at that point in time. This is not source
   attestation and does not itself authorize public composer submission,
   worker claim/dispatch, or any trading path.
