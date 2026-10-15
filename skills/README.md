# skills — Skill 资产（工作流 SOP）

存放 **Agent Skills** 规范下的技能包：描述「先做什么、再调哪些工具」，**不包含可执行代码**。

执行能力在 `domains/` + `mcp_server/`；Skill 教 Agent **如何编排**。

---

## 目录

```
skills/
├── bilibili-trend/         B 站全站热门选品（内部运营）
├── etsy-review/            Etsy 评论导出
├── etsy-listing-assets/    Etsy 换场景生图、预设
└── feishu-ops/             飞书出站：日历 / IM / Docs / Sheets（lark-cli Bot）
```

每个 Skill 含 `SKILL.md` 与 `references/tools.md`（工具契约）。

---

## Skill 与 MCP 的关系

| 组件 | 作用 |
|------|------|
| **Skill**（`SKILL.md`） | 工作流步骤、异常策略、报告格式 |
| **MCP**（Cloud Run / `:8002`–`:8004`） | 实际执行领域工具（飞书经 `lark-cli`） |
| **SkillToolset** | `load_skill` 把 SOP 注入上下文 |
| **McpToolset** | 调用远程工具 |

Agent instruction 普遍要求：**领域任务前先 `load_skill`，再按 SOP 调 MCP 工具**。

---

## 谁在使用

| Skill | 挂载的 Agent |
|-------|----------------|
| `bilibili-trend` | 调度树阿B |
| `etsy-review` | 调度树 E姐 |
| `etsy-listing-assets` | 调度树 E姐 |
| `feishu-ops` | 调度树小飞 |

构建逻辑：[`domains/bilibili/builder.py`](../domains/bilibili/builder.py)、[`domains/etsy/builder.py`](../domains/etsy/builder.py)、[`domains/feishu/builder.py`](../domains/feishu/builder.py)。  
Skill 路径解析：[`domains/shared/skill_resolver.py`](../domains/shared/skill_resolver.py)（优先 `skills/<id>/`）。

---

## 维护流程

1. 编辑 `skills/<skill-id>/SKILL.md`
2. 校验：

```bash
python skill_registry.py validate
```

3. （可选）上传 GCP Skill Registry：

```bash
python skill_registry.py update --skill-id bilibili-rpa
```

4. **调度树云端**：`./scripts/deploy_smart_agents.sh` 会 `rsync` 到 `smart_agents/skills/`
5. 若改了 `metadata.adk_additional_tools` 或 instruction 引用 → redeploy Agent

---

## SKILL.md 规范要点

- frontmatter `name` **必须**与目录名一致（如 `bilibili-rpa`）
- `name` 仅小写字母、数字、连字符
- `metadata.adk_additional_tools` 列出关联 MCP 工具名

示例：[`bilibili-rpa/SKILL.md`](bilibili-rpa/SKILL.md)。

---

## skill_registry.py（GCP 治理 CLI）

| 命令 | 作用 |
|------|------|
| `validate` | 校验本地包 |
| `create` / `update` | 上传到 GCP Skill Registry |
| `list` / `get` / `retrieve` | 查询云端 |

```bash
python skill_registry.py validate
python skill_registry.py list
python skill_registry.py retrieve --query "etsy 评论"
```

环境：`GCP_PROJECT_ID`、`GCP_LOCATION`、ADC 已登录。  
Registry **可选**；本地 `adk run` 直接读 `skills/` 目录即可。

---

## 加新 Skill

1. 新建 `skills/<skill-id>/SKILL.md` + `references/`
2. 在 `domains/<domain>/manifest.yaml` 的 `skills` 列表加入 id
3. 在对应 `builder.py` 的 `_skill_toolset()` 会随 `SKILL_IDS` 自动加载
4. `validate` → deploy / rsync

---

## 故障排查

| 现象 | 处理 |
|------|------|
| `未找到 Skill` | 确认 `skills/<id>/SKILL.md` 存在 |
| `name does not match directory` | 改 frontmatter `name` |
| Agent 不调某工具 | 检查 `adk_additional_tools` 与 MCP `tool_filter` |

---

## 相关文档

- [`../docs/domains_architecture.md`](../docs/domains_architecture.md)
- [`../user_guide.md`](../user_guide.md)
- [ADK Skill Registry 集成](https://cloud.google.com/gemini-enterprise/docs/skill-registry/adk-integration)
- [`../docs/agent_platform_learning_guide.md`](../docs/agent_platform_learning_guide.md)
