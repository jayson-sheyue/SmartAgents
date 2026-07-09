# mcp_server — MCP 协议层

将本机 L1 工具封装为 **Model Context Protocol (MCP) Server**，供 Cursor、云端 `*_cloud_agent_mcp`、`smart_agents` 调度树使用。

REST 等价能力在 [`../local_node/`](../local_node/)。

| 文件 | 端口 | 作用 |
|------|------|------|
| `bilibili_mcp.py` | **8002** | B 站 MCP（Agent Engine / 飞书 / Cursor） |
| `etsy_mcp.py` | **8003** | Etsy MCP |
| `tunnel_hosts.py` | — | 隧道 Host 白名单解析 |

---

## B 站 MCP（`bilibili_mcp.py`）

### 暴露的 Tools

| MCP Tool | 参数 | → bilibili_tools |
|----------|------|------------------|
| `get_up_list` | 无 | `read_up_names_from_excel` |
| `fetch_fans_data` | `up_name` | `get_up_fans_data`（经 run_sync 子进程） |
| `write_excel` | `up_name`, `fans_count` | `write_fans_to_excel` |

### 运行

```bash
# stdio（Cursor）
python mcp_server/bilibili_mcp.py

# HTTP（云端 / 调度树）
python mcp_server/bilibili_mcp.py --http
# → http://0.0.0.0:8002/mcp
```

环境变量：`BILIBILI_MCP_SERVER_URL`（Agent 侧）、`BILIBILI_TUNNEL_HOST`（Host 白名单，可选，也可从 URL 自动解析）。

---

## Etsy MCP（`etsy_mcp.py`）

### 暴露的 Tools

`etsy_check_credentials` · `etsy_fetch_listing_reviews` · `etsy_write_reviews_excel` · `etsy_fetch_and_export_reviews`

### 运行

```bash
python mcp_server/etsy_mcp.py --http
# → http://0.0.0.0:8003/mcp
```

环境变量：`ETSY_MCP_SERVER_URL`（Agent 侧）、`ETSY_TUNNEL_HOST`（Host 白名单，可选）。

---

## 共用文件

| 文件 | 作用 |
|------|------|
| `run_sync.py` | Playwright 同步子进程（B 站） |
| `toolspec.json` | GCP Agent Registry（B 站 MCP） |
| `test_local_client.py` | B 站 stdio 联调 |
| `tunnel_hosts.py` | 从隧道 URL 解析 MCP Host 白名单 |

---

## GCP Agent Registry（B 站 MCP）

| 字段 | 示例 |
|------|------|
| MCP Server URL | `https://<uuid>.trycloudflare.com/mcp` |
| toolspec | `mcp_server/toolspec.json` |

`McpToolset` 连 URL 后动态 `tools/list`。

---

## 与云端 Agent 的关系

```
Playground / *_cloud_agent_mcp / smart_agents
    → McpToolset(StreamableHTTPConnectionParams)
    → Cloudflare Tunnel 或 127.0.0.1
    → bilibili_mcp.py :8002  或  etsy_mcp.py :8003
    → bilibili_tools / etsy_tools
```

调度树须**同时**启动 :8002 与 :8003。公网暴露见 [`../scripts/start_cloudflare_tunnel.sh`](../scripts/start_cloudflare_tunnel.sh)。

---

## 升级改造

| 需求 | 步骤 |
|------|------|
| 新 B 站 tool | `bilibili_mcp.py` → `bilibili_tools.py` → toolspec + SKILL |
| 新 Etsy tool | `etsy_mcp.py` → `etsy_tools.py` → Skill |
| 隧道换域名 | 更新 `.env` + GCP Registry URL + 重启 `--http` |

---

## 相关文档

- [`../user_guide.md`](../user_guide.md) §2.3、§3.3、§4、§6、§9
- [`../bilibili_cloud_agent_mcp/README.md`](../bilibili_cloud_agent_mcp/README.md)
- [`../etsy_cloud_agent_mcp/README.md`](../etsy_cloud_agent_mcp/README.md)
- [`.cursor/README.md`](../.cursor/README.md)
