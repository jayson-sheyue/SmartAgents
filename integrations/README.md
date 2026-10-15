# integrations — 外部平台接入

| 目录 | 说明 |
|------|------|
| [`feishu/`](feishu/) | 飞书群聊 / 私聊 → `smart_agents` 调度树 |

---

## 飞书双通道

| 模式 | 行为 |
|------|------|
| `FEISHU_RUN_MODE=local` | Bridge 进程内 ADK Runner，等价 `adk run smart_agents` |
| `FEISHU_RUN_MODE=cloud` | `streamQuery` 调已部署的 Agent Engine |

local 模式须 **双 MCP 常开**（:8002 + :8003）。

小智在飞书侧的能力与 `adk run smart_agents` 一致（含 RAG、TSE、Code Execution），由根 `.env` 开关控制。

---

## 快速启动

```bash
python mcp_server/bilibili_mcp.py --http    # 终端 1
python mcp_server/etsy_mcp.py --http        # 终端 2
./scripts/run_feishu_smart_agents.sh        # 终端 3
```

配置见 [`feishu/README.md`](feishu/README.md) 与 [`../env/README.md`](../env/README.md)（`.env` + `env/local.env`）。

---

## 相关文档

- [`../user_guide.md`](../user_guide.md) §5
- [`feishu/README.md`](feishu/README.md)
- [`../docs/agent_platform_learning_guide.md`](../docs/agent_platform_learning_guide.md) §10
- [`../README.md`](../README.md)
