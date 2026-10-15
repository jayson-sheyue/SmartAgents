# 工作流示意

```
用户：抓全站热门并做选品分析
    ↓
Agent load_skill('bilibili-trend-rpa')
    ↓
fetch_hot_videos(source=popular, limit=50, export_excel=true)
    ↓
检查 ok → 读 data.videos + data.summary + data.excel_path
    ↓
输出《选品洞察报告》（运营视角，见 SKILL.md 步骤 2）
```

与 `bilibili-rpa`（粉丝 Excel）互不干扰；根据用户意图选择 Skill。
