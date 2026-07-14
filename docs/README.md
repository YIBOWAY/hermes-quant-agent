# 文档导航与当前执行状态

这份文件回答三个问题：**现在按哪份计划做、做到哪里、其他文档该怎么读**。
设计理念和历史过程不在这里重复；它们分别留在 roadmap、spec、implementation
plan、audit 和 git history 中。

> 事实快照：2026-07-14。状态变化后优先更新本文件和对应交付记录，不要在
> `AGENTS.md` 追加开发流水账。

## 当前唯一执行入口

| 层级 | 权威文档 | 当前含义 |
|---|---|---|
| 产品方向 | [`design/2026-07-01-roadmap-phases-0b-4.md`](design/2026-07-01-roadmap-phases-0b-4.md) | Hermes 是个人量化 COO；平台是领域后端。该 roadmap 管长期阶段、决策与安全门。 |
| 已批准下一产品设计 | [`superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md`](superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md) | D-31：`/hermes` 成为默认首页，真实连接本地 Hermes，并逐步吞并 factor-lab、backtest、experiments、agent-studio 的页面体验。 |
| 第一批正式计划：Hermes 合同（已冻结，chat fail-closed） | [`superpowers/plans/2026-07-13-hermes-gateway-capability-contract.md`](superpowers/plans/2026-07-13-hermes-gateway-capability-contract.md) | 将本机 Hermes 0.18.2 的 WebSocket JSON-RPC 能力、Git 绑定独立审查和安装指纹冻结为 fail-closed 合同；证据见 [`contracts/hermes-gateway-0.18.2.md`](contracts/hermes-gateway-0.18.2.md)。当前缺少 request recovery、Run identity、event replay、immutable provider/fallback policy 和 actual-provider evidence，所以真实 chat/resume 写端继续关闭。 |
| 第一批正式计划：候选安全（代码已交付并审查加固） | [`superpowers/plans/2026-07-13-candidate-integrity-and-gate3.md`](superpowers/plans/2026-07-13-candidate-integrity-and-gate3.md) | 统一 repo-anchored candidate root、immutable manifest、HQA Scene-B Gate 1 精确源确认/绑定、Gate 2 digest/CAS、legacy_unbound、最后读取再校验与隔离 Gate 3 worktree 已交付；真实 migration `--apply` 与 Hermes 新审批 mutation 仍未开放。 |
| 第一批正式计划：专业前端（代码已交付） | [`superpowers/plans/2026-07-13-hermes-professional-frontend-shell.md`](superpowers/plans/2026-07-13-hermes-professional-frontend-shell.md) | F0 direction-a + F1 书面批准后，F2 只读壳与可回滚默认首页已代码交付；chat/execution/unifiedResults/legacyRedirects 字面 false；能力提示静态 `blocked_in_this_slice`；不开放 chat mutation 与旧页 redirect。 |
| 已完成实现记录 | [`superpowers/plans/2026-07-10-phase-1a-4-v2.md`](superpowers/plans/2026-07-10-phase-1a-4-v2.md) | Phase 1a-4 v2 的 Slice 9A-9H 已全部完成；其中“没有下一 slice”仅是该交付完成时的历史状态，不代表当前 D-31 计划状态。 |
| 当前交付记录 | [`superpowers/plans/2026-07-12-full-9h-automation-notifications.md`](superpowers/plans/2026-07-12-full-9h-automation-notifications.md) | 完整 9H 的只读自动化、周复盘、freshness、feed 1.1、页面可见性、local 通知与四个 Hermes cron 的代码交付和运行验收。 |
| 前序交付记录 | [`superpowers/plans/2026-07-12-slice-9g-opportunity-ledger.md`](superpowers/plans/2026-07-12-slice-9g-opportunity-ledger.md) | 9G 稳定 signal identity、decision/action ledger、精确平台行动关联与 missed 安全判定。 |
| 更早交付记录 | [`superpowers/plans/2026-07-12-slice-9f-mini-9h.md`](superpowers/plans/2026-07-12-slice-9f-mini-9h.md) | 9F proposal-only 市场推演和 mini 9H `/hermes` 三源只读产物架。 |
| 前序实现 | `/Users/sunyibo/programs/ai-quant-platform/docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md` | Slice 0-8 的权威实现与验收记录；只作为 D-31 的现状/parity inventory，不再提供可直接执行的后续 backlog。 |
| 被替代计划 | [`superpowers/plans/2026-07-07-phase-1a-4-research-employees.md`](superpowers/plans/2026-07-07-phase-1a-4-research-employees.md) | 产品目标保留，implementation plan 已由 v2 重排计划替代，不得原样执行。 |
| 历史素材 | `ai-quant-platform/docs/phases/phase_15_iteration_roadmap.md`、两仓旧 phase/plan/audit | 只提供设计与验收证据，不得自行成为下一步。 |

