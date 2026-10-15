---
name: tse-to-bitable
description: >
  指导 Agent 完成 TSE 工作记录 → 按用户提示词解读/筛选 → 飞书多维表格的跨 Agent 同步：
  读表结构 → 查 TSE → 解读筛选 → schema-first 映射 → 关联/人员补全 → 写入。
  当用户要求把 TSE 日报/跟进记录同步、导入、写入飞书多维表格时使用。
metadata:
  version: "1.1"
  author: SmartAgents
  tags:
    - tse
    - bitable
    - feishu
    - sync
    - daily-report
  adk_additional_tools:
    # 小智侧
    - query_tse_daily_reports_by_date
    - get_tse_customer_daily_reports
    - map_tse_daily_reports_to_bitable
    - ask_tse_workspace
    - task_card_upsert
    - task_card_complete
    # 小飞侧
    - feishu_bitable_parse_url
    - feishu_bitable_field_list
    - feishu_bitable_enrich_tse_records
    - feishu_bitable_write_tse_records
    - feishu_bitable_record_batch_create
---

# TSE 工作记录 → 飞书多维表格同步

> **跨 Agent 复合任务**：小智（调度员）负责查数据 + **按提示词解读/筛选** + 映射，小飞负责读表结构 + 补全 + 写入。  
> 必须 **schema-first**：先读目标表字段，再按字段映射，禁止先造假表头再硬写入。  
> Task Card：`deliverable=bitable_with_rows`（写入已有表或新建带行均用此枚举）。

## 协议与工具名

| 阶段 | 执行者 | 工具 |
|------|--------|------|
| 解析 URL | 小飞 | `feishu_bitable_parse_url` |
| 读表字段 | 小飞 | `feishu_bitable_field_list` |
| 查 TSE 日报 | 小智 | `query_tse_daily_reports_by_date` / `get_tse_customer_daily_reports` |
| 按提示词解读/筛选 | 小智 | 自然语言筛选；开放语义可用 `ask_tse_workspace` |
| 按字段映射 | 小智 | `map_tse_daily_reports_to_bitable` |
| 锁定主线 | 小智 | `task_card_upsert(deliverable=bitable_with_rows, pending_records_json=…)` |
| 补全关联/人员并写入 | 小飞 | `feishu_bitable_write_tse_records`（**全名**，禁止简称 write_tse_records） |
| （兼容）仅补全 | 小飞 | `feishu_bitable_enrich_tse_records` |
| （兼容）仅写入 | 小飞 | `feishu_bitable_record_batch_create` |

## 标准工作流

### 步骤 1：解析 URL + 读表结构（小飞）

小智 transfer 小飞，**只要求两件事**：

1. `feishu_bitable_parse_url(url=<用户链接>)` → 得到 `base_token` / `table_id`
2. `feishu_bitable_field_list(base_token, table_id)` → 把 **fields 原文**（含 `property.tableId`）交回小智

**禁止**此时写入；**禁止**臆造或复用旧 Base ID。

小飞完成后 transfer 回小智，在回复中附上 `base_token`、`table_id`、`fields` 原文。

### 步骤 2：查 TSE 跟进/日报（小智）

- 跨客户按时间段：`query_tse_daily_reports_by_date(date_from, date_to, owner_email?=…)`
- 单客户：`get_tse_customer_daily_reports(item_id, date_from, date_to)`

「本月」用 instruction 末尾 `month_start`～`month_end`，**禁止**用 2024 年。  
**0 条**：如实告知「该时段无跟进记录」，停止，不要空写表。

### 步骤 2.5：按用户提示词解读 / 筛选（小智，高频必做）

用户常要求「只要需跟进的」「提炼风险点」「按优先级」等——**禁止**把时段内全部日报无脑 map 进表。

1. 对照用户本轮提示词，从 reports 中筛出符合条件的子集（或提炼后的要点）
2. 开放语义分析可先 `ask_tse_workspace`，再把结论落到可写入的行
3. 仅将**筛选后**的 reports（或等价 create_records）进入下一步 map
4. 向用户一句话说明筛选口径（如「已按『需本周跟进』筛出 N 条」）

### 步骤 3：按字段映射（小智）

```
map_tse_daily_reports_to_bitable(
    fields_json=<步骤 1 fields 原文>,
    reports_json=<步骤 2.5 筛选后的 reports>,
)
```

输出：
- `records_json` — 可写字段的值（文本/日期已处理）
- `enrichment_hints` — 每行对应的 `customer_name` / `sales_name` / `owner`
- `unsupported_fields` — 系统只读/关联/人员列（跳过原因）
- `mapping_legend` — 每个字段从哪提取的

