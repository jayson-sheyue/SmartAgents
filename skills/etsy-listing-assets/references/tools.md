# Etsy 上架素材工具参数对照

## 进程内（`etsy_agent/agent.py`）

| 工具 | 主要参数 | 成功关键字段 |
|------|----------|----------------|
| `etsy_get_listing` | `listing_url_or_id` | `data.listing`, `data.existing_images` |
| `etsy_fetch_listing_images` | `listing_id` | `data.images`, `data.count` |
| `etsy_list_image_presets` | — | `data.presets` |
| `etsy_get_image_preset` | `preset_id` | `data.preset` |
| `etsy_save_image_preset` | `preset_id`, `label`, `scene_default` | `data.path` |
| `etsy_polish_scene_brief` | `scene_seed`, `title?` | `data.polished_scene` |
| `etsy_submit_scene_variants_job` | `listing_url_or_id`, `all_images?`, `preset_id?`, `custom_scene?` | `data.job_id` |
| `etsy_get_scene_job` | `job_id` | `data.status`, `data.result` |
| `etsy_list_scene_jobs` | `limit?`, `status?` | `data.jobs` |
| `etsy_wait_scene_job` | `job_id`, `timeout_sec?`, `verbose?` | `data.status`, `data.result.gcs_uris` |
| `etsy_read_scene_notifications` | `limit?` | `data.notifications` |

实现层：`etsy_agent/etsy_tools.py`、`etsy_agent/image_tools.py`、`etsy_agent/preset_tools.py`

## 默认行为

- 生图一律走 `etsy_submit_scene_variants_job`（异步）
- 默认 `upload_to_gcs=true`、`save_local_copy=true`
- 提交后**不要**自动 `etsy_wait_scene_job`，除非用户明确要求

## 路径与配置

- 本地图片：`~/Documents/EtsyData/generated/<listing_id>/scene_swap/`
- manifest：`~/Documents/EtsyData/etsy_listing_assets.xlsx`
- 用户预设：`~/Documents/EtsyData/presets/`（或 `ETSY_PRESET_DIR`）
- GCS：`ETSY_IMAGE_GCS_BUCKET` + `ETSY_IMAGE_GCS_PREFIX`（默认 `etsy/`）

## 风格优先级

```
custom_scene > preset_id > style > infer_style > default
```
