# SDD Progress Ledger — D-31 first wave (2026-07-13)

Branch: `codex/full-9h` (HQA)
Platform branch: `audit-remediation-2026-06-23`
Start HEAD (HQA): `2939c04`

## Preflight (controller)

- Hermes Agent v0.18.2 (2026.7.7.2) confirmed
- source_checkout_commit: `4281151ae859241351ba14d8c7682dc67ff4c126` (matches plan)
- server.py SHA-256: `2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17` (matches plan)
- tracked Hermes source dirty: empty (clean)
- **Source review:** live `hermes --version` upstream identifier is now `b03c94db` (was plan-frozen `e4ea0a0e`). Checkout + server digest unchanged. Task 1 must record the new observed `upstream_commit` via source review, not silently keep the stale plan value nor invent values to pass tests.
- HQA git remote: **none configured** — commits local; push will fail until remote added. Platform has `origin`.
- Hard gates: no real Hermes chat mutation; candidate migration dry-run only; F0/F1 require written user approval; F2 read-only shell only.

## Plans

1. Gateway capability contract (HQA) — Tasks 1-4
2. Candidate integrity + Gate 3 (platform + HQA callers) — Tasks 1-8
3. Professional frontend shell (platform) — Tasks 1-9; F0/F1 user gates

## Task status

(none complete yet)

## Gateway Task 1: complete (commits 2939c04..1b461ef, review clean)
- Commit: 1b461ef feat(hqa): add fail-closed Hermes gateway capability contract
- Tests: 19/19 test_hermes_capabilities.py
- Review: Approved (ecc:python-reviewer), no Critical/Important
- Source review: upstream_commit b03c94db

## Gateway Task 2: complete (commits 1b461ef..34713d8, review clean)
- Commit: 34713d8 feat(hqa): expose Hermes chat readiness as strict JSON
- Tests: 20/20 test_hermes_capability_cli.py; live verify-chat exit 3
- Review: Approved, no Critical/Important
- Note: HQA has no git remote — cannot push until remote configured

## Gateway Task 3: complete (commits 34713d8..c767b75, review clean)
## Gateway Task 4: complete (commits c767b75..ea0b297, dual review CLEAR, blocked verdict committed)
- Stage A CLEAR (ecc:code-reviewer), Stage B CLEAR (ecc:security-reviewer)
- verify-chat exit 3 with contract_review_blocked + capability blockers
- HQA remote: none — push skipped

## Candidate Task 1: complete (commits 4933b89..5c8188a, review clean)
- Commit: 5c8188a feat(agent): unify API candidate root with CLI source of truth
- Platform push: attempted
- Tests: 60 passed focused suite

## Candidate Task 2: complete (commits 5c8188a..cb4d7e0, review clean after fix)
- 1741f74 feat + cb4d7e0 fix (FD leak, approval binding, root barrier)
- Tests: 80 passed
- Pushed to origin audit-remediation-2026-06-23

## Candidate Task 3: complete (cb4d7e0..ed3b9bb, review clean after fix)
- 51647d9 + ed3b9bb require expected_status CAS
- Pushed

## Candidate Task 4: complete (ed3b9bb..8aaa278, review clean)
- 8aaa278 recheck digest before research/promotion
- Pushed

## Agent routing policy (updated after user feedback)
- Prefer specialized agents; multi-reviewer gates when cross-layer.
- **Platform bug:** space-named types (Frontend Developer, Backend Architect, UI Designer, Code Reviewer, Reality Checker) are listed but spawn fails → use ecc:* slugs + general-purpose with role prompt for write paths.
- **Read-only specialists:** ecc:architect, ecc:code-architect, ecc:code-explorer (audit/design, not commit)
- **Backend implement:** ecc:tdd-guide, general-purpose (backend persona), review: ecc:python-reviewer, ecc:fastapi-reviewer, ecc:security-reviewer
- **Frontend implement:** general-purpose (frontend persona) until Frontend Developer spawn fixed; review: ecc:react-reviewer, ecc:typescript-reviewer, ecc:a11y-architect

## Candidate Task 5: complete (8aaa278..392485a platform + ea0b297..2f0c96d HQA)
- Triple review: fastapi Approved, react Approved, hqa python Approved
- Platform pushed; HQA no remote

