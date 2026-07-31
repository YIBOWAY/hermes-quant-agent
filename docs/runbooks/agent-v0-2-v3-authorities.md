# Agent v0.2 V3 本地权威运维手册

> 适用范围：V3 `IntentPayloadStore` 与 `WorkflowAuthority` 的本地、暗态运维。
> 本手册不授权 Web Chat 写入、Hermes Run、worker claim/dispatch、provider、Gate、
> migration、paper/live 或任何交易动作。`chat_write_ready` 与 public composer 继续 OFF。
> `probe` / `initialize-key` 与 recovery environment 合同属于 2026-07-31 hardening
> change set；不能由本手册推导其 exact commit、安装、验收、live runtime 或授权状态。

## 1. 权威与路径

| 权威 | 默认路径 | 保存什么 | 明确不保存什么 |
|---|---|---|---|
| Intent payload | `data/_runtime/intent-payloads-v2` | 加密 blob、payload ref/digest、owner/workspace/session、TTL、consumer binding、tombstone | journal/index 中不保存 prompt 或 provider policy 正文 |
| Research workflow | `data/_runtime/workflow-authority-v2` | Task/Attempt、plan digest/source ref、Run/evidence/Gate/result/stop refs、事件链与 projection | 不保存 prompt、plan/result 正文，不调用 Hermes/platform/数据库 |
| 设备密钥 | macOS Keychain | 仅 256-bit device-local master key | key 不进仓库、文件、argv、env、stdout/stderr |
| Crypto helper | `~/.hermes/bin/hqa-intent-payload-crypto` | 固定 CryptoKit/Keychain 适配器 | 不保存 payload，不输出明文 |

路径可用 `HQA_INTENT_PAYLOAD_DIR`、`HQA_WORKFLOW_AUTHORITY_DIR`、
`HQA_INTENT_PAYLOAD_CRYPTO_HELPER` 覆盖。CLI 的单用户 owner 默认为
`local-owner-v1`，可用 `HQA_WORKFLOW_OWNER_USER_ID` 固定；已经产生 authority 后不得无计划
更换 owner。

## 2. 安装、Keychain 预检与初始化

```bash
HQA_RELEASE_ROOT=/absolute/path/to/clean-reviewed-HQA-release
cd "$HQA_RELEASE_ROOT"
git status --short
git rev-parse HEAD
test "${HQA_SKIP_NATIVE_BUILD:-0}" = "0"
env -u HQA_SKIP_NATIVE_BUILD bash "$HQA_RELEASE_ROOT/scripts/install.sh"
```

只从已审查、已提交并与目标 runtime identity 精确绑定的 checkout 执行安装；不要把 dirty
worktree 直接当作可安装 candidate。`git status --short` 必须为空，并且记录的 HEAD 必须与
三仓 preflight 中的 HQA identity 完全一致。不要因为主 checkout 路径看起来更“正式”就从它
安装；如果它不是被审查的 exact release identity，旧 helper 会覆盖本次修复。release 安装
必须走正常 native build；`HQA_SKIP_NATIVE_BUILD=1` 仅是测试/受控复用 seam，不能作为本机
release helper 的来源。安装过程会：

1. 把物理 wrapper 复制到 `~/.hermes/scripts/`；
2. 安装 `hqa-research-task` skill；
3. 用当前 macOS SDK 编译 CryptoKit helper，并将 helper 与其目录设为 owner-only `0700`。

验证 helper 不接受普通 stdin/stdout 协议：

```bash
~/.hermes/bin/hqa-intent-payload-crypto
```

预期 exit `64`，stdout/stderr 均为空。默认仓库测试使用 deterministic fake，并编译、验证
真实 helper 的私有 FD 协议与非创建路径；需要实际创建随机 Keychain 项的集成段默认跳过，
只有操作者显式设置 `HQA_TEST_ALLOW_REAL_KEYCHAIN_MUTATION=1` 才可运行，且精确删除失败必须
使测试失败。普通全量测试不得把 Keychain 写入当作隐式副作用。

Keychain 预检必须使用非创建式 `probe`。它只接受空 JSON object；成功时只返回
`{"ok":true,"status":"ready"}`：

```bash
printf '{}\n' | ./.venv/bin/python -m hqa.intent_payload_cli probe
```

`probe` 不创建 key。`put`、`bind_resolve` 和普通 encrypt 也不得隐式创建 key；key
不存在或不可用时必须 fail closed。只有在操作者已经核对 exact committed source、安装/runtime
identity 与 release preflight，并为本次初始化单独作出明确决定后，才可执行：

```bash
printf '{}\n' | ./.venv/bin/python -m hqa.intent_payload_cli initialize-key
```

`initialize-key` 同样只接受空 JSON object，成功 receipt 与 `probe` 相同；它是唯一允许创建
device-local key 的入口。不得用 `/usr/bin/security add-*` 或其他手工方式写测试 key，也不得把
`initialize-key` 暴露给 BFF、Hermes skill、worker 或自动重试路径。Platform subprocess port
只可按其受控流程调用 `put|bind_resolve|probe`。

## 3. Research Task CLI（只读）

读操作：

```bash
~/.hermes/scripts/hqa-research-task.sh show --task-ref <task-ref>
~/.hermes/scripts/hqa-research-task.sh events --task-ref <task-ref> --limit 100
~/.hermes/scripts/hqa-research-task.sh audit
```

Hermes wrapper/skill **不暴露 `apply`、stdin command document 或任何 workflow mutation**。wrapper
在进入 Python 之前只放行 `show|events|audit|rebuild`；其他子命令稳定返回
`workflow_invalid_request`，且不得创建 authority root。typed workflow 写入只允许未来受信任的 HQA
进程内协调器调用；V3 暗态没有 Web、Hermes 或 cron 写入口。

