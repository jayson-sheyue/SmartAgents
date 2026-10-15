---
name: bilibili-trend
description: >
  指导 Agent 完成 B 站全站热门/排行榜视频抓取与内部运营选品分析。
  当用户要求热点、爆款、热门视频、排行榜、选品分析、内容趋势洞察时使用。
metadata:
  version: "2.0"
  author: SmartAgents
  tags:
    - bilibili
    - trend
    - hot
    - ops
  adk_additional_tools:
    - fetch_hot_videos
    - export_hot_videos_excel
---

# B 站全站热门选品工作流（公开 API）

> **面向**：内部运营选品、内容趋势研判。粉丝 Excel RPA 已下线。

## 协议与工具名

| 步骤 | MCP 工具名 |
|------|------------|
| 抓取热门 | `fetch_hot_videos` |
| 单独导出 GCS | `export_hot_videos_excel` |

## 统一返回格式

```json
{
  "ok": true,
  "tool": "fetch_hot_videos",
  "data": { "videos": [], "summary": {}, "gcs_uri": "..." },
  "error": null,
  "meta": {}
}
```

## 前置条件

- **无需** B 站登录态（走公开 API）
- MCP 部署在 Cloud Run；Excel 产物写 GCS（`MCP_ARTIFACT_GCS_BUCKET`）

## 标准工作流

### 步骤 1：抓取全站热门

默认 **只返回 JSON**（`export_excel=false`）：

```
fetch_hot_videos(source="popular", limit=50, export_excel=false)
```

需要表格时：

```
fetch_hot_videos(source="popular", limit=50, export_excel=true)
```

成功时读取 `data.videos`、`data.summary`；若导出则读 `data.gcs_uri` / `data.signed_url`。

### 步骤 2：生成《选品洞察报告》

基于工具返回字段写运营报告，勿编造未返回的数据。

### 步骤 3（可选）：仅导出

`export_hot_videos_excel(videos=...)` → GCS URI。

## 注意

- 粉丝数查询已下线，勿调用已移除的 RPA 工具
- `engagement_score` 为内部加权互动分

详细字段见 `references/tools.md`。
