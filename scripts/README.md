# scripts — 启动、检查与部署

## 环境加载（所有 `run_adk_*` / `run_feishu_*`）

```
.env  →  env/local.env（覆盖）
```

由 [`lib/load_env.sh`](lib/load_env.sh) 统一处理。详见 [`../env/README.md`](../env/README.md)。

---

## Agent 启动脚本

| 脚本 | `adk run` 包 | 自动检查 |
|------|--------------|----------|
| `run_adk_bilibili_agent.sh` | `bilibili_agent` | `bilibili_agent` |
| `run_adk_etsy_agent.sh` | `etsy_agent` | `etsy_agent` |
| `run_adk_smart_agents.sh` | `smart_agents` | `smart_agents` |
| `run_feishu_smart_agents.sh` | Bridge → 调度树 | `feishu` |

---

## 本地三终端（调度树 / 飞书）

```bash
python mcp_server/bilibili_mcp.py --http   # 读根 .env
python mcp_server/etsy_mcp.py --http
./scripts/run_adk_smart_agents.sh          # 读 .env + env/local.env
```

---

## 其他脚本

| 脚本 | 说明 |
|------|------|
| `check_runtime_env.py` | 启动脚本自动调用；`--mode smart_agents` / `feishu` / `bilibili_agent` / `etsy_agent` |
| `deploy_smart_agents.sh` | 读根 `.env`，rsync `skills/`，生成 `smart_agents/.env` 并 deploy `app` |
| `run_a2a_smart_agents_local.sh` | A2A Card/`set_up` smoke；`live` 需双 MCP |
| `deploy_smart_agents_a2a.sh` | **并行第二 Engine**：部署 `A2aAgent`（`SMART_AGENTS_A2A_ENGINE_ID`） |
| `start_cloudflare_tunnel.sh` | Quick Tunnel（云端 Engine 回本机 MCP） |
| `run_widget.sh` | Widget :8000（读根 `.env`） |

改 TSE / Code Exec / 飞书护栏代码后，须 **重启** 对应 `run_*` 进程（不必 redeploy，除非走 cloud）。

---

## 相关文档

- [`../env/README.md`](../env/README.md) — **按入口填哪些变量**
- [`../user_guide.md`](../user_guide.md)
- [`../docs/agent_platform_learning_guide.md`](../docs/agent_platform_learning_guide.md)
