# SmartAgents

多领域 **Google ADK Agent**：调度树 **小智** + 阿B / E姐 / 小飞。MCP 跑在 **Cloud Run**；TSE 工作台、飞书入站、Widget 经 Agent Engine 调公网 MCP。

TSE 生产入口是独立仓库 **TSE Smart Workspace**（侧栏同域代理本调度树，`CHAT_BACKEND=smart_agents`），不是本机 Widget。

> **第一次来？** 部署三 MCP（B 站 / Etsy / 飞书）→ 写 `.env` URL → [`user_guide.md`](user_guide.md) / `./scripts/deploy_smart_agents.sh`。

---

## 这个项目做什么

| 领域 | 专家人格 | 能力 |
|------|----------|------|
| **调度** | 小智 | 接待、搜索、RAG、TSE 工具、Code Exec、Task Card；转交专家 |
| **飞书** | 小飞 | 日历 / 云文档 / 多维表格 / IM（用户 OAuth + Bot） |
| **TSE** | 小智工具 | 查跟进/日报、语义问答、大盘、映射多维表格、分布图 |
| **B 站** | 阿B | 全站热门选品；Excel 可选写 GCS |
| **Etsy** | E姐 | 评论采集 + 上架素材同步生图 |

**设计原则**：领域工具在 **Cloud Run MCP**；编排在 Agent Engine / `adk run`。TSE 业务数据走确定性工具 + External API，不靠裸 Firestore MCP 答日报问题。

---

## 架构总览

```
┌──────────────────────────────────────────────────────────────────────────┐
│ L4 用户入口                                                               │
│   TSE Smart Workspace 侧栏   同域 API → Agent Engine（生产主入口）        │
│   integrations/feishu/       飞书入站 → Engine / local runner             │
│   local_node/widget :8000    调试用 Web 聊天页                            │
├──────────────────────────────────────────────────────────────────────────┤
│ L3 Agent 编排（ADK）                                                       │
│   小智 + Task Card；子 Agent：阿B / E姐 / 小飞                             │
│   skills: feishu-ops · tse-to-bitable · bilibili-trend · etsy-*           │
├──────────────────────────────────────────────────────────────────────────┤
│ L2 Cloud Run MCP                                                           │
│   feishu-mcp · bilibili-mcp · etsy-mcp                                    │
├──────────────────────────────────────────────────────────────────────────┤
│ L1 domains/ + TSE Firestore/API + Vertex RAG + GCS                         │
└──────────────────────────────────────────────────────────────────────────┘
```

**调用链**：

```
TSE 工作台 / 飞书 / Widget
  → 小智（Gemini / Vertex）
       │ transfer_to_agent
       ▼
     小飞 / 阿B / E姐 → Cloud Run MCP
```

复合任务用 Session **Task Card** 保主线；TSE 工作台在 transfer 空转或建表未写入时会自动续跑。

### 部署 MCP

```bash
./scripts/deploy_bilibili_mcp_cloudrun.sh
./scripts/deploy_etsy_mcp_cloudrun.sh
./scripts/deploy_feishu_mcp_cloudrun.sh
# 将 URL 写入 .env：BILIBILI_MCP_SERVER_URL / ETSY_MCP_SERVER_URL / FEISHU_MCP_SERVER_URL
# 并设置 MCP_ARTIFACT_GCS_BUCKET=
./scripts/deploy_smart_agents.sh
```

更细的目录约定见 [`docs/domains_architecture.md`](docs/domains_architecture.md)。

---

## 目录结构

```
SmartAgents/
├── README.md                 ← 本文（总览）
├── user_guide.md             ← 操作手册（新人首选实操文档）
├── requirements.txt
├── .env.example              ← 环境变量模板
│
├── domains/                  ← 领域核心（工具 + Agent 构建器）
│   ├── shared/               manifest 解析、MCP 健康检查、Skill 路径
│   ├── bilibili/             manifest、registry、builder、bilibili_tools
│   └── etsy/                 etsy_tools、image_tools、preset_tools、presets/
│
├── bilibili_agent/           ← ADK 包：adk run bilibili_agent
├── etsy_agent/               ← ADK 包：adk run etsy_agent
├── smart_agents/             ← ADK 包：调度树 + app（记忆/压缩）
│
├── mcp_server/               ← MCP HTTP 服务（必须先 --http 启动）
├── skills/                   ← feishu-ops、tse-to-bitable、bilibili-trend、etsy-*
├── integrations/feishu/      ← 飞书入站 Bridge（与小飞出站正交）
├── local_node/               ← Web Widget（:8000，无 REST 节点）
├── env/                      ← local.env 本地覆盖（example 可提交）
├── scripts/                  ← 启动、检查、部署脚本
└── docs/                     ← 架构说明、Agent Platform 学习导读
```

