# etsy_cloud_agent — Etsy REST + Skill Agent

云端/本地 `adk run` 经 **HTTP REST** 调用本机 Etsy 节点（与 B 站 `bilibili_cloud_agent` 同模式）。

## 调用链

```
adk run etsy_cloud_agent
  → load_skill('etsy-review')
  → etsy_*_from_node
  → BILIBILI_REST_SERVER_URL/api/etsy_*
  → local_node/server.py :8001
  → etsy_tools.py（本机 .env 凭证 + Excel）
```

## 本地 Cloudflare Tunnel 联调

**终端 1** — 本地节点（含 B 站 + Etsy 路由）：

```bash
python local_node/server.py
```

**终端 2** — Cloudflare Tunnel（模拟云端访问本机）：

```bash
cloudflared tunnel --url http://127.0.0.1:8001
# 将 https 域名写入 .env：ETSY_REST_SERVER_URL=https://xxxx.trycloudflare.com
```

**终端 3** — Agent：

```bash
./scripts/run_adk_etsy_cloud_agent.sh
```

纯本机（本机直连（免隧道））：

```bash
ETSY_REST_SERVER_URL=http://127.0.0.1:8001 ./scripts/run_adk_etsy_cloud_agent.sh
```

## 与 etsy_agent 的区别

| | `etsy_agent` | `etsy_cloud_agent`（本目录） |
|--|--------------|---------------------------|
| 执行 | 进程内直连 | REST HTTP |
| 凭证位置 | Agent 进程 | 本机 `local_node` |
| 适用 | 快速迭代 Skill | 企业 demo / 隧道链路 |

## 部署（后续）

```bash
cp -R skills/etsy-review/* etsy_cloud_agent/skills/etsy-review/
adk deploy agent_engine etsy_cloud_agent --project=... --region=...
```

## 相关文档

- 操作手册：[`../user_guide.md`](../user_guide.md) §3.2（Etsy REST）
- 导读：[`../README.md`](../README.md)
- REST 节点：[`../local_node/README.md`](../local_node/README.md)
