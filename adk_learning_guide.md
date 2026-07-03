# SmartAgents 项目 — ADK 辅助学习导读

> 本文档梳理 **本项目实际用到的 Google Agent Development Kit (ADK)** 概念、代码落点与**官方文档链接**，便于按图索骥系统学习。  
> 操作步骤见 [`user_guide.md`](user_guide.md)；架构总览见 [`README.md`](README.md)。

---

## 1. ADK 是什么？在本项目里扮演什么角色？

**ADK（Agent Development Kit）** 是 Google 开源的、代码优先的 Agent 开发框架，用于定义 LLM Agent、挂载工具、管理会话/记忆，并部署到 **Vertex AI Agent Engine（Reasoning Engine）**。

在本项目中，ADK **只用于 L3 云端 Agent 层**（不用于 `main.py` 本地 Agent 或 Cursor MCP）：

| 部署包 | 入口 | ADK 版本 | 作用 |
|--------|------|----------|------|
| `cloud_agent/` | `cloud_agent.py` → `agent.py` | `google-adk>=2.3.0` | REST 包装函数作 Tool，经 ngrok 调本地 RPA |
| `cloud_agent_mcp/` | `cloud_agent_mcp.py` → `agent.py` | `google-adk>=2.3.0` | SkillToolset + McpToolset，经 MCP 调本地 RPA |

两条路径共享同一套 RPA 能力（`main.py`），区别在**协议与编排方式**。

```
┌─────────────────────────────────────────────────────────────────┐
│  GCP Agent Engine (adk deploy agent_engine)                      │
│  ┌─────────────────────┐    ┌──────────────────────────────┐  │
│  │ cloud_agent         │    │ cloud_agent_mcp               │  │
│  │ Agent + 3×REST fn   │    │ Agent + SkillToolset          │  │
│  │ + PreloadMemoryTool │    │ + McpToolset + PreloadMemory  │  │
│  └──────────┬──────────┘    └──────────────┬───────────────┘  │
└─────────────┼──────────────────────────────┼────────────────────┘
              │ NGROK_URL :8001              │ MCP_SERVER_URL :8002
              ▼                              ▼
       local_node/server.py          mcp_server/bilibili_mcp.py
              └──────────────┬───────────────┘
                             ▼
                        main.py (RPA)
```

---

## 2. 本项目涉及的 ADK 概念速查

| 概念 | 本项目用法 | 代码位置 |
|------|-----------|----------|
| **`Agent`（`LlmAgent`）** | 定义 `root_agent`，挂 model / instruction / tools | `cloud_agent/agent.py`、`cloud_agent_mcp/agent.py` |
| **`root_agent` 导出约定** | ADK CLI 要求模块暴露 `root_agent` | 两个 `agent.py` 末尾 |
| **自定义 Function Tool** | 三个 Python 函数包装 REST API | `cloud_agent/agent.py` |
| **`McpToolset`** | Streamable HTTP 连接本机 MCP Server | `cloud_agent_mcp/agent.py` |
| **`SkillToolset`** | 编排层：`load_skill` + 动态暴露工具 | `cloud_agent_mcp/agent.py` |
| **`load_skill_from_dir`** | 从 `skills/bilibili-rpa/` 加载本地 SOP | `cloud_agent_mcp/agent.py` |
| **`GCPSkillRegistry`** | 对接 GCP Skill Registry | `cloud_agent_mcp/agent.py` |
| **`metadata.adk_additional_tools`** | Skill 激活后才暴露的 MCP 工具名 | `skills/bilibili-rpa/SKILL.md` |
| **`PreloadMemoryTool`** | 每轮预加载 Memory Bank 记忆 | 两个 `agent.py` 的 `tools` / `additional_tools` |
| **`after_agent_callback`** | 会话结束写入 Memory Bank | `generate_memories_callback` |
| **`CallbackContext`** | `add_session_to_memory()` | 同上 |
| **自定义 `Gemini` 模型** | `VertexGemini` 子类，配置代理 httpx | 两个 `agent.py` |
| **`adk run`** | 本地交互调试 Agent | `scripts/run_adk_cloud_agent*.sh` |
| **`adk deploy agent_engine`** | 部署/更新 Reasoning Engine | README / 各 agent README |
| **`.adk/` 会话库** | 本地 `adk run` 会话持久化 | `cloud_agent/.adk/session.db`（gitignore） |

