# Agent v0.2 · Slice V3 Acceptance

> 日期：2026-07-19。结论：**V3 SOURCE ACCEPTED / LOCAL DARK INSTALL COMPLETE / PUBLIC
> WRITES STILL OFF**。本记录不授权 migration、Hermes Durable Run、Web mutation、worker
> claim/dispatch、provider、Gate、paper/live 或交易；也不把 V3 暗态地基表述成可用的完整 Web Chat。
>
> **后续行为替代说明（2026-07-31 change-set inventory）：** 本文保留 2026-07-19 的历史验收事实，
> 但 §6“第一个真实 encrypted intent 创建 Keychain key”不再是当前 source 合同。后续
> hardening source 要求非创建式 `probe`；`put`、`bind_resolve` 与普通 encrypt 均不得创建 key；只有
> 操作者在核对 exact runtime/preflight 后明确执行 `initialize-key` 才可创建。本说明不声称该
> source 的 exact commit、安装、live 加载、验收或授权状态。

## 1. Source identity

| 字段 | 值 |
|---|---|
| branch | `codex/full-9h` |
| V3 source commit | `121926388d864e02c0c1d380cd4e828158b3f380` |
| tree | `fc439ac75918beab910e73edae470dc860693060` |
| archive SHA-256 | `6133d11657522103d17f0e98d9a6fe4cba583e155a556c01952511f599d5f20a` |
| remote | `https://github.com/YIBOWAY/hermes-quant-agent.git` |
| publication check | 2026-07-19 fresh `ls-remote refs/heads/codex/full-9h` 与 V3 source commit 一致；后续 documentation-only descendant 可继续推进该 ref |

前置 V0/V2 formal close-out 在 `7d81611`，独立 verdict 为 `CLEAR` 且
`release_authorized=false`。V3 没有改变该 manifest 对 live Hermes 的 fail-closed 判定。

## 2. 已交付边界

- `IntentPayloadStore`：closed schema、owner/workspace/session scope、content-addressed encrypted
  blob、immutable 1–30 天 TTL、exact consumer binding、ciphertext delete、digest tombstone、下游
  acknowledgement、bounded reconcile、backup/restore/reverse audit。
- production crypto：macOS CryptoKit AES-256-GCM + ThisDeviceOnly Keychain key；plaintext/AAD 只走
  private inherited pipe FD，不进 argv/env/stdout/stderr/journal/projection/backup/error。
- `WorkflowAuthority`：Research Task `1:N` Attempt、typed public command union、expected-version CAS、
  stable event/hash chain、idempotent replay、terminal immutability、projection rebuild、backup/restore。
- intent/workflow seam：owner 预检、payload acceptance、scope/CAS、workflow apply、exact Attempt
  binding；commit-ack unknown 可重放，不创建第二套 Task/Attempt。
- expiry seam：七字段 tombstone evidence 是唯一公开的 workflow expiry 入口。直接
  `ExpireIntent` / `ObservePayloadTombstone` 已从 public contract/parser/export/apply 删除；旧 journal
  的 canonical kind/digest、replay 和 backup restore 保持兼容。
- Hermes surface：安装后的 skill/wrapper 只允许 `show|events|audit|rebuild`；不存在 raw `apply`、
  stdin command document、payload resolve、provider/platform/DB/trading 入口。
- retention：固定、无参数、本地 `--no-agent` 脚本；空 authority 时静默退出，不创建 authority 或
  Keychain key。

## 3. 对抗发现与修复

1. 修复 intent journal 已 fsync、disposable index 尚未发布时 exact retry 误报 corruption；现在先验证
   canonical journal，再重建 owner-only index，`intent_durability_unknown` 正确标为 retryable。
2. 修复 workflow-first binding 可能在 owner/scope 不匹配时留下 orphan Task/Attempt；协调器先做 owner/
   existing Task scope 检查，再写 workflow，并以相同 operation 做 exact recovery。
3. 修复同一 Task 多 Attempt 同轮过期的 version 冲突，以及 running/older/terminal Attempt 被错误改写
   terminal outcome；只有最新、未执行的 planned Attempt 可进入 `intent_expired`，其他只写 metadata
   observation。
4. 删除 Hermes raw workflow mutation 表面；wrapper 在进入 Python 前做 read-only allowlist。
5. 修复 `events --limit 0` 被误报成 retryable infrastructure failure；现在 rc `2`、
   `workflow_invalid_request`、不创建 authority。
