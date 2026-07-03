# cloud_agent_mcp — 云端 MCP + Skill Agent 部署包

云端 Agent 通过 **SkillToolset** 加载 SOP，通过 **McpToolset** 调用本地 MCP Server 执行 RPA。

这是推荐的新路径；REST 路径见 [`../cloud_agent/`](../cloud_agent/)。

---

## 文件说明

| 文件 / 目录 | 作用 |
|-------------|------|
| `agent.py` | ADK Agent（**部署入口**） |
| `requirements.txt` | 部署依赖 |
| `skills/bilibili-rpa/` | 部署包内 Skill 副本（Registry 兜底） |

根目录 [`cloud_agent_mcp.py`](../cloud_agent_mcp.py) 用 `importlib` 加载本目录 `agent.py`（避免与包名冲突）。

---

## 三层集成（agent.py）

```python
# 1. 执行层 — MCP
bilibili_mcp_toolset = McpToolset(..., tool_filter=[...])

# 2. 编排层 — Skill
bilibili_skill = load_skill_from_dir(...)      # 本地包
gcp_skill_registry = GCPSkillRegistry(...)     # 云端 Registry

skill_toolset = SkillToolset(
    skills=[bilibili_skill],
    registry=gcp_skill_registry,
    additional_tools=[bilibili_mcp_toolset, PreloadMemoryTool()],
)

# 3. Agent 只挂一个 toolset
root_agent = Agent(..., tools=[skill_toolset])
```

| 组件 | 理由 |
|------|------|
| `load_skill_from_dir` | 容器内无 Registry 时仍有 SOP |
| `GCPSkillRegistry` | 与 GCP 注册表同步、可检索 |
| MCP 在 `additional_tools` | Skill 激活后才暴露 RPA tools |
| `system_instruction` 要求先 `load_skill` | 策略层，确保走 SOP |

---

## 调用链

```
Playground
    → load_skill('bilibili-rpa')   # 读 SKILL.md 工作流
    → get_up_list / fetch_fans_data / write_excel
    → McpToolset → MCP_SERVER_URL → ngrok :8002
    → mcp_server/bilibili_mcp.py
    → main.py
```

---

## 本地 adk run

```bash
# 终端 1 — MCP HTTP 服务
python mcp_server/bilibili_mcp.py --http

# 终端 2（国内建议设 VERTEX_HTTP_PROXY）
./scripts/run_adk_cloud_agent_mcp.sh
```

本机可设 `MCP_SERVER_URL=http://127.0.0.1:8002/mcp`（脚本默认已是此值）。  
云端 Playground 需 ngrok 8002 + `.env` 中 `MCP_SERVER_URL` / `NGROK_HOST`。

MCP 工具直接返回 **P0 envelope**（与 REST 相同契约），`system_instruction` + Skill v1.1 已说明 `ok/data/error` 处理。

---

## 部署前检查

```bash
# 1. 本地 MCP + ngrok
python mcp_server/bilibili_mcp.py --http
ngrok http 8002

# 2. .env
MCP_SERVER_URL=https://<域名>.ngrok-free.dev/mcp
NGROK_HOST=<域名>.ngrok-free.dev

# 3. 同步 Skill（若改过 skills/）
cp -R skills/bilibili-rpa/* cloud_agent_mcp/skills/bilibili-rpa/
python skill_registry.py update   # 可选

# 4. 部署
adk deploy agent_engine cloud_agent_mcp \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud MCP Agent" \
  --agent_engine_id=$MCP_AGENT_ENGINE_ID
```

| 项 | 环境变量 |
|----|----------|
| Engine ID | `MCP_AGENT_ENGINE_ID` |
| MCP Server ID（Registry） | `MCP_SERVER_REGISTRY_ID` |
| Skill ID | `bilibili-rpa` |

---

## Skill 源 vs 部署副本

| 位置 | 用途 |
|------|------|
| [`../skills/bilibili-rpa/`](../skills/bilibili-rpa/) | 编辑源 |
| `skills/bilibili-rpa/`（本目录） | 打进 Docker |
| GCP Skill Registry | 云端共享、`skill_registry.py` 管理 |

三者内容应保持一致。

---

## 升级改造

| 需求 | 步骤 |
|------|------|
| 改 SOP | `../skills/` → `skill_registry update` → cp 到本目录 skills/ |
| 改 MCP 连接 | `.env` + 可能改 GCP MCP Server URL |
| 新 MCP tool | `mcp_server/` + toolspec + SKILL `adk_additional_tools` + 本 agent |
| 改 load 策略 | `agent.py` instruction / SkillToolset 配置 → redeploy |

---

## 相关文档

- MCP Server：[`../mcp_server/README.md`](../mcp_server/README.md)
- Skill 资产：[`../skills/README.md`](../skills/README.md)
- Skill 集成说明：[`../update.md`](../update.md)
- 全场景指南：[`../user_guide.md`](../user_guide.md) 场景五
