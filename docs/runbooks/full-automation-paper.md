# D-33 自动 paper 运行手册

> **历史运行手册。** 产品身份见
> [`../plans/2026-08-13-personal-quant-assistant.md`](../plans/2026-08-13-personal-quant-assistant.md)。
> 本文只解释已经落地的论文入队机怎么开关，不再定义默认研究入口。

## 1. 边界

这条路径把已满足 `hqa.paper_intake/v1` 的论文研究请求自动推进到：机器策略评审、真实
final backtest、本地 `paper_only` 因子、限额 sleeve、paper 信号、执行计划和模拟成交。
它不授予 `live_eligible`，不调用 live broker，不 auto-push GitHub，也不改变 public release。

四个开关必须同时为精确小写 `true`，否则在任何自动 mutation 前拒绝：

```dotenv
QS_FACTOR_AUTOMATION_MODE=true
QS_FACTOR_AUTOMATION_AUTO_LAND=true
HQA_FACTOR_AUTOMATION_MODE=true
HQA_FACTOR_AUTOMATION_AUTO_LAND=true
```

开关只写入 Platform runtime 的 owner-only
`data/_runtime/agent-v0.2-backend.env`（普通文件、owner、`0600`）。不要写进 Git、shell
profile、Codex/Claude 临时环境。源码默认值是 false；本机 owner runtime 已在
2026-08-10 完成全量测试与冷启动验收后显式启用四项。

## 2. 常驻方式

