# TSE 数据访问路径（Lab-00）

> 数据访问与权限约束参见本说明及对应工具代码。
> 运行时入口：确定性工具 `smart_agents/tse_tools.py`；禁止为演示再开平行业务查询路径。

---

## 一句话职责边界

| 路径 | 一句话 |
|------|--------|
| **P0 TSE API + 确定性工具** | 业务正确性与权限语义的主路径：用户可见数据、开放语义、大盘；Agent 只调场景工具，不直连库。 |
| **P1 Firestore MCP（`fs_*` / `tse_store`）** | 只读探索与兜底：无会话 Key、跨用户排障、shares、关键词扫描、schema 探查。 |
| **P2 Knowledge Catalog（`kc_*`）** | 可选元数据发现：术语/资产目录，**不是**客户与日报的查询依赖。 |
| **P3 BigQuery** | 仅审计/BI（Lab-01）；**不是**业务真相源。 |

**主路径优先级**：`API/工具 > Firestore MCP > KC`（禁止再引入第四种业务查询入口）。

---

## 当前入口盘点

| 入口 | 模块 | 职责 | 默认角色 |
|------|------|------|----------|
| 确定性场景工具 | `tse_tools.py` | 名单/详情/日报/统计/分享/Key 管理话术 | **P0 业务界面** |
| TSE External API | `tse_api_client.py` → `/api/external/v1/*` | Key 作用域 ACL；chat / global_report；list/get 在有 Key 时优先 | **P0 后端** |
| Firestore 存储封装 | `tse_store.py`（经 MCP） | 分页 list/get、字段解析；供工具兜底与无 API 场景 | **P1 实现层** |
| 裸 `fs_*` MCP | `gcp_data_mcp.py` | 托管只读 get/list；排障/探 schema | **P1 探索** |
| 裸 `kc_*` MCP | `gcp_data_mcp.py` | Glossary / entry 发现 | **P2 可选** |
| Vertex RAG | `rag_tools.py` | 技术知识库文档（非 Firestore knowledge） | 知识检索（非 TSE 客户主路径） |

### 工具 × 后端（Lab-00 收敛后）

| 工具 | 有会话/环境 Key 时 | 无 Key / API 不可用 | 备注 |
|------|-------------------|---------------------|------|
| `ask_tse_workspace` | **API** `/chat` | 失败 → 要 Key | 必须 API |
| `generate_tse_global_report` | **API** `/global_report` | 失败 → 要 Key | 必须 API |
| `set_tse_session_api_key` | **API** `/system/status` 校验 | — | Session 写入 |
| `list_tse_customers` | **API** `/customers` 优先 | Firestore | Key 作用域 |
| `list_tse_items_for_user` | **API** `/customers`（email=Key 主体） | Firestore | 他用户仍 Firestore |
| `get_tse_customer` | **API** `/customers/{id}` 优先 | Firestore | |
| `get_tse_customer_daily_reports` | **API** `.../daily_reports` 优先 | Firestore | 日期过滤在工具侧 |
| `get_tse_user_workspace` | **API** `/settings`（仅 Key 主体） | Firestore | |
| `list_tse_api_keys` | **API** `/api_keys`（仅 Key 主体） | Firestore | 脱敏 |
| `query_*` / `search_*` / shares / overview / stats / chart | — | **Firestore** | External API 尚无对等能力 |
| `lookup_tse_schema` / catalog | 内嵌 Glossary | — | KC 仅补充，非默认 |
| 裸 `fs_*` / `kc_*` | 禁止作为业务默认 | 探索/排障 | |

---

## 必须走业务 API / 确定性工具的场景（P0）

1. 开放语义问答、全局工作大盘（须会话 Key + External API）
2. 「我的 / Key 主体可见」客户名单、单客户详情、单客户日报
3. Key 主体的 Prompt/UI settings、本人 API Key 列表（脱敏）
4. 关键词证据检索、按日期跨客户查日报、销售分布统计与作图（**工具界面**；底层可暂 Firestore）
5. 写入多维表格前的 `map_tse_daily_reports_to_bitable`（数据仍来自场景工具）

Agent **禁止**：跳过场景工具，直接用 `fs_*` 拼业务答案；**禁止**用 `kc_*` 当客户/日报查询。

---

## 允许走 Firestore MCP 兜底的场景（P1）

1. 未绑定 TSE API Key，且用户接受服务账号只读扫描（运维/演示）
2. 跨用户 / 全库总览（`list_tse_users`、`get_tse_overview`）—— External API 无跨租户能力
3. `shares` 待办与列表（API 未暴露）
4. `search_tse_daily_reports` / `query_tse_daily_reports_by_date`（API 无搜索/日期查询）
5. 裸 `fs_*`：schema 验证、单文档排障、确认 collection 是否存在
6. API 调用失败时的降级（工具返回中带 `access_path`）

---

## Knowledge Catalog 评估结论（P2）

| 项 | 决定 |
|----|------|
| 是否保留 | **保留为可选**：`KC_MCP_ENABLED` 或总开关下启用 |
| 是否默认依赖 | **否**。术语以 `lookup_tse_schema` 内嵌 Glossary 为准 |
| 适用 | 元数据目录演示、跨源资产发现、Console 治理故事 |
| 不适用 | 客户名单、日报正文、权限裁决、统计正确性 |

---

## 反回归（后续 Lab 必守）

- [ ] 不把 BigQuery 建成客户/日报查询路径
- [ ] 不把 KC 设为「先查 KC 再查库」的默认问候/指令
- [ ] 不新增与 `tse_tools` 平行的第三套业务 list/get
- [ ] Agent Gateway（Lab-05）只治理 MCP 出站，不作 TSE API 前门

---

## 相关代码

- 指令：`dispatcher_instruction_block()`（`tse_tools.py`）
- 开关：`firestore_mcp_enabled` / `kc_mcp_enabled` / `tse_scenario_tools_enabled`（`gcp_data_mcp.py`）
- TSE App API：`TSE-SMART-WORKSPACE-Final/routes.py` `/api/external/v1/*`
