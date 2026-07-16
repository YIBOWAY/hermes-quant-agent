### Task 3: Reproducible evidence and bridge-plan admission gate

**Files:**

- Create: <code>docs/contracts/hermes-gateway-0.18.2.md</code>
- Modify: <code>docs/README.md</code>
- Modify: <code>docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md</code>

**Interfaces:**

- Consumes: the checked-in contract and read-only local commands.
- Produces: a written admission rule for the next bridge plan.

- [ ] **Step 1: Record the exact evidence**

Write <code>docs/contracts/hermes-gateway-0.18.2.md</code> with these sections and exact commands:

~~~markdown
# Hermes gateway 0.18.2 capability evidence

Observed 2026-07-13. This document is a local compatibility snapshot, not a
promise about newer Hermes versions.

## Reproduce without a model call

    hermes --version
    hermes serve --help
    git -C /Users/sunyibo/.hermes/hermes-agent rev-parse HEAD
    git -C /Users/sunyibo/.hermes/hermes-agent status \
      --porcelain --untracked-files=no
    shasum -a 256 \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    rg -n '^@method\("(session|prompt|approval|config)' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    rg -n \
      -e 'client_request|idempoten|request_correlation|request_lookup' \
      -e 'run_id|event_id|event_cursor' \
      -e 'requested_provider|actual_provider|fallback' \
      -e 'approval.*(digest|ttl|expir|single)' \
      -e 'interrupt.*(idempoten|reconcil)' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '1138,1152p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '4515,4610p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '5161,5304p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '5528,5680p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '8420,8525p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '8114,8170p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '10199,10315p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py

Record both matching and zero-result searches. A false capability means the
specific create/submit/event/interrupt/approval/Run contract lacks the required
semantic guarantee; it does not claim that a similarly named token is absent
from unrelated billing, process, or internal implementation code.

## Confirmed read surface

session.list, session.status and session.history exist.

## Stateful resume surface

session.resume exists, but rebinds a transport and may restore/build an agent.
It is a separately gated mutation and is not authorized by chat_read_enabled.

## Confirmed mutation surface

session.create, prompt.submit, session.interrupt, approval.respond and config.set
exist. session.create accepts a per-session model/provider override; config.set
can later switch the session model/provider, so the primary policy is not locked.

## Missing recovery contract

session.create and prompt.submit expose no client idempotency key, durable
request-correlation metadata, lookup by client request ID or caller-supplied
Run ID. The inspected session contract does not prove an immutable primary or
fallback provider policy. Events have no
durable event_id/cursor replay contract. The inspected turn output does not
provide immutable requested/actual provider+model, fallback from/to/reason, and
usage evidence bound to the same Run. approval.respond has no command-digest,
TTL, or single-use binding; session.interrupt has no Run-scoped idempotent
reconciliation contract.

## Admission rule

A bridge implementation plan may be written only after a newly observed
contract makes hqa.hermes_capability_cli verify-chat exit 0 with
review.verdict=ready and installation.matches_snapshot=true. Until then the
platform may display read-only/offline capability state, but session creation,
session resume, prompt submit, streaming, approval and stop remain disabled. The old
/api/agent/tasks endpoint is not a fallback.
~~~

- [ ] **Step 2: Make the current execution status unambiguous**

Update <code>docs/README.md</code> so the current table names this capability plan, the candidate-integrity plan, and the frontend plan as the first selected wave. State explicitly:

~~~markdown
The real Hermes chat mutation slice is not selected. The fingerprinted Hermes
0.18.2 installation exposes the
needed JSON-RPC method names but does not yet satisfy D-31 request-recovery,
event-replay, Run identity, immutable session provider/fallback policy, or
actual-provider evidence. The checked-in capability evaluator and Git-bound
independent review therefore keep chat/resume/approval/stop disabled.
~~~

Update section 14 of the D-31 spec from “implementation plan not written” to:

~~~markdown
The first implementation wave is split into three independently testable plans:
gateway capability contract, candidate integrity/Gate 3, and professional
frontend/read-only shell. The bridge/chat plan is admitted only when
verify-chat returns ready against a Git-reviewed default contract and current
installed Hermes evidence.
~~~

- [ ] **Step 3: Verify docs and contract agree**

Run:

~~~bash
./.venv/bin/python -m hqa.hermes_capability_cli verify-chat
rg -n "missing_request_recovery|chat mutation|不.*fallback|/api/agent/tasks" \
  docs/README.md docs/contracts/hermes-gateway-0.18.2.md \
  docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md
~~~

Expected before independent review: the CLI exits 3 with <code>contract_unreviewed</code> plus the declared capability blockers; every document says the write path is blocked for the same named reason and no document calls the old AgentRunner a fallback.

- [ ] **Step 4: Run the HQA suite**

Run: <code>./.venv/bin/pytest</code>

Expected: all existing and new tests pass; no network/model call occurs.

- [ ] **Step 5: Commit evidence and governance**

~~~bash
git add docs/README.md docs/contracts/hermes-gateway-0.18.2.md \
  docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md
git commit -m "docs(hermes): freeze gateway contract and chat admission gate"
~~~

---

