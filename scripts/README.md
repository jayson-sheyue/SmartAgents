# scripts — 启动与测试脚本

所有脚本默认在 **仓库根目录** 执行：`./scripts/<name>.sh`

**全场景命令矩阵**：[`../user_guide.md`](../user_guide.md) §1 · **开发者前置条件**：[`../user_guide.md` §0](../user_guide.md#0-开发者本地部署前置条件总览)

通用前置（详见 user_guide §0）：

```bash
source .venvAgents/bin/activate
cp .env.example .env   # 首次；按 §0 填写 GCP / Etsy / 飞书等
# 云端 Playground：另需 brew install cloudflared && ./scripts/start_cloudflare_tunnel.sh <port>
```

---

## Agent 脚本一览

| 脚本 | `adk run` 目标 | 领域 | 协议 | 本地必须先起 |
|------|----------------|------|------|--------------|
| [`run_adk_bilibili_agent.sh`](run_adk_bilibili_agent.sh) | `bilibili_agent` | B 站 | 进程内 | `python -m bilibili_agent login` + Excel |
| [`run_adk_bilibili_cloud_agent.sh`](run_adk_bilibili_cloud_agent.sh) | `bilibili_cloud_agent` | B 站 | REST | `python local_node/server.py` (:8001) |
| [`run_adk_bilibili_cloud_agent_mcp.sh`](run_adk_bilibili_cloud_agent_mcp.sh) | `bilibili_cloud_agent_mcp` | B 站 | MCP | `python mcp_server/bilibili_mcp.py --http` (:8002) |
| [`run_adk_etsy_agent.sh`](run_adk_etsy_agent.sh) | `etsy_agent` | Etsy | 进程内 | `.env` Etsy 凭证 |
| [`run_adk_etsy_cloud_agent.sh`](run_adk_etsy_cloud_agent.sh) | `etsy_cloud_agent` | Etsy | REST | `local_node/server.py` (:8001) |
| [`run_adk_etsy_cloud_agent_mcp.sh`](run_adk_etsy_cloud_agent_mcp.sh) | `etsy_cloud_agent_mcp` | Etsy | MCP | `python mcp_server/etsy_mcp.py --http` (:8003) |
| [`run_adk_smart_agents.sh`](run_adk_smart_agents.sh) | `smart_agents` | **调度树** | 双 MCP | B 站 :8002 + Etsy :8003 |
| [`run_feishu_smart_agents.sh`](run_feishu_smart_agents.sh) | （Bridge 内嵌 Runner） | 飞书→调度树 | 双 MCP | 同上 + 飞书长连接配置 |

---

## 本地 vs 云端 Playground

| 模式 | 脚本行为 | 额外要求 |
|------|----------|----------|
| **纯本机** | 脚本默认 `127.0.0.1` MCP/REST URL | 无需隧道 |
| **云端 Playground** | 使用 `.env` 中 Cloudflare Tunnel HTTPS URL | `./scripts/start_cloudflare_tunnel.sh <port>`；MCP 配 `*_TUNNEL_HOST` |

`run_adk_smart_agents.sh` / `run_feishu_smart_agents.sh` **默认强制本机 MCP**（避免 `.env` 里只配了一条隧道）。云端演示请显式：

```bash
export SMART_AGENTS_BILIBILI_MCP_SERVER_URL=https://<bilibili-uuid>.trycloudflare.com/mcp
export SMART_AGENTS_ETSY_MCP_SERVER_URL=https://<etsy-uuid>.trycloudflare.com/mcp
./scripts/run_adk_smart_agents.sh
```

| 脚本 | 说明 |
|------|------|
| [`deploy_smart_agents.sh`](deploy_smart_agents.sh) | 同步 skills + 生成 `smart_agents/.env`（含 **MCP / RAG_***）+ `adk deploy --adk_app_object=app` |
| [`start_cloudflare_tunnel.sh`](start_cloudflare_tunnel.sh) | Cloudflare Quick Tunnel 说明与启动 |

> **RAG**：仅当根 `.env` 设置 `RAG_ENABLED=true` 与 `RAG_CORPUS_NAME` 时，deploy 会把配置打进云端；细则见 [`../user_guide.md`](../user_guide.md) §10。


---

## 单领域 vs 整棵树

```
单领域 B 站进程内: ./scripts/run_adk_bilibili_agent.sh
单领域 B 站 MCP:    ./scripts/run_adk_bilibili_cloud_agent_mcp.sh
单领域 Etsy MCP:  ./scripts/run_adk_etsy_cloud_agent_mcp.sh
整棵调度树:       ./scripts/run_adk_smart_agents.sh
飞书入口:         ./scripts/run_feishu_smart_agents.sh
```

调度树中的子 Agent 与单领域 MCP 包 **共用** `smart_agents/bilibili_mcp_sub.py`、`etsy_mcp_sub.py`。

---

## 测试脚本

| 脚本 | 说明 |
|------|------|
| [`test_p0_local.py`](test_p0_local.py) | B 站 P0 envelope（`rpa_tools` / REST） |
| [`test_etsy_local.py`](test_etsy_local.py) | Etsy 工具与 API |

```bash
python scripts/test_p0_local.py
python scripts/test_etsy_local.py
```

---

## 其他

| 脚本 | 说明 |
|------|------|
| [`run_widget.sh`](run_widget.sh) | Web Widget 网关 → `local_node/widget_server.py` |

---

## 云端部署（不在此目录执行 deploy）

部署使用 `adk deploy agent_engine <包名>`，见：

- [`../bilibili_cloud_agent/README.md`](../bilibili_cloud_agent/README.md)
- [`../bilibili_cloud_agent_mcp/README.md`](../bilibili_cloud_agent_mcp/README.md)
- [`../smart_agents/README.md`](../smart_agents/README.md)
- [`../etsy_cloud_agent/README.md`](../etsy_cloud_agent/README.md)
- [`../etsy_cloud_agent_mcp/README.md`](../etsy_cloud_agent_mcp/README.md)

---

## Vertex 代理

带 `run_adk_*` 的脚本会：

1. 将 Shell 的 `HTTPS_PROXY` 转为 `VERTEX_HTTP_PROXY`（仅 Vertex 用）
2. 清掉全局 `HTTP_PROXY`，避免 httpx 误代理本地 `127.0.0.1`

详见 [`../bilibili_cloud_agent/README.md`](../bilibili_cloud_agent/README.md) 排错一节。
