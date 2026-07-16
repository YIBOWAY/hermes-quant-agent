# Gateway Task 2 Review — JSON-only capability CLI

**Reviewer role:** Task-scoped gate + Python quality  
**Base:** `1b461efa2ac00ecfb1d3f29453149b746335f9c9`  
**Head:** `34713d87d3d13f301fa96c950517cc2c529912c7`  
**Diff scope:** 2 files, +753 lines (`hqa/hermes_capability_cli.py`, `tests/test_hermes_capability_cli.py`)

---

### Spec Compliance

- ✅ **Files delivered** — Creates the prescribed CLI module and focused tests. `hqa/config.py` correctly left untouched because `HERMES_GATEWAY_REVIEW_PATH` already landed in Task 1.
  - Evidence: commit `34713d8` name-only list is exactly the two new files; base config already defines `HERMES_GATEWAY_REVIEW_PATH` at `hqa/config.py:76`.

- ✅ **Interfaces** — Consumes fixed capability/review paths plus local Hermes binary/source fingerprint; only `show` accepts diagnostic `--contract`; `verify-chat` always uses the default contract and rejects overrides with exit `2` / `invalid_arguments`.
  - Evidence: `hqa/hermes_capability_cli.py:60-70`, `304-330`; `tests/test_hermes_capability_cli.py:520-524`.

- ✅ **Exit / JSON contract** — One sorted strict JSON document (`ensure_ascii=False`, `allow_nan=False`, `sort_keys=True`, compact separators). `show` → `0`; `verify-chat` ready → `0`, blocked → `3`; contract invalid → `1`; args invalid → `2`.
  - Evidence: `hqa/hermes_capability_cli.py:47-57`, `304-330`; CLI tests cover `0`/`2`/`3` paths.

- ✅ **Effective gate fail-closed after review + installation** — Declared gate is overlaid by review provenance, then installation fingerprint. Bridge admission (`verify-chat` ready) requires both `chat_write_enabled` and `stream_enabled` after overlays; approval/stop remain independent and stay closed in the ready path.
  - Evidence: `hqa/hermes_capability_cli.py:208-218`, `270-301`, `325-330`; tests for ready, replay-required, blocked review, dirty/mismatch/probe-failed.

- ✅ **Review provenance authorizes only exact default-contract bytes** — Exact field set; schema `1.0`; verdict `blocked|ready`; lowercase sha256/40-char commit/UTC timestamp/non-empty reason; custom path never trusted; working contract bytes must match HEAD blob and reviewed-ancestor blob; review-record bytes must match HEAD blob; non-ancestor / schema / digest failures collapse to untrusted `contract_unreviewed`.
  - Evidence: `hqa/hermes_capability_cli.py:93-179`; table-driven git fixtures in `tests/test_hermes_capability_cli.py:618-746` cover missing/unknown fields, invalid digest/commit, digest mismatch, non-ancestor, reviewed-contract differs, working≠HEAD while matching older ancestor, dirty review bytes; happy-path accept test at `:749-765`.

- ✅ **Trusted blocked keeps reads; untrusted closes reads** — `close_read=not review["trusted"]` so `contract_review_blocked` leaves `chat_read_enabled` open while closing mutations; `contract_unreviewed` / `custom_contract_unreviewed` close reads and mutations.
  - Evidence: `hqa/hermes_capability_cli.py:186-211`; tests `:413-429`, `:483-498`, `:388-410`.

- ✅ **Installation fingerprint gate** — Live probe is bounded read-only (`hermes --version`, `rev-parse HEAD`, tracked-only `status --porcelain`, `server.py` SHA-256). Mismatch / dirty tracked source / probe exception all close reads and every mutation gate; probe failure emits `{error: TypeName}` only (no stderr leak).
  - Evidence: `hqa/hermes_capability_cli.py:221-301`; tests `:461-517`, `:527-557`.

