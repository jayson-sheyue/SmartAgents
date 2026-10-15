# SmartAgents — 调度树（Dispatcher + 三 MCP 子 Agent）

根 Agent **小智**负责接待、记忆、搜索、RAG、**TSE 数据**、**Code Execution**、**Task Card**，通过 `transfer_to_agent` 把 B 站 / Etsy / 飞书出站交给 **阿B**、**E姐**、**小飞**。

生产里用户从 **TSE Smart Workspace** 侧栏进来（工作台同域 API → Agent Engine），不是本机 Widget。复合任务的可交付物写在 Session Task Card（`task_card.py`）；工作台 `smart_agents_runtime` 按 card 自动续跑。

---

## 架构

```
SmartAgents_Dispatcher（小智）
  ├─ GoogleSearch · PreloadMemory · LoadMemory
  ├─ rag_search（可选）
  ├─ run_code · stage_data_file（可选，Code Execution）
  ├─ build_tse_tools() × 18（可选，GCP_DATA_MCP_ENABLED）
  ├─ kc_* · fs_* Remote MCP（可选，fs 只读）
  ├─ Bilibili_Cloud_MCP_Agent   → Cloud Run / :8002
  ├─ Etsy_Cloud_MCP_Agent       → Cloud Run / :8003
  └─ Feishu_Cloud_MCP_Agent     → Cloud Run / :8004（lark-cli Bot）
```

- 子 Agent：[`domains/bilibili/builder.py`](../domains/bilibili/builder.py) · [`domains/etsy/builder.py`](../domains/etsy/builder.py) · [`domains/feishu/builder.py`](../domains/feishu/builder.py)（`standalone=False`）
- 子 Agent **禁止** peer 互转
- 代码：[`agent.py`](agent.py) · App：[`app_factory.py`](app_factory.py)
- 飞书 **入站** bridge 见 [`integrations/feishu`](../integrations/feishu/README.md)；与小飞出站正交

---

## 能力矩阵

| 能力 | 小智 | 阿B / E姐 / 小飞 |
|------|:----:|:----------------:|
| Session（短期） | ✅ | ✅ |
| Memory Bank | ✅ | ❌ |
| `google_search` | ✅ | ❌ |
| `rag_search` | ✅（`RAG_ENABLED`） | ❌ |
| TSE 确定性工具 | ✅（`GCP_DATA_MCP_ENABLED`） | ❌ |
| Code Execution / 作图 | ✅（`CODE_EXECUTION_ENABLED`） | ❌ |
| MCP 领域工具 | 经 transfer | ✅ |

---

## TSE 数据（可选）

开关：`GCP_DATA_MCP_ENABLED=true`（或分别开 Firestore/KC）；API：`TSE_API_BASE_URL` + 会话 Key。  
路径约定见 [`docs/tse_data_access.md`](../docs/tse_data_access.md)（**Lab-00**：`API/工具 > Firestore MCP > KC`）。

| 模块 | 路径 | 说明 |
|------|------|------|
| 场景工具 | `tse_tools.py` | P0 业务界面；有 Key 时 list/get 优先 External API |
| API 客户端 | `tse_api_client.py` | `/api/external/v1/*` |
| 存储层 | `tse_store.py` | Firestore MCP 封装（P1 兜底） |
| Remote MCP | `gcp_data_mcp.py` | `fs_*` 兜底 / `kc_*` 可选元数据 |

**入口**：用户问 TSE → 先 `list_tse_tool_catalog` → 调对应 `get_tse_*` / `list_tse_*`。  
Glossary：[`KC-checklist.md`](../KC-checklist.md)

常用工具：

- `get_tse_overview` — 用户/客户总览（Firestore）
- `list_tse_customers` / `get_tse_customer` — 有 Key 优先 API
- `query_tse_daily_reports_by_date` — 按时间段查日报（跨客户）
- `search_tse_daily_reports` — 关键词证据检索
- `set_tse_session_api_key` / `ask_tse_workspace` / `generate_tse_global_report` — 会话 Key + API
- `map_tse_daily_reports_to_bitable` — 映射多维表格 records
- `get_tse_customer_sales_stats` / `render_tse_customer_sales_chart` — 统计与分布图

---

## Code Execution（可选）

```env
CODE_EXECUTION_ENABLED=true
CODE_EXEC_LOCATION=us-central1
```

- `run_code` / `stage_data_file` — 沙箱 Python
- `render_tse_customer_sales_chart` — TSE 分布图（**禁止**手写示例数据）
- 产物 → Session Artifact → 飞书 [`media_delivery.py`](../integrations/feishu/media_delivery.py)

---

## 本地运行

```bash
# 终端 1–3：三 MCP（飞书需本机 lark-cli + FEISHU_APP_*）
python mcp_server/bilibili_mcp.py --http
python mcp_server/etsy_mcp.py --http
python mcp_server/feishu_mcp.py --http

# 终端 4
cp env/local.env.example env/local.env   # 首次
./scripts/run_adk_smart_agents.sh
```