**二次抽取**：
- 「下一步跟进计划」等文本字段会从日报正文按小标题抽取，不依赖 Firestore 独立字段
- 未映射的文本列也会按字段名当小标题尝试从正文提取

映射后立刻：

```
task_card_upsert(
  goal=…,
  deliverable=bitable_with_rows,
  base_token=…,
  table_id=…,
  pending_records_json=<records_json>,
  next_action=feishu_bitable_write_tse_records,
)
```

### 步骤 4：补全关联/人员并写入（小飞）

小智 transfer 小飞，附上 Task Card 中的 coords + pending（或 `records_json` / `fields`）。

```
feishu_bitable_write_tse_records(
    base_token=…,
    table_id=…,
    fields_json=<fields 原文>,
    records_json=<步骤 3 的 records_json>,
    enrichment_hints_json=<可选>,
    create_missing_links=true,
)
```

内部会：
- **客户简称**：读关联表 → 匹配/自动创建 → `[{"id":"rec…"}]`
- **内部参与人**：通讯录 → `[{"id":"ou_…"}]`
- 剥离 `__tse_*` hint 字段后写入主表

若返回 `LINK_FIELDS_UNRESOLVED` / `LINK_FIELD_NOT_DETECTED` / `LINK_WRITE_NOT_PERSISTED`：
**禁止**谎称已写入客户简称；**禁止**让用户「手动点一下关联」当默认方案；把错误码与 `missing_links` / `resolutions` / `verify` 如实告诉用户后再修。

兼容拆步：`enrich_tse_records` → 仅用其返回的 `records_json` 做 `record_batch_create`（**禁止**用 map 原始 records 直写）。

### 新建空表路径

若用户要**新建**多维表再写入：解读后整理 `create_records` →
`task_card_upsert(pending_records_json=…)` → 小飞 `feishu_bitable_create` + **本轮**
`feishu_bitable_record_batch_create`。**禁止**对新建空表调用 `feishu_bitable_write_tse_records`。

## 对用户说话（防「精神分裂」感）

- **不要**在正式回答里粘贴整份 `records_json` / `create_records`
- **不要**复述另一位 Agent 已经说过的开场白（「好的我来处理」「请稍候」连环叠）
- transfer 时一句话交接即可；最终成功/失败由**最后一位**Agent 用一段完整话收束
- 成功只报：写了几条、关联字段是否已填、表链接；失败只报：错误码 + 下一步

## 常见问题处理

| 问题 | 处理 |
|------|------|
| `NOTEXIST` | `base_token` / `table_id` 用错了；重新 `parse_url` |
| `Changeset validation failed` | 某字段值类型不对；检查是否跳过了 enrich/write_tse |
| `LINK_FIELDS_UNRESOLVED` | 客户简称未关联成功；看 `resolutions`/`missing_links`，不要让用户手动点 |
| `LINK_FIELD_NOT_DETECTED` | field_list 未识别出 link；检查 type=`link`/18/21 与 property.tableId |
| `LINK_WRITE_NOT_PERSISTED` | 写入回读关联仍空；看 verify/repair；按官方 `[{id:rec…}]` 排查 |
| `MISSING_APP_SCOPE` | 缺 `base:record:read`；用户身份开通后重新 OAuth；不要只发个人授权糊弄 |
| 客户简称为空 | 曾用 map 原始 records 直写，或未识别 `type: link`；改用 `feishu_bitable_write_tse_records` |
| 下一步跟进计划为空 | 日报正文里没有「下一步」「跟进计划」等段落标题 |
| 内部参与人为空 | 通讯录搜不到该销售姓名；检查 `resolutions.unresolved` |
| 时段无记录 | 如实说 0 条，不要空写或编造客户 |

## 关键约束

- **schema-first**：必须先 `field_list`，再映射；禁止先臆造列名
- **先解读再写入**：必须执行步骤 2.5；禁止无脑全量 map
- **URL 锁定**：`parse_url` 一次，后续所有操作用它返回的 token；禁止臆造/混用
- **跨 Agent**：TSE 查询 = 小智；飞书操作 = 小飞；禁止小飞搜飞书文档冒充 TSE
- **日期**：用当前自然月/周，禁止默认 2024 年
- **只读字段**：创建人/创建时间/修改人/修改时间由飞书自动填，不写入

详细工具参数见 `references/tools.md`，工作流示意见 `references/workflow.md`。
