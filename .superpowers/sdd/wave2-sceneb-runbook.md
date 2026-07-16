# Wave 2 Scene-B Operational Smoke Runbook

> Updated after successful v3 smoke (Gate1→Gate2→final→Gate3 prepare).

## Authoritative smoke candidate

| Field | Value |
|---|---|
| ID | `factor-wave2_scene_b_smoke_v3_loadable_factor-da01df1188` |
| integrity | verified |
| status | approved (Gate 2) |
| manifest_digest | `5ca064d597778b45f1a718047becf5b67b30cf9b24d441632b3a408cfd1c227d` |
| Gate 1 | `gate1-67ccff3217cdeefb6e22ed276923c14d` |
| Final receipt | `backtest-f4da78d66b4ee6eaab6e7226740ac6ac` |
| Gate 3 promo | `promo-7c8a74e9c333a2eb1eadc49ab488c24d` (`awaiting_human_commit`) |

Migrated legacy candidate `factor-momentum_20d_reversal-323b045e4b` remains verified for Approvals UI; it is **not** the Scene-B smoke path (no Gate1 binding; factor_id collides if re-proposed as stub).

## Path executed

```text
HQA propose (Gate 1) → HQA approve (Gate 2 CAS)
  → HQA backtest --final (Futu)
  → HQA promote (Gate 3 prepare only)
  → human git commit in isolated worktree  ← NOT DONE
```

Full evidence: `wave2-sceneb-smoke-evidence.md`.
