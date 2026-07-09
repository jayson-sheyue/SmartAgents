# etsy_agent — Etsy 评论 Agent

Etsy 域模块：**Open API v3**，支持三种 Agent 路径。

## 三条路径

| 路径 | 目录 | 执行方式 | 本地联调 |
|------|------|----------|----------|
| **进程内** | `etsy_agent/` | Skill + 直连 `etsy_tools` | `./scripts/run_adk_etsy_agent.sh` |
| **REST** | `etsy_cloud_agent/` | Skill + HTTP → `:8001` | `./scripts/run_adk_etsy_cloud_agent.sh` + Cloudflare Tunnel 或 `127.0.0.1` |
| **MCP** | `etsy_cloud_agent_mcp/` | Skill + MCP → `:8003` | `./scripts/run_adk_etsy_cloud_agent_mcp.sh` + Cloudflare Tunnel 或 `127.0.0.1` |

企业 demo 推荐 **REST / MCP**（凭证与 Excel 留在本机）。快速改 Skill 可用进程内路径。

B 站域对称结构：`bilibili_agent` / `bilibili_cloud_agent` / `bilibili_cloud_agent_mcp`（见 [`../README.md`](../README.md)）。

## 目录结构

```
etsy_agent/etsy_tools.py     ← L1 工具（唯一实现）
local_node/server.py         ← REST /api/etsy_*
mcp_server/etsy_mcp.py       ← MCP :8003
skills/etsy-review/          ← Skill SOP
etsy_cloud_agent/            ← REST Agent
etsy_cloud_agent_mcp/        ← MCP Agent
```

## 本地 Cloudflare Tunnel 联调（REST）

```bash
# 终端 1
python local_node/server.py

# 终端 2
cloudflared tunnel --url http://127.0.0.1:8001
# 更新 .env ETSY_REST_SERVER_URL=https://....trycloudflare.com

# 终端 3
./scripts/run_adk_etsy_cloud_agent.sh
```

## 本地 Cloudflare Tunnel 联调（MCP）

```bash
# 终端 1
python mcp_server/etsy_mcp.py --http

# 终端 2
cloudflared tunnel --url http://127.0.0.1:8003
# 更新 .env ETSY_MCP_SERVER_URL=https://....trycloudflare.com/mcp

# 终端 3
./scripts/run_adk_etsy_cloud_agent_mcp.sh
```

本机直连（免隧道）：见 [`../etsy_cloud_agent/README.md`](../etsy_cloud_agent/README.md) 与 [`../etsy_cloud_agent_mcp/README.md`](../etsy_cloud_agent_mcp/README.md)。

## L1 工具测试（无大模型）

```bash
python scripts/test_etsy_local.py --check-credentials --verify-api
python scripts/test_etsy_local.py --listing-id 786582119 --live-fetch
```

## 凭证

本机 `.env`：`ETSY_KEYSTRING` + `ETSY_SHARED_SECRET`。REST/MCP 路径下由 `local_node` / `etsy_mcp` 读取，不经 Agent 上云。

## 相关文档

- 操作手册：[`../user_guide.md`](../user_guide.md) §3（Etsy 域）
- 导读：[`../README.md`](../README.md)
- 脚本：[`../scripts/README.md`](../scripts/README.md)
- Skill：[`../skills/etsy-review/SKILL.md`](../skills/etsy-review/SKILL.md)
