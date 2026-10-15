# SmartAgents — Agent Platform 学习导读

> 结合**本项目实践**与 **Google Gemini Enterprise Agent Platform**（含 ADK、Agent Engine、Memory Bank、RAG、Code Execution、Remote MCP）官方能力，说明「用了什么、代码在哪、官方文档去哪查」。  
> 操作步骤：[`user_guide.md`](../user_guide.md) · 架构：[`README.md`](../README.md) · domains：[`domains_architecture.md`](domains_architecture.md)

---

## 1. 平台栈在本项目中的位置

SmartAgents 不是「只用 ADK」的 demo，而是 **Agent Platform 多组件组合**：

| 层级 | 平台能力 | 本项目落点 |
|------|----------|------------|
| **编排** | ADK `Agent` / `App` / `sub_agents` | `smart_agents/agent.py` · `app_factory.py` |
| **运行时** | Vertex AI **Agent Engine**（Reasoning Engine） | `adk deploy agent_engine` · 飞书/Widget `cloud` |
| **模型** | Vertex AI Gemini | `smart_agents/vertex.py` |
| **工具协议** | MCP over HTTP | `mcp_server/*` · `McpToolset` |
| **工作流 SOP** | ADK Skill + GCP Skill Registry（可选） | `skills/` · `SkillToolset` |
| **长期记忆** | **Memory Bank** | `callbacks.py` · `plugins/memory_plugin.py` |
| **团队知识** | **Vertex RAG Engine** | `smart_agents/rag_tools.py` |
| **联网** | `GoogleSearchTool` | 仅小智 |
| **数据分析/作图** | **Code Execution**（Agent Engine Sandbox） | `smart_agents/code_exec.py` |
| **企业数据** | **Knowledge Catalog** + **Firestore Remote MCP** | `smart_agents/gcp_data_mcp.py` |
| **TSE 业务** | 确定性只读工具（17 个） | `smart_agents/tse_tools.py` · `tse_store.py` |
| **入口** | 飞书长连接 / Web Widget / `adk run` | `integrations/feishu/` · `local_node/` |

