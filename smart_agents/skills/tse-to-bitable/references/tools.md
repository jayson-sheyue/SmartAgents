# tse-to-bitable 工具参数

## 小智侧（TSE 查询 + 映射）

| 工具 | 主要参数 | 说明 |
|------|----------|------|
| `query_tse_daily_reports_by_date` | `date_from`, `date_to`, `sales_name?`, `owner_email?`, `limit_reports?=50` | 跨客户按日期查日报；服务端过滤 |
| `get_tse_customer_daily_reports` | `item_id`, `limit?`, `date_from?`, `date_to?` | 单客户日报 |
| `map_tse_daily_reports_to_bitable` | `fields_json`（必须）, `reports_json?`, `date_from?`, `date_to?`, `owner_email?` | 按表字段映射；输出 `records_json` + `enrichment_hints` |

### map 输出字段

| 字段 | 说明 |
|------|------|
| `records_json` | `{"create_records":[...]}` 可直接交给 enrich |
| `enrichment_hints` | 每行 `{customer_name, sales_name, owner}` 供 enrich 解析关联/人员 |
| `mapping_legend` | 每个表字段映射来源（`customer_name` / `date→ms` / `extracted_next_step_from_report` / `skipped_*`） |
| `unsupported_fields` | 跳过的字段及原因 + `linked_table_id` |
| `writable_field_names` | 实际写入了值的字段名列表 |

### 文本二次抽取

`map` 工具对文本类字段会从日报正文（`ai_generated_content` / `raw_draft`）按标题抽取：

- 「下一步跟进计划」→ 正文里 `下一步跟进计划：` / `下一步：` / `跟进计划：` / `待办` / `Next steps` 等段落
- 其它未映射的文本字段名也会当小标题尝试匹配

## 小飞侧（飞书多维表格）

| 工具 | 主要参数 | 说明 |
|------|----------|------|
| `feishu_bitable_parse_url` | `url` | 从链接解析 `base_token` / `table_id`；禁止臆造 |
| `feishu_bitable_field_list` | `base_token`, `table_id` | 读表字段（含 `property.tableId`）；须传完整原文给 enrich |
| `feishu_bitable_enrich_tse_records` | `base_token`, `table_id`, `fields_json`, `records_json`, `enrichment_hints_json?`, `create_missing_links?=true` | 补全关联/人员；关联失败返回 `LINK_FIELDS_UNRESOLVED` / `LINK_FIELD_NOT_DETECTED` |
| `feishu_bitable_write_tse_records` | 同上 | **推荐**：enrich + batch_create + 回读校验；失败可能 `LINK_WRITE_NOT_PERSISTED` |
| `feishu_bitable_record_batch_create` | `base_token`, `table_id`, `records_json` | 写入（须用 enrich 后的 records） |

### enrich 返回的 resolutions

| 键 | 说明 |
|----|------|
| `links.<字段名>.matched` | 客户名 → record_id 映射 |
| `links.<字段名>.catalog_size` | 关联表已有记录数 |
| `created_link_records` | 本次新建的客户行 `[{table_id, name, record_id, primary_field}]` |
| `persons.<字段名>` | 销售姓名 → open_id 映射 |
| `unresolved` | 无法解析的条目 `[{field, reason, ...}]` |

### 飞书多维表格字段类型对照

| 类型 | type code | 可否直接写 | enrich 处理 |
|------|-----------|-----------|-------------|
| 文本 | 1 | ✅ | 不处理 |
| 数字 | 2 | ✅ | 不处理 |
| 日期 | 5 | ✅（毫秒时间戳） | map 已转换 |
| 人员 | 11 | ⚠️ 需 `[{"id":"ou_…"}]` | enrich 通讯录解析 |
| 单向关联 | 18 | ⚠️ 需 `[{"id":"rec…"}]` | enrich 关联表匹配/创建 |
| 双向关联 | 21 | ⚠️ 需 `[{"id":"rec…"}]` | enrich 关联表匹配/创建 |
| 创建人 | 1001 | ❌ 系统只读 | 跳过 |
| 创建时间 | 1002 | ❌ 系统只读 | 跳过 |
| 修改人 | 1003 | ❌ 系统只读 | 跳过 |

### 必需 OAuth scope

`bitable_write`（含 `base:record:read` + `base:record:retrieve`）+ `contact`（搜人）

> 注意：开放平台需在 **应用身份** 与 **用户身份** 都开通 `base:record:read`；仅 user 有而 tenant 没有时，列关联表仍可能报 `app has not applied`。开通后需重新用户 OAuth 刷新令牌。
