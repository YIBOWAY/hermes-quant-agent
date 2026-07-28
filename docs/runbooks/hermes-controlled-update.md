# Hermes Desktop / 集成运行时受控更新

本机 Hermes 不是单一 checkout：

- Desktop 从 `~/.hermes/hermes-agent` 的 `main` 读取官方版本；
- Gateway / Agent v0.2 从
  `~/.hermes/hermes-agent/.claude/worktrees/v2-integration`
  的集成分支运行。

因此不得直接使用 Desktop 的通用更新按钮覆盖两个工作树。HQA 提供
`hqa-hermes-update.sh`，把二者作为同一个更新单元处理。它是**人工操作工具**，
不得加入 cron、no-agent watcher 或自动启动项。

## 日常操作

检查更新（会执行 `git fetch`，不会改工作树）：

```bash
~/.hermes/scripts/hqa-hermes-update.sh check
```

应用更新：

```bash
~/.hermes/scripts/hqa-hermes-update.sh apply
```

`apply` 的顺序固定为：

1. 验证 Desktop 根目录和运行集成工作树属于同一个 Git 仓库；
2. 获取单实例 operator lock，拒绝并发 update / rollback；
3. 拒绝任何已跟踪的未提交改动、错误分支或非 fast-forward 的 Desktop 根目录；
4. 创建私有 bundle 备份和隔离候选工作树；
5. 在候选中合并 `origin/main`、同步开发依赖，并运行 official API
   capability / durable run / managed session / approval / replay / stop
   的聚焦测试；
6. 只有候选通过，才快进运行集成分支与 Desktop `main`；
7. 按本机能力集保留 `all + messaging + edge-tts + voice` 运行依赖，
   重启 Gateway，并通过 loopback `/health` 验证；
8. 任一线上步骤失败时，自动恢复两个精确旧提交并再次启动旧版本。

更新不会修改 `chat_write_ready`、public cutover、kill switch、paper/live
trading 或任何研究 Gate。

## 冲突或测试失败

工具会输出一行 JSON：

- `status=conflict`：候选合并冲突；
- `status=validation_failed`：候选测试失败；
- `status=rolled_back_after_failure`：上线步骤失败，旧版本已自动恢复；
- `status=rollback_failed`：自动恢复或旧版本重启失败，需要立即人工处理。

前两种情况不会改 Desktop 和运行工作树。JSON 中的 `candidate_path` 保留了
隔离现场，`receipt_path` 与 `backup_bundle` 位于私有
`~/.hermes/hqa-update/receipts/`。

## 人工回滚一次已成功更新

只允许使用该工具生成的 `status=applied` receipt：

```bash
~/.hermes/scripts/hqa-hermes-update.sh rollback \
  --receipt /Users/sunyibo/.hermes/hqa-update/receipts/<id>/receipt.json
```

回滚前会再次检查：

- 两个工作树没有已跟踪改动；
- 当前提交仍等于 receipt 记录的更新后提交；
- receipt 属于当前本机拓扑。

如果更新后又有新提交，回滚会拒绝执行，避免覆盖后续工作。
