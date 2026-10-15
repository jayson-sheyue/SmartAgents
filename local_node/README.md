# local_node — Web Widget

浏览器聊天页，把用户消息转给 **smart_agents 调度树**（local 本机 Runner 或 cloud Agent Engine）。

> 本目录 **仅保留 Widget**（`:8000`）。历史 REST 节点 `:8001` 已移除；工具统一走 MCP。

---

## 文件

| 文件 | 说明 |
|------|------|
| `widget_server.py` | FastAPI 服务，`:8000` |
| `index.html` | 聊天 UI（访问 `http://127.0.0.1:8000/`） |
| `openapi.json` | API 参考 |

---

## 调用链

```
浏览器 index.html
  → POST :8000/chat
  → widget_server.py
       ├─ local:  进程内 ADK Runner（smart_agents）
       └─ cloud:  Vertex streamQuery → Agent Engine
  → 调度树 → MCP :8002 / :8003 → domains/
```

---

## local 模式（推荐新手，免 deploy）

```bash
# 终端 1
python mcp_server/bilibili_mcp.py --http

# 终端 2
python mcp_server/etsy_mcp.py --http

# 终端 3
# .env 或 env 中：WIDGET_RUN_MODE=local
./scripts/run_widget.sh
```

浏览器打开：**http://127.0.0.1:8000/**

验证：「先查 B 站粉丝，再导出 Etsy 评论」（测跨域调度）。  
TSE / 作图：在 `.env` 开启 `GCP_DATA_MCP_ENABLED` / `CODE_EXECUTION_ENABLED` 后，对小智问「梁伶飞客户日报」或「客户分布图」。

---

## 能力说明

| 能力 | Widget | 备注 |
|------|:------:|------|
| 调度树（阿B/E姐） | ✅ | 双 MCP 须先起 |
| Memory Bank | ❌ | 匿名 `web_{uuid}` |
| RAG / TSE / Code Exec | ✅ | 与小智一致，由 `.env` 控制 |

---

## cloud 模式

```env
WIDGET_RUN_MODE=cloud
SMART_AGENTS_ENGINE_ID=your-engine-id
GCP_PROJECT_NUMBER=...
```

前置：[`user_guide.md` §4.2](../user_guide.md)（双隧道 + 双 MCP + deploy）。

```bash
./scripts/run_widget.sh
```

纯闲聊只需 Widget + 已 deploy Engine；**RPA 任务仍须本机双 MCP + 隧道**。

---

## 插件嵌入（第三方 Web App）

任意站点可用一行脚本接入，**不改宿主业务代码逻辑**（仅注入悬浮聊天窗）：

```html
<script
  src="http://127.0.0.1:8000/embed.js"
  data-api-base="http://127.0.0.1:8000"
  data-title="SmartAgents"
  data-position="bottom-right"
  async
></script>
```

或先设 `window.SMART_AGENTS_WIDGET = { url: 'http://127.0.0.1:8000' }` 再加载 `/embed.js`。

`embed.js` 会 iframe 打开本服务的 `/?embed=1`（全屏聊天面板，隐藏自带悬浮钮）。  
原有独立页 `http://127.0.0.1:8000/` 行为不变。

---

## 环境变量

| 变量 | 说明 |
|------|------|
| `WIDGET_RUN_MODE` | `local` 或 `cloud` |
| `GCP_PROJECT_ID` / `GCP_LOCATION` | 必填 |
| `SMART_AGENTS_ENGINE_ID` | cloud 模式 |
| `AGENT_RESOURCE_NAME` | 可选，覆盖 Engine |
| `VERTEX_HTTP_PROXY` | 国内访问 GCP |
| `WIDGET_PORT` | 默认 `8000` |
| （嵌入）`/embed.js` | 第三方站点插件入口，见上文「插件嵌入」 |

健康检查：`GET http://127.0.0.1:8000/health`

---

## Session

- 每浏览器 tab 独立 `session_id`（存 `sessionStorage`）
- 点「新会话」清空当前 tab 上下文
- **不使用** Memory Bank（匿名 `web_{uuid}`）

---

## 相关文档

- [`../user_guide.md`](../user_guide.md) §4.3
- [`../smart_agents/README.md`](../smart_agents/README.md)
- [`../docs/agent_platform_learning_guide.md`](../docs/agent_platform_learning_guide.md)
