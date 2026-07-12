# 文档导航与当前执行状态

这份文件回答三个问题：**现在按哪份计划做、做到哪里、其他文档该怎么读**。
设计理念和历史过程不在这里重复；它们分别留在 roadmap、spec、implementation
plan、audit 和 git history 中。

> 事实快照：2026-07-12。状态变化后优先更新本文件和对应交付记录，不要在
> `AGENTS.md` 追加开发流水账。

## 当前唯一执行入口

| 层级 | 权威文档 | 当前含义 |
|---|---|---|
| 产品方向 | [`design/2026-07-01-roadmap-phases-0b-4.md`](design/2026-07-01-roadmap-phases-0b-4.md) | Hermes 是个人量化 COO；平台是领域后端。该 roadmap 管长期阶段、决策与安全门。 |
| 已完成实现记录 | [`superpowers/plans/2026-07-10-phase-1a-4-v2.md`](superpowers/plans/2026-07-10-phase-1a-4-v2.md) | Phase 1a-4 v2 的 Slice 9A-9H 已全部完成；当前没有选定下一 slice。 |
| 当前交付记录 | [`superpowers/plans/2026-07-12-full-9h-automation-notifications.md`](superpowers/plans/2026-07-12-full-9h-automation-notifications.md) | 完整 9H 的只读自动化、周复盘、freshness、feed 1.1、页面可见性、local 通知与四个 Hermes cron 的代码交付和运行验收。 |
| 前序交付记录 | [`superpowers/plans/2026-07-12-slice-9g-opportunity-ledger.md`](superpowers/plans/2026-07-12-slice-9g-opportunity-ledger.md) | 9G 稳定 signal identity、decision/action ledger、精确平台行动关联与 missed 安全判定。 |
| 更早交付记录 | [`superpowers/plans/2026-07-12-slice-9f-mini-9h.md`](superpowers/plans/2026-07-12-slice-9f-mini-9h.md) | 9F proposal-only 市场推演和 mini 9H `/hermes` 三源只读产物架。 |
| 前序实现 | `/Users/sunyibo/programs/ai-quant-platform/docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md` | Slice 0-8 的权威实现与验收记录；后续前端 backlog 仍从这里取材，但不盖过当前 v2 计划。 |
| 被替代计划 | [`superpowers/plans/2026-07-07-phase-1a-4-research-employees.md`](superpowers/plans/2026-07-07-phase-1a-4-research-employees.md) | 产品目标保留，implementation plan 已由 v2 重排计划替代，不得原样执行。 |
| 历史素材 | `ai-quant-platform/docs/phases/phase_15_iteration_roadmap.md`、两仓旧 phase/plan/audit | 只提供设计与验收证据，不得自行成为下一步。 |

Phase 1a-4 v2 已完整交付到 9H。最终 HQA 门禁为 `530 passed, 2 skipped`；
`hqa-full-9h-daily-close`、`hqa-full-9h-freshness`、`hqa-full-9h-weekly` 和
`hqa-full-9h-notification-drain` 四个 Hermes `no-agent`、local-delivery cron 均已真实触发并
报告 `ok`。feed schema 1.1 精确包含六源，`/hermes` 已可见 weekly、opportunity 和
automation，并保留风险、预测与市场推演三类卡片。

真实 options artifact 的 59 个阈值信号仍全部诚实保持 `not_actionable`，最终为
`59 not_actionable / 0 missed`。通知默认 target 是 local，运行验收没有实际外发 Discord。
本交付未触发策略、回测、paper mutation、broker 或交易，也没有为完整 9H 新增平台数据库
migration/table。

Git、远端和运行进程是易变状态，不在本入口维护“ahead/dirty/尚未推送”快照。每次交接
都应以 `git status --short --branch`、`git log`、`curl /api/health` 和对应测试重新核验。
当前没有选定下一实现 slice。任何新切片都必须先有单独的用户/产品决策，再按当时源码
另立 bite-sized plan；不得从旧 1a-4 模板、旧前端 P2/P3 或历史 audit 自行推导下一步。

