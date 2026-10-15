# SmartAgents 操作手册

> 面向**从未接触过本项目**的开发者：按章节勾选即可完成环境准备、选场景、启动与排错。  
> 架构鸟瞰：[`README.md`](README.md) · 脚本索引：[`scripts/README.md`](scripts/README.md) · 环境 profile：[`env/README.md`](env/README.md)

---

## 0) 前置条件总览

### 0.1 按场景需要什么？

| 条件 | 几乎所有场景 | 仅 B 站 | 仅 Etsy | 本地 `adk run` | 云端 **cloud** | 飞书 | RAG | TSE | Code Exec |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| §0.2 Python + 依赖 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| §0.3 `.env` + `local.env` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| §0.4 B 站登录 + Excel | — | ✅ | — | 视任务 | B 站任务 | B 站任务 | — | — | — |
| §0.5 Etsy 凭证 + GCS | — | — | ✅ | 视任务 | Etsy 任务 | Etsy 任务 | — | — | — |
| §0.6 Cloudflare 隧道 | — | — | — | ❌ | ✅ | cloud | — | — | — |
| §0.7 飞书应用 | — | — | — | — | — | ✅ | — | — | — |
| §0.8 deploy + Engine ID | — | — | — | ❌ | ✅ | cloud | ✅ | ✅ | ✅ |

**本地纯调试**（`adk run`、飞书 `local`、Widget `local`）：双 MCP 用 `127.0.0.1`，**不需要**隧道。

---

### 0.2 克隆仓库与 Python 环境（必做）

**建议系统**：macOS / Linux（Windows + Playwright 未完整验证）。

```bash
git clone <your-repo-url> SmartAgents
cd SmartAgents

python3 -m venv .venvAgents
source .venvAgents/bin/activate    # Windows: .venvAgents\Scripts\activate

pip install -r requirements.txt
playwright install chromium        # B 站 RPA；只跑 Etsy 可先跳过
```

验证：

```bash
python -c "import google.adk; print('adk ok')"
adk --help
```

飞书 Bridge 额外依赖（跑 `run_feishu_smart_agents.sh` 时脚本会提示安装）：

```bash
pip install -r integrations/feishu/requirements.txt
```

**国内访问 Vertex**：在 env 中加 `VERTEX_HTTP_PROXY=http://127.0.0.1:7890`（按你的代理端口改）。

---

### 0.3 环境配置（必读：两个文件）

> 详细说明：[`env/README.md`](env/README.md)

#### 第一步：根目录 `.env`（密钥总表，只填一次）

```bash
cp .env.example .env
# 编辑 .env — 至少填 GCP；按你要测的入口再加 Etsy / 飞书 / GCS / RAG（见下表）

gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID
```

#### 第二步：`env/local.env`（本地入口覆盖，强烈推荐）

```bash
cp env/local.env.example env/local.env
# 一般保持默认即可（强制 FEISHU_RUN_MODE=local + 127.0.0.1 MCP）
```

**加载顺序**：所有 `run_adk_*.sh` / `run_feishu_*.sh` 先读 `.env`，再读 `env/local.env`（后者覆盖前者）。  
MCP 与 Agent 脚本均加载 `.env` → `env/local.env`。在仓库根启动 MCP 即可。

#### 按入口：`.env` 里要填什么？

