# Agent v0.2 · V0/V2 Release Closure Audit

> 审计日期：2026-07-19。本文是三仓 source candidate、Hermes live identity 与已有验证证据的
> source/runtime 收口记录。配套 formal manifest 已生成在
> `evidence/2026-07-19-v0-v2-release-manifest.json`，primary validation 的封闭绑定已生成在
> `evidence/2026-07-19-v0-v2-validation-binding.json`，独立复核结论保存在
> `evidence/2026-07-19-v0-v2-independent-verdict.json`；本文与这些 artifact 都**不是 live
> install/canary 授权，也不开放任何 write gate**。易变的 PID、start time、health 与 runtime file
> 只代表 manifest 采集时快照。

## 结论

- **V0：SOURCE + FORMAL EVIDENCE + INDEPENDENT CLOSE-OUT DONE。**
  Workspace contracts 与三仓 source coordinates 已形成；manifest 修订已提交到 HQA
  `4fdad9e7b31b`，并生成 digest
  `4effb1b2ee7d234a52ca6a6cf6de1153ea9dd46235c4c2bda860c7ff4f1596e6`；三仓 fresh exact
  JUnit 已由 `binding_digest=78a2bf95bc718f9b411a1ce8b67feef87eb01741ee72443af19b85d8c1df6184`
  绑定到同一 identity。独立 adversarial reviewer fresh 重算三仓 remote/head/tree/archive、两份
  closed-schema digest 与三份 JUnit hash/count 后给出 **CLEAR**；其 verdict 明确
  `release_authorized=false`。V0 的 source/formal freeze 至此 DONE，但这不升级任何 runtime/live gate。
- **V2：SOURCE ACCEPTED / LIVE NOT RELEASED。** DurableRunAuthority candidate 已在 Hermes
  integration `2eb5fa27790f` 独立验收并推送至用户 fork；live Hermes 运行的是 upstream
  `main@c0c76a471533`，不是 candidate。launchd/install stamp/process/module identity 没有形成一致
  chain，因此不能写成 installed、runtime-accepted 或 released。
- **V3 后续已完成 source acceptance 与 local dark install。** 其独立验收见
  `2026-07-19-agent-v0-2-v3-acceptance.md`；该后续结论不改变本文的 V0/V2 source/runtime
  判定，也不允许越过 live install 与后续 release gates。
- `chat_write_ready`、browser mutation、worker claim/dispatch、public composer、durable runs、provider、
  Gate、paper/live 与交易链路全部保持 **OFF**。

## Source candidate 坐标

旧文档里的 `frozen base` 在本记录统一改名为 `historical_fork_base`。它只说明历史祖先/分叉背景，
不参与 current source head、installed identity 或 write readiness 判定。

| Repo | Canonical remote / branch | Source head | `historical_fork_base` | 当前判定 |
|---|---|---|---|---|
| HQA | `https://github.com/YIBOWAY/hermes-quant-agent.git` / `codex/full-9h` | `4fdad9e7b31bd4088cf7eaaf7a087da167093c95` | `a7428b6219ded4550f4c8951b6fabc4542a1724f` | source 已推送；formal identity + validation binding + independent CLEAR 已闭合 |
| ai-quant-platform | `https://github.com/YIBOWAY/ai-quant-platform.git` / `codex/agent-v0-2-platform-v1` | `bb62f5d0bc6a5a9a62a2e735b4d559f7d111ba01` | `7b73b5f2fe9e80509f4762c3de696d1e2c58fc9d` | source 已推送 |
| Hermes integration | `https://github.com/YIBOWAY/hermes-agent.git` / `codex/v2-live-integration` | `2eb5fa27790fb7af73fababa21d43b3996fe2d99` | `a79b818360700d526c0a48107444810e3d6ecc2e` | source 已推送；不是 live runtime |

HQA 与 platform 主工作树都可能同时承载独立用户/并行工作。尤其 platform 当前 dirty 已超出旧审计
记录的固定文件集合；这些更改全部排除于本次 scope，未清理、未回滚。正式 manifest 必须在生成
瞬间精确声明 tracked/untracked snapshot，或在新建的 clean controlled worktree 中对上述 source
commit 采集，禁止沿用“仅 4 项”等过期计数。

## Hermes live identity（易变快照）

