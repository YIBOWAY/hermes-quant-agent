# D-25 — 交互延迟三件套 + artifact-first（实现计划）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把 Discord↔Hermes↔平台的交互延迟从「多回合 agentic 任务 216-742s」压到可接受范围。
根因（2026-07-05 网关日志实测）：延迟 ≈ 回合数 ×（LLM 思考+工具执行+解析重试）+ 审批等人 + 会话恢复。
单回合问答仅 18s——问题不在模型速度，在回合数和阻塞等待。

**三件套**（对应 D-25 ①②③）：

| 件 | 消灭的浪费 | 实现物 |
|---|---|---|
| ① 异步 ack+推送 | 盯着屏幕等长任务 | `hqa-notify.sh`（`hermes send --to discord` 包装，未配置时 local 兜底）+ 技能卡中的「>30s 分诊约定」 |
| ② HQA 技能卡 | 探索式回合（15-25 次调用里大半是试命令/读输出/纠错） | `skills/hermes/hqa/SKILL.md`，install.sh 部署到 `~/.hermes/skills/hqa/` |
| ③ 只读预授权 | 「等人点按钮」死时间（07-05 实测一轮 46s） | `hqa-quant-readonly.sh` 只读闸门 wrapper + config.yaml `command_allowlist` 单条 glob |

**已核验的 Hermes 事实**（写计划前查过源码/配置，非假设）：

- 技能格式：`~/.hermes/skills/<name>/SKILL.md`，YAML frontmatter 需 `name/description/version/platforms`，可选 `metadata.hermes.tags`。
- `command_allowlist`（config.yaml 顶层键）：条目是**命令文本 + shell 风格通配符**（如 `podman *`）；含 `&&`/`|`/`;`/`$(` 的复合命令**不走**allowlist 捷径 → 技能卡必须教 Hermes 调用**单命令绝对路径 wrapper**，不用 `cd X && ...` 形式。
- `hermes send --to discord "msg"` 无需 LLM 即可投递；cron wrapper 已用此模式。
- wrapper 部署机制：`scripts/install.sh` 把 `scripts/hermes/hqa-*.sh` 复制（非 symlink）到 `~/.hermes/scripts/` 并替换 `__HQA_REPO_DIR__`/`__HQA_PLATFORM_DIR__` 占位符。

**安全边界**：只读预授权只放行**无副作用**命令；写操作（propose/approve/paper mutation/任何交易链路）永远保留人工审批。allowlist 唯一入口是 `hqa-quant-readonly.sh`，它在脚本内白名单校验子命令，防御「allowlist glob 意外放行写操作」。

---

### Task L1: `hqa-quant-readonly.sh` 只读闸门 wrapper

**Files:** `scripts/hermes/hqa-quant-readonly.sh`（新建）；`tests/test_install.py`（扩展）。

行为：

```bash
hqa-quant-readonly.sh doctor
hqa-quant-readonly.sh options chain --symbol NVDA ...
```

1. 第一个参数必须命中只读白名单（写死在脚本里）：`doctor`、`config get/show`、`data`（仅查询子命令）、`factor list/show`、`options chain|snapshot|expirations|screen`、`backtest list/show`、`experiment list/show`、`paper status/positions`（只读查询）、`agent list-candidates`。
2. 命中 → `cd $PLATFORM_DIR && exec quant-system "$@"`；未命中 → stderr 报 `REFUSED: not in read-only allowlist` 并退出 2。
3. 白名单逐条对照平台 CLI 核实「确无副作用」后才写入（实现时用 `--help` 核验，宁缺勿滥）。

- [ ] Step 1: 失败测试——白名单命令通过（dry 断言 argv 构造）；`paper run`/`agent review` 等写命令被拒；空参数被拒。
- [ ] Step 2: 实现脚本；install.sh 无需改（glob 已覆盖 hqa-*.sh）。
- [ ] Step 3: 测试绿；提交 `feat(D-25): read-only gate wrapper for pre-authorized platform queries`。

