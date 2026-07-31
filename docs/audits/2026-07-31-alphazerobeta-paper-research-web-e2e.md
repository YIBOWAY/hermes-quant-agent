# AlphaZeroBeta 论文研究 `/hermes` Web E2E 审计

> 执行窗口：2026-07-31 至 2026-08-01（Asia/Shanghai）
> 审计范围：本机、单用户、私有 candidate 下的真实浏览器 → Platform → HQA connector →
> Hermes/provider → PostgreSQL/Hermes durable facts；不包含 public release/cutover。
> 结论：**最终重跑 PASS；public release/write 仍 OFF。** 第一次尝试的审批投影缺陷保留为
> `FAIL` 证据，修复后同一类真实任务成功完成。

## 1. 判定边界

本审计只证明：在一个受控的本地私有 candidate 窗口中，网页可以提交指定论文研究 prompt，
Hermes 能真实联网、下载并读取论文、通过精确 command approval、形成有依据的研究结论，并把
Command/Run/provider/usage 事实持久化。它**不证明** Agent v0.2 全部发布 Gate、两条产品纵切、
public composer、release stamp/cutover 或 live trading 已完成。

状态含义：

- `PASS`：本窗口取得了可复核的运行或持久化证据。
- `FAIL`：真实尝试失败；即使后来修复，也保留原失败事实。
- `BLOCKED`：安全边界仍故意关闭，不能从本窗口推导开放。
- `EXPECTED_NOT_REACHED`：上游研究判断按合同结束，因此后续动作不应发生；不是漏测伪装。

## 2. 精确输入

网页发送的规范化 prompt 为：

> 我刚刚发现了一篇论文： alphazerobeta:deep reinforcement learning for market-neutral
> portfolios，你帮我先研究研究这篇论文，如果有策略和因子的话，就提取出来并回测，沉淀成
> 策略；如果没有的话，就跟我说一下这篇论文干了点啥就行

| 输入 | SHA-256 |
|---|---|
| 浏览器实际发送的规范化文本 | `6633a60bfb3c8b82c4f90e363479e374343692f621a46d83a163190143b204c9` |
| `prompt.txt` 原始 bytes（含末尾 LF） | `4bedb09dac721d12aeec58f33c85dd79bb6e6c2c78c172aba1a271d7171209de` |
| operator control source | `730968a71c1f670b568c019619b1d63e436fde7d321fabe19d11b234f518c428` |

输入文件位于
`/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-e2e-20260731.CKKG3r/`。

## 3. 结果矩阵

