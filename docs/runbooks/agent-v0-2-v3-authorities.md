# Agent v0.2 V3 本地权威运维手册

> 适用范围：V3 `IntentPayloadStore` 与 `WorkflowAuthority` 的本地、暗态运维。
> 本手册不授权 Web Chat 写入、Hermes Run、worker claim/dispatch、provider、Gate、
> migration、paper/live 或任何交易动作。`chat_write_ready` 与 public composer 继续 OFF。

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

## 2. 安装与验证

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent
bash scripts/install.sh
```

安装过程会：

1. 把物理 wrapper 复制到 `~/.hermes/scripts/`；
2. 安装 `hqa-research-task` skill；
3. 用当前 macOS SDK 编译 CryptoKit helper，并将 helper 与其目录设为 owner-only `0700`。

验证 helper 不接受普通 stdin/stdout 协议：

```bash
~/.hermes/bin/hqa-intent-payload-crypto
```

预期 exit `64`，stdout/stderr 均为空。不要手工向 Keychain 写测试 key；仓库测试使用
deterministic fake，只编译和验证真实 helper 的私有 FD 协议错误路径。

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
owner-only、非 symlink 的新目录中，且不能位于 authority root 内。

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
- migration 006 仍不得 live apply；V3 不读取或写入 PostgreSQL。
- 当前 live Hermes 未安装 V2 candidate；durable runs、Web mutation、claim/dispatch 和 public
  composer 必须保持 OFF。
