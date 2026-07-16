# Candidate Task 5 — FastAPI Review

**Scope:** Platform API CAS surfaces in `392485a` (`8aaa278..HEAD`)  
**Focus:** schema correctness, 409 mapping, required CAS fields, no CAS bypass  
**Reviewed:** `src/quant_system/api/schemas/agent.py`, `src/quant_system/api/routes/agent.py`, OpenAPI emission, `tests/test_api_agent.py`, `tests/test_api_response_models.py`  
**Out of scope for this pass:** frontend UI, HQA callers, CLI presentation (CLI CAS flags checked only as fail-closed contract)

## Verdict summary

Gate 2 review is fail-closed at the FastAPI boundary:

- `AgentReviewRequest` requires both CAS fields with no defaults.
- Digest is constrained to lowercase SHA-256 hex; status is const `"pending"`.
- Domain exceptions map to stable HTTP 409 codes, most-specific first.
- Omitted/invalid CAS inputs return 422 before any lock write.
- List remains 200 when sibling candidates are migration/corrupt; those items cannot approve.

No Critical or High findings. One Medium OpenAPI documentation gap does not weaken runtime CAS.

---

## Findings

```text
[MEDIUM] Review route OpenAPI omits 409 CAS conflict responses
File: src/quant_system/api/routes/agent.py:271-274
Issue: POST /api/agent/candidates/{candidate_id}/review only documents
  responses 200 and 422 in OpenAPI. Runtime correctly returns 409 with
  stable detail codes (candidate_revision_stale,
  candidate_review_state_stale, candidate_migration_required,
  candidate_integrity_failed, candidate_conflict), but generated clients
  and docs cannot discover those contracts.
Fix: Add responses={409: ...} (shared error model or explicit schema) on
  review_candidate describing the message-free detail shape
  {code, resource, id}. Optionally assert codes in
  test_api_response_models.py.
```

```text
[MEDIUM] Missing-candidate 404 relies on exception message substrings
File: src/quant_system/api/routes/agent.py:304-311
Issue: CandidateIntegrityError is split into 404 vs 409 by matching
  "does not exist" / "not a directory" in str(exc). That works with
  current CandidatePool.review messages but is brittle: a wording change
  could reclassify missing as candidate_integrity_failed (or the reverse).
  Not a CAS bypass (both paths refuse the lock), but weakens stable API
  semantics.
Fix: Prefer typed/sentinel errors (e.g. CandidateNotFoundError) or an
  explicit attribute on the exception, and map that to not_found_404
  without string inspection.
```

No Critical/High issues found for:

- hardcoded secrets
- SQL injection
- auth bypass
- CAS field defaults / optional review without digest or status
- exception subclass collapse (hierarchy verified)

---

## Contract checks (focus areas)

### 1. Schema correctness — pass

`AgentReviewRequest` matches the brief:

```63:67:src/quant_system/api/schemas/agent.py
class AgentReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=2000)
    expected_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_status: Literal["pending"]
```

OpenAPI emission verified:

| Field | Contract |
|---|---|
| `required` | `decision`, `note`, `expected_manifest_digest`, `expected_status` |
| `expected_manifest_digest` | `pattern: ^[0-9a-f]{64}$` |
| `expected_status` | `const: pending` |
| `note` | `minLength: 1`, `maxLength: 2000` |

Probes:

| Input | Result |
|---|---|
| omit digest | 422 |
| omit status | 422 |
| `expected_status: "approved"` | 422 |
| uppercase digest | 422 |
| short/null digest | 422 |
| empty note | 422 |

List/detail response models expose integrity/CAS visibility fields (`integrity_state`, `manifest_digest`, `observed_manifest_digest`, `approval_binding`, `approval_enabled`, `integrity_error_code`) as nullable optionals — correct for mixed verified/migration/corrupt lists.

### 2. 409 mapping — pass

Exception hierarchy:

