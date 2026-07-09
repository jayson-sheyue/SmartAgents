# skills — Skill 资产（SOP 源文件）

存放 **Agent Skills 规范** 下的技能包，描述「如何用工具完成 B 站 RPA 任务」，不包含可执行代码。

- **执行能力**在 [`bilibili_agent/bilibili_tools.py`](../bilibili_agent/bilibili_tools.py) + [`mcp_server/`](../mcp_server/) / [`local_node/`](../local_node/)
- **云端注册**用根目录 [`skill_registry.py`](../skill_registry.py)

---

## Skill Registry 与 Agent Registry

| | Skill Registry | Agent Registry (MCP) |
|---|----------------|----------------------|
| 存什么 | 工作流说明、编排知识（`SKILL.md` + 资源） | 可执行工具端点（MCP URL + toolspec） |
| 作用 | 教 Agent **怎么做** | 提供 Agent **调什么** |
| 本项目 | `skill_registry.py` 上传 | GCP 控制台注册 MCP Server |

两者配合：Skill 提供 SOP，MCP/REST 提供执行能力。

---

## 目录结构

```
skills/
├── README.md              ← 本文件
├── bilibili-rpa/          ← B 站 Skill（skill_id = bilibili-rpa）
│   ├── SKILL.md
│   └── references/
└── etsy-review/           ← Etsy Skill（skill_id = etsy-review）
    ├── SKILL.md
    └── references/
```

部署包内有一份副本：

- 单领域：`bilibili_cloud_agent*/skills/`、`etsy_cloud_agent*/skills/`
- 调度树：`smart_agents/skills/`（[`deploy_smart_agents.sh`](../scripts/deploy_smart_agents.sh) 自动 rsync）

**维护规则**：改 `skills/` 后：

```bash
python skill_registry.py validate && python skill_registry.py update   # 可选：GCP Registry
# 单领域：cp 到对应 cloud_agent*/skills/
# 调度树：./scripts/deploy_smart_agents.sh（自动 rsync）
```

---

## SKILL.md 与实现的关系

Skill 是 **编排文档**，必须和工具契约一致：

| Skill 可以写 | Skill 不能写（除非先改代码） |
|-------------|---------------------------|
| 步骤顺序、异常策略、报告格式 | 任意 Excel 文件名（当前无参数） |
| 单个 UP 主跳过读名单 | 导出到其他系统（无对应 tool） |
| 只查不写（不调 write） | 超出 `adk_additional_tools` 的能力 |

**规范要点**：

- frontmatter `name` **必须**与目录名相同（`bilibili-rpa`）
- `name` 仅允许小写字母、数字、连字符
- `metadata.adk_additional_tools` 列出关联工具名，供 ADK `SkillToolset` 动态启用

详见 [`bilibili-rpa/SKILL.md`](bilibili-rpa/SKILL.md)。

---

## skill_registry.py（云端治理 CLI）

| 命令 | 作用 | 操作对象 |
|------|------|----------|
| `validate` | 校验本地包 | 本地 `skills/` |
| `create` / `update` | 上传 GCP | 本地 → 云端 Registry |
| `list` / `get` / `retrieve` | 查询 | **云端** Registry |
| `delete` | 删除 | 云端 |

```bash
# 全局参数写在子命令之前
python skill_registry.py validate
python skill_registry.py create
python skill_registry.py list
python skill_registry.py --skill-id bilibili-rpa get
python skill_registry.py retrieve --query "bilibili 粉丝"
python skill_registry.py update --skill-id bilibili-rpa
```

GCP 控制台**暂无** Skill Registry UI，`list` 即云端清单。

云端资源名：

```
projects/<GCP_PROJECT_ID>/locations/<GCP_LOCATION>/skills/bilibili-rpa
```

### 环境要求

```bash
source .venvAgents/bin/activate
pip install "google-cloud-aiplatform>=1.154.0" python-dotenv
gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID
```

IAM：`roles/aiplatform.user`（写操作需写权限）。可用区域：`us-central1`、`europe-west4`、`us-east5`。

### 环境变量（`.env`）

```env
GCP_PROJECT_ID=<your-gcp-project-id>
GCP_LOCATION=us-central1
SKILL_ID=bilibili-rpa
SKILL_DIR=skills/bilibili-rpa
SKILL_DISPLAY_NAME=Bilibili RPA Skill
```

命令行 `--project`、`--location`、`--skill-id` 等可覆盖默认值。

---

## 谁在使用这个 Skill

### bilibili-rpa

| 消费者 | 是否 attach |
|--------|-------------|
| `bilibili_agent`（进程内） | ✅ |
| `bilibili_cloud_agent` / `bilibili_cloud_agent_mcp` | ✅ |
| Cursor MCP | ❌ 直接调 tool |

### etsy-review

| 消费者 | 是否 attach |
|--------|-------------|
| `etsy_agent`（进程内） | ✅ |
| `etsy_cloud_agent` / `etsy_cloud_agent_mcp` | ✅ |
| `smart_agents`（E姐 / 阿B 经子 Agent） | ✅（`smart_agents/skills/`，deploy 脚本 rsync） |

Agent 指令要求：处理 B 站 RPA 前先 `load_skill('bilibili-rpa')`，再按 SOP 调用 REST/MCP 工具。

**重新部署**（修改 agent 或 skill 包后）：

```bash
cp -R skills/bilibili-rpa/* bilibili_cloud_agent/skills/bilibili-rpa/
cp -R skills/bilibili-rpa/* bilibili_cloud_agent_mcp/skills/bilibili-rpa/
python skill_registry.py update   # 可选

adk deploy agent_engine bilibili_cloud_agent \
  --project=$GCP_PROJECT_ID --region=$GCP_LOCATION \
  --display_name="Bilibili-Cloud-Agent" \
  --agent_engine_id=$BILIBILI_REST_AGENT_ENGINE_ID

adk deploy agent_engine bilibili_cloud_agent_mcp \
  --project=$GCP_PROJECT_ID --region=$GCP_LOCATION \
  --display_name="Bilibili Cloud MCP Agent" \
  --agent_engine_id=$BILIBILI_MCP_AGENT_ENGINE_ID
```

---

## 故障排查

| 现象 | 处理 |
|------|------|
| `Permission denied` / 403 | 确认 `roles/aiplatform.user` 且已 `gcloud auth application-default login` |
| `Skill name does not match directory name` | frontmatter `name:` 改为 `bilibili-rpa` |
| `skill_id` 格式错误 | 小写连字符；不能以 `gcp-` 开头 |
| 删除后 24h 内无法复用同一 ID | GCP 限制，等待或换新 ID |
| `create` / `update` 长时间等待 | LRO 操作，默认 `wait_for_completion=True` |

---

## 升级改造

1. 编辑 `skills/bilibili-rpa/SKILL.md`
2. `python skill_registry.py validate && python skill_registry.py update`
3. 同步到 `bilibili_cloud_agent*/skills/` 并 redeploy（若 instruction 或 `additional_tools` 有变）

---

## 参考链接

- [创建和管理技能（GCP）](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/create-manage?hl=zh-cn)
- [ADK Skill Registry 集成](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/adk-integration?hl=zh-cn)
- 操作手册：[`../user_guide.md`](../user_guide.md)
- ADK 概念：[`../docs/adk_learning_guide.md`](../docs/adk_learning_guide.md)