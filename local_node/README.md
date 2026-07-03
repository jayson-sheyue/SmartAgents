# local_node — REST 本地节点 + Web Widget

本目录是 **REST 协议层**：把 [`main.py`](../main.py) 的 RPA 能力暴露为 HTTP API，供云端 REST Agent 或浏览器 Widget 调用。

MCP 路径在 [`../mcp_server/`](../mcp_server/)，功能等价、协议不同。

---

## 文件说明

| 文件 | 端口 | 作用 |
|------|------|------|
| `server.py` | **8001** | FastAPI：3 个 RPA API |
| `widget_server.py` | **8000** | 前端 → 云端 REST Agent 的中转 |
| `index.html` | — | 聊天 Widget 页面（请求 `:8000/chat`） |
| `openapi.json` | — | OpenAPI 描述（参考） |

根目录的 `server.py` / `widget_server.py` 为**兼容 shim**，内部转调本目录。

---

## API 映射（REST Tool ↔ Python）

云端 `cloud_agent` 中的函数与此一一对应（**P0 envelope 已对接**，见 [`../feat.md`](../feat.md)）：

| REST 端点 | cloud_agent 工具名 | rpa_tools |
|-----------|-------------------|-----------|
| `GET /api/get_up_list` | `get_up_list_from_node` | `tool_get_up_list` |
| `POST /api/fetch_fans_data` | `fetch_fans_data_from_node` | `tool_fetch_fans_data` |
| `POST /api/write_excel` | `write_excel_to_node` | `tool_write_excel` |

**P0 响应**：直接返回 `{ok, tool, data, error, meta}` envelope，不再是 `{status, data}`。

Excel 路径默认 `~/Desktop/Up主名称.xlsx`；可选 `excel_path`（须在 Desktop 或 `~/Documents/BilibiliRPA` 下）。

---

## 启动顺序

### 场景 A：云端 REST Agent / curl 直调

```bash
# 终端 1 — REST 节点
python local_node/server.py
# 或: python server.py

# 终端 2 — ngrok
ngrok http 8001

# .env
NGROK_URL=https://<你的域名>.ngrok-free.dev
```

### 场景 B：Web Widget 演示（Phase 2c）

```bash
# 终端 1 — REST 节点（必须）
python local_node/server.py

# 终端 2 — ngrok 8001（云端 Agent 调本地 RPA 需要）
ngrok http 8001
# .env: NGROK_URL=https://<你的域名>.ngrok-free.dev

# 终端 3 — Widget 中转
./scripts/run_widget.sh
# 或: python local_node/widget_server.py

# 浏览器（推荐，避免 file:// 跨域问题）
open http://localhost:8000/
```

| 配置 | 说明 |
|------|------|
| `REST_AGENT_ENGINE_ID` | Widget 调用的 REST Reasoning Engine |
| `GCP_PROJECT_NUMBER` | Widget streamQuery 资源路径中的项目编号 |
| `GCP_PROJECT_ID` | GCP 项目 ID |
| `VERTEX_HTTP_PROXY` | 国内访问 GCP streamQuery 时需要（如 `http://127.0.0.1:7890`） |
| `GET /health` | 检查 Widget + 本地 :8001 是否就绪 |

`POST /chat` 返回：`reply`、`session_id`（多轮会话）、`tool_events`（工具调用/结果摘要）。

**Session 续接（Phase 2c+）**：刷新页面后对话不丢，依赖显式 Session API：

| 端点 | 作用 |
|------|------|
| `POST /session` | 校验 `sessionStorage` 中的 id，无效则 `async_create_session` |
| `POST /chat` | 内部先 `ensure_session`，再 `streamQuery`（始终带 `session_id`） |

请求体示例：`{"user_id":"web_user_001","session_id":"可选","force_new":false}`

改用 MCP Agent 时：修改 `.env` 中 `REST_AGENT_ENGINE_ID` 为 MCP Engine ID，或设 `AGENT_RESOURCE_NAME` 全路径。

---

## 与 MCP 路径对比

| | REST（本目录） | MCP（mcp_server/） |
|---|----------------|---------------------|
| 端口 | 8001 | 8002 |
| 暴露方式 | 自定义 `/api/*` | MCP `tools/list` + `tools/call` |
| 云端 Agent | `cloud_agent` | `cloud_agent_mcp` |
| GCP 控制台 | 不注册 | Agent Registry → MCP Servers |

---

## 升级改造

1. **新增 API**：在 `server.py` 加路由 → 在 `cloud_agent/agent.py` 加包装函数 → 更新 `skills/.../references/tools.md`
2. **改 RPA 行为**：只改 [`main.py`](../main.py)，本目录通常只改请求/响应格式
3. **Widget 换 Agent**：改 `widget_server.py` 的 `AGENT_RESOURCE_NAME`

---

## 相关文档

- 全场景命令：[`../user_guide.md`](../user_guide.md) 场景三、四、六
- REST 云端 Agent：[`../cloud_agent/README.md`](../cloud_agent/README.md)
