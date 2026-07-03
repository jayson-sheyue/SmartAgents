# Cursor MCP 配置

本目录配置 Cursor IDE 通过 **stdio MCP** 连接本地 RPA，不经过 ngrok。

## mcp.json

```json
{
  "mcpServers": {
    "bilibili-rpa": {
      "command": ".../.venvAgents/bin/python",
      "args": ["mcp_server/bilibili_mcp.py"]
    }
  }
}
```

- **协议**：stdio（非 HTTP）
- **Server 实现**：[`../mcp_server/bilibili_mcp.py`](../mcp_server/bilibili_mcp.py)
- **与云端区别**：云端用 `--http` + ngrok；Cursor 由 IDE 拉起子进程

## 使用

在 Cursor Agent 对话中直接描述任务，例如：「读取 Excel UP 主名单并抓取粉丝数」。

无需启动 `local_node/server.py` 或 ngrok；需本地已有：

- `bilibili_state.json`（`python main.py login`）
- `~/Desktop/Up主名称.xlsx`

详见 [`../mcp_server/README.md`](../mcp_server/README.md) 与 [`../user_guide.md`](../user_guide.md) 场景二。
