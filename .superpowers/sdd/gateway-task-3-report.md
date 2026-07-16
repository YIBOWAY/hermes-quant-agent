# Gateway Task 3 Report: Reproducible evidence and bridge-plan admission gate

**Status:** DONE  
**Date:** 2026-07-13  
**BASE:** `34713d87d3d13f301fa96c950517cc2c529912c7`  
**Commit:** `c767b75` — `docs(hermes): freeze gateway contract and chat admission gate`

## Deliverables

| Path | Action |
|---|---|
| `docs/contracts/hermes-gateway-0.18.2.md` | Created — live reconfirm + admission rule |
| `docs/README.md` | Updated — first selected wave + chat mutation blocked |
| `docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md` | Updated — §14 admission language |

Not created (out of scope): `config/hermes-gateway-capabilities.v1.review.json` (Task 4).  
No Hermes mutation, chat enablement, or network/model call.

## Live evidence reconfirm (read-only)

Commands re-run on 2026-07-13 (PATH note: system `rg` absent; searches executed with
Codex-bundled `rg` at
`/Users/sunyibo/.codex/packages/standalone/releases/0.142.0-aarch64-apple-darwin/codex-path/rg`
and cross-checked with Python/`grep -nE`).

| Check | Result |
|---|---|
| `hermes --version` | `Hermes Agent v0.18.2 (2026.7.7.2) · upstream b03c94db` |
| Plan-era upstream vs live | Plan-era note `e4ea0a0e`; **snapshot truth `b03c94db`** |
| `git rev-parse HEAD` (hermes-agent) | `4281151ae859241351ba14d8c7682dc67ff4c126` |
| `git status --porcelain --untracked-files=no` | empty (clean tracked) |
| `shasum -a 256 tui_gateway/server.py` | `2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17` |
| Checkout + server digest vs contract JSON | **unchanged / matches** |
| `@method` session/prompt/approval/config | 26 registrations; allowlisted subset present |
| Zero-result tokens | `client_request`, `request_correlation`, `request_lookup`, `run_id`, `event_id`, `event_cursor`, `actual_provider` → **0** |
| `approval.*(digest\|ttl\|expir\|single)` | **0** |
| `interrupt.*(idempoten\|reconcil)` | **0** |
| Combined recovery `rg` | 84 lines — mostly unrelated `fallback` / teardown `idempotent` / **billing** `idempotency_key` / internal `requested_provider` |

Semantic conclusion (documented, not invented capability): method names exist; D-31
request recovery, Run identity, event replay, immutable provider/fallback policy,
and actual-provider Run evidence do **not**.

## Verification

```bash
./.venv/bin/python -m hqa.hermes_capability_cli verify-chat
# exit 3; status=blocked; review.verdict=unreviewed; review.blocker=contract_unreviewed
# installation.matches_snapshot=true
# gate.blockers include:
#   missing_request_recovery, missing_run_identity, missing_provider_policy_lock,
#   missing_actual_provider_evidence, missing_event_replay, contract_unreviewed
# chat_write_enabled=false, stream_enabled=false, resume_enabled=false,
# approval_enabled=false, stop_enabled=false

rg -n "missing_request_recovery|chat mutation|不.*fallback|/api/agent/tasks" \
  docs/README.md docs/contracts/hermes-gateway-0.18.2.md \
  docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md
# All three docs: write path blocked; /api/agent/tasks is not a fallback;
# contract doc names missing_request_recovery (+ sibling blocker codes)

./.venv/bin/pytest -q
# exit 0 — full suite green (existing tests; no network/model call)
```

## Admission rule frozen

Bridge/chat implementation plan may be written **only** after a newly observed
contract makes `hqa.hermes_capability_cli verify-chat` exit 0 with
`review.verdict=ready` and `installation.matches_snapshot=true`. Until then:
read-only/offline capability display only; session create/resume, prompt submit,
streaming, approval, and stop remain disabled. Old `/api/agent/tasks` is not a
fallback.

## Concerns / follow-ups

1. **Task 4** still required for independent review JSON (`contract_unreviewed`
   remains a hard gate even if evidence flags were true).
2. Host shell has no `rg` on default PATH; evidence doc still lists the brief’s
   exact `rg` commands. Reproducers need ripgrep installed or an equivalent.
3. `fallback` / `idempoten*` token hits must not be misread as D-31 recovery —
   document explicitly scopes false capabilities to the create/submit/event/
   interrupt/approval/Run contract.
4. Do not enable chat or write a bridge plan on method-name presence alone.

## Commit contents

```
docs(hermes): freeze gateway contract and chat admission gate
 3 files changed, 259 insertions(+), 15 deletions(-)
 create mode 100644 docs/contracts/hermes-gateway-0.18.2.md
```
