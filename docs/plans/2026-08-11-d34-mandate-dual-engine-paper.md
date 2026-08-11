# D-34：Mandate 驱动的双引擎自主 Paper 研究助手

## 1. 目标

D-34 把个人研究工作流收敛为一条可长期运行的本机闭环：

```text
30 天 Mandate
→ Futu 权威快照
→ RD-Agent / Qlib 提出并迭代假设
→ Platform 独立重放成交、费用、风险与 NAV
→ Artifact Registry + 确定性 Policy
→ 真实 paper canary sleeve
→ 自动估值、暂停、demote、回滚与复盘
```

它优先保证本地研究顺畅度。Docker 是开放的本机开发环境，不作为敌对安全边界；允许
root、bridge、Docker socket 和项目/缓存/数据目录读写挂载。只保留作业超时、容器清理、
paper 限额、emergency stop、审计和恢复所需的约束。

## 2. 不变边界

- D-34 Artifact 永远是 `paper_only`，不能原地升级到 live；live 仍走全新的人工资格链。
- 不自动 push GitHub，不自动 apply migration。
- emergency stop 优先级最高；它停止新研究和新 paper 订单，但不伪造平仓。
- paper 单 sleeve、总暴露、单标的、日配额、日亏与回撤限制始终生效。
- D-33 保留为回退路径；切换或回滚默认 hold，不自动 flatten。

## 3. 仓库与部署边界

- 两个本地 `main` 仍是唯一集成与 GitHub 发布基线；D-34 后续切片在
  `/Users/sunyibo/programs/.worktrees/d34/{Hermes-quant-agent,ai-quant-platform}` 的
  purpose worktree 上开发，按 Slice 验收后再 fast-forward 合回 `main`。
- D-34 Platform 修正截止 `2640dbc`，已 fast-forward 进本地 `main`；并行前端修正合入后，
  当前主 checkout 与 runtime mirror 均为 `9f453c9`。HQA 文档分支仅承载本记录。
- AsiaRadar 的 runtime WIP 未被 D-34 合并、清理或提交。
- `data/_runtime/agent-v02-work/*` 仍是部署镜像，只允许 fetch/fast-forward；禁止直接开发。
- 2026-08-12 正式库已按 030 → 031 → 032 应用，runtime mirror 与主 checkout
  SHA 一致；开发仍禁止直接在 runtime mirror 进行。

## 4. 正式契约与权威

### 4.1 PostgreSQL

- `030_d34_mandate_policy.sql`：Mandate、确定性 PolicyDecision、emergency-stop 事件。
- `031_d34_experiment_jobs.sql`：durable job、lease、heartbeat、attempt、预算与恢复。
- `032_d34_artifact_canary.sql`：双引擎 receipt、comparison、Artifact、canary lifecycle。

三份 migration 都必须通过 source 检查、一次性 PostgreSQL 全链 apply 和 runtime 最小权限
测试。正式库不由启动脚本或无人值守 worker apply。

### 4.2 版本化对象

- `hqa.mandate/v1`
- `hqa.market_data_snapshot/v1`
- `hqa.d34_experiment_job/v1`
- `hqa.d34_artifact/v1`
- `hqa.d34_engine_receipt/v1`
- `hqa.d34_comparison/v1`
- `hqa.d34_policy_decision/v1`
- `hqa.d34_canary/v1`

Artifact 绑定 Mandate、policy、snapshot、候选代码、Qlib 配置、RD-Agent/Qlib commit、Docker
image digest、两份 engine receipt 和 comparison receipt。Futu Parquet 是权威快照；Qlib
provider URI 是可重建缓存，禁止 sample/Yahoo/community dataset 静默 fallback。

## 5. 双引擎分工

- RD-Agent/Qlib：提出假设、生成因子代码、计算因子、研究回测和目标权重。
- Platform：消费同一 snapshot 与目标权重，独立重放成交、费用、持仓、风险和 NAV。
- Platform 不复制因子公式来伪装“独立证明”。已知因子 oracle 只验证 adapter 与重放链。
- exact input digest 必须一致；初始比较阈值为日收益相关性 `>=0.995`、期末 NAV 差
  `<=25 bps`、单标的权重差 `<=50 bps`。阈值只能通过新 policy version 修改。

## 6. Mandate 与默认限额

默认 Mandate 有效 30 天，universe 为 `SPY/QQQ/IWM/DIA`；每周期 1 个假设、最多 3 次
迭代、每次最多 3 个实验、并发 1。LLM 预算默认 100 美元，80% 提醒，100% 后不再启动
新实验。Mandate 可一次授权 `paper_execution_allowed=true`，普通部署或重启不需要重新点开。

初始 paper 限额复用 D-33 保守档：

