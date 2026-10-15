# feishu-ops 工具参数

| 工具 | 主要参数 | 说明 |
|------|----------|------|
| `feishu_cli_status` | （无） | 检查 lark-cli 与应用凭证 |
| `feishu_oauth_status` | （无） | 当前会话用户是否已 OAuth（无 token 原文） |
| `feishu_oauth_start` | `capabilities` 或 `scopes` | Device Flow；**按任务最小权限**（如 `bitable_create,bitable_write`） |
| `feishu_oauth_complete` | `device_code`（可选） | 默认用 pending；用户授权后调用 |
| `feishu_app_scopes_remediate` | `scopes`（可选） | **应用级**：开通页链接 + 尝试 `scopes/apply` 向管理员申请 |
| `feishu_calendar_agenda` | `start`, `end`, `calendar_id` | **需用户 OAuth**；查今天请留空 start/end；返回 `server_today`/`queried_*` |
| `feishu_calendar_create` | `summary`, `start`, `end`, `attendee_ids`, `description` | **需用户 OAuth**；建日程并可邀 `ou_`/`oc_`/`omm_` |
| `feishu_calendar_freebusy` | `start`, `end`, `user_id` | **需用户 OAuth**；忙闲；`user_id` 空=自己 |
| `feishu_contact_search_user` | `query`, `page_size`, `has_chatted` | **需用户 OAuth**；按姓名/邮箱解析 `open_id` |
| `feishu_im_chat_search` | `query`, `member_ids`, `page_size`, `page_token` | **需用户 OAuth**；按群名/成员名或 `ou_` 找 `oc_`（**不是**消息正文搜索） |
| `feishu_im_send_text` | `text`, `chat_id` **或** `user_id` | Bot 发文本；`user_id` 为 `ou_…`，群为 `oc_…` |
| `feishu_im_messages_search` | `query`, `chat_id?`, `start?`, `end?`, `page_size?`, `page_token?`, `page_all?`, `page_limit?` | **需用户 OAuth**（含 `search:message`）；仅明确主题词；元词会返回 `USE_MESSAGES_LIST` |
| `feishu_im_chat_messages_list` | `chat_id`, `page_size?`, `page_token?`, `start?`, `end?`, `order?`, `as_user?=true` | **近 N 天全量聊天默认工具**；`as_user=true` 需用户 OAuth；有 `has_more` 须翻页 |
| `feishu_doc_search` | `query`, `page_size`, `page_token`, `filter_json` | **需用户 OAuth**；`docs +search`；可用 `intitle:` |
| `feishu_doc_fetch` | `doc`, `doc_format` | **需用户 OAuth** |
| `feishu_doc_create_markdown` | `content`, `title` | 有 UAT 用 user，否则 bot |
| `feishu_sheet_read` | `spreadsheet`, `range_a1` | **需用户 OAuth** |
| `feishu_sheet_write_csv` | `spreadsheet`, `csv_text`, `start_cell` | 有 UAT 用 user，否则 bot |
| `feishu_bitable_create` | `name`, `table_name`, `fields_json` | **需用户 OAuth**；新建 Base+首表字段；成功必含 `table_id`+`next_action` |
| `feishu_bitable_table_list` | `base_token` | **需用户 OAuth**；列出 tables；丢 table_id 时自愈，禁止甩给用户 |
| `feishu_bitable_parse_url` | `url` | 从多维表格链接解析 `base_token`/`table_id`（缺 table 时自动 list） |
| `feishu_bitable_field_list` | `base_token`, `table_id` | **需用户 OAuth**；写前看字段 |
| `feishu_bitable_record_list` | `base_token`, `table_id`, `limit?`, `offset?`, `filter_json?` | **需用户 OAuth**；列记录（关联解析） |
| `feishu_bitable_enrich_tse_records` | `base_token`, `table_id`, `fields_json`, `records_json`, `enrichment_hints_json?`, `create_missing_links?=true` | **需用户 OAuth**；补全关联/人员；失败码 `LINK_FIELDS_UNRESOLVED` |
| `feishu_bitable_write_tse_records` | 同上 | **需用户 OAuth**；enrich+写入一步完成（TSE 同步推荐） |
| `feishu_bitable_record_batch_create` | `base_token`, `table_id`, `records_json` | **需用户 OAuth**；`create_records` |
| `feishu_bitable_record_batch_update` | `base_token`, `table_id`, `records_json` | **需用户 OAuth**；`update_records` |
| `feishu_bitable_record_upsert` | `base_token`, `table_id`, `fields_json`, `record_id?` | **需用户 OAuth**；单条建/改 |

身份由 MCP 根据 `X-Adk-User-Id` + Firestore 令牌决定；CLI 调用带 `--as user|bot`。