---

## 3. 概念详解 + 项目对照 + 官方文档

### 3.1 安装与项目结构

**本项目：**

```bash
pip install google-adk>=2.3.0   # cloud_agent*/requirements.txt
adk run cloud_agent              # 或 cloud_agent_mcp
adk deploy agent_engine cloud_agent --project=... --region=...
```

**官方文档：**

| 主题 | 链接 |
|------|------|
| ADK 官网（总入口） | https://adk.dev |
| Python 快速入门 | https://adk.dev/get-started/python/ |
| Gemini Enterprise 平台上的 ADK 介绍 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk |
| ADK Python 源码与 Release Notes | https://github.com/google/adk-python |
| ADK 文档仓库 | https://github.com/google/adk-docs |
| Google 开发者博客：ADK 发布说明 | https://developers.googleblog.com/en/agent-development-kit-easy-to-build-multi-agent-applications/ |

> **版本说明**：本项目使用 ADK **2.3.x**（`Agent` + Toolset 模型）。ADK 2.0 起事件模型与会话 schema 有破坏性变更，学习时请以 2.x 文档为准。

---

### 3.2 `Agent`（LLM Agent）

Agent 是 ADK 的「大脑」：绑定模型、系统指令（`instruction`）、工具列表（`tools`），由 LLM 决定何时调用哪个工具。

**本项目 REST Agent 定义：**

```330:337:cloud_agent/agent.py
root_agent = Agent(
    name="Bilibili_Cloud_ADK_Agent",
    model=vertex_model,
    description="通过 REST API（P0 envelope）调用本地 Bilibili RPA 节点",
    instruction=system_instruction,
    tools=adk_tools,
    after_agent_callback=generate_memories_callback,
)
```

**本项目 MCP Agent 定义：**

```206:213:cloud_agent_mcp/agent.py
root_agent = Agent(
    name="Bilibili_Cloud_MCP_Agent",
    model=vertex_model,
    description="Skill 编排 + MCP 调用本地 Bilibili RPA（P0 envelope）",
    instruction=system_instruction,
    tools=[skill_toolset],
    after_agent_callback=generate_memories_callback,
)
```

**官方文档：**

| 主题 | 链接 |
|------|------|
| LLM Agent 概念 | https://adk.dev/agents/llm-agents/ |
| 模型与认证（Vertex / Gemini） | https://adk.dev/models/ |
| 多 Agent 编排（本项目未用，扩展阅读） | https://adk.dev/agents/multi-agents/ |

---

### 3.3 自定义 Function Tools（REST 路径）

将普通 Python 函数放进 `tools=[...]`，ADK 自动根据**函数名、类型注解、docstring** 生成 LLM 可见的 tool schema。

**本项目三个 REST 工具：**

- `get_up_list_from_node` → `GET {NGROK_URL}/api/get_up_list`
- `fetch_fans_data_from_node` → `POST .../fetch_fans_data`
- `write_excel_to_node` → `POST .../write_excel`

均返回统一 **P0 envelope** `{ ok, tool, data, error, meta }`。

**官方文档：**

| 主题 | 链接 |
|------|------|
| 自定义 Function Tools | https://adk.dev/tools-custom/function-tools/ |
| Tool 总览 | https://adk.dev/tools/ |
| Codelab：多工具 Agent | https://codelabs.developers.google.com/multi-tool-ai-agent-adk |

---

### 3.4 `McpToolset`（MCP 路径）

`McpToolset` 连接外部 MCP Server，动态发现工具并暴露给 Agent。本项目使用 **Streamable HTTP** 传输，经 ngrok 或本机 `127.0.0.1:8002` 访问。

```143:151:cloud_agent_mcp/agent.py
bilibili_mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=MCP_SERVER_URL,
        headers={"ngrok-skip-browser-warning": "true"},
        timeout=30.0,
        sse_read_timeout=180.0,
    ),
    tool_filter=["get_up_list", "fetch_fans_data", "write_excel"],
)
```

**官方文档：**

| 主题 | 链接 |
|------|------|
| MCP 集成示例（Supermetrics） | https://adk.dev/integrations/supermetrics/ |
| TypeScript `MCPToolset` API 参考 | https://adk.dev/api-reference/typescript/classes/MCPToolset.html |
| Java `McpToolset` API 参考 | https://adk.dev/api-reference/java/com/google/adk/tools/mcp/McpToolset.html |

