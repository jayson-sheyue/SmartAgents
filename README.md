# SmartAgents

多领域 **RPA + ADK Agent** 演示项目：B 站粉丝采集、Etsy 评论导出，经 **调度树（Dispatcher + 子 Agent）** 或 **单领域 Agent** 接入；支持本地 `adk run`、云端 Agent Engine、飞书群聊、Web Widget。

> **从哪开始？** 看下方 [模块地图](#模块地图) 选场景 → 点进对应 README。  
> **全场景操作手册**（勾选清单 + 命令矩阵）：[`user_guide.md`](user_guide.md)  
> **ADK 概念与部署全景**：[`docs/adk_learning_guide.md`](docs/adk_learning_guide.md)

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│ L4 入口                                                                  │
│  integrations/feishu/     飞书长连接 Bridge → local/cloud 双通道         │
│  local_node/widget_server.py :8000   Web Widget → local/cloud 调度树     │
│  GCP Agent Engine Playground          → 云端 Agent + Cloudflare Tunnel   │
├─────────────────────────────────────────────────────────────────────────┤
│ L3 编排                                                                  │
│  smart_agents/            调度树（小智 + 阿B + E姐）+ App（记忆/压缩）      │
│  bilibili_agent/          B 站本地进程内 Agent（无 HTTP）                 │
│  bilibili_cloud_agent*    B 站单领域 Agent（REST 或 MCP）                 │
│  etsy_agent/              Etsy 本地进程内 Agent（无 HTTP）                │
│  etsy_cloud_agent*        Etsy 单领域 Agent（REST 或 MCP）                │
│  skills/ + skill_registry.py   Skill 资产与 GCP Registry                 │
├─────────────────────────────────────────────────────────────────────────┤
│ L2 协议                                                                  │
│  local_node/server.py     REST :8001（单领域 REST Agent）                │
│  mcp_server/              MCP :8002（B 站）/ :8003（Etsy）               │
├─────────────────────────────────────────────────────────────────────────┤
│ L1 执行                                                                  │
│  bilibili_agent/bilibili_tools.py   B 站 Playwright RPA                  │
│  etsy_agent/etsy_tools.py           Etsy Open API + Excel                │
└─────────────────────────────────────────────────────────────────────────┘
```

**原则**：RPA / 凭证 / 浏览器留在 **本机**；云端只跑 **LLM + 编排**，经 **Cloudflare Tunnel** 或 **127.0.0.1** 调本地 MCP/REST。

**记忆与会话**（仅调度树 `smart_agents`）：

| 能力 | 谁有 | 说明 |
|------|------|------|
| Session（短期） | 全部入口 | 按 `session_id` 隔离；飞书按群/私聊 |
| Memory Bank（长期） | **仅小智** | `PreloadMemoryTool` + `LoadMemoryTool`；飞书 `user_id=feishu_{open_id}` 跨群共享 |
| 联网搜索 | **仅小智** | `GoogleSearchTool` |
| 知识库 RAG | **仅小智** | `rag_search` → Vertex RAG Engine corpus（`RAG_ENABLED=true`） |
| Session 事件压缩 | 云端 `app` | `app_factory.py` + `EventsCompactionConfig` |
| Widget | 无 Memory / 无 RAG 专属配置 | 匿名 `web_{uuid}`；云端模式可复用小智工具 |

云端部署调度树须 `--adk_app_object=app`（见 [`scripts/deploy_smart_agents.sh`](scripts/deploy_smart_agents.sh)），`adk run` 仅加载 `root_agent`，不含 Plugin / 压缩。

---

## 模块地图

### 按领域

| 领域 | L1 工具 | L2 协议 | L3 单领域 Agent | L3 调度树中的子 Agent |
|------|---------|---------|-----------------|----------------------|
| **B 站** | [`bilibili_agent/bilibili_tools.py`](bilibili_agent/bilibili_tools.py) | [`mcp_server/bilibili_mcp.py`](mcp_server/bilibili_mcp.py) · [`local_node/server.py`](local_node/server.py) | [`bilibili_agent/`](bilibili_agent/) 进程内 · [`bilibili_cloud_agent/`](bilibili_cloud_agent/) REST · [`bilibili_cloud_agent_mcp/`](bilibili_cloud_agent_mcp/) MCP | `smart_agents` → 阿B |
| **Etsy** | [`etsy_agent/etsy_tools.py`](etsy_agent/etsy_tools.py) | [`mcp_server/etsy_mcp.py`](mcp_server/etsy_mcp.py) · `local_node` Etsy 路由 | [`etsy_agent/`](etsy_agent/) 进程内 · [`etsy_cloud_agent/`](etsy_cloud_agent/) REST · [`etsy_cloud_agent_mcp/`](etsy_cloud_agent_mcp/) MCP | `smart_agents` → E姐 |
| **调度 + 入口** | — | Widget `:8000` | [`smart_agents/`](smart_agents/) | [`integrations/feishu/`](integrations/feishu/) · [`local_node/widget_server.py`](local_node/widget_server.py) |

### 按 README 索引

| 你想… | 文档 |
|--------|------|
| **总览与选路** | 本文 |
| **一键脚本说明** | [`scripts/README.md`](scripts/README.md) |
| **全场景操作手册** | [`user_guide.md`](user_guide.md)（§1 速查 · §2–3 单域 · §4 调度树 · §5 飞书 · §6 部署 · §10 RAG） |
| **ADK 学习与官方链接** | [`docs/adk_learning_guide.md`](docs/adk_learning_guide.md) |
| 本地测 B 站 RPA（无 Agent） | [`scripts/test_p0_local.py`](scripts/test_p0_local.py) |
| Cursor MCP（stdio） | [`.cursor/README.md`](.cursor/README.md) · [`mcp_server/README.md`](mcp_server/README.md) |
| B 站本地进程内 Agent | [`bilibili_agent/README.md`](bilibili_agent/README.md) |
| B 站 REST / MCP 云端 Agent | [`bilibili_cloud_agent/README.md`](bilibili_cloud_agent/README.md) · [`bilibili_cloud_agent_mcp/README.md`](bilibili_cloud_agent_mcp/README.md) |
| Etsy 本地 / REST / MCP | [`etsy_agent/README.md`](etsy_agent/README.md) · [`etsy_cloud_agent/README.md`](etsy_cloud_agent/README.md) · [`etsy_cloud_agent_mcp/README.md`](etsy_cloud_agent_mcp/README.md) |
| **整棵调度树** | [`smart_agents/README.md`](smart_agents/README.md) |
| 飞书群聊入口 | [`integrations/feishu/README.md`](integrations/feishu/README.md) · [`integrations/README.md`](integrations/README.md) |
| Web 聊天 Widget | [`local_node/README.md`](local_node/README.md) |
| Skill 管理与 Registry | [`skills/README.md`](skills/README.md) |

---

## 快速选路：测什么、跑哪条命令

| 目标 | 本地依赖 | 命令 |
|------|----------|------|
| B 站 RPA 直测 | — | `python scripts/test_p0_local.py` |
| B 站 **单 Agent** 进程内 | `python -m bilibili_agent login` + Excel | `./scripts/run_adk_bilibili_agent.sh` |
| B 站 **单 Agent** MCP | `bilibili_mcp.py --http` :8002 | `./scripts/run_adk_bilibili_cloud_agent_mcp.sh` |
| B 站 **单 Agent** REST | `local_node/server.py` :8001 | `./scripts/run_adk_bilibili_cloud_agent.sh` |
| Etsy **单 Agent** MCP | `etsy_mcp.py --http` :8003 | `./scripts/run_adk_etsy_cloud_agent_mcp.sh` |
| Etsy **单 Agent** REST | `local_node/server.py` :8001 | `./scripts/run_adk_etsy_cloud_agent.sh` |
| Etsy 进程内 | `.env` Etsy 凭证 | `./scripts/run_adk_etsy_agent.sh` |
| **整棵调度树**（本机） | 双 MCP :8002 + :8003 | `./scripts/run_adk_smart_agents.sh` |
| 飞书 → 调度树 | 双 MCP + Bridge | `./scripts/run_feishu_smart_agents.sh` |
| Web Widget | 双 MCP + `widget_server.py` | `./scripts/run_widget.sh` 或 `python local_node/widget_server.py` |
| 云端 Playground / Widget cloud / 飞书 cloud | 上表 MCP + **隧道** + **deploy** | `./scripts/deploy_smart_agents.sh` |

**端口速记**：REST `:8001`（仅单领域 REST Agent）· B 站 MCP `:8002` · Etsy MCP `:8003` · Widget `:8000`。调度树 / Widget cloud / 飞书 cloud **走 MCP，不走 :8001**。

---

## 目录结构（命名约定）

与 Etsy 对齐：**`{领域}_cloud_agent`（REST）**、**`{领域}_cloud_agent_mcp`（MCP）**。

```
SmartAgents/
├── README.md
├── user_guide.md                  ← 操作手册（首选实操文档）
├── docs/adk_learning_guide.md     ← ADK 概念导读
├── requirements.txt
├── skill_registry.py
├── rpa_tools.py                   ← 兼容 re-export（REST/MCP 调用链）
│
├── bilibili_agent/                ← B 站本地 ADK（进程内工具）
├── bilibili_cloud_agent/          ← B 站 REST + Skill
├── bilibili_cloud_agent_mcp/      ← B 站 MCP + Skill
├── etsy_agent/
├── etsy_cloud_agent/
├── etsy_cloud_agent_mcp/
├── smart_agents/                  ← 调度树 + app_factory + rag_tools + skills 副本
│
├── local_node/                    ← REST :8001 + Widget :8000
├── mcp_server/                    ← bilibili_mcp :8002 · etsy_mcp :8003
├── skills/                        ← Skill 源（bilibili-rpa · etsy-review）
├── integrations/feishu/           ← 飞书 Bridge
├── scripts/                       ← 启动与 deploy 脚本
└── .env.example
```

**不要手改** `*_tmp*` 部署临时目录（`.gitignore` 已忽略）。

---

## Reasoning Engine ID（`.env`）

| Agent 包名 | 环境变量 | 本地工具依赖 |
|------------|----------|--------------|
| `bilibili_cloud_agent` | `BILIBILI_REST_AGENT_ENGINE_ID` | `local_node` :8001 |
| `bilibili_cloud_agent_mcp` | `BILIBILI_MCP_AGENT_ENGINE_ID` | `bilibili_mcp` :8002 |
| `etsy_cloud_agent` | `ETSY_REST_AGENT_ENGINE_ID` | `local_node` :8001 |
| `etsy_cloud_agent_mcp` | `ETSY_MCP_AGENT_ENGINE_ID` | `etsy_mcp` :8003 |
| `smart_agents` | `SMART_AGENTS_ENGINE_ID` | 双 MCP :8002 + :8003 |

---

## 环境准备（最短路径）

```bash
python3 -m venv .venvAgents && source .venvAgents/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # 填入 GCP、凭证、Engine ID 等
gcloud auth application-default login
python -m bilibili_agent login   # B 站登录态 → bilibili_state.json
```

新手推荐路径见 [`user_guide.md` §8](user_guide.md#8-建议新手的最短路径)。

---

## 升级改造（改哪一层）

| 需求 | 先改 | 再改 |
|------|------|------|
| B 站抓取逻辑 | `bilibili_agent/bilibili_tools.py` | `mcp_server/` · `local_node/` |
| Etsy API | `etsy_agent/etsy_tools.py` | MCP / REST 暴露层 |
| 工作流 SOP | `skills/*/SKILL.md` | `skill_registry.py update` · 同步部署包 |
| 调度人格 / 路由 / 搜索 | `smart_agents/personas.py` · `agent.py` | `./scripts/deploy_smart_agents.sh` |
| 知识库 RAG | 控制台建 corpus + `.env` `RAG_*` · `rag_tools.py` | redeploy |
| 飞书忠诚护栏 | `integrations/feishu/message_utils.py` · `.env` `FEISHU_OWNER_*` | 重启 Bridge |
| 记忆刷写 | `smart_agents/memory_ingest.py` · `callbacks.py` · Feishu `agent_client.py` | redeploy + 重启 Bridge |
| Session 压缩参数 | `.env` `SMART_AGENTS_COMPACTION_*` | redeploy |
| 单领域云端行为 | `*_cloud_agent*` | `adk deploy` |
| 隧道换域名 | `.env` MCP URL + `*_TUNNEL_HOST` | 重启 MCP → redeploy `smart_agents` |

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [`user_guide.md`](user_guide.md) | 场景速查、逐步清单、部署、排错 |
| [`docs/adk_learning_guide.md`](docs/adk_learning_guide.md) | ADK 概念、多 Agent、Memory、RAG、部署方式全景 |
| [`skills/README.md`](skills/README.md) | Skill 资产与 GCP Registry |
| [`integrations/feishu/README.md`](integrations/feishu/README.md) | 飞书双通道、记忆、护栏、Session 映射 |