## Candidate Task 6: complete (392485a..1a6f471, review clean after fix)
- a4252d5 migration + 1a6f471 backup verify/barriers
- Security Approved; Python Approved after fix
- Dry-run only on real data; --apply NOT run
- Pushed

## Candidate Task 7: complete (1a6f471..ae191be, dual review clean)
- ae191be Gate 3 isolated worktrees
- Security Approved; Python Approved
- Pushed

## Candidate Task 8: complete (ae191be..1589886 platform + a5d9cb1 HQA)
- Final security CLEAR (Tasks 1-7)
- Platform 1329 passed; HQA 579 passed
- Dry-run only; --apply not authorized
- Platform pushed

## Frontend Task 1 (F0): DRAFT ready — STOPPED at user gate
- Platform commit e24246f docs(frontend): draft Hermes F0 high-fidelity visual directions
- Pushed to origin
- Serve: http://127.0.0.1:4173/f0/direction-a.html (also b, c)
- Awaiting written user selection of A/B/C before F1

## Frontend Task 1 independent review: Ready for user selection
- UX (react-reviewer): Ready for user selection; B has mobile 390 caveat
- A11y: Ready for user selection
- Review notes committed de34e2b (no F0 decision recorded)
- **BLOCKED on user written choice:** direction-a | direction-b | direction-c

## Frontend F0: approved direction-a + premium polish
- User selected direction-a; demanded craft upgrade via awesome-design-md
- DESIGN.md refs: Linear/Raycast/Superhuman/Vercel/VoltAgent/...
- Commits: 9425da8 polish, 67ed590 grid fix, F0 decision in README
- Ship to F1 after grid re-verify (main 924 / secondary 288 @1440)

## Frontend F1: draft Ready for user approval
- Commit b0dab2b F1 prototype
- UX review Ready; a11y Ready
- Preview: http://127.0.0.1:4173/f1/prototype.html
- STOPPED for written user F1 approval before F2 production shell

## Frontend craft v3: finance/crypto desk (user rejected AI-purple look)
- Refs: Binance, Coinbase, Revolut, xAI, Claude, Ollama, Stripe, Wise (+ prior set)
- Layout: killed 288px rail; full-width stage; @1440 attention 1384px
- Visual: #0b0e11 canvas, amber attention, coral human-gate, purple glyph-only
- Commits: 97b9221 F0, 3c00ab3 F1, (+ density pass pending)
- Independent critique: Ready for user look
- Preview: http://127.0.0.1:4173/f0/direction-a.html and /f1/prototype.html

## Frontend token rebind + F1 approved
- Commit c5c614d QUANTUM_CORE palette on F0/F1
- Primary CTA #5EA2FF; success #089981; warning safety-only; hermes brand-only
- F1 approved by user with platform token alignment

## Frontend F2 complete (platform ab932f3)
- Token rebind QUANTUM_CORE (c5c614d)
- Tasks 3-9: view model, shell, today, routes, visual gates, cutover, docs
- Runtime smoke: API :8765 ok; FE :3001 /zh→/zh/hermes 307; hermes/tasks/approvals/results 200
- Hard-off chat/execution; Factor Lab etc preserved
- HQA docs cc74257 (no remote push)

## Wave-1 formal acceptance (user 2026-07-14)
User confirmed production Hermes shell is acceptable ("暂时没什么问题，可以先确定").
Three first-wave plans closed for implementation scope:

1. Gateway capability contract — delivered; verify-chat fail-closed / blocked review
2. Candidate integrity + Gate 3 — delivered; real --apply still unauthorized
3. Professional frontend + read-only shell — F0/F1 approved; F2 code delivered; chat hard-off

No further unchecked construction tasks remain inside those three plan task lists.
Next work requires NEW plans or explicit user gates:
- migration --apply (separate auth after dry-run JSON)
- bridge/chat only after verify-chat exit 0 + ready review
- Factor Lab / Backtester / Experiments / Agent Studio parity cutover

## Wave 2 (plan 2026-07-14-d31-wave2-bridge-approvals-parity) — 2026-07-14

Branch: HQA `codex/full-9h`; platform `audit-remediation-2026-06-23`.