Phase 1a-4 v2 已完整交付到 9H；该交付当时的 HQA 门禁为
`530 passed, 2 skipped`。2026-07-14 对抗性加固后的当前全量门禁为
`659 passed, 2 skipped`；
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
下一产品设计已经通过 D-31 单独确认。**Wave 1** 三份计划（gateway 合同、candidate
integrity/Gate 3、professional frontend/read-only shell）已代码交付并经用户确认收口：
完整 D-31 仍是**按设计部分完成**，不得表述成 Hermes 已全部接通。
**Wave 2 执行入口：**
[`superpowers/plans/2026-07-14-d31-wave2-bridge-approvals-parity.md`](superpowers/plans/2026-07-14-d31-wave2-bridge-approvals-parity.md)。
2026-07-14 证据下 Wave 2 **部分完成**（见下表）；不得表述成 Hermes 已全部接通或旧四页已退役。
不得从旧 1a-4 模板或历史 audit 自行加步骤。`verify-chat` 未 ready（exit 3）前禁止打开真实网页 chat 写端。

### D-31 Wave 2 状态（2026-07-14 证据）

| Task | 状态 | 证据要点 |
|---|---|---|
| A — Candidate migration `--apply` | **DONE** | 真实候选 `factor-momentum_20d_reversal-323b045e4b`：`integrity=verified`，`approval_enabled=True`，digest `294bbe7b846ae86384e56deae8ba8df2576ac6ffa8a5937e4f82a2352fdd8558` |
| B — Hermes Approvals Gate 2 CAS UI | **DONE（平台代码）** | platform `8052fe6`：仅 `approval_enabled` + `verified` + `pending` 显示批准/拒绝；确认时 re-fetch detail digest + 必填 note；CAS 提交 `expected_manifest_digest` + `expected_status=pending` |
| C — Tasks 证据读模型 | **DONE（平台代码）** | 同 `8052fe6`：自动化/周报/机会摘要只读；**无** research task 写账本 / create-submit |
| D — Scene-B 实跑 | **PARTIAL / BLOCKED at final** | `data/_runtime/sceneb-wave2/`：Gate 1 propose + Gate 2 approve 已对 smoke 候选 `factor-wave2_scene_b_smoke_momentum_20d_reversa-6106ea1c63` 落盘；`final-backtest.out` 因 `factor_id` 与既有候选冲突被拒绝；**无**成功 final receipt、**无** Gate 3 prepare/worktree |
| E — Capability re-audit + read bridge | **DONE（scaffold）** | HQA `753f153`：`installation.matches_snapshot=true`，`chat_write=false`，`verify-chat` exit 3；`hqa/hermes_read_bridge.py` 只读 `session.list/status/history`，从不暴露 create/submit/approval |
| F — 旧页 parity | **PARTIAL** | platform `3400659`：Factor Lab / Backtester / Experiments / Agent Studio **soft banners only**；**未**删除、**未** redirect；inventory 见工作区 `.superpowers/sdd/wave2-parity-inventory.md`（本地 SDD，可能未入库） |
| G — Docs / 双仓核验 | **IN PROGRESS** | 本文件与平台 INDEX 按证据回写；chat write 与 legacy retirement 仍关闭 |

**Wave 2 明确未完成 / 仍关闭：**

- 真实网页 **chat write / stream / resume**（`verify-chat` exit 3；合同 review 仍 `blocked`；composer 硬禁用）。
- Scene-B **完整** Gate1→final receipt→Gate3 prepare→human commit 路径（final 已 blocked）。
- 旧四页 **deletion / hard redirect**（仍完整保留能力；仅 soft banner）。
- Hermes **unified results** 动态详情（`unifiedResults` hard-off；Results 只链到既有平台面）。
- 将 `POST /api/agent/tasks` 当作 Hermes fallback（禁止）。

Candidate integrity / Gate 3 交付要点（以平台代码与两仓测试为准，非历史计划 checkbox）：

- 唯一 canonical root：`resolve_agent_output_dir()` → 默认
  `/Users/sunyibo/programs/ai-quant-platform/data/agent_run`，候选目录
  `.../data/agent_run/agent/candidates`；仅 `QS_AGENT_OUTPUT_DIR` 可覆盖；CWD /
  `QS_DATA_DIR` 不迁移候选池。
- 读状态：`verified` / `migration_required` / `corrupt` 互斥；`legacy_unbound`
  无批准/执行/晋级权威。