**命名约定**：每个领域只有一个 ADK 包名（`bilibili_agent` / `etsy_agent`），本地与云端 deploy 共用，不再有 `*_cloud_agent` 或 REST 路径。

---

## 端口速记

| 端口 | 服务 | 何时需要 |
|------|------|----------|
| **8002** | B 站 MCP | 调度树或单测阿B |
| **8003** | Etsy MCP | 调度树或单测 E姐 |
| **8004** | 飞书 MCP | 调度树或单测小飞（需 lark-cli） |
| **8000** | Web Widget | 仅调试聊天页；生产走 TSE 工作台 |

本地 MCP 用 `127.0.0.1:8002/8003/8004`，**不需要** Cloudflare 隧道。

---

## 快速选路

| 你想… | 终端 1 | 终端 2 | 终端 3 | 入口命令 |
|--------|--------|--------|--------|----------|
| **只测 B 站** | `python mcp_server/bilibili_mcp.py --http` | — | — | `./scripts/run_adk_bilibili_agent.sh` |
| **只测 Etsy** | `python mcp_server/etsy_mcp.py --http` | — | — | `./scripts/run_adk_etsy_agent.sh` |
| **调度树（小智+三专家）** | 三 MCP | — | — | `./scripts/run_adk_smart_agents.sh` |
| **飞书群聊（入站）** | 三 MCP | `./scripts/run_feishu_smart_agents.sh` | — | 飞书 @机器人 |
| **Web 聊天页（调试）** | 三 MCP | `./scripts/run_widget.sh` | — | `http://127.0.0.1:8000/` |
| **TSE 工作台侧栏** | 云端 Engine 已 deploy | — | — | 工作台 `CHAT_BACKEND=smart_agents` |

**启动前一次性准备**（所有路径共用）：

```bash
cd /path/to/SmartAgents
python3 -m venv .venvAgents && source .venvAgents/bin/activate
pip install -r requirements.txt
playwright install chromium          # B 站需要；仅 Etsy 可后装
cp .env.example .env                 # 填密钥（见 user_guide §0.3）
cp env/local.env.example env/local.env   # 本地覆盖，一般保持默认
gcloud auth application-default login
python -m bilibili_agent login       # 仅 B 站：生成 bilibili_state.json
```

分场景配置见 [`env/README.md`](env/README.md)（**`.env` + `env/local.env` 两层**）。

---

## 模块地图

### 按你想做的事

| 目标 | 文档 |
|------|------|
| **从零跑起来（逐步清单）** | [`user_guide.md`](user_guide.md) |
| **脚本与命令索引** | [`scripts/README.md`](scripts/README.md) |
| **环境文件怎么配** | [`env/README.md`](env/README.md) |
| **架构与加新工具** | [`docs/domains_architecture.md`](docs/domains_architecture.md) |
| **ADK / Agent Platform 概念** | [`docs/agent_platform_learning_guide.md`](docs/agent_platform_learning_guide.md) |
| **TSE 数据 / KC Glossary** | [`docs/tse_data_access.md`](docs/tse_data_access.md) · [`KC-checklist.md`](KC-checklist.md) |
| **TSE 工作台（生产 UI）** | 独立仓库 TSE Smart Workspace；侧栏代理本 Engine |
| **GCP Lab 实验清单** | [`lab.md`](lab.md) |
| B 站单域 Agent | [`bilibili_agent/README.md`](bilibili_agent/README.md) |
| Etsy 单域 Agent | [`etsy_agent/README.md`](etsy_agent/README.md) |
| 调度树 | [`smart_agents/README.md`](smart_agents/README.md) |
| MCP 服务 | [`mcp_server/README.md`](mcp_server/README.md) |
| Skill 资产 | [`skills/README.md`](skills/README.md) |
| 飞书接入 | [`integrations/feishu/README.md`](integrations/feishu/README.md) |
| Web Widget | [`local_node/README.md`](local_node/README.md) |

### 按技术层

