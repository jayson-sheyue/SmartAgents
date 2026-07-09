# SmartAgents 操作手册

> 全场景「照着做就能跑」清单 + 命令矩阵。  
> 架构总览：[`README.md`](README.md) · 脚本索引：[`scripts/README.md`](scripts/README.md) · ADK 概念：[`docs/adk_learning_guide.md`](docs/adk_learning_guide.md)

---

## 0) 全局一次性准备（只做一次）

- [ ] 创建并激活虚拟环境
```bash
cd /path/to/SmartAgents
python3 -m venv .venvAgents
source .venvAgents/bin/activate
pip install -r requirements.txt
playwright install chromium
```

- [ ] 配置环境变量
```bash
cp .env.example .env
```

- [ ] 按运行模式填写 `.env`（本地/云端二选一）
```env
# 通用
WIDGET_RUN_MODE=local   # 或 cloud
FEISHU_RUN_MODE=local   # 或 cloud
SMART_AGENTS_ENGINE_ID= # cloud 模式必填（调度树 / Widget cloud / 飞书 cloud）

# AGENT_RESOURCE_NAME=projects/<project-number>/locations/us-central1/reasoningEngines/<engine-id>
# （Widget/飞书 cloud 可显式指定；不填则按 SMART_AGENTS_ENGINE_ID 自动拼接）

# 本地模式（推荐先跑通）
BILIBILI_REST_SERVER_URL=http://127.0.0.1:8001
BILIBILI_MCP_SERVER_URL=http://127.0.0.1:8002/mcp
ETSY_REST_SERVER_URL=http://127.0.0.1:8001
ETSY_MCP_SERVER_URL=http://127.0.0.1:8003/mcp
BILIBILI_TUNNEL_HOST=
ETSY_TUNNEL_HOST=

# 云端 Playground（Cloudflare Quick Tunnel，域名每次重启会变）
# BILIBILI_MCP_SERVER_URL=https://<bilibili-uuid>.trycloudflare.com/mcp
# ETSY_MCP_SERVER_URL=https://<etsy-uuid>.trycloudflare.com/mcp
# BILIBILI_TUNNEL_HOST=<bilibili-uuid>.trycloudflare.com
# ETSY_TUNNEL_HOST=<etsy-uuid>.trycloudflare.com

# 小智知识库 RAG（可选，见 §10）
# RAG_ENABLED=true
# RAG_CORPUS_NAME=projects/<project>/locations/<loc>/ragCorpora/<id>
# RAG_LOCATION=asia-east1
```

- [ ] 完成 GCP ADC 登录
```bash
gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID
```

- [ ] B 站首次登录（仅 B 站相关场景需要）
```bash
python -m bilibili_agent login
```

- [ ] Etsy 凭证写入 `.env`（仅 Etsy 相关场景需要）
```env
ETSY_KEYSTRING=...
ETSY_SHARED_SECRET=...
```

---

## 1) 场景速查（先选你要跑哪条）