- ✅ **Global constraints respected for this slice** — No browser/secret path; no Hermes session mutation; no provider calls; no installed-Hermes edits; no platform POST fallback surface; no review-record/docs (Task 3/4); safety baseline untouched; tests hermetic via monkeypatch + temp git repos (local git only, no network/provider).
  - Evidence: commit scope; subprocess list-args + `shell=False` + timeout; no `session.create` / `prompt.submit` / network clients in CLI or tests.

- ✅ **TDD / live claims** — Report sequence RED (ImportError) → GREEN (20 tests) matches delivered suite size (8 CLI cases + probe-failed + 9 parametrized reject cases + accept + custom-path). Live read-only `show`/`verify-chat` behavior reported as expected pre-Task-4 (`snapshot_readable=true`, `matches_snapshot=true`, effective gates closed with `contract_unreviewed`, verify exit 3). Not re-executed in this review (full suite intentionally not re-run).

- ⚠️ **Cannot verify from diff alone** — Live Hermes fingerprint match and live CLI exit codes are implementer-reported; static review confirms the code paths that would produce those outcomes when the local install matches the checked-in snapshot and no review record is present.

---

### Strengths

- Near line-faithful implementation of the prescribed CLI; little room for silent behavioral drift from the plan.
- Fail-closed layering is correct and independently testable: declared gate → review overlay → installation overlay → bridge admission conjunction.
- Review checks are cryptographic/git-hard rather than “file exists”: HEAD blob identity for both contract and review record, ancestor contract byte identity, and strict schema/identity validation.
- Hermetic coverage is strong for the high-risk surface (`_probe_review` git matrix + probe-exception non-leakage), while keeping production subprocesses out of the unit path via monkeypatch.
- Scope discipline: single commit, two files, prescribed message, Task 1 config path reused rather than re-touched.
- Operational safety: `shell=False`, timeouts, captured output, no secret reflection on probe failure.

---

### Issues

#### Critical
None.

#### Important
None.

#### Minor

1. **`_probe_review` length / complexity**  
   File: `hqa/hermes_capability_cli.py:93-179`  
   Issue: Function is well over the usual ~50-line preference (schema + identity + four git checks in one body). Matches the brief’s prescribed shape and is covered by table-driven tests; non-blocking for this task.  
   Fix (optional later): extract schema validation vs git provenance helpers without changing semantics.

2. **Bare `dict` return types**  
   File: `hqa/hermes_capability_cli.py` (`_emit`, `_read`, `_probe_review`, `_probe_installation`, gate helpers)  
   Issue: Public-ish helpers use untyped `dict` rather than `dict[str, object]` / TypedDict. Matches brief; fine for a thin CLI.  
   Fix (optional): add TypedDicts for review/installation/document shapes once Task 3 docs freeze the JSON schema.

3. **Mocked CLI identity still uses plan-frozen `e4ea0a0e`**  
   File: `tests/test_hermes_capability_cli.py:353-360`  
   Issue: Stub `_contract()` follows the brief snippet (`upstream_commit=e4ea0a0e`) rather than the Task-1 controller-approved live snapshot value (`b03c94db`). Harmless because installation is mocked and never loads the committed JSON, but a later reader may think tests assert the production fingerprint.  
   Fix (optional): align stub identity with the committed snapshot or name the helper `_stub_identity()` to make the fiction obvious.

4. **Parametrized probe fixture is a large if/elif chain**  
   File: `tests/test_hermes_capability_cli.py:631-738`  
   Issue: Readable enough and maps 1:1 to required reject cases, but failures will point at one mega-test body.  
   Fix (optional): one small factory per case or pytest fixtures keyed by case name.

---

### Assessment

**Task quality:** Approved  

**Reasoning:** The implementation matches the Task 2 brief and binding global constraints: strict JSON CLI, fail-closed review provenance that authorizes only exact default-contract bytes at the reviewed ancestor (and HEAD), installation fingerprint comparison that closes all gates on drift/dirt/probe failure, bridge admission only when write∧stream survive overlays, hermetic tests with no provider/network/Hermes session mutation, and commit scope limited to the two prescribed new files. No Critical or Important defects found; remaining notes are optional polish.
