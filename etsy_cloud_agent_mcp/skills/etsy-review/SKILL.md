---
name: etsy-review
description: >
  指导 Agent 完成 Etsy 商品评论拉取与 Excel 导出：校验 API 凭证、解析 listing_id、
  分页拉取评论、写入表格并汇总报告。当用户提供 Etsy 商品链接或 listing_id、
  要求导出评论、分析评价时使用此技能。
metadata:
  version: "1.1"
  author: SmartAgents
  tags:
    - etsy
    - reviews
    - excel
    - api
  adk_additional_tools:
    - etsy_check_credentials
    - etsy_fetch_listing_reviews
    - etsy_write_reviews_excel
    - etsy_fetch_and_export_reviews
    - etsy_check_credentials_from_node
    - etsy_fetch_listing_reviews_from_node
    - etsy_write_reviews_excel_from_node
    - etsy_fetch_and_export_reviews_from_node
---

# Etsy 商品评论拉取工作流（P0 工具契约）

> **v1.1**：REST / MCP 双轨；凭证与 Excel 在本机节点执行，云端 Agent 经 Cloudflare Tunnel 调用。

## 协议与工具名

| 步骤 | MCP 工具名 | REST 工具名 |
|------|------------|-------------|
| 凭证检查 | `etsy_check_credentials` | `etsy_check_credentials_from_node` |
| 拉取评论 | `etsy_fetch_listing_reviews` | `etsy_fetch_listing_reviews_from_node` |
| 写 Excel | `etsy_write_reviews_excel` | `etsy_write_reviews_excel_from_node` |
| 拉取+导出 | `etsy_fetch_and_export_reviews` | `etsy_fetch_and_export_reviews_from_node` |

下文步骤以 **MCP 工具名** 书写；REST Agent 加载后改用 `*_from_node`。

## 本地服务

- REST：`local_node/server.py` :8001 → `/api/etsy_*`
- MCP：`python mcp_server/etsy_mcp.py --http` :8003
- 凭证：本机 `.env` 的 `ETSY_KEYSTRING` / `ETSY_SHARED_SECRET`（不上云）

## 统一返回格式

所有工具返回：

```json
{
  "ok": true,
  "tool": "etsy_fetch_listing_reviews",
  "data": { },
  "error": null,
  "meta": { }
}
```

失败时 `ok=false`，读 `error.code` / `error.message`。常见 code：

| code | 含义 |
|------|------|
| `ETSY_API_KEY_MISSING` | `.env` 未配置 Key |
| `ETSY_API_KEY_PENDING` | Key 未激活或 Secret 错误 |
| `ETSY_AUTH_FAILED` | 认证失败 |
| `ETSY_NOT_FOUND` | listing 不存在 |
| `ETSY_NO_REVIEWS_FOUND` | 无评论或 ID 不正确 |
| `ETSY_NETWORK_ERROR` | 网络异常（可重试） |
| `INVALID_INPUT` | listing_id / URL 无法解析 |
| `PATH_NOT_ALLOWED` | Excel 路径不在允许目录 |
| `WRITE_FAILED` | Excel 写入失败 |

## 前置条件

- `.env` 配置 `ETSY_KEYSTRING` + `ETSY_SHARED_SECRET`（或 `ETSY_API_KEY=key:secret`）
- Etsy Developer App 状态为 **Personal Access**
- 默认 Excel：`~/Documents/EtsyData/etsy_reviews.xlsx`
- 允许目录：`~/Desktop/**`、`~/Documents/EtsyData/**`
- 本地节点：REST `local_node/server.py:8001` 或 MCP `etsy_mcp.py --http:8003`

## 标准工作流

### 步骤 0（推荐）：凭证检查

任务开始前或用户反馈鉴权问题时：

```
etsy_check_credentials(probe=true)
```

成功：读 `data.api_verified`。若为 `false` 且 `ok=false`，提示用户检查 `.env` 与 Etsy 后台状态。

### 步骤 1：解析 listing_id

从用户输入提取数字 ID：

- URL：`https://www.etsy.com/listing/786582119/...` → `786582119`
- 纯数字：直接使用

无法解析时向用户索要正确链接或 ID。

### 步骤 2：拉取并导出（推荐一步到位）

大多数场景使用：

```
etsy_fetch_and_export_reviews(
  listing_url_or_id="https://www.etsy.com/listing/786582119/...",
  limit=25,
  max_pages=3,
  excel_path=null,
  dry_run=false
)
```

成功：读 `data.fetch.count`、`data.write.excel_path`、`data.write.total_rows`。

用户仅想预览流程、不拉真实数据时：`dry_run=true`。

### 步骤 2b（分步，可选）

需要中间检查评论内容时：

```
etsy_fetch_listing_reviews(
  listing_id="786582119",
  listing_url=null,
  limit=25,
  max_pages=3,
  dry_run=false
)
→ etsy_write_reviews_excel(
  listing_id="786582119",
  reviews=[...],   # 来自上一步 data.reviews
  excel_path=null,
  deduplicate=true
)
```

### 步骤 3：报告

汇总：

- listing_id / listing_url
- 拉取评论数（`data.fetch.count` 或 `data.count`）
- Excel 路径与总行数
- 失败条目的 `error.code`

## 示例用户意图

- 「把这个 Etsy 链接的评论导到 Excel」→ check_credentials → fetch_and_export_reviews
- 「先别写文件，看看能不能拉到」→ fetch_listing_reviews（或 fetch_and_export dry_run）
- 「多翻几页，最多 5 页」→ max_pages=5
- 「导出到我桌面的 reviews.xlsx」→ excel_path 须在允许目录内

## 限流提示

Personal App 约 **5 QPS / 5K QPD**；`max_pages` 不宜过大，默认 3 即可。

详细参数见 `references/tools.md`。
