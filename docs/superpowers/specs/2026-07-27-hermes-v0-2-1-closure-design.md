# Hermes v0.2.1 Closure Design

**Status:** normative implementation specification  
**Scope:** v0.2.1 closure only  
**Operating mode:** local, single operator, research and paper simulation only  
**Standing safety state:** global `kill_switch=true`, `live_trading_enabled=false`, public write standing default OFF, `release_authorized=false`

## 1. Purpose, authority, and outcome

Hermes v0.2.1 is a finite closure release. It preserves every recoverable source of current work, restores unambiguous repository authority, integrates only reviewed changes into clean branches, rebuilds reproducible environments, verifies the release from committed bytes, and emits one detached, content-addressed closure-evidence package.

This document governs closure of the current v0.2 release line. It does not implement v0.3 contracts, retire legacy routes, open public mutation, authorize live trading, or convert historical test results into current evidence. v0.3 implementation may begin only after this contract produces `verdict.json` with `verdict="CLOSED"`.

The closure result is exactly one of:

- `CLOSED`: every mandatory gate passed against exact clean, committed revisions; all mandatory evidence is present; the detached seal verifies; no admissible P0/P1 blocker remains.
- `BLOCKED`: at least one mandatory gate failed, remained unknown, or could not be bound to exact authority and committed bytes.
- `ABORTED_RECOVERABLE`: implementation stopped under a finite stop rule before closure and verified recovery packages can restore every touched checkout.

There is no partial release state. Elapsed effort, source presence, historical acceptance, a green subset, a successful paper effect, or a written plan cannot imply `CLOSED`.

## 2. Binding safety model and non-goals

### 2.1 Three distinct switch identities

The implementation must keep these facts separate in schemas, evidence, logs, and acceptance decisions:

1. **Global process safety switch:** Platform configuration such as `QS_KILL_SWITCH`, observed as global `kill_switch=true`. Repository defaults and HQA safety expectations require this value to remain true.
2. **Paper-account-local switch:** `PaperAccount.kill_switch`, owned by one disposable paper account. It may block mutations within that account independently of the global switch.
3. **Replay request option:** request field `enable_kill_switch`, which configures replay behavior. It is not either standing switch and cannot prove the global or account-local state.

No evidence field named only `kill_switch` is sufficient where more than one identity is in scope. Every switch observation must carry `switch_scope` equal to `global_process`, `paper_account`, or `replay_request`, plus its exact authority reference.

### 2.2 Standing state

All mandatory closure work occurs with:

- global `kill_switch=true`;
- `live_trading_enabled=false`;
- `release_authorized=false`;
- public/browser/chat write standing default OFF;
- no live broker order submission, cancellation, replacement, account unlock, wallet operation, or live execution;
- no automatic Gate 1, Gate 2, Gate 3, candidate registration, promotion, Git commit, merge, push, migration apply, service restart, paper mutation, or release act.

The mandatory operational exercise in Section 9 is a **zero-effect blocked/replay proof**. It must retain global `kill_switch=true` throughout. It may demonstrate an attempted operation being blocked and a same-identity replay returning the same zero-effect outcome, but it must not create an order or mutate a paper account.

A one-effect disposable-paper-account exercise is optional. It requires separate written authorization, is not a prerequisite for `CLOSED`, uses only an explicitly bound paper-account-local switch transition, and never changes the global switch or `live_trading_enabled`. Its absence, denial, or deliberate omission cannot block `CLOSED`.

### 2.3 Non-goals

v0.2.1 does not:

- enable a public, browser, chat, or standing write surface;
- enable live trading or alter live broker configuration;
- authorize release, Gate review, candidate registration, or promotion;
- retire Agent Studio, Factor Lab, Experiments, or Backtester;
- change global `legacyRedirects=false`;
- implement any v0.3 progress, budget, or comparison contract;
- rewrite Git history, force-push, delete remote artifacts, or erase unreconciled work;
- refresh dependencies merely because a lock or install is inconvenient;
- treat paths, branch names, `latest`, local remotes, or dirty worktrees as artifact identity.

## 3. Repository authority and immutable binding

### 3.1 Canonical repository identities

Every closure record, command record, environment record, test result, runtime result, review, and verdict must bind all four values: canonical publication URL, absolute checkout path, full commit ID, and Git tree ID.