- 单 sleeve `min($10,000, 1% NAV)`；自动 sleeve 合计不超过 `10% NAV`。
- 每日最多 1 个新 canary；单标的自动合计不超过 `5% NAV`。
- 日亏 2% 或从峰值回撤 10% 自动 pause。

## 7. 常驻循环与恢复

独立 LaunchAgent 在关闭 Codex/Claude/终端后继续运行。每轮先读取有效安全状态并维护已有
canary，再决定是否启动研究：

1. 对 running/paused/demoted/rolled-back canary 继续估值和记录 P&L/回撤；风险越线时
   先暂停本地 sleeve，再 CAS 更新 Registry。
2. 若 paper 权限有效，按 next-open 时窗生成/执行 D-34 paper 计划；执行前再次读取
   emergency stop 与 Mandate，并用实际价格/订单金额重新运行统一 Policy；旧 pending plan
   不能穿透新 stop，也不能与其他 canary 累计越过账户级单标的上限。
3. 已完成研究但尚未写完 Artifact/canary 的 terminal phase 可幂等恢复；expired lease 收敛为
   `outcome_unknown` 并保留 receipt 等待核对，不盲目重跑无法证明结果的研究。
4. 只有上海时区周二至周六 06:00 以后才创建新 snapshot/job；canary 维护和 terminal
   recovery 不受研究窗口限制。
5. 作业状态固定为
   `queued → leased → running → succeeded/rejected/outcome_unknown/cancelled`。
6. job key、attempt、receipt、Artifact、canary 和预算消费均幂等；重启不得重复下单。
7. 每个 Docker 子任务前后记录 Platform/HQA Git status 与 tracked diff；本次作业造成 dirty 时
   写 durable anomaly，但不 reset、删除或自动提交。常驻 runner 只接受 Python 3.11。

Mandate 的 `max_concurrent_jobs` 在数据库 lease 时锁定并计数。新 canary 先以
`paused/awaiting_registry` 持久化，Registry 成功后才恢复执行。D-34 的 `top_k=1` 语义不套用
D-33 的单 sleeve 40% 分散化限制；它仍受单 sleeve 1%、自动合计 10% 和账户级单标的 5%
限制。D-33 与 D-34 都走 `paper-execution-policy/v2`。D-34 每个实际 accepted/rejected order
batch 在订单变更前追加写入 `d34_policy_decisions`；同一 execution 幂等，不同 execution 即使
输入相同也有独立审计记录。审计写入失败时订单保持 blocked。

## 8. 本地 owner 接口与工作台

Owner API 提供 Mandate create/list/active/pause/resume/renew/revoke、job、D-34 Artifact、
canary pause/demote、D-34 rollback、emergency stop 与 `/api/safety/effective/v2`。旧的统一
`GET /api/hermes/artifacts` 合同保持兼容；D-34 专属血缘使用
`GET /api/hermes/d34/artifacts`，再由工作台统一呈现。

`/hermes` D-34 工作台显示 Mandate、预算、当前 job、Artifact 双引擎 correlation/NAV/weight
差异、paper canary P&L/回撤、真实 sleeve 现金/持仓、风险限额与异常。UI 不提供 live 升级
按钮，emergency stop 始终可见；持仓仍从 paper sleeve 权威读取，不复制到 Artifact Registry。

## 9. 交付状态（2026-08-12 runtime snapshot）

| 切片 | Source 状态 | Runtime 状态 |
|---|---|---|
| 0 开放 Docker + pins | 已复用 Hermes xAI OAuth，移除无实际使用的 embedding 依赖；真实 JSON/Qlib/Futu/Docker child smoke 通过 | `com.aiquant.hermes-oauth-proxy` 与 D-34 worker 已常驻 |
| 1 纵向闭环 + 030–032 | 已实现 | 正式库 030–032 已顺序 apply，受限 runtime role 已验证 |
| 2 snapshot/adapter/双引擎 | 已实现 | 真实 Futu snapshot、Qlib provider、Qlib 回测和 Platform replay 已运行 |
| 3 Policy/worker/canary | 已实现 | Artifact `artifact-ca04678e7f6ce784878cbbc989507747` 通过比较并创建运行中 canary，额度 `9986.08` |
| 4 `/hermes` 工作台 | 已实现，frontend production build 通过 | 已随 runtime 部署 |
| 5 主用/回退 | 机制已实现 | 首个周期已完成；10 周期/5 交易日运行门尚未完成 |

既有 D-34 纵向实现已在 Platform `main`；本轮 Slice 0 在并行 AsiaRadar 合入后重排为：
`79f968c` 加入启用态 preflight，`01bf05b` 修正 pinned RD-Agent env，`db2068f` 让 Platform
wheel 在固定构建工具下无需临时下载 build dependency，`ce9fc28` 同步 operator 文档，
`a00ec37` 排除 frontend build artifact 对 image context/digest 的污染，`95d908b` 让 owner-env
阻塞通过 preflight 公共 JSON 返回稳定的 `d34_env_*` code，`1df7c16` 将 preflight 与正式
`hqa.effective_paper_safety/v2` authority contract 对齐，消除 provider/migration 就绪后才会出现的
必失败漂移。HQA 的恢复验证兼容提交仍为 `ab977e9`。这些都是 source 事实；disabled
LaunchAgent 安装也不是 migration apply、启用态 provider smoke 或 paper 订单运行证据。

