# 全自动 paper 路径实施计划（D-33）— 修订版

> **历史文件，不是现行计划。** 2026-08-13 起只按
> [`2026-08-13-personal-quant-assistant.md`](2026-08-13-personal-quant-assistant.md)
> 施工。本文是研究账「论文入队」来源的实现记录。不要按未完成方框续写，也不要把 D-33 当成产品线。

**日期**：2026-08-10  
**状态**：**Slices 1–5 源码与文档已实施；全量验收、runtime 对齐与双 Flag 启用进行中（2026-08-10）**
**范围**：HQA + Platform 两仓；paper 全自动；live 永远人工  
**修订原则（写给怕「又搞成什么都干不了」的你）**：

> **砍的是人闸，不是安全。**  
> 人工 Gate 1/2/3 在 **paper 自动模式**下会被 **机器策略**整段替换，不会再要你点三下。  
> 保留/加强的，全是**结构性隔离**和**机器可判的硬条件**——不是新的「请再授权一次」仪式。  
> 若某条规则会让你日常「论文→paper 策略」再次卡住等人点确认，它就不该以「硬性前置门」的名义存在于 paper 自动路径。

**前置决策（用户已拍 + Codex 修订后的落地）**：
1. 范围 = 端到端 Slice 1–5  
2. paper 限额 = **首发保守档**（下文）；25k/50%/2次/天 仅作后续升级上限  
3. Platform 分叉 = 一并统一  

**§15 确认进度（2026-08-10 全部确认）**：
- [x] 1 `paper_only` 结构性隔离 — **要**
- [x] 2 首发限额 10k/1% NAV、合计 10%、1 promote/天、2%/10% 暂停 — **接受**
- [x] 3 e400553：release 赢基建 + 扩大自动测试门 — **接受**
- [x] 4 Slice 2 = P1+管道；全自动过门只在 Slice 4 — **接受（按推荐）**
- [x] 5 Slice 4 driver-only + LaunchAgent — **接受（按推荐）**
- [x] 6 land 不 auto-push — **接受（按推荐）**
- [x] 7 demote 默认 quarantined_hold — **接受（按推荐）**
- [x] 8 先 commit 计划 → 可逆冻结 — **接受（按推荐）**

---

## 0. 一句话目标

「论文 → 因子 → 回测 → **仅 paper** 常驻路径」对 solo-owner **全自动**；  
带 **机器评审政策 + 限额 + 审计 + 可恢复 demote**；  
**live 路径永远人工**，且 **自动晋级因子永远不能继承为 live 资格**。

---

## 0.1 初心对齐：Codex 说的「硬性前置」里，哪些是真的、哪些会变成新仪式

| Codex 点 | 判定 | 我们怎么落 |
|---|---|---|
| `paper_only` 资格与 live 注册表隔离 | **真风险，必须做** | 结构性：自动因子写进独立资格，live registry **物理上装不进去**。你日常 paper 自动**零额外点击** |
| Slice 2 状态机自相矛盾 | **真 bug，必须改** | 统一口径：Slice 2 = P1 + 跑通到 **可 final-backtest 的 approved candidate** 的**机械能力**；**全自动过门在 Slice 4 一次打开**，不在 Slice 2 半自动半人工拖泥带水 |
| P1 只靠一次 web_search 太弱 | **真风险，必须加强** | 机器收据链，不是人审论文。失败 = 自动标失败，不是弹窗请你批准 |
| 限额首发更保守 | **接受** | 默认收紧；你以后一条配置调大，不必改代码 |
| demote 默认 hold 语义含糊 | **接受** | 状态机说清楚；不是再加审批 |
| 迁移 029 要单独批 | **仪式倾向 → 砍掉「再批一次」** | 总计划批准即含 029 设计；**执行 Slice 3 时只做一次确认文案**，不搞第二次「授权会议」 |
| Phase 0「只读」 | **用词错误** | 改称 **「可逆冻结」**（会写 bundle/tag/补丁，但可回滚、不改业务行为） |
| e400553 不能只靠两组测试 | **接受** | 扩大测试门，仍是自动测，不是人工闸 |

