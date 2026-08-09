# Hermes-quant-agent

Hermes orchestration layer for the local `ai-quant-platform`. Phase 1a-4/9H is
complete; current D-32 work targets a real Agent v0.2 with complete `/hermes`
Web Chat while preserving read-only / proposal-only and never touching the trading
chain:

## Normal local operation

The 2026-08-09 Mac runtime is persistent and project-owned: Docker PostgreSQL
plus Hermes, Platform backend/frontend, and the HQA connector run under user
LaunchAgents. Start or inspect it from the Platform runtime checkout:

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform
bash scripts/local_mac_stack.sh start
bash scripts/local_mac_stack.sh status
```

Hermes official source is pinned at `2446c8bb6755`; the live integration is
`codex/v2-live-integration@a4bac87463fd` (including bounded macOS cold-start
socket-drain hardening). Use only
`~/.hermes/scripts/hqa-hermes-update.sh check|apply` for future updates. Local
trust reports `admission_mode=local_trust` without candidate identity; it
simplifies the single-user identity step only and does not relax
`live_trading_enabled=false`, `kill_switch=true`, migrations, human gates, or
public-release controls.

Start with [`docs/README.md`](docs/README.md): it separates the long-term HQA
roadmap, the current D-32 Agent v0.2 plan, and predecessor delivery records. The
`docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md` delivery record covers Slice 9A's paper-strategy
read model and explicit crash recovery, Slice 9B's unified paper snapshot,
Slice 9C's current-snapshot portfolio risk v1, Slice 9D's strict historical
price seam + risk v2, Slice 9E's prediction ledger, Slice 9F's proposal-only
market foresight, the mini 9H read-only Hermes artifact shelf, and Slice 9G's
auditable opportunity ledger. Full 9H adds the four-job
read-only automation loop, strict weekly/opportunity/freshness projections,
durable notification receipts, feed schema 1.1 and the visible `/hermes` cards.
D-31 has since delivered the official API GET-only session BFF (3A), PostgreSQL
command/event/outbox/run-link ledger with claim/lease/heartbeat primitives (3B),
and a deterministic connector notify/scan/expired-lease reconcile runtime (3C).
The runtime does not claim queued commands and remains reconcile-only. Agent v0.2
V2 now has an independently accepted and pushed durable Run/approval/provider-evidence
source candidate at Hermes integration `codex/v2-live-integration@2eb5fa27790f`.
It is not the live runtime: the 2026-07-19 process is upstream
`main@c0c76a471533` (PID `96807`, health `0.18.2`), while launchd and the install
stamp are stale, the stamp still names `916f5fbf5452`, and
`gateway/durable_runs.py` is absent. Durable runs, real Web submission,
claim/dispatch and approval mutations therefore remain OFF. Slice 3C.1 has a
code-accepted append-only Task/Attempt
authority, immutable content-addressed payloads, exact cross-authority bindings,
and reverse audit. Platform migration 006 has not been applied to the live database;
a later v0.2 review found its `UNIQUE(task_id)` incompatible with multi-Attempt
research. Because the current runner replays old SQL, the selected fix is to revise
the never-live 006 and redo its full evidence—not assume a later 007 can repair it—
before any live authorization.
Slice V0 (interface/cardinality/authority freeze) is source/formal **DONE**. The five
`hqa/agent_workspace_*` contract modules and exact three-repo source coordinates are
bound to a fail-closed runtime identity manifest, fresh JUnit evidence and an independent
`CLEAR` verdict in the
[`V0/V2 release closure audit`](docs/audits/2026-07-19-v0-v2-release-closure.md).
That verdict explicitly says `release_authorized=false`; the
[2026-07-17 cross-review](docs/audits/2026-07-17-v0-three-repo-cross-review.md) remains
historical evidence. All live write gates remain OFF.
V1's startup migration/DLP/schema-fingerprint baseline is code-accepted with fresh
platform full-suite and browser evidence; live DB role/RLS provisioning remains PARTIAL
(`quant` is still superuser/bypassrls and migration 006 is absent). V2 source is accepted
and pushed, but the live Hermes runtime is still upstream `main@c0c76a471533`, not the
candidate; Durable Run and every public write gate remain OFF. V3 is source-accepted and
locally installed in dark mode at HQA `121926388d86`: encrypted intent payloads,
multi-Attempt WorkflowAuthority, read-only Hermes research inspection and a unique local
`--no-agent` retention job are delivered. The current V3 acceptance is
[`docs/audits/2026-07-19-agent-v0-2-v3-acceptance.md`](docs/audits/2026-07-19-agent-v0-2-v3-acceptance.md).
This is internal infrastructure, not a usable `/hermes` composer. Hermes updates remain
operator-controlled and periodic/manual; the no-agent watcher reports drift but never
pulls, merges, installs, restarts or enables a gate. The upstream Hermes 40k full suite
is not an Agent v0.2 release gate.
This foundation is not yet an activated write path. The read-only Unified Results catalog and details are
delivered and locally accepted as 3E-A, while independent Hermes Run results and
full results cutover are not. Agent Studio has only a reversible page-scoped
redirect mechanism that defaults off; exact-bound audit parity, user cutover
approval, and retirement of all four legacy research pages remain open. The only
active implementation plan is [Agent v0.2 full `/hermes` Web Chat](docs/superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md);
the [Wave 3 plan](docs/superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md)
is a predecessor delivery record. Read both it and the accepted
[local Hermes integration decision](docs/design/2026-07-15-local-hermes-integration-decision.md)
for evidence before changing the bridge. Discord stays usable, but no temporary
web chat or fallback path is planned. The platform frontend plan is the Slice 0-8 delivery
record, not an executable queue. Platform Phase 15 is reference only.

- **Safety watchdog** (`hqa.doctor_watchdog`) — `[SILENT]`; JSON-first safety
  parse; splits `[INFRA]` (doctor/platform failure) vs `[SAFETY]` (baseline
  breach) so infra flaps no longer masquerade as kill-switch failures.
- **Pre-market digest** (`hqa.premarket_digest`) — daily summary of platform
  safety status, the latest collected Futu options-radar artifact, and AI HOT
  headlines with explicit degraded labels when sources are unavailable.
- **Review log** (`hqa.reviewlog`, `hqa.review_cli`) — append-only JSONL
  cognition store with Markdown rendering and human-filled confirmation fields.
- **Signal watchdog** (`hqa.signal_watchdog`) — consumes collected scan
  artifacts; loads `data/_runtime/signal_thresholds.json` (`min_score`, optional
  `min_iv_rank`) to exit permanent collect. Missing artifact sets
  `artifact_missing=true` in the log. Does not launch expensive Futu scans or
  `factor refresh-lab` by default (`--scan` / `--refresh-lab` opt-in).
- **Opportunity ledger** (`hqa.opportunities`, `hqa.opportunity_cli`) — folds
  structured `signal_records` into a locked append-only decision/action ledger.
  It validates exact platform signal/execution IDs through the pure
  `paper strategies observations` seam and records complete coverage watermarks
  before an eligible, expired action window can become `missed`. Current
  options-scan candidates remain `not_actionable` because the platform has no
  supported paper-options execution route. Use `hqa-opportunities.sh
  sync-signals|decide|record-action|sync-actions|reconcile|list`; symbol matching
  is forbidden and no command creates a signal, execution or trade.
- **Weekly review** (`hqa.weekly_review`) — emits a strict seven-day aggregate
  across safety, signals, reviews, prediction calibration and opportunity state;
  malformed sources degrade locally instead of breaking the whole projection.
- **Scene-B factor reproduction** (`hqa.factor_repro_cli`) — human-gated
  `propose|detail|approve|backtest|promote` flow covering the three human gates: factor
  formula confirm (exact reviewed source SHA-256 + non-empty note, persisted and
  bound to the resulting candidate manifest) → Gate 2 digest CAS approve
  (`--candidate-id` + `--expected-digest` + `--expected-status pending` +
  `--note`; never refetch and require the exact machine receipt) → successful
  content-addressed `--final` one-shot backtest receipt → Gate 3 HQA
  `promote --candidate-id --expected-digest --final-backtest-receipt --base-commit`
  Gate-1/backtest-revalidated isolated review worktree (human `git diff` + commit; never
  auto-commits). Raw platform review/promotion commands are generic primitives,
  not proof of the supported Scene-B provenance chain.
  The receipt accepts only Futu/Tiingo evidence and re-verifies the platform's
  persisted config, summary, exact generated report, unique experiment
  namespace rooted at the explicitly passed HQA artifact authority directory,
  and fixed one-run identity. Gate 3 additionally checks the actual
  three-file worktree, Git patch, and the platform's same-provenance status;
  timeouts remain an explicit unknown outcome with recovery evidence.
  Factor code is generated in the Hermes session, ingested via platform
  `agent propose-factor --source-file`, then backtested through the exact
  candidate ID + expected manifest digest path of
  `experiment run-config --provider futu` (futu
  is the only configured provider; tiingo is not set up). Candidates share the
  platform repo-anchored `data/agent_run/agent/candidates` root. Anti-overfit
  guardrails: per-factor trial counter (warns at 3rd run), 183-day holdout by
  default (`--final` runs the full window), and `hqa-gate` requiring
  `paper_days_completed >= 30` before broker-sim promotion.
- **Options radar summary** (`hqa.options_radar`) — daily structured summary
  for the latest collected Futu scan artifact; fresh Futu scans require
  explicit `--scan`.
- **Portfolio risk v2** (`hqa.portfolio_risk`) — consumes the unified paper
  snapshot once, writes one finite `logs/portfolio_risk.jsonl` artifact, and
  reports current long/short/gross/net exposure, gross-book concentration,
  account weights, valuation provenance, and repository degradation. Invested
  accounts also request strict Futu QFQ daily history through the platform
  `data prices` seam, globally align trading dates before returns, and report
  per-position beta versus SPY plus position-pair correlations. History failure
  degrades only that section and preserves current facts. It does not substitute
  sample/local/Tiingo/Longbridge data or calculate aggregate beta, VaR, FX,
  threshold verdicts, forecasts, or trading actions.
- **Prediction ledger** (`hqa.predictions`, `hqa.prediction_cli`) — records an
  explicitly stated US-equity direction forecast as a locked append-only JSONL
  event, anchors it to the latest completed Futu/QFQ session, and later scores
  the first actual session on or after the calendar horizon. Create and score
  are idempotent; concurrent IDs/scores use a local POSIX lock and CAS; torn or
  corrupt ledgers fail closed. The score is a declared-direction binary Brier,
  not a three-class probability score. There is no sample/local/Tiingo/
  Longbridge fallback and no account, strategy, backtest, or trading side
  effect. Use `hqa-prediction.sh create|list|reconcile`; full 9H now runs a
  bounded post-close reconcile but never creates predictions. Runtime data
  defaults to `predictions/`; override it with
  `HQA_PREDICTION_DIR` or `--prediction-dir` (use a temporary override for
  smoke tests rather than fabricating a formal prediction).
- **Market foresight** (`hqa.market_foresight`,
  `hqa.market_foresight_cli`) — validates a Hermes/user-authored US-equity
  thesis against the latest completed Futu/QFQ session and publishes an
  immutable proposal-only candidate. It never auto-creates a prediction or
  trading action. Use `hqa-market-foresight.sh propose|list`; changed intent
  under the same request ID fails closed.
- **Hermes artifact feed** (`hqa.hermes_artifacts`,
  `hqa.hermes_artifacts_cli`) — rebuilds or reads
  `artifacts/hermes-feed/manifest.v1.json`. Schema 1.1 adds weekly review,
  opportunity summary and per-job automation freshness to the original risk,
  prediction and market-foresight sources. The platform consumes it through the
  same read-only API; use `hqa-artifacts.sh refresh|show`.
- **Full 9H automation** (`hqa.research_automation`) — runs post-close,
  two-hour freshness, Sunday weekly and 15-minute notification-drain jobs through
  Hermes no-agent cron. Stable receipts, a non-blocking process lock and a
  private outbox make replays auditable. The default notification target is
  local; external delivery is not exercised by acceptance. No job generates a
  strategy, runs a backtest, mutates paper state, creates an execution or trades.

- **AI-HOT alerts** (`hqa.aihot_alerts`) — `[SILENT]` notable-news watchdog;
  prints only when score/category filters find something worth attention.

Slice 9G remains the decision/action fact source; full 9H only schedules its safe
read/reconcile interfaces and publishes aggregates. It adds no database table,
POST route, platform scheduler, execution path or trading permission.

Hermes-facing affordances (D-25): read-only platform queries run through
`scripts/hermes/hqa-quant-readonly.sh` (allowlist-gated; **no** full options
scan — those write snapshots and stay human-approved); `hqa-notify.sh` pushes
async completions to Discord with a local JSONL fallback; the `hqa-quant`
skill card gives Hermes artifact-first command templates and a >30s triage
convention. Machine-readable paper-account queries use the existing
`paper account-show --format json` command and the platform's unified snapshot
envelope; there is no second account command or JSON shape. After changing
wrappers/skill: `bash scripts/install.sh`. Historical price reads are allowed
only through the exact `data prices` leaf; `data ingest-*` remains refused.

Ops note (2026-07-09 audit): missing same-day scan meta surfaces as
`DEGRADED: no scan artifact for <date>` in premarket/options-radar digests
rather than silent empty options.

Logic lives in `hqa/` (Python 3.11+, stdlib-only runtime). Hermes cron runs thin wrappers
copied into `~/.hermes/scripts/` by `scripts/install.sh`.

The repository-authoritative published-baseline-to-final upgrade/import/CLI
smoke is:

```bash
upgrade_parent="$(mktemp -d /private/tmp/hqa-noneditable-upgrade.XXXXXX)"
scripts/verify_agent_v02_noneditable_upgrade.sh \
  --output-dir "$upgrade_parent/result"
