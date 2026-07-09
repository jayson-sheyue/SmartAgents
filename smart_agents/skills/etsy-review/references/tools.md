# Etsy 工具参数对照（P0 v1.1）

## MCP（`mcp_server/etsy_mcp.py` :8003）

| 工具 | 主要参数 | 成功关键字段 |
|------|----------|----------------|
| `etsy_check_credentials` | `probe?`, `probe_listing_id?` | `data.api_verified` |
| `etsy_fetch_listing_reviews` | `listing_id`, `limit?`, `max_pages?`, `dry_run?` | `data.reviews`, `data.count` |
| `etsy_write_reviews_excel` | `listing_id`, `reviews`, `excel_path?` | `data.excel_path` |
| `etsy_fetch_and_export_reviews` | `listing_url_or_id`, `max_pages?`, `excel_path?` | `data.fetch.count`, `data.write.excel_path` |

## REST（`local_node/server.py` :8001）

| 端点 | 方法 | Agent 工具名 |
|------|------|----------------|
| `/api/etsy_check_credentials` | GET | `etsy_check_credentials_from_node` |
| `/api/etsy_fetch_listing_reviews` | POST | `etsy_fetch_listing_reviews_from_node` |
| `/api/etsy_write_reviews_excel` | POST | `etsy_write_reviews_excel_from_node` |
| `/api/etsy_fetch_and_export_reviews` | POST | `etsy_fetch_and_export_reviews_from_node` |

响应体为 P0 envelope。

## 进程内（仅 `etsy_agent/`，无隧道）

| 工具 | 说明 |
|------|------|
| `etsy_*`（无 `_from_node`） | `etsy_agent/agent.py` 本地直连，不经过 REST/MCP |

实现层：`etsy_agent/etsy_tools.py`

## Excel 路径

默认 `~/Documents/EtsyData/etsy_reviews.xlsx`；允许 `~/Desktop/**`、`~/Documents/EtsyData/**`。
