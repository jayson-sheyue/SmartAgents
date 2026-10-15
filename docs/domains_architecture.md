# Domains 架构（Cloud Run MCP）

```
smart_agents/agent.py          Dispatcher「小智」
domains/bilibili|etsy|feishu/  领域：manifest + registry + builder + L1 tools
skills/                        Skill 源（bilibili-trend / etsy-* / feishu-ops）
mcp_server/                    FastMCP 入口（同源进 Cloud Run 镜像）
services/*_mcp/                Dockerfile + requirements
```

## 数据流

```
Agent Engine / 飞书入站 bridge / Widget
  → 小智 transfer_to_agent
  → 阿B / E姐 / 小飞（McpToolset）
  → Cloud Run MCP URL
  → domains L1 tools
      → Bilibili API / Etsy API / Vertex / GCS
      → 飞书：lark-cli subprocess
           ├─ Bot：tenant_access_token（应用权限）
           └─ User：Device Flow OAuth → Firestore feishu_user_oauth/{user_id}
              → LARKSUITE_CLI_USER_ACCESS_TOKEN + --as user
```

与 [`integrations/feishu`](../integrations/feishu/README.md) **正交**：bridge 是「飞书→SmartAgents」入站；「小飞」是「SmartAgents→飞书」出站。

用户身份：ADK `session.user_id`（飞书侧 `feishu_{open_id}`）经 `McpToolset(header_provider)` 传 `X-Adk-User-Id`。OAuth 令牌存 **MCP 同项目 Firestore**（非 TSE 业务库），不进 Memory Bank。

## 能力面

| 专家 | Skill | MCP |
|------|-------|-----|
| 阿B | `bilibili-trend` | `fetch_hot_videos`, `export_hot_videos_excel`（GCS） |
| E姐 | `etsy-review`, `etsy-listing-assets` | 评论工具 + **同步** `etsy_generate_listing_scene_variants` |
| 小飞 | `feishu-ops` | Bot IM；用户 OAuth 日历/文档/表格；`feishu_oauth_start|complete|status` |

粉丝 RPA（Playwright）与 Etsy 异步 job 工具已下线。

## 部署

1. `./scripts/deploy_bilibili_mcp_cloudrun.sh`
2. `./scripts/deploy_etsy_mcp_cloudrun.sh`
3. `./scripts/deploy_feishu_mcp_cloudrun.sh`（需 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`；Cloud Run SA 需 Firestore 读写）
4. `.env` 写入三 URL + `MCP_ARTIFACT_GCS_BUCKET`
5. `./scripts/deploy_smart_agents.sh`

飞书开放平台需为应用申请对应用户 scope（日历读/建/忙闲、云文档、`search:docs:read`、`contact:user:search`、`im:chat:read`、多维表格 `base:app:create`/`base:record:create|update`/`base:field:read`/`base:table:*`、电子表格），并发布版本；已授权用户需重新 OAuth 才会带上新 scope。Bot 发群消息仍要求机器人已在目标群内。

复合任务若 `transfer_to_agent` 后专家未开口：TSE `smart_agents_runtime` 会自动续问一轮；transfer 返回 null 属 ADK 正常现象。
若本轮 `feishu_bitable_create` 成功但未写入记录，TSE 也会强制续跑催促 `batch_create`。
会话主线由 ADK `session.state` 中的 **Task Card**（`task_card_*` 工具）跨 Agent 保持。
