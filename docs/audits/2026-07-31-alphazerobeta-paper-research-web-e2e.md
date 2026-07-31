# AlphaZeroBeta 论文研究 `/hermes` Web E2E 审计

> 执行窗口：2026-07-31 至 2026-08-01（Asia/Shanghai）
> 审计范围：本机、单用户、私有 candidate 下的真实浏览器 → Platform → HQA connector →
> Hermes/provider → PostgreSQL/Hermes durable facts；不包含 public release/cutover。
> 结论：**两轮均为运行链路 PASS、论文 intake FAIL；public release/write 仍 OFF。**
> Command/Run 的 `succeeded` 只证明运行终态，不证明论文 intake、可复现性判断或后续领域纵切
> 通过。

## 1. 判定边界

本审计证明的是两层不同事实：网页、Session、dispatch、provider、approval、durable Run、直接
PDF/全文读取与数据库持久化能够工作；论文 intake 合同没有被运行时强制满足。尤其是
2026-08-01 retest 中，模型正文声称执行了 `web_search`，但权威 tool trace 记录为
`web_search=0`，不能用模型叙述覆盖工具事实。本文不接受该轮 reproducibility 或
non-actionable verdict，也不证明 Agent v0.2 全部发布 Gate、两条产品纵切、public composer、
release stamp/cutover 或 live trading 已完成。

状态含义：

- `PASS`：本窗口取得了可复核的运行或持久化证据。
- `FAIL`：真实尝试或所需合同失败；即使外层 Command/Run 为 `succeeded` 也保留失败。
- `UNVERIFIED / NOT ACCEPTED`：有模型输出，但缺少所需合同证据，不能作为研究结论接收。
- `NOT EVALUATED`：上游合同失败后没有资格判断的下游阶段；既不是通过，也不是
  `EXPECTED_NOT_REACHED`。
- `BLOCKED / OFF`：安全边界仍故意关闭，不能从本窗口推导开放。

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

首次运行输入位于
`/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-e2e-20260731.CKKG3r/`。

## 3. 两轮运行必须分开

| 窗口 | 运行事实 | 论文 intake 判定 |
|---|---|---|
| 首次真实 Web 尝试 | Hermes Session `web_211e8ec3eb6944bcc5c83f1eaae535e9a3964b6f`、Command `2f6d48f5-7a18-458c-bfc5-28c9923ae0e8`、Run `run_ac253949311b47929d445f50f963456a` 因缺失 durable approval snapshot 投影而失败；zero orders。 | **FAIL**。该尝试没有越过 approval recovery。 |
| 第一轮修复后完成态（2026-07-31 至 2026-08-01） | Candidate `candidate_5ddfd4db518146318beebf4a58f45d5a`；Platform Session `wm_fb5f44086e3c059ce65cf0f314a9222f`、Hermes Session `web_fb5f44086e3c059ce65cf0f314a9222fb0a1bee5`；Command `3176607c-4202-4646-8781-4bf7dcb1dab2` version 13 / attempt 1 和 Run `run_f62837e8fda84cd7a04a37239f258e2d` 为 `succeeded`。真实 provider、5 次 allow-once approval、直接 PDF/全文读取和 durable persistence 有证据；candidate 后续已 revoke。 | **FAIL（追溯纠正）**。原报告把外层成功和模型结论误写成 paper-research PASS；当时没有由运行时强制的 digest-bound intake contract、typed no-body tool receipts 与 HQA verifier，不能接受 reproducibility/non-actionable 判定。 |
| 2026-08-01 web-search retest | Candidate `candidate_087abe73ffb54fb9914fac6817862c01`、digest `6324041cca7b8a33ca40a55b5e24318bb4225f6c6e83019c843436f0eef0afa0`；Platform Session `wm_39f4577b534c9a9bca8eb5c634339408`、Hermes Session `web_39f4577b534c9a9bca8eb5c634339408cd82dd74`；Command `850d34cd-6286-4fdb-9151-4c6b333ef895` version 11 / attempt 1 和 Run `run_7cf82203191743ff85cb373285579ab6` 为 `succeeded`；candidate 后续已 revoke。 | **FAIL**。权威 trace 为 `web_search=0`、`web_extract=1` 且失败；模型 prose 声称使用 web search，trace 直接反证。 |

第一轮的 approval-projection 修复是真实闭环，但它只修复 approval recovery，不能据此把论文
intake 也判为通过。2026-08-01 retest 是新的 candidate、新的 Session/Command/Run 和新的
preflight，不能与第一轮合并成一个“最终重跑 PASS”。

## 4. 2026-08-01 retest 结果矩阵

