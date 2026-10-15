# MCP servers（Cloud Run 为主）

本目录是 **Cloud Run MCP 镜像的同源代码**。生产路径：

```bash
./scripts/deploy_bilibili_mcp_cloudrun.sh
./scripts/deploy_etsy_mcp_cloudrun.sh
./scripts/deploy_feishu_mcp_cloudrun.sh
```

写入 `.env` 的 `BILIBILI_MCP_SERVER_URL` / `ETSY_MCP_SERVER_URL` / `FEISHU_MCP_SERVER_URL`（`https://….run.app/mcp`），再 `./scripts/deploy_smart_agents.sh`。

| 文件 | 说明 |
|------|------|
| `bilibili_mcp.py` | B 站热门 API：`fetch_hot_videos` / `export_hot_videos_excel` |
| `etsy_mcp.py` | Etsy 评论 + **同步** `etsy_generate_listing_scene_variants` |
| `feishu_mcp.py` | 飞书白名单工具（容器内 `lark-cli --as bot`） |
| `http_settings.py` | `$PORT` + Cloud Run DNS-rebinding 关闭 + **stateless HTTP** |
| `tunnel_hosts.py` | 遗留：本地调试 Host 白名单（非生产主路径） |

## 本地调试（可选，非生产）

```bash
export PORT=8080 MCP_DISABLE_DNS_REBINDING=1
python mcp_server/bilibili_mcp.py --http
python mcp_server/etsy_mcp.py --http
# 飞书另开端口，例如 PORT=8004
python mcp_server/feishu_mcp.py --http
```

Agent / 飞书入站 bridge / Widget **不再**默认连 `127.0.0.1:8002/8003`，也不再依赖 Cloudflare 隧道。

## 产物

Excel / 生图写 GCS：`MCP_ARTIFACT_GCS_BUCKET`（或 `ETSY_IMAGE_GCS_BUCKET`）。
