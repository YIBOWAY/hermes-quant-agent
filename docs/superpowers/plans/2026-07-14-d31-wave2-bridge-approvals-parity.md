# D-31 Wave 2 — Bridge/Chat Foundations, Approvals Mutation, Candidate Apply, Scene-B Reality, Page Parity

> **For agentic workers:** Use superpowers:subagent-driven-development. Wave 1 three-plan delivery remains complete and partial relative to full D-31.

**Goal:** Close the remaining D-31 gaps listed after Wave 1 acceptance without lying about Hermes readiness: migrate real candidates, open honest Gate 2 approvals in Hermes UI when integrity is verified, replace Tasks placeholder with a real read model, run Scene-B evidence path with human CAS inputs, re-audit Hermes installation and build a fail-closed bridge, and stage old-page parity cutover.

**Architecture:** Keep platform as domain authority and HQA as orchestration. Chat write stays fail-closed until `verify-chat` exits 0 against a source-backed ready contract and matching installation. Approvals mutate only the existing platform review CAS API. Migration `--apply` is explicit, backup-required, and once-only for real data. Page parity never deletes Factor Lab / Backtester / Experiments / Agent Studio until each surface has Hermes-equivalent read paths and human confirmation.

**Tech Stack:** Platform Python/FastAPI/Typer/React/Next/Vitest/Playwright; HQA Python/pytest; Hermes 0.18.2 local gateway; PostgreSQL existing tables only.

## Global Constraints

- Never claim Hermes is fully connected while `verify-chat` ≠ 0 or capability review is `blocked`.
- Browser never receives Hermes bearer keys or provider secrets.
- `POST /api/agent/tasks` is never a Hermes fallback.
- Gate 2 still requires human-supplied candidate-id, expected-digest, expected-status=pending, note; no list refetch into approve.
- Gate 3 never auto-commits, merges, or pushes; main dirty worktree untouched.
- Keep `paper_trading=true`, `live_trading_enabled=false`, kill switch baseline.
- Preserve unrelated dirty files: platform `data/options_universe/earnings_calendar.csv`, `src/quant_system/options/data_refresh.py`, `tests/test_options_data_refresh.py`, `.understand-anything/diff-overlay.json`; HQA `.superpowers/`.
- Real provider/backtest/Scene-B runs only through approved CLI wrappers and receipts; no silent paper/broker mutation.

## Execution order

1. **Task A — Candidate migration apply** (user authorized by Wave-2 kickoff): dry-run again, apply with non-overlapping backup, re-list integrity.
2. **Task B — Hermes Approvals mutation UI**: Gate 2 CAS form for `verified` + `approval_enabled` only; migration/corrupt remain display-only.
3. **Task C — Hermes Tasks real read model**: bind automation runs / research receipts / opportunity summary; still no write unless a later plan adds it.
4. **Task D — Scene-B operational smoke**: Gate 1 source confirm → one-shot final backtest receipt (Futu/Tiingo only) → Gate 3 prepare in isolation (no auto human commit).
5. **Task E — Capability re-audit + bridge scaffold**: reconfirm install fingerprint, start/check loopback 9119, implement platform/HQA bridge that exposes **reads only** until write gates green; never greenwash contract.
6. **Task F — Page parity staged cutover**: inventory Factor Lab / Backtester / Experiments / Agent Studio; implement Hermes-side deep links + optional soft banners; no deletion without separate approval after parity proof.
7. **Task G — Docs + dual-repo verification + service restart evaluation**.

## Non-goals this wave

- Turning blocked chat_write into ready without Hermes source evidence.
- Deleting old four pages without parity proof.
- Automatic Gate 3 git commit.
- Any live trading path.

## Success criteria

- At least one real candidate is `verified` after apply (or documented conflict if apply cannot produce verified without manual repair).
- Hermes Approvals can submit CAS approve/reject for verified pending items and fails closed otherwise.
- Tasks page shows real automation/research evidence, not only “尚未接入”.
- Scene-B has at least one documented real Gate 1 + final receipt + Gate 3 prepare artifact set (or explicit BLOCKED with evidence).
- Bridge code exists; `verify-chat` still honest; chat composer remains disabled until ready.
- Old pages still present; parity plan evidence recorded.
- HQA and platform tests green; docs/README + platform INDEX updated.
