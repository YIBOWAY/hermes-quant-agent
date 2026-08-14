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
第 1 步按计划收口：隔离栈上，已挂试运行仓能成交、能记账，实盘仍关。  
那不是「助手已经在看效果」。预览种子用假价 179 买进，页面 Futu 现价只是市值差，不许写进摘要。  
核对预览用 `http://127.0.0.1:3002/zh/paper-trading`（后端 `:8876`，库 `quantplatform_coo`），不要改 live `:3001`。  
第 2 步按计划收口（隔离语义）：派研究不会挂仓，挂上另下一命令；双引擎默认停在已验证候选。  
`:3002`「聊天遥控」只核对这两条命令，不是 Hermes 网页已经能说话。  
第 3 步按计划收口（隔离语义）：挂上必须绑候选源码 digest，禁止再造通用动量仓；本分支 D-33 `run_once` 默认停在已验证候选。不是 Artifact CAS 正式挂仓，也不切 live `:3001`。第 4 步先别开。第 5 步等真观察日，不要用种子盈亏顶上。  
前端按 §9 已开视觉打样：`http://127.0.0.1:3002/zh/desk-preview`（blotter 桌面 + 右栏 Hermes 会话流，石墨主题已定稿为默认）。假数据全标预览态，不当今日效果；定稿前不动正式桌面。  
第 4 步进行中（隔离语义）：`dispatch-research` 已接真作业。隔离一次性 worker 已对 `quantplatform_coo` 跑完首作业 `request:2026-08-14:030600c343f3`：双引擎都出了收据，对照因终端净值差 29.1bps > 25bps 上限拒收（`dual_engine_comparison_rejected`）。账本已投影 `rejected`。无 artifact、无金丝雀、未挂仓。live 库没有这条 job。候选回填和材料 intake 仍未开。  
值班韧性：`portfolio_risk` 历史价 Futu 失败先重试一次，可选 Tiingo 显式回退（`tiingo/adjusted`，收据双留痕；回退合同失败仍保留 Futu 收据；非法 `HQA_PORTFOLIO_RISK_HISTORY_FALLBACK` 会在收据上留痕）。已部署到镜像与 wrapper 的是提交版；工作区含 `adjusted` 合同修复，等提交后再 ff 镜像。`QS_TIINGO_API_TOKEN` 填值后回退才真正出门。兵器库条款进 §4，试点 runbook 见 `runbooks/arsenal-pilot-daily-stock-analysis.md`。

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
