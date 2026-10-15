# 热门选品工具（P0）

## MCP 工具

| 工具 | 主要参数 | 成功时关键字段 |
|------|----------|----------------|
| `fetch_hot_videos` | `source?`, `period?`, `limit?`, `rid?`, `export_excel?`, `excel_path?` | `data.videos`, `data.summary`, `data.excel_path` |
| `export_hot_videos_excel` | `videos`, `excel_path?` | `data.excel_path`, `data.rows_written` |

服务：`python mcp_server/bilibili_mcp.py --http`（8002）

## source / period

| source | 含义 | period |
|--------|------|--------|
| `popular`（默认） | 综合热门推荐流 | 忽略 |
| `ranking` | 全站排行榜 | `day` 日榜 / `week` 周榜 |

`rid=0` 表示全站；其他分区 id 可后续扩展。

## 单条 video 字段

| 字段 | 说明 |
|------|------|
| `rank` | 排名 |
| `bvid` / `url` | BV 号与链接 |
| `title` | 标题 |
| `partition` | 分区 |
| `up_name` | UP 主 |
| `duration_display` | 时长 mm:ss |
| `view` / `like` / `coin` / `favorite` / `share` | 互动绝对值 |
| `like_rate_pct` 等 | 互动率（%） |
| `engagement_score` | 内部加权互动分（选品排序用） |
| `rcmd_reason` | 推荐理由（popular 可能有） |

## summary 字段（供报告引用）

- `partition_distribution`：分区计数
- `median_duration_min`：时长中位数（分钟）
- `median_view`：播放中位数
- `median_engagement_score`：互动分中位数
- `top_engagement_bvids` / `top_engagement_titles`：互动分 Top5

## Excel 输出列

排名、标题、BV号、链接、分区、UP主、时长、发布时间、播放、点赞、投币、收藏、分享、弹幕、评论、点赞率%、投币率%、收藏率%、互动分、推荐理由、数据源

默认目录：`~/Documents/BilibiliRPA/`