对话示例：

- 「抓 B 站全站热门」→ 阿B
- 「导出 Etsy listing 评论」→ E姐
- 「查今天飞书日历」→ 小飞
- 「把本月需跟进的客户写入这个多维表格」→ Task Card `bitable_with_rows` → 小智拉日报 + 小飞写入
- 「你好」→ 小智
- 「Gemini 权限怎么配？」→ 小智 `search_tse_knowledge` / `rag_search`
- 「梁伶飞客户 + 随机日报」→ 小智 `get_tse_sales_customer_reports`

---

## 记忆与用户隔离

| 入口 | `user_id` | Memory Bank |
|------|-----------|-------------|
| TSE 工作台侧栏 | 登录邮箱 | 小智；cloud + deploy `app` 持久 |
| 飞书入站 | `feishu_{open_id}` | 小智；cloud + deploy `app` 持久 |
| Widget | `web_{uuid}` | 匿名，不持久 |
| `adk run` | CLI 默认 | 无 Plugin |

飞书 **`新对话`**：清 Session，不删 Memory。  
飞书 local **Session guard**：`FEISHU_LOCAL_SESSION_GUARD_ENABLED`（防 token 溢出）。

---

## 知识库 RAG（可选）

```env
RAG_ENABLED=true
RAG_CORPUS_NAME=projects/.../ragCorpora/...
RAG_LOCATION=asia-east1
```

细则：[`user_guide.md`](../user_guide.md) §10。

---

## 飞书 / Widget

```bash
./scripts/run_feishu_smart_agents.sh
./scripts/run_widget.sh                # :8000
```

均需双 MCP（local 模式）。

---

## 环境变量（核心）

| 变量 | 说明 |
|------|------|
| `GCP_PROJECT_ID` | Vertex（必填） |
| `GCP_DATA_MCP_ENABLED` | TSE KC + Firestore + 场景工具 |
| `TSE_FIRESTORE_PROJECT_ID` / `TSE_FIRESTORE_DATABASE` | TSE 库 |
| `TSE_API_BASE_URL` | TSE 应用根 URL（/chat、/global_report） |
| `TSE_API_KEY` | 可选运维回落；生产由用户会话 `set_tse_session_api_key` 提供 |
| `CODE_EXECUTION_ENABLED` | 沙箱 Python |
| `RAG_*` | 知识库 |
| `SMART_AGENTS_ENGINE_ID` | 云端 deploy |
| `FEISHU_LOCAL_SESSION_*` | 飞书 local Session 防爆闸 |

完整列表： [`.env.example`](../.env.example) · [`env/README.md`](../env/README.md)

---

## 云端部署

```bash
./scripts/deploy_smart_agents.sh
```

`rsync skills/` → `smart_agents/skills/`，生成 `smart_agents/.env`，`adk deploy ... --adk_app_object=app`。

### 并行第二 Engine（A2A）

不替换 `SMART_AGENTS_ENGINE_ID`（xiaozhi / 飞书 cloud）。另起一台 Runtime，用 Vertex `A2aAgent` 包同一棵 `root_agent`：

```bash
./scripts/run_a2a_smart_agents_local.sh          # card smoke
./scripts/run_a2a_smart_agents_local.sh live     # 可选；需双 MCP
./scripts/deploy_smart_agents_a2a.sh             # 创建或更新 SMART_AGENTS_A2A_ENGINE_ID
```

PoC Executor 使用 in-memory Session/Memory（尚未接 App Memory Bank）。云端 RPA 仍需可达 MCP 隧道。

模块：`a2a_card.py` · `a2a_executor.py` · `a2a_agent.py`。

---

## 相关文档

- [`user_guide.md`](../user_guide.md) §4–§6、§11–§12
- [`docs/agent_platform_learning_guide.md`](../docs/agent_platform_learning_guide.md)
- [`integrations/feishu/README.md`](../integrations/feishu/README.md)
- [`local_node/README.md`](../local_node/README.md)
# SAP Computer Use（可选）

小智支持通过独立浏览器执行服务按采购订单号查询 SAP，使用截图驱动的 Gemini Computer Use。
默认关闭；启动、登录、只读边界和 TSE 云端限制见 [SAP 接入说明](../docs/sap_computer_use.md)。

小智同时支持上传发票图片/PDF，提取采购订单号、供应商、金额、币种和日期，再执行 SAP 查询。
触发话术、原生附件输入与部署配置见 [发票 → SAP Demo](../docs/sap_invoice_demo.md)。
云端小智通过 HTTPS 调用本机专用 SAP 浏览器，启动与绑定见 [本机接入说明](../docs/sap_local_bridge.md)。
当前客户 PoC 使用固定三步黄金路径，脚本和实际能力范围见 [黄金路径 Demo](../docs/sap_golden_path.md)。