6. installer 对所有祖先/目标做 physical owner/mode/link 检查，完整 staging/preflight 后逐文件
   fd-relative replace + fsync；输出只声明本 candidate 实际安装的文件，不把既有无关 skill/wrapper
   冒充本次安装。

## 4. Validation evidence

| Evidence | 结果 |
|---|---|
| V3 + config/install + release targeted | `218 passed`；JUnit `/tmp/hqa-v3-1219263-targeted.xml`；SHA-256 `cf4c0b461452f4aa02756f04951a44c3173ee53e90cf47aa18fa9cfad4758261` |
| HQA full（显式 `HQA_HERMES_INTEGRATION_WT=/nonexistent`） | `1726 passed, 15 skipped`；JUnit `/tmp/hqa-v3-final-full.xml`；SHA-256 `5884d64a53fed6eacd9117d00d340118b365f524c7192b0f92bd9d0218ade02e` |
| 静态检查 | Ruff、Python 3.9 `py_compile`、`bash -n`、`git diff --check` 全绿 |
| expiry authority fresh independent re-review | `83 passed`；P1/P2 均关闭；无 P0–P3 finding |
| V3 final independent adversarial review | `CLEAR`；reviewer focused `211 passed`；无 P0/P1/P2 finding |

15 个 full-suite skip 中，13 个是本轮明确禁用的 isolated real-Hermes suite，另外 2 个是既有
AIHOT live-network 与真实 `quant-system` 人工测试。V2 的 exact Hermes candidate acceptance 已由
V0/V2 bundle 单独绑定；没有用 Hermes upstream 约 40k 全仓测试作为 V3 gate。

## 5. Local dark install / scheduler evidence

`bash scripts/install.sh` 完成两次（第二次含 honest-output 修订），没有重启 Hermes。最终安装：

| Artifact | mode / SHA-256 |
|---|---|
| `~/.hermes/bin/hqa-intent-payload-crypto` | `0700`, owner UID `501`, nlink `1`; `7f626313a139d5dfe83231807b3ea53852960754d975f90da31153f1fd76f6dc` |
| `~/.hermes/scripts/hqa-intent-payload-reconcile.sh` | `0700`; `488a724e46f6c9874e10872e2f5763759d4cc777beb3ce3209c9b52cea3dad0f` |
| `~/.hermes/scripts/hqa-research-task.sh` | `0700`; `76c3edf36e4e756b5d134cfc1dd3508f261d51517f3a40fdb75362a985254e5a` |
| `~/.hermes/skills/hqa-research-task/SKILL.md` | `0600`; `bb1cd2030218f4ad692a1acb721ba6a081f9c49f82b293e17d95783f0edf2b09` |

安装后 smoke：

- helper 无参数：rc `64`，stdout/stderr `0` bytes；
- `hqa-research-task.sh apply`：rc `2` + redacted `workflow_invalid_request`；
- 空 retention：rc `0`、stdout/stderr `0` bytes；
- smoke 前后 intent/workflow authority root 都不存在；Keychain exact account 查询前后均 rc `44`
  （不存在），证明安装/空任务没有创建 key；
- Hermes PID 仍为 `96807`，start time 不变；`GET /health` 仍为 `ok / hermes-agent / 0.18.2`。

Hermes cron 创建唯一任务：

```text
id:       cb5702cc3909
name:     hqa-intent-payload-reconcile
schedule: 11 * * * *
script:   hqa-intent-payload-reconcile.sh
mode:     no-agent
deliver:  local
```

fresh list count 为 `1`，Gateway ticker 正常。该任务没有 prompt/agent/provider 调用；空 stdout 即静默。

## 6. Residual / next admission

- installer 明确只保证**逐文件原子**，不是整包事务；若在多个 replace 之间被强杀，可能出现可检测、
  可由同一 reviewed commit 重装修复的混合版本。当前已有完整 staging/preflight，但尚无注入式
  mid-publication kill test；这是非阻塞、已披露 residual。
- production Keychain key 会在第一个真实 encrypted intent 时创建；本轮刻意没有制造测试 key 或
  payload。device key 不随 backup 跨设备，缺 key 的 restore 必须 fail closed。
- V3 是暗态内部地基，不等于用户现在能在 `/hermes` 发消息。下一施工切片是 V4 的 PostgreSQL
  schema/BFF submission saga/security；先修订 never-live 006 与 migration runner、完成隔离 PostgreSQL
  和独立 review，再另行请求 live migration 授权。V2 live candidate install/canary 仍是独立授权轨道。
