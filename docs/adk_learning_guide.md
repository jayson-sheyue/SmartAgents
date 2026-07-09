# SmartAgents 项目 — ADK 学习导读

> 梳理本项目实际用到的 **Google Agent Development Kit (ADK)** 概念、代码落点与**官方文档链接**。  
> 操作步骤：[`user_guide.md`](../user_guide.md) · 架构总览：[`README.md`](../README.md)

---

## 1. ADK 在本项目中的位置

**ADK** 是 Google 开源的代码优先 Agent 框架：定义 LLM Agent、挂载工具、管理 Session / Memory，并部署到 **Vertex AI Agent Engine（Reasoning Engine）**。

本项目在 **L3 编排层** 使用 ADK（Cursor stdio MCP **不经 ADK**）：

| 部署包 | 入口 | 模式 |
|--------|------|------|
| `bilibili_agent` | `agent.py` | 进程内工具 + Skill |
| `bilibili_cloud_agent` | `agent.py` | Skill + REST → `:8001` |
| `bilibili_cloud_agent_mcp` | `agent.py` | Skill + McpToolset → `:8002` |
| `etsy_agent` / `etsy_cloud_agent*` | `agent.py` | 与 B 站对称（Etsy API） |
| **`smart_agents`** | `agent.py` + **`app_factory.py`** | **多 Agent 调度树** + Memory Plugin + 事件压缩 |

```
┌──────────────────────────────────────────────────────────────────────┐
│  GCP Agent Engine（adk deploy agent_engine）                          │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────────┐ │
│  │ bilibili_cloud_* │  │ etsy_cloud_*     │  │ smart_agents (app)    │ │
│  │ 单领域 Agent     │  │ 单领域 Agent     │  │ Dispatcher + 2×子Agent │ │
│  └────────┬────────┘  └────────┬─────────┘  └───────────┬────────────┘ │
└───────────┼────────────────────┼────────────────────────┼──────────────┘
            │ REST :8001 / MCP   │                        │ 双 MCP
            ▼                    ▼                        ▼
     local_node/server.py   mcp_server/*.py         :8002 + :8003
            └────────────────────┴────────────────────────┘
                                 ▼
                    bilibili_tools.py / etsy_tools.py（L1）
```

---

## 2. 概念速查表

| 概念 | 本项目用法 | 代码位置 |
|------|-----------|----------|
| **`Agent`（`LlmAgent`）** | `root_agent`：model / instruction / tools / sub_agents | 各 `*/agent.py` |
| **`root_agent` 约定** | `adk run` 加载对象 | 各 `agent.py` 末尾 |
| **`App` + `--adk_app_object=app`** | Memory Plugin、Session 压缩 | `smart_agents/app_factory.py` |
| **自定义 Function Tool** | REST 包装函数 `*_from_node` | `bilibili_cloud_agent/agent.py` |
| **`McpToolset`** | Streamable HTTP → 本机 MCP | `*_mcp_sub.py`、`*_cloud_agent_mcp/` |
| **`SkillToolset`** | `load_skill` + 动态暴露工具 | 单领域 MCP/REST Agent |
| **`sub_agents` + `transfer_to_agent`** | 小智 → 阿B / E姐 | `smart_agents/agent.py` |
| **`GoogleSearchTool`** | 仅小智联网搜索 | `smart_agents/agent.py` |
| **`rag_search`（Function Tool）** | 仅小智；Vertex RAG Engine `retrieval_query` | `smart_agents/rag_tools.py` |
| **`PreloadMemoryTool` / `LoadMemoryTool`** | 仅小智长期记忆 | `smart_agents/agent.py` |
| **`after_agent_callback`** | 每轮结束写 Memory Bank | `smart_agents/callbacks.py` |
| **`MemoryPersistencePlugin`** | Runner 结束后 flush（兜底） | `smart_agents/plugins/memory_plugin.py` |
| **`EventsCompactionConfig`** | Session 事件压缩 | `smart_agents/app_factory.py` |
| **`VertexGemini`** | 代理访问 Vertex | `smart_agents/vertex.py` 等 |
| **`adk run`** | 本地交互调试 | `scripts/run_adk_*.sh` |
| **`adk deploy agent_engine`** | 部署/更新 Reasoning Engine | `scripts/deploy_smart_agents.sh` 等 |