正常入口仍是：

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform
bash scripts/local_mac_stack.sh start
bash scripts/local_mac_stack.sh status
```

stack 会安装 D-33 的 user LaunchAgent `com.aiquant.factor-automation`。它每 300 秒调用
repository-owned runner；runner从 owner env 解析稳定 HQA root/Python，明确拒绝
`.codex`、`.claude` 或 ChatGPT.app 内的临时运行时，因此关闭 AI 工具或终端不影响服务。
当前 stack 还独立安装 Asia Radar daily refresh；它与 D-33 队列及资格链无关。

## 3. 入队合同

唯一 Hermes ingress：

```bash
~/.hermes/scripts/hqa-factor-automation.sh enqueue --request-file /absolute/path/request.json
```

安装 wrapper 只允许该 exact enqueue，并转交同一个 Platform owner-env runner；因此四个
Flag 来自 `0600` runtime env，而不是 Hermes、Codex/Claude 或调用终端的临时环境。

request 必须是严格 schema `hqa.factor_automation_request/v1`，包含：

- 唯一 `automation_id`、正文 intake receipt/digest；
- owner-owned、非符号链接的绝对 Python source 与精确 SHA-256；
- ordered universe、`futu|tiingo`、start/end、Platform `base_commit`；
- policy evidence。调用方声明仅用于预检；最终授权会从实际 backtest artifact 重算
  sample/OOS/coverage/cost/drawdown/turnover；
- 源码静态前视扫描拒绝负向 `shift/diff/pct_change`、backfill/bfill 和 centered rolling。

入队将源码复制到 owner-private `0700` queue，文件为 `0600`。相同内容幂等；同 ID 不同
内容冲突。driver 串行消费，每次只取一项；成功结果写入 owner-private run artifact，失败
保留可恢复事实，不凭模型 prose 宣告成功。

每次 enqueue 和每轮 queue 消费还会读取 Platform 的只读
`hqa.d34_research_routing/v1`。D-34 的 `10` 个完整周期与 `5` 个观察日只形成时间门；只有随后
的最终零重复/零 live eligibility receipt 通过显式本机 cutover，D-34 才成为默认新研究入口。
此时新的 D-33 enqueue 返回 `d33_new_intake_disabled_by_d34`，已有 queue 保持原样且不消费；
driver 仍先运行 `factor-automation-maintain`，所以旧 D-33 sleeve 的估值、pause/quarantine 和
paper cycle 不会停止。routing authority 不可读取时，新 D-33 intake 失败并给出
`d34_research_routing_unavailable`，维护结果仍保留可见。

## 4. 机器 Gate 与资格隔离

- Gate 1：精确源码 digest + `auto:` note；
- Gate 2：候选/digest/status CAS，`reviewer=auto`、`registration=auto_promote`、版本化
  policy digest；
- final backtest：real provider、唯一 experiment namespace、真实数据证据和静态检查均通过；
- Gate 3：prepare 后独立 auto-commit，再走既有 reviewed-commit 校验；
- land：Platform main HEAD CAS + `git merge --ff-only`，仅本地，不 push；
- qualification 固定 `promotion_scope=paper_only`。paper registry 可加载，live registry
  必须硬拒绝。进入 live 需要一条全新的人工资格流程，不能继承自动结果。

## 5. 首发限额与审计

首发采用保守档：单 sleeve `min(10,000, 1% NAV)`，自动 sleeve 合计 10% NAV，日 promote
1、日 demote 5，单票 40% sleeve，账户跨 sleeve 单票 5% NAV，单笔 10,000。日亏达到 2%
或从峰值回撤达到 10% 自动 pause。

PostgreSQL migration 029 的 append-only 表是 promote/demote/日配额权威；文件只作运行
缓存。029 已在 2026-08-10 经备份和隔离 restore 后 apply 一次，禁止重放。正常启动从不
执行 migration。

## 6. 常驻 paper 周期

driver 每五分钟先做风险维护，再只处理 `automation_managed=true` 且 running 的 sleeve：

- 本机时区周二至周六 06:10 后：当日信号至多一次，并建立下一个工作日的 next-open
  计划；
- 周一至周五 21:35 后：处理当日到期计划，paper fill 至多一次；
- 并发重跑以 signal/execution identity 幂等；手工 sleeve 不在扫描范围；
- 当前使用工作日规则，不内置交易所假期日历。休市或数据缺失应产生无订单/阻断事实，
  不得伪造 fill。

## 7. Pause、quarantine 与 demote

限额或风险触发时先 pause，禁止新订单。因子缺失/不一致进入 `quarantined_hold`：停止
sleeve、卸载 resident factor，但继续估值、告警并计入暴露；这不等于已经平仓。
可选 flatten 完成后才是 `demoted_complete`。默认不自动平仓。

## 8. 观察、关闭与恢复

```bash
launchctl print "gui/$(id -u)/com.aiquant.factor-automation"
tail -n 50 data/_runtime/logs/factor-automation.launchd.out.log
tail -n 50 data/_runtime/logs/factor-automation.launchd.err.log
```

紧急关闭：先把任意一对 Flag 改为 false，再运行 `local_mac_stack.sh start` 重新安装/拉起。
driver 会报告 disabled，不继续自动 mutation；已有 paper 持仓不会因此假装消失。需要拆除
某个因子时走 audited demote，默认 hold。Git 冲突、unknown outcome 或失败队列必须保留
原 artifact 后按精确 ID 恢复，禁止删除证据后重跑。

D-34 rollback 会在暂停 Mandate、取消 queued D-34 job 和 hold D-34 canary 的同一次 owner
操作里，把默认研究入口恢复为 D-33。下一次 enqueue 立即重新可用，不需要改四个 Flag、编辑
env 或重启 LaunchAgent；D-34 以后重新达标时仍需一份新的最终验收 receipt 才能再次 cutover。

## 9. 2026-08-10 本机验收快照

- HQA Python 3.11 全量 pytest 通过；Platform Python 3.11 全量 pytest 通过；
- 前端 77 个测试文件 / 468 个测试、type-check、lint、production build 通过；
- 两份 HQA checkout fast-forward 到同一 `main`，两份 Platform checkout
  fast-forward 到同一 `main`；GitHub 未 push；
- `local_mac_stack.sh start` 完成 production build 并安装常驻 jobs；Hermes/backend/
  frontend/connector 均 ready；Docker `quantplatform-db` ready；
- factor automation RunAtLoad 返回 `state=idle, queued=0`，launchd last exit 0；
- `/api/health` 显示 `admission_mode=local_trust`、`release_authorized=false`；
  `/api/safety/effective` 显示 `dry_run=true`、`paper_trading=true`、
  `live_trading_enabled=false`、`kill_switch=true`。
