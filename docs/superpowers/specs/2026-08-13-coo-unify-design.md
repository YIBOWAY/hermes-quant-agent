# COO 统一重构设计（D-34 主入口 + Hermes 真当 COO）

> **已被取代。** 2026-08-13 起只按
> [`../../plans/2026-08-13-personal-quant-assistant.md`](../../plans/2026-08-13-personal-quant-assistant.md)
> 施工。本文是隔离 worktree 的早期施工笔记，不再当产品线。

状态：隔离施工 spec。施工只发生在
`/Users/sunyibo/programs/.worktrees/coo-unify/` 的 `refactor/coo-unify`
分支，以及独立库 `quantplatform_coo`。不改 live soak、不改公开
`main`。分支可以 push；不自动合入 `main`。实盘 / kill_switch / paper_only
边界不变。研究回路可以闭环，但**默认不跑**——只有 owner 提出研究需求后才入队。

## 1. 金丝雀是什么（产品名）

金丝雀不是一个隐藏菜单，是 D-34 走完研究后自动开出的
**纸面试运行仓**：把刚通过双引擎对照的因子，用很小一笔模拟资金
（约账户 1%、上限 $10,000）挂进模拟账户，只观察、不升级实盘。

本机已经有两个：

- `canary-004…` / `canary-ca0…`
- 各约 $10,000 现金，P&L $0，状态 running
- 2026-08-13 有 pending 执行（QQQ 99% / DIA 99%），但账户因
  `kill_switch=true` 冻结，所以一直填不成

界面上它原先写的是英文 `Paper canaries`，又被整页 D-34 操作台压在
「早上好」上面，所以日常几乎看不见。隔离区统一中文：**纸面试运行仓**。

它不是第三个交易系统。它就是「新因子先用小钱在纸面上活几天」。

## 2. 隔离方式（已选定）

不用整盘复制项目文件夹。AGENTS.md 已经规定目的命名 worktree。

| 层 | 选择 | 原因 |
|---|---|---|
| 代码 | git worktree + 新分支 `refactor/coo-unify` | 保留历史，可回并，不污染 live LaunchAgent 用的部署镜像 |
| 数据库 | 同实例新建库 `quantplatform_coo` | 比「新建一张表」隔离；不拷贝 live 金丝雀/soak 行 |
| GitHub | push 同名分支 `refactor/coo-unify` | 不推 `main`，不自动公开 |

路径：

- `/Users/sunyibo/programs/.worktrees/coo-unify/ai-quant-platform`
- `/Users/sunyibo/programs/.worktrees/coo-unify/Hermes-quant-agent`

Live `:3001` / `:8765` / soak 继续跑部署镜像。隔离区前端若要看，另起端口。

## 3. 目标（对初心）

用户早上只做一件事：**打开 Hermes，知道安不安全、有没有要处理的、
跟它说话，它能诚实去跑研究或拒绝。**

因此：

1. Hermes 是唯一日常入口（对话 + 今日摘要）。
2. D-34 是唯一研究入口，但是按需的：owner 提出需求后才入队。D-33 退成旧 sleeve 维护。
3. 研究引擎必须真的在组合/迭代因子，而不是五选一罐头。
4. 纸面试运行仓是研究的唯一自动落点；live 永远不从这里升级。
5. 仪式（digest CAS、Gate、paper_only）留下；切片标记、双晨报、
   双研究机、文档收据风暴拿掉。

## 4. Hermes 怎么才算 COO

不是再做一个 Web Chat。是把「开口之前答案已在」做成一条回路：

```
今日摘要（ops digest）
  → 对话（已通的 managed Session）
  → 你提出一条研究命令（D-34 Mandate 只是信封）
  → 纸面试运行仓观察
  → 摘要里出现结果或诚实失败
```

这条回路不是默认自动跑。没有 owner 的研究需求，五分钟 worker 只
`lease_next` 已入队作业，并维护已有纸面试运行仓。

Hermes 不再靠 750 行 skill 手搓 CLI。它先读 `python -m hqa.ops_digest_cli`，
再调少数确定性命令。模型散文不能把 Run 标成成功。RD-Agent/Qlib 需要 LLM
时走 Hermes xAI OAuth 代理 `127.0.0.1:8645`，模型 `grok-4.6`。

今日页只留四块：安全、要你处理的（含试运行仓异常）、对话、最近结论。
D-34 操作台默认折叠。因子实验室 / 回测 / 实验 / Agent Studio 继续藏。

## 5. 让 RD-Agent 名副其实（仍 paper-only）

不装 Jupyter / AzureML / Streamlit。也不假装跑完整微软实验室。

保留已经做对的部分：Qlib 算分、Platform 独立重放、对照收据、
`paper_only`。

加深的是 **提议层**：

- 旧：LLM 从 5 个算子里挑一个 + 两个窗口。
- 新：LLM 必须给出可证伪 thesis，并给出一条 **白名单 Qlib 表达式**
  （`$close/$open/$high/$low/$volume` + `Ref/Mean/Std/Rank/Delta/Abs/Log`
  + 四则运算，深度和窗口有上限）。
- 静态解析失败 = 这次实验失败，不许静默掉回罐头。
- 下一轮必须引用上一轮收据（已经有 history，强制写进 thesis）。
- 五个罐头算子只留作解析失败时的 *显式* 降级标记 `degraded_catalog`，
  不得再当默认成功路径。

这仍然不是完整 RD-Agent FactorCoSTEER。它是「假设 → 实现表达式 →
回测 → 对照 → 迭代」这条 RD-Agent 主循环在本机可执行的最小真子集。

## 6. 明确不做

- 不碰 live 交易、kill_switch 默认、公开 composer、自动 push
- 不把 soak 中的 live 金丝雀迁进 `quantplatform_coo`
- 不在这个分支重写整个前端视觉系统
- 不新开 Claude Code / Codex 会话

## 7. 施工顺序

1. 表达式白名单 + 单测（已做）
2. `hqa ops digest` 只读摘要（已做）
3. 今日页：试运行仓中文、摘要优先；提出研究才入队（本切片）
4. RD-Agent/Qlib LLM 默认 Hermes `grok-4.6`（本切片）
5. 隔离库套 schema，D-34 在隔离环境默认入口（未切 live）
6. Hermes skill 收成「先 digest，再一条命令」
