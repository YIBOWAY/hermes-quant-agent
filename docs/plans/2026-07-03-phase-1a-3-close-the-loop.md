# Phase 1a-3 — Close-the-Loop Implementation Plan (D-20/D-21/D-22/D-23)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two verified gaps between "backtest report" and "paper money allocated":
(1) approved candidate factors are invisible to the frontend factor catalog
(`api/routes/factors.py:33` builds only the default registry), and (2) approved
candidates cannot drive a strategy sleeve
(`paper_strategy_signal_service.py:188-192` raises `KeyError` for candidate
factor_ids via `registry.py:31-36`). Ship the third human gate — deterministic
**promote-to-code** (D-20) — plus the anti-overfit disciplines (D-21) and the
`--json` CLI contract (D-22), with the registry factory consolidation (D-23).

**Architecture:** Two repos. Platform gains a single registry factory, a
`/factors` catalog that can show approved candidates with provenance, a
deterministic `agent promote-candidate` command (produces a working-tree diff,
NEVER commits — the human `git diff` review + commit IS Gate 3), and `--json`
output on the four commands HQA consumes. HQA gains JSON-first parsing (regex
fallback), a per-factor trial counter with an overfit warning, a default
6-month holdout cut on Scene-B backtests, and a hard ≥30-paper-days criterion
in `hqa-gate`. **The sleeve signal path never execs `.candidate` files**: the
restricted-exec loader stays confined to one-shot backtests
(`run-config --include-approved-candidates`); the resident trading path only
sees promoted, code-reviewed, registered factors.

**Tech Stack:** Platform: Python 3.11 · typer · pydantic · `./.venv/bin/python -m pytest -q`. HQA: Python 3.9 stdlib only · `./.venv/bin/pytest`.

## Global Constraints

- **Three human gates, none automatable:** Gate 1 = translation confirm (in
  Hermes session, before propose). Gate 2 = `agent review --decision approve`
  (human-only CLI/UI). Gate 3 = `git diff` review + commit of the promotion
  diff (human-only; `promote-candidate` must never invoke git).
- **Promotion prerequisites enforced in code:** `promote-candidate` refuses
  unless `approved.lock` exists (SafetyGate), the AST safety check passes
  (reuse `promotion._check_source`), and the target module does not already
  exist. It is deterministic — no LLM, no network.
- **Resident-path purity:** `PaperStrategySignalService` keeps
  `include_approved=False` semantics — it must only ever see the default
  (examples + promoted) registry. No exec of candidate text in any resident
  process.
- **D-14 unchanged:** real backtests stay `--provider tiingo`; `sample`/`stub`
  remain unit-test-only.
- **HQA Python 3.9 compat:** every HQA module starts with
  `from __future__ import annotations`; stdlib only.
- **Baselines before this phase:** HQA `77 passed, 1 skipped` (after 1a-2);
  platform: record `./.venv/bin/python -m pytest -q` baseline first,
  acceptance = baseline + new, no NEW failures.

---

## File Structure

```
ai-quant-platform (PLATFORM repo):
  src/quant_system/factors/registry.py        # + build_factor_registry(...) factory
  src/quant_system/factors/library/promoted/  # NEW package: one module per promoted factor
      __init__.py                              #   regenerated PROMOTED_FACTORS tuple
  src/quant_system/agent/promote.py            # NEW: promote_candidate() (D-20)
  src/quant_system/cli.py                       # + agent promote-candidate; + --json on 4 cmds
  src/quant_system/api/routes/factors.py       # /factors gains include_candidates + origin
  src/quant_system/api/schemas/factors.py      # + origin field
  tests/test_factor_registry_factory.py         # NEW
  tests/test_agent_promote.py                   # NEW
  tests/test_cli_json_output.py                 # NEW

Hermes-quant-agent (HQA repo):
  hqa/factor_repro.py       # + parse_json_payload() JSON-first, regex fallback
  hqa/trials.py             # NEW: append_trial(), count_trials(), overfit_warning()
  hqa/holdout.py            # NEW: effective_backtest_end() (D-21 ②)
  hqa/factor_repro_cli.py   # backtest: holdout default + --final + trial warning
  hqa/gate.py               # + paper_days_completed >= 30 criterion
  tests/test_factor_repro.py, test_trials.py, test_holdout.py,
  tests/test_factor_repro_cli.py, test_gate.py   # extend
```