- Gate 1（Scene-B HQA wrapper）：人类提供精确 reviewed source SHA-256 与非空确认说明；
  HQA 持久化 source confirmation，并将它绑定到平台返回的 exact candidate ID + manifest
  digest。平台以 binary read 原样摄入外部源码，并在 machine receipt 返回 verified
  `source_sha256`；HQA 只有在它等于 Gate 1 digest 时才写 binding。`list` 只展示去除命令
  的非权威清单；只有 exact JSON `detail` 在绑定存在时展示 approve command，approve 也
  fail closed。Hermes readonly gate 不再暴露 raw `agent list-candidates`，平台该命令本身也
  不再输出 copyable review command。平台原始
  review endpoint 只是 Gate 2 primitive，不单独构成 Scene-B Gate 1 证据。
- Gate 2：HQA 要求人类提供 `candidate-id + expected-digest + expected-status=pending + note`，
  approve 路径禁止 refetch。
- final one-shot：只有成功的 `backtest --final` 才写 canonical、content-addressed receipt，
  绑定 candidate/digest/factor/experiment/run/provider/symbols/full window，以及安全读取并
  SHA-256 复核的 config/agent-summary/report。HQA 还要求真实 provider、每次调用唯一且
  不覆盖的实验命名空间，并把三份产物的完整路径固定到显式
  `HQA_FACTOR_EXPERIMENT_OUTPUT_DIR` authority root 下；同时要求 exact `run-001`、完整
  safety/provenance schema 和与平台生成器逐字一致的报告；non-final trial 不生成 Gate 3 权威。
- Gate 3：Scene-B 使用 HQA `factor_repro_cli promote`，必须显式携带
  candidate/digest/final-backtest-receipt/base，先重验 Gate 1 exact binding 与同一
  candidate/digest 的成功 final receipt，再调用平台 prepare；stdout 四字段
  `{promotion_id, worktree, patch, manifest}`；status/cleanup 只认 promotion-id；
  HQA 还会安全读取 manifest/patch 和 actual worktree，复核 candidate/digest/base、确定性
  promotion ID、exact 三路径、文件 bytes/mode、完整 dirty set 与实际 Git patch；平台
  `promotion-status` 同步返回 manifest/patch/candidate/base/path provenance，并在状态读取时
  重新证明未提交工作区未漂移。超时只代表 outcome unknown，必须按 recovery handle/根目录
  只读核查，不能盲目 retry/abandon。输出前再次验证 Gate 1 与 final receipt。abandon 仅显式；隔离 review worktree；永不自动 commit。平台原始 promotion CLI 是通用
  primitive，不单独证明 HQA Gate 1 provenance。
- 迁移命令默认仍 dry-run；**Wave 2 已对真实数据授权并执行一次 `--apply`**，使
  `factor-momentum_20d_reversal-323b045e4b` 达到 `integrity=verified` /
  `approval_enabled=True`（digest
  `294bbe7b846ae86384e56deae8ba8df2576ac6ffa8a5937e4f82a2352fdd8558`）。后续新
  legacy/canonical 冲突仍需单独授权，不得静默再 apply。
- Hermes Approvals **Gate 2 CAS mutation UI 已在平台交付**（Wave 2）：仅
  verified+pending+approval_enabled 可批；migration/corrupt 仍证据只读。这不是
  chat bridge，也不等于 Scene-B Gate 1/3 完成。

The real Hermes **chat write** slice is still not selected. Wave 2 re-audit
(HQA `753f153`) treats banner `upstream` as diagnostic only: installation match
is version + pinned checkout + `server.py` digest + tracked clean, so
`installation.matches_snapshot=true` even when the banner shows `226e8de8` vs
contract freeze `b03c94db`. `verify-chat` still exits **3** with
`chat_write_enabled=false` / stream/resume disabled; `chat_read_enabled` may be
true for the read-only scaffold. The inspected Hermes 0.18.2 surface still lacks
D-31 request-recovery, event-replay, Run identity, immutable session
provider/fallback policy, and actual-provider evidence. Contract review remains
`blocked`. Read-only bridge scaffold: `hqa/hermes_read_bridge.py`
(`session.list` / `status` / `history` only).

只有 capability plan 的 `verify-chat` 针对已提交、独立审查为 `ready` 的默认合同和当时
干净安装态证据返回 ready（`review.verdict=ready` 且
`installation.matches_snapshot=true`），才能另写 **chat write** implementation plan。
旧 `/api/agent/tasks` / AgentRunner **不是** fallback。

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
2. [`superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md`](superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md)：核对 D-31 已批准设计；书面规格和后续 implementation plan 获批前不要施工。
3. 已完成实现记录与当前交付记录：核对 9A-9H 的范围、验收事实和历史边界。
4. [`design/2026-07-01-roadmap-phases-0b-4.md`](design/2026-07-01-roadmap-phases-0b-4.md)：核对产品方向和安全门。
5. [`design/vision-daily-life.md`](design/vision-daily-life.md)：理解目标用户体验。
6. 只有改到具体模块时，再读对应 `plans/`、spec 或平台 guide/architecture。

