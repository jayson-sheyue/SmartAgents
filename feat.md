# feat.md — P0 工具契约增强（本地阶段）

> **状态**：P0 本地 L1/L2；**REST Agent（2a）**、**Widget（2c）**、**MCP Agent（2b）** 已对接 envelope。  
> **读代码**：P0 核心文件已加面向零基础读者的详细中文注释，建议顺序：`rpa_tools.py` → `scripts/test_p0_local.py` → `local_node/server.py` → `mcp_server/bilibili_mcp.py`。

---

## 1. 目标

增强 Agent 调用 RPA 工具时的灵活性，同时保持：

- 默认行为与旧版兼容（不传参 = 桌面 `Up主名称.xlsx`）
- REST 与 MCP **同一套参数与 envelope**
- 路径安全护栏（禁止任意文件系统访问）

---

## 2. 变更范围（本阶段）

| 已改 | 未改（下一阶段） |
|------|------------------|
| `rpa_tools.py`（新建） | `cloud_agent/agent.py` |
| `local_node/server.py` | `cloud_agent_mcp/agent.py` |
| `mcp_server/bilibili_mcp.py` | `local_node/widget_server.py` |
| `mcp_server/run_sync.py` | `cloud_agent.py` 根目录副本 |
| `mcp_server/toolspec.json` | GCP MCP Server 注册 |
| `skills/bilibili-rpa/` v1.1 | `skill_registry.py update` / redeploy |
| `scripts/test_p0_local.py` | `user_guide.md` 全量修订 |

`main.py` **未改** Playwright 逻辑；`run_bilibili_agent` 仍使用旧函数签名。

---

## 3. 架构

```
main.py (Playwright RPA，不变)
    ↑
rpa_tools.py (P0 契约：envelope + 参数 + 路径护栏)
    ↑
local_node/server.py   mcp_server/bilibili_mcp.py
    REST :8001              MCP :8002 / stdio
```

---

## 4. P0 能力明细

### 4.1 统一返回 envelope

```json
{
  "ok": true,
  "tool": "get_up_list",
  "data": { },
  "error": null,
  "meta": { }
}
```

失败：`ok=false`，`error.code` / `error.message` / `error.retryable`。

### 4.2 `get_up_list`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `excel_path` | str? | 桌面默认表 | 须在允许目录内 |
| `sheet_name` | str | Sheet1 | |
| `name_column` | str? | 第一列 | |
| `limit` | int? | 无 | 最多返回 N 条 |

成功：`data.up_names`, `data.count`, `meta.excel_path`。

错误码：`FILE_NOT_FOUND`, `PATH_NOT_ALLOWED`, `READ_FAILED`, `COLUMN_NOT_FOUND`。

### 4.3 `fetch_fans_data`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `up_name` | str | 必填 | |
| `dry_run` | bool | false | true 仅检查 `bilibili_state.json` |

成功：`data.fans_count_display`（写入 Excel 用此字段）、`fans_count_value`（解析值）、`meta.duration_ms`。

错误码：`LOGIN_STATE_MISSING`, `FETCH_FAILED`, `INVALID_INPUT`。

### 4.4 `write_excel`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `up_name` | str | 必填 | |
| `fans_count` | str | 必填 | |
| `excel_path` | str? | 桌面默认表 | |
| `sheet_name` | str | Sheet1 | |
| `target_column` | str | 粉丝数 | |
| `write_mode` | enum | update | `append_if_missing` 可追加新行 |

成功：`data.rows_updated`, `meta.write_mode`。

错误码：`UP_NOT_FOUND`（update 模式）、`FILE_NOT_FOUND`, `PATH_NOT_ALLOWED`, `WRITE_FAILED`。

### 4.5 Excel 路径护栏

仅允许：

- `~/Desktop/**`
- `~/Documents/BilibiliRPA/**`

---

## 5. REST API 变更

Base：`http://localhost:8001`

| 端点 | 变更 |
|------|------|
| `GET /api/get_up_list` | 新增 query 参数；响应为 envelope（**不再是** `{status, data: []}`） |
| `POST /api/fetch_fans_data` | body 新增 `dry_run`；响应为 envelope |
| `POST /api/write_excel` | body 新增 `excel_path`, `sheet_name`, `target_column`, `write_mode` |

OpenAPI：`http://localhost:8001/docs`

---

## 6. MCP 变更

- 三个 tool 参数与 REST 对齐，返回 envelope dict。
- `fetch_fans_data` 仍通过 `run_sync.py` 子进程跑 Playwright（避免 asyncio 冲突），子进程现输出完整 envelope JSON。
- `toolspec.json` 已更新（GCP 注册待 Phase 2）。

