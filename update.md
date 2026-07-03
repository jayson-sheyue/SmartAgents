> 项目结构总览见 [`README.md`](README.md)。

# Update: Skill Registry 集成

本文档说明新增的 **GCP Skill Registry（技能注册表）** 能力。该功能与现有 REST / MCP / 本地 Agent 路径**完全独立**，不修改任何已有代码行为。

---

## 新增内容

| 路径 | 说明 |
|------|------|
| `skills/bilibili-rpa/SKILL.md` | B 站 RPA 工作流技能包（必需） |
| `skills/bilibili-rpa/references/` | 补充说明（工具对照、流程图） |
| `skill_registry.py` | Skill Registry 管理 CLI |
| `cloud_agent_mcp/skills/bilibili-rpa/` | 部署用 Skill 包（与 `skills/` 同步） |
| `update.md` | 本文档 |

---

## Skill Registry 是什么

与项目中已使用的 **Agent Registry（MCP Server 注册）** 不同：

| | Skill Registry | Agent Registry (MCP) |
|---|----------------|----------------------|
| 存什么 | 工作流说明、编排知识（`SKILL.md` + 资源） | 可执行工具端点（MCP URL + toolspec） |
| 作用 | 教 Agent **怎么做** | 提供 Agent **调什么** |
| 本项目 | `skill_registry.py` 上传 | 控制台注册 MCP Server |

两者配合使用时：Skill 提供 SOP，MCP/REST 提供执行能力。

---

## 环境要求

```bash
source .venvAgents/bin/activate

# 需 google-cloud-aiplatform >= 1.154.0（含 agentplatform 模块）
pip install "google-cloud-aiplatform>=1.154.0" python-dotenv

# GCP 认证
gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID
```

IAM 角色（项目级）：

- `roles/aiplatform.user` 或 `roles/aiplatform.viewer`（只读）
- 创建/更新/删除 Skill 需要写权限

可用区域：`us-central1`（与项目一致）、`europe-west4`、`us-east5`

---

## 快速开始

### 1. 校验本地 Skill 包

```bash
python skill_registry.py validate
```

检查项：

- `skills/bilibili-rpa/SKILL.md` 存在
- YAML frontmatter 含 `name`、`description`
- `name` 与目录名 `bilibili-rpa` 一致（仅小写字母、数字、连字符）

### 2. 上传到 Skill Registry

```bash
python skill_registry.py create
```

默认参数：

| 参数 | 默认值 |
|------|--------|
| skill_id | `bilibili-rpa` |
| display_name | `Bilibili RPA Skill` |
| skill_dir | `skills/bilibili-rpa/` |
| location | `us-central1` |

创建成功后输出资源名，形如：

```
projects/<GCP_PROJECT_ID>/locations/<GCP_LOCATION>/skills/bilibili-rpa
```

### 3. 查看与管理

> 全局参数（`--skill-id` 等）须写在子命令**之前**，例如：`python skill_registry.py --skill-id bilibili-rpa get`

```bash
# 列出所有 Skill
python skill_registry.py list

# 查看详情
python skill_registry.py get --skill-id bilibili-rpa

# 语义检索
python skill_registry.py retrieve --query "bilibili up主 粉丝数抓取"

# 更新（修改 SKILL.md 后）
python skill_registry.py update --skill-id bilibili-rpa

# 删除
python skill_registry.py delete --skill-id bilibili-rpa
```

---

## 环境变量

可在 `.env` 中配置：

```env
GCP_PROJECT_ID=<your-gcp-project-id>
GCP_LOCATION=us-central1
SKILL_ID=bilibili-rpa
SKILL_DIR=skills/bilibili-rpa
SKILL_DISPLAY_NAME=Bilibili RPA Skill
SKILL_DESCRIPTION=指导 Agent 完成 B 站 UP 主粉丝数采集工作流。
```

命令行参数 `--project`、`--location`、`--skill-id` 等可覆盖上述默认值。

---

## Skill 包结构

```
skills/bilibili-rpa/
├── SKILL.md              # 必需：元数据 + 工作流说明
└── references/
    ├── tools.md          # MCP / REST 工具对照
    └── workflow.md       # 流程说明
```