| Repository | Canonical publication URL | Authoritative release checkout | Release branch | Published baseline |
|---|---|---|---|---|
| HQA | `https://github.com/YIBOWAY/hermes-quant-agent.git` | `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/Hermes-quant-agent` | `codex/agent-v0-2-release` | `a5589ba0626e76bc99b55bd1a126d578196c51f4` |
| Platform | `https://github.com/YIBOWAY/ai-quant-platform.git` | `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform` | `codex/agent-v0-2-release` | `e19087e1580a21ccc9160bc664167972e322021c` |

The release checkouts currently name the canonical publication remote `github` and use a local-path `origin`. Therefore `github` is the publication authority in those checkouts. A local-path remote is never publication evidence.

The Platform release-checkout commit `f61deffc00028c8f49218b61984a0db7ca667b39`, the range from the published Platform baseline to that commit, candidate UI commits `6335b0d81f4b2631ad88a2727be5e25771f09574`, `df6cca9b4313350b3e4add4f1956207a91a5f2ec`, and `96785ae3a7ba35c6a2a0a371b07b927ab35735b3`, dirty overlays, primary clones, stale worktrees, remediation branches, and conflict stages are review inputs only. None is implicitly accepted.

### 3.2 Required repository binding record

Each final repository entry in `repositories.json` is a closed object with:

- `repository_id`: `hqa` or `platform`;
- `publication_url`: exact canonical URL from Section 3.1;
- `publication_remote_name`;
- `publication_ref`: exact `refs/heads/codex/agent-v0-2-release`;
- `absolute_checkout_path`;
- `branch`;
- `base_commit`;
- `final_commit`;
- `tree_id`;
- `archive_sha256`: SHA-256 of a bounded `git archive` of `final_commit`;
- `remote_head_commit`;
- `base_is_ancestor`;
- `remote_published`;
- `working_tree_clean`;
- `hidden_index_paths`: empty;
- `captured_at`.

`CLOSED` requires, for both repositories:

- the checkout root equals the recorded absolute path;
- publication URL matches exactly after credential-free URL normalization;
- branch and publication ref match;
- `final_commit` is a descendant of `base_commit`;
- local `HEAD`, tree, archive digest, and remote head agree with the record;
- no tracked, untracked, conflicted, assume-unchanged, or skip-worktree residue exists;
- evidence capture observes no identity change during capture.

A path alone, a local clone name, an abbreviated commit, a branch tip without a fetched full commit, or an archive without repository URL binding is insufficient.

### 3.3 Current-state qualification

The identities and dirty states stated above are verified design inputs, not closure results. The implementation must re-observe them before the first state-changing action and again at final sealing. Any drift updates evidence and is evaluated by this contract; it is not silently normalized.

## 4. Preservation contract before state change

No cherry-pick abort, reset, branch switch, remote change, dependency-link replacement, conflict resolution, clean, checkout deletion, worktree removal, migration apply, install, or restart may occur before the affected checkout has a verified preservation package and restore receipt.

### 4.1 Recovery package

Each checkout receives a restricted package outside every Git worktree:

```text
<evidence-root>/recovery/<timestamp>/<repository-id>/<checkout-id>/
  identity.json
  refs.txt
  pseudo-refs.txt
  status-v2-z.bin
  index.bin
  index-stages.txt
  staged.patch
  unstaged.patch
  untracked.tar
  worktree-list.txt
  submodules.txt
  bundle.bundle
  recovery-files.json
  restore-receipt.json
```

The evidence root is mode `0700`; regular files are mode `0600`. `identity.json` records repository ID, publication URL, absolute checkout path, branch, HEAD, upstream, object format, Git version, capture time, operator identity, and every deliberate exclusion from `untracked.tar`.

The package preserves all refs and pseudo-refs, exact index bytes and conflict stages, binary-capable staged and unstaged patches, bounded untracked content, worktree/submodule state, and a Git bundle containing every referenced reachable commit required for restoration.

`recovery-files.json` lists every regular recovery artifact other than itself only if its own digest is supplied by the enclosing closure manifest. It must not claim a recursive self-digest.

### 4.2 Secret-shaped residue

The modified primary-HQA `tests/test_quant_cli.py` is handled without displaying suspect bytes.

- Compute only a non-printing fingerprint, length class, and structural scanner classification.
- Determine plausible validity from credential ownership records; do not attempt authentication.
- If validity is plausible or ownership is unknown, rotate or revoke through the credential owner before cleanup.
- Preserve exact pre-cleanup bytes only in the restricted recovery package.
- Exclude the bytes from ordinary patches, logs, issue text, release evidence, and command output.
- Verify absence from every final checkout and newly generated artifact with non-printing match-count/fingerprint tooling.
- If committed or remote history contains the value, stop. History rewriting and remote cleanup require a separate destructive-action design and explicit user authorization.

