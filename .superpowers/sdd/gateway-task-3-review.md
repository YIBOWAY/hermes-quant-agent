# Gateway Task 3 Review: Reproducible evidence and bridge-plan admission gate

**Reviewer:** independent read-only review  
**Date:** 2026-07-13  
**Base:** `34713d87d3d13f301fa96c950517cc2c529912c7`  
**Head:** `c767b758e524e2a3ee15f66ab7618eafbcd87057`  
**Package:** brief + report + review.diff; live reconfirm of digests / `verify-chat` / `server.py` tokens

---

### Spec Compliance

| Requirement | Status | Notes |
|---|---|---|
| Create `docs/contracts/hermes-gateway-0.18.2.md` with required sections | **Pass** | All brief sections present; command block matches Step 1 exactly; extra Snapshot / Observed / Inspected sections are additive quality |
| Evidence from real read-only commands, not invented | **Pass** | Live reconfirm: version `0.18.2 · upstream b03c94db`, checkout `4281151a…`, server SHA-256 `2a05d897…`, clean tracked tree, 26 `@method` hits, recovery zero-tokens, 84 combined pattern lines — all match the contract + report |
| Source-reviewed upstream tip `b03c94db` + matching checkout+server digest | **Pass** | Matches live install, `config/hermes-gateway-capabilities.v1.json`, and contract Snapshot identity; plan-era `e4ea0a0e` explicitly demoted to non-truth |
| Admission rule: bridge plan only after `verify-chat` exit 0 with `review.verdict=ready` and `installation.matches_snapshot=true` | **Pass** | Verbatim in contract §Admission rule; mirrored in README and D-31 §14 |
| Chat remains closed; no mutation | **Pass** | Commit is docs-only (3 files). Live `verify-chat` exit 3, `status=blocked`, all write gates false, `contract_unreviewed` + capability blockers present, `installation.matches_snapshot=true` |
| Update `docs/README.md`: first selected wave + English chat-blocked block | **Pass** | Table marks three plans as 已选 wave; English block present; `/api/agent/tasks` not fallback |
| Update D-31 §14 admission language | **Pass** | Required English paragraph + explicit exit-0 / verdict / matches_snapshot criteria |
| Docs agree on write-path block reasons | **Pass** | Three docs name blockers / fail-closed chat; none treat AgentRunner or `/api/agent/tasks` as fallback |
| Step 3 expected pre-review CLI state | **Pass** | `verify-chat` exit 3; `review.verdict=unreviewed` / `blocker=contract_unreviewed`; declared blockers include `missing_request_recovery` et al. |
| Step 4 pytest green | **Pass (report)** | Report claims full suite green; Task 3 is docs-only so regression risk is negligible; suite not re-run in this review |
| Step 5 commit message/files | **Pass** | `docs(hermes): freeze gateway contract and chat admission gate`; exactly the three paths |

**Binding constraints:** all four satisfied. Evidence is observational; admission gate is fail-closed and correctly conditioned; chat/write path stays disabled; fingerprint identity is coherent across install, JSON contract, and prose.

---

### Strengths

1. **Evidence over assertion.** Contract records exact commands *and* observed outputs, including zero-result searches and a semantic (not token-presence) reading of `fallback` / billing `idempotency_key`.
2. **Correct false-capability framing.** Explicitly scopes missing D-31 guarantees to create/submit/event/interrupt/approval/Run, matching the brief’s “false capability ≠ token absent from unrelated code.”
3. **Fingerprint coherence.** Live install, JSON twin, and prose all agree on `b03c94db` / `4281151a…` / `2a05d897…`; plan-era `e4ea0a0e` is clearly non-authoritative.
4. **Admission rule is operational, not soft.** Requires `verify-chat` exit 0 *and* `review.verdict=ready` *and* `installation.matches_snapshot=true`; no method-name-only path to a bridge plan.
5. **Governance alignment.** README table + §“已选 wave”, D-31 §14, and contract admission language say the same thing in three places; Task 4 (review JSON) correctly left out of scope.
6. **Line-range inspection quality.** Summaries of `_emit`, `session.create`, `prompt.submit`, `session.interrupt`, `approval.respond`, and `config.set` match live source at the cited lines (spot-checked).
7. **No scope creep.** Docs-only commit; no Hermes mutation, no chat enablement, no inventing recovery contracts.

---

### Issues

#### Critical

None.

#### Important

None that block approval.

#### Minor

1. **`rg` not on default PATH.** Report and concerns correctly note host shell lacks system `rg`; evidence still lists the brief’s exact `rg` commands. Reproducers need ripgrep (or equivalent). Document already used Python/`grep` cross-check — consider a one-line PATH/install note under Reproduce for operators without Codex-bundled `rg`.
2. **`hermes serve --help` is summarized, not pasted.** Adequate for endpoint identity; full dump is optional.
3. **README subsection title lag.** “已批准设计、第一批正式计划待执行” still reads “待执行” while body says capability evidence is advancing; cosmetic only (pre-existing section structure largely retained).
4. **Pytest not independently re-run in this review.** Docs-only change; report’s green suite is accepted with low risk. Re-run if process policy requires reviewer-side suite proof.

---

### Assessment: **Approved**

Task 3 meets the brief and binding constraints. Evidence is real and reproducible from the listed read-only commands (with the known `rg` PATH caveat). The bridge-plan admission gate is correctly frozen: chat remains closed until a newly observed contract yields `verify-chat` exit 0 with `review.verdict=ready` and `installation.matches_snapshot=true`. No critical or important fixes required before Task 4 (independent review JSON).

**Recommended next step:** proceed to Task 4 for Git-bound independent review material; do not open chat or draft a bridge plan on method-name presence alone.