## 状态用词

- **已实现**：代码存在，但可能仍在工作树中。
- **已提交**：本地 commit 存在。
- **已推送**：远端分支已包含该 commit。
- **代码交付**：实现和约定测试已完成；不自动等于真实运营验收。
- **运行验收**：当前进程已重启到目标代码，并用真实本地依赖完成 smoke/E2E。
- **排队**：设计可以保留，但不得被 agent 当作当前实现指令。
- **历史快照**：只描述某一日期的事实，不承担当前状态维护职责。

文档里出现“已交付”时，应尽量注明是代码交付还是运行验收。计划中的 checkbox
只能证明该计划记录了完成状态，仍应以代码、git 和测试证据复核。

## 阅读顺序

1. 本文件：确定当前主线和状态。
2. 已完成实现记录与当前交付记录：核对 9A-9H 的范围、验收事实和历史边界；在新的
   用户/产品决策前不要执行另一 slice。
3. [`design/2026-07-01-roadmap-phases-0b-4.md`](design/2026-07-01-roadmap-phases-0b-4.md)：核对产品方向和安全门。
4. [`design/vision-daily-life.md`](design/vision-daily-life.md)：理解目标用户体验。
5. 只有改到具体模块时，再读对应 `plans/`、spec 或平台 guide/architecture。

## 文档分类

### 现役

- 本文件：当前工作入口。
- `design/2026-07-01-roadmap-phases-0b-4.md`：产品路线与决策台账。
- `superpowers/plans/2026-07-10-phase-1a-4-v2.md`：已完成的 Phase 1a-4 v2 实现记录。
- `superpowers/plans/2026-07-12-full-9h-automation-notifications.md`：当前交付与运行验收记录。
- 平台 `2026-07-08-frontend-redesign-hermes-integration.md`：Slice 0-8 实现记录与前端 backlog。
- 两仓 `README.md`：稳定能力、启动和安全说明。
- 两仓 `AGENTS.md` / `.claude/CLAUDE.md`：agent 必须遵守的规则与权威指针。

### 已完成阶段的实现记录

`plans/2026-07-01-phase-0a-*`、`phase-0b-*`、`phase-1a-0-*`、
`phase-1a-1-*`、`phase-1a-2-*`、`phase-1a-3-*` 和 D-25 文档用于追溯设计、
测试与边界；它们不是当前待办清单。某些 checkbox 没有回填，不应据此反推代码不存在。

### 未选定下一切片

目前没有 active/queued implementation slice。原 Phase 1a-4 spec/plan 仅保留为历史输入；
`2026-07-10-phase-1a-4-v2.md` 和完整 9H 计划均是已完成记录，不得把其中的旧 deferred
条目自动升级为下一步。

### 历史审计

`audits/` 记录特定日期的发现和后续处置。审计中的未完成项、优先级和“下一步”只对
该快照有效；当前状态回到本文件、当前交付记录、源码和测试核验。

## 双仓职责与安全边界

- `Hermes-quant-agent`：编排、记忆、cron、通知、人机审批和 artifact-first 体验。
- `ai-quant-platform`：行情、因子、回测、期权、paper account、数据库和前端领域实现。
- 候选因子只可用于显式的一次性研究；常驻 paper/live 路径只允许 promoted、registered、
  tested factor。
- 不绕过 `paper_trading`、`live_trading_enabled=false`、`kill_switch` 或人工门。
- `/hermes` 已从 mini 9H 三源产物架升级为 feed schema 1.1 六源只读视图；它通过
  `GET /api/hermes/artifacts` 展示 `portfolio_risk`、`prediction`、`market_foresight`、
  `weekly_review`、`opportunity_summary`、`automation_status`。disabled composer、保留
  factor-lab/agent-studio、不调用 `POST /api/agent/tasks` 仍是安全设计，不是缺陷。