---

### Task P1 (PLATFORM): registry factory consolidation (D-23)

**Files:** Modify `src/quant_system/factors/registry.py`; create
`src/quant_system/factors/library/promoted/__init__.py` (empty
`PROMOTED_FACTORS: tuple = ()` initially); modify the four verified call
sites; create `tests/test_factor_registry_factory.py`.

**Interface:**

```python
def build_factor_registry(
    *,
    include_promoted: bool = True,
    include_approved_candidates: bool = False,
    candidates_dir: str | Path | None = None,
) -> FactorRegistry:
    """Single construction point. Examples always; promoted by default;
    approved candidates only when explicitly requested (one-shot research)."""
```

- `build_default_factor_registry()` becomes a thin alias
  (`build_factor_registry()`) so untouched call sites keep working.
- Call-site policy (verified 2026-07-03):
  - `api/routes/factors.py:33` → factory with
    `include_approved_candidates=True` behind a query param (Task P2).
  - `factors/lab.py:53` → factory (promoted visible in Factor Lab data).
  - `execution/paper_strategy_signal_service.py:188` → factory with
    `include_approved_candidates=False` **hardcoded** (resident-path purity;
    add a comment stating D-20's rule).
  - `cli.py` run-config branch keeps calling
    `load_approved_factor_candidates` explicitly (already correct).

- [ ] Step 1: failing test — factory returns examples+promoted by default;
  `include_approved_candidates=True` with a tmp candidates dir containing an
  approved candidate registers it; `False` does not; promoted package with a
  stub factor class in `PROMOTED_FACTORS` gets registered.
- [ ] Step 2: run → fail (no `build_factor_registry`).
- [ ] Step 3: implement factory; rewire the call sites listed above.
- [ ] Step 4: platform suite green (baseline + new).
- [ ] Step 5: commit `feat(factors): single registry factory; promoted library package (D-23)`.

---

### Task P2 (PLATFORM): /factors catalog shows approved candidates with provenance

**Files:** Modify `src/quant_system/api/routes/factors.py`,
`src/quant_system/api/schemas/factors.py`; extend
`tests/test_factor_registry_factory.py` (API section).

**Interface:** `GET /factors?include_candidates=true` → each item gains
`origin: "builtin" | "promoted" | "candidate"`. Default (`false`) returns
builtin+promoted only, so existing consumers see no behavior change beyond the
additive field. Candidate loading reuses the factory from Task P1 with the
same candidates dir the CLI uses (`data/agent_run/agent/candidates` — mirror
the `--candidates-dir` default in `cli.py:677`).

- [ ] Step 1: failing test — API client: default call has no `candidate`
  origins; `?include_candidates=true` lists the approved tmp candidate with
  `origin="candidate"`; a pending (un-approved) candidate never appears.
- [ ] Step 2: run → fail.
- [ ] Step 3: implement (origin computed from which registration pass added
  the factor_id; keep it in the factory's return metadata, not by re-parsing).
- [ ] Step 4: suite green.
- [ ] Step 5: commit `feat(api): /factors provenance + opt-in approved candidates`.

---

### Task P3 (PLATFORM): `agent promote-candidate` — deterministic Gate-3 diff (D-20)

**Files:** Create `src/quant_system/agent/promote.py`; wire
`agent promote-candidate` into `cli.py`; create `tests/test_agent_promote.py`.

**Interface:**

```python
def promote_candidate(
    candidate_id: str,
    *,
    candidates_dir: Path,
    library_dir: Path,   # src/quant_system/factors/library/promoted
    tests_dir: Path,     # tests/factors
) -> PromotionResult:   # {factor_id, module_path, test_path, init_path}
```

Behavior (all verified against existing seams):

1. Refuse unless `SafetyGate(candidates_dir).allow_promotion(candidate_id)`
   (approved.lock present, no rejected.lock — `agent/safety.py:21-31`).
2. Run `promotion._check_source` (AST allowlist) on
   `<candidate_dir>/factor.py.candidate`; refuse on violation.
3. Extract the `BaseFactor` subclass and its `factor_id` (static AST read of
   the class body / metadata — no exec needed for discovery; refuse if zero or
   multiple factor classes).
4. Write `library/promoted/<factor_id>.py` = candidate source verbatim + a
   provenance header comment (`candidate_id`, approval note path, date).
   Refuse if the module already exists (idempotence guard).
5. Regenerate `library/promoted/__init__.py` deterministically (sorted
   imports, `PROMOTED_FACTORS` tuple).
6. Write a test scaffold `tests/factors/test_<factor_id>.py` (constructs the
   factor, asserts metadata fields present, computes on a tiny synthetic
   OHLCV frame without NaN explosion).
7. **Never touches git.** CLI prints the file list and:
   `GATE 3 — review the diff and commit yourself: git diff -- <paths>`.

- [ ] Step 1: failing tests — happy path writes 3 files & regenerated init
  imports the new module; un-approved candidate → refuse; AST-violating
  source → refuse; second promotion of same factor_id → refuse; result
  factor_id matches the class metadata; **no `.git` mutation** (assert no
  subprocess/git import in `promote.py`).
- [ ] Step 2: run → fail.
- [ ] Step 3: implement `promote.py` + CLI command
  (`agent promote-candidate --candidate-id <id> [--candidates-dir ...]`).
- [ ] Step 4: suite green; then a manual end-to-end sanity: promote the
  existing on-disk candidate `factor-momentum_20d_reversal-323b045e4b`
  (approve it first if pending), inspect `git diff`, then `git checkout --`
  the generated files (leave the repo clean — this plan does not decide that
  factor's promotion).
- [ ] Step 5: commit `feat(agent): promote-candidate deterministic Gate-3 diff (D-20)`.

---

### Task P4 (PLATFORM): `--json` contract on the four HQA-consumed commands (D-22)

**Files:** Modify `src/quant_system/cli.py`; create `tests/test_cli_json_output.py`.

**Interface:** `--json` flag → exactly one JSON object on the LAST stdout line
(human lines may precede it; HQA parses the last line). Shapes:

- `agent propose-factor --json` → `{"candidate_id", "status", "path", "metadata_path"}`
- `agent review --json` → `{"candidate_id", "decision", "registration": "manual_required"}`
- `experiment run-config --json` → `{"experiment_id", "run_count", "best_run_id", "agent_summary", "report", "approved_candidates_loaded": [...]}`
- `doctor --json` → `{"environment", "safety": {"dry_run", "paper_trading", "live_trading_enabled", "kill_switch"}, "ok"}`

Existing key=value lines are UNCHANGED when `--json` is absent (HQA regex
fallback keeps working; no consumer breaks mid-migration).

- [ ] Step 1: failing tests — each command with `--json`: last line parses,
  required keys present; without `--json`: byte-identical legacy format
  (regression-pin one representative line per command).
- [ ] Step 2: run → fail.
- [ ] Step 3: implement (shared `_emit_json(payload)` helper; `typer.echo(json.dumps(..., sort_keys=True))`).
- [ ] Step 4: suite green.
- [ ] Step 5: commit `feat(cli): --json contract for HQA consumers (D-22)`.

---

### Task H1 (HQA): JSON-first parsing with regex fallback (D-22)

**Files:** Modify `hqa/factor_repro.py`, `hqa/quant_cli.py`,
`tests/test_factor_repro.py`, `tests/test_quant_cli.py`.

**Interfaces:**

- `factor_repro.parse_json_payload(output: str) -> Optional[dict]` — parse the
  last non-empty stdout line as JSON; `None` if not JSON.
- `parse_candidate_id` / `parse_experiment_summary` try JSON first, fall back
  to the existing regex/`partition("=")` paths (fallback stays covered by the
  existing tests).
- `quant_cli.run_propose_factor/run_agent_review/run_experiment_config/run_doctor`
  append `--json` to their argv.

- [ ] Step 1: failing tests — JSON last-line parsed; mixed human-lines+JSON
  parsed; legacy-only output still parsed via fallback; argv now ends with
  `--json`.
- [ ] Step 2: run → fail.
- [ ] Step 3: implement.
- [ ] Step 4: `./.venv/bin/pytest -q` green.
- [ ] Step 5: commit `feat: JSON-first platform CLI parsing, regex fallback (D-22)`.

---

### Task H2 (HQA): trial counter + overfit warning (D-21 ①)

**Files:** Create `hqa/trials.py`, `tests/test_trials.py`.

**Interfaces:**

```python
def append_trial(factor_id: str, record: dict, log_path: Path) -> None
def count_trials(factor_id: str, log_path: Path) -> int
def overfit_warning(factor_id: str, n: int, threshold: int = 3) -> str
    # "" when n < threshold, else the warning text
```

Log: `logs/factor_trials.jsonl`, one line per backtest run:
`{"ts", "factor_id", "start", "end", "final": bool, "sharpe": ...}`.
Warning text (≥3rd trial): `OVERFIT WARNING: trial N for <factor_id> — 回测结果可信度随迭代次数下降；参考 D-21/复盘库，考虑 holdout --final 或收手`.

- [ ] Step 1: failing tests — append+count round-trip; missing log → 0;
  warning empty at n=2, non-empty at n=3.
- [ ] Step 2: run → fail. Step 3: implement. Step 4: green.
- [ ] Step 5: commit `feat: per-factor trial counter with overfit warning (D-21)`.

---

### Task H3 (HQA): default holdout cut + `--final` (D-21 ②)

**Files:** Create `hqa/holdout.py`; modify `hqa/factor_repro_cli.py`;
`tests/test_holdout.py`, `tests/test_factor_repro_cli.py`.

**Interfaces:**

```python
HOLDOUT_DAYS = 183
def effective_backtest_end(start: str, end: str, final: bool) -> tuple[str, str]
    # final=True → (end, "")
    # else → (end - 183d ISO, note text); raises ValueError if cut end <= start
```

`factor_repro_cli backtest` gains `--final` (default off). Non-final runs:
config written with the CUT end date; stdout prints
`HOLDOUT: last 183 days reserved; run --final ONCE before promotion (D-21)`.
Every run (final or not) appends a trial record (Task H2) and prints the
overfit warning when due. `--final` runs are also recorded (`"final": true`).

- [ ] Step 1: failing tests — cut math (ISO dates, 3.9-compatible
  `datetime.date.fromisoformat`); window-too-short raises; CLI non-final
  writes cut end into the experiment config + prints HOLDOUT note; `--final`
  writes the full end; 3rd run prints OVERFIT WARNING.
- [ ] Step 2: run → fail. Step 3: implement. Step 4: green.
- [ ] Step 5: commit `feat: default 6-month holdout on Scene-B backtests (D-21)`.

---

### Task H4 (HQA): full-month criterion in the acceptance gate (D-21 ③)

**Files:** Modify `hqa/gate.py`, `tests/test_gate.py`.

**Interface:** `check_strategy` adds a fifth criterion:
`add("paper_month", cfg.get("paper_days_completed", 0) >= 30, "needs paper_days_completed >= 30 (D-21)")`.
Existing four criteria unchanged; a config passing today with no
`paper_days_completed` must now FAIL overall.

- [ ] Step 1: failing tests — config with `paper_days_completed=30` + prior
  fields passes; 29 fails; absent fails; result list length now 5.
- [ ] Step 2: run → fail. Step 3: implement. Step 4: full HQA suite green.
- [ ] Step 5: commit `feat: gate requires >=30 paper days before broker-sim promotion (D-21)`.

---

### Task 6: docs governance sweep (D-24) + runbook

- [x] Step 1 (HQA repo): this plan + roadmap/header edits applied in the
  2026-07-03 neat-freak doc-source cleanup. Commit remains a human/project
  milestone decision, not an automated requirement of the cleanup;
  `docs/design/hermes_quant_agent_plan.md` header gains one line: 「路线与阶段以
  `2026-07-01-roadmap-phases-0b-4.md` 决策台账（D-1…D-24）为准；本文为背景调研与
  总设计，个别章节可能已被台账取代」.
- [x] Step 2 (PLATFORM repo, per D-24): `git mv docs/phases/phase_11*.md
  docs/phases/phase_12*.md docs/phases/phase_13*.md docs/phases/phase14*.md
  docs/archive/phases/`; prepend to `phase_15_iteration_roadmap.md`: 「⚠️ 迭代
  治理已移交 Hermes-quant-agent（D-18，2026-07-03）：平台不再独立按本文迭代，
  P0 永久保持，P1/P2 按 Hermes 需求拉动，P4/P5 由 Hermes 工作台承接（D-17），
  P3 推迟。本文余下内容仅作素材保留」; add the mutual pointer line to the
  platform `AGENTS.md`. Applied in the same cleanup; final commit/push is still
  separate.
- [ ] Step 3: end-to-end runbook (human-run, after P1–P4 + H1–H3 land):

```text
GATE 1 (Hermes 会话): 论文 → 因子定义蒸馏 → 你确认 → 代码写入 /tmp/factor_src.py
$ python3 -m hqa.factor_repro_cli propose --goal "<confirmed>" --source-file /tmp/factor_src.py
GATE 2: cat …/candidates/<id>/factor.py.candidate → 审码
$ python3 -m hqa.factor_repro_cli approve --candidate-id <id> --note "translation confirmed"
$ python3 -m hqa.factor_repro_cli backtest --factor-id <fid> --symbol SPY --symbol QQQ \
    --start 2020-01-02 --end 2026-06-30          # holdout 自动截断，末 183 天保留
  …迭代 ≤2 次；第 3 次起出现 OVERFIT WARNING…
$ python3 -m hqa.factor_repro_cli backtest ... --final    # 转正前唯一一次全窗口
GATE 3 (平台仓库): quant-system agent promote-candidate --candidate-id <id>
$ git diff        # 人工审查生成的 library/promoted/<fid>.py + 测试脚手架
$ git add -A && git commit -m "promote: <fid> (Gate 3)"
前端 /factors 与 paper-trading 页现在都能看到 <fid> → 创建 strategy config
（factor_ids=[<fid>]）→ 建 sleeve → 分配 sleeve cash → 纸面模拟开始跑。
30 天后 hqa-gate check 才可能放行进入 1b 券商模拟讨论。
```

---

## Phase 1a-3 Acceptance (maps to roadmap §2.6)

- [ ] 一篇论文 → Gate1 → Gate2 → 回测报告 → Gate3（diff 审查+人工 commit）→
  `/factors` 可见 → sleeve 分配 cash 跑纸面模拟：全程零手写代码，三道门均无
  代码路径可绕过（P3 的 no-git 断言、gate 的人工 CLI、review 的 approve.lock）。
- [ ] 常驻交易路径（sleeve 信号服务）永不加载候选文件；只有 promoted 模块。
- [ ] `hqa-factor-repro backtest` 同一 factor_id 第 3 次运行打印 OVERFIT
  WARNING；非 `--final` 运行自动保留末 183 天 holdout。
- [ ] `hqa-gate check` 缺 `paper_days_completed>=30` 必不放行。
- [ ] 平台 4 命令 `--json` 最后一行可解析；无 `--json` 时输出与旧版逐字节一致。
- [ ] 两仓库测试全绿（各自 baseline + new）。

## Self-Review

**1. 断点覆盖：** 断点 1（前端目录不可见）由 P1+P2 修复；断点 2（sleeve 不可用）
由 P3 转正路径修复——且是唯一路径，拒绝了"sleeve 直接 exec 候选"的捷径（审计
困难、违反 phase_15 因子代码化纪律）。
**2. 三门完整性：** Gate 3 的强制力来自 promote 命令 no-git + 人工 commit；
测试断言 `promote.py` 不含 git 调用。
**3. 迁移安全：** `--json` 为增量 flag，旧输出逐字节回归钉死；HQA 正则兜底
保留，两仓库可分开合入。
**4. D-21 落地位置：** 试验计数/holdout 在 HQA（研究纪律属编排层）；满月门槛
在 `hqa-gate`（晋级判定属治理层）；平台不掺 LLM 也不掺纪律逻辑，职责清晰。