**明确拒绝的「假前置」**（不做）：
- 每个自动 promote 再要你确认一次  
- paper 自动路径保留「人工 Gate1 + 人工 Gate2」作为长期常态  
- 把「ordered universe allowlist」做成每次研究都要人填的表单（改为：**可选**预置默认 universe；未配置时用策略里写死的默认池 + 记入 policy digest；**禁止模型临时编造 universe 却不落盘**）  
- public release / live 相关任何放行  

---

## 1. 问题诊断（代码事实）

### 1.1 你砍过的是身份仪式，不是因子闸门

`QS_LOCAL_TRUST_MODE` 只松 candidate admission 身份仪式。  
Gate 1/2/3 仍是结构性硬编码（见初版锚点：`factor_repro.py:325/600`、`paper_gate_authority.py:602-603`、`paper_research_cli.py:3468`、`factor_repro_cli.py:723`）。

### 1.2 paper-intake 卡的是强制，不是读不到论文

AlphaZeroBeta：PDF/全文 PASS，`web_search=0` 却 claimed search。  
P1 四件套仍不存在；prompt 加固已被证明不够。

### 1.3 安全网没接到真 paper 路径

`RiskEngine` 只在回测模拟；`account_service.py:453-457`：kill_switch 是 paper **唯一**盘前闸门。  
无 demote；无 auto-promote 日配额权威账本。

### 1.4 最大结构性洞：晋级因子没有 paper/live 资格分裂

`build_factor_registry(include_promoted=True)`（`registry.py:62+`）把 **所有** `PROMOTED_FACTORS` 装进 resident 路径。  
**没有** `paper_only` vs `live_eligible`。  
因此「只靠 `live_trading_enabled=false`」**不够**：一旦有人/未来误开 live，自动晋级代码与人工晋级代码在注册表里**同权**。  
→ 本计划 **开工阻塞级** 修复：资格隔离（见 §2、§8）。

### 1.5 final backtest 不能对 pending candidate 跑

`load_approved_factor_candidate`（`promotion.py:429+`）要求 `approval_binding == "approved"`。  
→ 「不 approve 就 final-backtest」在**当前平台 API 下不可能**。状态机必须诚实（§6）。

### 1.6 现场拓扑（2026-08-10 复核）

| 位置 | tip / 状态 |
|---|---|
| Platform runtime | `f3b346b`，`codex/agent-v0-2-release`，**35** dirty（33 tracked + 2 untracked） |
| Platform 普通 checkout | `854a65f`，`codex/agent-v0-2-platform-v1` |
| GitHub Platform `main` | `197bc17`，**当前无 branch protection** |
| merge-base | `dc863e1`；main 是祖先 → 可 ff 发布 |
| HQA 根仓 | `620c2b9`（文档续有提交；计划须入 Git） |
| HQA runtime clone | 仍 `84c4484`，**落后根仓**，Slice 1 窗口一并对齐 |
| 本计划文件 | 仍 **untracked** → 修订后先 commit 再冻结 |
| e400553 | **26 files / +2675/-209**，测试门必须宽于「两组 lifecycle」 |

HQA wrapper 默认 `HQA_AIQP_DIR=/Users/sunyibo/programs/ai-quant-platform` → **CLI 跑 A、服务跑 B** 仍在。

---

## 2. 目标架构

```
[paper 自动模式 — flag 默认 OFF；solo；LaunchAgent/本机常驻，不依附 AI 终端]
  论文
    → P1 强制 intake 收据链（发现+正文+身份+lineage）
    → 机器 Gate1（digest+note，reviewer 痕迹=auto）
    → 机器 Gate2（CAS + **版本化机器评审政策** policy digest）
    → final backtest（仅 approved）
    → 机器 Gate3 prepare → auto-commit → 本地 ff-land
    → 写入资格 promotion_scope=paper_only（不可变）
    → paper registry / sleeve 仅消费 paper_only|live_eligible
    → 限额 + 审计 + demote 状态机

[live 路径 — 永远]
  仅 promotion_scope=live_eligible 且 reviewer=manual 的因子
  原人工 Gate1/2/3
  自动 paper 因子要进 live = **全新一次人工晋级**，不继承 paper 自动结果
```

