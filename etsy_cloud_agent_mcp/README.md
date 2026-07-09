# etsy_cloud_agent_mcp — Etsy MCP + Skill Agent

云端/本地 `adk run` 经 **MCP HTTP** 调用本机 Etsy 工具（与 B 站 `bilibili_cloud_agent_mcp` 同模式）。

## 调用链

```
adk run etsy_cloud_agent_mcp
  → load_skill('etsy-review')
  → McpToolset
  → ETSY_MCP_SERVER_URL（默认 :8003/mcp）
  → mcp_server/etsy_mcp.py
  → etsy_tools.py
```

## 本地 Cloudflare Tunnel 联调

**终端 1** — Etsy MCP HTTP：

```bash
python mcp_server/etsy_mcp.py --http
```

**终端 2** — Cloudflare Tunnel（独立隧道，端口 8003）：

```bash
cloudflared tunnel --url http://127.0.0.1:8003
# .env:
# ETSY_MCP_SERVER_URL=https://xxxx.trycloudflare.com/mcp
# ETSY_TUNNEL_HOST=xxxx.trycloudflare.com   # 或复用 BILIBILI_TUNNEL_HOST
```

**终端 3** — Agent：

```bash
./scripts/run_adk_etsy_cloud_agent_mcp.sh
```

纯本机：

```bash
ETSY_MCP_SERVER_URL=http://127.0.0.1:8003/mcp ./scripts/run_adk_etsy_cloud_agent_mcp.sh
```

（脚本读取 `ETSY_MCP_SERVER_URL`，默认已是 `127.0.0.1:8003/mcp`。）

## MCP 工具

`etsy_check_credentials` / `etsy_fetch_listing_reviews` / `etsy_write_reviews_excel` / `etsy_fetch_and_export_reviews`

## 部署（后续）

```bash
cp -R skills/etsy-review/* etsy_cloud_agent_mcp/skills/etsy-review/
adk deploy agent_engine etsy_cloud_agent_mcp --project=... --region=...
```

## 相关文档

- 操作手册：[`../user_guide.md`](../user_guide.md) §3.3（Etsy MCP）
- 导读：[`../README.md`](../README.md)
- MCP 服务：[`../mcp_server/README.md`](../mcp_server/README.md)
- 调度树：[`../smart_agents/README.md`](../smart_agents/README.md)（E姐子 Agent）
