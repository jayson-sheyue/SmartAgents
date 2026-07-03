# mcp_server — MCP 协议层

将 [`main.py`](../main.py) 的 RPA 封装为 **Model Context Protocol (MCP) Server**，供 Cursor、云端 `cloud_agent_mcp`、GCP Agent Registry 使用。

REST 等价能力在 [`../local_node/`](../local_node/)。

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `bilibili_mcp.py` | MCP Server 主程序（stdio / HTTP） |
| `run_sync.py` | 子进程跑 Playwright 同步 API（避免 asyncio 冲突） |
| `toolspec.json` | GCP Agent Registry 注册用的 tool schema |
| `test_local_client.py` | 本地 MCP 联调测试 |

---

## 暴露的 Tools

| MCP Tool | 参数 | → main.py |
|----------|------|-----------|
| `get_up_list` | 无 | `read_up_names_from_excel` |
| `fetch_fans_data` | `up_name` | `get_up_fans_data`（经 run_sync 子进程） |
| `write_excel` | `up_name`, `fans_count` | `write_fans_to_excel` |

---

## 运行方式

### 1. stdio（Cursor / Claude Desktop）

```bash
python mcp_server/bilibili_mcp.py
```

由客户端通过管道 JSON-RPC 通信。项目已配置 [`.cursor/mcp.json`](../.cursor/mcp.json)。

### 2. HTTP（云端 Agent + ngrok）

```bash
python mcp_server/bilibili_mcp.py --http
# 监听 0.0.0.0:8002，transport=streamable-http

ngrok http 8002
```

`.env` 配置：

```env
MCP_SERVER_URL=https://<域名>.ngrok-free.dev/mcp
NGROK_HOST=<域名>.ngrok-free.dev
```

`NGROK_HOST` 用于 FastMCP DNS rebinding 白名单（否则云端请求 421）。

---

## GCP Agent Registry

控制台 **Build → MCP Servers** 注册的是 **Server 端点**，不是单个 Tool：

| 字段 | 本项目示例 |
|------|-----------|
| MCP Server URL | `https://<ngrok>/mcp` |
| toolspec | `mcp_server/toolspec.json` |
| Server ID | `MCP_SERVER_REGISTRY_ID`（见 `.env`） |

运行时 `McpToolset` 连 URL 后 **动态 `tools/list`**，无需在控制台逐条登记 tool。

---

## 与云端 Agent 的关系

```
Playground / cloud_agent_mcp
    → McpToolset(StreamableHTTPConnectionParams)
    → ngrok :8002
    → bilibili_mcp.py
    → main.py
```

Skill 编排见 [`../cloud_agent_mcp/README.md`](../cloud_agent_mcp/README.md)。

---

## 升级改造

| 需求 | 步骤 |
|------|------|
| 新 tool | `bilibili_mcp.py` 加 `@mcp.tool()` → 更新 `toolspec.json` → 更新 Skill `adk_additional_tools` |
| 新参数 | 改 tool 签名 + `main.py` → 同步 toolspec + SKILL.md |
| ngrok 换域名 | 改 `.env` + GCP MCP Server URL + 重启 `--http` |

---

## 相关文档

- [`../user_guide.md`](../user_guide.md) 场景二、五、七
- [`../feat.md`](../feat.md) MCP 双轨说明