> Python 侧用法与 TypeScript/Java 文档中的概念一致：`connection_params` + 可选 `tool_filter`。

---

### 3.5 Skill Registry + `SkillToolset`（MCP 路径编排层）

Skill 是**可版本化的 SOP 包**（`SKILL.md` + `references/`），不含可执行代码。ADK 通过 `SkillToolset` 提供 `search_skills` / `load_skill` 内置工具，按用户意图加载工作流说明，并通过 `metadata.adk_additional_tools` **按需激活**关联的 MCP 工具。

**本项目 Skill 包：** `skills/bilibili-rpa/SKILL.md`

```14:20:skills/bilibili-rpa/SKILL.md
  adk_additional_tools:
    - get_up_list
    - fetch_fans_data
    - write_excel
    - get_up_list_from_node
    - fetch_fans_data_from_node
    - write_excel_to_node
```

**本项目 SkillToolset 组装：**

```156:163:cloud_agent_mcp/agent.py
bilibili_skill = load_skill_from_dir(_resolve_skill_dir())
gcp_skill_registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)

skill_toolset = SkillToolset(
    skills=[bilibili_skill],
    registry=gcp_skill_registry,
    additional_tools=[bilibili_mcp_toolset, PreloadMemoryTool()],
)
```

**GCP 侧治理（非 ADK 库，但配套）：** 根目录 `skill_registry.py`（`agentplatform` SDK）。

**官方文档：**

| 主题 | 链接 |
|------|------|
| **ADK × Skill Registry 集成（核心）** | https://adk.dev/integrations/skills-registry/ |
| GCP：创建和管理技能 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/create-manage |
| GCP：创建和管理技能（中文） | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/create-manage?hl=zh-cn |
| GCP：将技能附加到智能体 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents/create-manage#create-attach-skills |

**项目内延伸阅读：** [`update.md`](update.md)、[`skills/README.md`](skills/README.md)

---

### 3.6 Memory Bank + `PreloadMemoryTool`

`PreloadMemoryTool` 在**每轮对话开始**自动检索 Memory Bank，把用户偏好注入 system instruction。`after_agent_callback` 里调用 `add_session_to_memory()` 把本轮会话沉淀为长期记忆。

```294:296:cloud_agent/agent.py
async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None
```

部署到 Agent Engine 后，ADK 默认使用 **`VertexAiMemoryBankService`**；本地 `adk run` 默认用内存实现。

**官方文档：**

| 主题 | 链接 |
|------|------|
| Memory Bank × ADK 快速入门 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/adk-quickstart |
| Memory Bank 设置 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/setup |
| 开发 ADK Agent（含 PreloadMemoryTool 示例） | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-adk-agent |
| 使用已部署的 ADK Agent（含记忆 API） | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent |

---

### 3.7 Vertex AI 模型与网络代理

本项目不直接用字符串 `"gemini-2.5-pro"`，而是子类化 `google.adk.models.Gemini`，注入带代理的 `google.genai.Client`（`vertexai=True`），解决国内环境访问 Vertex 的问题。详见 `VertexGemini` 与 `scripts/run_adk_cloud_agent.sh` 中的 `VERTEX_HTTP_PROXY` 处理。

**官方文档：**

| 主题 | 链接 |
|------|------|
| ADK 模型与认证 | https://adk.dev/models/ |
| 连接 Google Cloud / Agent Platform | https://adk.dev/deploy/connect-to-google-cloud/ |

---

### 3.8 本地运行：`adk run`

| 命令 | 本项目用途 |
|------|-----------|
| `adk run cloud_agent` | 本地调试 REST Agent（需 `local_node/server.py`） |
| `adk run cloud_agent_mcp` | 本地调试 MCP Agent（需 `bilibili_mcp.py --http`） |

**推荐脚本（处理代理环境变量）：**

- `./scripts/run_adk_cloud_agent.sh`
- `./scripts/run_adk_cloud_agent_mcp.sh`

---

### 3.9 部署到 Agent Runtime：方式全景

> **导读说明**：此前版本只写了本项目在用的 `adk deploy agent_engine`（源文件部署）。实际上 Agent Runtime 支持多种部署路径；下表为官方完整选项，并标明与本项目的关系。

#### 3.9.1 部署目标：三种「运行时」别混淆