| 入口 | 启动命令 | `.env` **必填** | `.env` **按需**（做对应任务时） |
|------|----------|-----------------|--------------------------------|
| B 站单域 | `run_adk_bilibili_agent.sh` | `GCP_PROJECT_ID`、`GCP_LOCATION` | — |
| Etsy 单域 | `run_adk_etsy_agent.sh` | 上 + `ETSY_KEYSTRING`、`ETSY_SHARED_SECRET` | 生图：`ETSY_IMAGE_GCS_BUCKET` 等 |
| 调度树 | `run_adk_smart_agents.sh` | `GCP_*` | Etsy 任务 → Etsy 凭证；知识库 → `RAG_*`；TSE → `GCP_DATA_MCP_*`；作图 → `CODE_EXECUTION_*` |
| 飞书 | `run_feishu_smart_agents.sh` | `GCP_*`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET` | Etsy、RAG、TSE（`GCP_DATA_MCP_*`）、Code Exec |
| Widget | `run_widget.sh` | `GCP_*` | `WIDGET_RUN_MODE`；cloud → `SMART_AGENTS_ENGINE_ID` |
| 只起 MCP | `python mcp_server/etsy_mcp.py --http` | Etsy 凭证在 `.env` | 生图 GCS |
| 云端 deploy | `deploy_smart_agents.sh` | `GCP_*`、`SMART_AGENTS_ENGINE_ID`、公网 MCP URL | `RAG_*`、`GCP_DATA_MCP_*`、`CODE_EXECUTION_*` |

每个本地入口还需要 **`env/local.env`**（`cp env/local.env.example env/local.env`）+ **另开终端起 MCP**（见 §1）。

#### 环境检查

`run_*` 脚本会**自动**检查，不必单独跑。排错：

```bash
python scripts/check_runtime_env.py --mode smart_agents
python scripts/check_runtime_env.py --mode feishu
```

---

### 0.4 B 站 RPA（按需）

| 项 | 说明 |
|----|------|
| Chromium | `playwright install chromium` |
| 登录态 | `python -m bilibili_agent login` → 根目录 `bilibili_state.json`（已 gitignore） |
| UP 主 Excel | 默认 `~/Desktop/Up主名称.xlsx`（首列为 UP 主名） |

无 Agent 直测 RPA：

```bash
python scripts/test_p0_local.py
```

B 站 Agent 启动前 **必须先** 起 MCP：

```bash
python mcp_server/bilibili_mcp.py --http   # 终端 1，保持运行
./scripts/run_adk_bilibili_agent.sh         # 终端 2
```

---

### 0.5 Etsy 凭证与生图（按需）

写入**根 `.env`**：

```env
ETSY_KEYSTRING=your-keystring
ETSY_SHARED_SECRET=your-shared-secret
ETSY_IMAGE_GCS_BUCKET=your-bucket   # 真实生图需要
```

获取与验证见 [Etsy Developers](https://www.etsy.com/developers/your-apps)；`python scripts/test_etsy_local.py --check-credentials --verify-api`

Etsy Agent：**先** `python mcp_server/etsy_mcp.py --http`，**再** `./scripts/run_adk_etsy_agent.sh`

---

### 0.6 Cloudflare Quick Tunnel（仅云端调本机 MCP）

**何时需要**：Agent Engine Playground、Widget `cloud`、飞书 `cloud`。

**何时不需要**：本地 `adk run`、飞书 `local`、Widget `local`。

```bash
brew install cloudflare/cloudflare/cloudflared   # macOS 示例

# 各开一个终端
./scripts/start_cloudflare_tunnel.sh 8002   # B 站 MCP
./scripts/start_cloudflare_tunnel.sh 8003   # Etsy MCP
```

从输出复制 `https://<uuid>.trycloudflare.com`，写入根 `.env`：

```env
BILIBILI_MCP_SERVER_URL=https://<bilibili-uuid>.trycloudflare.com/mcp
ETSY_MCP_SERVER_URL=https://<etsy-uuid>.trycloudflare.com/mcp
BILIBILI_TUNNEL_HOST=<bilibili-uuid>.trycloudflare.com
ETSY_TUNNEL_HOST=<etsy-uuid>.trycloudflare.com
```

**顺序**：先隧道拿域名 → 写 `.env` → **再启动 MCP**（白名单在 MCP 启动时加载）→ deploy。

隧道进程与 MCP 须 **常开**。Clash fake-ip 可能导致 SSL 异常（§7）。

---

### 0.7 飞书开放平台（仅飞书入口）