```

Run it only from the canonical clean release branch after its exact `HEAD` is
published to the `github` remote-tracking ref. The command archives committed
bytes, denies network access, removes provider/trading credentials, keeps the
global kill switch on and live trading off, and writes a private 0700 evidence
root with 0600 command logs and receipt. The published baseline `a5589ba` has a
pytest-only `pyproject.toml`, no PEP 621 project metadata, and no `uv.lock`, so
the command builds a deterministic, explicitly labeled compatibility wheel
around those exact historical `hqa/` bytes. It then consumes the final
`pyproject.toml` and frozen lock offline, upgrades the same copy-based Python
3.11 environment to the final wheel, runs an isolated import and CLI help
smoke, and compares it with an independent fresh-final environment. Source-tree
imports, editable/direct-directory installs, `PYTHONPATH`, `.pth` files,
symlinked identity, URL/branch/commit/tree drift, non-descendant history,
unpublished `HEAD`, and dirty or hidden index state fail closed.

Run the fixed Round 1 Gate 6 focused-safety selector with
`scripts/verify_agent_v02_focused_safety.sh --python ABS --basetemp ABS
--hermes-live ABS --integration-worktree ABS --hermes-python ABS`, using a
release-local Python, a fresh basetemp outside the checkout, and the explicitly
bound owned Hermes root, clean `codex/agent-v0-2-release` integration worktree,
and Hermes Python. The wrapper accepts no other pytest arguments or selectors,
replaces the host environment with disabled-provider and fail-closed trading
rails, and requires private owner-controlled authority paths; only the final
Hermes Python entry may be a checked user-owned symlink.

Separately, build a clean, non-editable full-test environment from the exact current commit
(not from uncommitted working-tree bytes):

```bash
source_checkout="$(pwd -P)"
source_commit="$(git rev-parse HEAD)"
fresh_checkout="$(mktemp -d "$(dirname "$source_checkout")/hqa-committed.XXXXXX")"
git archive --format=tar "$source_commit" | tar -xf - -C "$fresh_checkout"
cd "$fresh_checkout"
env -u PYTHONHOME -u PYTHONPATH uv sync --frozen --extra dev --no-editable --python 3.11
env -u PYTHONHOME -u PYTHONPATH .venv/bin/python -I - <<'PY'
import importlib.metadata as metadata
import os
from pathlib import Path
import hqa