| 检查项 | 状态 | 证据与解释 |
|---|---|---|
| 第一次真实 Web 尝试 | **FAIL（已修复，保留）** | Session `web_211e8ec3eb6944bcc5c83f1eaae535e9a3964b6f`、Command `2f6d48f5-7a18-458c-bfc5-28c9923ae0e8`、Run `run_ac253949311b47929d445f50f963456a` 失败；根因是 Platform 未从 Hermes durable Run snapshot 投影等待中的审批，网页看不到 challenge，waiter 超时。该尝试未产生订单。 |
| 最终浏览器提交与 durable lifecycle | **PASS** | Platform Session `wm_fb5f44086e3c059ce65cf0f314a9222f`、Hermes Session `web_fb5f44086e3c059ce65cf0f314a9222fb0a1bee5`；Command `3176607c-4202-4646-8781-4bf7dcb1dab2` 在 version `13`、attempt `1` 进入 `succeeded`；canonical Run `run_f62837e8fda84cd7a04a37239f258e2d` 为 `succeeded`。 |
| 真实 provider 与联网研究 | **PASS** | actual provider/model=`xai-oauth/grok-4.5`；20 条消息、10 次 tool call、9 次 API call；usage=`442766` input、`3650` output、`446416` total。 |
| 论文定位、下载与正文读取 | **PASS** | Firecrawl 不可用、arXiv `urllib` 请求失败后没有伪造成功；`curl` fallback 下载成功。PDF 为 `750580` bytes、59 页，提取 `126631` chars。`pymupdf` 安装因 hash mismatch 被拒绝，随后使用已允许的 `pypdf` fallback 成功读取。 |
| Hermes command approval | **PASS** | 5 个 challenge 全部由网页以精确 digest 的 allow-once 流程消费；每个 challenge 都具有完整 durable event chain，不存在遗留 pending 或重复消费。 |
| 研究结论与 HQA 可复现性判断 | **PASS** | Hermes 结论是该论文在当前 HQA 因子可复现合同下 **non-actionable**：它描述端到端深度强化学习的 market-neutral portfolio controller，但没有可直接按当前 deterministic factor/Gate 管线提取并复现的独立因子/策略规格。本次应返回论文做法说明，而不是虚构因子。 |
| `prepare-intent`、论文 Gate 1/2/3 | **EXPECTED_NOT_REACHED** | non-actionable 判定在研究阶段终止，因而不应创建研究 intent 或人类 Gate。PostgreSQL 本次新增 workflow binding、run link、Gate 均为 `0`。 |
| factor、backtest、strategy 沉淀 | **EXPECTED_NOT_REACHED** | 用户 prompt 明确允许“没有则说明论文做了什么”；既然没有可复现因子，安全且正确的行为是零 factor、零 backtest、零 strategy，而不是强行生成样本结果。本次相关新增行均为 `0`。 |
| PostgreSQL migration 028 | **PASS** | 正式库快照显示 marker rows=`1`、version rows=`1`、目标 triggers=`2`；028 只应用一次，未重放。 |
| 正式三仓候选验证 | **PASS** | sealed manifest SHA-256=`439b5731b52e761168caaa5202e495a0c0c7f2ef2aa50f7557864eb2eb110da5`；Platform `2764 passed / 255 skipped`、HQA `2140 / 17`、Hermes focused `299 / 0`、frontend `429 / 0`，合计 `5632 passed / 272 skipped / 0 failed`。 |
| 正常安装、restart 与兼容性 | **PASS** | final commits：Hermes `199a251d20ec62be3845681f40d220a40fabd7d8`、HQA `005e92ed7849ea2956bff18b72e399b407b67895`、Platform `2eb714d1ef4ece96a664a816b1f3392d1640809e`；Hermes exact frozen sync/restart/import 通过，compatibility report digest `c4762b…` 为 compatible；Platform restart receipt SHA-256=`d436d86324acd25619968413b4d1ce0b52324469c9c913e57aace69f0ec7bec6` 且 status=`passed`。 |
| 交易与数据库零副作用 | **PASS** | `kill_switch=true`；订单 ledger=`12`、`max_seq=12`、pending orders=`0`、positions=`3`，四表稳定 MD5=`634c9c2ca6c46ef9b000388ec5e7bcc3`。前后快照一致，本窗口 zero orders。 |
| candidate/connector 清理 | **PASS** | Candidate `candidate_5ddfd4db518146318beebf4a58f45d5a` 已 `revoked`，open candidates=`0`；connector 进程已恢复 `reconcile_only`。candidate 关闭后 health 不宣称 supervised liveness（`connector_liveness_ready=false`），最终页面重载为 dark/只读状态。 |
| public release/write | **BLOCKED / OFF（预期）** | `release_authorized=false`、`public_write_authorized=false`、`public_chat_write_ready=false`。私有 candidate 成功不构成 public release 授权。 |

## 4. 第一次失败与修复闭环

第一次 Run 已在 Hermes 中持久化审批 challenge，但 Platform 当时只依赖事件增量，未从 durable
snapshot 恢复等待中的审批；网页因此无法呈现 allow-once 操作，Run 最终失败。修复没有延长超时
或跳过审批，而是补齐权威链：