### SKILL.md 规范

- frontmatter `name` **必须**与目录名相同（`bilibili-rpa`）
- `name` 仅允许小写字母、数字、连字符（GCP 要求）
- GCP 上的 `skill_id` 同样使用 `bilibili-rpa`
- `metadata.adk_additional_tools` 列出关联工具名，供 ADK SkillToolset 动态启用

---

## 与现有 Agent 的关系

| Agent | Skill 集成 | 说明 |
|-------|-----------|------|
| `cloud_agent`（REST） | 未 attach | 行为不变 |
| **`cloud_agent_mcp`（MCP）** | **已 attach** | `SkillToolset` + `GCPSkillRegistry` + 本地兜底包 |
| 本地 / Cursor / Widget | 未使用 | 行为不变 |

### cloud_agent_mcp 中的 Skill 集成（已实现）

`cloud_agent_mcp/agent.py` 使用 ADK 2.3 的 `SkillToolset`：

- **GCP Skill Registry**：`GCPSkillRegistry(project_id, location)` 拉取云端 `bilibili-rpa`
- **本地兜底**：`cloud_agent_mcp/skills/bilibili-rpa/`（部署包内，与 `skills/bilibili-rpa/` 同步）
- **执行工具**：`McpToolset` + `PreloadMemoryTool` 作为 `additional_tools`，由技能 `metadata.adk_additional_tools` 动态启用

Agent 指令要求：处理 B 站 RPA 任务前先 `load_skill('bilibili-rpa')`，再按技能 SOP 调用 MCP 工具。

**重新部署**（修改 agent 或 skill 包后）：

```bash
# 1. 同步 skill 到部署目录（若改了 skills/bilibili-rpa/）
cp -R skills/bilibili-rpa/* cloud_agent_mcp/skills/bilibili-rpa/

# 2. 可选：更新 GCP Skill Registry
python skill_registry.py update

# 3. 部署
adk deploy agent_engine cloud_agent_mcp \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud MCP Agent" \
  --agent_engine_id=$MCP_AGENT_ENGINE_ID
```

Skill 资源名：`projects/<GCP_PROJECT_ID>/locations/<GCP_LOCATION>/skills/bilibili-rpa`

**推荐组合**：Skill（工作流 SOP）+ MCP Toolset（实际执行）+ Memory Bank（用户偏好）

---

## 完整调用矩阵（更新后）

| 场景 | 入口 | Skill Registry | 工具执行 |
|------|------|----------------|----------|
| 本地 Agent | `main.py` | 未使用 | 本地 Python 函数 |
| Cursor MCP | `.cursor/mcp.json` | 未使用 | MCP stdio |
| 云端 REST | `cloud_agent` | 可选 attach | REST → ngrok → server.py |
| 云端 MCP | `cloud_agent_mcp` | **已 attach** | Skill + MCP → ngrok → bilibili_mcp.py |
| Web Widget | `index.html` | 未使用 | 经 REST Agent |
| **Skill 管理** | **`skill_registry.py`** | **已使用** | 不涉及 RPA 执行 |

---

## 故障排查

### `Permission denied` / 403

确认账号具有 `roles/aiplatform.user` 且已 `gcloud auth application-default login`。

### `Skill name does not match directory name`

修改 `SKILL.md` frontmatter 的 `name:` 为 `bilibili-rpa`（与目录名一致）。

### `skill_id` 格式错误

须小写、连字符，例如 `bilibili-rpa`；不能以 `gcp-` 开头。

### 删除后 24 小时内无法复用同一 skill_id

GCP 限制，等待或使用新 ID。

### 创建/更新长时间等待

`create` / `update` 为 LRO（长时间运行操作），脚本默认 `wait_for_completion=True`，请耐心等待。

---

## 参考链接

- [创建和管理技能](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/create-manage?hl=zh-cn#python)
- [ADK Skill Registry 集成](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/adk-integration?hl=zh-cn)
- 项目内其他文档：`user_guide.md`（全场景使用指南）、`feat.md`（架构变更记录）