| 层 | B 站 | Etsy | 飞书 |
|----|------|------|------|
| L1 工具 | `domains/bilibili/` | `domains/etsy/` | `domains/feishu/` |
| L2 MCP | `:8002` | `:8003` | `:8004` |
| L3 Builder | `build_bilibili_agent` | `build_etsy_agent` | `build_feishu_agent` |
| Skill | `bilibili-trend` | `etsy-review` · `etsy-listing-assets` | `feishu-ops` · `tse-to-bitable` |

---

## 记忆与能力分工（仅调度树）

| 能力 | 小智 | 阿B / E姐 / 小飞 |
|------|:----:|:----------------:|
| Session（短期上下文） | ✅ | ✅（当次任务） |
| Memory Bank（长期） | ✅ | ❌ |
| Google 联网搜索 | ✅ | ❌ |
| 知识库 RAG | ✅（`RAG_ENABLED`） | ❌ |
| TSE 场景工具 | ✅（API / Firestore 工具） | ❌ |
| Task Card | ✅（会话 state，跨专家） | 读写同一张卡 |
| Code Execution / 作图 | ✅ | ❌ |
| MCP 领域工具 | 经 transfer | ✅ |

`adk run` 只加载 `root_agent`，**不含** Memory Plugin / Session 事件压缩；完整记忆能力需云端 `adk deploy ... --adk_app_object=app`（见 `deploy_smart_agents.sh`）。

---

## 环境变量（核心）

| 变量 | 用途 |
|------|------|
| `GCP_PROJECT_ID` / `GCP_LOCATION` | Vertex AI（必填） |
| `BILIBILI_MCP_SERVER_URL` | 默认 `http://127.0.0.1:8002/mcp` |
| `ETSY_MCP_SERVER_URL` | 默认 `http://127.0.0.1:8003/mcp` |
| `FEISHU_MCP_SERVER_URL` | 默认 `http://127.0.0.1:8004/mcp` |
| `ETSY_KEYSTRING` / `ETSY_SHARED_SECRET` | Etsy Open API（MCP 后端读取） |
| `TSE_API_BASE_URL` | TSE 工作台 External API 根地址 |
| `SMART_AGENTS_ENGINE_ID` | 云端 deploy 后填入（工作台 / 飞书 cloud） |
| `SMART_AGENTS_A2A_ENGINE_ID` | 可选：并行 A2A Engine（`deploy_smart_agents_a2a.sh`） |
| `FEISHU_RUN_MODE` | `local`（本机 Runner）或 `cloud`（Agent Engine） |
| `GCP_DATA_MCP_ENABLED` | TSE：KC + Firestore Remote MCP + 确定性工具（可选） |
| `CODE_EXECUTION_ENABLED` | 小智沙箱 Python / TSE 分布图（可选） |
| `TSE_FIRESTORE_PROJECT_ID` / `TSE_FIRESTORE_DATABASE` | TSE Firestore 库（默认 `tse-jayson-database`） |
| `RAG_ENABLED` / `RAG_CORPUS_NAME` | 小智知识库（可选） |

完整列表见 [`.env.example`](.env.example) 与 [`user_guide.md`](user_guide.md) §0。

---

## 改代码时动哪一层

| 需求 | 先改 | 再改 / 重启 |
|------|------|-------------|
| B 站抓取逻辑 | `domains/bilibili/bilibili_tools.py` | 重启 `bilibili_mcp.py` |
| Etsy API / 生图 | `domains/etsy/` 对应模块 | 重启 `etsy_mcp.py` |
| 工作流 SOP | `skills/*/SKILL.md` | redeploy（若 instruction 变） |
| 专家人格 / 路由 | `smart_agents/personas.py` · `agent.py` | redeploy 调度树 |
| TSE 工具 / Glossary | `smart_agents/tse_tools.py` · `KC-checklist.md` | redeploy |
| Task Card / 可交付物 | `smart_agents/task_card.py` | redeploy；TSE 续跑逻辑在工作台 `smart_agents_runtime.py` |
| 飞书出站 MCP | `domains/feishu/` · `skills/feishu-ops` | 重启 `feishu_mcp.py` |
| 飞书入站护栏 | `integrations/feishu/agent_client.py` | 重启 Bridge |
| 新 MCP 工具 | `domains/<domain>/registry.py` + manifest | MCP 自动注册 |

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [`user_guide.md`](user_guide.md) | 前置条件、场景清单、部署、排错 |
| [`docs/domains_architecture.md`](docs/domains_architecture.md) | domains 布局与扩展 |
| [`docs/agent_platform_learning_guide.md`](docs/agent_platform_learning_guide.md) | ADK + Agent Platform 组件导读 |