### 4.3 Restore drill

Before touching a source checkout, restore its package into a disposable directory on the same filesystem class and:

1. Restore recorded commits, refs, tags, and pseudo-ref targets from `bundle.bundle`.
2. Restore exact index bytes without resolving conflicts.
3. Restore tracked and untracked worktree bytes.
4. Recompute HEAD, refs, index stages, porcelain-v2 status, tracked hashes, and untracked archive inventory.
5. Compare every field to the captured package.
6. Rehearse the next state-changing operation only in the disposable restore.
7. Restore again and repeat the comparison.

`restore-receipt.json` records compared fields, digests, exits, mismatches, and `restore_verified`. The source checkout may be changed only when `restore_verified=true`. A new immutable identity snapshot follows every state-changing source-checkout operation.

## 5. Integration and update rules

### 5.1 Clean integration branches

Create fresh integration branches from the exact published baselines in the authoritative release checkouts after preservation succeeds. Do not branch from a conflicted checkout, dirty index, stale worktree, or primary clone merely because it contains desired changes.

Every imported unit records:

- source publication URL and absolute checkout path;
- source full commit or recovery artifact digest;
- reviewed diff digest;
- destination baseline, commit, and tree;
- conflict-resolution note;
- covering tests;
- disposition: `required`, `excluded`, `superseded`, or `deferred`.

Dirty overlays are ported file-by-file or hunk-by-hunk after review. They are never committed wholesale to manufacture cleanliness.

### 5.2 Frontend candidate series

Review the three candidate UI commits in their recorded order. Replay them only if every commit remains compatible with the final Platform architecture and wire contract without resurrecting removed components or reverting later authority work. Otherwise selectively port the minimum accepted behavior and tests, preserving source provenance.

The finite frontend issue set contains only:

- defects demonstrated by candidate tests;
- final wire-contract conflicts;
- regressions against approved D-31/F2 layout, accessibility, responsive, state, or safety boundaries;
- integration-caused build, lint, type, API-type, unit, or Playwright failures.

Unrelated visual refinement is backlog and cannot extend closure.

### 5.3 Update identity

Update discovery in the release checkouts uses the `github` remote only after its normalized URL equals the corresponding canonical publication URL. Update checks fail closed on dirty/conflicted state, unbound detached HEAD, absent expected branch, URL mismatch, TLS or credential failure, unresolved fetched identity, or any implicit merge, rebase, reset, install, restart, or gate change.

An update check reports drift only. Fetch, integration, install, restart, push, and release remain separate operator actions with their own authority.

## 6. Reproducible environments

### 6.1 HQA

Create a new isolated Python environment inside the exact clean HQA final checkout and install from that checkout's declared metadata. Acceptance requires:

- recorded interpreter and `sys.executable` inside the environment;
- `import hqa` resolving inside the exact final checkout;
- distribution and dependency inventory;
- no `PYTHONPATH`, editable link, `.pth`, or symlink to another clone;
- installer exit and input metadata digests.

The final environment command is discovered under Section 7. This design does not invent an environment-creation command absent from repository authority.

### 6.2 Platform backend

Create a new Python 3.11 environment in the exact clean Platform final checkout. Installation consumes its committed `uv.lock` and `pyproject.toml`. Record interpreter, `quant_system` import path, dependency inventory, lock digest, and installer exit. PostgreSQL tests use a disposable, visibly temporary database and never the operator's canonical database.

### 6.3 Platform frontend

Run `npm ci` in the exact final `src/frontend` directory against the committed `package-lock.json`. Active source must not use another checkout's `node_modules` symlink. Record Node/npm versions, lock digest, install exit, and resolved checkout path. A required lockfile modification blocks closure; it does not authorize a dependency refresh.

## 7. Canonical command discovery

A command becomes closure authority only when discovered against the exact final commit in this precedence order:

1. Version-controlled CI workflow or executable verification script.
2. Package-manager script, manifest, lockfile, or declared entry point.
3. Current repository README or runbook matching the same checkout and platform.
4. Historical audit only as a locator to a current executable surface.

If higher-precedence sources disagree, resolve the repository contract before testing. Do not compose a new command from fragments.

Each command record contains repository URL, absolute checkout, branch, commit, tree, clean-tree digest, source file/field, working directory, exact argv, environment-variable names, runtime versions, dependency/lock digests, expected exits, declared skips, output locations, side-effect classification, and whether it may touch network, database, runtime, paper state, or generated files.