---

## 7. Skill 文档

`skills/bilibili-rpa/` 升至 **v1.1**，描述 envelope 与新参数。  
**未** upload 到 GCP Skill Registry（待你确认后再 `skill_registry.py update`）。

---

## 8. 本地测试指南

### 8.1 自动化契约测试（推荐先做）

```bash
cd /Users/apple/Desktop/Demo/SmartAgents
source .venvAgents/bin/activate
python scripts/test_p0_local.py
```

覆盖：默认读表、路径护栏、dry_run、write update/append（使用 `~/Documents/BilibiliRPA/_p0_test.xlsx`，**不修改**桌面默认表）。

### 8.2 真实 RPA 抓取（可选，会开浏览器）

```bash
python scripts/test_p0_local.py --live-fetch --up-name "老番茄"
```

前置：`python main.py login`，且网络/ B 站页面正常。

### 8.3 REST 手工 curl

```bash
# 终端 1
python local_node/server.py

# 读名单
curl -s "http://localhost:8001/api/get_up_list" | python -m json.tool

# 指定路径 + limit
curl -s "http://localhost:8001/api/get_up_list?limit=1" | python -m json.tool

# dry_run
curl -s -X POST http://localhost:8001/api/fetch_fans_data \
  -H "Content-Type: application/json" \
  -d '{"up_name":"老番茄","dry_run":true}' | python -m json.tool

# 真实抓取（慢）
curl -s -X POST http://localhost:8001/api/fetch_fans_data \
  -H "Content-Type: application/json" \
  -d '{"up_name":"老番茄"}' | python -m json.tool

# 写回（示例）
curl -s -X POST http://localhost:8001/api/write_excel \
  -H "Content-Type: application/json" \
  -d '{"up_name":"测试UP","fans_count":"123","write_mode":"append_if_missing","excel_path":"~/Documents/BilibiliRPA/_p0_test.xlsx"}' | python -m json.tool
```

### 8.4 MCP 本地

**stdio（Cursor）**：重启 Cursor 或 reload MCP，对话中让 Agent 调用 `get_up_list` / `fetch_fans_data(dry_run=true)`，检查返回 envelope。

**HTTP**：

```bash
python mcp_server/bilibili_mcp.py --http
python mcp_server/test_local_client.py   # 若脚本仍适用可试跑
```

### 8.5 验收清单

- [ ] `test_p0_local.py` 无报错退出
- [ ] 默认 `get_up_list` 返回真实桌面 Excel 名单
- [ ] `/etc/passwd` 路径被拒绝（PATH_NOT_ALLOWED）
- [ ] `dry_run=true` 在已 login 时 `ok=true`
- [ ] `write_mode=append_if_missing` 在测试 xlsx 追加行成功
- [ ] （可选）live-fetch 返回 `fans_count_display`
- [ ] Cursor MCP 能看到新参数（重启 MCP 后）

---

## 9. 兼容状态（更新于 Phase 2a）

| 组件 | 状态 |
|------|------|
| **云端 REST Agent** | ✅ `cloud_agent/agent.py` 已对接 P0 envelope |
| **`adk run cloud_agent`** | ✅ 同上；需 local_node + NGROK_URL |
| Web Widget | ✅ Phase 2c：`widget_server.py` + `index.html` 已升级 |
| **`adk run cloud_agent_mcp`** | ✅ Phase 2b；Skill v1.1 + MCP envelope |
| `main.py` 本地 Agent | 仍用旧函数，未改 |

---

## 10. Phase 2 进度

- [x] **2a** `cloud_agent/agent.py` — REST envelope + 新参数 + deploy  
- [x] **2b** `cloud_agent_mcp` + Skill 同步 + deploy  
- [x] **2c** Widget — `widget_server.py` v2 + `index.html` + `scripts/run_widget.sh`  
- [ ] GCP MCP toolspec 更新（可选）

---

## 11. 文件索引

| 文件 | 说明 |
|------|------|
| `rpa_tools.py` | P0 核心实现 |
| `scripts/test_p0_local.py` | 本地自动化测试 |
| `local_node/server.py` | REST v2 |
| `mcp_server/bilibili_mcp.py` | MCP v2 |
| `local_node/widget_server.py` | Widget 中转 v2（streamQuery + tool_events） |
| `local_node/index.html` | 聊天 UI |

项目总览：[`README.md`](README.md)
