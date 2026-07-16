### Task 4: Independent review and next-plan decision record

**Files:**

- Create: <code>config/hermes-gateway-capabilities.v1.review.json</code>
- Modify: <code>docs/contracts/hermes-gateway-0.18.2.md</code>

**Interfaces:**

- Consumes: Tasks 1-3 and current installed Hermes source.
- Produces: a human-readable review verdict and a strict Git-bound machine record. The current verdict is blocked and does not enable chat.

- [ ] **Step 1: Request two-stage review**

First run <code>git status --short</code> and retain the exact pre-existing worktree baseline in the review notes; do not clean, stage, revert, or reinterpret any baseline entry.

Stage A uses <code>superpowers:requesting-code-review</code> for plan/spec compliance. Stage B invokes the user's professional <code>[@Code Reviewer](subagent://Code Reviewer)</code> against the committed Task-3 code and evidence, without sharing Stage A's conclusion. Both reviewers must independently return no unresolved P0/P1 before the review record is written. Require both to verify:

~~~text
1. Every true capability is supported by an exact Hermes source/help reference.
2. No missing capability is inferred from UI behavior.
3. verify-chat cannot become ready merely because method names exist or a stale
   snapshot was once ready.
4. session.resume is not classified as read; bridge admission requires both
   safe submit recovery and replayable stream identity.
5. Endpoint parsing rejects credentials, query/fragment data, wrong paths,
   non-loopback hosts and invalid ports without reflecting secret text.
6. A custom contract, missing/mismatched review record, uncommitted review edit,
   tracked Hermes source change, or installation drift closes the effective gate.
7. Approval and stop stay independently closed without blocking otherwise-safe
   ordinary chat.
8. No secret, profile credential, state.db content, transcript, or provider token
   is checked into the contract.
9. No test invokes Grok, Codex, prompt.submit, session.create, session.resume,
   paper, or live paths.
10. relevant_methods_observed is explicitly an allowlisted subset, not a claim
    to freeze the complete server registry.
11. Primary-provider/model immutability, fallback-policy immutability, and the
    complete per-Run requested/actual/fallback/usage evidence are proved
    separately; targeted source searches support every false value.
~~~

- [ ] **Step 2: Capture immutable review inputs**

Run these commands separately and retain their verbatim output:

~~~bash
git rev-parse HEAD
shasum -a 256 config/hermes-gateway-capabilities.v1.json
date -u +%Y-%m-%dT%H:%M:%SZ
~~~

The HEAD value is the reviewed Task-3 commit. Confirm <code>git show &lt;reviewed-commit&gt;:config/hermes-gateway-capabilities.v1.json</code> is byte-identical to the working file. Do not review an uncommitted contract.

- [ ] **Step 3: Write both review records**

With <code>apply_patch</code>, append an <code>Independent review</code> section to the evidence document whose timestamp, contract digest, and <code>Commit reviewed</code> values are the verbatim command outputs. For the frozen 0.18.2 snapshot, record <code>Verdict: BLOCKED</code> and this exact reason: <code>current Hermes contract lacks deterministic request recovery, replayable event identity, Run identity, immutable provider/fallback policy and actual-provider evidence.</code>

Create <code>config/hermes-gateway-capabilities.v1.review.json</code> with no placeholders left:

~~~json
{
  "schema_version": "1.0",
  "contract_sha256": "<64-character shasum output>",
  "reviewed_commit": "<40-character git rev-parse output>",
  "reviewed_at": "<UTC timestamp output>",
  "verdict": "blocked",
  "reason": "current Hermes contract lacks deterministic request recovery, replayable event identity, Run identity, immutable provider/fallback policy and actual-provider evidence."
}
~~~

Change <code>verdict</code> to <code>ready</code> only in a later independent-review commit when newly cited source evidence changes the checked-in contract, every required capability is true, the review digest/commit checks pass, and <code>verify-chat</code> would otherwise pass the live installation gate. A local uncommitted edit is never sufficient.

- [ ] **Step 4: Verify the uncommitted record is not trusted**

Run:

~~~bash
./.venv/bin/python -m hqa.hermes_capability_cli verify-chat
git diff --check
git status --short
~~~

Expected: exit 3 and <code>contract_unreviewed</code> is still present because the review record is not yet part of HEAD. Relative to the recorded Step-1 baseline, only the intended review document and JSON record are new modifications. Pre-existing dirty/untracked files remain byte-identical and must not be removed.

- [ ] **Step 5: Commit the review record**

~~~bash
git add config/hermes-gateway-capabilities.v1.review.json \
  docs/contracts/hermes-gateway-0.18.2.md
git commit -m "docs(review): confirm Hermes chat remains fail closed"
~~~

- [ ] **Step 6: Verify the committed blocked verdict**

Run:

~~~bash
./.venv/bin/pytest -q tests/test_hermes_capabilities.py tests/test_hermes_capability_cli.py
./.venv/bin/python -m hqa.hermes_capability_cli show
./.venv/bin/python -m hqa.hermes_capability_cli verify-chat
git diff --check
git status --short
~~~

Expected: tests pass; <code>show</code> reports a trusted <code>review.verdict=blocked</code>, matching installation, and effective read access for list/status/history; <code>verify-chat</code> exits 3 with the five current capability blockers plus <code>contract_review_blocked</code>. Resume/chat/stream/approval/stop remain false. No Hermes session or provider usage appears.

## Completion criteria

- The installed gateway facts are machine-readable and reproducible without a provider call.
- Unknown schema, non-loopback endpoint, or malformed evidence fails closed.
- The current 0.18.2 contract exposes only list/status/history reads; resume/chat/stream/approval/stop remain closed.
- The current blocker is visible in <code>docs/README.md</code>.
- No BFF, database migration, browser mutation, session creation, model call, paper path, or live path was added.
- The plan explicitly leaves runtime process identity/handshake to the later bridge slice; it does not confuse a clean matching checkout with a verified running server.
- A later bridge plan cannot claim admission until a fresh source-backed contract and committed independent <code>ready</code> review make <code>verify-chat</code> exit 0 against a clean matching installation.