1. Hermes 暴露 durable approval snapshot，并在 waiter 已消失、challenge 尚未发布/消费且无
   event 引用时精确清理 unbound orphan；
2. Platform 从 snapshot 投影审批，并保持 challenge/run/digest/expiry 的 exact CAS；
3. HQA compatibility watcher 固定 owner-only API-key file 路径，拒绝 hostile env、symlink、
   world-writable 与不安全 FIFO 情形；
4. 三仓重新提交、正常安装、完整候选套件、restart 与真实浏览器重跑。

最终 5 个审批均可见、可操作、只消费一次，证明修复的是 recovery/projection 合同，而不是绕过
Hermes command approval。

## 5. 数据库、备份与安全证据

- 正式库 pre-028 备份：
  `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/maple-e2e-20260731T060327Z/live-pre028-backup/quantplatform-pre028.dump`
  （SHA-256 `017d29a6abb4a4cd0c51e7e6f573dab250f9f45a3b21e350cd80d3ff0b7b273e`）。
- 备份已在隔离数据库恢复并核对 owner/relation/effective privileges；隔离库保留为
  `quantplatform_pre028_maple_20260731_tmp` 与
  `quantplatform_pre028_rehearsal_20260731_tmp`。
- schema fingerprint：
  `e3f713ac05a1a990cfa9be45157e880e06709c425a4883736544d8f2b626f33a`。
- candidate 绑定 paper-authority epoch=`197`，关闭原因为完成最终监督 E2E 后恢复本地暗态。
- 本次 Command/Run 成功不伴随任何 research workflow/Gate/factor/backtest 写入，也不改变
  paper/live eligibility。

## 6. 关键 artifact

| 证据 | 路径 |
|---|---|
| exact prompt/control source | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-e2e-20260731.CKKG3r/` |
| 正式 sealed preflight | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-compat-fix-e2e-20260731.luZH43/candidate-preflight-release-final/bundle/agent-v0.2-candidate-evidence.json` |
| Platform restart receipt | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-compat-fix-e2e-20260731.luZH43/platform-restart-final/restart-receipt.json` |
| 浏览器 ready / prompt-filled | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-e2e-20260731.CKKG3r/browser/01-alphazerobeta-ready.png`、`02-alphazerobeta-prompt-filled.png` |
| 清理后 dark reload | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-e2e-20260731.CKKG3r/browser/14-alphazerobeta-final-dark-reloaded.png`（SHA-256 `92f17d04f1db3679768f839d1a0b2217deb63c2158d4b68391d56363a3474148`） |
| 最终稳定只读详情 | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-e2e-20260731.CKKG3r/browser/15-alphazerobeta-final-readonly-detail.png`（SHA-256 `2948247f0a1d70467828acbf75fe5805bfce2a090d368c3c10dc4de91d5210c6`） |

`candidate-preflight-final` 与 `candidate-preflight-keyfreeze-final` 是诊断过程产物；最终候选事实只
引用 `candidate-preflight-release-final`。任何后续仓库提交（包括 docs-only commit）都会改变
runtime identity，因此不得拿本审计中的已撤销 candidate 或 sealed manifest 直接打开 release。
浏览器视觉证据仅限上表实际存在且经复核的四个文件；不得在后续报告中补写其他编号。

## 7. 最终结论

AlphaZeroBeta 这条“联网搜索 → PDF 下载/解析 → 论文理解 → 精确审批 → 有条件提取/回测”真实
任务在修复后完成。它正确停在“论文非当前 HQA 可复现因子”这一分支，所以 Gate、factor、
backtest 与策略沉淀为 `EXPECTED_NOT_REACHED`。这证明本地私有 research-conversation 路径和
durable approval recovery 已打通；它没有证明 actionable paper Gate 纵切、Vertical A、完整
restart/fork 矩阵或 public V8 release 已完成。当前安全终态仍是 candidate revoked、connector
`reconcile_only`、public write/release OFF、zero orders。