root = Path.cwd().resolve()
package = Path(hqa.__file__).resolve()
distribution = Path(
    metadata.distribution("hermes-quant-agent").locate_file("")
).resolve()
assert os.environ.get("PYTHONPATH") is None
assert root / ".venv" in package.parents
assert root / ".venv" in distribution.parents
print(package)
print(distribution)
PY
test_pycache="$fresh_checkout/.test-pycache"
env -u PYTHONHOME -u PYTHONPATH PYTHONPYCACHEPREFIX="$test_pycache" .venv/bin/python -X int_max_str_digits=0 -I -m pytest --import-mode=importlib
cd "$source_checkout"
rm -R "$fresh_checkout"
```

The committed `uv.lock` is the dependency authority. Runtime dependencies are
empty; the `dev` extra pins the verified test runner exactly. The test-only
`int_max_str_digits=0` setting lets the existing adversarial fixture serialize
its intentional 10,000-digit integer so application-level rejection is still
exercised on Python 3.11. `PYTHONPYCACHEPREFIX` keeps Python 3.11 subprocess
bytecode out of disposable Git fixtures, matching the clean-tree behavior of
the former macOS system-Python runner. Both settings are test-process-only and
are not runtime defaults.

Install/update Hermes script wrappers:

```bash
bash scripts/install.sh
```

Repository recovery packages and detached evidence roots are also repository
tools. Restore receipts intentionally live outside the package they validate,
so each receipt can bind the exact final `recovery-files.json` bytes without a
self-referential or stale pre-receipt digest:

```bash
python -m hqa.repository_recovery_cli capture \
  --repository /absolute/path/to/repository \
  --package /absolute/path/to/evidence/package
python -m hqa.repository_recovery_cli drill \
  --package /absolute/path/to/evidence/package \
  --destination /absolute/path/to/disposable/restore-1 \
  --receipt /absolute/path/to/evidence/receipts/restore-1.json
python -m hqa.repository_recovery_cli verify-receipt \
  --package /absolute/path/to/evidence/package \
  --receipt /absolute/path/to/evidence/receipts/restore-1.json
python -m hqa.repository_recovery_cli build-detached-manifest \
  --root /absolute/path/to/sealed-evidence-tree
python -m hqa.repository_recovery_cli verify-detached-manifest \
  --root /absolute/path/to/sealed-evidence-tree
```

Run two independent `drill` destinations/receipts before relying on a package.
The tools reject existing destinations, symlinks, hard-linked or special
artifacts, path escapes, non-canonical indexes, file-set drift, and digest
changes. A detached `manifest.sha256` covers every other regular file under its
root and never covers itself.

See `docs/README.md` first, then
`docs/design/2026-07-01-roadmap-phases-0b-4.md` for product decisions and
`docs/design/hermes_quant_agent_plan.md` for the original system design.
