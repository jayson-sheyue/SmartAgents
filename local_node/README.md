# local_node — REST 本地节点 + Web Widget

本目录是 **REST 协议层**：把 L1 工具暴露为 HTTP API，供云端 REST Agent 或 Web Widget 调用。

| 领域 | L1 | REST 路由前缀 |
|------|-----|---------------|
| B 站 | [`bilibili_agent/bilibili_tools.py`](../bilibili_agent/bilibili_tools.py) | `/api/get_up_list` 等 |
| Etsy | [`etsy_agent/etsy_tools.py`](../etsy_agent/etsy_tools.py) | `/api/etsy_*` |

操作手册：[`../user_guide.md`](../user_guide.md) §2.2 · §3.2（REST）· §4.3（Widget）

MCP 路径在 [`../mcp_server/`](../mcp_server/)，功能等价、协议不同。

---

## 文件说明

| 文件 | 端口 | 作用 |
|------|------|------|
| `server.py` | **8001** | FastAPI：B 站 RPA + Etsy REST 路由 |
| `widget_server.py` | **8000** | 前端入口（local: 本地 smart_agents Runner / cloud: Agent Engine） |
| `index.html` | — | 聊天 Widget 页面（请求 `:8000/chat`） |
| `openapi.json` | — | OpenAPI 描述（参考） |

---

## API 映射（REST Tool ↔ Python）

云端 `bilibili_cloud_agent` 中的函数与此一一对应（**P0 envelope**，实现见 [`../bilibili_agent/bilibili_tools.py`](../bilibili_agent/bilibili_tools.py)）：

| REST 端点 | bilibili_cloud_agent 工具名 | rpa_tools |
|-----------|-------------------|-----------|
| `GET /api/get_up_list` | `get_up_list_from_node` | `tool_get_up_list` |
| `POST /api/fetch_fans_data` | `fetch_fans_data_from_node` | `tool_fetch_fans_data` |
| `POST /api/write_excel` | `write_excel_to_node` | `tool_write_excel` |

**P0 响应**：直接返回 `{ok, tool, data, error, meta}` envelope，不再是 `{status, data}`。

Excel 路径默认 `~/Desktop/Up主名称.xlsx`；可选 `excel_path`（须在 Desktop 或 `~/Documents/BilibiliRPA` 下）。

---

## 启动顺序

### 场景 A：云端 REST Agent / 本地 `adk run` / curl 直调

```bash
# 终端 1 — REST 节点（必做）
python local_node/server.py
# 终端 2 — 网络出口（二选一）
#   A1) Cloudflare Tunnel（Playground / Widget / 与 .env 中 https 域名一致）
cloudflared tunnel --url http://127.0.0.1:8001
# .env: BILIBILI_REST_SERVER_URL=https://<你的域名>.trycloudflare.com

#   A2) 仅本机 adk run，本机直连（免隧道）
# .env 或命令行: BILIBILI_REST_SERVER_URL=http://127.0.0.1:8001
```

`adk run bilibili_cloud_agent` 与 Playground 相同，经 HTTP 调 `BILIBILI_REST_SERVER_URL`，**不是**进程内 RPA。详见 [`../bilibili_cloud_agent/README.md`](../bilibili_cloud_agent/README.md)。

### 场景 B：Web Widget（双模式）

```bash
# local 模式（免部署）
# .env: WIDGET_RUN_MODE=local
python mcp_server/bilibili_mcp.py --http   # 终端 1
python mcp_server/etsy_mcp.py --http       # 终端 2
python local_node/widget_server.py         # 终端 3

# cloud 模式（连 Agent Engine）
# .env: WIDGET_RUN_MODE=cloud + SMART_AGENTS_ENGINE_ID（或 AGENT_RESOURCE_NAME）
# 还需双 Cloudflare Tunnel（8002 / 8003）确保云端可访问 MCP
./scripts/run_widget.sh
# 或: python local_node/widget_server.py

# 浏览器（推荐，避免 file:// 跨域问题）
open http://localhost:8000/
```

| 配置 | 说明 |
|------|------|
| `WIDGET_RUN_MODE` | `local` 或 `cloud` |
| `SMART_AGENTS_ENGINE_ID` | cloud 模式默认目标 Engine |
| `AGENT_RESOURCE_NAME` | 可选，显式覆盖目标 Engine |
| `GCP_PROJECT_NUMBER` | Widget streamQuery 资源路径中的项目编号 |
| `GCP_PROJECT_ID` | GCP 项目 ID |
| `VERTEX_HTTP_PROXY` | 国内访问 GCP streamQuery 时需要（如 `http://127.0.0.1:7890`） |
| `GET /health` | 检查 Widget 与当前模式依赖是否就绪 |

`POST /chat` 返回：`reply`、`session_id`（多轮会话）、`tool_events`（工具调用/结果摘要）。

**Session 续接（Phase 2c+）**：刷新页面后对话不丢，依赖显式 Session API：

| 端点 | 作用 |
|------|------|
| `POST /session` | 校验 `sessionStorage` 中的 id，无效则 `async_create_session` |
| `POST /chat` | 内部先 `ensure_session`，再 `streamQuery`（始终带 `session_id`） |

请求体示例：`{"user_id":"web_user_001","session_id":"可选","force_new":false}`

Widget local/cloud 两种模式都支持同一前端页面 `index.html`。

---

## 与 MCP 路径对比

| | REST（本目录） | MCP（mcp_server/） |
|---|----------------|---------------------|
| 端口 | 8001 | 8002 |
| 暴露方式 | 自定义 `/api/*` | MCP `tools/list` + `tools/call` |
| 云端 Agent | `bilibili_cloud_agent` | `bilibili_cloud_agent_mcp` |
| GCP 控制台 | 不注册 | Agent Registry → MCP Servers |

---

## 升级改造

1. **新增 API**：在 `server.py` 加路由 → 在 `bilibili_cloud_agent/agent.py` 加包装函数 → 更新 `skills/.../references/tools.md`
2. **改 RPA 行为**：只改 [`bilibili_agent/bilibili_tools.py`](../bilibili_agent/bilibili_tools.py)，本目录通常只改请求/响应格式
3. **Widget 换 Agent**：改 `widget_server.py` 的 `AGENT_RESOURCE_NAME`

---

## 相关文档

- 操作手册：[`../user_guide.md`](../user_guide.md) §2.2 · §3.2 · §4.3 · §6
- B 站 REST Agent：[`../bilibili_cloud_agent/README.md`](../bilibili_cloud_agent/README.md)
- Etsy REST Agent：[`../etsy_cloud_agent/README.md`](../etsy_cloud_agent/README.md)