| 检查项 | 状态 | 证据与解释 |
|---|---|---|
| Browser UI / managed Session | **PASS** | Platform Session `wm_39f4577b534c9a9bca8eb5c634339408` 精确对应 Hermes Session `web_39f4577b534c9a9bca8eb5c634339408cd82dd74`；浏览器提交和最终只读详情可复核。 |
| dispatch / provider / command approval | **PASS** | supervised connector 完成真实 dispatch；actual provider/model=`xai-oauth/grok-4.5`。Run usage=`489719` input、`3930` output、`493649` total；Session usage=`10` API calls、`53623` input、`436096` cache-read、`3930` output、`1668` reasoning。2 个 approval grant 均 exact allow-once 且 consumed。此项不推导论文 intake 成功。 |
| Command / durable Run | **PASS** | Command `850d34cd-6286-4fdb-9151-4c6b333ef895` 在 version 11、attempt 1 为 `succeeded`；Run `run_7cf82203191743ff85cb373285579ab6` 为 `succeeded`。 |
| Hermes durable events | **PASS（运行事实）** | `tool.started=13`、`tool.completed=13`、`run.completed=1`；`approval.request`、`approval.decision_recorded`、`approval.responded`、`approval.release_committed`、`approval.signalled` 各 `2`。这些事件证明 lifecycle，不证明 intake 合同。 |
| 直接 PDF / 全文读取 | **PASS** | 直接下载/读取路径取得 PDF 与全文证据；这是内容可访问性，不等于 web-search intake 合同完成。 |
| tool trace | **FAIL（paper intake）** | `web_search=0`；`web_extract=1` 且失败；`terminal=5`（其中一次 exit 124）；`read_file=5`；`skill_view=2`。模型 prose 声称 web search，不能覆盖该 trace。 |
| 数据库持久化 | **PASS** | PostgreSQL 有 exact managed Session 与 1 条 primary Command；Hermes authority 有 1 条 Run。该 Session 的 workflow binding=`0`、Gate challenge/action/completion=`0/0/0`，primary Command 的 run link=`0`；typed result、Platform run/backtest 均为 `0`。成功落库不升级研究结论的可信度。 |
| reproducibility 判断 | **UNVERIFIED / NOT ACCEPTED** | paper-intake contract 未满足，因而没有可接受的、由 HQA verifier 绑定的 reproducibility receipt。 |
| non-actionable 研究结论 | **UNVERIFIED / NOT ACCEPTED** | 模型可以输出该结论，但本轮 trace 不足以证明它来自合规 intake；不得把 prose 当权威 verdict。 |
| factor / backtest / Gate / result | **NOT EVALUATED** | 上游 intake 已失败，不能把零下游写入解释为 `EXPECTED_NOT_REACHED` 或 non-actionable branch PASS。 |
| candidate 清理 | **PASS** | Candidate `candidate_087abe73ffb54fb9914fac6817862c01`、digest `6324041cca7b8a33ca40a55b5e24318bb4225f6c6e83019c843436f0eef0afa0` 于 `2026-07-31T22:20:43.863331Z` revoke，close reason 明确记录 paper-intake failure；open candidates=`0`。connector 恢复 `reconcile_only`。revoke 路径按设计不填写 `final_order_snapshot_digest`，不得伪称它已封存。 |
| 交易边界 | **PASS** | canonical zero-order snapshot SHA-256=`c4d6979ffddeed35fad34ca6daef30907c7bc8036297ce0b6332b6bfa1ad295d`：account=`1`、ledger=`12`（max seq `12`）、pending=`0`、positions=`3`；四张权威表 delta rows=`0`，paper-authority epoch=`197` 未变，`kill_switch=true`。 |
| public release/write | **BLOCKED / OFF（预期）** | cleanup 后 `release_authorized=false`、public cutover OFF、`chat_write_ready=false`，composer 已恢复只读；私有运行不构成 release 授权。 |

## 5. P1 residual：运行时必须 fail closed

重测前已把 Hermes Web search backend 精确配置为 `xai`，真实直接 `web_search` smoke 能返回
arXiv 主源；安装态 HQA skill 也已是 1.18.5，并明确要求实际 `web_search`。因此本次
在先调用 `skill_view(arxiv)` 与 `skill_view(hqa-quant)` 后仍出现的 `web_search=0`，不能归因于
搜索 provider 不可用或 skill 未加载，而是 skill 提示与流程 hardening 没有强制执行成功条件。
重测证明仅改配置/skill 不足。下一次 paper-research candidate 之前，运行时至少需要：

1. 在执行前绑定 digest-bound `execution_contract=hqa.paper_intake/v1`；
2. 为 `web_search`、`web_extract`、直接 PDF/全文读取等步骤生成 typed、no-body tool
   receipts，只投影类型、结果、digest/计数等必要事实，不泄漏正文；
3. 通过固定端口调用 HQA subprocess verifier 校验 exact contract 与 receipts；
4. verifier 不通过时必须在 `mark_succeeded` 之前 fail closed，不能让模型 prose 或外层
   Run terminal status 替代合同事实。

这项是 **P1 residual**，不是已实现能力，也不授权重新打开 candidate 或 public cutover。

## 6. preflight、测试与 artifact

2026-08-01 retest 的正式 preflight 为：

`/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-websearch-retest-20260801.pEDa3x/preflight/agent-v0.2-candidate-evidence.json`

- SHA-256：
  `eba8099bf3801927f3d93b40d1e133546d7cbcc4eece4c58b416bf52bd29a136`
