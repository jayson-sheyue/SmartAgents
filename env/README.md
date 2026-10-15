# 环境变量配置

只需 **两个文件**：

| 文件 | 谁读 | 填什么 |
|------|------|--------|
| **`.env`**（仓库根） | 全部进程：MCP、Agent 脚本、Widget、deploy、Python 工具 | **所有密钥**：GCP、Etsy、飞书、GCS、RAG、云端 Engine ID |
| **`env/local.env`** | 同上（在 `.env` 之后加载，**覆盖**同名变量） | **本地模式**：`FEISHU_RUN_MODE=local`、MCP `127.0.0.1`、`WIDGET_RUN_MODE=local` |

```
.env  →  env/local.env
```

---

## 第一次配置

```bash
cp .env.example .env
cp env/local.env.example env/local.env
# 编辑 .env 填入真实密钥；local.env 一般保持 example 默认即可

gcloud auth application-default login
```

---

## 按入口：`.env` 要填哪些？

| 入口 | 命令 | `.env` 必填 | `.env` 按需 |
|------|------|-------------|-------------|
| B 站单域 | `run_adk_bilibili_agent.sh` | `GCP_*` | — |
| Etsy 单域 | `run_adk_etsy_agent.sh` | `GCP_*`、Etsy 凭证 | 生图 GCS |
| 调度树 | `run_adk_smart_agents.sh` | `GCP_*` | Etsy、RAG、`GCP_DATA_MCP_*`、`CODE_EXECUTION_*` |
| 飞书 | `run_feishu_smart_agents.sh` | `GCP_*`、飞书凭证 | Etsy、RAG、TSE、Code Exec |
| Widget | `run_widget.sh` | `GCP_*` | `WIDGET_RUN_MODE`（local 写在 `local.env`） |
| MCP | `python mcp_server/*_mcp.py --http` | Etsy 凭证（Etsy MCP） | 同左 |
| 云端 deploy | `deploy_smart_agents.sh` | `GCP_*`、`SMART_AGENTS_ENGINE_ID`、公网 MCP | `RAG_*`、`GCP_DATA_MCP_*`、`CODE_EXECUTION_*` |
| A2A 并行 Engine | `deploy_smart_agents_a2a.sh` | `GCP_*`、公网 MCP（RPA） | `SMART_AGENTS_A2A_ENGINE_ID`（更新时）、`SMART_AGENTS_A2A_STAGING_BUCKET`、`RAG_*` / TSE / Code Exec |

每个本地入口还需要 **`env/local.env`** + **另开终端起 MCP**。

---

## 可选能力变量速查

### TSE 数据（小智）

```env
GCP_DATA_MCP_ENABLED=true
TSE_FIRESTORE_PROJECT_ID=your-gcp-project
TSE_FIRESTORE_DATABASE=tse-jayson-database
# TSE_CUSTOMER_STRICT_ITEM_TYPE=false   # 默认含 item_type 为空的历史客户
# TSE_API_BASE_URL=https://your-tse-app.run.app
# TSE_API_KEY=   # 可选回落；优先用户会话 set_tse_session_api_key
```

需 ADC + IAM：`roles/mcp.toolUser`、`roles/datastore.viewer` 等。详见 [`user_guide.md`](../user_guide.md) §11。

### Code Execution（小智作图）

```env
CODE_EXECUTION_ENABLED=true
CODE_EXEC_LOCATION=us-central1
# 默认复用 SMART_AGENTS_ENGINE_ID
```

详见 [`user_guide.md`](../user_guide.md) §12。

### 飞书 Session 防爆闸（local）

```env
FEISHU_LOCAL_SESSION_GUARD_ENABLED=true
FEISHU_LOCAL_SESSION_MAX_EVENTS=80
FEISHU_LOCAL_SESSION_MAX_CHARS=120000
```

---

## `local.env` 做什么？

根 `.env` 可保留云端配置（`FEISHU_RUN_MODE=cloud`、隧道 MCP URL）。  
`local.env` 用几行覆盖回本地调试，**不必维护第二份密钥**。

---

## 环境检查

`run_*` 脚本自动执行 `check_runtime_env.py`。手动排错：

```bash
python scripts/check_runtime_env.py --mode smart_agents
python scripts/check_runtime_env.py --mode feishu
```

---

## 仓库内文件

| 路径 | 说明 |
|------|------|
| `.env.example` | 根配置模板（可提交） |
| `env/local.env.example` | 本地覆盖模板（可提交） |
| `.env` | 你的密钥（gitignore） |
| `env/local.env` | 你的本地覆盖（gitignore） |

---

## 相关文档

- [`../user_guide.md`](../user_guide.md) §0.3
- [`../docs/agent_platform_learning_guide.md`](../docs/agent_platform_learning_guide.md)
- [`../scripts/lib/load_env.sh`](../scripts/lib/load_env.sh)