| 目标 | CLI 命令 | 特点 | 与本项目 |
|------|----------|------|----------|
| **Agent Engine / Agent Runtime**（托管 Reasoning Engine） | `adk deploy agent_engine` | 托管扩缩容、Session、Memory Bank、Playground | ✅ **当前用法** |
| **Cloud Run** | `adk deploy cloud_run` | 自建容器跑 ADK API Server，你管 Dockerfile | ❌ 未用 |
| **GKE** | `adk deploy gke` | Kubernetes 集群部署 | ❌ 未用 |

Agent Engine 与 Agent Runtime 在文档中常混用：本项目部署的是 **Vertex AI Reasoning Engine**（控制台称 Agent Engine），运行在 **Agent Platform Agent Runtime** 托管环境上。

#### 3.9.2 部署到 Agent Runtime 的六种载荷方式

官方 [Deploy an agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent) 列出以下路径（**不限于源文件**）：

| 方式 | 说明 | 典型入口 | 适用场景 |
|------|------|----------|----------|
| **① 源文件（Source）** | 打包本地 `agent.py` + `requirements.txt` 上传，平台构建 | `adk deploy agent_engine cloud_agent` 或 SDK `source_packages` | 快速迭代、CI/CD、**本项目** |
| **② Dockerfile** | 本地带 `Dockerfile`，平台按 Dockerfile 构建 | SDK：`source_packages` + `image_spec: {}` | 需自定义系统依赖、`installation_scripts` |
| **③ 容器镜像（BYOC）** | 自带已构建镜像 URI（Artifact Registry） | SDK：`container_spec.image_uri` | 私有依赖、完全掌控构建、降低部署延迟 |
| **④ Developer Connect** | 从已关联的 Git 仓库拉代码部署 | SDK：`developer_connect_source` | 团队 Git 工作流、原生 CI/CD |
| **⑤ Agent 对象** | 内存中的 `AdkApp` / agent 对象直接上传 | SDK：`client.agent_engines.create(agent=adk_app)` | Colab 交互式、简单原型 |
| **⑥ Agents CLI** | 一键搭好 GCP 环境 + IaC + 流水线 | [Agents CLI 加速路径](https://adk.dev/deploy/agent-runtime/) | 成熟生产、要完整平台治理 |

**BYOC（Bring Your Own Container）** 即上表 **③**：镜像需推到 Artifact Registry，部署时只传 `image_uri`，不再由平台从源码现场 `pip install`。

```python
# BYOC 示例（Python SDK，非本项目默认路径）
remote_agent = client.agent_engines.create(
    config={
        "display_name": "byoc_agent",
        "container_spec": {"image_uri": "us-central1-docker.pkg.dev/PROJECT/REPO/image:tag"},
        "agent_framework": "google-adk",
        "class_methods": [...],  # stream_query 等
    },
)
```

Codelab 逐步教程：[Deploy your containerized agent on Agent Runtime](https://codelabs.developers.google.com/codelabs/agent-runtime-deploy-containerized-agent)

#### 3.9.3 本项目用的：源文件 + `adk deploy agent_engine`

```bash
# REST Agent（更新已有 Engine）
adk deploy agent_engine cloud_agent \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili-Cloud-Agent" \
  --agent_engine_id=$REST_AGENT_ENGINE_ID

# MCP + Skill Agent
adk deploy agent_engine cloud_agent_mcp \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud MCP Agent" \
  --agent_engine_id=$MCP_AGENT_ENGINE_ID
```

**源文件部署时平台上发生什么**（简化）：

```
cloud_agent/ 或 cloud_agent_mcp/
  ├── agent.py          ← root_agent 定义
  ├── requirements.txt  ← google-adk>=2.3.0 等
  └── skills/...        ← MCP 包内 Skill 副本（仅 mcp 路径）
        │
        ▼  adk deploy agent_engine
  打包 tarball → 上传 GCS → 平台构建容器 → 注册 Reasoning Engine
        │
        ▼
  本地生成 cloud_agent_*_tmp*（gitignore，勿手改）
```

**源文件部署的限制**（官方与社区共识）：

- 依赖只能来自 `requirements.txt` + 同包源码；**不能**在构建阶段自定义 `pip` 私有源（私有包需 vendoring 或改 BYOC / `adk deploy cloud_run`）
- Python 部署**不含** ADK Web UI；API Server 由 Runtime 提供
- `source_packages` 打包上限约 **8MB**（SDK 直传时）

#### 3.9.4 何时考虑从源文件换成 BYOC / Cloud Run？

| 需求 | 建议路径 |
|------|----------|
| 当前演示、改 `agent.py` 即 redeploy | 保持 **源文件 + agent_engine**（本项目） |
| 私有 PyPI / Artifact Registry Python 包 | **BYOC** 或 `adk deploy cloud_run` + 自定义 Dockerfile |
| 要完全控制 API Server / 系统包 | **Dockerfile** 或 **BYOC** |
| 团队 Git + 自动发布 | **Developer Connect** 或 CI 调 SDK `source_packages` |
| 不要 Vertex 托管、只要容器 | **Cloud Run** / **GKE**（自行管 Session/Memory） |

#### 3.9.5 部署相关官方文档索引

| 主题 | 链接 |
|------|------|
| **部署总览（六种方式）** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent |
| ADK → Agent Runtime 导读 | https://adk.dev/deploy/agent-runtime/ |
| ADK → Agent Engine CLI | https://adk.dev/deploy/agent-engine/ |
| ADK CLI 完整参考（含 cloud_run / gke） | https://adk.dev/api-reference/cli/ |
| 开发 ADK Agent（AdkApp、Memory） | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-adk-agent |
| 使用已部署 Agent（query / session API） | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent |
| **BYOC Codelab** | https://codelabs.developers.google.com/codelabs/agent-runtime-deploy-containerized-agent |
| Runtime 资源调优 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/optimize-scale |
| 连接 Google Cloud / ADC | https://adk.dev/deploy/connect-to-google-cloud/ |

**本项目 Playground（已部署实例）：**

| Agent | Engine ID | Playground |
|-------|-----------|------------|
| REST `cloud_agent` | `$REST_AGENT_ENGINE_ID` | Console → Agent Engine Playground |
| MCP `cloud_agent_mcp` | `$MCP_AGENT_ENGINE_ID` | Console → Agent Engine Playground |

---

### 3.10 会话与本地调试

- 本地 `adk run` 会在项目下生成 `.adk/session.db`（已 gitignore）
- `adk deploy` 会生成 `cloud_agent_*_tmp*` 临时目录（已 gitignore），**不要手动编辑**
- 可选：`adk web` 启动 Web UI 调试（仅开发用，本项目未作为主路径）

**官方文档：**

| 主题 | 链接 |
|------|------|
| 会话（Sessions） | https://adk.dev/sessions/ |
| ADK Web（开发调试 UI） | https://adk.dev/get-started/python/ （Quickstart 中的 `adk web` 小节） |

---

## 4. 两条 Agent 路径的 ADK 设计对比

| 维度 | `cloud_agent`（REST） | `cloud_agent_mcp`（MCP + Skill） |
|------|----------------------|----------------------------------|
| 工具类型 | 3 个 Python 函数 | `SkillToolset`（内含 `McpToolset`） |
| 工作流来源 | `system_instruction` 硬编码 | `load_skill('bilibili-rpa')` + `SKILL.md` |
| Skill Registry | 未 attach | `GCPSkillRegistry` + 本地目录兜底 |
| 本地协议 | HTTP REST `:8001` | MCP Streamable HTTP `:8002` |
| Engine ID | `$REST_AGENT_ENGINE_ID` | `$MCP_AGENT_ENGINE_ID` |
| 推荐场景 | Widget、简单 REST 集成 | 标准 MCP、可治理 SOP、工具动态启用 |

学习建议：**先读 REST 路径**（概念更少），再读 MCP + Skill 路径（编排与治理更完整）。

---

## 5. 推荐学习路径（约 2–3 天）

### 第 1 步：环境与最小 Agent（0.5 天）

1. 阅读 [Python Quickstart](https://adk.dev/get-started/python/)
2. 本地跑通：`./scripts/run_adk_cloud_agent.sh`（先起 `local_node/server.py`）
3. 对照 `cloud_agent/agent.py` 理解 `Agent` + Function Tool

### 第 2 步：工具与 MCP（0.5–1 天）

1. 阅读 [Function Tools](https://adk.dev/tools-custom/function-tools/)
2. 阅读 [MCP 集成示例](https://adk.dev/integrations/supermetrics/)，对照 `cloud_agent_mcp/agent.py`
3. 本地跑通：`python mcp_server/bilibili_mcp.py --http` + `./scripts/run_adk_cloud_agent_mcp.sh`

### 第 3 步：Skill Registry（0.5 天）

1. 阅读 [ADK × Skills Registry](https://adk.dev/integrations/skills-registry/)
2. 阅读 `skills/bilibili-rpa/SKILL.md` 与 [`update.md`](update.md)
3. 练习：`python skill_registry.py list` / `validate`

### 第 4 步：记忆与部署（0.5–1 天）

1. 阅读 [Memory Bank ADK Quickstart](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/adk-quickstart)
2. 理解 `PreloadMemoryTool` + `after_agent_callback`
3. 阅读 [Deploy an agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent)（对比源文件 vs BYOC vs Git）
4. 对本项目执行 `adk deploy agent_engine cloud_agent ...`；在 Playground 验证

### 第 5 步：项目实战串联

按 [`user_guide.md`](user_guide.md) 场景三（REST）→ 场景五（MCP）完整走一遍。

---

## 6. 官方文档索引（按主题）

### 入门与总览

- https://adk.dev
- https://adk.dev/get-started/python/
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk
- https://github.com/google/adk-python
- https://github.com/google/adk-docs

### Agent 与工具

- https://adk.dev/agents/llm-agents/
- https://adk.dev/tools/
- https://adk.dev/tools-custom/function-tools/
- https://adk.dev/models/

### 集成（本项目相关）

- https://adk.dev/integrations/skills-registry/
- https://adk.dev/integrations/supermetrics/ （McpToolset 范例）
- https://adk.dev/deploy/connect-to-google-cloud/

### 部署与运行时

- https://adk.dev/api-reference/cli/ （`agent_engine` / `cloud_run` / `gke`）
- https://adk.dev/deploy/agent-runtime/
- https://adk.dev/deploy/agent-engine/
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent （**源文件 / Dockerfile / BYOC / Git** 全景）
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-adk-agent
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/optimize-scale
- https://codelabs.developers.google.com/codelabs/agent-runtime-deploy-containerized-agent （**BYOC**）

### Memory Bank

- https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/setup
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/adk-quickstart

### Skill Registry（GCP 平台文档）

- https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/create-manage
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/create-manage?hl=zh-cn
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents/create-manage#create-attach-skills

### 会话

- https://adk.dev/sessions/

---

## 7. 项目内文档交叉引用

| 文档 | 内容 |
|------|------|
| [`user_guide.md`](user_guide.md) | 全场景操作：adk run、Playground、端口、排错 |
| [`cloud_agent/README.md`](cloud_agent/README.md) | REST Agent 部署与 Vertex 代理排错 |
| [`cloud_agent_mcp/README.md`](cloud_agent_mcp/README.md) | MCP + Skill 三层集成 |
| [`skills/README.md`](skills/README.md) | Skill 资产与 `adk_additional_tools` |
| [`update.md`](update.md) | Skill Registry 集成变更记录 |
| [`feat.md`](feat.md) | REST/MCP 双轨与 P0 envelope |
| [`mcp_server/README.md`](mcp_server/README.md) | MCP Server（ADK 的「被调用方」） |

---

## 8. 常见问题（ADK 相关）

| 现象 | 原因 | 处理 |
|------|------|------|
| `adk run` 输入即 `httpx.ConnectError` | 连 Vertex 失败（非 REST 节点问题） | 设 `VERTEX_HTTP_PROXY`，用 `run_adk_cloud_agent*.sh` |
| Agent 调不到本地 RPA | ngrok 未起或 `.env` 域名过期 | 更新 `NGROK_URL` / `MCP_SERVER_URL` |
| MCP Agent 无 RPA 工具 | 未 `load_skill` 或 MCP Server 未运行 | 按 instruction 先 load skill；起 `:8002` |
| 改了 Skill 云端未生效 | 未 `skill_registry.py update` + redeploy | 同步三处：`skills/`、部署包副本、`adk deploy` |
| `adk deploy` 生成 tmp 目录 | CLI 正常行为 | 勿手改；改源目录后重新 deploy |

---

*文档生成自 SmartAgents 代码库与 Google ADK 官方文档（截至 2026-07）。若官方链接迁移，以 https://adk.dev 站内导航为准。*