**红线**
- `live_trading_enabled=false` + 确认短语校验器  
- kill_switch 默认 true  
- 自动路径 **零** live 下单面  
- AST / 单 BaseFactor / digest CAS / never-execute / 原子写 全部保留  
- public release 不在范围  

---

## 3. 资格模型（开工阻塞项 — 这是「隔离」不是「仪式」）

### 3.1 数据

每个晋级因子（模块头 + registry 元数据 + 审计事件）固定带：

| 字段 | 自动 paper | 人工 live |
|---|---|---|
| `promotion_scope` | `paper_only`（不可变） | `live_eligible` |
| `reviewer` | `auto` | `manual` |
| `automation_policy_digest` | 机器评审政策 sha256 | 空或 N/A |
| `intake_contract_digest` | P1 合同 | 按人工流程 |

### 3.2 注册表分裂（推荐实现）

- `library/promoted/` 可仍放代码文件，但 **`PROMOTED_FACTORS` 拆成**：
  - `PAPER_PROMOTED_FACTORS`（含 `paper_only` + 可选 `live_eligible`）
  - `LIVE_ELIGIBLE_FACTORS`（**仅** `live_eligible` + `reviewer=manual`）
- `build_factor_registry(purpose="paper"|"live")`：
  - paper sleeve / 日频信号：`purpose="paper"` → paper 集  
  - 任何未来 live/broker 路径：`purpose="live"` → **只** live 集  
- **拒绝**：`paper_only` 因子被 live builder 注册（硬报错，不是警告）

你日常无感：自动链路只写 `paper_only`；不会多出对话框。

### 3.3 升级到 live

单独命令/流程：`promote-to-live-eligible`，**强制人工** Gate 等价物 + 新 digest；**禁止** flag 自动执行。

---

## 4. 限额 — 首发保守档

账户默认本金 `DEFAULT_INITIAL_CASH = 1_000_000`。

| 键 | **首发默认** | 后续可升到（配置上限参考） |
|---|---|---|
| 单 sleeve 现金 | **`min(10_000, 1% 当前 NAV)`** | 25_000 / 2.5% NAV |
| 自动 sleeve 合计 | **10% NAV** | 50% NAV |
| 日 promote | **1** | 2 |
| 日 demote | 5 | 5 |
| sleeve 日亏 pause | **2%**（对齐 `RiskLimits`） | 5% |
| sleeve 回撤 pause | **10%**（对齐 `RiskLimits`） | 20% |
| sleeve 单票 | 0.40 | 0.40 |
| 单笔 order | 10_000 | 10_000 |

**额外（Codex，接受）**
- 账户级单票跨 sleeve 聚合暴露上限（首发 5% NAV）  
- 同 `factor_id` / 同 manifest 拒绝重复 auto-sleeve  
- 日配额 **权威 = DB 表（029 账本）**；JSON 仅缓存，冲突以 DB 为准  

**RiskEngine 接线注意**：sleeve 级 `RiskLimits` 必须 `kill_switch=False`；账户 kill_switch 仍是外层。

---

## 5. 五切片顺序（不变，口径已修）

```
1  Platform 统一 main
2  P1 + 自动研究到「approved + final backtest」的机械能力
   （全自动过门的开关与机器政策在 4 打开；2 先把 P1 和回测链做实）
3  安全网（限额/审计/demote 状态机/资格字段落地）
4  打开 paper 全自动 Gate1/2/3 + land + 只写 paper_only
5  文档/skill/记忆
```

**依赖**：4 不得在 3 的资格隔离 + 限额 + 审计未绿时打开。  
**029 迁移**：随 Slice 3 实施；总计划批准 = 设计批准；执行前在 Slice 3 开头用清单勾选「现在 apply 029」，**不是**第二套授权体系。

---

## 6. Slice 1 — Platform → 单一 main

（技术步骤同前一版 Phase 0–6，以下为修订点。）

### 6.1 用词
- Phase 0 = **可逆冻结**（bundle、dirty 补丁、annotated tag、push tags）—— **会写 Git refs**，不是「只读」。

