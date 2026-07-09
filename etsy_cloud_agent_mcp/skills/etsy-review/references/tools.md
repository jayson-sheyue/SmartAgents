# Etsy 工具参数对照（P0 v1.0）

## 统一 envelope

```json
{ "ok": true, "tool": "...", "data": {}, "error": null, "meta": {} }
```

## 进程内工具（etsy_agent 本地 ADK）

| 工具 | 主要参数 | 成功时关键字段 |
|------|----------|----------------|
| `etsy_check_credentials` | `probe?` | `data.api_verified`, `data.masked_key` |
| `etsy_fetch_listing_reviews` | `listing_id`, `listing_url?`, `limit?`, `max_pages?`, `min_created?`, `max_created?`, `dry_run?` | `data.reviews`, `data.count` |
| `etsy_write_reviews_excel` | `listing_id`, `reviews`, `listing_url?`, `excel_path?`, `sheet_name?`, `deduplicate?` | `data.excel_path`, `data.total_rows` |
| `etsy_fetch_and_export_reviews` | `listing_url_or_id`, `limit?`, `max_pages?`, `excel_path?`, `dry_run?` | `data.fetch.count`, `data.write.excel_path` |

实现层：`etsy_agent/etsy_tools.py`

## Excel 路径护栏

仅允许：

- `~/Desktop/**`
- `~/Documents/EtsyData/**`

默认：`~/Documents/EtsyData/etsy_reviews.xlsx`

## 评论行字段（data.reviews[]）

`platform`, `listing_id`, `listing_url`, `review_id`, `shop_id`, `rating`,
`review_text`, `language`, `buyer_user_id`, `created_timestamp`,
`updated_timestamp`, `image_url`, `scraped_at`

## 示例（fetch 成功 data 摘要）

```json
{
  "platform": "etsy",
  "listing_id": "786582119",
  "listing_url": "https://www.etsy.com/listing/786582119/...",
  "reviews": [ { "review_id": "...", "rating": 5, "review_text": "..." } ],
  "count": 15
}
```