> **怎么用这张表**：先完成 [§0](#0-全局一次性准备只做一次)；在下表找到目标行，按「本地终端」列开终端。**云端调度树**统一走 [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用)（先隧道拿域名 → 写 `.env` → 启 MCP → deploy → 入口）。

### 单领域（只跑 B 站或 Etsy 其中一个 Agent）

| 目标 | 本地终端要跑什么 | `.env` / 前置 | 入口（在项目根执行） | 详细步骤 |
|------|------------------|---------------|----------------------|----------|
| **B 站进程内** Agent | 无额外服务 | §0：`python -m bilibili_agent login`；桌面有 `Up主名称.xlsx` | `./scripts/run_adk_bilibili_agent.sh` | [§2.1](#21-进程内最简单) |
| **Etsy 进程内** Agent | 无额外服务 | §0：`ETSY_KEYSTRING` / `ETSY_SHARED_SECRET` | `./scripts/run_adk_etsy_agent.sh` | [§3.1](#31-进程内最简单) |
| **B 站 REST** Agent | **终端 1**：`python local_node/server.py`（:8001） | 本地：`BILIBILI_REST_SERVER_URL=http://127.0.0.1:8001` | `./scripts/run_adk_bilibili_cloud_agent.sh` | [§2.2](#22-rest本机或云端链路) |
| **Etsy REST** Agent | **终端 1**：`local_node/server.py`（:8001，与 B 站共用） | 本地：`ETSY_REST_SERVER_URL=http://127.0.0.1:8001` | `./scripts/run_adk_etsy_cloud_agent.sh` | [§3.2](#32-rest) |
| **B 站 MCP** Agent | **终端 1**：`python mcp_server/bilibili_mcp.py --http`（:8002） | 本地：`BILIBILI_MCP_SERVER_URL=http://127.0.0.1:8002/mcp` | `./scripts/run_adk_bilibili_cloud_agent_mcp.sh` | [§2.3](#23-mcp本机或云端链路) |
| **Etsy MCP** Agent | **终端 1**：`python mcp_server/etsy_mcp.py --http`（:8003） | 本地：`ETSY_MCP_SERVER_URL=http://127.0.0.1:8003/mcp` | `./scripts/run_adk_etsy_cloud_agent_mcp.sh` | [§3.3](#33-mcp) |

### 调度树（小智调度阿B + E姐，双领域）

| 目标 | 本地终端（常开） | 一次性 / 入口 | `.env` / 前置 | 详细步骤 |
|------|------------------|---------------|---------------|----------|
| **调度树本地** `adk run` | **1–2**：双 MCP（:8002 / :8003）<br>**3**：`run_adk_smart_agents.sh` | 终端 3 即入口 | §0 完成；脚本默认连 `127.0.0.1` 双 MCP | [§4.1](#41-本地调度树) |
| **调度树云端** Playground | **1–2**：双隧道<br>**3–4**：双 MCP | **5**：`deploy_smart_agents.sh`（跑完可关）<br>入口：GCP Console Playground | 隧道域名已写入 `.env` 后再启 MCP；已 deploy | [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用) · [§6](#6-云端部署清单可选) |

### 多入口（Widget / 飞书，底层都是调度树）

> **云端模式**（Widget cloud / 飞书 cloud）与 Playground **共用同一套底座**：[§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用) 的终端 **1–5** 跑通后，再开 **终端 6** 启动对应入口。

| 目标 | 本地终端（常开） | 一次性 / 入口 | `.env` / 前置 | 详细步骤 |
|------|------------------|---------------|---------------|----------|
| **Widget 本地** | **1–2**：双 MCP<br>**3**：`widget_server.py` | 浏览器 `http://127.0.0.1:8000/` | `WIDGET_RUN_MODE=local` | [§4.3 A](#43-widget-入口双模式) |
| **Widget 云端** | **1–2**：双隧道<br>**3–4**：双 MCP<br>**6**：`widget_server.py` | **5**：`deploy_smart_agents.sh`<br>浏览器 `http://127.0.0.1:8000/` | `WIDGET_RUN_MODE=cloud` + `SMART_AGENTS_ENGINE_ID` | [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用) · [§4.3 B](#43-widget-入口双模式) |
| **飞书 local** | **1–2**：双 MCP<br>**3**：`run_feishu_smart_agents.sh` | 飞书群聊 `@机器人` 或私聊 | `FEISHU_RUN_MODE=local` + 飞书凭证 | [§5.1](#51-local-模式默认本地-runner) |
| **飞书 cloud** | **1–2**：双隧道<br>**3–4**：双 MCP<br>**6**：`run_feishu_smart_agents.sh` | **5**：`deploy_smart_agents.sh`<br>飞书群聊 `@机器人` 或私聊 | `FEISHU_RUN_MODE=cloud` + `SMART_AGENTS_ENGINE_ID` | [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用) · [§5.2](#52-cloud-模式云端-agent-runtime) |

**端口速记**：REST `:8001`（仅 REST 单模块）· B 站 MCP `:8002` · Etsy MCP `:8003` · Widget `:8000`。**调度树 / Widget cloud / 飞书 cloud 走 MCP，不走 :8001。**

**云端终端数速记**：常开 **4**（双隧道 + 双 MCP）+ 一次性 **1**（deploy）+ 入口 **1**（Widget 或飞书 Bridge）= 最多 **6** 个终端；Playground 测通底座后 **不必** 再开第 6 个本地进程。

---

## 2) B 站单模块清单

### 2.1 进程内（最简单）

- [ ] 已完成 `python -m bilibili_agent login`
- [ ] 桌面有 `Up主名称.xlsx`
- [ ] 启动：`./scripts/run_adk_bilibili_agent.sh`
- [ ] 验证：发一句「读取 Excel 里所有 UP 主并写回粉丝数」

### 2.2 REST（本机或云端链路）

- [ ] 启动 REST 节点：`python local_node/server.py`
- [ ] 本机直连（推荐本地调试）：
```bash
BILIBILI_REST_SERVER_URL=http://127.0.0.1:8001 ./scripts/run_adk_bilibili_cloud_agent.sh
```
- [ ] 云端：开 `cloudflared tunnel --url http://127.0.0.1:8001` 并更新 `.env` 的 `BILIBILI_REST_SERVER_URL`
- [ ] 健康检查：`curl http://127.0.0.1:8001/docs`

### 2.3 MCP（本机或云端链路）

- [ ] 启动 B 站 MCP：`python mcp_server/bilibili_mcp.py --http`
- [ ] 本机直连：
```bash
BILIBILI_MCP_SERVER_URL=http://127.0.0.1:8002/mcp ./scripts/run_adk_bilibili_cloud_agent_mcp.sh
```
- [ ] 云端（单 MCP 模块）：见 [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用) 中「步骤 1–4」的单端口版（只开 :8002 隧道 + MCP）

---

## 3) Etsy 单模块清单

### 3.1 进程内（最简单）

- [ ] `.env` 已配置 `ETSY_KEYSTRING` / `ETSY_SHARED_SECRET`
- [ ] 凭证自检：`python scripts/test_etsy_local.py --check-credentials --verify-api`
- [ ] 启动：`./scripts/run_adk_etsy_agent.sh`

### 3.2 REST

- [ ] 启动 REST 节点：`python local_node/server.py`
- [ ] 本机直连：`ETSY_REST_SERVER_URL=http://127.0.0.1:8001 ./scripts/run_adk_etsy_cloud_agent.sh`
- [ ] 云端：隧道 :8001 并更新 `ETSY_REST_SERVER_URL`

### 3.3 MCP

- [ ] 启动 Etsy MCP：`python mcp_server/etsy_mcp.py --http`
- [ ] 本机直连：`ETSY_MCP_SERVER_URL=http://127.0.0.1:8003/mcp ./scripts/run_adk_etsy_cloud_agent_mcp.sh`
- [ ] 云端（单 MCP 模块）：见 [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用) 单端口版（:8003）

---

## 4) Agent 树（smart_agents）清单

### 4.1 本地调度树

- [ ] 双 MCP：`:8002` + `:8003`
- [ ] `./scripts/run_adk_smart_agents.sh`
- [ ] 验证路由：
  - 「帮我查 B 站 UP 主粉丝数」→ 阿B
  - 「导出 Etsy listing 评论」→ E姐
  - 「你好」→ 小智直接答，不 transfer

> `adk run` 加载 `root_agent`，**不含** Memory Plugin / Session 压缩。长期记忆与压缩仅在云端 `--adk_app_object=app` 部署后生效。

### 4.2 云端调度树底座（Playground / Widget cloud / 飞书 cloud 共用）

以下步骤适用于：**Playground 测调度树**、**Widget cloud**、**飞书 cloud**（三者都需要云端 Engine 能访问本机双 MCP）。

**为什么先隧道、后 MCP？**  
`BILIBILI_TUNNEL_HOST` / `ETSY_TUNNEL_HOST` 在 **MCP 进程启动时**读入并写入 Host 白名单。先开隧道拿到域名、写入 `.env`，再 **第一次** 启动双 MCP，即可带上白名单，**不必先启 MCP 再重启**。  
（隧道在后端未起时可能返回 502，不影响从 `cloudflared` 输出里复制域名。）

**终端布局（共 6 个，deploy 为一次性）**

| 终端 | 命令 | 说明 |
|------|------|------|
| **1** | `./scripts/start_cloudflare_tunnel.sh 8002` | B 站 MCP 隧道；记下 `*.trycloudflare.com` |
| **2** | `./scripts/start_cloudflare_tunnel.sh 8003` | Etsy MCP 隧道；记下另一域名（**勿与 B 站混用**） |
| — | 编辑根目录 `.env` | 见下方 env 块 |
| **3** | `python mcp_server/bilibili_mcp.py --http` | :8002；启动日志应打印隧道 Host 白名单 |
| **4** | `python mcp_server/etsy_mcp.py --http` | :8003 |
| **5** | `./scripts/deploy_smart_agents.sh` | 一次性；把 MCP 公网 URL 写入 `smart_agents/.env` 并 deploy |
| **6** | 仅 Widget / 飞书需要 | Widget：`python local_node/widget_server.py`；飞书：`./scripts/run_feishu_smart_agents.sh`；**Playground 不需要终端 6** |

```bash
brew install cloudflare/cloudflare/cloudflared   # macOS 首次
```

**步骤 1–2**：开双隧道，从各自终端输出复制域名。

**步骤 3（写 `.env`）**：

```env
BILIBILI_MCP_SERVER_URL=https://<bilibili-uuid>.trycloudflare.com/mcp
ETSY_MCP_SERVER_URL=https://<etsy-uuid>.trycloudflare.com/mcp
BILIBILI_TUNNEL_HOST=<bilibili-uuid>.trycloudflare.com
ETSY_TUNNEL_HOST=<etsy-uuid>.trycloudflare.com
SMART_AGENTS_ENGINE_ID=<你的 Engine ID>
```

**步骤 4**：在 **已 source `.env` 的 shell** 或确保 `load_dotenv` 能读到上述变量后，启动双 MCP（终端 3–4）。

**步骤 5**：`./scripts/deploy_smart_agents.sh`（终端 5，跑完可关）。

**步骤 6（按场景）**：

| 场景 | 操作 |
|------|------|
| Playground | GCP Console → Agent Engine → Playground |
| Widget cloud | `WIDGET_RUN_MODE=cloud` + 终端 6 起 `widget_server.py` |
| 飞书 cloud | `FEISHU_RUN_MODE=cloud` + 终端 6 起 `run_feishu_smart_agents.sh` |

**单领域 MCP 云端（仅 B 站或 Etsy 一个包）**：只做对应端口——隧道 **1** 个终端 + MCP **1** 个终端，更新该侧的 `*_MCP_SERVER_URL` / `*_TUNNEL_HOST`，再 deploy 对应单领域包。

**隧道域名变更时**：更新 `.env` → **重启对应 MCP** → **redeploy**（`deploy_smart_agents.sh` 或单领域 `adk deploy`）。

### 4.3 Widget 入口（双模式）

#### A) local 模式（推荐新手，免部署）

- [ ] `WIDGET_RUN_MODE=local`
- [ ] 双 MCP + `python local_node/widget_server.py`
- [ ] 浏览器打开 `http://127.0.0.1:8000/`
- [ ] 验证跨域调度：「先查 B 站粉丝，再导出 Etsy 评论」

#### B) cloud 模式（连 Agent Engine）

**cloud 模式**：推理与编排运行在云端 Agent Engine；RPA 仍在本机（经 MCP + 隧道）。

```
浏览器 → widget :8000 → Vertex Agent Engine（云端）
                              ↓ transfer
                         MCP :8002 / :8003（本机 + 隧道）
                              ↓
                         bilibili_tools / etsy_tools
```

- **纯闲聊 / 路由**：只需 `widget_server.py` + 已 deploy 的 Engine
- **B 站 / Etsy 任务**：须双 MCP + 双隧道；**不需要** `local_node/server.py`（`:8001`）

- [ ] `WIDGET_RUN_MODE=cloud`
- [ ] 已完成 [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用) 终端 **1–5**（双隧道 + 双 MCP + deploy）
- [ ] `SMART_AGENTS_ENGINE_ID` 或 `AGENT_RESOURCE_NAME`
- [ ] **终端 6**：`python local_node/widget_server.py` → `http://127.0.0.1:8000/`

**常见体感问题**：
- Session 停在子 Agent 时，下条消息可能仍由专家接手 → 点 **「新会话」**
- 启动时 `async_get_session HTTP 400` 后自动新建 session：可忽略，用新 session 继续

---

## 5) 飞书接入清单（基于调度树）

- [ ] `.env` 配置 `FEISHU_APP_ID` + `FEISHU_APP_SECRET`（或 `FEISHU_APP_TOKEN`）

### 5.1 local 模式（默认，本地 Runner）

- [ ] `FEISHU_RUN_MODE=local`
- [ ] 双 MCP + `./scripts/run_feishu_smart_agents.sh`

### 5.2 cloud 模式（云端 Agent Runtime）

- [ ] `FEISHU_RUN_MODE=cloud`
- [ ] 已完成 [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用) 终端 **1–5**
- [ ] `AGENT_RESOURCE_NAME` 或 `GCP_PROJECT_NUMBER` + `GCP_LOCATION` + `SMART_AGENTS_ENGINE_ID`
- [ ] **终端 6**：`./scripts/run_feishu_smart_agents.sh`

- [ ] 飞书后台：事件 `im.message.receive_v1`，接收方式 **长连接**
- [ ] 验证：群聊 `@机器人`；首条「处理中」，长任务会更新进度
- [ ] 发送 `新对话` / `/新对话`：清空当前群/私聊 Session，**不**删长期记忆

### 5.3 记忆、搜索与身份

| 能力 | 说明 |
|------|------|
| **Session**（短期） | 按 `feishu_{chat}_{user}` 隔离；`新对话` 清空 |
| **Memory Bank**（长期） | `user_id=feishu_{open_id}`，跨群/私聊共享；**仅小智**读写 |
| **联网搜索** | 仅小智 `GoogleSearchTool`；新闻/天气等时效问题 |
| **知识库 RAG** | 仅小智 `rag_search`；文档问答（见 [§10](#10-知识库-rag-poc)） |
| **cloud Session 映射** | 飞书逻辑 session → Engine 分配 id（`feishu_cloud_sessions.db`） |
| **Memory 刷写** | Engine `after_agent_callback` + Bridge 侧 `memories.generate` 兜底 |
| **local 模式** | Session 落 SQLite；Memory 进程内（重启丢失）— 长期记忆请用 **cloud** |
| **Widget** | 无用户身份，**不使用** Memory Bank |

### 5.4 防提示词注入（主人忠诚模式）

在 `.env` 增加并重启 Bridge：

```env
FEISHU_OWNER_OPEN_ID=ou_xxxxxxxxxxxxxxxxxxxxx
FEISHU_OWNER_ALIASES=owner_display_name,nickname
FEISHU_STRICT_LOYALTY_MODE=true
```

生效后：
- 非主人用户的「改系统提示词/改规则/只听我」类指令会被直接拦截
- 非主人针对主人别名的辱骂、攻击指令会被直接驳回
- 主人本人指令不受该拦截影响

---

## 6) 云端部署清单（可选）

部署前：`set -a && source .env && set +a`；按 [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用) 跑通双隧道 + 双 MCP，再执行 deploy。

### 6.1 `--agent_engine_id`：首次 vs 更新

| 场景 | 是否加 `--agent_engine_id` | 结果 |
|------|---------------------------|------|
| **首次部署** | **不要加** | 创建新 Engine；记下输出的 ID |
| **更新已有 Engine** | **要加** | 覆盖同一实例 |

首次成功后写入 `.env`：

```env
BILIBILI_REST_AGENT_ENGINE_ID=...
BILIBILI_MCP_AGENT_ENGINE_ID=...
ETSY_REST_AGENT_ENGINE_ID=...
ETSY_MCP_AGENT_ENGINE_ID=...
SMART_AGENTS_ENGINE_ID=...   # 调度树 / Widget cloud / 飞书 cloud
```

> 各 Agent 包 **相互独立**，不要混用 Engine ID。

### 6.2 Skill：两条路径

| 路径 | 作用 | 是否 deploy 前置 |
|------|------|------------------|
| **A. 打进 Agent 镜像** | `SKILL.md` 随 `adk deploy` 进容器 | ✅ **必须** |
| **B. GCP Skill Registry** | 云端治理、`retrieve` 检索 | ❌ 可选 |

调度树：[`deploy_smart_agents.sh`](scripts/deploy_smart_agents.sh) 自动 `rsync skills/` → `smart_agents/skills/`。

单领域改 Skill 后：

```bash
python skill_registry.py validate
python skill_registry.py update --skill-id bilibili-rpa   # 可选
cp -R skills/bilibili-rpa/* bilibili_cloud_agent/skills/bilibili-rpa/
cp -R skills/bilibili-rpa/* bilibili_cloud_agent_mcp/skills/bilibili-rpa/
# Etsy 同理
adk deploy agent_engine ...
```

### 6.3 单领域 Agent 部署

| 包名 | 本地依赖 | `.env` 云端 URL |
|------|----------|-----------------|
| `bilibili_cloud_agent` | `server.py` :8001 + 隧道 | `BILIBILI_REST_SERVER_URL` |
| `bilibili_cloud_agent_mcp` | `bilibili_mcp` :8002 + 隧道 | `BILIBILI_MCP_SERVER_URL` · `BILIBILI_TUNNEL_HOST` |
| `etsy_cloud_agent` | `server.py` :8001 + 隧道 | `ETSY_REST_SERVER_URL` |
| `etsy_cloud_agent_mcp` | `etsy_mcp` :8003 + 隧道 | `ETSY_MCP_SERVER_URL` · `ETSY_TUNNEL_HOST` |

```bash
# 首次（省略 --agent_engine_id）
adk deploy agent_engine bilibili_cloud_agent \
  --project=$GCP_PROJECT_ID --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud REST Agent"

# 更新（加 ID）
adk deploy agent_engine bilibili_cloud_agent \
  --project=$GCP_PROJECT_ID --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud REST Agent" \
  --agent_engine_id=$BILIBILI_REST_AGENT_ENGINE_ID
```

其他单领域包同理，见各目录 README。

### 6.4 调度树 `smart_agents` 部署（推荐脚本）

```bash
./scripts/deploy_smart_agents.sh
```

脚本会：
1. `rsync` `skills/` → `smart_agents/skills/`
2. 生成 `smart_agents/.env`（MCP 公网 URL + **RAG_*** 等）
3. `adk deploy ... --adk_app_object=app`（启用 Memory Plugin + Session 压缩）

**不要**只用仓库根 `--env_file=.env`（云端读不到 MCP / RAG URL）。

手动等价：

```bash
adk deploy agent_engine smart_agents \
  --project=$GCP_PROJECT_ID --region=$GCP_LOCATION \
  --display_name="SmartAgents Dispatcher" \
  --agent_engine_id=$SMART_AGENTS_ENGINE_ID \
  --adk_app_object=app
```

### 6.5 改代码后需要重启什么？

| 改动 | 操作 |
|------|------|
| `smart_agents/agent.py`、记忆、路由、搜索、RAG | 仅 `./scripts/deploy_smart_agents.sh` |
| MCP 隧道 URL / `TUNNEL_HOST` | 更新 `.env` → **重启 MCP** → **redeploy** |
| Feishu Bridge 代码（Session 映射、Memory flush、护栏） | **重启** `run_feishu_smart_agents.sh` |
| Widget 网关代码 | **重启** `widget_server.py` |
| 仅 `bilibili_tools` / `etsy_tools` | 重启 MCP，**不必** redeploy Agent |
| 仅换 `RAG_CORPUS_NAME` / 开关 | 更新根 `.env` → **redeploy**（写入 `smart_agents/.env`） |

---

## 7) 高频故障快速排查

| 现象 | 原因 | 处理 |
|------|------|------|
| 工具 HTTP 404 | 隧道过期或 MCP 未起 | 本地改 `127.0.0.1` 验证；更新隧道 URL |
| Agent 说「正在查询」但无工具调用 | 云端连不上 MCP | 检查隧道、`curl` MCP URL；重启 MCP |
| MCP **421** Invalid Host | `TUNNEL_HOST` 未在 MCP 启动时加载 | 更新 `.env` → **重启 MCP** |
| 隧道 SSL / control stream 失败 | Clash/VPN fake-ip 或 Quick Tunnel 不稳定 | 关 VPN 或 Named Tunnel |
| B 站 **503** `LOGIN_STATE_MISSING` | 无登录态 | `python -m bilibili_agent login` |
| 飞书 cloud **async_create_session 400** | 已修复：逻辑 id 映射 | 更新 Bridge；见 `cloud_session_store.py` |
| Memory Bank 始终 0 条 | 未 deploy `app` 或未发新消息 | `deploy_smart_agents.sh` + 重启 Bridge + 再聊一轮 |
| 文档问答不走知识库 / 无 `rag_search` | 未启用或未 redeploy | 检查 `RAG_ENABLED` + `RAG_CORPUS_NAME`；`deploy_smart_agents.sh` |
| RAG `RAG_QUERY_FAILED` / 跨区失败 | corpus region 与 `RAG_LOCATION` 不一致 | `RAG_LOCATION` 与 corpus 一致（如 `asia-east1`） |
| Widget 对「你好」答非所问 | Session 停在子 Agent | 点「新会话」或 redeploy 最新交还规则 |
| `adk run` 无长期记忆 | 预期行为 | 记忆仅在云端 `app` 部署 + 飞书 cloud |
| 端口冲突 | 进程占用 | `lsof -i :8001` / `:8002` / `:8003` → `kill` |

```bash
# 快速端口检查
lsof -i :8001 && lsof -i :8002 && lsof -i :8003
```

---

## 8) 建议新手的最短路径

1. B 站进程内：`./scripts/run_adk_bilibili_agent.sh`
2. Etsy 进程内：`./scripts/run_adk_etsy_agent.sh`
3. 调度树本地：双 MCP + `./scripts/run_adk_smart_agents.sh`
4. Widget 本地：`widget_server.py` + 浏览器 `:8000`
5. 飞书 local：`./scripts/run_feishu_smart_agents.sh`
6. 云端：按 [§4.2](#42-云端调度树底座playground--widget-cloud--飞书-cloud-共用)（隧道 → `.env` → MCP → deploy）+ Playground
7. （可选）RAG：见 [§10](#10-知识库-rag-poc)，先起 corpus 再 redeploy

---

## 9) Cursor IDE（stdio MCP）

无需启动 HTTP 服务或隧道；Cursor 以 **stdio** 拉起 `bilibili_mcp.py`。

- [ ] 配置见 [`.cursor/README.md`](.cursor/README.md)（`mcp.json`）
- [ ] `python -m bilibili_agent login` + 桌面 `Up主名称.xlsx`
- [ ] 在 Cursor Agent 对话中直接描述任务

与云端路径区别：Cursor 用 stdio；Agent Engine / 调度树用 `--http` + MCP URL。

---

## 10) 知识库 RAG（PoC）

把手册 / PDF 导入 **Agent Platform → RAG Engine**，再挂到调度员**小智**的 `rag_search`。  
**与 Memory Bank 分工**：Memory 记「这个人」的偏好；RAG 记「团队文档」知识。

### 10.1 平台侧建 corpus

1. Agent Platform → **RAG Engine** → Create corpus  
2. Region：优先与 Agent Engine 同区（`us-central1`）。若 Spanner mode 报白名单限制，可改用 **Serverless**，或换可用区（本 PoC 曾用 `asia-east1`）  
3. Embedding：`Text Multilingual Embedding 002`（中文稳）  
4. Vector DB：托管 Spanner / Serverless 均可（受区域白名单约束）  
5. Chunk 建议 PoC：`size≈800`、`overlap≈160`；布局解析先用 Default  
6. **Import data**（GCS / 本地 / Drive）：等 Data 页全部 **Imported**（创建成功 ≠ 已入库）  
7. 复制 Details 中的完整 resource name：  
   `projects/<project>/locations/<loc>/ragCorpora/<id>`

> **RAG Engine vs Vector Search**：前者是托管「文档→切分→embedding→检索」应用层；后者是底层向量库（自备 embedding）。杂乱 PDF 开箱路线优先 RAG Engine。

### 10.2 根目录 `.env`

```env
RAG_ENABLED=true
RAG_CORPUS_NAME=projects/<project>/locations/<loc>/ragCorpora/<id>
RAG_LOCATION=<loc>          # 必须与 corpus 同 region
# RAG_PROJECT_ID=           # 可选，默认 GCP_PROJECT_ID
```

### 10.3 部署与验证

```bash
./scripts/deploy_smart_agents.sh   # 把 RAG_* 写入 smart_agents/.env
```

飞书 / Playground 问文档内问题（示例）：

- 「Gemini Enterprise 权限怎么配？」
- 「Vertex AI API 接入要注意什么？」
- 「DSQ / 429 怎么缓解？」

本地 smoke（无需 deploy）：

```bash
RAG_ENABLED=true \
RAG_CORPUS_NAME='projects/.../ragCorpora/...' \
RAG_LOCATION=asia-east1 \
python -c "from smart_agents.rag_tools import rag_search; print(rag_search('权限配置', 3))"
```

### 10.4 能力边界

| 问题类型 | 小智行为 |
|----------|----------|
| 内部 PDF / 手册 | `rag_search` |
| 新闻 / 天气等时效 | `google_search` |
| 称呼 / 偏好 | Memory Bank |
| B 站 / Etsy RPA | transfer 专家（不用 RAG） |

代码：[`smart_agents/rag_tools.py`](smart_agents/rag_tools.py) · 挂载：[`smart_agents/agent.py`](smart_agents/agent.py)。

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [`README.md`](README.md) | 架构总览、模块地图 |
| [`docs/adk_learning_guide.md`](docs/adk_learning_guide.md) | ADK 概念、多 Agent、Memory、RAG、部署全景 |
| [`mcp_server/README.md`](mcp_server/README.md) | MCP、隧道 |
| [`skills/README.md`](skills/README.md) | Skill Registry CLI |
| [`smart_agents/README.md`](smart_agents/README.md) | 调度树、记忆、RAG |
| [`integrations/feishu/README.md`](integrations/feishu/README.md) | 飞书环境变量、护栏、Bridge |
