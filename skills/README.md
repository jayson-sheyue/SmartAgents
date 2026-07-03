# skills — Skill 资产（SOP 源文件）

存放 **Agent Skills 规范** 下的技能包，描述「如何用工具完成 B 站 RPA 任务」，不包含可执行代码。

- **执行能力**在 [`main.py`](../main.py) + [`mcp_server/`](../mcp_server/) / [`local_node/`](../local_node/)
- **云端注册**用根目录 [`skill_registry.py`](../skill_registry.py)

---

## 目录结构

```
skills/
├── README.md              ← 本文件
└── bilibili-rpa/          ← 业务 Skill（skill_id = bilibili-rpa）
    ├── SKILL.md           ← 必需：frontmatter + 工作流
    └── references/
        ├── tools.md       ← MCP/REST 工具对照
        └── workflow.md    ← 流程图说明
```

部署包内有一份副本：[`../cloud_agent_mcp/skills/bilibili-rpa/`](../cloud_agent_mcp/skills/bilibili-rpa/)（`adk deploy` 打进容器）。

**维护规则**：改 `skills/bilibili-rpa/` 后执行：

```bash
python skill_registry.py update
cp -R skills/bilibili-rpa/* cloud_agent_mcp/skills/bilibili-rpa/
```

---

## SKILL.md 与实现的关系

Skill 是 **编排文档**，必须和工具契约一致：

| Skill 可以写 | Skill 不能写（除非先改代码） |
|-------------|---------------------------|
| 步骤顺序、异常策略、报告格式 | 任意 Excel 文件名（当前无参数） |
| 单个 UP 主跳过读名单 | 导出到其他系统（无对应 tool） |
| 只查不写（不调 write） | 超出 `adk_additional_tools` 的能力 |

详见 [`bilibili-rpa/SKILL.md`](bilibili-rpa/SKILL.md) 前置条件与 `metadata.adk_additional_tools`。

---

## skill_registry.py（云端治理 CLI）

| 命令 | 作用 | 操作对象 |
|------|------|----------|
| `validate` | 校验本地包 | 本地 `skills/` |
| `create` / `update` | 上传 GCP | 本地 → 云端 Registry |
| `list` / `get` / `retrieve` | 查询 | **云端** Registry |
| `delete` | 删除 | 云端 |

```bash
python skill_registry.py list
python skill_registry.py --skill-id bilibili-rpa get
python skill_registry.py retrieve --query "bilibili 粉丝"
```

GCP 控制台**暂无** Skill Registry UI，`list` 即云端清单。

云端资源名：

```
projects/<GCP_PROJECT_ID>/locations/<GCP_LOCATION>/skills/bilibili-rpa
```

---

## 谁在使用这个 Skill

| 消费者 | 是否 attach |
|--------|-------------|
| `cloud_agent_mcp` | ✅ `SkillToolset` + `GCPSkillRegistry` |
| `cloud_agent`（REST） | ❌ 工作流仍在 agent instruction 里 |
| Cursor MCP | ❌ 直接调 tool，不 load skill |

---

## 升级改造

1. 编辑 `skills/bilibili-rpa/SKILL.md`
2. `python skill_registry.py validate && python skill_registry.py update`
3. 同步到 `cloud_agent_mcp/skills/` 并 redeploy MCP Agent（若 instruction 或 additional_tools 有变）

更多说明：[`../update.md`](../update.md)