Unknown commands are first executed in a disposable restored clone with mutable-state and network observations. A command that unexpectedly writes outside the checkout, contacts a provider, changes safety/release state, or mutates canonical runtime data is rejected as a release command.

Verified command surfaces include HQA `./.venv/bin/pytest` and `bash scripts/install.sh`; Platform `python -m pytest -q`, `ruff check src/quant_system tests`, and `quant-system doctor`; frontend `npm ci`, `lint`, `type-check`, `test`, `build`, and `check:api-types`; and backend health at `http://127.0.0.1:8765/api/health`. These names are locators, not current pass claims. Exact final commands and fresh exits must be rediscovered and captured.

## 8. Mandatory verification gates

Every result binds the exact command record, start/end time, exit, stdout/stderr digest, artifacts, repository URL/path/commit/tree, environment identity, and clean status before and after.

### 8.1 Static, hermetic, and recovery gates

Mandatory gates are:

1. Complete HQA test suite.
2. Complete Platform non-PostgreSQL backend suite.
3. Disposable-PostgreSQL suite covering migration, authority, claim/dispatch, approval, stop, release boundaries, replay, and restore.
4. Repository-defined Python lint, type, and static checks.
5. Frontend `lint`, `type-check`, `test`, `build`, and `check:api-types`.
6. Focused safety tests for all three switch identities, live disable, release authorization, public-write defaults, Gate separation, exact approval/stop binding, idempotency, recovery, and absence of live-order dependencies.
7. Clean installation and published-baseline-to-final upgrade rehearsal in independent environments, followed by import and CLI smoke.
8. Backup/restore and restart recovery from exact committed bytes.
9. The mandatory zero-effect operational proof in Section 9.1.
10. Independent code/security review and adversarial verification under Section 11.

Unexpected skips block closure. Expected skips must be declared by repository authority and justified in evidence. Provider/network tests remain excluded unless separately authorized; exclusion is not a pass.

### 8.2 Frontend and browser gates

Playwright uses isolated ports and an isolated runtime/data root. It covers `/hermes` idle and active states; multi-turn refresh/reconnect; exact-message fork and historical read-only behavior; stop, approval, Gate, result, and degraded/unavailable projections without authority invention; deep links, query strings, and English/Chinese locale behavior; viewports `1440x900`, `1280x800`, `768x1024`, and `390x844`; long text and identifiers; loading, empty, error, partial, and terminal states; semantic regions; keyboard and focus behavior; WCAG AA contrast; 44px touch targets; reduced motion; non-color status; no console errors; no streaming-scroll hijack; and no overlaps or clipped controls.

Snapshots are reviewed, never blindly updated. Global `legacyRedirects=false` is asserted, and every legacy route remains directly reachable.

### 8.3 Runtime and health gates

For each relevant restart:

1. Capture pre-restart process, source, install stamp, environment, port, schema, and safety identity.
2. Restart only with the separately authorized, discovered canonical command.
3. Query fresh health; cached output is invalid.
4. Verify process executable, loaded module path, commit/archive digest, schema fingerprint, connector generation/heartbeat, and loopback bindings.
5. Reassert global `kill_switch=true`, `live_trading_enabled=false`, public write OFF, and `release_authorized=false`.
6. Verify an empty queue causes zero provider work.

A source/install/process mismatch, stale health, unknown schema, non-loopback exposure, or safety drift blocks closure.

## 9. Operational safety exercises

### 9.1 Mandatory zero-effect blocked/replay proof

This proof is mandatory and may block `CLOSED`. It must use a disposable runtime/data root or hermetic paper authority. It is not a one-effect order exercise.

The preflight binds:

- exact HQA and Platform repository URL/path/commit/tree and runtime digests;
- exact simulation-only adapter and disposable account/reference;
- global switch authority and observed `true` value;
- paper-account-local switch authority and its observed value;
- replay request `enable_kill_switch` value, if the route accepts it;
- `live_trading_enabled=false`, public write OFF, and `release_authorized=false`;
- exact operation/idempotency identity and request digest;
- dependency spies proving no Futu trade context, live broker adapter, account unlock, or fallback is configured;
- expected closed error/outcome and zero-effect counters.

Execution must:

