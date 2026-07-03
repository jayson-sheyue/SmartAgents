# SmartAgents

B 站 UP 主粉丝数 **RPA + 多协议 Agent** 演示项目。  
核心思路：**`main.py` 只写一次 RPA**，上层用不同协议（本地 / REST / MCP / 云端 Agent）接入。

> **新手入口**：先看 [架构分层](#架构分层)，再按场景选 [调用路径](#调用路径速查)。  
> **操作手册**（端口、命令、排错）：[`user_guide.md`](user_guide.md)

---

## 架构分层

从下到上共四层，**改能力从下往上改，改 SOP 主要改 Skill 层**。

```
┌─────────────────────────────────────────────────────────────┐
│  L3 编排 / 治理                                              │
│  skills/          Skill Registry (skill_registry.py)         │
│  cloud_agent_mcp/ 云端 Agent + SkillToolset + MCP            │
│  cloud_agent/     云端 Agent + REST 包装函数                  │
├─────────────────────────────────────────────────────────────┤
│  L2 协议暴露（同一套 RPA，两种协议）                          │
│  local_node/      REST :8001  + Web Widget :8000             │
│  mcp_server/      MCP Server :8002 (stdio / HTTP)           │
├─────────────────────────────────────────────────────────────┤
│  L1 RPA 核心                                                │
│  main.py + rpa_tools.py   Playwright + P0 工具契约           │
└─────────────────────────────────────────────────────────────┘
```

| 层级 | 目录 / 文件 | 职责 |
|------|-------------|------|
| **L1 核心** | [`main.py`](main.py) + [`rpa_tools.py`](rpa_tools.py) | RPA 实现 + P0 envelope 三件套 |
| **L2 REST** | [`local_node/`](local_node/) | FastAPI 暴露 3 个 API；Widget 中转 |
| **L2 MCP** | [`mcp_server/`](mcp_server/) | MCP Server，动态暴露 3 个 tool |
| **L3 REST Agent** | [`cloud_agent/`](cloud_agent/) | 云端 ADK + HTTP → ngrok → REST |
| **L3 MCP Agent** | [`cloud_agent_mcp/`](cloud_agent_mcp/) | 云端 ADK + Skill + MCP |
| **L3 Skill 资产** | [`skills/`](skills/) | SOP 源文件 + Registry CLI |

---

## 目录结构

```
SmartAgents/
├── README.md                 ← 你在这里（总览）
├── main.py                   ← L1 RPA 核心（Playwright）
├── rpa_tools.py              ← L1 P0 工具契约（envelope + 三件套）
├── scripts/test_p0_local.py  ← P0 本地测试脚本
├── skill_registry.py         ← GCP Skill Registry CLI
├── cloud_agent.py            ← REST Agent 本地入口（→ cloud_agent/agent.py）
├── cloud_agent_mcp.py        ← MCP Agent 本地入口（→ cloud_agent_mcp/agent.py）
├── server.py                 ← 兼容 shim → local_node/server.py
├── widget_server.py          ← 兼容 shim → local_node/widget_server.py
│
├── local_node/               ← REST + Web Widget
├── mcp_server/               ← MCP Server
├── skills/                   ← Skill 源包 + 说明
├── cloud_agent/              ← REST 云端部署包
├── cloud_agent_mcp/          ← MCP+Skill 云端部署包
│
├── user_guide.md             ← 全场景操作指南
├── feat.md                   ← REST/MCP 双轨变更记录
├── update.md                 ← Skill Registry 集成说明
└── .cursor/mcp.json          ← Cursor stdio MCP 配置
```

**不要手动改** `cloud_agent_*_tmp*` 目录：为 `adk deploy` 临时生成，已在 `.gitignore` 忽略。

---

## 调用路径速查

| 你想… | 读哪个 README | 典型命令 |
|--------|---------------|----------|
| 本地调试 RPA | 本文 + `main.py` | `python main.py login` |
| Cursor 里用 MCP | [`mcp_server/README.md`](mcp_server/README.md) | Cursor 自动拉起 stdio |
| 云端 Agent + REST | [`cloud_agent/README.md`](cloud_agent/README.md) | `./scripts/run_adk_cloud_agent.sh` 或 Playground |
| 云端 Agent + MCP + Skill | [`cloud_agent_mcp/README.md`](cloud_agent_mcp/README.md) | `./scripts/run_adk_cloud_agent_mcp.sh` 或 Playground |
| Web 聊天演示 | [`local_node/README.md`](local_node/README.md) | `./scripts/run_widget.sh` → http://localhost:8000 |
| 管理云端 Skill | [`skills/README.md`](skills/README.md) | `python skill_registry.py list` |

### Reasoning Engine ID

在 `.env` 中配置（见 [`.env.example`](.env.example)）：

| Agent | 环境变量 | 本地依赖 |
|-------|----------|----------|
| REST `cloud_agent` | `REST_AGENT_ENGINE_ID` | REST :8001 |
| MCP `cloud_agent_mcp` | `MCP_AGENT_ENGINE_ID` | MCP :8002 |

---

## 升级改造建议（改哪里）

| 需求 | 先改 | 再改 |
|------|------|------|
| 换 Excel 路径 / 写回逻辑 | `main.py` | MCP + REST 暴露层（通常不用动） |
| 新增工具参数 | `main.py` → `mcp_server/` + `local_node/server.py` | `skills/.../SKILL.md`、`toolspec.json` |
| 改工作流 SOP | `skills/bilibili-rpa/SKILL.md` | `skill_registry.py update` |
| 改云端 Agent 行为 | `cloud_agent_mcp/agent.py` 或 `cloud_agent/agent.py` | `adk deploy ...` |
| 换 ngrok 域名 | `.env` | GCP MCP Server 注册 URL（MCP 路径） |

---

## 环境速览

```bash
source .venvAgents/bin/activate
pip install -r requirements.txt
playwright install chromium
gcloud auth application-default login
```

详见 [`user_guide.md`](user_guide.md) 第 2 节；环境变量模板见 [`.env.example`](.env.example)（复制为 `.env` 后填入真实值）。
