# 工作流示意图

```
用户指令
    │
    ▼
Agent 加载 bilibili-rpa 技能（SKILL.md 工作流说明）
    │
    ▼
get_up_list / get_up_list_from_node
    │
    ▼
对每个 UP 主 ──► fetch_fans_data / fetch_fans_data_from_node
    │                    │
    │                    ▼
    │              本地 Playwright RPA
    │                    │
    ▼                    ▼
write_excel / write_excel_to_node ◄── fans_count
    │
    ▼
汇总报告回复用户
```

## 与 Skill Registry 的关系

- **Skill Registry**：存储本工作流的**说明与编排知识**（即本目录）
- **Agent Registry (MCP)** 或 **REST API**：提供实际**执行工具**
- Agent 部署时需同时 attach 本 Skill 并配置 MCP/REST 工具，才能完成端到端任务
