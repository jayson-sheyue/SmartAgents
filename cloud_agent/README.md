# cloud_agent — 云端 REST Agent 部署包

通过 **HTTP REST** 调用本地 RPA 节点（`local_node/server.py`），**P0 envelope** 已对接。

Skill Registry 未 attach；工作流在 `agent.py` 的 `system_instruction` 中。

---

## 调用链

```
adk run / Playground (REST Agent)
    → get_up_list_from_node / fetch_fans_data_from_node / write_excel_to_node
    → NGROK_URL/api/*
    → local_node/server.py :8001
    → rpa_tools.py
```

| Agent 工具 | REST 端点 |
|-----------|-----------|
| `get_up_list_from_node` | `GET /api/get_up_list` |
| `fetch_fans_data_from_node` | `POST /api/fetch_fans_data` |
| `write_excel_to_node` | `POST /api/write_excel` |

工具返回 **完整 envelope**（`ok/data/error/meta`），不是旧版裸 list。

---

## 本地 adk run

### 1. 启动本地 REST 节点

```bash
python local_node/server.py
```

### 2. 暴露给 Agent（二选一）

**方式 A — ngrok（与云端一致）**

```bash
ngrok http 8001
```

`.env`：

```env
NGROK_URL=https://<你的域名>.ngrok-free.dev
```

**方式 B — 纯本机（adk run 在本机时）**

```env
NGROK_URL=http://127.0.0.1:8001
```

### 3. 运行 Agent

**推荐**（自动取消 Shell 代理 + 默认连本机 8001）：

```bash
./scripts/run_adk_cloud_agent.sh
```

或手动：

```bash
source .venvAgents/bin/activate
NGROK_URL=http://127.0.0.1:8001 adk run cloud_agent
```

示例指令：「先 dry_run 检查登录态，再抓取桌面 Excel 里第一个 UP 主的粉丝数并写回。」

---

## 故障排查

### `adk run` 报 `httpx.ConnectError`（输入 hi 就崩溃）

**与 REST 节点无关**，是本地连 **Vertex AI（Gemini）** 的网络问题。常见两种模式：

| 堆栈特征 | 原因 | 处理 |
|---------|------|------|
| `http_proxy.py` + `start_tls` | 全局 `HTTP_PROXY` 被 httpx 自动套用，TLS 握手失败 | 用 `./scripts/run_adk_cloud_agent.sh`（会把代理转成 `VERTEX_HTTP_PROXY` 并清全局变量） |
| `connect_tcp` + `All connection attempts failed` | 代理被清掉后无法直连 Google（国内常见） | 确保 Clash 在跑，且 `export VERTEX_HTTP_PROXY=http://127.0.0.1:7890` 后再跑脚本 |

**推荐（国内 + Clash）**：

```bash
export VERTEX_HTTP_PROXY=http://127.0.0.1:7890   # 端口以 Clash 为准
./scripts/run_adk_cloud_agent.sh
```

启动时应看到：`🔐 Vertex 网络：经代理 http://127.0.0.1:7890`

若显示「直连」且你在国内，一定会连不上 Vertex。

**替代**：在 GCP Console 打开 Playground（路径见 `user_guide.md` §2.6）。

---

## 部署到 GCP

```bash
source .venvAgents/bin/activate
# 确保 .env 已配置 GCP_PROJECT_ID、REST_AGENT_ENGINE_ID

adk deploy agent_engine cloud_agent \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili-Cloud-Agent" \
  --agent_engine_id=$REST_AGENT_ENGINE_ID
```

部署前确认：

- 本地 `server.py` + ngrok 8001 运行中
- `.env` 中 `NGROK_URL` 与 ngrok 一致（部署时打进包或控制台配置）

| 项 | 环境变量 |
|----|----------|
| Engine ID | `REST_AGENT_ENGINE_ID` |
| Playground | Console → Vertex AI → Agent Engine → 选择对应 Engine |

---

## 与 cloud_agent_mcp 对比

| | cloud_agent（本目录） | cloud_agent_mcp |
|---|----------------------|-----------------|
| 协议 | REST | MCP |
| Skill | 无 | bilibili-rpa |
| 本地端口 | 8001 | 8002 |
| Engine ID | `$REST_AGENT_ENGINE_ID` | `$MCP_AGENT_ENGINE_ID` |

---

## 相关文档

- REST 节点：[`../local_node/README.md`](../local_node/README.md)
- P0 契约：[`../feat.md`](../feat.md)
