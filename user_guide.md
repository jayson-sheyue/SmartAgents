# SmartAgents — B 站 RPA Agent 使用指南

> **项目结构总览**：请先阅读 [`README.md`](README.md)（分层架构 + 各目录 README）。  
> 本文档侧重**操作步骤**与**场景命令**。

本文档说明本项目中 **所有 Agent 调用方式** 的使用方法，帮助你根据场景选择合适的路径完成「读取 UP 主名单 → 抓取粉丝数 → 写回 Excel」任务。

---

## 目录

0. [首次使用（必读）](#0-首次使用必读)
1. [项目简介](#1-项目简介)
2. [环境准备（所有场景通用）](#2-环境准备所有场景通用)
3. [调用方式总览](#3-调用方式总览)
4. [场景一：本地 Agent（main.py）](#4-场景一本地-agentmainpy)
5. [场景二：Cursor MCP（stdio）](#5-场景二cursor-mcpstdio)
6. [场景三：云端 Agent + REST（经典路径）](#6-场景三云端-agent--rest经典路径)
7. [场景四：Web Widget 聊天界面](#7-场景四web-widget-聊天界面)
8. [场景五：云端 Agent + MCP（新路径）](#8-场景五云端-agent--mcp新路径)
9. [场景六：直接调用 REST API（无 Agent）](#9-场景六直接调用-rest-api无-agent)
10. [场景七：MCP 本地联调测试](#10-场景七mcp-本地联调测试)
11. [端口与环境变量速查](#11-端口与环境变量速查)
12. [示例指令](#12-示例指令)
13. [常见问题](#13-常见问题)

---

## 0. 首次使用（必读）

按顺序完成以下步骤，即可跑通**全部 7 种调用方式**。

### 0.1 克隆项目并配置环境变量

```bash
cd /path/to/SmartAgents
python3 -m venv .venvAgents
source .venvAgents/bin/activate
pip install -r requirements.txt
playwright install chromium

# 复制环境变量模板并填入真实值（.env 不会提交 Git）
cp .env.example .env
# 编辑 .env：GCP 项目、Engine ID、ngrok 等（可向项目维护者索取已填好的副本）
```

完整变量说明见 [§2.5](#25-配置文件-env) 与 [`.env.example`](.env.example)。

### 0.2 Google Cloud 登录

```bash
gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID   # 与 .env 中 GCP_PROJECT_ID 一致
```

### 0.3 B 站登录（RPA 必须）

```bash
python main.py login
```

### 0.4 最小验证（无需 ngrok）

```bash
# 1) RPA 直调
python scripts/test_p0_local.py

# 2) 本地 Gemini Agent
python main.py

# 3) MCP stdio（或 Cursor 对话，见场景二）
python mcp_server/test_local_client.py
```

### 0.5 云端 Agent 首次部署（可选，已有 Engine 可跳过）

```bash
source .venvAgents/bin/activate
set -a && source .env && set +a

# REST Agent
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

部署后把控制台分配的 Engine ID 写回 `.env`。Skill 包管理见 `python skill_registry.py --help`。

### 0.6 云端联调快速路径（需 ngrok）

| 目标 | 终端 1 | 终端 2 | 终端 3 | 入口 |
|------|--------|--------|--------|------|
| REST Playground | `python server.py` | `ngrok http 8001` | — | GCP Playground（REST Engine） |
| Web Widget | `python server.py` | `ngrok http 8001` | `python widget_server.py` | 浏览器 `local_node/index.html` |
| MCP Playground | `python mcp_server/bilibili_mcp.py --http` | `ngrok http 8002` | — | GCP Playground（MCP Engine） |

Playground 入口：GCP Console → **Vertex AI** → **Agent Engine** → 选择对应 Reasoning Engine → **Playground**。

### 0.7 功能测试清单

| # | 场景 | 验证命令 / 操作 | 通过标准 |
|---|------|-----------------|----------|
| 1 | RPA 核心 | `python scripts/test_p0_local.py` | envelope `ok: true` |
| 2 | 本地 Agent | `python main.py` | 终端有 Agent 汇报 |
| 3 | Cursor MCP | Cursor 对话发抓取指令 | 工具被调用并返回粉丝数 |
| 4 | REST API | `curl localhost:8001/api/get_up_list` | 返回 JSON 名单 |
| 5 | MCP 本地 | `python mcp_server/test_local_client.py` | 列出 3 个 tool |
| 6 | 云端 REST | Playground + ngrok 8001 | Agent 完成抓取 |
| 7 | Web Widget | 三终端 + 打开 index.html | 聊天有回复 |
| 8 | 云端 MCP | Playground + ngrok 8002 | Agent 完成抓取 |

---

## 1. 项目简介

本项目是一个 **B 站 UP 主粉丝数据采集 RPA + AI Agent** 演示系统。核心能力封装在 `main.py`：

| 技能 | 函数 | 说明 |
|------|------|------|
| 读名单 | `read_up_names_from_excel` | 从桌面 Excel 读取 UP 主名称 |
| 抓数据 | `get_up_fans_data` | Playwright 自动化访问 B 站并提取粉丝数 |
| 写回表 | `write_fans_to_excel` | 将粉丝数写入 Excel「粉丝数」列 |
| 记偏好 | `save_user_preference` | 将用户偏好写入 `agent_memory.json` |

**架构原则**：LLM（大脑）负责理解指令与编排任务；Playwright（手脚）在本地浏览器执行 RPA。云端 Agent 无法直接操作你的浏览器，因此必须通过 **ngrok** 或 **MCP HTTP** 把请求转发到本机。

---

## 2. 环境准备（所有场景通用）

### 2.1 安装依赖

```bash
cd /path/to/SmartAgents

# 创建并激活虚拟环境（若尚未创建）
python3 -m venv .venvAgents
source .venvAgents/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

### 2.2 Google Cloud 认证

云端 Agent、Web Widget 中转服务需要访问 Vertex AI，请先完成 ADC 登录：

```bash
gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID
```

`GCP_PROJECT_ID` 从 `.env` 加载；也可 `export GCP_PROJECT_ID=...` 后再执行 `gcloud config set`。

### 2.3 B 站登录态（必须）

RPA 抓取依赖已保存的登录凭证 `bilibili_state.json`。首次使用需手动登录：

```bash
python main.py login
```

按提示在弹出的浏览器中扫码或密码登录，回到终端按 **Enter**，凭证会保存到项目根目录的 `bilibili_state.json`。

> 若该文件不存在或过期，任何抓取任务都会失败。

### 2.4 Excel 数据文件

默认路径：`~/Desktop/Up主名称.xlsx`

- **Sheet1** 第一列为 UP 主名称
- 需有 **「粉丝数」** 列（不存在时程序会自动创建）
- 若文件不存在，程序会使用默认 UP 主：`schmoyoho官号`

### 2.5 配置文件 `.env`

**首次使用**：`cp .env.example .env`，再填入真实值。`.env` 已在 `.gitignore` 中，不会提交到 Git。

```env
# --- Google Cloud（必填）---
GCP_PROJECT_ID=your-gcp-project-id
GCP_PROJECT_NUMBER=000000000000
GCP_LOCATION=us-central1

# --- Reasoning Engine（部署后从控制台获取）---
REST_AGENT_ENGINE_ID=your-rest-reasoning-engine-id
MCP_AGENT_ENGINE_ID=your-mcp-reasoning-engine-id

# --- MCP Registry（仅 MCP 云端路径）---
MCP_SERVER_REGISTRY_ID=your-mcp-server-registry-id

# --- ngrok（云端 Agent 访问本机时必填）---
NGROK_URL=https://your-subdomain.ngrok-free.dev
MCP_SERVER_URL=https://your-subdomain.ngrok-free.dev/mcp
NGROK_HOST=your-subdomain.ngrok-free.dev

# --- 可选：国内访问 Vertex ---
# VERTEX_HTTP_PROXY=http://127.0.0.1:7890
```

本地纯 `adk run`（不经云端）时，可将 `NGROK_URL` 设为 `http://127.0.0.1:8001`，`MCP_SERVER_URL` 设为 `http://127.0.0.1:8002/mcp`，无需 ngrok。

### 2.6 Playground 与资源名

| 资源 | 构造方式 |
|------|----------|
| REST Playground | Console → Agent Engine → 选择 `REST_AGENT_ENGINE_ID` 对应实例 |
| MCP Playground | Console → Agent Engine → 选择 `MCP_AGENT_ENGINE_ID` 对应实例 |
| Widget 调用的 Agent | `projects/{GCP_PROJECT_NUMBER}/locations/{GCP_LOCATION}/reasoningEngines/{REST_AGENT_ENGINE_ID}` |
| Skill 资源名 | `projects/{GCP_PROJECT_ID}/locations/{GCP_LOCATION}/skills/bilibili-rpa` |

ngrok 免费版每次重启域名可能变化，需同步更新 `.env` 及 GCP Agent Registry 中的 MCP Server URL。

---

## 3. 调用方式总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         用户 / 客户端入口                                 │
├──────────────┬──────────────┬──────────────┬──────────────┬──────────────┤
│  main.py     │  Cursor      │  GCP         │  index.html  │  curl /      │
│  本地 Agent  │  MCP         │  Playground  │  Web Widget  │  脚本直调    │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┘
       │              │              │              │              │
       ▼              ▼              ▼              ▼              ▼
   Gemini 本地    stdio MCP     云端 Agent     widget_server   server.py
   + main.py    bilibili_mcp   (REST/MCP)        :8000         :8001
       │              │              │              │              │
       └──────────────┴──────────────┴──────────────┴──────────────┘
                                    │
                                    ▼
                              main.py RPA
                         (Playwright + Excel)
```

| 场景 | 入口 | Agent 位置 | 本地需启动 | 适用人群 |
|------|------|-----------|-----------|---------|
| 一 | `python main.py` | 本地 Gemini | 无（直连 RPA） | 开发调试 |
| 二 | Cursor 对话 | Cursor 内置模型 | MCP stdio 自动拉起 | 日常开发 |
| 三 | `adk run` / GCP Playground | 云端 REST Agent | `server.py` + ngrok 8001 | 生产 REST 链路 |
| 四 | 浏览器打开 `index.html` | 云端 REST Agent | `server.py` + ngrok 8001 + `widget_server.py` | 演示 / 非技术用户 |
| 五 | GCP Playground (MCP Agent) | 云端 MCP Agent | `bilibili_mcp.py --http` + ngrok 8002 | MCP 标准协议 |
| 六 | curl / Postman | 无 Agent | `server.py` | API 集成测试 |
| 七 | `test_local_client.py` | 无 Agent | `bilibili_mcp.py`（stdio） | MCP 协议调试 |

**云端 Reasoning Engine（在 `.env` 配置）：**

| Agent | 环境变量 | 协议 |
|-------|----------|------|
| REST 版 | `REST_AGENT_ENGINE_ID` | REST → ngrok → `server.py` |
| MCP 版 | `MCP_AGENT_ENGINE_ID` | MCP → ngrok → `bilibili_mcp.py` |

---

## 4. 场景一：本地 Agent（main.py）

**特点**：LLM 与 RPA 全在本地运行，无需 ngrok，适合快速验证 RPA 逻辑。

### 启动步骤

```bash
source .venvAgents/bin/activate

# 可选：修改 main.py 末尾 user_command，或直接在代码里调用 run_bilibili_agent()
python main.py
```

### 登录（首次）

```bash
python main.py login
```

### 工作原理

- 使用 **Gemini 2.5 Pro**（Vertex AI）作为大脑
- 将 `read_up_names_from_excel`、`get_up_fans_data`、`write_fans_to_excel`、`save_user_preference` 注册为 Tool
- Agent 自主决定调用顺序并生成报告
- 长期记忆保存在 `agent_memory.json`

### 限制

- 需要本机可访问 Vertex AI
- 浏览器会在本地弹出（`headless=False`），抓取过程中请勿关闭窗口

---

## 5. 场景二：Cursor MCP（stdio）

**特点**：在 Cursor IDE 中直接让 AI 调用 B 站 RPA 工具，无需手动写脚本。

### 配置

项目已配置 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "bilibili-rpa": {
      "command": "python3",
      "args": ["mcp_server/bilibili_mcp.py"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

若 Cursor 无法找到 Python，将 `command` 改为你虚拟环境中的解释器路径，例如 `.venvAgents/bin/python`。

### 使用步骤

1. 确保已完成 [2.3 B 站登录](#23-b-站登录态必须) 和 [2.4 Excel](#24-excel-数据文件)
2. 在 Cursor 中打开本项目
3. 确认 MCP Server `bilibili-rpa` 已连接（Settings → MCP）
4. 在对话中直接发指令，例如：

   > 读取 Excel 里的 UP 主名单，抓取第一个 UP 主的粉丝数并写回表格

Cursor 会自动调用 `get_up_list`、`fetch_fans_data`、`write_excel`。

### 可用 MCP 工具

| 工具 | 参数 | 说明 |
|------|------|------|
| `get_up_list` | 无 | 返回 UP 主名称列表 |
| `fetch_fans_data` | `up_name: str` | 启动 Playwright 抓取粉丝数 |
| `write_excel` | `up_name`, `fans_count` | 写回 Excel |

### 注意

- stdio 模式由 Cursor 自动拉起进程，**不要在终端手动运行** `python mcp_server/bilibili_mcp.py`（会卡在等待输入）
- 与 `--http` 模式互不冲突，可同时存在

---

## 6. 场景三：云端 Agent + REST（经典路径）

**特点**：Agent 运行在 GCP，通过 REST API 远程驱动本机 RPA。与 Web Widget 共用同一条链路。

### 架构

```
GCP Reasoning Engine (cloud_agent)
    → HTTP requests
    → ngrok 公网 URL
    → server.py :8001
    → main.py RPA
```

### 本地启动（两个终端）

**终端 1 — REST 服务：**

```bash
source .venvAgents/bin/activate
python server.py
# 监听 http://0.0.0.0:8001
```

**终端 2 — ngrok 穿透：**

```bash
ngrok http 8001
```

将 ngrok 给出的 HTTPS 地址写入 `.env`：

```env
NGROK_URL=https://xxxx.ngrok-free.dev
```

### 调用方式 A：GCP Console Playground

1. 打开 GCP Console → Vertex AI → Agent Engine → 选择 `REST_AGENT_ENGINE_ID` 对应实例 → **Playground**
2. 确保本地 `server.py` 和 ngrok 8001 正在运行
3. 发送自然语言指令，例如：「帮我抓取所有 UP 主的粉丝数并写入 Excel」

### 调用方式 B：ADK 本地交互

```bash
./scripts/run_adk_cloud_agent.sh
# 或
adk run cloud_agent "帮我抓取所有 UP 主的粉丝数"
```

### 调用方式 C：重新部署 REST Agent

```bash
source .venvAgents/bin/activate
set -a && source .env && set +a
adk deploy agent_engine cloud_agent \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud REST Agent" \
  --agent_engine_id=$REST_AGENT_ENGINE_ID
```

### REST Agent 使用的工具

| 云端 Tool | 对应本地 API |
|-----------|-------------|
| `get_up_list_from_node` | `GET /api/get_up_list` |
| `fetch_fans_data_from_node` | `POST /api/fetch_fans_data` |
| `write_excel_to_node` | `POST /api/write_excel` |

---

## 7. 场景四：Web Widget 聊天界面

**特点**：浏览器悬浮聊天窗口，适合演示给非技术人员。

### 架构

```
index.html (浏览器)
    → POST http://localhost:8000/chat
    → widget_server.py
    → GCP Reasoning Engine (REST Agent)
    → ngrok → server.py → RPA
```

### 启动步骤（三个终端）

**终端 1 — 本地 RPA REST 节点：**

```bash
python server.py
```

**终端 2 — ngrok 穿透 8001：**

```bash
ngrok http 8001
```

更新 `.env` 中的 `NGROK_URL`。

**终端 3 — Widget 中转服务：**

```bash
python widget_server.py
# 监听 http://0.0.0.0:8000
```

启动时若 8001 未开，会提示：`请先运行 python3 server.py`。

### 打开界面

用浏览器直接打开项目根目录的 `index.html`（或本地 HTTP 服务器托管）。

- 右下角点击 💬 打开聊天窗口
- 输入指令并发送
- 回复来自云端 REST Agent

### 注意

- `widget_server.py` 从 `.env` 读取 `REST_AGENT_ENGINE_ID`、`GCP_PROJECT_NUMBER` 拼接 Agent 资源名
- 若要改用 MCP Agent，在 `.env` 设置 `AGENT_RESOURCE_NAME` 为 MCP Engine 全路径
- 需要本机 `gcloud auth application-default login` 有效

---

## 8. 场景五：云端 Agent + MCP（新路径）

**特点**：通过 MCP 标准协议调用本地 RPA，工具已在 GCP Agent Registry 注册。

### 架构

```
GCP Reasoning Engine (cloud_agent_mcp)
    → ADK McpToolset (Streamable HTTP)
    → ngrok 公网 URL /mcp
    → bilibili_mcp.py :8002
    → main.py RPA
```

### Agent Registry 配置（已完成）

| 字段 | 值 |
|------|-----|
| Name | Bilibili RPA MCP Server |
| MCP Server URL | `https://<ngrok域名>/mcp` |
| Tools | `get_up_list`, `fetch_fans_data`, `write_excel` |
| toolspec | `mcp_server/toolspec.json` |

### 本地启动（两个终端）

**终端 1 — MCP HTTP 服务：**

```bash
source .venvAgents/bin/activate
python mcp_server/bilibili_mcp.py --http
# 监听 http://0.0.0.0:8002/mcp
```

**终端 2 — ngrok 穿透 8002：**

```bash
ngrok http 8002
```

更新 `.env`：

```env
MCP_SERVER_URL=https://xxxx.ngrok-free.dev/mcp
NGROK_HOST=xxxx.ngrok-free.dev
```

若 ngrok 域名变化，还需在 GCP Console → Agent Registry 更新 MCP Server URL。

**修改 Host 白名单后必须重启 MCP 服务。**

### 调用方式 A：GCP Console Playground

1. 打开 GCP Console → Agent Engine → 选择 `MCP_AGENT_ENGINE_ID` 对应实例 → **Playground**
2. 确保本地 MCP 服务和 ngrok 8002 正在运行
3. 发送指令测试

### 调用方式 B：ADK 本地交互

```bash
./scripts/run_adk_cloud_agent_mcp.sh
# 或
adk run cloud_agent_mcp "帮我抓取所有 UP 主的粉丝数并写入 Excel"
```

### 调用方式 C：重新部署 MCP Agent

```bash
source .venvAgents/bin/activate
set -a && source .env && set +a
adk deploy agent_engine cloud_agent_mcp \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud MCP Agent" \
  --agent_engine_id=$MCP_AGENT_ENGINE_ID
```

### REST 与 MCP 路径对比

| | REST 路径 | MCP 路径 |
|---|-----------|----------|
| 本地服务 | `server.py` :8001 | `bilibili_mcp.py --http` :8002 |
| ngrok | `ngrok http 8001` | `ngrok http 8002` |
| 云端 Agent | `$REST_AGENT_ENGINE_ID` | `$MCP_AGENT_ENGINE_ID` |
| 工具协议 | 自定义 REST | MCP Streamable HTTP |

两条路径**可同时运行**，互不影响。

---

## 9. 场景六：直接调用 REST API（无 Agent）

**特点**：绕过 LLM，直接测试本地 RPA 接口，适合调试 `server.py`。

### 启动

```bash
python server.py
```

### API 示例

**获取 UP 主名单：**

```bash
curl http://localhost:8001/api/get_up_list
```

**抓取粉丝数：**

```bash
curl -X POST http://localhost:8001/api/fetch_fans_data \
  -H "Content-Type: application/json" \
  -d '{"up_name": "老番茄"}'
```

**写回 Excel：**

```bash
curl -X POST http://localhost:8001/api/write_excel \
  -H "Content-Type: application/json" \
  -d '{"up_name": "老番茄", "fans_count": "1800万"}'
```

API 文档（OpenAPI）：启动 `server.py` 后访问 `http://localhost:8001/docs`。

---

## 10. 场景七：MCP 本地联调测试

**特点**：不经过 Agent，直接验证 MCP Server 工具是否可用。

### 运行测试客户端

```bash
source .venvAgents/bin/activate
python mcp_server/test_local_client.py
```

脚本会：

1. 以 stdio 方式启动 `bilibili_mcp.py`
2. 列出可用工具
3. 调用 `fetch_fans_data(up_name="老番茄")` 并打印结果

### 修改测试目标

编辑 `mcp_server/test_local_client.py` 中的 `up_name` 参数即可。

---

## 11. 端口与环境变量速查

### 端口

| 端口 | 服务 | 命令 |
|------|------|------|
| 8000 | Web Widget 中转 | `python widget_server.py` |
| 8001 | REST RPA 节点 | `python server.py` |
| 8002 | MCP HTTP 服务 | `python mcp_server/bilibili_mcp.py --http` |
| 4040 | ngrok 管理界面 | `ngrok` 启动后自动可用 |

### 环境变量

| 变量 | 用途 | 说明 |
|------|------|------|
| `GCP_PROJECT_ID` | GCP 项目 ID | 所有 Vertex / deploy / skill_registry |
| `GCP_PROJECT_NUMBER` | 项目编号 | Widget `streamQuery` 资源路径 |
| `GCP_LOCATION` | 区域 | 默认 `us-central1` |
| `REST_AGENT_ENGINE_ID` | REST 云端 Agent | Playground / Widget |
| `MCP_AGENT_ENGINE_ID` | MCP 云端 Agent | Playground |
| `MCP_SERVER_REGISTRY_ID` | MCP Registry 记录 | 文档参考，Console 可查 |
| `NGROK_URL` | REST Agent → 本机 | 含 `https://`，无路径后缀 |
| `MCP_SERVER_URL` | MCP Agent → 本机 | 以 `/mcp` 结尾 |
| `NGROK_HOST` | MCP Host 白名单 | 不含 `https://` 和端口 |
| `VERTEX_HTTP_PROXY` | 可选代理 | 国内访问 Vertex 时使用 |
| `AGENT_RESOURCE_NAME` | 可选 | 覆盖 Widget 默认 Agent 路径 |

### 关键文件

| 文件 | 说明 |
|------|------|
| `~/Desktop/Up主名称.xlsx` | UP 主名单与粉丝数 |
| `bilibili_state.json` | B 站登录凭证 |
| `agent_memory.json` | 本地 Agent 长期记忆 |
| `cloud_agent_memory.json` | 云端 Memory Bank 相关 |

---

## 12. 示例指令

以下指令适用于 Playground、Web Widget、Cursor、ADK run 等所有 Agent 入口：

| 意图 | 示例指令 |
|------|---------|
| 完整流程 | 帮我读取 Excel 里所有 UP 主，逐个抓取粉丝数并写回表格，最后给我一份报告 |
| 单个 UP 主 | 查一下「老番茄」的粉丝数 |
| 仅读名单 | 读取 Excel 里有哪些 UP 主 |
| 记住偏好 | 记住：以后报告用简洁表格格式 |
| 问候 / 能力咨询 | 你能做什么？ |

Agent 典型执行顺序：

1. `get_up_list` / `get_up_list_from_node` → 获取名单  
2. 对每个 UP 主调用 `fetch_fans_data` / `fetch_fans_data_from_node`  
3. 成功后调用 `write_excel` / `write_excel_to_node`  
4. 汇总回复用户  

单次 `fetch_fans_data` 约需 **30–120 秒**（含浏览器启动与页面加载），请耐心等待。

---

## 13. 常见问题

### Q1：`bilibili_state.json` 不存在

```bash
python main.py login
```

### Q2：端口被占用（`address already in use`）

```bash
lsof -i :8002    # 查看占用进程（替换端口号）
kill <PID>       # 结束进程
```

### Q3：MCP 日志报 `Invalid Host header` / `421`

ngrok 域名未加入 Host 白名单。确认 `.env` 中 `NGROK_HOST` 正确，并**重启**：

```bash
python mcp_server/bilibili_mcp.py --http
```

### Q4：Playground 报 `Reasoning Engine Execution failed`

查看云端日志：

```bash
gcloud logging read \
  'resource.labels.reasoning_engine_id="'$REST_AGENT_ENGINE_ID'" AND severity>=ERROR' \
  --project=$GCP_PROJECT_ID --limit=5
```

常见原因：Agent 代码部署问题（已修复）、本地 ngrok / RPA 服务未启动。

### Q5：ngrok 域名变了怎么办？

1. 更新 `.env` 中的 `NGROK_URL` / `MCP_SERVER_URL` / `NGROK_HOST`
2. REST 路径：重启 `server.py` 即可（云端读 `.env` 需在部署时打包）
3. MCP 路径：重启 `bilibili_mcp.py --http`，并在 GCP Agent Registry 更新 MCP Server URL
4. 若使用 MCP 云端 Agent，通常无需重新部署 Agent（URL 在 Registry 侧）

### Q6：抓取失败 / 找不到粉丝数元素

B 站页面结构可能变化。检查 `main.py` 中 Playwright 选择器，或在本地直接运行：

```bash
python -c "from main import get_up_fans_data; print(get_up_fans_data('老番茄'))"
```

### Q7：REST 和 MCP 应该选哪个？

| 选择 | 建议 |
|------|------|
| REST | 已有 Web Widget、稳定生产、团队熟悉 FastAPI |
| MCP | 新集成、Agent Registry 治理、Cursor 本地开发、标准工具协议 |
| 两者并行 | 推荐：互不影响，逐步迁移 |

### Q8：Cursor MCP 与云端 MCP 的区别

| | Cursor MCP | 云端 MCP |
|---|-----------|----------|
| 传输 | stdio（本地进程） | HTTP + ngrok |
| 启动 | Cursor 自动拉起 | 手动 `bilibili_mcp.py --http` |
| 需要 ngrok | 否 | 是 |

---

## 附录：推荐日常使用组合

### 开发者本地调试

```bash
python main.py login          # 首次
# Cursor 对话 或
adk run cloud_agent_mcp "测试抓取"
```

### 演示给他人看

```bash
# 终端 1
python server.py

# 终端 2
ngrok http 8001

# 终端 3
python widget_server.py

# 浏览器打开 index.html
```

### 云端 MCP 完整链路

```bash
# 终端 1
python mcp_server/bilibili_mcp.py --http

# 终端 2
ngrok http 8002

# GCP Playground 发指令
```

---

更多架构与变更记录见 `feat.md`；MCP Server 技术细节见 `mcp_server/README.md`。