| Identity seam | 2026-07-19 观测 | 与 V2 candidate 的关系 |
|---|---|---|
| source candidate | `codex/v2-live-integration@2eb5fa27790f` | 已 ACCEPT/推送，未被 live 加载 |
| live checkout / process source | upstream `main@c0c76a47153398953c718ca729bc5192da1e63ac` | 不等于 candidate |
| running process | PID `96807`；start `2026-07-19 17:39:09 +08:00`；`python -m hermes_cli.main gateway run --replace` | 只证明 upstream main 进程在跑 |
| HTTP health | `127.0.0.1:8642` → `status=ok`, `platform=hermes-agent`, `version=0.18.2` | health 不证明 candidate installed 或 durable available |
| launchd definition | stale | 不能作为 current process/source attestation |
| install stamp | 仍记录 source `916f5fbf5452`、durable OFF | 与 checkout/process `c0c76a471533` 不一致 |
| durable module | live checkout 无 `gateway/durable_runs.py` | V2 authority 未安装 |

因此当前 formal verdict 必须 fail closed：`candidate_installed=false`、`write_ready=false`。manifest
内 canonical aggregate blockers 是 `candidate_not_installed:hermes` 与
`runtime_not_aligned:hermes`；runtime record 进一步保存 `installed_identity_mismatch` 与
`runtime_stamp_invalid`。stale launchd 与 module absence 是本文的独立上下文观察，不伪装成 manifest
schema 已编码的事实。即使 checkout 与 process 同为 `c0c76a471533`，也不能忽略 install stamp 或
candidate `2eb5fa27790f` 未加载。

Hermes 的运维模式是**由操作者自主决定频率的手工更新 + no-agent watcher**。watcher 只观察和报告 upstream、checkout、
process、health、stamp 与 compatibility drift；不得自动 pull/merge/install/restart，不得改 config，
不得打开 durable/write/provider/worker gate。任何 candidate install、restart 或 canary 仍需独立明确
授权和 rollback evidence。

## 已绑定 primary validation 与补充上下文

下表记录当前用于 source acceptance 的 evidence。独立 close-out 仍须核对命令、结果、source
commit/tree/archive digest 与 `manifest_digest`，不能只抄测试计数。

| Repo / evidence surface | 已有结果 | 此处能证明什么 |
|---|---|---|
| HQA V0/V2 exact final-head targeted | `4fdad9e7b31b`：8 files，`733 passed`；JUnit SHA-256 `e3d8833cfa9ab0899577bcd79fbb1cc72ed05e1217a8b1cdc730e6e03fc4c410` | committed formal HQA head 的 Workspace、manifest、adapter 与 acceptance surface |
| platform exact final-head full | `bb62f5d0bc6a`：`1573 passed, 99 skipped`；JUnit SHA-256 `2a439d03aecbc615fee99537db5656dbae2198d983cbeff905e70aff2c5978dd` | clean controlled source 的 platform 全仓 source acceptance；临时复用主工作树 `node_modules` 后已清理，checkout 恢复 clean |
| platform isolated PostgreSQL semantic fingerprint（补充上下文，未作为本 binding 的 primary） | `1 passed` | 语义指纹对抗路径；不改变 live role/RLS PARTIAL 事实 |
| Hermes exact focused authority surface | `2eb5fa27790f`：15 files，`389 passed`；JUnit SHA-256 `b88d77f73505d4ce65afcc570fd84c0aafdf77ade7ac400107ceb0e3c25ae46e` | DurableRunAuthority changed-test surface 与 Ruff 通过 |
| 较早 HQA full / Hermes conversation loop | HQA `1531 passed, 2 skipped`；Hermes `436 passed` | 仅作历史/相邻上下文；未绑定当前三仓 exact source，不冒充本 bundle 的 primary evidence |
| 较早 Hermes source reviewer | `ACCEPT`；focused Ruff / diff check green | V2 source review 上下文；不替代本次 bundle 的 independent close-out |

upstream Hermes 约 40k 的全仓 suite **不是 Agent v0.2 release gate**。不能把“未跑 40k”当 blocker，
也不能用 40k 结果替代本计划要求的 focused contracts、conversation-loop、manifest/runtime identity 与
independent close-out。

## Formal identity + validation binding

`hqa/release_manifest.py` 的 schema v1 与最后修订已提交到 HQA `4fdad9e7b31b`。formal artifact
由该 committed builder 生成并保存在：

```text
docs/audits/evidence/2026-07-19-v0-v2-release-manifest.json
```