### 6.2 计划与 HQA 对齐（新增）
1. **先把本计划 commit 进 HQA `main`**（结束 untracked）  
2. HQA runtime clone fast-forward 到根仓 tip（现 `620c2b9`+）  
3. 再开 Platform Phase 0  

### 6.3 e400553（26 文件 / +2675）
- 规则仍：release 赢共享 hermes 基础设施；回填真正新 recovery  
- **测试门扩大**（自动，不是人闸）：  
  `test_hermes_run_lifecycle_port`、`test_hermes_connector_dispatch`、  
  `test_hermes_http_dispatch_adapter`、`test_hermes_connector_cli`、  
  `test_composite_turn_submit`、相关 frontend workspace/composer、  
  以及任何 PostgreSQL/恢复相关触及测试  
- 全量 backend pytest + frontend vitest/eslint/`next build` 仍为发布门  

### 6.4 发布与保护
- ff 推 `main` → smoke → **再**加与 HQA 相同三保护  
- 规范工作目录 = runtime 路径；HQA `AIQP_DIR` / install.sh / 包装重装锁步（顺序 5.1→5.3→5.2）  

### 6.5 验收
- 远程只剩 main + archive tags；两副本 tip 一致  
- CLI 与服务同一树；安全姿态不变  
- bundle verify 入审计文档  

---

## 7. Slice 2 — P1 + 研究链到 final backtest（口径已统一）

### 7.1 目标
1. P1 运行时强制（无收据不能 succeeded）  
2. 一条 **可重复** 的「论文 → factor source →（approve）→ final backtest receipt」链在代码里跑通  
3. **不** land promote；**不**写 live 资格  

### 7.2 状态机（消除自相矛盾）

**禁止**再写：「机器调 human-reviewed Gate1，但自动化又算 Slice 4」。

**Slice 2 交付物**：
```
P1 intake 强制
→ 生成 factor source（Hermes）
→ propose 得到 pending candidate
→ 【开发/验收期】可用「测试夹具或 flag 下的 machine approve」
     仅用于证明 final-backtest 管道；
     默认产品行为仍是：未开 Slice4 flag 时 Gate2 保持人工
→ final backtest receipt（平台要求 approved —— 见 promotion.py）
→ 停止在「有 receipt 的 candidate」，不 promote
```

**Slice 4 交付物**：同一条链上 **Gate1/2/3 + land** 在 `factor_automation` flag 下全自动，且只产出 `paper_only`。

即：Slice 2 修 **管道与 P1**；Slice 4 开 **自动过门**。不是 Slice 2 永久保留三道人闸。

### 7.3 P1 通过条件（加强，仍全自动）

必须同时具备（digest 绑定；prose 无效）：

```
来源发现（web_search≥1 结果 digest 或 用户/配置预设 URL）
+ 正文获取（direct_pdf 或 web_extract/full_text，字节下限 + sha256）
+ 论文身份（title/归一化 id 至少一项落盘）
+ lineage：factor source 字节 digest 与 intake receipt 绑定
```

挂载点不变：dispatch 绑 `execution_contract=hqa.paper_intake/v1`；  
`connector_worker.py:670` 前 verifier fail-closed；  
verifier 镜像现有 subprocess-port 模板。

### 7.4 机器评审政策（为 Slice 4 Gate2 准备，Slice 2 末可先落 schema）

版本化文件（例 `config/factor_automation_policy.v1.json`），digest 写入审计：
- 最小样本长度 / 样本外段  
- 成本假设、最大回撤、换手上限  
- 数据覆盖率、lookahead 静态检查（复用现有 AST/安全检查 + 回测摘要字段）  
- **默认 universe**：配置 allowlist；缺省用文件内默认池；**禁止**无落盘的模型临时宇宙  

Gate2 `reviewer=auto` = **对照该政策 CAS 通过**，不是「代码能跑就批」。

### 7.5 驱动部署
- 常驻：LaunchAgent / `local_mac_stack` 一类 **正常本机启动**  
- **禁止** 依赖 Codex/Claude 终端会话保活  

