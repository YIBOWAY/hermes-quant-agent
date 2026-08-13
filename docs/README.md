# 文档导航与当前执行状态

只回答三个问题：**现在按哪份计划做、实际做到哪里、其他文档该怎么读。**

## 现在按哪份做

**唯一现行计划：** [`plans/2026-08-13-personal-quant-assistant.md`](plans/2026-08-13-personal-quant-assistant.md)

产品是一台本机个人量化助手（盯盘、复现、回测、模拟盘每天跑、看效果）。  
`D-31` / `D-32` / `D-33` / `D-34` 不是产品线，不是默认入口，不是下一 slice 名。

日常启动（部署镜像，只许 start/status/ff，不许在里面改代码）：

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform
bash scripts/local_mac_stack.sh start
bash scripts/local_mac_stack.sh status
```

Hermes 更新只用 `~/.hermes/scripts/hqa-hermes-update.sh check|apply`。

施工地点：主 checkout 或 `/Users/sunyibo/programs/.worktrees/` 下有名字的 worktree。  
隔离收口在 `.worktrees/coo-unify/` 的 `refactor/coo-unify` 与空库 `quantplatform_coo`。

## 实际做到哪里

能力零件大多已经落地：真 Futu、回测器、模拟账户、论文入队机、双引擎研究作业、试运行仓、本机 LaunchAgent。  
第 1 步已在隔离栈解开：已挂上的试运行仓可以成交并记 P&L，全局 `kill_switch` 仍冻实盘。  
看效果请开 `http://127.0.0.1:3002/zh/paper-trading`（后端 `:8876`，库 `quantplatform_coo`），不要改 live `:3001`。  
双引擎通过仍只进已验证候选，挂上才每天跑。第 2–4 步未开。

纸面与实盘切开、`live_trading_enabled=false`、公开 composer 关闭，这些红线还在。  
不要用 soak `1/10` 或旧 audit 里的 PID/commit 当 NEXT。

## 其他文档怎么读

| 要干什么 | 读这份 |
|---|---|
| 下一步施工 | [`plans/2026-08-13-personal-quant-assistant.md`](plans/2026-08-13-personal-quant-assistant.md) |
| 本机栈怎么起停 | 平台 [`runbooks/agent-v0-2-local-stack.md`](https://github.com/YIBOWAY/ai-quant-platform/blob/main/docs/runbooks/agent-v0-2-local-stack.md) |
| 模拟盘/回测/因子实验室怎么用 | 平台 `docs/guides/` |
| 当时为什么这样建 | 下面「历史索引」。全部盖了历史印，**不要按未完成方框续写** |

### 历史索引（证据，不是队列）

| 旧名 | 文件 | 现在只当 |
|---|---|---|
| 决策台账 D-1…D-33 | [`design/2026-07-01-roadmap-phases-0b-4.md`](design/2026-07-01-roadmap-phases-0b-4.md) | 当时的决策记录 |
| 论文自动 paper | [`plans/2026-08-10-full-automation-paper-path.md`](plans/2026-08-10-full-automation-paper-path.md) | 研究账来源之一的实现记录 |
| 双引擎 Mandate | [`plans/2026-08-11-d34-mandate-dual-engine-paper.md`](plans/2026-08-11-d34-mandate-dual-engine-paper.md) | 研究账来源之二的实现记录 |
| Agent v0.2 Web Chat | [`superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md`](superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md) | 公开 Chat 方向，现行计划明确不做 NEXT |
| 工作台设计 | [`superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md`](superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md) | `/hermes` 首页来源 |
| 9A–9H | [`superpowers/plans/2026-07-10-phase-1a-4-v2.md`](superpowers/plans/2026-07-10-phase-1a-4-v2.md) | 已交付 |
| quark | [`superpowers/specs/2026-08-10-quark-program-integration-design.md`](superpowers/specs/2026-08-10-quark-program-integration-design.md) | P1 已交付；P2/P3 不是助手主线 |
| AlphaZeroBeta | [`audits/2026-07-31-alphazerobeta-paper-research-web-e2e.md`](audits/2026-07-31-alphazerobeta-paper-research-web-e2e.md) | paper intake 未接受；模型散文 ≠ 收据 |
| 手工 Scene-B | Wave 2 / Gate 3 记录 | live 与手工转正仍走 Gate 1/2/3 |
| 平台 Phase 15 | 平台 `docs/phases/phase_15_iteration_roadmap.md` | 素材，不是路线图 |

`docs/audits/`、`docs/contracts/`、`docs/superpowers/plans/` 里其余文件都是交付证据。  
新会话禁止从它们的 checkbox 推断当前工作。