### Task A — Candidate migration apply: DONE
- Real candidate `factor-momentum_20d_reversal-323b045e4b`: integrity=**verified**, approval_enabled=**True**, digest `294bbe7b846ae86384e56deae8ba8df2576ac6ffa8a5937e4f82a2352fdd8558`
- Evidence: platform candidate root `manifest.v1.json` present; Wave 2 runbook `.superpowers/sdd/wave2-sceneb-runbook.md`

### Task B — Hermes Approvals Gate 2 CAS UI: DONE (platform code)
- Commit platform `8052fe6` feat(frontend): Hermes Gate 2 CAS approvals + Tasks evidence read model
- Report: `.superpowers/sdd/wave2-approvals-tasks-report.md` (+ review notes)
- Controls only for approval_enabled + verified + pending; detail re-fetch digest; required note; CAS POST

### Task C — Hermes Tasks evidence read model: DONE (platform code)
- Same `8052fe6`: automation / weekly_review / opportunity_summary read-only; no task write ledger
- Report: `.superpowers/sdd/wave2-approvals-tasks-report.md`

### Task D — Scene-B operational smoke: PARTIAL (artifacts exist; final BLOCKED)
- Artifacts under HQA `data/_runtime/sceneb-wave2/`: propose.out (Gate 1), detail.out, approve.out (Gate 2), reviewed_factor.py, final-backtest.out
- Smoke candidate `factor-wave2_scene_b_smoke_momentum_20d_reversa-6106ea1c63` approved (digest `d69498a63de14ad2f4004d5329c9d23b47b075d257bda0b1468a1c2c036e40cf`); Gate1 binding under `data/_runtime/factor-gate1/`
- **final-backtest.out:** `candidate_load_refused` — factor_id `agent_candidate_low_vol_momentum` collides with existing candidate `factor-momentum_20d_reversal-323b045e4b`
- **No** successful final receipt; **no** Gate 3 promote/worktree/patch claimed
- Runbook: `.superpowers/sdd/wave2-sceneb-runbook.md` still marks full Gate1→final→Gate3 as not claimed

### Task E — Capability re-audit + read bridge scaffold: DONE
- HQA commit `753f153` fix(hermes): re-audit Wave 2 bridge readiness, ignore banner tip drift
- `installation.matches_snapshot=true`; `chat_write=false`; `verify-chat` exit **3**
- Scaffold: `hqa/hermes_read_bridge.py` + `tests/test_hermes_read_bridge.py`
- Report: `.superpowers/sdd/wave2-hermes-capability-reaudit.md`

### Task F — Page parity staged cutover: PARTIAL
- Soft banners DONE: platform `3400659` feat(frontend): soft Hermes parity banners on legacy research pages
- Inventory DONE (docs): `.superpowers/sdd/wave2-parity-inventory.md`
- **Not done:** deletion, hard redirects, ready-to-redirect for Factor Lab / Backtester / Experiments / Agent Studio

### Task G — Docs + verification: IN PROGRESS / docs portion
- HQA `docs/README.md` Wave 2 status table updated honestly
- Platform `docs/INDEX.md` D-31/Hermes status reconciled (migration apply + Gate 2 CAS + remaining gaps)
- Chat write remains blocked; old four pages not deleted

### Wave 2 remaining gaps (do not overclaim)
- Chat write/stream/resume (`verify-chat` ≠ 0; contract review blocked)
- Scene-B successful final one-shot + Gate 3 prepare + human commit
- Legacy four-page redirect/retirement after parity proof
- Platform BFF live read-bridge wiring / gateway port discovery (scaffold only)
- Push/remote: HQA still has no remote configured as of Wave 1 notes

## Wave 2 Scene-B smoke (controller 2026-07-14 cont)
- Gate1+Gate2+final+Gate3 prepare DONE for v3 candidate
- receipt backtest-f4da78d66b4ee6eaab6e7226740ac6ac promo promo-7c8a74e9c333a2eb1eadc49ab488c24d
- Human commit NOT done
- Bridge wire HQA 6bb366c; docs 6f5856f; platform property fix pending push

## Wave 2 cont — live read bridge
- session.list live OK on 9119 with session token (chat_ready still false)
- HQA commits: 6bb366c wire, token auth commit, 32fb201 docs, Scene-B evidence
- Platform 4263b7f property fix pushed
