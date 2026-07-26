# Hermes v0.2.1 Closure and v0.3 Research Workbench — Spec Index

**Status:** design suite entry point  
**Date:** 2026-07-27  
**Safety:** local-only, single operator, paper/research only; public write OFF; no live trading

This file is the **index**, not the sole normative authority. Implementation planning and coding MUST follow the five standalone specifications below. If this index and a standalone specification disagree, the standalone specification wins.

## Delivery Decision

1. **v0.2.1 closes the current release line first.**
2. **v0.3 starts only after v0.2.1 reaches verdict `CLOSED`.**
3. **v0.3 priority order is stability → research capability → Hermes experience.**
4. **UI remains inside the approved F2/D-31 frame:** existing global platform sidebar + lightweight Hermes tabs + full-width main stage. No permanent `fat side-nav | narrow center | permanent right rail`.
5. **Legacy Factor Lab / Experiments / Backtester retirement is not bundled with layout approval.** Migration remains page-local expand → parity → cutover → contract, with server-side parity seal authority.
6. **Three backend contracts are delivered and activated in order 1 → 2 → 3**, hermetic first, public write never opened by these contracts.
7. **UI richer surfaces activate only after the corresponding contract tests and real-data integration pass.**

## Normative Specification Suite

| Order | Document | Authority |
|---|---|---|
| 0 | [v0.2.1 Closure Design](2026-07-27-hermes-v0-2-1-closure-design.md) | Preservation, repository identity, recovery, clean integration, mandatory zero-effect safety proof, detached evidence seal, finite stop rules |
| 1 | [v0.3 Master Design](2026-07-27-hermes-v0-3-master-design.md) | Information architecture, page composition, capability admission, sample/real labels, legacy parity seal, delivery sequence |
| 2 | [Contract 1 — Immutable Task Progress](2026-07-27-hermes-v0-3-contract-1-immutable-task-progress.md) | Immutable `execution_progress_plan`, `step_completed`, derived `completed/total`, workspace wire, ledger vs observation separation |
| 3 | [Contract 2 — Wall-Clock Budget](2026-07-27-hermes-v0-3-contract-2-wall-clock-budget.md) | Absolute deadline binding, authority-locked enforcement, `budget_exceeded`, layered stop/reconcile, v3 migration that preserves Contract 1 |
| 4 | [Contract 3 — Backtest Comparison](2026-07-27-hermes-v0-3-contract-3-backtest-comparison.md) | Deterministic real-only comparison, regime/cost/capacity axes, ranking, `proposal_only` recommendation, no auto-promote |

## Contract Activation Order

1. **Contract 1 readers** → Contract 1 writers → progress UI (`3/4`, derived bar, authoritative step checks).
2. **Contract 2 parsers/shadow** → hermetic enforcement → budget UI and recovery state.
3. **Contract 3 evidence reader/validate-only** → production proposal capability → ranking/`proposal_only` UI.

Each step requires hermetic acceptance, exact committed revision evidence, and fail-closed capability flags. Sample/hermetic/test-synthetic data must remain visibly labeled and must not enter production proposal paths.

## Standing Non-Goals

Across the whole suite:

- no public/browser/chat write standing grant;
- no change to defaults `kill_switch=true`, `live_trading_enabled=false`, `release_authorized=false`, public write OFF;
- no live broker adapter or real order path;
- no auto-approval, auto-registration, or auto-promotion;
- no treating `N/N`, `budget_exceeded`, ranking, or `proposal_only` as authorization;
- no mechanical resurrection of rejected three-column shell geometry;
- no legacy route deletion without page-specific parity seal and observation period.

## Implementation Entry

After human review of this suite:

1. create the detailed implementation plan from the five normative documents;
2. execute **v0.2.1 closure** to verdict `CLOSED`;
3. implement and accept **Contract 1**, then **Contract 2**, then **Contract 3**;
4. activate corresponding UI surfaces only after each contract gate;
5. keep documentation, hermetic receipts, and Git commits synchronized per delivery step.

Do not begin product-code implementation from this index alone.