1. Keep global `kill_switch=true` before, during, and after the proof.
2. Submit one bounded simulation-only operation expected to be blocked before any effect.
3. Observe the repository-defined blocked result and prove zero orders, fills, cash changes, position changes, broker calls, trade-context creation, account unlocks, and external dispatches.
4. Replay with the same idempotency identity and exact request bytes.
5. Observe the same authoritative zero-effect receipt or defined idempotent replay result, with no second command/effect.
6. Submit no different-identity retry after ambiguity; reconcile the original identity only.
7. Capture preflight, first receipt, replay receipt, account/ledger before-and-after digests, dependency-spy counts, and postflight switch observations.

Acceptance requires a reconciled blocked/replay outcome, all effect counters equal zero, and unchanged safety/release facts. A route that can reach a live adapter, requires lowering the global switch, cannot distinguish the three switch identities, or cannot prove zero effect fails the mandatory gate.

### 9.2 Optional one-effect disposable paper-account exercise

This exercise is optional and cannot block `CLOSED`. It may run only after all mandatory gates are green and only with a separate authorization artifact whose digest is recorded. The authorization must name the exact final commits, disposable paper account, one bounded order/replay request, maximum notional, finite window, operator, cleanup, and the account-local switch transition.

Constraints:

- global `kill_switch=true` remains unchanged;
- `live_trading_enabled=false`, public write OFF, and `release_authorized=false` remain unchanged;
- only the disposable paper account's local switch may transition `true -> false -> true`;
- the transition occurs immediately before and after the one-shot window and is journaled by exact account ID and snapshot digest;
- replay request `enable_kill_switch` is bound independently and cannot stand in for either switch;
- exactly one simulation effect is permitted;
- no automatic retry occurs; ambiguity becomes `outcome_unknown` and reconciliation uses the original identity;
- dependency spies and runtime audit prove zero live broker calls, zero trade contexts, and zero account unlocks;
- postflight restoration of the account-local switch to true is mandatory even when the effect fails.

Failure of an authorized optional exercise records `optional_paper_exercise="failed"` and may create a separate safety blocker if it reveals an admissible mandatory defect. The optional exercise's absence or a failure confined to optional effect mechanics does not by itself change an otherwise valid `CLOSED` verdict.

## 10. Closure evidence and detached seal

### 10.1 Evidence layout

The final evidence root is outside mutable runtime/data directories and mode `0700`:

```text
v0.2.1-closure/
  manifest.json
  repositories.json
  recovery/
  environments/
  commands/
  tests/
  frontend/
  runtime/
  operational-proof/
  optional-paper-exercise/
  security/
  reviews/
  verdict.json
  manifest.sha256
```

`manifest.json` binds design digest; canonical repository URL/path/branch/commit/tree/archive identities; publication remotes; recovery and restore receipts; environments and locks; every command and result; frontend/browser evidence; runtime/process/install/schema/health identities; mandatory zero-effect proof; optional exercise status if any; secret-cleanup fingerprints and absence counts; reviews and dispositions; standing safety facts; `release_authorized=false`; and final verdict.

All JSON is canonical UTF-8 with sorted keys, compact separators, duplicate-key rejection, and no NaN or Infinity. Evidence contains no secrets, prompts, provider bodies, unrestricted tool output, account credentials, or quarantined suspect bytes.

### 10.2 Detached `manifest.sha256` semantics

`manifest.sha256` is a detached root and **must exclude itself** from its covered-file set. It covers every other regular file under `v0.2.1-closure/`, recursively, including `manifest.json` and `verdict.json`.

Generation is defined exactly:

1. Walk the evidence root without following symlinks.
2. Reject every symlink, hard-linked file with link count other than one, device, socket, FIFO, directory escape, absolute member name, backslash, `.`/`..` component, non-UTF-8 relative path, carriage return, or newline in a path.
3. Select regular files only, excluding the root-relative path exactly `manifest.sha256`.
4. Convert each relative path to normalized POSIX form.
5. Sort entries by raw UTF-8 bytes of the normalized relative path in ascending order.
6. Compute SHA-256 over each file's exact bytes after all writers are closed and before the package is moved or published.
7. Emit one ASCII line per file with exact grammar:

```text
<64 lowercase hex SHA-256><two U+0020 spaces><normalized relative POSIX path><U+000A newline>
```

The file is nonempty, has no BOM, uses LF only, has exactly two spaces after the digest, contains no blank lines, duplicate paths, size field, comments, header, footer, or self-entry, and ends with exactly one LF as part of its final record.

Verification parses this grammar strictly, independently enumerates the covered tree with the same safety rules, and requires exact set equality. It rejects missing, extra, renamed, duplicated, unsafe, unreadable, non-regular, digest-mismatched, or post-enumeration-changed files. It also rejects any `manifest.sha256` entry that attempts to cover `manifest.sha256`.

