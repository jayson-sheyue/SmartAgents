---
name: etsy-review
description: >
  指导 Agent 完成 Etsy 商品评论拉取与导出：校验凭证、解析 listing、
  分页拉取评论（默认 JSON）；需要表格时写 GCS。用户提供 Etsy 链接或 listing_id 时使用。
metadata:
  version: "2.0"
  author: SmartAgents
  tags:
    - etsy
    - reviews
    - gcs
    - api
  adk_additional_tools:
    - etsy_check_credentials
    - etsy_fetch_listing_reviews
    - etsy_write_reviews_excel
    - etsy_fetch_and_export_reviews
---

# Etsy 商品评论工作流（Cloud Run MCP）

## 工具

| 步骤 | MCP 工具 |
|------|----------|
| 凭证 | `etsy_check_credentials` |
| 拉取 JSON | `etsy_fetch_listing_reviews` |
| 写 GCS Excel | `etsy_write_reviews_excel` / `etsy_fetch_and_export_reviews` |

## 推荐流程

1. `etsy_check_credentials`
2. 默认 `etsy_fetch_listing_reviews` 返回 JSON 给用户分析
3. 用户要表格时：`etsy_fetch_and_export_reviews` → 读 `data.gcs_uri` / `signed_url`

产物在 GCS（`MCP_ARTIFACT_GCS_BUCKET`），不再写本机 `~/Documents`。