## 10. Source 验收证据

- Platform 最新 main + D-34 组合态：Python 3.11.15、显式 worktree `PYTHONPATH` 下全量
  `2977 passed, 259 skipped`；其后的最终 Docker-context delta 另以 D-34 API/runtime 定向集合
  `62 passed, 1 skipped` 验收。`95d908b` 的稳定 blocker delta 另以全部 `test_d34_*.py`
  `57 passed, 1 skipped`、preflight/env/LaunchAgent 相关 `23 passed` 和变更文件 Ruff 验收。
  `1df7c16` 的真实 safety-contract delta 以 D-34/API 定向 `64 passed, 1 skipped`、全量 Ruff、
  frontend typecheck/ESLint 与 Chromium D-34 E2E `1 passed` 验收。`ruff check src tests` 与
  `git diff --check` 均通过。
- HQA 与最新 main 的组合态全量：`2220 passed, 4 skipped, 0 failed`；恢复闭包 34 项定向测试
  通过。新增修复只接受 UV 管理根下、最终解析为同一 3.11 解释器且文件 digest 一致的
  minor alias；外部、内部跳转、越界、悬空和循环 symlink 仍 fail closed。
- Frontend 与当前 Slice 0 source：Vitest `80 files / 485 tests`、typecheck、ESLint、Next
  production build 均通过；
  `PW_E2E=1` 的 D-34 浏览器流程 `1 passed`，覆盖 Mandate 续期、比较数值、canary P&L/回撤、
  sleeve 现金/持仓、风险限额和 live 按钮缺失；生成类型已同步。
- PostgreSQL：一次性隔离数据库从 001 顺序 apply 到 032，并以受限 runtime role 运行 D-34
  authority 测试，`1 passed`；覆盖实际 order-batch policy append-only/幂等/跨 execution 身份与
  Artifact comparison 列表投影。临时数据库已删除，正式库没有改变。
- Docker：镜像 `hqa-d34-rdagent-qlib:0.1.0` 从当前 Slice 0 source 重建，ID 为
  `sha256:de57c7561f636f1d16b7ff34815cff0ed52848993d0fc6657ccd3a5b724a7242`；
  固定 RD-Agent `274e274d5dbb72cc2ea139d1a7c93d73ce9b1198`、Qlib
  `da920b7f954f48ab1bb64117c976710de198373e`。Python 3.11.15、Qlib backtest 30/15 行、
  宿主 Futu socket 与 Docker socket child smoke 通过。首次重建真实复现了 Platform wheel
  build-isolation 的网络依赖；修复后该 wheel 步骤不再访问 package index，并重建成功。最终
  build context 从 frontend build 后的 416.93 MB 收敛为只含 Python package 的 77.84 kB，
  `.next/.tmp/node_modules` 不再改变 D-34 image digest。
- 真实 Futu snapshot 为 4 个标的、27 个交易日、108 行，digest
  `e1ea96bbec3a386e26e0814e32b9ab3b4e0b3892ec9b53f7dcdd95d4fd1cdb31`。
  最终镜像内的确定性 proposal 闭环真实运行 Qlib 与 Platform replay：日收益相关性
  `0.9999974003`、NAV 差 `0.073594 bps`、最大权重差 `42.428420 bps`，comparison
  accepted。这里替代的只有 LLM proposal，用于验证数据/双引擎集成，不能冒充真实 LLM
  round-trip。
- Runtime 验收：Hermes xAI OAuth 代理的 `grok-4.5` 真实 JSON round-trip 通过，
  D-34 不再需要单独 embedding provider。首个周期的 comparison 为 correlation
  `0.9999993722`、NAV 差 `0.507243 bps`、最大权重差 `11.743665 bps`，
  `exact_inputs=true` 且 accepted。首次坏 schema 已保留为 `outcome_unknown`；修复后
  retry 完成研究，并从 canary activation 的 float/Decimal 边界失败中幂等恢复。

## 11. 剩余运行验收

- 至少 10 次完整自动周期、5 个交易日 canary；覆盖 restart、Futu/LLM/Docker 失败、digest
  mismatch、emergency stop、重复运行与 outcome unknown。
- 证明零重复订单/Artifact/预算消费，且无 live eligibility、无自动 GitHub push。
- 达标后 D-34 成为新研究入口；D-33 只监控旧 sleeve 并保留一键回退。