### 7.6 验收
- [x] 强制无正文/无搜索 → 不能 mark_succeeded
- [x] 真 PDF 路径 → 合同过 + candidate +（approve 后）final receipt
- [x] Slice 2 停在 receipt；无 promote / 无 live 资格写入

---

## 8. Slice 3 — 安全网 + 资格字段落地

### 8.1 限额
按 §4 首发档接线到 `create_sleeve` + `sleeve_risk` + execution_plan。

### 8.2 审计
- `029_factor_automation_events.sql`（append-only）= **日配额与 promote/demote 权威账本**  
- 事件绑定：candidate / policy / intake / gate / commit / sleeve  
- reviewlog 仅叙事  

### 8.3 Demote 状态机（修订命名）

```
running
  → paused                         # 风控/人工 pause
  → quarantined_hold               # 代码将卸或已卸；持仓仍在；禁止新单/恢复
  → flattened | transferred | manually_accepted
  → demoted_complete               # 仅当持仓终结或人工接受残留后
```

- 默认路径：stop sleeve → 卸 promoted 代码 → **`quarantined_hold`**（**不**称「demote 完成」）  
- `quarantined_hold` 期间：**继续估值、告警、计入暴露**；禁止新订单与 resume  
- 可选 `--flatten` → `flattened` → `demoted_complete`  
- `demoted.json` 防抖；信号路径 `factor_missing` → 自动进入 quarantine sweep  

### 8.4 验收
- [x] 超限 BLOCKED；日亏/回撤 pause
- [x] 正常 fill 不因 sleeve RiskLimits 的默认 kill switch 误杀
- [x] quarantine 持仓仍被监控
- [x] paper_only 因子无法被 live registry 加载（单测）

---

## 9. Slice 4 — paper 全自动过门

### 9.1 Flag
- Platform `QS_FACTOR_AUTOMATION_MODE` / `AUTO_LAND`（deny-only，镜像 local_trust）  
- HQA `HQA_FACTOR_AUTOMATION*`  
- 两端都开才全自动；**只写 `paper_only`**  

### 9.2 门
- Gate1：机器 digest + `auto:` note  
- Gate2：CAS + **policy digest 通过** + `reviewer=auto` + `registration=auto_promote`  
- Gate3：两阶段 prepare → `promote-auto-commit` → 现有 `_evaluate_reviewed_commit`  
- Land：本地 `ff-only` + HEAD CAS；**不** auto-push；`landed` 状态短路防 `review_invalidated`  

### 9.3 Driver
`hqa/factor_automation.py`：串行；LaunchAgent 触发；crash 可恢复。  
每五分钟先维护风险，再仅对 `automation_managed` sleeve 幂等生成 daily signal、
next-weekday plan 与到期 paper fill；手工 sleeve 不受影响。
浏览器 saga 自动完成 = **后置**，不挡 driver-only。

### 9.4 验收
- [x] flag OFF 全拒
- [x] 自动链测试到 paper_only land + sleeve 限额内
- [x] live registry 拒绝该因子
- [x] landed 不 flip invalidated
- [x] 常驻 paper 周期 signal → plan → fill 幂等，手工 sleeve 不触碰

---

## 10. Slice 5 — 文档

- [x] 现行规则改为「paper 自动 + live 人工 + paper_only 隔离」
- [x] 历史 audit **不改写**
- [x] skill 升到 1.19.0；install 重装进入最终 runtime 验收
- [x] D-33 决策写入 roadmap
- [x] 运维 runbook：flag、配额、quarantine、demote、policy、常驻 paper 周期

---

## 11. 两仓锁步（摘要）

路径 AIQP、reviewer/registration 值集、新 CLI、P1 contract、029、flag、provenance 键、**promotion_scope** —— 斜向 fail-closed。

---

## 12. 明确不做

- 不自动 live / 不 auto-push / 不把 paper_only 静默升 live  
- 不在 Slice 1 cherry-pick Gate3 reviewed 分支  
- 不把 RiskEngine 接到手动下单路径（本阶段）  
- 不在 paper 自动路径保留「每步人工确认」  
- 不把 029 搞成第二次立项审批（仅 Slice 3 执行勾选）  

---

## 13. 风险（节选）