```
┌─────────────────────────────────────────────────────────────────────────┐
│ L4 入口：飞书 Bridge · Web Widget · adk run · Agent Engine Playground     │
├─────────────────────────────────────────────────────────────────────────┤
│ L3 小智调度树（ADK App）                                                  │
│   Memory · RAG · Search · Code Exec · TSE 工具 · transfer → 子 Agent    │
├─────────────────────────────────────────────────────────────────────────┤
│ L2 MCP :8002 / :8003  │  KC MCP  │  Firestore MCP（只读 fs_*）          │
├─────────────────────────────────────────────────────────────────────────┤
│ L1 domains/bilibili · domains/etsy · Firestore（TSE 生产库）              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. ADK：代码优先的 Agent 框架

**ADK**（Agent Development Kit）负责：定义 `Agent`、挂载工具、管理 Session、部署到 Agent Engine。

| 概念 | 本项目 | 代码 |
|------|--------|------|
| `LlmAgent` / `Agent` | 小智、阿B、E姐 | `domains/*/builder.py` · `smart_agents/agent.py` |
| `tools` | Function tools + MCP toolsets | `agent.py` · `tse_tools.py` |
| `sub_agents` + `transfer_to_agent` | 小智 → 阿B / E姐 | `smart_agents/agent.py` |
| `root_agent` | `adk run` 加载 | 各 `agent.py` 末尾 |
| `App` + `--adk_app_object=app` | Memory Plugin、Session 压缩 | `smart_agents/app_factory.py` |
| `before_model_callback` | 纯招呼短路 | `smart_agents/greeting.py` |
| `after_agent_callback` | Memory Bank 写入 | `smart_agents/callbacks.py` |

官方：[ADK 文档](https://adk.dev) · [Python Quickstart](https://adk.dev/get-started/python/) · [Multi-agent](https://adk.dev/agents/multi-agents/)

---

## 3. Agent Engine（Reasoning Engine）与部署

云端运行时载体是 **Vertex AI Agent Engine**（控制台常称 Reasoning Engine）。

| 模式 | 行为 | 配置 |
|------|------|------|
| **local** | 进程内 `Runner` | 飞书 `FEISHU_RUN_MODE=local` · Widget `WIDGET_RUN_MODE=local` |
| **cloud** | `streamQuery` 调已部署 Engine | `SMART_AGENTS_ENGINE_ID` 或 `AGENT_RESOURCE_NAME` |

```bash
./scripts/deploy_smart_agents.sh   # rsync skills + 生成 smart_agents/.env + deploy app
```

| | `adk run` | `deploy --adk_app_object=app` |
|--|-----------|-------------------------------|
| Memory Plugin | ❌ | ✅ |
| Session 事件压缩 | ❌ | ✅ `EventsCompactionConfig` |
| Memory Bank 持久化 | 内存实现 | `VertexAiMemoryBankService` |

官方：[Deploy an agent](https://cloud.google.com/gemini-enterprise/docs/agent-engine/deploy)

---

## 4. Memory Bank（长期记忆，仅小智）

| 组件 | 作用 |
|------|------|
| `PreloadMemoryTool` / `LoadMemoryTool` | 每轮注入 / 主动检索用户偏好 |
| `after_agent_callback` | `memories.generate` 刷写 |
| `MemoryPersistencePlugin` | Runner 结束后再 flush（兜底） |
| 飞书 `agent_client.py` | cloud 模式每轮 generate 兜底 |

子 Agent（阿B/E姐）**无** Memory / Search / RAG。

`user_id`：飞书 `feishu_{open_id}`（跨群共享）；Widget `web_{uuid}`（匿名）。

官方：[Memory Bank ADK 集成](https://cloud.google.com/gemini-enterprise/docs/agent-engine/memory-bank/adk)

---

## 5. Vertex RAG Engine（团队文档，仅小智）

- 工具：`rag_search`（`smart_agents/rag_tools.py`）
- 开关：`RAG_ENABLED=true` + `RAG_CORPUS_NAME`
- 与 Memory 分工：Memory =「这个人」；RAG =「团队 PDF/手册」

官方：[RAG Engine 快速入门](https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/rag-quickstart)

---

## 6. Code Execution（沙箱 Python，仅小智）

在 **Agent Engine Sandbox** 中执行 Python（pandas / matplotlib 等），用于统计、作图。

| 项 | 说明 |
|----|------|
| 开关 | `CODE_EXECUTION_ENABLED=true` + `SMART_AGENTS_ENGINE_ID` |
| 工具 | `run_code` · `stage_data_file` |
| TSE 作图 | `render_tse_customer_sales_chart`（内嵌真实数据，禁止手写示例） |
| 产物 | Session **Artifact**；`after_agent_callback` inline 回传 → **GE / Playground** 出图；飞书经 `media_delivery.py` 发图/附件 |
| 区域 | 通常 `us-central1`（`CODE_EXEC_LOCATION`） |

官方：[Code Execution](https://cloud.google.com/gemini-enterprise/docs/agent-engine/code-execution)（以控制台文档为准）

---

## 7. GCP 数据层：KC + Firestore MCP + TSE 工具

### 7.1 三层设计（避免「遇场景就补丁」）

| 层 | 模块 | 职责 |
|----|------|------|
| **L0** | `gcp_data_mcp.py` | Remote MCP：`kc_*`（元数据）· `fs_*`（**只读** get/list） |
| **L1** | `tse_store.py` | Firestore MCP 封装、分页、字段解析 |
| **L2** | `tse_tools.py` | **17 个确定性场景工具** + `list_tse_tool_catalog` |

开关：`GCP_DATA_MCP_ENABLED=true`（或分别 `KC_MCP_ENABLED` / `FIRESTORE_MCP_ENABLED`）。

### 7.2 关键原则

- TSE 业务查询：**先** `list_tse_tool_catalog` 或 `lookup_tse_schema`，**再**调场景工具
- **禁止** `fs_add_document` / `fs_update_document` / `fs_delete_document`（已从白名单移除）
- **日报** = `global_customers.daily_reports[]` 内嵌数组，不是独立 collection
- Glossary 详见仓库根 [`KC-checklist.md`](../KC-checklist.md)

### 7.3 工具目录（节选）

| 意图 | 工具 |
|------|------|
| 不确定用哪个 | `list_tse_tool_catalog` |
| 某销售客户 + 日报 | `get_tse_sales_customer_reports` |
| 用户可见客户 | `list_tse_items_for_user` |
| 统计 / 分布图 | `get_tse_customer_sales_stats` · `render_tse_customer_sales_chart` |
| 待审批分享 | `list_tse_pending_shares` |

完整列表见 `TSE_TOOL_CATALOG`（`tse_tools.py`）。

官方：[Knowledge Catalog MCP](https://cloud.google.com/gemini-enterprise/docs/knowledge-catalog) · Firestore 经 [MCP 工具用户](https://cloud.google.com/firestore/docs) + `roles/mcp.toolUser`

---

## 8. MCP + Skill（领域 RPA）

### 8.1 调用链

```
Agent → load_skill(SKILL.md) → McpToolset → :8002|:8003 → domains/*
```

- B 站：`skills/bilibili-rpa/` → `:8002`
- Etsy：`skills/etsy-review/` · `etsy-listing-assets/` → `:8003`

### 8.2 构建器

[`domains/bilibili/builder.py`](../domains/bilibili/builder.py) / [`domains/etsy/builder.py`](../domains/etsy/builder.py)：

```python
tools = [McpToolset(...), SkillToolset(...)]
Agent(name=..., instruction=..., tools=tools)
```

官方：[MCP Tools](https://adk.dev/tools-custom/mcp-tools/) · [Skills Registry](https://adk.dev/integrations/skills-registry/)

---

## 9. 调度树 `smart_agents`

```
SmartAgents_Dispatcher（小智）
  ├─ Bilibili_Cloud_MCP_Agent（阿B）
  └─ Etsy_Cloud_MCP_Agent（E姐）
```

能力矩阵见 [`smart_agents/README.md`](../smart_agents/README.md)。

**A2A（并行第二 Engine）**：`SMART_AGENTS_ENGINE_ID`（xiaozhi / `adk deploy app`）保持不变；`./scripts/deploy_smart_agents_a2a.sh` 另建 Runtime，用 Vertex `A2aAgent` + 自定义 Executor 包同一 `root_agent`，写入 `SMART_AGENTS_A2A_ENGINE_ID`。本地：`./scripts/run_a2a_smart_agents_local.sh`。PoC Session/Memory 为 in-memory，不等于飞书 Memory Bank。

---

## 10. 入口层与会话

| 入口 | local | cloud | 备注 |
|------|-------|-------|------|
| `adk run` | ✅ | — | 双 MCP 须先起 |
| 飞书 | `FEISHU_RUN_MODE=local` | streamQuery | [`integrations/feishu/README.md`](../integrations/feishu/README.md) |
| Widget | `WIDGET_RUN_MODE=local` | streamQuery | `:8000` |

**飞书 local 防爆闸**：`FEISHU_LOCAL_SESSION_GUARD_ENABLED` — 事件/字符超阈值自动轮换 Session，避免 token 溢出 400。

**Session 压缩**（deploy `app`）：`EventsCompactionConfig` in `app_factory.py`。

---

## 11. 推荐学习路径（约 2–3 天）

### Day 1 — 环境与 MCP

1. [`user_guide.md` §0–§2](../user_guide.md)
2. [ADK Python Quickstart](https://adk.dev/get-started/python/)
3. 读 `domains/bilibili/builder.py` + `mcp_server/bilibili_mcp.py`

### Day 2 — 调度树与平台能力

1. [Multi-agent](https://adk.dev/agents/multi-agents/)
2. `smart_agents/agent.py` · `app_factory.py`
3. [`user_guide.md` §4](../user_guide.md) 本地调度树
4. 可选：RAG §10 · Code Execution §12 · TSE §11

### Day 3 — 部署与入口

1. [Deploy an agent](https://cloud.google.com/gemini-enterprise/docs/agent-engine/deploy)
2. [Memory Bank](https://cloud.google.com/gemini-enterprise/docs/agent-engine/memory-bank/adk)
3. [`user_guide.md` §5–§6](../user_guide.md) 飞书 + deploy
4. 全链路：[`user_guide.md` §8](../user_guide.md#8-新手最短路径约-30-分钟)

---

## 12. 官方文档索引

| 主题 | 链接 |
|------|------|
| ADK 总入口 | https://adk.dev |
| Agent Engine | https://cloud.google.com/gemini-enterprise/docs/agent-engine |
| Memory Bank | https://cloud.google.com/gemini-enterprise/docs/agent-engine/memory-bank |
| RAG Engine | https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine |
| Skill Registry | https://cloud.google.com/gemini-enterprise/docs/skill-registry |
| Knowledge Catalog | https://cloud.google.com/gemini-enterprise/docs/knowledge-catalog |

---

## 13. 项目内文档

| 文档 | 内容 |
|------|------|
| [`user_guide.md`](../user_guide.md) | 场景速查、部署、排错 |
| [`README.md`](../README.md) | 架构总览 |
| [`smart_agents/README.md`](../smart_agents/README.md) | 调度树能力矩阵 |
| [`KC-checklist.md`](../KC-checklist.md) | TSE Glossary 与 Firestore schema |
| [`env/README.md`](../env/README.md) | 环境变量两层 |
| [`skills/README.md`](../skills/README.md) | Skill 维护 |

---

## 14. 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| MCP 不可达 | 未起 `:8002`/`:8003` | 先 `mcp_server/*_mcp.py --http` |
| Token 溢出 400（飞书） | Session 历史过大 | Session guard 已默认开；发「新对话」 |
| Memory 空 | 未 deploy `app` | `deploy_smart_agents.sh` |
| TSE 反问「日报在哪」 | 未用确定性工具 | `list_tse_tool_catalog` → `get_tse_sales_customer_reports` |
| 图表假数据 | 未用 `render_tse_customer_sales_chart` | 禁止手写 Sales01 示例 `run_code` |
| RAG 不生效 | 未写入 `smart_agents/.env` | redeploy |
| Firestore 写失败 | 已禁写工具 | 设计为只读；改数据走 TSE App |

---

*基于 SmartAgents 代码库与 Google Agent Platform 文档（2026-07）。*