- Platform：`2764 passed / 255 skipped / 0 failed`
- HQA：`2140 passed / 17 skipped / 0 failed`
- Hermes focused：`299 passed / 0 skipped / 0 failed`
- frontend：`429 passed / 0 skipped / 0 failed`
- 合计：`5632 passed / 272 skipped / 0 failed`
- runtime identity：Hermes
  `199a251d20ec62be3845681f40d220a40fabd7d8`、HQA
  `669c247f8b0d33c8a90e6381c3f0828519304816`、Platform
  `53f7280dbd66ecb79add9fc377db2de8a3d22edd`

这些测试证明候选源和已列套件通过，不覆盖 live paper-intake semantic failure。
下表中不以 `/` 开头的路径均相对 `retest bundle`。

| 证据 | 路径 |
|---|---|
| retest bundle | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-websearch-retest-20260801.pEDa3x/` |
| read-only oracle summary（非 release receipt） | `oracle-summary.json`（SHA-256 `c29e42014a9562a8826fad8cc506de74ba0f80b9e88daaaf9a49d15ee3767e8c`） |
| direct PDF | `paper/2607.18001.pdf`（`750580` bytes；SHA-256 `d9b61183059b5b17d1dc32dc9a690babd3a1e068ec48652c3d975adf70b2778f`） |
| extracted full text | `paper/2607.18001.txt`（`152195` bytes；SHA-256 `e728f588387419626bf81f10a232fdf8ff5003ce422a98c640f0b83f84f82bdb`） |
| prompt filled | `browser/01-prompt-filled.png`（SHA-256 `280521adf304b892a1e8fcb0cdba3adac2c406c0efc4112570f07861700fec25`） |
| prompt sent | `browser/02-prompt-sent.png`（SHA-256 `60d3c69ce1caf289cfe4168b687ef5c6e0459ccbd4a71769d3d4a61b6f0b80b9`） |
| final live UI | `browser/03-final-live.png`（SHA-256 `c9514ce2de63a3f2e7de5447d114279712ead368c914b4e85d114640f8c0f5cd`） |
| final read-only detail | `browser/04-final-readonly-detail.png`（SHA-256 `9222c2748ca2e83721a7f33893844ec57c0f3313eab80b82e366c2960c02b97a`） |
| Platform restart receipt | `platform-restart-retry/restart-receipt.json`（SHA-256 `2299d5bf7d4b244b426e5e5dfccf1bfbad9d1db2348e7c07cc3215c0b8416602`，status=`passed`、`release_authorized=false`） |
| 第一轮 exact prompt/control source | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-e2e-20260731.CKKG3r/` |
| 第一轮 sealed preflight | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-compat-fix-e2e-20260731.luZH43/candidate-preflight-release-final/bundle/agent-v0.2-candidate-evidence.json` |
| 第一轮 Platform restart receipt | `/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-compat-fix-e2e-20260731.luZH43/platform-restart-final/restart-receipt.json` |

第一轮环境证据继续只支持其明确子项：Hermes
`199a251d20ec62be3845681f40d220a40fabd7d8`、HQA
`005e92ed7849ea2956bff18b72e399b407b67895`、Platform
`2eb714d1ef4ece96a664a816b1f3392d1640809e` 的安装/restart/compatibility 记录；旧 sealed
manifest SHA-256
`439b5731b52e761168caaa5202e495a0c0c7f2ef2aa50f7557864eb2eb110da5`；以及 pre-028 backup
`/Users/sunyibo/programs/Hermes-quant-agent/artifacts/maple-e2e-20260731T060327Z/live-pre028-backup/quantplatform-pre028.dump`
SHA-256
`017d29a6abb4a4cd0c51e7e6f573dab250f9f45a3b21e350cd80d3ff0b7b273e`、隔离 restore 和 schema
fingerprint `e3f713ac05a1a990cfa9be45157e880e06709c425a4883736544d8f2b626f33a`。
这些事实不修复两轮 paper-intake failure。

任何后续仓库提交都会改变 runtime identity，因此不得复用两轮已撤销 candidate 或旧 sealed
manifest 直接打开 release。

## 7. 安全终态与最终结论

两轮 AlphaZeroBeta 都证明了本地私有 UI/Session/dispatch/provider/approval/durable
Run/direct-PDF/full-text/数据库路径中的相应子项，但**都没有通过 paper intake**。因此：

- reproducibility 与 non-actionable research verdict 均为
  `UNVERIFIED / NOT ACCEPTED`；
- factor、backtest、Gate 与 result 为 `NOT EVALUATED`；
- zero orders 通过，`kill_switch=true`；
- retest candidate 已 revoke，connector=`reconcile_only`，composer 已恢复只读；
- public cutover OFF，不能声明 release authorization。

下一准入不是重述模型答案，而是先交付 P1 运行时 execution contract/receipt/verifier/fail-before-
`mark_succeeded`，再使用新的 exact candidate 重测。完整 browser DoD、Vertical A、
actionable-paper Gate 纵切、release stamp/cutover 仍各自未被本审计证明。
