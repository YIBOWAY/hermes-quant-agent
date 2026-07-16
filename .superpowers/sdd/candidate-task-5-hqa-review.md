# Candidate Task 5 HQA Review (Gate 2 CAS)

**Task:** Digest-aware HQA Gate 2 callers (four-value human CAS)  
**Range:** `ea0b297`..`2f0c96d` (HEAD = `2f0c96d`)  
**Commit:** `2f0c96d fix(hqa): carry candidate digest through manual Gate 2 review`  
**Files reviewed:**
- `hqa/quant_cli.py`
- `hqa/factor_repro_cli.py`
- `skills/hermes/hqa-quant/SKILL.md`
- `tests/test_quant_cli.py`
- `tests/test_factor_repro_cli.py`
- `tests/test_install.py`  
**Note:** `tests/test_factor_repro.py` is listed in the brief but has no CAS call-site; no change required.  
**Reviewer role:** senior Python code review (security + Pythonic standards + Gate 2 constraints)

## Assessment: **Approved**

No CRITICAL or HIGH issues. Gate 2 constraints hold: HQA approve never lists/refetches/substitutes observed digests; all four human CAS values are required and passed through keyword-only `run_agent_review`; skill card is versioned executable surface at `1.9.0`. Suites for the Task 5 HQA surface are green.

## Brief compliance checklist

| Requirement | Status |
|---|---|
| `run_agent_review(*, candidate_id, decision, note, expected_manifest_digest, expected_status, ...)` keyword-only | Met |
| Review argv includes `--expected-digest` + `--expected-status` | Met |
| Library never lists/refetches a candidate to fill digest/status | Met |
| `hqa-factor-repro approve` requires `--candidate-id`, `--expected-digest`, `--expected-status pending`, `--note` | Met |
| Approve path never calls `run_list_candidates` / detail / parser substitution | Met |
| Local validation exits 2 before `run_agent_review` (omit / empty note / bad digest / non-pending) | Met |
| Propose/list/detail print authoritative digest + copyable approve syntax for verified pending | Met |
| `migration_required` prints observed digest as migration evidence only; approval disabled | Met |
| `corrupt` prints no digest/source; approval disabled | Met |
| Observed digest never substituted into approve command | Met |
| `SKILL.md` version `1.9.0`, exact four-value command, “never refetch” | Met |
| Install tests prove source + installed card + all former `1.8.0` asserts → `1.9.0` | Met |

## What was verified

### `hqa/quant_cli.py` — `run_agent_review`

- Signature is keyword-only after `*`; positional call raises `TypeError` (covered by test).
- Forwards only caller-supplied values into platform CLI list-argv (no shell join, no f-string shell).
- Does not call `run_list_candidates`, candidate detail, or any parser.
- Docstring states CAS / never-refetch contract.

### `hqa/factor_repro_cli.py` — Gate 2 surface

- **approve:** validates digest with `^[0-9a-f]{64}$`, rejects empty/whitespace note, requires literal `pending` (`choices=("pending",)` + local check). Passes keyword kwargs only; no list/refetch.
- **propose:** prefers JSON `manifest_digest`, falls back to authoritative kv line; prints `candidate_id` / `manifest_digest` / `status=pending` / full `approve_cmd` only when digest is 64-hex; otherwise prints incomplete template without inventing a digest.
- **list/detail:** integrity-aware printing:
  - `verified` + pending + approval enabled → authoritative digest + copyable approve cmd
  - `migration_required` → `observed_manifest_digest` + “migration evidence; approval disabled”
  - `corrupt` → no digest/source
- Observed digests are never placed into `--expected-digest` of an approve command.

### Skill card + install contract

- Frontmatter `version: 1.9.0`.
- Approve example is the exact four-value CAS command required by the brief.
- Notes state all four values come from one human-inspected verified item and forbid refetch.
- `test_installed_skill_documents_exact_gate2_cas_command` covers installed + source cards; other skill tests updated off `1.8.0`.

### Tests re-run

```text
./.venv/bin/pytest -q \
  tests/test_quant_cli.py \
  tests/test_factor_repro.py \
  tests/test_factor_repro_cli.py \
  tests/test_install.py
```

**Result:** all passed (exit 0). `ruff` not installed in `.venv` (skipped).

Static review also confirmed:
- approve block source contains no `run_list_candidates`
- no remaining `version: 1.8.0` or old two-value approve command in skill/tests
- subprocess path remains list-argv (`_run`), no command injection surface from digest/note

---

## Findings

### [MEDIUM] Legacy list branch can emit `approve_cmd` without `integrity=verified`

**File:** `hqa/factor_repro_cli.py:89-97` (`_print_list_item` else branch)

**Issue:** When platform stdout lacks an `integrity` / `integrity_state` field, the else path treats any `manifest_digest`/`digest` + `status=pending` as approvable and prints a full `approve_cmd`. That softens the verified-only display contract if an older or partial platform line is still in use during rollout. Approve itself remains fail-closed (human must supply values; platform CAS rejects migration/corrupt/stale), so this is display/UX risk, not a silent auto-approve.

**Fix (optional, non-blocking):** Only emit `approve_cmd` when `integrity == "verified"` (and optionally `approval_enabled` truthy). For unknown/legacy lines, print raw fields + “approval disabled until integrity=verified”.

### [MEDIUM] `propose` hardcodes `status=pending` rather than reading platform status

**File:** `hqa/factor_repro_cli.py:185-190`

**Issue:** When a digest is present, `_print_verified_pending(..., status="pending")` always labels the item pending even if JSON/kv carried a different status. Normal propose returns pending; this is only a consistency nit.

**Fix (optional):** Prefer `payload.get("status")` / kv `status` when present and only print copyable approve_cmd when that status is exactly `pending`.

### [MEDIUM] No dedicated `detail` CLI test

**File:** `tests/test_factor_repro_cli.py`

**Issue:** `list` integrity printing is covered; `detail --candidate-id` shares `_print_list_item` but has no direct test for found / not_found paths.

**Fix (optional):** Add a small monkeypatched test asserting detail filters one id and returns 1 with `not_found=true` when missing.

---

## Non-issues (checked)

- No bare `except` / swallowed errors on approve path.
- No `eval` / unsafe deserialization / hardcoded secrets.
- No path traversal; no shell=True.
- Mutable defaults not introduced.
- Keyword-only CAS API prevents accidental positional omission of digest/status.
- Empty note rejected before platform call.
- Uppercase/short digests rejected locally (exit 2).
- `choices=("pending",)` rejects `--expected-status approved` at argparse before review.

## Approval criteria

- **CRITICAL:** none  
- **HIGH:** none  
- **MEDIUM:** three optional nits (legacy display, propose status hardcode, missing detail test)

**Verdict: Approved** — safe to treat HQA Task 5 Gate 2 CAS as complete for merge/use with platform counterpart. Residual items are non-blocking polish.