`manifest.json` may record byte sizes and semantic metadata. Size is deliberately not part of the detached line grammar; exact bytes are committed by SHA-256 and file-set equality. A separate transport signature may cover the exact bytes of `manifest.sha256`, but no signature is required to call the hash root detached.

### 10.3 Verdict schema and closure predicate

`verdict.json` is a closed object containing:

- `schema_version: "hermes.v0.2.1-closure-verdict.v1"`;
- `verdict: "CLOSED"|"BLOCKED"|"ABORTED_RECOVERABLE"`;
- exact design digest;
- exact final HQA and Platform publication URL/path/commit/tree bindings;
- one boolean and evidence reference for every mandatory gate;
- `mandatory_zero_effect_proof_passed`;
- `optional_paper_exercise: "not_authorized"|"not_run"|"passed"|"failed"`;
- `p0_open`, `p1_open`, and admissible blocking P2 findings;
- `evidence_complete`;
- `detached_manifest_verified`;
- standing safety values;
- `release_authorized:false`;
- `decided_at` and decision authority.

`CLOSED` is legal if and only if:

- every mandatory gate boolean is true;
- both final repositories satisfy Section 3.2 and are clean;
- all mandatory evidence references resolve inside the sealed tree;
- the detached manifest verifies by exact set equality;
- `p0_open=0` and `p1_open=0`;
- no blocking P2 remains;
- global `kill_switch=true`, `live_trading_enabled=false`, public write OFF, and `release_authorized=false` are freshly observed;
- the optional-paper-exercise value is ignored by the closure predicate.

A docs-only commit after sealing changes repository identity and invalidates the seal. Normative documents must be final before commit-bound gates and final evidence generation.

## 11. Independent review and finite closure

Closure permits one primary implementation pass, one independent review, and one adversarial verification pass.

Severity rules:

- P0/P1 findings block and must reach zero.
- P2 blocks only when it violates an explicit mandatory gate or demonstrates a reproducible high-probability operational failure.
- P3, aesthetic refinement, nonfunctional cleanup, and speculative hardening enter backlog.

A finding is admissible only with a concrete failure scenario, exact affected code/evidence reference, and direct evidence. Rewordings, preferences, historical concerns disproved on the final commit, optional-paper-only shortcomings, and issues outside the finite integration set do not reopen closure.

Finite stop rules are:

1. After the primary pass, review, and adversarial pass, two consecutive complete passes with no new admissible P0/P1 end defect discovery and require a verdict.
2. If the same mandatory gate fails twice for the same root cause after one bounded repair, issue `BLOCKED`; do not continue speculative fixes.
3. If preservation or restore fails twice, issue `ABORTED_RECOVERABLE` and do not touch the source checkout.
4. If repository URL/path/commit/tree, publication remote, or ancestry cannot be proven, issue `BLOCKED`.
5. If suspected secret remediation requires history rewrite or remote destructive cleanup, quarantine and rotate/revoke as applicable, record separate authorization work, and do not expand v0.2.1.
6. If the mandatory operational proof cannot preserve global `kill_switch=true`, distinguish all switch identities, prove simulation-only routing, or prove zero effect, issue `BLOCKED`.
7. If any safety flag drifts, a live-capable call occurs, or public/release authorization opens unexpectedly, preserve evidence, use only an already-known canonical stop operation, and issue `BLOCKED`.
8. If a new requirement is unnecessary for a mandatory gate, backlog it and continue toward the finite verdict.
9. Optional one-effect paper authorization, execution, repair, or success may not delay an otherwise complete closure verdict.

Closure is complete when one of the three verdicts is sealed. `BLOCKED` and `ABORTED_RECOVERABLE` are terminal for this closure attempt; later work begins a new attempt with new evidence identity rather than mutating the sealed verdict.

## 12. Implementation planning boundary

Implementation planning must produce a file-level, command-level sequence for preservation, restore drills, clean integration, environment construction, canonical command discovery, mandatory verification, runtime checks, the zero-effect operational proof, independent review, and detached sealing.

The plan may fill in only commands discovered from the final repository state under Section 7. It may not weaken safety, replace immutable repository binding with paths or `latest`, reuse historical exits, invent commands, silently update dependencies, rewrite history, apply live migrations, restart services, run the optional one-effect exercise, push, or release without the relevant explicit operator authorization.

v0.3 contract design and implementation remain separate work after a sealed `CLOSED` verdict.
