# Gateway Task 2 Report — JSON-only capability CLI

**Status:** DONE  
**Branch:** `codex/full-9h`  
**Commit:** `34713d8` — `feat(hqa): expose Hermes chat readiness as strict JSON`  
**Base:** `1b461efa2ac00ecfb1d3f29453149b746335f9c9` (Task 1)

## What shipped

| Path | Action |
|------|--------|
| `tests/test_hermes_capability_cli.py` | Created — CLI exit/output tests + table-driven `_probe_review` git fixtures + installation probe-failure test |
| `hqa/hermes_capability_cli.py` | Created — `show` / `verify-chat` strict JSON CLI |
| `hqa/config.py` | Unchanged — `HERMES_GATEWAY_REVIEW_PATH` already present from Task 1 |

## TDD sequence

1. **RED:** `pytest -q tests/test_hermes_capability_cli.py` failed collection with `ImportError: cannot import name 'hermes_capability_cli'`.
2. **GREEN:** Implemented `hqa/hermes_capability_cli.py` per brief; `20` tests passed.
3. **Live (read-only):**
   - `python -m hqa.hermes_capability_cli show` → exit `0`
   - `snapshot_readable=true`, `installation.matches_snapshot=true`
   - effective `gate.chat_read_enabled=false`, `gate.chat_write_enabled=false` with `contract_unreviewed`
   - `python -m hqa.hermes_capability_cli verify-chat` → exit `3`, `status=blocked`
4. **Commit:** only the two new files listed above.

## Behavior summary

- **`show`:** loads contract (default or diagnostic `--contract`), overlays review + installation gates, emits one sorted strict JSON document, exit `0` (or `1`/`2` on contract/args errors). Custom contracts never authorize (`custom_contract_unreviewed`).
- **`verify-chat`:** default contract only; rejects `--contract` with exit `2` / `invalid_arguments`. Exit `0` only when both `chat_write_enabled` and `stream_enabled` are true after review + installation; otherwise exit `3` / `blocked`.
- **Review provenance (fail-closed):** exact field set, digest, ancestor, HEAD blob match for contract and review record; untrusted → closes reads when not trusted; trusted+blocked keeps reads open but closes mutations.
- **Installation:** bounded read-only `hermes --version` + source `rev-parse` / tracked-only status / `server.py` SHA-256. Mismatch → `installation_fingerprint_mismatch`; dirty tracked → `installation_source_dirty`; probe exception → `installation_probe_failed` with `{error: TypeName}` only (no stderr leak). All three close reads and every mutation gate.
- **No** Hermes session mutation, **no** provider calls, **no** installed Hermes checkout edits, **no** review-record file (Task 4), **no** docs/contracts (Task 3).

## Self-review

- Matches brief implementation; config review path already satisfied Task 1.
- Live 0.18.2 fingerprint matches snapshot (`upstream_commit=b03c94db`, checkout `4281151…`, server sha `2a05d897…`, tracked clean).
- Known snapshot remains blocked on missing recovery/replay contracts plus `contract_unreviewed` until Task 4 review record.
- Tests hermetic except live manual commands (not part of pytest).
- Commit scope limited to Task 2 files; did not push.

## Concerns

None material. Live verify-chat correctly stays blocked until Task 4 admits a checked-in review record (and still fails write/stream on the known 0.18.2 missing contracts even after a `blocked` review).

## Test summary

`./.venv/bin/pytest -q tests/test_hermes_capability_cli.py` → **20 passed**.
