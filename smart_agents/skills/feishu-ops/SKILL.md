---
name: feishu-ops
description: >
  指导 Agent 通过 Cloud Run MCP + lark-cli 完成飞书出站操作：
  用户 OAuth（日历/文档/表格/多维表格/通讯录/搜群/搜聊天记录）、Bot 发/列消息。
  当用户要求查日历、约会议、建多维表格、按姓名找人/找群发消息、按话题汇总群聊、搜/读文档时使用。
metadata:
  version: "1.8"
  author: SmartAgents
  tags:
    - feishu
    - lark
    - oauth
    - calendar
    - bitable
    - contact
    - im
    - docs
    - sheets
  adk_additional_tools:
    - feishu_cli_status
    - feishu_oauth_status
    - feishu_oauth_start
    - feishu_oauth_complete
    - feishu_calendar_agenda
    - feishu_calendar_create
    - feishu_calendar_freebusy
    - feishu_contact_search_user
    - feishu_im_chat_search
    - feishu_im_send_text
    - feishu_im_chat_messages_list
    - feishu_im_messages_search
    - feishu_doc_search
    - feishu_doc_fetch
    - feishu_doc_create_markdown
    - feishu_sheet_read
    - feishu_sheet_write_csv
    - feishu_bitable_create
    - feishu_bitable_field_list
    - feishu_bitable_table_list
    - feishu_bitable_parse_url
    - feishu_bitable_record_list
    - feishu_bitable_enrich_tse_records
    - feishu_bitable_write_tse_records
    - feishu_bitable_record_batch_create
    - feishu_bitable_record_batch_update
    - feishu_bitable_record_upsert
    - task_card_get
    - task_card_upsert
    - task_card_complete
    - task_card_clear
---

# 飞书出站操作工作流（Bot + 用户 OAuth）

> **面向**：SmartAgents → 飞书开放平台。  
> **不是**：飞书机器人把用户消息转给小智的入站 bridge。

## 协议与工具名

| 步骤 | MCP 工具名 |
|------|------------|
| OAuth | `feishu_oauth_status` / `start` / `complete` |
| 查/建日程 / 忙闲 | `feishu_calendar_agenda` / `create` / `freebusy` |
| 搜人 / 搜群 / 发消息 | `feishu_contact_search_user` / `feishu_im_chat_search` / `feishu_im_send_text` |
| **按话题搜/列聊天** | `feishu_im_messages_search` / `feishu_im_chat_messages_list` |
| 云文档 | `feishu_doc_search` / `fetch` / `create_markdown` |
| 电子表格 Sheets | `feishu_sheet_read` / `write_csv` |
| 多维表格 Base | `parse_url` / `create` / `table_list` / `field_list` / `record_list` / `write_tse_records` / `enrich_tse_records` / `record_batch_*` / `record_upsert` |
| 主线 Task Card | `task_card_get` / `upsert` / `complete` / `clear`（会话 state，非 MCP） |

### OAuth 最小权限

- `feishu_oauth_start(capabilities="bitable_create,bitable_write")` 等，**按任务申请**，不要一次申请全部
- 能力名：`calendar_read` / `calendar_write` / `docs_read` / `docs_write` / `sheets_read` / `sheets_write` / `contact` / `im_chat` / `im_message_read` / `bitable_create` / `bitable_write`
- 工具鉴权失败时系统会按该工具自动发起对应 capabilities 的授权链接
- **禁止**引导用户一次授权「全部飞书能力」

## Task Card（deliverable 枚举）

开场 `task_card_upsert` **必须**写规范 `deliverable`（系统会按类型注入完成契约）：

| deliverable | 最短路径 |
|-------------|----------|
| `bitable_with_rows` | create → **本轮** batch_create → complete |
| `doc_search_answer` | doc_search → 交付 **items[].title/url** → complete（禁止建表/编造链接） |
| `doc_fetch` / `doc_created` | fetch/create → 交付 → complete |
| `calendar_event` / `calendar_agenda` | create/agenda → 播报 → complete |
| `im_message_sent` | search → send → complete |
| `im_chat_topic_summary` | chat_search → **无主题词用 messages_list 翻页** / 有主题词用 messages_search → 汇总 → complete |
| `sheet_updated` / `sheet_read` | write/read → complete |
| `oauth_setup` | start → 发 verification_url → 等用户 → complete |

先看注入的【Task Card】或 `task_card_get`；若 status=active/blocked，按 `next_action` / `phase` 推进。

## 接手后必须开口

被 `transfer_to_agent` 转来后：**立刻自然语言汇报**并继续任务。transfer 返回 `null` 正常，禁止静默结束。

## 群聊时间窗 / 话题汇总（强制）

用户说「某群最近 N 天聊天记录」「总结要点」「关于 XXX」时走本节。

