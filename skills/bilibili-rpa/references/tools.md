# 工具与协议对照（P0 v1.1）

## 统一 envelope

```json
{ "ok": true, "tool": "...", "data": {}, "error": null, "meta": {} }
```

## MCP 工具（本地 P0 已升级）

| 工具 | 主要参数 | 成功时关键字段 |
|------|----------|----------------|
| `get_up_list` | `excel_path?`, `sheet_name?`, `name_column?`, `limit?` | `data.up_names`, `meta.excel_path` |
| `fetch_fans_data` | `up_name`, `dry_run?` | `data.fans_count_display` |
| `write_excel` | `up_name`, `fans_count`, `excel_path?`, `write_mode?` | `data.rows_updated` |

服务：`python mcp_server/bilibili_mcp.py --http`（8002）

## REST API（本地 P0 已升级）

| 端点 | 方法 | 参数 |
|------|------|------|
| `/api/get_up_list` | GET | query: excel_path, sheet_name, name_column, limit |
| `/api/fetch_fans_data` | POST | body: up_name, dry_run |
| `/api/write_excel` | POST | body: up_name, fans_count, excel_path, sheet_name, target_column, write_mode |

服务：`python local_node/server.py`（8001）

响应体即为 envelope（不再包一层 `{status, data}`）。

## REST 工具（云端 REST Agent — Phase 2a 已升级 P0）

与 MCP 相同 envelope；Agent 函数名带 `_from_node` 后缀。

## Excel 路径护栏

仅允许：

- `~/Desktop/**`
- `~/Documents/BilibiliRPA/**`

## 示例（fetch 成功 data）

```json
{
  "up_name": "示例UP主",
  "status": "success",
  "fans_count_raw": "1800万",
  "fans_count_display": "1800万",
  "fans_count_value": 18000000
}
```

写入时使用 `fans_count_display`。