| 风险 | 缓解 |
|---|---|
| 无 scope 隔离导致未来 live 误用自动因子 | §3 阻塞级；live builder 硬拒绝 |
| P1 过弱假成功 | §7.3 收据链 |
| Gate2 变「能跑就批」 | 版本化 policy digest |
| e400553 回归 | 扩大自动测试门 |
| landed→invalidated | 状态短路 + 单测 |
| 配额双真相 | DB 权威 |
| demote「完成」但仓还在 | quarantined_hold 语义 |
| 计划未入 Git / HQA clone 落后 | Slice1 前先 commit + ff clone |

---

## 14. 批准后的真实第一刀（修订）

1. 你确认本修订版 §15  
2. **Commit 本计划到 HQA main** + runtime HQA clone 对齐  
3. Slice 1 **可逆冻结**（bundle/tags/dirty 补丁）  
4. 再 dirty commit → cherry-pick worktree → …  

---

## 15. 请你确认（替换旧 8 项）

| # | 项 | 请回 |
|---|---|---|
| 1 | 目标：paper 全自动 + live 人工 + **paper_only 结构性隔离** | 是/否 |
| 2 | 首发限额：10k 或 1% NAV、合计 10%、1 promote/天、2%/10% 暂停 | 是/否 |
| 3 | e400553：release 赢基建 + **扩大自动测试门** | 是/否 |
| 4 | Slice 2 = P1+管道到 final backtest；**全自动过门只在 Slice 4**（不在 2 留长期人闸） | 是/否 |
| 5 | Slice 4 driver-only + LaunchAgent，不依附 AI 终端 | 是/否 |
| 6 | land 不 auto-push | 是/否 |
| 7 | demote 默认 **quarantined_hold**，完成态另算 | 是/否 |
| 8 | 先 commit 计划 → 可逆冻结；**不是**「未改计划就开干」 | 是/否 |

---

## 16. 直接回答你的担心

> 「硬性前置门会不会又搞成什么都干不了？」

- **会搞成形式主义的做法**：每步再要人批、Slice 2 永久双人闸、迁移反复「授权会议」、universe 每次手填。  
- **本修订明确砍掉这些。**  
- **留下的「硬」只有**：  
  1）自动因子 **永远进不了 live 注册表**（你不用点，系统直接装不进）；  
  2）没读到论文正文 **不能假装成功**（自动失败）；  
  3）机器评审政策和限额（配置，不是弹窗）；  
  4）拆仓语义诚实（hold ≠ 做完）。  

这与「个人量化 agent 主打全自动 paper」一致：  
**人从环路里出去；机器用可审计规则替人；live 另说。**

---

## 17. 实施记录（2026-08-10）

- Platform 已统一为单一受保护 `main`；两份运行 checkout 按同一主线管理，archive
  tags/bundle/dirty snapshot 可恢复。
- P1、机器 policy、paper/live registry 分裂、029 authority、两阶段 land、限额 sleeve、
  risk/demote、五分钟 LaunchAgent、真实 backtest 证据复核和 paper signal→plan→fill 均已落地。
- 029 在 backup + isolated restore 后只 apply 一次；禁止重放。双 Flag 在全量 suites、安装
  与冷启动验收通过前保持关闭；上述门已通过，owner runtime 四项 Flag 已显式启用。
- 一次真实研究链已到 candidate/final receipt，但实际 cost/drawdown/turnover 不满足政策，
  因而正确拒绝、没有 land。它是负向安全证据，不冒充成功自动因子。
- GitHub 不由自动链 push；浏览器 saga 仍是明确后置项，不阻塞 driver-only D-33。
- 最终验收：HQA/Platform 的 Python 3.11 全量 suites 通过；前端 77 文件/468 测试、
  type-check、lint、production build 通过；两仓各自的两个本地 checkout 均 ff 同步。
  冷启动后 Docker、Hermes、backend、frontend、connector ready，自动 driver 首轮
  `idle/queued=0`、launchd last exit 0；安全面仍为 dry-run + paper、live false、
  kill-switch true、release 未授权。

*实施以当前两仓 Git、测试输出、正式库 marker/trigger 和 runtime health 为证据；历史 audit 未改写。*