1. [飞书开放平台](https://open.feishu.cn/) 创建应用，开启机器人  
2. **App ID / Secret 写在根 `.env`**；`env/local.env` 保持 `FEISHU_RUN_MODE=local`  
3. 事件 `im.message.receive_v1`，长连接（先启动 Bridge 再保存）  
4. 详见 [`integrations/feishu/README.md`](integrations/feishu/README.md)

---

## 1) 场景速查

> 完成 §0 后，在下表找到目标行，按列开终端并执行入口命令。

### 单领域 Agent

| 目标 | 终端 1（常开） | 终端 2（入口） | 配置 |
|------|----------------|----------------|------|
| **B 站 Agent** | `python mcp_server/bilibili_mcp.py --http` | `./scripts/run_adk_bilibili_agent.sh` | `.env` GCP + `env/local.env` + §0.4 登录 |
| **Etsy Agent** | `python mcp_server/etsy_mcp.py --http` | `./scripts/run_adk_etsy_agent.sh` | `.env` GCP+Etsy + `env/local.env` |

> 脚本自动检查 env；**MCP 须先在另一终端常开**。

### 调度树（小智 + 阿B + E姐）

| 目标 | 终端 1 | 终端 2 | 终端 3 |
|------|--------|--------|--------|
| **本地 adk run** | B 站 MCP :8002 | Etsy MCP :8003 | `./scripts/run_adk_smart_agents.sh` |

> `.env` + `env/local.env`；脚本自动检查 GCP + 双 MCP URL。

验证话术：

- 「帮我查 Excel 里 UP 主粉丝数」→ 转阿B
- 「导出 listing 12345 的评论」→ 转 E姐
- 「你好，你能做什么？」→ 小智直接答，不 transfer
- 「梁伶飞的客户名单，每人抽一条日报」→ 小智 `get_tse_sales_customer_reports`（需 `GCP_DATA_MCP_ENABLED`）
- 「画一张 TSE 客户归属销售分布图」→ 小智 `render_tse_customer_sales_chart`（需 Code Execution）

### 多入口（底层都是 smart_agents）

| 目标 | 本地常开 | 入口 | 关键 env |
|------|----------|------|----------|
| **飞书 local** | 双 MCP | `./scripts/run_feishu_smart_agents.sh` | `.env` 含飞书凭证 + `local.env` 强制 local |

> 脚本自动检查飞书 App ID/Secret。
| **飞书 cloud** | 双隧道 + 双 MCP + deploy | 同上 | `FEISHU_RUN_MODE=cloud` + `SMART_AGENTS_ENGINE_ID` |
| **Widget local** | 双 MCP | `./scripts/run_widget.sh` | `WIDGET_RUN_MODE=local` |
| **Widget cloud** | 双隧道 + 双 MCP + deploy | 同上 | `WIDGET_RUN_MODE=cloud` |
| **Playground** | 双隧道 + 双 MCP + deploy | GCP Console | `SMART_AGENTS_ENGINE_ID` |

**端口**：B 站 MCP `:8002` · Etsy MCP `:8003` · Widget `:8000`。

---

## 2) B 站单域 — 逐步清单

- [ ] `playwright install chromium`
- [ ] `python -m bilibili_agent login`
- [ ] 桌面有 `Up主名称.xlsx`
- [ ] 终端 1：`python mcp_server/bilibili_mcp.py --http`
- [ ] 终端 2：`./scripts/run_adk_bilibili_agent.sh`
- [ ] 对话：「读取 Excel 里所有 UP 主并写回粉丝数」
- [ ] Agent 会先 `load_skill('bilibili-rpa')`，再调 MCP 工具

---

## 3) Etsy 单域 — 逐步清单

- [ ] 配置 `ETSY_KEYSTRING` / `ETSY_SHARED_SECRET`
- [ ] `python scripts/test_etsy_local.py --check-credentials --verify-api`
- [ ] （生图）配置 `ETSY_IMAGE_GCS_BUCKET` 等
- [ ] 终端 1：`python mcp_server/etsy_mcp.py --http`
- [ ] 终端 2：`./scripts/run_adk_etsy_agent.sh`
- [ ] 评论：「导出 listing \<id\> 的评论到 Excel」
- [ ] 生图：「用 nordic_lifestyle 预设给这张图换场景」（会先 `load_skill('etsy-listing-assets')`）

---

## 4) 调度树 — 逐步清单

### 4.1 本地（推荐新手）

- [ ] `.env` + `env/local.env` 已配置
- [ ] 终端 1：`python mcp_server/bilibili_mcp.py --http`
- [ ] 终端 2：`python mcp_server/etsy_mcp.py --http`
- [ ] 终端 3：`./scripts/run_adk_smart_agents.sh`
- [ ] 验证双域路由（§1 话术）

> `adk run` 不含 Memory Plugin / 事件压缩；长期记忆需云端 deploy（§6）。

### 4.2 云端底座（Playground / Widget cloud / 飞书 cloud 共用）

| 步骤 | 操作 |
|------|------|
| 1–2 | 双隧道（:8002、:8003），复制域名 |
| 3 | 更新根 `.env` 中 MCP URL 与 `*_TUNNEL_HOST` |
| 4–5 | 启动双 MCP（须在写 `.env` **之后**） |
| 6 | `./scripts/deploy_smart_agents.sh`（一次性） |
| 7 | Playground / Widget / 飞书（按场景） |

`.env` 示例：

```env
BILIBILI_MCP_SERVER_URL=https://<bilibili-uuid>.trycloudflare.com/mcp
ETSY_MCP_SERVER_URL=https://<etsy-uuid>.trycloudflare.com/mcp
BILIBILI_TUNNEL_HOST=<bilibili-uuid>.trycloudflare.com
ETSY_TUNNEL_HOST=<etsy-uuid>.trycloudflare.com
SMART_AGENTS_ENGINE_ID=<engine-id>
```

单领域云端 deploy：`adk deploy agent_engine bilibili_agent` 或 `etsy_agent`（包名与本地相同），只需对应一侧 MCP + 隧道。

### 4.3 Web Widget

**local（免 deploy）**

- [ ] `WIDGET_RUN_MODE=local`
- [ ] 双 MCP + `./scripts/run_widget.sh`
- [ ] 浏览器 `http://127.0.0.1:8000/`

**cloud**

- [ ] 完成 §4.2 底座
- [ ] `WIDGET_RUN_MODE=cloud` + `SMART_AGENTS_ENGINE_ID`
- [ ] `./scripts/run_widget.sh`

---

## 5) 飞书接入清单

- [ ] 根 `.env` 含 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`；`env/local.env` 含 `FEISHU_RUN_MODE=local`
- [ ] `FEISHU_RUN_MODE=local`（本机）或 `cloud`（已 deploy）
- [ ] 双 MCP 常开（local 模式）
- [ ] `./scripts/run_feishu_smart_agents.sh`
- [ ] 飞书后台长连接事件已保存
- [ ] 群聊 `@机器人` 或私聊发消息

### 记忆与「新对话」

| 能力 | 说明 |
|------|------|
| Session | 按群/私聊隔离；发 `新对话` 或 `/新对话` 清空 |
| Memory Bank | `user_id=feishu_{open_id}`，跨群共享；**仅小智** |
| cloud 持久记忆 | 需 deploy `--adk_app_object=app` |

### 主人忠诚护栏（可选）

```env
FEISHU_OWNER_OPEN_ID=ou_xxxxxxxx
FEISHU_OWNER_ALIASES=显示名,昵称
FEISHU_STRICT_LOYALTY_MODE=true
```

---

## 6) 云端部署

### 6.1 Engine ID：首次 vs 更新

| 场景 | `--agent_engine_id` |
|------|---------------------|
| 首次创建 | **省略** |
| 更新同一实例 | **必填** |

成功后写入 `.env`：

```env
SMART_AGENTS_ENGINE_ID=...
# 单域可选：
# BILIBILI_MCP_AGENT_ENGINE_ID=...  # 若单独 deploy bilibili_agent
# ETSY_MCP_AGENT_ENGINE_ID=...      # 若单独 deploy etsy_agent
```

### 6.2 调度树 deploy（推荐脚本）

```bash
./scripts/deploy_smart_agents.sh
```

脚本会：

1. `rsync` `skills/` → `smart_agents/skills/`
2. 生成 `smart_agents/.env`（MCP 公网 URL + RAG）
3. `adk deploy ... --adk_app_object=app`

**不要**只用根目录 `--env_file=.env`；云端运行时读 `smart_agents/.env`。

### 6.3 单领域 deploy

```bash
# 首次（省略 agent_engine_id）
adk deploy agent_engine etsy_agent \
  --project=$GCP_PROJECT_ID --region=$GCP_LOCATION \
  --display_name="Etsy Agent"

# 更新
adk deploy agent_engine etsy_agent \
  --project=$GCP_PROJECT_ID --region=$GCP_LOCATION \
  --agent_engine_id=$ETSY_MCP_AGENT_ENGINE_ID
```

`bilibili_agent` 同理。云端须能 HTTPS 访问本机 MCP（隧道）。

### 6.4 改代码后重启什么？

| 改动 | 操作 |
|------|------|
| `domains/*` 工具逻辑 | 重启对应 MCP |
| `smart_agents/agent.py`、RAG、路由 | `deploy_smart_agents.sh` |
| MCP 隧道 URL | 更新 `.env` → 重启 MCP → redeploy |
| 飞书 Bridge | 重启 `run_feishu_smart_agents.sh` |
| Widget | 重启 `run_widget.sh` |
| 仅 `skills/*.md` | validate → redeploy |

---

## 7) 高频故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| `adk run` 启动即报 MCP 不可达 | MCP 未起 | 先 `python mcp_server/*_mcp.py --http` |
| 工具调用 404 / 超时 | MCP 挂了或 URL 错 | `curl` MCP URL；检查 env |
| MCP **421** Invalid Host | 隧道 Host 未进白名单 | 更新 `*_TUNNEL_HOST` 后 **重启 MCP** |
| B 站 503 `LOGIN_STATE_MISSING` | 未登录 | `python -m bilibili_agent login` |
| 飞书 `app_id is invalid` | 根 `.env` 仍是占位符 | 填真实飞书凭证 |
| 飞书仍像旧「评论专家」 | `FEISHU_RUN_MODE=cloud` 连旧 Engine | 改 `local` 或 redeploy 最新 `smart_agents` |
| Token 溢出 400（飞书 local） | Session 历史过大 | 默认 Session guard 已开；发「新对话」或调低 `FEISHU_LOCAL_SESSION_MAX_*` |
| Memory 始终为空 | 未 deploy `app` | `deploy_smart_agents.sh` + 飞书 cloud |
| TSE 反问「日报在哪」 | 未用确定性工具 | `GCP_DATA_MCP_ENABLED=true`；应走 `list_tse_tool_catalog` |
| 图表假 Sales01 数据 | 手写 `run_code` | 必须用 `render_tse_customer_sales_chart` |
| RAG 不生效 | 未 redeploy | 检查 `RAG_*` 是否在 `smart_agents/.env` |
| 端口占用 | 旧进程 | `lsof -i :8002` / `:8003` / `:8000` |

```bash
lsof -i :8002 && lsof -i :8003
python scripts/check_runtime_env.py --mode smart_agents
```

---

## 8) 新手最短路径（约 30 分钟）

1. §0.2–0.3：venv、`pip install`、`gcloud auth`
2. `cp .env.example .env` + `cp env/local.env.example env/local.env`，填 `.env`
3. 只玩调度树：双 MCP + `run_adk_smart_agents.sh`，对小智说「你好」
4. 玩 B 站：`bilibili_agent login` + 双 MCP 之一 + `run_adk_bilibili_agent.sh`
5. 玩 Etsy：配 Etsy 凭证 + `run_adk_etsy_agent.sh`
6. 飞书：§0.7 + `run_feishu_smart_agents.sh`
7. 云端：§0.6 隧道 + §4.2 deploy
8. （可选）RAG：§10 · TSE 数据：§11 · Code Execution：§12

---

## 9) L1 工具直测（不经 Agent）

```bash
python scripts/test_p0_local.py                              # B 站
python scripts/test_etsy_local.py --check-credentials        # Etsy 凭证
python scripts/test_etsy_listing_assets_local.py             # Etsy 生图链路（按需）
```

---

## 10) 知识库 RAG（可选）

小智专用 `rag_search`，与 Memory Bank 分工：Memory 记「这个人」，RAG 记「团队文档」。

1. Agent Platform → **RAG Engine** → 建 corpus → Import 文档 → 等 `Imported`
2. 根 `.env`：

```env
RAG_ENABLED=true
RAG_CORPUS_NAME=projects/<project>/locations/<loc>/ragCorpora/<id>
RAG_LOCATION=<loc>
```

3. `./scripts/deploy_smart_agents.sh`
4. 问：「Gemini Enterprise 权限怎么配？」

本地 smoke：

```bash
RAG_ENABLED=true RAG_CORPUS_NAME='projects/...' RAG_LOCATION=asia-east1 \
  python -c "from smart_agents.rag_tools import rag_search; print(rag_search('权限', 3))"
```

---

## 11) TSE Smart Workspace 数据（可选）

小智通过 **GCP 数据 MCP + 确定性工具** 查询 TSE Firestore（**只读**），不经过阿B/E姐。

### 11.1 开启

根 `.env`：

```env
GCP_DATA_MCP_ENABLED=true
TSE_FIRESTORE_PROJECT_ID=your-gcp-project
TSE_FIRESTORE_DATABASE=tse-jayson-database
```

需 ADC：`gcloud auth application-default login`  
IAM 建议：`roles/mcp.toolUser`、`dataplex.catalogViewer`、`roles/datastore.viewer`（只读）

### 11.2 三层能力

| 层 | 说明 |
|----|------|
| `kc_*` | Knowledge Catalog 元数据（Glossary 补充） |
| `fs_*` | Firestore MCP **只读**（get/list） |
| `list_tse_*` / `get_tse_*` | 17 个场景工具（见 `smart_agents/tse_tools.py`） |

**原则**：先 `list_tse_tool_catalog`，再调场景工具；禁止让用户解释「日报存在哪」。

### 11.3 常用话术

| 用户问 | 工具 |
|--------|------|
| TSE 有多少用户/客户 | `get_tse_overview` |
| 某时间段日报并提炼 | `query_tse_daily_reports_by_date(date_from, date_to, …)` |
| 某销售的客户 + 日报 | `get_tse_sales_customer_reports(sales_name=...)` |
| 客户分布统计/图 | `get_tse_customer_sales_stats` · `render_tse_customer_sales_chart` |
| 待我审批的分享 | `list_tse_pending_shares(recipient_email=...)` |
| 字段什么意思 | `lookup_tse_schema` |

Knowledge Catalog 配置参见 [Agent Platform 学习指南](docs/agent_platform_learning_guide.md)。  
架构导读：[`docs/agent_platform_learning_guide.md`](docs/agent_platform_learning_guide.md) §7。

本地验证（无需飞书）：

```bash
./scripts/run_adk_smart_agents.sh
# 或仅测工具：
python -c "from smart_agents.tse_tools import get_tse_overview; print(get_tse_overview())"
```

改 TSE 工具后 **重启** `run_feishu_smart_agents.sh` 或 `run_adk_smart_agents.sh`。

---

## 12) Code Execution（可选）

小智在 **Vertex Agent Engine Sandbox** 中跑 Python（统计、matplotlib 作图）。

```env
CODE_EXECUTION_ENABLED=true
CODE_EXEC_LOCATION=us-central1
# 默认复用 SMART_AGENTS_ENGINE_ID
```

| 场景 | 工具 |
|------|------|
| 通用分析 | `run_code` + 可选 `stage_data_file` |
| TSE 客户分布图 | **`render_tse_customer_sales_chart`**（内嵌真实 Firestore 统计，禁止手写示例数据） |

- 首次沙箱创建约 1–2 分钟
- 产出 **Artifact**；飞书自动附图（`integrations/feishu/media_delivery.py`）
- TSE 分布图 **不要** 用虚构 `Sales01` 数据直接 `run_code`

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [`README.md`](README.md) | 架构总览 |
| [`docs/domains_architecture.md`](docs/domains_architecture.md) | domains 与扩展 |
| [`docs/agent_platform_learning_guide.md`](docs/agent_platform_learning_guide.md) | Agent Platform 组件导读 |
| [`KC-checklist.md`](KC-checklist.md) | TSE Glossary / Firestore schema |
| [`mcp_server/README.md`](mcp_server/README.md) | MCP 细节 |
| [`smart_agents/README.md`](smart_agents/README.md) | 调度树能力 |
| [`integrations/feishu/README.md`](integrations/feishu/README.md) | 飞书变量与护栏 |
| [`skills/README.md`](skills/README.md) | Skill Registry |
