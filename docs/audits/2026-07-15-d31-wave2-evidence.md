# D-31 Wave 2 事实验收与 Gate 3 证据

> 证据日期：2026-07-15。本文是已完成事实的审计快照，不是新的执行计划。

## 结论

Wave 2 的 Scene-B 三道人类门已经真实闭合：Gate 1 精确源码确认与候选绑定、Gate 2
digest/status CAS、Futu final receipt、Gate 3 隔离 diff 人工复核/commit、reviewed、cleanup，
最终因子已进入平台 promoted registry。此前“Gate 3 人类 commit 未完成”的说法已经过期。

这不等于完整 D-31 已完成。当前只新增了 official Hermes session GET 的只读 BFF；网页
chat write、Hermes approval mutation、unified Results 和旧四页 redirect 仍关闭。

## Scene-B 权威标识

| 字段 | 值 |
|---|---|
| candidate | `factor-wave2_scene_b_smoke_v3_loadable_factor-da01df1188` |
| manifest digest | `5ca064d597778b45f1a718047becf5b67b30cf9b24d441632b3a408cfd1c227d` |
| final backtest receipt | `backtest-f4da78d66b4ee6eaab6e7226740ac6ac` |
| effective promotion | `promo-b7bbab8cf571a5f4ff43aa652aebf3bc` |
| isolated review branch | `codex/promotion-promo-b7bbab8cf571a5f4ff43aa652aebf3bc` |
| reviewed commit | `524e791e5e3e22cec12a4166ad8fc3617c735566` |
| factor ID | `agent_candidate_wave2_sceneb_mom20_v3` |
| final lifecycle | `reviewed` → `cleaned` |

## Gate 3 过程

1. 旧 prepare 的 base 指向平台旧 HEAD；主开发分支前进后，status 正确返回 base mismatch，
   因此旧 promotion 被显式 abandon，没有盲目继续或覆盖。
2. 按当前 HEAD 重新 prepare，HQA 重验 exact Gate 1 binding 与同一 candidate/digest 的成功
   final receipt，并生成独立 worktree、patch、manifest 四字段输出。
3. 人类授权后在隔离 worktree 复核 exact 三文件 dirty set、bytes、mode、patch 与 manifest：
   promoted 因子源码、`promoted/__init__.py` 注册、scaffold test。
4. 人工 commit 得到 `524e791e5e3e22cec12a4166ad8fc3617c735566`；promotion status 观察到
   `reviewed`，随后按 promotion ID cleanup 到 `cleaned`。
5. 该 commit 以 fast-forward 合入平台 `audit-remediation-2026-06-23` 并已存在于远端同名
   分支；主 HQA 脏工作树和平台无关脏文件未被 Gate 3 worktree 继承。

## 当前仓库证据

`git show 524e791 --stat` 的 exact 三路径为：

```text
src/quant_system/factors/library/promoted/agent_candidate_wave2_sceneb_mom20_v3.py
src/quant_system/factors/library/promoted/__init__.py
tests/factors/test_agent_candidate_wave2_sceneb_mom20_v3.py
```

默认 promoted package 已导入并实例化
`agent_candidate_wave2_sceneb_mom20_v3_factor`；scaffold metadata/compute tests 存在。后续对
该因子的缺失收盘价行为加固属于 promoted 因子的正常维护，不改变上述 Gate 3 provenance。

## Wave 2 事实表

| 项 | 结果 | 当前解释 |
|---|---|---|
| Candidate migration apply | **DONE** | 授权的一次真实 apply 已使既有候选达到 verified；后续 migration 仍逐次授权 |
| Scene-B Gate 1/2/final/Gate 3 | **DONE** | 标识与 commit 如上；因子已 registered/promoted |
| Tasks 证据读模型 | **DONE** | 只读 automation/weekly/opportunity；没有 research task submit |
| 旧 TUI read bridge | **HISTORICAL / FAIL-CLOSED** | checkout/source 已漂移，不再是当前 runtime 合同 |
| Official API session GET BFF | **DONE（只读）** | gateway/list/detail/messages；composer 禁用 |
| Browser Gate 2 mutation | **ROLLED BACK** | 旧 UI 会 refetch digest/status，违反 HQA Gate 1 binding/no-refetch；当前只读 |
| Unified Results | **NOT DONE** | 动态统一详情与 exact run/result linking 未交付 |
| Legacy page retirement | **NOT DONE** | 旧四页仍在；soft banner 不等于 redirect/deletion |
| Chat/stream/resume/stop | **BLOCKED** | 缺 durable request/run/event/provider/approval/stop 合同 |

## 本轮连通性与副作用边界

- official API 的 health/capabilities/session GET 只读取本机已持久化状态，不发起 Hermes
  LLM 推理，不消耗 Codex/Grok provider 额度。
- session-read BFF 没有新增 PostgreSQL migration/table；数据库只运行既有迁移。
- 本次证据复核没有新建 research Run、回测、paper mutation、broker order 或交易。
- Scene-B 的 final receipt 是先前已经完成的权威研究证据；本文复核没有重跑它。

## 后续权威入口

- official API 只读合同：
  [`../contracts/hermes-api-server-0.18.2.md`](../contracts/hermes-api-server-0.18.2.md)
- 下一计划：
  [`../superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md`](../superpowers/plans/2026-07-15-d31-wave3-official-api-bff.md)
- 当前状态导航：[`../README.md`](../README.md)