---

## 3. 单领域 Agent（B 站 / Etsy）

### 3.1 三条执行路径

| 路径 | 工具如何到达 L1 | 典型场景 |
|------|-----------------|----------|
| **进程内** | Python 函数直接调 `*_tools.py` | 最快改 Skill / RPA |
| **REST** | Function Tool → HTTP `:8001` | REST 集成 demo |
| **MCP** | `McpToolset` → HTTP `:8002` / `:8003` | 标准 MCP、**调度树子 Agent** |

单领域 REST 与 MCP **均 Skill 化**：先 `load_skill`，再按 SOP 调工具。

### 3.2 Function Tools（REST）

ADK 根据函数名、类型注解、docstring 生成 tool schema。本项目 REST 工具统一返回 **P0 envelope**：`{ ok, tool, data, error, meta }`。

```python
# bilibili_cloud_agent/agent.py — 示意
def fetch_fans_data_from_node(up_name: str) -> dict:
    """从本地 REST 节点抓取 UP 主粉丝数。"""
    ...
```

官方：[Function Tools](https://adk.dev/tools-custom/function-tools/) · [Tool 总览](https://adk.dev/tools/)

### 3.3 McpToolset（MCP）

```python
McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=BILIBILI_MCP_SERVER_URL,
        timeout=30.0,
        sse_read_timeout=180.0,
    ),
    tool_filter=["get_up_list", "fetch_fans_data", "write_excel"],
)
```

云端经 Cloudflare Tunnel 或 `127.0.0.1` 访问。官方：[MCP 集成示例](https://adk.dev/integrations/supermetrics/)

### 3.4 SkillToolset + GCP Skill Registry

- **本地**：`load_skill_from_dir(skills/bilibili-rpa/)`
- **云端治理（可选）**：`skill_registry.py` → GCP Skill Registry
- **激活工具**：`SKILL.md` frontmatter `metadata.adk_additional_tools`

官方：[ADK × Skills Registry](https://adk.dev/integrations/skills-registry/) · 项目内：[`skills/README.md`](../skills/README.md)

---

## 4. 调度树 `smart_agents`（多 Agent）

### 4.1 架构

```
SmartAgents_Dispatcher（小智）
  ├─ Bilibili_Cloud_MCP_Agent（阿B）  ← bilibili_mcp_sub.py
  └─ Etsy_Cloud_MCP_Agent（E姐）      ← etsy_mcp_sub.py
```

- **路由**：`transfer_to_agent`；子 Agent **禁止** peer 互转
- **共享构建器**：`bilibili_mcp_sub.py` / `etsy_mcp_sub.py`（与单领域 MCP 包逻辑一致）
- **人格**：`personas.py`（秘书小智 / 专家口吻）

官方：[Multi-agent 编排](https://adk.dev/agents/multi-agents/)

### 4.2 `root_agent` vs `app`

| | `adk run smart_agents` | `adk deploy ... --adk_app_object=app` |
|--|------------------------|----------------------------------------|
| 加载对象 | `root_agent` | `app`（含 `root_agent`） |
| Memory Plugin | ❌ | ✅ `MemoryPersistencePlugin` |
| Session 压缩 | ❌ | ✅ `EventsCompactionConfig` |
| Memory Bank 持久化 | 本地内存实现 | `VertexAiMemoryBankService` |

```python
# smart_agents/agent.py
app = build_smart_agents_app(name="smart_agents", root_agent=_dispatcher_agent, enable_memory=True)
root_agent = _dispatcher_agent
```

部署：**必须** `--adk_app_object=app`（见 [`deploy_smart_agents.sh`](../scripts/deploy_smart_agents.sh)）。

### 4.3 记忆架构（仅小智）

| 组件 | 作用 |
|------|------|
| `PreloadMemoryTool` | 每轮预加载用户长期偏好 |
| `LoadMemoryTool` | 主动检索 Memory Bank |
| `after_agent_callback` | `add_events_to_memory` + `memories.generate` 元数据 |
| `MemoryPersistencePlugin` | Runner 结束后再 flush 一次（兜底） |
| Feishu Bridge | cloud 模式每轮 `memories.generate` 兜底 |

**身份隔离**：

| 入口 | `user_id` | `session_id` | Memory |
|------|-----------|--------------|--------|
| 飞书 | `feishu_{open_id}` | `feishu_{chat}_{user}` | ✅ 小智 only |
| Widget | `web_{uuid}` | 每 tab | ❌ |
| Playground | 控制台指定 | 控制台指定 | ✅（若 deploy app） |

子 Agent（阿B/E姐）**无** Memory / 搜索 / RAG 工具。

官方：[Memory Bank ADK Quickstart](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/adk-quickstart)

### 4.4 联网搜索（仅小智）

```python
GoogleSearchTool(bypass_multi_tools_limit=True)
```

用于新闻、天气、时效事实；B 站/Etsy RPA 任务仍 transfer 给专家，不搜索。

### 4.5 知识库 RAG（仅小智）

平台侧用 **RAG Engine** 建 corpus（文档切分 + embedding + 向量检索），代码侧只挂一个 Function Tool：

```python
# smart_agents/rag_tools.py
response = rag.retrieval_query(
    rag_resources=[rag.RagResource(rag_corpus=CORPUS_NAME)],
    text=query,
    rag_retrieval_config=rag.RagRetrievalConfig(top_k=5),
)
```

| 环境变量 | 说明 |
|----------|------|
| `RAG_ENABLED` | `true` 时挂载到小智 |
| `RAG_CORPUS_NAME` | `projects/.../locations/.../ragCorpora/...` |
| `RAG_LOCATION` | 须与 corpus 同 region（可跨 Agent Engine 区域调用） |

与 Memory / Search 的分工见 [`user_guide.md` §10](../user_guide.md#10-知识库-rag-poc)。  
平台文档：[RAG quickstart](https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/rag-quickstart)

### 4.6 Session 事件压缩

`app_factory.py` 默认启用（可用 `SMART_AGENTS_DISABLE_EVENT_COMPACTION=true` 关闭）：

| 环境变量 | 默认 |
|----------|------|
| `SMART_AGENTS_COMPACTION_TOKEN_THRESHOLD` | 80000 |
| `SMART_AGENTS_COMPACTION_EVENT_RETENTION` | 20 |
| `SMART_AGENTS_COMPACTION_INTERVAL` | 5 |
| `SMART_AGENTS_COMPACTION_OVERLAP` | 2 |

---

## 5. 入口层如何调用 ADK

| 入口 | 本地模式 | 云端模式 |
|------|----------|----------|
| **飞书 Bridge** | 进程内 `Runner` + `smart_agents` | `streamQuery` → Agent Engine |
| **Widget** | 本地 Runner | `streamQuery` + Session API |
| **Playground** | — | 直接连已部署 Engine |
| **`adk run`** | CLI 交互 | — |

飞书 cloud 模式：逻辑 `session_id` 与 Engine 分配 id 经 SQLite 映射（`cloud_session_store.py`），因 `async_create_session` 不支持自定义 id。

详见：[`integrations/feishu/README.md`](../integrations/feishu/README.md) · [`local_node/README.md`](../local_node/README.md)

---

## 6. 本地运行：`adk run`

> **注意**：`bilibili_cloud_agent*` / `etsy_cloud_agent*` 在本地 `adk run` 时工具仍经 **HTTP** 访问 MCP/REST URL，**不是**进程内直连 `*_tools.py`。须先起对应本地服务。

| 命令 | 前置服务 |
|------|----------|
| `adk run bilibili_agent` | `login` + Excel |
| `adk run bilibili_cloud_agent` | `local_node/server.py` :8001 |
| `adk run bilibili_cloud_agent_mcp` | `bilibili_mcp.py --http` :8002 |
| `adk run smart_agents` | 双 MCP :8002 + :8003 |

推荐用 `scripts/run_adk_*.sh`（处理 `VERTEX_HTTP_PROXY`，避免代理误伤 `127.0.0.1`）。

官方：[Sessions](https://adk.dev/sessions/) · [Python Quickstart](https://adk.dev/get-started/python/)

---

## 7. 部署到 Agent Engine

### 7.1 本项目用法：源文件 + `adk deploy agent_engine`

```bash
# 调度树（推荐脚本）
./scripts/deploy_smart_agents.sh
# 内含：rsync skills、写 smart_agents/.env、--adk_app_object=app

# 单领域示例
adk deploy agent_engine bilibili_cloud_agent_mcp \
  --project=$GCP_PROJECT_ID --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud MCP Agent" \
  --agent_engine_id=$BILIBILI_MCP_AGENT_ENGINE_ID
```

**首次部署**省略 `--agent_engine_id`；成功后把 ID 写入 `.env`。

### 7.2 其他部署方式（本项目未用，扩展阅读）

| 方式 | 说明 |
|------|------|
| Dockerfile / BYOC | 自带镜像 URI |
| Developer Connect | 从 Git 仓库部署 |
| `adk deploy cloud_run` / `gke` | 非托管 Runtime |

官方：[Deploy an agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent) · [ADK Agent Engine CLI](https://adk.dev/deploy/agent-engine/)

### 7.3 部署时注意

- `adk deploy` 只打包**目标目录**；`smart_agents` 的 Skill 须在 `smart_agents/skills/`
- 云端 MCP URL / **RAG_*** 写在 `smart_agents/.env`（由 deploy 脚本从根 `.env` 生成），非仓库根直接挂载
- CLI 会生成 `*_tmp*` 临时目录（gitignore），勿手改
- `source_packages` 上限约 8MB；私有依赖考虑 BYOC

---

## 8. 路径对比总表

| 维度 | 进程内 | REST 单领域 | MCP 单领域 | 调度树 `smart_agents` |
|------|--------|-------------|------------|----------------------|
| 协议 | 无 HTTP | HTTP :8001 | MCP :8002/8003 | 双 MCP |
| Skill | ✅ | ✅ | ✅ | 子 Agent 内 load |
| Memory Bank | 单 Agent 可有 | 单 Agent 可有 | 单 Agent 可有 | **仅小智** + `app` |
| 多 Agent | ❌ | ❌ | ❌ | ✅ Dispatcher |
| Google 搜索 | ❌ | ❌ | ❌ | ✅ 小智 |
| 知识库 RAG | ❌ | ❌ | ❌ | ✅ 小智（`rag_search`） |
| 推荐场景 | 改 RPA/Skill | REST demo | MCP demo / 子 Agent 共用 | 飞书 / Widget / 生产入口 |

---

## 9. 推荐学习路径（约 2–3 天）

### 第 1 步：环境与单领域 REST（0.5 天）

1. [Python Quickstart](https://adk.dev/get-started/python/)
2. [`user_guide.md` §2.2](../user_guide.md#22-rest本机或云端链路)：B 站 REST
3. 对照 `bilibili_cloud_agent/agent.py` 理解 `Agent` + Function Tool

### 第 2 步：MCP + Skill（0.5–1 天）

1. [Function Tools](https://adk.dev/tools-custom/function-tools/) · [MCP 示例](https://adk.dev/integrations/supermetrics/)
2. [`user_guide.md` §2.3](../user_guide.md#23-mcp本机或云端链路)：B 站 MCP
3. 阅读 `skills/bilibili-rpa/SKILL.md` · `python skill_registry.py validate`

### 第 3 步：调度树与多 Agent（0.5 天）

1. [Multi-agent](https://adk.dev/agents/multi-agents/)
2. [`user_guide.md` §4.1](../user_guide.md#41-本地调度树)：本地调度树
3. 阅读 `smart_agents/agent.py` · `bilibili_mcp_sub.py`

### 第 4 步：Memory、App 与部署（0.5–1 天）

1. [Memory Bank Quickstart](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/adk-quickstart)
2. 理解 `app_factory.py` · `callbacks.py` · `memory_ingest.py`
3. [`user_guide.md` §6.4](../user_guide.md#64-调度树-smart_agents-部署推荐脚本)：deploy + Playground
4. 可选：[`user_guide.md` §5](../user_guide.md#5-飞书接入清单基于调度树) 飞书 cloud
5. 可选：[`user_guide.md` §10](../user_guide.md#10-知识库-rag-poc) 小智挂 RAG 知识库

### 第 5 步：全链路实战

按 [`user_guide.md` §8](../user_guide.md#8-建议新手的最短路径) 从进程内 → 调度树 → 飞书走完。

---

## 10. 官方文档索引

### 入门

- https://adk.dev
- https://adk.dev/get-started/python/
- https://github.com/google/adk-python

### Agent 与工具

- https://adk.dev/agents/llm-agents/
- https://adk.dev/agents/multi-agents/
- https://adk.dev/tools/
- https://adk.dev/tools-custom/function-tools/
- https://adk.dev/models/

### 集成

- https://adk.dev/integrations/skills-registry/
- https://adk.dev/integrations/supermetrics/
- https://adk.dev/deploy/connect-to-google-cloud/

### 部署与 Runtime

- https://adk.dev/deploy/agent-engine/
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-adk-agent
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent

### Memory Bank

- https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/setup
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/adk-quickstart

### RAG Engine

- https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/rag-quickstart
- https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/rag-overview

### 会话

- https://adk.dev/sessions/

---

## 11. 项目内文档交叉引用

| 文档 | 内容 |
|------|------|
| [`user_guide.md`](../user_guide.md) | 场景速查、部署、排错、**§10 RAG** |
| [`README.md`](../README.md) | 架构、模块地图 |
| [`smart_agents/README.md`](../smart_agents/README.md) | 调度树、记忆、RAG、deploy |
| [`skills/README.md`](../skills/README.md) | Skill Registry CLI |
| [`mcp_server/README.md`](../mcp_server/README.md) | MCP Server（被调用方） |
| [`integrations/feishu/README.md`](../integrations/feishu/README.md) | 飞书 Bridge、护栏 |

---

## 12. 常见问题（ADK 相关）

| 现象 | 原因 | 处理 |
|------|------|------|
| `adk run` 即 `httpx.ConnectError` | Vertex 网络 | `VERTEX_HTTP_PROXY` + `run_adk_*.sh` |
| 工具 HTTP 404 | 隧道过期 | 更新 URL 或 `127.0.0.1` |
| MCP 无 RPA 工具 | 未 load_skill 或 MCP 未起 | 按 instruction；起 :8002/:8003 |
| 改了 Skill 云端未生效 | 未同步部署包 + redeploy | `rsync` / `cp` + `adk deploy` |
| Memory Bank 空 | 未 deploy `app` 或未 flush | `deploy_smart_agents.sh` + 飞书 cloud |
| `adk run` 调度树无记忆 | 预期 | 记忆需云端 `app` |
| deploy 后 MCP 421 | `TUNNEL_HOST` | 重启 MCP |
| 云端不调 `rag_search` | 未写入 `smart_agents/.env` 或未 redeploy | 根 `.env` 设 `RAG_*` 后跑 `deploy_smart_agents.sh` |
| RAG 跨区查询失败 | `RAG_LOCATION` ≠ corpus region | 与 corpus Details 中的 location 对齐 |

---

*基于 SmartAgents 代码库与 Google ADK 官方文档（2026-07）。链接失效时以 https://adk.dev 站内导航为准。*