内部调用以 exact `operation_id` + canonical command digest 实现精确重放；相同 ID 不同 digest
冲突。发生 outcome unknown 时，受信任调用方必须先按 exact Task/event 查证，再重放同一 typed
command，禁止另造 operation 掩盖未知结果。

普通 conversation 只通过受信任的进程内 `IntentWorkflowCoordinator.accept_conversation()` 建立
加密 payload，不创建 Task/Attempt。`resolve()` 只允许未来受信任的进程内 consumer 调用；没有
CLI、skill 或 cron 暴露该方法，也不得打印其返回值。

## 4. TTL retention

手工运行：

```bash
~/.hermes/scripts/hqa-intent-payload-reconcile.sh
```

固定任务每次最多处理 100 个到期 payload。没有到期项时 stdout 为空；有处理时只输出计数，
不会输出 prompt、调用模型或发起 HTTP。期望 Hermes cron 合同为：

```text
name:     hqa-intent-payload-reconcile
schedule: 11 * * * *
mode:     no-agent
deliver:  local
```

到期后正文密文被删除，journal 留 exact payload tombstone。旧 backup restore 必须保留原
`expires_at`；恢复时已经到期的 blob 不解密、不复活。

## 5. Backup / restore drill

必须先暂停未来 V4 的 submission/dispatch；当前 V3 暗态没有这些 writer。backup 目的地应在
owner-only、非 symlink 的新目录中，且不能位于 authority root 内。release/closure recovery
使用一个新建的 owner-controlled `0700` evidence root；backup、restore、verification temp 与
`uv-cache` 都放在该 root 或 recovery package 的 sibling 路径下，不使用共享 `/tmp`。
生成的 evidence 文件必须保持 owner-only。

```python
from pathlib import Path

from hqa import config
from hqa.intent_payload_crypto import MacOSKeychainCrypto
from hqa.intent_payloads import IntentPayloadStore
from hqa.workflow_authority import WorkflowAuthority

payloads = IntentPayloadStore(
    config.INTENT_PAYLOAD_DIR,
    crypto=MacOSKeychainCrypto(config.INTENT_PAYLOAD_CRYPTO_HELPER),
)
workflow = WorkflowAuthority(
    config.WORKFLOW_AUTHORITY_DIR,
    config.WORKFLOW_OWNER_USER_ID,
)
payloads.backup(Path("/absolute/owner-only/backup/intent"))
workflow.backup(Path("/absolute/owner-only/backup/workflow.json"))
```

restore 只允许指向不存在的全新 authority root；不得覆盖或 merge 现存 authority。先在隔离路径
恢复，再执行两边 audit，对比 payload digest、Task snapshot 与 event cursor。Intent backup 依赖
本机 Keychain key；换设备后没有同一 device-local key 时必须 fail closed，不能生成替代 key 冒充
旧密文。

闭合恢复可将 `HOME` 与 `TMPDIR` 指向上述 owner-controlled root；private `HOME` 不拥有 Python
解释器权威。Python 必须是 exact uv-managed Python 3.11：工具从当前 managed interpreter
推导 `.local/share/uv/python`，或接受同一精确目录的绝对
`HQA_UV_MANAGED_PYTHON_ROOT`。不得从 `HOME` 推导 uv root，也不得把一个宽泛父目录冒充 managed
root。recovery 的独立 verification temp 和 `uv-cache` 均必须保持 `0700`，并与 authority root
隔离。

恢复中断时保留原 backup，不手工拼 journal。Intent restore 使用 sibling staging + atomic rename；
workflow restore 只能对空目标或 exact identical authority 幂等恢复。任一侧失败时保持 Web/worker
写 gate OFF，按 audit 结果重新从干净目标执行。

## 6. Audit / rebuild

Workflow：

```bash
~/.hermes/scripts/hqa-research-task.sh audit
~/.hermes/scripts/hqa-research-task.sh rebuild
```

Intent 使用进程内 `reverse_audit()` / `rebuild_index()`。rebuild 只从 append-only journal 重建
disposable projection/index；不得修改 canonical events、重新生成 payload digest、补造 Run/Gate/
result/provider evidence。发现损坏、symlink/hardlink、hash-chain gap、跨 Task exact ref 重绑或 quota
越界时必须 fail closed。

## 7. 更新 Hermes 后的兼容检查

Hermes 由操作者定期手工更新。更新后可立即运行：

```bash
~/.hermes/scripts/hqa-hermes-compatibility-watch.sh
```

同一检查也由 Hermes `--no-agent` cron 每 15 分钟轮询 profile/source/shared-manifest/contract
trigger。当前 wrapper 使用 `local_agent_v0_2`：只执行一个本地 service-status、五个
loopback GET（额外读取 `/v1/capabilities`）及 Platform 版本化 manifest 校验；不会
pull、merge、install、restart、调用模型、provider、交易路径或打开 gate。
若 Hermes 本身无法启动，其 cron 也不能运行，因此手工执行仍是更新后的最终保险。

## 8. 回滚边界

- Helper/wrapper/skill 可以由 `scripts/install.sh` 从已审查 commit 重建；不要从未知 live checkout
  反向复制进仓库。
- authority 数据不可通过 `git checkout`、文本编辑或删除 projection 来“修好”；先 backup，再 audit。
- V3 authority 本身不读取或写入 PostgreSQL；本手册不授予任何 migration apply、install、
  service restart、candidate admission、release stamp 或 public cutover。
- source 存在、测试通过、安装完成、live runtime 加载和操作者授权是不同状态。每次操作前都必须按
  `docs/README.md`、active plan、PostgreSQL/runtime identity 与当次授权重新确认，不能沿用本手册
  或历史 audit 中的 dated live 结论。
