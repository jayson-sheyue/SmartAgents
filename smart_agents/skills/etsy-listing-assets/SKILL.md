---
name: etsy-listing-assets
description: >
  Etsy 商品上架素材生图：解析 listing、风格预设、自然语言场景、
  同步 scene-swap 生图并上传 GCS。用户提供 Etsy 商品链接、换场景/出图时使用。
metadata:
  version: "2.0"
  author: SmartAgents
  tags:
    - etsy
    - listing
    - image-generation
    - presets
  adk_additional_tools:
    - etsy_check_credentials
    - etsy_get_listing
    - etsy_fetch_listing_images
    - etsy_list_image_presets
    - etsy_get_image_preset
    - etsy_save_image_preset
    - etsy_polish_scene_brief
    - etsy_generate_listing_scene_variants
---

# Etsy Listing 上架素材生图（同步 + GCS）

## 对话流程

1. 用户发送 **Etsy 商品链接** 或 `listing_id`
2. `etsy_get_listing` 确认商品与附图数量
3. `etsy_list_image_presets` 列出预设请用户选择（或用 `custom_scene`）
4. 确认范围：推荐 `all_images=true`，或主图 `count=1`
5. **一次同步调用** `etsy_generate_listing_scene_variants`（可能 1–3 分钟）：
   - `upload_to_gcs=true`（Cloud Run 强制）
   - `custom_scene` 时默认不润色
6. 汇报 `gcs_uri` / 本地路径（若有）/ `spec_ok`

## 风格优先级

```
custom_scene > preset_id > style > infer_style > default
```

## 工具返回格式

P0 envelope：`ok` / `data` / `error` / `meta`

## 前置条件

- `ETSY_KEYSTRING`、`GCP_PROJECT_ID`
- `ETSY_IMAGE_MODEL`、`ETSY_IMAGE_GCS_BUCKET`（或 `MCP_ARTIFACT_GCS_BUCKET`）
- MCP 在 Cloud Run 上运行

## 示例

```
etsy_generate_listing_scene_variants(
  listing_url_or_id,
  preset_id="holiday_warm",
  all_images=true,
  polish_with_llm=false,
  upload_to_gcs=true
)
```

异步 job 工具已下线，不要再调用 `etsy_submit_scene_variants_job`。
