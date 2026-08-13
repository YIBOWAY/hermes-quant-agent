# AGENTS.md

Rules for AI agents working in this repository.

## Project Role

- 这是本机**个人量化助手**的编排层。领域后端是
  `/Users/sunyibo/programs/ai-quant-platform`。
- **唯一现行计划：** `docs/plans/2026-08-13-personal-quant-assistant.md`。
  先读 `docs/README.md`。`D-31`/`D-32`/`D-33`/`D-34` 不是产品线，不是 NEXT。
- 助手只做五件事：盯盘、复现、回测、**已挂上**的策略每天跑、看效果。
  值班、已挂策略、评价必须自动。论文/说明可跑到双引擎，默认停在**已验证候选**；
  「挂上」或明文「过了就挂」才进每天跑。持续方向最多 1 个作业且停在候选。
  视频只抽规则、多数停问，不是研究账完成条件。没有授权禁止发明周期。
  聊天是遥控，实验室/回测/模拟盘仍是一等页面。
- 正常启动：部署镜像里的 `bash scripts/local_mac_stack.sh start`。
  服务寿命不绑 AI 终端。Hermes 更新只用
  `~/.hermes/scripts/hqa-hermes-update.sh check|apply`。
- 只许在主 checkout 或 `/Users/sunyibo/programs/.worktrees/` 下有名字的
  worktree 里改代码。`data/_runtime/agent-v02-work/` 是部署镜像：只许
  fetch/ff，不许 edit/commit/rebase/push。
- 收口施工默认在 `.worktrees/coo-unify/` 的 `refactor/coo-unify` 与空库
  `quantplatform_coo`。没有单独授权不要切 live soak / `:3001`。
- 主人对可逆的本地开发、配置、测试、测试数据和本地提交有持续授权。
  实盘、自动推 `main`、不可恢复删除仍要另外开口。
- quark P2/P3、公开 Web Chat、平台 Phase 15 都不是现行主线。

## Safety Rules

- `live_trading_enabled=false`。因子、试运行仓、研究收据都没有 live 升级操作。
- 常驻模拟只跑**已挂上**的因子。已验证候选和模型散文不能进每天跑。
- 没有授权禁止发明研究作业，只维护已挂策略。没有「每周槽」。
  双引擎通过 ≠ 挂上。持续方向不是全权委托。
- 模型说搜了网 / 回测过 / 成交了，必须有无正文收据；没有就失败，不许把 Run 标成功。
- 不要重放已经 apply 过的正式库 migration（028–033 等）。新动作前先核 live 元数据。
- 不要绕过 `paper_trading`、`live_trading_enabled=false`。
  `kill_switch` 冻实盘/真危险。已挂上的试运行仓走 `QS_PAPER_OBSERVATION_ENABLED`
  （默认开）；`emergency_stop` 或 `live_trading_enabled=true` 仍冻纸面成交。
  隔离预览：平台 worktree 里 `bash scripts/coo_unify_preview.sh start|stop`，
  端口 `:8876` / `:3002`，库只许 `quantplatform_coo`。
  预览种子成交证明的是冻结账户能记账，不是每日观察；种子市值差不许写进摘要。
- 手工 Scene-B 和任何 **live** 资格仍走三道人闸（公式确认、源码 CAS、diff/commit）。
  纸面每天跑不走这三道闸。Gate 细节在现行计划 §6；旧 Scene-B 包装器仍是手工入口。
- 规范候选在平台仓 `data/agent_run/agent/candidates`（只可用 `QS_AGENT_OUTPUT_DIR` 改）。
  `legacy_unbound` 永不授权。
- 机会结论不能升级成交资格。只许用精确的平台 signal/execution ID 连动作。
- 平台投影不得伪造缺失的 Hermes Run/event/provider/approval/stop 事实。
- 公开 `chat_write_ready` / composer 保持关。本地暗门不是公开 cutover。
- 假 Hermes adapter 只许用在密封测试。
- `IntentPayloadStore` 拥有加密正文；平台禁止 `import hqa`。payload CLI 是
  `python -m hqa.intent_payload_cli`。retention cron 必须 `--no-agent`，
  禁止 provider/HTTP/数据库/交易调用。

## Local Commands

- HQA tests: `./.venv/bin/python -m pytest`（必须用 venv 的 `python` 入口）
- Install Hermes wrappers: `bash scripts/install.sh`
- Persistent Mac stack:
  `bash /Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/scripts/local_mac_stack.sh start`
- Controlled Hermes update: `~/.hermes/scripts/hqa-hermes-update.sh check` then explicit `apply`
- Platform CLI: `/Users/sunyibo/programs/ai-quant-platform/ai-quant/bin/quant-system`

## Collaboration

- 先读现行计划，再动代码。不要从旧计划未勾选的方框推断进度。
- 核对 `docs/README.md`、现行计划、git、测试和正在跑的进程。
- 保留工作区里别人的改动，不要回滚无关文件。
- 没有 `.codegraph/` 就跳过 CodeGraph；平台仓有。
- 每做完现行计划的一步，用 neat-freak 只改现行文档，不要往历史 D-xx 计划里追加「现已上线」。
