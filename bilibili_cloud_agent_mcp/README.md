# bilibili_cloud_agent_mcp — B 站 MCP + Skill Agent

云端/本地 `adk run` 经 **MCP HTTP** 调用本机 B 站 RPA（与 [`etsy_cloud_agent_mcp`](../etsy_cloud_agent_mcp/) 同模式）。

**推荐** B 站单领域路径；[`smart_agents`](../smart_agents/) 调度树中的 **阿B** 与本包共用 `smart_agents/bilibili_mcp_sub.py`。

## 调用链

```
adk run bilibili_cloud_agent_mcp
  → load_skill('bilibili-rpa')
  → McpToolset
  → BILIBILI_MCP_SERVER_URL（默认 :8002/mcp）
  → mcp_server/bilibili_mcp.py
  → rpa_tools.py → bilibili_tools.py
```

## 本地联调

**终端 1**
```bash
python mcp_server/bilibili_mcp.py --http
```

**终端 2**（云端 Playground 时需要）
```bash
cloudflared tunnel --url http://127.0.0.1:8002
# .env:
# BILIBILI_MCP_SERVER_URL=https://xxxx.trycloudflare.com/mcp
# BILIBILI_TUNNEL_HOST=xxxx.trycloudflare.com
```

**终端 3**
```bash
./scripts/run_adk_bilibili_cloud_agent_mcp.sh
```

纯本机：

```bash
BILIBILI_MCP_SERVER_URL=http://127.0.0.1:8002/mcp ./scripts/run_adk_bilibili_cloud_agent_mcp.sh
```

## MCP 工具

`get_up_list` · `fetch_fans_data` · `write_excel`（P0 envelope）

## 与 bilibili_cloud_agent（REST）的区别

| | MCP（本目录） | REST（[`bilibili_cloud_agent`](../bilibili_cloud_agent/)） |
|--|---------------|-----------------------------------------------------------|
| 端口 | :8002 | :8001 |
| 协议 | MCP Streamable HTTP | 自定义 REST |
| GCP Registry | 可注册 MCP Server URL | 无 |

## 部署到 Agent Engine

```bash
set -a && source .env && set +a

cp -R skills/bilibili-rpa/* bilibili_cloud_agent_mcp/skills/bilibili-rpa/
# 可选: python skill_registry.py update

adk deploy agent_engine bilibili_cloud_agent_mcp \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud MCP Agent" \
  --agent_engine_id=$BILIBILI_MCP_AGENT_ENGINE_ID
```

| 项 | 环境变量 |
|----|----------|
| Engine ID | `BILIBILI_MCP_AGENT_ENGINE_ID` |
| MCP Server Registry | `MCP_SERVER_REGISTRY_ID` |
| 云端 MCP URL | `BILIBILI_MCP_SERVER_URL` + Cloudflare Tunnel :8002 |

## 相关文档

- 操作手册：[`../user_guide.md`](../user_guide.md) §2.3（B 站 MCP）
- MCP Server：[`../mcp_server/README.md`](../mcp_server/README.md)
- Skill：[`../skills/README.md`](../skills/README.md)
- 调度树：[`../smart_agents/README.md`](../smart_agents/README.md)