1. `task_card_upsert(deliverable=im_chat_topic_summary, goal=…)`
2. `feishu_im_chat_search(query=群名)` → 取 `chat_id`（多候选先确认）
3. **分支 A — 无主题词**（「最近3天聊天记录 / 总结要点」）→ **必须**  
   `feishu_im_chat_messages_list(chat_id, start, end, page_size=50, as_user=true)`  
   - `start`/`end` 用 `YYYY-MM-DD`（按今天往回算 N 天）  
   - `has_more` → 继续 `page_token`，翻完再汇总  
   - **禁止**调用 `feishu_im_messages_search`（把「聊天记录」当 query 会 0 命中并误报无消息）
4. **分支 B — 有主题词**（如 BQCA）→ `feishu_im_messages_search`  
   （query=主题词，chat_id，start/end，`page_all=true`）；0 命中再走分支 A 复核
5. 汇总：日期 + 发送人 + 要点；区分待办 / 已结束
6. `NEED_REAUTH` / `USE_MESSAGES_LIST`：按错误码处理（授权或改 list）；禁止未重试就交回小智
7. `task_card_complete`

**禁止**：
- 用 `feishu_im_chat_search` 搜消息正文（它只搜群名/成员）
- 用 search 搜「聊天记录 / 要点 / 最近N天」
- 只调一次 list 第一页就宣称整段时间为空
- 未翻完时间窗就结案

## 多维表格（Base / Bitable）

用户说「多维表格 / bitable / Base」时走本节，**不要**用云文档或 Sheets 冒充。

### 新建 Base（create → 本轮写入，禁止只建不写）

1. `task_card_upsert(goal=…, deliverable=bitable_with_rows, pending_records_json='{"create_records":[…]}', next_action=create)`
2. `feishu_bitable_create(name=…, table_name=…, fields_json='[{"type":"text","name":"客户简称"},{"type":"text","name":"优先级"}]')`  
   - fields **只要** `name`/`type`/`options`；**禁止**塞 `property`（会报 Unrecognized key）
3. 从返回取 `base_token` / `table_id` / `url`（已校验）。若缺 table_id → `table_list`
4. **同一轮** `feishu_bitable_record_batch_create(base_token, table_id, records_json=Task Card 的 pending 或等价 create_records)`
5. `task_card_complete`，把链接告诉用户
6. **禁止**：对新建空表调用 `write_tse_records`；建完就 transfer；声称数据丢失（先看 Task Card）；让用户找 `table=`

### 写入已有 Base（含 TSE 同步）— 必须先读字段

仅当用户给了**已有表链接**时：

1. `feishu_bitable_parse_url` → `field_list`（fields 原文含 property 交给小智 map）
2. 小智 `map_tse_daily_reports_to_bitable` 产出 `records_json` + hints
3. 小飞 `feishu_bitable_write_tse_records(..., create_missing_links=true)`
4. `LINK_FIELDS_UNRESOLVED` 如实说明，禁止谎称已写入

**新建空表不要走本节。**

若 `feishu_bitable_*` / OAuth 相关错误：

- **`NEED_REAUTH` / `NEED_USER_OAUTH`（应用已有权限，缺个人授权）**  
  1. 若 `data.verification_url` 已有值：把该 URL 放进代码块发给用户，结束本轮  
  2. 用户在飞书授权页**批准本应用代为执行**即可  
  3. 用户回复「已授权」→ `feishu_oauth_complete` → **按 Task Card 立刻重试原操作**

- **`MISSING_APP_SCOPE`（应用未声明 / 租户未批准这些 API 权限）**  
  1. **禁止**再发个人 OAuth 链接  
  2. 把 `data.action_url`（或 `scope_enable_url`）放进代码块请用户点开：开通缺失 scope → 创建版本并提交管理员发布  
  3. 若 `data.admin_apply.ok=true`：告知「已自动向管理员提交审批」，等通过后用户回复「权限已开通」再重试  
  4. 也可主动调用 `feishu_app_scopes_remediate(scopes=…)`  
  5. **禁止**自动改成云文档/Markdown 表格冒充多维表格（除非用户明确同意降级）

- **`Cell value does not match any supported shape`**：先 `field_list` 看字段 type；日期用毫秒时间戳或改成 text 字段重试；禁止直接放弃并甩空表给用户

字段 `type` 常用：`text`、`number`、`datetime`、`select`（选项用 `options:[{"name":"…"}]`）。

## 日历 / 找人 / 找群 / 文档

- 查今天：`task_card_upsert(deliverable=calendar_agenda)`；agenda 的 start/end 留空
- 约会议：`deliverable=calendar_event`；contact 搜人 →（可选 freebusy）→ `calendar_create`
- 发私聊/群消息：`deliverable=im_message_sent`；先 search 再 send；多候选先确认
- 搜文档：`deliverable=doc_search_answer` → `feishu_doc_search` → 按 **`data.items[].title` + `items[].url`** 列表交付 → `task_card_complete`
  - 链接**只能**来自工具返回的 `url`；`count=0` 如实说未找到；禁止编造；禁止建多维表

## 安全

- 写操作前确认对象；多候选不要擅自执行；**Task Card 已锁定且用户已同意时不得再次征求方案**
- 禁止群发、删 Base、改高级权限（本期未暴露）

详细参数见 `references/tools.md`。
