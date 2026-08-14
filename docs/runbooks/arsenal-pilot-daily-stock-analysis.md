# 兵器库试点：daily_stock_analysis（个股分析 → 值班账来源）

状态：**runbook 已备，部署等你执行**（需要你选 LLM key 与端口，见第 2 步）。
纪律来自现行计划 §4 兵器库条款：MCP/skill 包装 + 收据 + 只喂值班/研究账。

## 1. 它是什么、放哪本账

[ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)（28k star）：
LLM 驱动的 A/H/美股自选股分析器，出「决策仪表盘」报告，带 FastAPI 服务与 Docker 镜像。
在本助手里它只当**值班账的分析来源**：报告=观点收据，进晨报/雷达引用；
**永远不产生成交资格，不碰模拟账**（红线：机会结论不能升级成交资格）。

## 2. 部署（一次性，约 10 分钟，需要你在场）

```bash
mkdir -p ~/programs/arsenal && cd ~/programs/arsenal
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis
cp .env.example .env   # 然后编辑 .env：
```

你要拍板的两件事：

1. **LLM key**：`.env` 里配 OpenAI 兼容端点。可选本机 Hermes OAuth 代理
   `http://127.0.0.1:8645/v1`（走 Hermes 订阅，注意消耗预算），或独立的 DeepSeek key（便宜、隔离）。
   建议先用独立 key，别让兵器吃 Hermes 预算。
2. **端口**：默认 8000，与本机栈无冲突即可。

```bash
docker run -d --name dsa-server --env-file .env -p 8000:8000 \
  -v "$(pwd)/data:/app/data" -v "$(pwd)/reports:/app/reports" \
  zhulinsen/daily_stock_analysis:latest \
  python main.py --serve-only --host 0.0.0.0 --port 8000
curl -s http://127.0.0.1:8000/api/analysis/status   # 冒烟
```

## 3. 包装成 Hermes 兵器（部署后半小时）

1. **skill**：`~/.hermes/skills/arsenal-dsa/SKILL.md`，描述写死触发条件：
   「个股涨跌/买卖点/技术面分析类问题，必须先调本工具，答复引用报告收据；
   工具不可用时明说，不得用散文顶替」。调用 = `POST /api/analysis/analyze`，
   落收据 = 保存报告 JSON 的 `sha256 + 路径` 进值班账事件。
2. **注册表**：`config/arsenal-registry.v1.json` 新建，一件兵器一条
   （name、端点、触发条件、账本归属、收据字段）。会话系统提示注入注册表摘要。
3. **路由评测**：`tests/` 加 10 条典型问法用例（「NVDA 明天涨吗」「帮我看看这支票」…），
   定期回放；答复无兵器收据 → 判「未走兵器」失败。

## 4. 验收（一句话定义）

在 `:3002` 右栏问一句「帮我分析下 AAPL 今天的技术面」，Hermes 调 DSA、
答复末尾带报告收据（sha256 短码），该收据同时出现在值班账事件里——即试点通过。
