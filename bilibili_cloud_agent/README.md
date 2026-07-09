# bilibili_cloud_agent — B 站 REST + Skill Agent

云端/本地 `adk run` 经 **HTTP REST** 调用本机 B 站 RPA 节点（与 [`etsy_cloud_agent`](../etsy_cloud_agent/) 同模式，领域为 B 站）。

## 调用链

```
adk run bilibili_cloud_agent
  → load_skill('bilibili-rpa')
  → get_up_list_from_node / fetch_fans_data_from_node / write_excel_from_node
  → BILIBILI_REST_SERVER_URL/api/*
  → local_node/server.py :8001
  → rpa_tools.py → bilibili_tools.py（Playwright）
```

> **重要**：`adk run` 与 Playground **走 HTTP REST**，不是进程内直连 `rpa_tools.py`。

## 本地联调

### 方式 A — Cloudflare Tunnel（与云端 Playground 一致）

**终端 1**
```bash
python local_node/server.py
```

**终端 2**
```bash
cloudflared tunnel --url http://127.0.0.1:8001
# .env: BILIBILI_REST_SERVER_URL=https://xxxx.trycloudflare.com
```

**终端 3**
```bash
./scripts/run_adk_bilibili_cloud_agent.sh
```

### 方式 B — 纯本机（本机直连（免隧道））

```bash
BILIBILI_REST_SERVER_URL=http://127.0.0.1:8001 ./scripts/run_adk_bilibili_cloud_agent.sh
```

## 与 bilibili_cloud_agent_mcp 的区别

| | 本目录（REST） | [`bilibili_cloud_agent_mcp`](../bilibili_cloud_agent_mcp/)（MCP） |
|--|----------------|------------------------------------------------------------------|
| 执行层 | REST 包装函数 → :8001 | `McpToolset` → :8002/mcp |
| 本地服务 | `local_node/server.py` | `mcp_server/bilibili_mcp.py --http` |
| 与调度树 | 不直接用于 `smart_agents` | **子 Agent 阿B 共用** `bilibili_mcp_sub.py` |

## 与调度树的关系

- **单跑 B 站**：用本目录（REST）或 `bilibili_cloud_agent_mcp`（MCP，推荐）
- **调度树**：用 [`smart_agents`](../smart_agents/)，B 站子 Agent 走 **MCP** 路径

## 部署到 Agent Engine

```bash
source .venvAgents/bin/activate
set -a && source .env && set +a

# 同步 Skill 副本（若改过 skills/bilibili-rpa/）
cp -R skills/bilibili-rpa/* bilibili_cloud_agent/skills/bilibili-rpa/

adk deploy agent_engine bilibili_cloud_agent \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud REST Agent" \
  --agent_engine_id=$BILIBILI_REST_AGENT_ENGINE_ID
```

| 项 | 环境变量 |
|----|----------|
| Engine ID | `BILIBILI_REST_AGENT_ENGINE_ID` |
| 云端调本地 | `BILIBILI_REST_SERVER_URL` 指向 Cloudflare Tunnel :8001 |

部署后：GCP Console → Agent Engine → Playground（须本机 `local_node/server.py` + Cloudflare Tunnel 在跑）。

## 排错

| 现象 | 处理 |
|------|------|
| 工具 HTTP 404 | 隧道未开或 `.env` 域名过期 → 更新或改用 `127.0.0.1:8001` |
| `httpx.ConnectError`（Vertex） | 设 `VERTEX_HTTP_PROXY`，用 `run_adk_bilibili_cloud_agent.sh` |
| 503 `LOGIN_STATE_MISSING` | 本机 `python -m bilibili_agent login` |

## 相关文档

- 操作手册：[`../user_guide.md`](../user_guide.md) §2.2（B 站 REST）
- REST 节点：[`../local_node/README.md`](../local_node/README.md)
- 启动脚本：[`../scripts/README.md`](../scripts/README.md)