## 文档分类

### 现役

- 本文件：当前工作入口。
- `design/2026-07-01-roadmap-phases-0b-4.md`：产品路线与决策台账。
- `superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md`：已批准的
  D-31 产品/架构设计；等待书面复核和 implementation plan。
- `superpowers/plans/2026-07-10-phase-1a-4-v2.md`：已完成的 Phase 1a-4 v2 实现记录。
- `superpowers/plans/2026-07-12-full-9h-automation-notifications.md`：当前交付与运行验收记录。
- 平台 `2026-07-08-frontend-redesign-hermes-integration.md`：Slice 0-8 已完成实现记录与
  D-31 parity inventory，不是当前 backlog。
- 两仓 `README.md`：稳定能力、启动和安全说明。
- 两仓 `AGENTS.md` / `.claude/CLAUDE.md`：agent 必须遵守的规则与权威指针。

### 已完成阶段的实现记录

`plans/2026-07-01-phase-0a-*`、`phase-0b-*`、`phase-1a-0-*`、
`phase-1a-1-*`、`phase-1a-2-*`、`phase-1a-3-*` 和 D-25 文档用于追溯设计、
测试与边界；它们不是当前待办清单。某些 checkbox 没有回填，不应据此反推代码不存在。

### 已批准设计、第一批正式计划（部分交付）

Hermes 统一研究工作台设计已经确认并记录在
`superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md`。第一批工作被拆成
Hermes capability、candidate integrity/Gate 3、professional frontend/read-only shell
三份可独立验证的正式计划（Wave 1，已收口）。**Wave 2**
（`2026-07-14-d31-wave2-bridge-approvals-parity.md`）在 2026-07-14 证据下部分完成：
真实 migration apply 与 Hermes Gate 2 CAS Approvals / Tasks 证据读模型已交付；
capability re-audit + 只读 bridge scaffold 已提交；Scene-B 仅到 Gate1/2 smoke 且
final 被拒；旧四页仅 soft banner，未 delete/redirect；**chat write 仍 fail-closed**
（`verify-chat` exit 3）。`legacyRedirects` / `unifiedResults` / `execution` 仍 hard-off。
旧 `/api/agent/tasks` 不是 fallback。原 Phase 1a-4 spec/plan 仅保留为历史输入；
`2026-07-10-phase-1a-4-v2.md` 和完整 9H 计划均是已完成记录，不得把其中的旧 deferred
条目自动升级为下一步。

### 历史审计

`audits/` 记录特定日期的发现和后续处置。审计中的未完成项、优先级和“下一步”只对
该快照有效；当前状态回到本文件、当前交付记录、源码和测试核验。

## 双仓职责与安全边界

- `Hermes-quant-agent`：编排、记忆、cron、通知、人机审批和 artifact-first 体验。
- `ai-quant-platform`：行情、因子、回测、期权、paper account、数据库和前端领域实现。
- 候选因子只可用于显式的一次性研究（digest 再校验后）；常驻 paper/live 路径只允许
  promoted、registered、tested factor。
- Gate 2 必须携带人类提供的 digest/pending/note CAS 值；Gate 3 只在隔离 worktree
  生成 scoped patch，永不自动 commit。
- 不绕过 `paper_trading`、`live_trading_enabled=false`、`kill_switch` 或人工门。
- `/hermes` 已从 mini 9H 三源产物架升级为 feed schema 1.1 六源专业壳（F2 + Wave 2）：
  默认首页可回滚到 Dashboard；单一全局 SafetyStrip；Today 以行动/异常/结论为先；
  Tasks 为平台证据读模型（自动化/周报/机会）；Approvals 在 verified CAS 条件下可
  提交平台 Gate 2 review（非 chat）；Results 为 9H artifact 索引 + 链到既有平台面；
  composer **仍硬禁用**；chat/stream/resume 与 `legacyRedirects` 仍 hard-off。
  它通过 `GET /api/hermes/artifacts` 展示 `portfolio_risk`、`prediction`、
  `market_foresight`、`weekly_review`、`opportunity_summary`、`automation_status`。
  不调用 `POST /api/agent/tasks`、不开放 chat mutation、不删除旧四页是 D-31 真实
  chat bridge 与 page-parity Gate 完成前的安全基线。
