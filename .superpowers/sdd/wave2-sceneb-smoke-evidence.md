# Wave 2 Scene-B operational smoke evidence

**Date:** 2026-07-14  
**Status:** Gate 1 → Gate 2 → final receipt → Gate 3 **prepare + human commit** DONE.  
**Human Gate 3 commit:** DONE (`524e791`, user-authorized).

## Successful path (v3 loadable factor)

| Stage | Result |
|---|---|
| Gate 1 propose | `gate1-67ccff3217cdeefb6e22ed276923c14d` |
| source_digest | `73e05452ff71dc702575f71fb45883eff3f5e1fe85386b5d7d22c5b01da0f699` |
| candidate_id | `factor-wave2_scene_b_smoke_v3_loadable_factor-da01df1188` |
| manifest_digest | `5ca064d597778b45f1a718047becf5b67b30cf9b24d441632b3a408cfd1c227d` |
| Gate 2 approve | CAS approve with explicit note; registration `manual_required` |
| final backtest | provider **futu**; window 2024-01-01→2024-12-31; SPY,QQQ |
| experiment_id | `factor-repro-factor-wave2_scene_b_smoke_v3_loadable_factor-da01df1188-20260714T081725342994Z-efb2967ebb21` |
| best_run_id | `run-001` |
| final_backtest_receipt | `backtest-f4da78d66b4ee6eaab6e7226740ac6ac` |
| sharpe / return / mdd | 1.037 / 0.152 / 0.110 (research only) |
| Gate 3 promote | `promo-7c8a74e9c333a2eb1eadc49ab488c24d` |
| status | **reviewed → cleaned** (`promo-b7bbab8…`, commit `524e791`) |
| worktree | `/private/var/folders/.../ai-quant-platform-gate3-worktrees/promo-7c8a74e9c333a2eb1eadc49ab488c24d` |
| scoped_paths | promoted factor + `__init__.py` + unit test |

## Artifact locations (HQA)

- `data/_runtime/sceneb-wave2/reviewed_factor_v3.py`
- `data/_runtime/sceneb-wave2/propose3.out`
- `data/_runtime/sceneb-wave2/approve3.out`
- `data/_runtime/sceneb-wave2/final-backtest-v3.out`
- `data/_runtime/sceneb-wave2/promote-v3.out`
- Receipt/report under `data/_runtime/factor-experiments/`

## Failures learned (documented, not greenwashed)

1. Reusing migrated stub factor_id `agent_candidate_low_vol_momentum` → collision with verified legacy candidate.
2. Stub template with `@property` + missing `default_lookback` → load refused until:
   - platform added `property` to candidate safe builtins (`promotion.py`)
   - smoke factor rewritten with `default_lookback=20` + `direction`
3. Earlier candidates (`…6106ea1c63`, `…5cce56cd72`) remain as approved/pending evidence of failed attempts; **authoritative smoke ID is v3**.

## Human next step (Gate 3 completion)

```bash
cd "$(python3 -c 'import json;print(json.load(open("/Users/sunyibo/programs/ai-quant-platform/data/agent_run/agent/promotions/promo-7c8a74e9c333a2eb1eadc49ab488c24d/manifest.v1.json"))' 2>/dev/null)" # or use worktree path from promote stdout
# In isolated worktree only:
git diff
# Review three scoped files only, then human commit if accepted
# Then: quant-system agent promotion-status --promotion-id promo-7c8a74e9c333a2eb1eadc49ab488c24d
# cleanup-promotion only after explicit policy
```

Do **not** auto-commit, merge to main dirty tree, or push promotion from agents.

## Safety

- paper_trading / live_trading_enabled=false / kill_switch unchanged
- No broker/paper mutation
- Gate 3 never auto-committed


## Gate 3 human completion (authorized 2026-07-14)

User authorized Gate 3 commit. First prepare `promo-7c8a74e9…` was abandoned
due to main HEAD drift (base `9866da4` → `4263b7f` property fix). Re-prepared
and completed:

| Field | Value |
|---|---|
| promotion_id | `promo-b7bbab8cf571a5f4ff43aa652aebf3bc` |
| base_commit | `4263b7f16494b1c2c24f6c9f499f8967c6c3086f` |
| reviewed_commit | `524e791e5e3e22cec12a4166ad8fc3617c735566` |
| branch | `codex/promotion-promo-b7bbab8cf571a5f4ff43aa652aebf3bc` |
| promotion-status | **reviewed** |
| cleanup-promotion | **cleaned** |
| main merge | ff-only onto `audit-remediation-2026-06-23` |
| factor_id | `agent_candidate_wave2_sceneb_mom20_v3` |

Scaffold tests: `tests/factors/test_agent_candidate_wave2_sceneb_mom20_v3.py` green.
