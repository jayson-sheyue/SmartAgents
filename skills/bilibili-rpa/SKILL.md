---
name: bilibili-rpa
description: >
  指导 Agent 完成 B 站 UP 主粉丝数数据采集的标准工作流：读取 Excel 名单、
  逐个抓取粉丝数、写回表格并生成报告。当用户要求抓取 UP 主数据、更新粉丝数、
  或处理 Excel 中的 B 站 UP 主名单时使用此技能。
metadata:
  version: "1.2"
  author: SmartAgents
  tags:
    - bilibili
    - rpa
    - excel
  adk_additional_tools:
    - get_up_list
    - fetch_fans_data
    - write_excel
    - get_up_list_from_node
    - fetch_fans_data_from_node
    - write_excel_to_node
---

# B 站 UP 主粉丝数 RPA 工作流（P0 工具契约）

> **v1.2**：`bilibili_agent`（进程内）、`bilibili_cloud_agent`（REST）与 `bilibili_cloud_agent_mcp`（MCP）均已 attach 本 Skill；工作流统一由 SKILL 编排，不再依赖 Agent 硬编码 SOP。

## 协议与工具名

本 Skill 同时服务 **MCP Agent** 与 **REST Agent**。步骤逻辑相同，工具函数名按协议选择：

| 步骤 | MCP 工具名 | REST 工具名 |
|------|------------|-------------|
| 读名单 | `get_up_list` | `get_up_list_from_node` |
| 抓粉丝 | `fetch_fans_data` | `fetch_fans_data_from_node` |
| 写 Excel | `write_excel` | `write_excel_to_node` |

下文步骤以 **MCP 工具名** 书写；REST Agent 加载本 Skill 后，将上表对应替换为 `*_from_node` 即可。

## 统一返回格式

所有工具返回：

```json
{
  "ok": true,
  "tool": "get_up_list",
  "data": { },
  "error": null,
  "meta": { }
}
```

失败时 `ok=false`，读 `error.code` / `error.message`。常见 code：

| code | 含义 |
|------|------|
| `FILE_NOT_FOUND` | Excel 不存在 |
| `PATH_NOT_ALLOWED` | 路径不在 Desktop 或 ~/Documents/BilibiliRPA |
| `LOGIN_STATE_MISSING` | 需 `python -m bilibili_agent login` |
| `UP_NOT_FOUND` | write_mode=update 但表中无该 UP |
| `FETCH_FAILED` | RPA 抓取失败 |

## 前置条件

- Excel 默认：`~/Desktop/Up主名称.xlsx`（可通过 `excel_path` 覆盖，须在允许目录内）
- 登录态：`bilibili_state.json`
- 本地服务：REST `local_node/server.py:8001` 或 MCP `bilibili_mcp.py --http:8002`

## 标准工作流

### 步骤 0（可选）：健康检查

对用户大规模任务前，可先 `fetch_fans_data(up_name="任意", dry_run=true)` 检查登录态。

### 步骤 1：获取 UP 主名单

```
get_up_list(
  excel_path=None,      # 可选
  sheet_name="Sheet1",
  name_column=None,     # 默认第一列
  limit=None            # 可选限制条数
)
```

成功：读 `data.up_names`。若 `ok=false` 且 `FILE_NOT_FOUND`，提示用户检查路径。

**单 UP 查询**：用户只提一个 UP 主名时，**跳过本步**。

### 步骤 2：抓取粉丝数

```
fetch_fans_data(up_name="...", dry_run=false)
```

成功：使用 **`data.fans_count_display`** 作为写入值（不要用旧字段 `fans_data.总粉丝数`）。

### 步骤 3：写回 Excel

```
write_excel(
  up_name="...",
  fans_count="...",           # 来自 fetch 的 fans_count_display
  excel_path=None,
  sheet_name="Sheet1",
  target_column="粉丝数",
  write_mode="update"         # 或 append_if_missing
)
```

- `update`：仅更新表中已有 UP 主行
- `append_if_missing`：表中无该 UP 时追加一行

用户说「只查不写」：**不要调用 write_excel**。

### 步骤 4：报告

汇总 `ok` / 失败 `error.code`、成功条数、使用的 `meta.excel_path`。

## 示例用户意图

- 「用桌面默认表抓全部 UP 主并写回」→ get_up_list → 循环 fetch → write
- 「只查某 UP 主，别写表」→ 仅 fetch，步骤 4 口头报告
- 「查完把某某 UP 追加到表里」→ fetch + write(mode=append_if_missing)

详细参数见 `references/tools.md`。
