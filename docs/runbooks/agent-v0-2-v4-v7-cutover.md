# Agent v0.2 V4–V7 本机 cutover runbook

状态：**设计/演练入口；尚未获得 live apply/install/restart 授权。**

这份 runbook 只用于把已验收源码部署到单用户本机暗态。它不开放 public V8，不修改
paper account，不下单，也不允许把 `quant` superuser 继续作为 application runtime。

## 0. 必须分开的两次授权

1. **Platform live authority cutover**：备份 live PostgreSQL，apply 009/010，创建受限 LOGIN，
   切换 backend DSN 并重启验证。
2. **Hermes/HQA durable runtime cutover**：固定三仓 identity，安装 reviewed candidate，重启
   Hermes/HQA/worker，做低成本 canary 与恢复演练。

不得用一次含糊的“继续”同时覆盖两项；任何一步失败都回到 composer OFF。

## 1. 冻结身份与写入

- 记录 HQA、platform、`~/.hermes/hermes-agent` 的 branch/HEAD/dirty、安装 stamp、进程 PID 与
  `/api/health`。
- 停止 platform backend、supervised worker 和可能写 ledger 的旧进程；前端可保持只读。
- 确认 `paper_trading` / `live_trading_enabled=false` / `kill_switch` 未变化。
- 对 live DB 做可恢复备份，并保存 apply 前 schema fingerprint。

## 2. Mandatory read-only preflight

```sql
SELECT state, count(*)
FROM quant_system.hermes_commands
GROUP BY state
ORDER BY state;

SELECT count(*) AS legacy_outcome_unknown
FROM quant_system.hermes_commands
WHERE state = 'outcome_unknown';
```

`legacy_outcome_unknown` 必须为 0；否则停止，不 replay、不换 key 重发，逐条调查 exact Hermes
Run。queued 的 legacy `managed_session_create|managed_session_fork` 只能由 reviewed migration 010
按精确条件审计式取消。

## 3. Platform authority cutover

先 dry-run，再在明确授权窗口一次 allowlist 两个 reviewed 文件：

```bash
quant-system migrate \
  --allow 009_agent_v0_2_v4r_security.sql \
  --allow 010_hermes_session_action_idempotency.sql

quant-system migrate --apply --yes \
  --allow 009_agent_v0_2_v4r_security.sql \
  --allow 010_hermes_session_action_idempotency.sql
```

初次 apply 需要现有数据库管理员，因为 009 创建/修复 cluster roles。随后由 operator secret
store 生成密码并创建专用 LOGIN：

```sql
CREATE ROLE quant_app_runtime
    LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS
    PASSWORD '<operator-secret>';
GRANT quant_runtime TO quant_app_runtime;
```

禁止授予 `quant_migrator`，禁止复用 `quant`，禁止把密码写进仓库/日志。只把 backend runtime
DSN 切到该 LOGIN，重启后验证：

```sql
SELECT session_user, current_user, rolsuper, rolbypassrls,
       pg_has_role(session_user, 'quant_runtime', 'MEMBER') AS runtime_member,
       pg_has_role(session_user, 'quant_migrator', 'MEMBER') AS migrator_member
FROM pg_roles
WHERE rolname = session_user;
```

必须满足 `session_user=current_user=quant_app_runtime`、全部特权 false、runtime member true、
migrator member false。`/api/health` 此时可以显示 runtime authority ready，但在 durable worker
operational proof 前，local/public chat readiness 仍必须 false。

## 4. Owner Web bootstrap

浏览器不能向 API 索取 secret。operator 在 backend terminal 显式运行：

```bash
quant-system owner-bootstrap-token
```

把 stdout 中的一次性 token 手工粘贴到 `/hermes` 的 owner-session 提示框。token 文件必须 0600，
成功 exchange 后即消费；怀疑泄露时用 `--rotate`。验证旧 token 不能复用、非 loopback/origin/
CSRF 请求被拒绝。

## 5. Hermes/HQA durable runtime cutover

- 只从 pinned reviewed worktree 构建/安装；不要在未知 live checkout 上就地 patch。
- 运行 HQA install wrapper 后，核对 source/install/runtime 三者 commit 一致。
- Hermes `/v1/runs` 必须实际加载 durable authority；platform production adapter 必须指向 HQA
  subprocess port 和官方 loopback Run API，不能注入 fake。
- 启动一个 supervised worker，验证 capability/heartbeat/lease；CLI 默认仍保持
  `reconcile_only`，常驻模式必须显式配置。
- 先做 no-provider health/read smoke，再单独确认一次低成本 provider canary。

## 6. Canary 与恢复矩阵

仅在 trading kill switch 保持开启时执行一个新 managed session 的普通只读 turn：

1. create action 同 ID/same digest 重试返回同一 session；same ID/different digest 返回 409；
2. turn ACK 正常时只产生一个 Hermes Run；
3. 模拟 accept 后 ACK 丢失，lookup/replay 找回原 Run，不能产生第二个 Run；
4. 刷新浏览器、断开 SSE、重启 BFF/worker/Hermes 后恢复 exact session/run/cursor；
5. terminal receipt crash window 可重建，provider 调用计数仍为 1；
6. 多于 reconcile limit 的 active Runs 经过多轮都被观察，无饥饿；
7. 日志、argv、PostgreSQL、浏览器 storage 不出现 prompt、bearer、provider secret；
8. 订单、paper account、broker unlock、交易 API 调用计数全部为 0。

## 7. 开关与回滚

- 只有上述 evidence 全绿后，才可打开**本机单用户 dark composer**；`public_chat_write_ready`
  与 public V8 继续 false。
- 若 runtime role/readiness、worker heartbeat、Hermes identity 或 Run recovery 任一失败，立即关
  local mutation/composer，停止 supervised worker；保留 ledger/registry/audit 供恢复。
- 不删除 authority 行、不盲重发 `outcome_unknown`、不把 failed/unknown 改写成 completed。
- schema rollback 与数据恢复必须使用 apply 前备份和独立审核的 rollback；禁止手工删除
  009/010 创建的角色、policy、event 或 retired control rows来“恢复”。