- `CandidateReviewStateStaleError` ⊂ `CandidateStaleError`
- `CandidateMigrationRequiredError` ⊂ `CandidateIntegrityError`
- `CandidateStaleError` and `CandidateIntegrityError` are siblings under `RuntimeError`

Route catch order is most-specific first:

1. `CandidateReviewStateStaleError` → `candidate_review_state_stale`
2. `CandidateMigrationRequiredError` → `candidate_migration_required`
3. `CandidateIntegrityError` → `candidate_integrity_failed` (or 404 for missing)
4. `CandidateStaleError` → `candidate_revision_stale`
5. `CandidateConflictError` → `candidate_conflict` (race on exclusive lock write)

`_candidate_conflict` always returns HTTP 409 with message-free detail:

```json
{"code": "<stable_code>", "resource": "agent_candidate", "id": "<candidate_id>"}
```

Matches brief (`code` / `resource` / `id`). Extra `candidate_conflict` for noreplace races is fail-closed and acceptable.

### 3. Required CAS fields — pass

- No defaults on either CAS field → request body omission is 422, not silent pending/digest fill.
- Route forwards caller-supplied values only:

```286:292:src/quant_system/api/routes/agent.py
        record = AgentRunner(agent_output_dir=agent_output_dir).review(
            candidate_id=candidate_id,
            decision=request.decision,
            note=request.note,
            expected_manifest_digest=request.expected_manifest_digest,
            expected_status=request.expected_status,
        )
```

- No list/detail refetch inside the review route to synthesize CAS values.
- Dependency injection uses `AgentOutputDirDep` (no process-global root in this path).

### 4. No CAS bypass — pass

| Scenario | HTTP | Lock written? |
|---|---|---|
| Stale digest (`0`*64) | 409 `candidate_revision_stale` | No |
| Second decision | 409 `candidate_review_state_stale` | First lock bytes unchanged |
| `migration_required` + observed digest | 409 `candidate_migration_required` | No |
| Corrupt candidate | 409 `candidate_integrity_failed` | No; bytes unchanged |
| Missing candidate | 404 `not_found` | No |
| List with mixed good/bad siblings | 200 | N/A; bad items `approval_enabled=false`, authoritative `manifest_digest=null` |

Observed migration digests cannot authorize approval: domain refuses migration before digest compare; API maps that to 409.

Whitespace-only notes (`"   "`) are accepted by both schema (`min_length=1`) and domain `_validate_note`. That is a note-quality gap, not a CAS concurrency bypass — digest + pending status are still required and enforced. HQA may tighten notes separately.

---

## Tests checked

```bash
cd /Users/sunyibo/programs/ai-quant-platform
./ai-quant/bin/python -m pytest -q \
  tests/test_api_agent.py \
  tests/test_api_response_models.py \
  tests/test_cli_json_output.py
# EXIT 0 (all collected tests passed)
```

Also manually verified OpenAPI `AgentReviewRequest` shape and CAS edge probes via TestClient.

Covered by automated tests:

- missing digest / missing status → 422
- stale digest → 409 `candidate_revision_stale`
- second decision → 409 `candidate_review_state_stale`, first lock preserved
- migration → 409 `candidate_migration_required`
- corrupt → 409 `candidate_integrity_failed`, bytes preserved
- list isolates corrupt + migration while verified remains readable
- OpenAPI required CAS fields on `AgentReviewRequest`
- CLI missing `--expected-digest` / `--expected-status` → exit 2

## Residual risk

- OpenAPI clients will not learn 409 CAS codes without reading runtime tests/docs (Medium finding above).
- 404-vs-409 integrity split remains message-coupled.
- No dedicated OpenAPI assertion that `expected_manifest_digest.pattern` / `expected_status.const` are published (runtime schema is correct; only the test gap remains).
- Concurrent double-approve relies on domain exclusive lock + `CandidateConflictError`; not re-load-tested here.
- Frontend/HQA CAS wiring is outside this FastAPI pass (covered by other Task 5 reviewers).

---

Assessment Approved
