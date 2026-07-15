# Hermes API Server 0.18.2 只读能力合同

> **当前合同（2026-07-15）：READ-ONLY / FAIL-CLOSED。** 这是 D-31 当前采用的
> Hermes 接入面。它只授权平台服务端 GET-only BFF 读取本机 Hermes 已持久化会话并由
> Next 页面展示；不授权
> chat/run 写入、SSE 消费、Hermes approval、stop/interrupt 或任何交易链路。

本文冻结本机 Hermes 0.18.2 official API Server 的已观察能力，不承诺较新提交或其他
安装拥有相同语义。旧 `tui_gateway/server.py` WebSocket JSON-RPC 合同只保留为历史审计，
见 [`hermes-gateway-0.18.2.md`](hermes-gateway-0.18.2.md)。

## 冻结身份

| 字段 | 值 |
|---|---|
| Hermes checkout | `9baa7d4673ce89f09378daa3660530f8bf142708` |
| official API source | `gateway/platforms/api_server.py` |
| source SHA-256 | `31f1c9c5750d8d3636e0e3a94e41cd1e349eb5b36cb7f4989944c7431f8270c7` |
| transport | loopback HTTP + server-side Bearer key |
| 本机 endpoint | `http://127.0.0.1:8642` |
| 页面入口 | `ai-quant-platform` `/hermes/sessions`；平台 API/BFF 访问 `/api/hermes/*`，浏览器不得直接访问 8642 |

checkout 或 source digest 任一变化，都只能触发重新审计；不得自动继承本合同的写权限。

## Wave 3 transport 边界

Wave 3 connector 将来即使通过写端 Gate，也只允许连接本文冻结的 official API Server
loopback HTTP origin（当前为 `127.0.0.1:8642`）。旧 `127.0.0.1:9119` TUI WebSocket 和运行时
动态 Dashboard WebSocket 仅是历史/诊断界面：它们不是稳定 connector 协议、不能作为服务发现
地址，也不能证明 chat/run/provider 已准入。

PostgreSQL command/event/outbox/lease/run-link ledger 是平台 transport command 的唯一权威；
HQA deterministic connector 只消费该 ledger。当前 reconcile-only worker 不调用本文的
chat/run/approval/stop endpoint，不读取 prompt，也不会触发 provider。

## 当前准入矩阵

| 能力 | upstream 路径 | D-31 准入 | 说明 |
|---|---|---:|---|
| 健康检查 | `GET /health` | `true` | 只验证进程可用性，不触发模型 |
| 能力说明 | `GET /v1/capabilities` | `true` | 只作诊断；上游宣称存在的写能力不等于 D-31 已授权 |
| 会话列表 | `GET /api/sessions` | `true` | 已持久化会话的只读分页列表 |
| 会话详情 | `GET /api/sessions/{session_id}` | `true` | 单一安全 session ID 的只读详情 |
| 会话消息 | `GET /api/sessions/{session_id}/messages` | `true` | 只向平台投影有限的 user/assistant 文本 |
| chat / run submit | `POST /v1/runs` 等 | `false` | 缺少 D-31 所需持久幂等、恢复和证据合同 |
| SSE stream / resume | run events surface | `false` | 缺少 durable event ID、cursor 与 replay 语义 |
| Hermes approval mutation | approval surface | `false` | 与候选 Gate 1/2/3 不是同一审批域，且缺摘要/TTL/单次消费约束 |
| stop / interrupt | run stop surface | `false` | 缺少 Run-scoped 幂等停止与重启后对账合同 |

`/v1/capabilities` 中即使出现 `run_submission=true`，也只说明 Hermes upstream 暴露了
入口，不证明平台已经具备“提交一次、可恢复、可追踪、可安全重试”的产品语义。

## 平台 BFF 只读合同

已交付的平台 BFF 只接受固定 allowlist 的 GET，并提供：

- `GET /api/hermes/gateway`
- `GET /api/hermes/sessions`
- `GET /api/hermes/sessions/{session_id}`
- `GET /api/hermes/sessions/{session_id}/messages`

边界要求：

1. Hermes API key 只从服务端 owner-only 文件读取，绝不下发浏览器、写入日志或放进
   LLM 上下文；HTTP client 禁用环境代理继承与 redirect。
2. upstream endpoint 必须是明确的 loopback HTTP origin；平台也必须只绑定 loopback。
   gateway enabled 时平台启动要求显式可信 bind 声明，并在每个 session 请求上核验实际
   ASGI server socket，不能只相信 Host header 或错误 env。`127.0.0.1` 是网络边界，不是
   操作系统级多用户鉴权；若开放 LAN/远程访问，必须先另做 TLS、登录、授权、CSRF 与审计。
3. session ID 必须拒绝 slash、反斜杠、dot segment、drive prefix、控制字符和超长值；
   upstream 响应必须限时、限字节、限条数并验证类型。
4. 消息投影只保留有限数量的 `user` / `assistant` 文本；Bearer、system、tool、reasoning
   等非展示字段和无效/截断 ID 不进入页面合同。user/assistant 文本按原内容限长展示，
   **没有 DLP/秘密扫描**；对话中曾粘贴的 key/token 仍可能显示。
5. upstream 不可用或配置不合法时返回可观察的 unavailable envelope；不得启用写端作为
   降级，也不得把旧 `POST /api/agent/tasks` 当 Hermes fallback。

## Provider 与数据库语义

- `health`、`capabilities`、session list/detail/messages 都是已有本地状态的 GET；不会启动
  Hermes 推理，因此不消耗 Codex、Grok 或其他 Hermes provider 额度。
- 本次 session-read slice 没有触发模型/provider 请求，也没有新增 PostgreSQL migration
  或 table。平台启动时只复用既有数据库与既有迁移。
- 将来只有真正创建 Run/提交 prompt 时才可能使用 Hermes 当前配置的 provider；在写合同
  未满足前，网页 composer 必须保持禁用，不能以“本机可对话”为由推断 provider 已锁定。

## 写端继续关闭的证据缺口

以下语义必须由 upstream 新能力或受审 adapter + durable ledger 共同提供，并经独立审查：

- caller-supplied idempotency key、持久 request lookup/recovery；
- 不变 Run identity，以及 requested/actual provider、model、fallback reason 和 usage 证据；
- 有 durable event ID/cursor 的断线 replay；
- session/provider policy 锁定，且 fallback 必须显式；
- approval 的主体、命令摘要、TTL、single-use/CAS；
- Run-scoped、幂等、可在重启后对账的 stop/reconcile。

在这些条件满足且 Wave 3 写端单独获批前，D-31 能力旗标必须保持：

```text
session_read=true
chat_write=false
stream=false
resume=false
approval_mutations=false
stop=false
execution=false
```

## 无模型调用的复核命令

```bash
git -C /Users/sunyibo/.hermes/hermes-agent rev-parse HEAD
shasum -a 256 \
  /Users/sunyibo/.hermes/hermes-agent/gateway/platforms/api_server.py
curl --fail --silent http://127.0.0.1:8642/health
```

带 Bearer 的能力/会话读取只应由服务端从专用 key file 完成；不要把 key 直接粘贴进 shell
历史、浏览器 DevTools、文档或测试 fixture。