### Task L2: HQA 技能卡

**Files:** `skills/hermes/hqa/SKILL.md`（新建）；`scripts/install.sh`（扩展：部署 skills）；`tests/test_install.py`（扩展）。

SKILL.md 内容要件：

1. frontmatter（name: hqa-quant, description, version, platforms）。
2. **命令速查表**：每个高频操作一行精确命令模板（走 `~/.hermes/scripts/hqa-quant-readonly.sh`，绝对路径、无复合操作符）+ 预期输出格式 + `--json` 提示（1a-3 落地后）。覆盖：安全状态、期权链/快照、雷达摘要、信号看门狗产物读取、复盘草稿/确认、盘前 digest 手动跑。
3. **artifact-first 指引**：回答行情/信号/雷达类问题先读 `logs/*.jsonl` 与 `data/options_scans/<date>.jsonl` 现成产物（附路径），产物新鲜（当日）直接用，缺失才现场跑。
4. **>30s 分诊约定**：预计超 30s 的任务（回测、全量扫描、启动服务）→ 后台启动 + 立即回「已启动 run_id=…」+ 完成后 `hqa-notify.sh` 推送；禁止阻塞对话轮询。
5. **安全红线重申**：写操作必须人工审批，禁止绕过。

- [ ] Step 1: 失败测试——install.sh 部署后 `~/.hermes/skills/hqa-quant/SKILL.md` 存在且占位符已替换。
- [ ] Step 2: 写 SKILL.md（命令模板逐条实跑核验，无占位符）；扩展 install.sh。
- [ ] Step 3: 测试绿；提交 `feat(D-25): HQA skill card — command templates, artifact-first, 30s triage`。

### Task L3: `hqa-notify.sh` 异步完成推送

**Files:** `scripts/hermes/hqa-notify.sh`（新建）；`tests/test_install.py`（扩展）。

```bash
hqa-notify.sh "#回测结果" "backtest run-xxx done: sharpe=1.18 report=..."
```

1. 检测 `hermes send --to discord` 可用性（hermes 在 PATH 且 discord 平台已配置）；可用 → 推送；不可用 → 追加到 `logs/notify_fallback.jsonl` 并 stdout 打印（local 兜底，D-7 同款模式）。
2. 消息自动加 `[HQA]` 前缀 + 时间戳。

- [ ] Step 1: 失败测试——fallback 路径写 JSONL（hermes 不可用时）；消息格式含前缀+时间戳。
- [ ] Step 2: 实现；提交 `feat(D-25): async completion push wrapper with local fallback`。

### Task L4: 只读预授权接入 config.yaml

**人工核验步骤**（改的是用户活配置，谨慎）：

- [ ] Step 1: 备份 `~/.hermes/config.yaml`。
- [ ] Step 2: `command_allowlist` 追加一条：`/Users/sunyibo/.hermes/scripts/hqa-quant-readonly.sh *`（单 wrapper 单条目；不放行裸 quant-system）。
- [ ] Step 3: 验证：Discord 里问一个行情问题，确认不再弹审批按钮；再确认写命令（如 factor-repro approve）仍弹审批。

### Task L5: 验收

- [ ] Discord 单回合问答（读 artifact 或只读查询）无审批弹窗、无探索回合，端到端 < 60s。
- [ ] 长任务对话立即拿到 ack，完成通知经 `#频道` 推回。
- [ ] 写操作审批门原样保留（实测一次拒绝路径）。
- [ ] HQA 测试套件全绿。

---

**关联**：D-22 `--json`（1a-3）落地后回访技能卡，把输出格式段更新为 JSON 契约。Discord 代理断连（127.0.0.1:7897 DNS 失败、300s 重试）是独立环境问题，不在本计划内——修复选项：换代理节点 / 直连 / 调短重试间隔。
