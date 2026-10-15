# 工作流示意

```
用户：把本月 TSE 工作记录写入 https://…/base/xxx?table=tblYYY
    ↓
小智 transfer 小飞（只读表结构）
    ↓
小飞：feishu_bitable_parse_url(url) → base_token + table_id
      feishu_bitable_field_list(base_token, table_id) → fields 原文
      transfer 回小智（附 base_token / table_id / fields）
    ↓
小智：query_tse_daily_reports_by_date(date_from, date_to, owner_email?)
      → reports
    ↓
小智：map_tse_daily_reports_to_bitable(fields_json, reports_json)
      → records_json + enrichment_hints + mapping_legend
    ↓
小智 transfer 小飞（附 records_json / enrichment_hints / fields / base_token / table_id）
    ↓
小飞：feishu_bitable_write_tse_records(…, create_missing_links=true)
      → enrich 关联/人员 + batch_create 写入
      → 若 LINK_FIELDS_UNRESOLVED：停止并向用户说明原因
    ↓
小飞向用户汇报：写入 N 条，新建了哪些客户，哪些字段跳过
```

## 关键决策点

| 节点 | 判断 | 动作 |
|------|------|------|
| 步骤 1 失败 | `NEED_USER_OAUTH` | 发 verification_url，等用户授权 |
| 步骤 1 失败 | `NOTEXIST` | URL 解析错误，重新 parse_url |
| 步骤 3 结果 | `unsupported_fields` 非空 | 正常：系统只读/关联/人员列被跳过 |
| write_tse | `LINK_FIELDS_UNRESOLVED` | 客户简称未关联；看 missing_links，禁止谎称成功 |
| write_tse | `unresolved` 含 `missing_linked_table_id` | fields_json 缺 property；重传完整 field_list |
| write_tse | `unresolved` 含 `ambiguous_contact` | 同名多候选；向用户确认 |
| write_tse | `Changeset validation failed` | 字段类型不对；检查是否跳过 enrich |