identity manifest 只承担 source/runtime identity 与 fail-closed verdict，不向 schema 内继续塞入测试
记录。companion validation binding 以 closed schema 绑定 identity 文件 SHA-256、内嵌
`manifest_digest`、三仓 source coordinates、完整 argv/cwd/setup/cleanup、exit status、JUnit
counts/path/SHA-256 与自己的 canonical `binding_digest`。这样不需要递归修改 identity schema，也不会
把测试计数文本当成 provenance。

本审计记录 artifact 路径、文件 SHA-256、内嵌 digest、验证证据与 reviewer verdict；
不使用签名/签字措辞冒充密码学签名。schema 必须 closed/fail-closed，至少包含：

1. `schema_version=1`，canonical JSON SHA-256 `manifest_digest`，未知字段/篡改拒绝。
2. 三仓 `repo`、absolute checkout、credential-free canonical remote/name/ref、source branch/head/tree/
   archive SHA-256、remote published identity。
3. `historical_fork_base` 的语义由 `base_commit` + `base_present` + `base_is_ancestor` 表达；该字段组
   不得被解释为 current expected head。
4. 每仓实际与声明的 exact tracked/untracked dirty lists，并把 `dirty_matches` 与
   `working_tree_clean` 分开；声明 dirty 不会把 candidate 变成 clean 或 write-ready。
5. Hermes `installed_checkout`、reviewed command + command digest、version、installed/running commit 与
   archive digest、PID、timezone-aware start time、allowlisted environment/config 和 runtime stamp。
   secrets、bearer/provider keys 与未知 config key 必须拒绝。
6. derived facts：`candidate_source_committed`、`dirty_declarations_match`、
   `working_trees_clean`、`runtime_coverage`、`candidate_installed`、`runtime_aligned`、canonical
   `runtime_blockers`、`write_ready`。

companion validation binding 位于：

```text
docs/audits/evidence/2026-07-19-v0-v2-validation-binding.json
```

其文件 SHA-256 为
`7b04441675d70a017a929585f93d6852ce553e05eda538d390a83660d9e8597a`，内嵌
`binding_digest` 为
`78a2bf95bc718f9b411a1ce8b67feef87eb01741ee72443af19b85d8c1df6184`。parser 拒绝未知/重复字段、
篡改 digest、不完整三仓 source、source coordinate mismatch、失败/错误 JUnit、不一致计数与
secret-like argv。

独立 verdict 位于：

```text
docs/audits/evidence/2026-07-19-v0-v2-independent-verdict.json
```

其文件 SHA-256 为
`6067dd482d80a2287c088056d4372bd371f9efb1977865428d5129ae1f7b519c`。verdict parser 使用 closed
schema，拒绝未知/重复字段、不完整 checks 和任何 `release_authorized=true`；artifact 绑定上述
identity 文件 SHA/digest 与 validation 文件 SHA/digest，结论为 `CLEAR`，但明确不授权 live release。

当前 artifact 文件 SHA-256 为
`9fb919109050b39067b4302b8339c058c2c7e67491b8e3bc77867d0f5bb9f2b4`，其正确 live verdict 是
`write_ready=false`。只有在受控安装后 source / installed / process / stamp / module / config
全部一致，并由独立 reviewer 对新的同一 `manifest_digest` 给出 CLEAR verdict，才允许重新计算；即便
manifest 为真，也不能绕过 V8 用户 cutover 与各项独立授权。

## Close-out 结果与剩余 live 边界

1. 独立 reviewer 已 fresh-verify identity manifest、validation binding、remote publication、archive
   digests、runtime blockers、实际 JUnit hashes/counts 与 `write_ready=false`，并给出绑定同一
   `manifest_digest` + `binding_digest` 的 `CLEAR`。V0 source/formal close-out DONE。
2. artifact/closure docs 的提交是对 `4fdad9e` source snapshot 的证明，
   不递归声称 evidence commit 自身等于被证明的 source head。
3. V2 source closure 可记录为 ACCEPTED；V2 live release 必须等待另行授权的 backup → controlled
   install/restart → pre/post Discord/health/capability smoke → rollback verification。当前不要安装。
4. 所有写 gate 继续 OFF；V3 只有通过自身完整验收后才能声明完成。

## 未触发与文档边界

本 source/runtime 收口没有 install/restart、launchd 修改、migration apply、
provider call、paper/live/broker、Gate mutation、browser mutation、redirect 或交易调用；没有触碰
platform/HQA 的独立用户或并行代码更改。历史审计
`2026-07-17-v0-three-repo-cross-review.md` 保持原文，仅用于说明当日为什么 fail closed；本文件是
2026-07-19 当前状态入口。
