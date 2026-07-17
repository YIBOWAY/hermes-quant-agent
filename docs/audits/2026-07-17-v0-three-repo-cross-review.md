# Agent v0.2 · Slice V0 三仓 Cross-Review

> 审计日期：2026-07-17。本文是对 Agent Workspace v1 ADR 的三仓一致性只读核查快照，**不是新的执行计划，也不授权任何 live effect**。核查方式：只读 `git`/`ls`/`ps`/合同文件比对；未 checkout、未 build、未启停进程、未 install、未 live apply migration、未触发任何 provider / paper / live / broker / Gate / redirect。

## 结论

**V0 = HQA-side DONE / 三仓 PENDING → 整体 NOT DONE。**

- **HQA 侧合同候选已交付且自洽**：5 个 `hqa/agent_workspace_*` 合同模块（~2541 行）+ 5 个测试模块（**622 个测试全绿**），并经一轮 11-agent 对抗性评审（五维全部 `on-track-with-gaps`、零核心 invariant 违例、唯一确认的硬伤 astimezone `OverflowError` 已于 `5775d9a` 修复并附回归测试）。
- **三仓 manifest 一致性尚未闭环**：ADR 假设三仓都落在各自 candidate 分支、冻结在指定 base。现实是**三个 candidate 分支都不存在**；platform 恰在冻结 commit 但位于别的分支且工作区 dirty；Hermes 的冻结 base 不在本地 checkout 历史中。按 ADR 自己的 fail-closed 规则（source 不匹配 / dirty 未声明 / identity 漂移 → 全部 write readiness 与 live Gate fail closed），platform 与 Hermes 两条腿今天都会 fail-closed。

这与 ADR 自述 "V0 NOT DONE / PRIMARY VALIDATION PENDING" 一致——它是诚实的，不是阻塞 HQA 合同本身正确性的信号。**DurableRunAuthority（Hermes 腿）是 V2 工作，本就不属于 V0。**

## 三仓逐项核查

| 仓 | ADR 冻结 candidate 分支 | ADR 冻结 base | 现实 checkout / 分支 | base 是否在历史中 | 工作区 | 判定 |
|---|---|---|---|---|---|---|
| HQA | `codex/agent-v0-2-limited-device` | `a7428b6219ded…1724f` | `codex/full-9h` @ `5775d9a`（V0 已 fully merged，`merge-base = 3a95dd0`） | ✅ base 与 `git rev-parse a7428b6` 完全一致 | 干净 | ✅ 合同已交付+测试全绿；candidate 分支已被 FF 合并吸收 |
| ai-quant-platform | `codex/agent-v0-2-platform-limited-device` | `7b73b5f2fe9e…c58fc9d` | `audit-remediation-2026-06-23` @ `7b73b5f2`（恰为冻结 commit） | ✅ base 是 HEAD 祖先 | **dirty**（options 数据/代码 + untracked） | ⚠️ commit 匹配但**分支名不符**、**dirty 未声明** |
| Hermes | `codex/agent-v0-2-durable-runs` | `a79b81836070…6ecc2e` | `main` @ `9baa7d467`（**落后 origin/main 385 提交**） | ❌ base **不在**本地 checkout 历史（仅在 origin/main） | 干净（editable install v0.18.2，install==checkout，两进程一致） | ❌ candidate 分支不存在、base 未拉取 → manifest 腿 fail-closed |

### 关键佐证

- **platform migration 006 cardinality 冲突属实**（证实 ADR Scheme A 分析）：
  `ai-quant-platform/scripts/sql/006_hermes_workflow_binding.sql` 同时带 `UNIQUE(task_id)`（:129，并在 :193-194 的 guard 块每次重放重建）与 `UNIQUE(attempt_id)`（:130）；**全库无 `UNIQUE(task_id, attempt_number)`**（`attempt_number` 仅是 :105 的列）。这与 ADR cardinality 矩阵的 **Research Task 1:N Attempt**（ADR:94）直接冲突。
  migration runner `run_migrations`（`src/quant_system/storage/database.py:150-207`）按字典序**全量重放** `scripts/sql/*.sql`；006 的 guard 块会重建 `UNIQUE(task_id)`，故"补 007"在一次 fresh 有序重放中会在到达 007 前先重建旧约束——**证实 ADR"当前 replay-all runner 下禁止追加 007"成立**。当前最高 migration 即 006，**无 007**，原地修订无编号冲突。
- **Hermes 合同与现实一致**：已评审的 `docs/contracts/hermes-api-server-0.18.2.md`（checkout `9baa7d467`、`api_server.py` SHA-256、`127.0.0.1:8642` listener PID 26485）与实机完全对上；老 TUI gateway 合同正确自标 mismatched/fail-closed。即 **Hermes 现状被现有合同如实覆盖**，缺的只是 ADR 为 V2 冻结的 `durable-runs` candidate 分支——尚未创建/拉取。
- **HQA frozen base 无笔误**：ADR 表与计划 addendum 的 `a7428b6219ded4550f4c8951b6fabc4542a1724f` 与 `git rev-parse a7428b6` 逐字符一致。

## 边界与未触发项

本次 cross-review **仅记录现状，不改动三仓**：未在 platform 建 candidate 分支、未触碰其 dirty 文件、未拉取/切换 Hermes checkout、未启动/停止任何进程、未 install、未 live apply migration。

## 关闭 V0 还需（不属于本次范围）

1. 在 platform 与 Hermes 各自创建/对齐 ADR 命名的 candidate 分支，并把 Hermes checkout 推进到含 `a79b8183` 的状态（V2 前置）。
2. 在 primary 环境跑三仓 full suite 并签名（primary validation）。
3. platform 工作区 dirty 的显式处置（按 ADR fail-closed 规则须声明或清理）。

详见计划 `docs/superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md` §7 Slice V1/V2。
