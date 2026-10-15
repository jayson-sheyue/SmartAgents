# bilibili_agent — B 站 ADK 包

B 站专家 **阿B**：通过 **MCP + Skill** 完成 UP 主粉丝采集与 Excel RPA。

---

## 组成

| 部分 | 路径 |
|------|------|
| ADK 入口 | `agent.py` → `build_bilibili_agent(standalone=True)` |
| L1 工具 | [`domains/bilibili/bilibili_tools.py`](../domains/bilibili/bilibili_tools.py) |
| Agent 构建 | [`domains/bilibili/builder.py`](../domains/bilibili/builder.py) |
| MCP 服务 | `mcp_server/bilibili_mcp.py` → **:8002/mcp** |
| Skill | `skills/bilibili-rpa/` · `skills/bilibili-trend-rpa/` |
| 登录 CLI | `python -m bilibili_agent login` → `bilibili_state.json` |

---

## 本地运行

**终端 1 — MCP（必须先起）**

```bash
python mcp_server/bilibili_mcp.py --http
```

**终端 2 — Agent**

```bash
python -m bilibili_agent login    # 首次
./scripts/run_adk_bilibili_agent.sh
```

> 脚本启动时会**自动**跑环境检查（`check_runtime_env --mode bilibili_agent`）。失败会直接退出；正常用时不必单独执行检查命令。

等价：

```bash
export BILIBILI_MCP_SERVER_URL=http://127.0.0.1:8002/mcp
adk run bilibili_agent
```

`agent.py` 启动时会 `assert_mcp_reachable`；MCP 未起会直接报错。

---

## 前置条件

- Playwright Chromium：`playwright install chromium`
- B 站登录态：`bilibili_state.json`
- UP 主 Excel：默认 `~/Desktop/Up主名称.xlsx`
- GCP：`GCP_PROJECT_ID`（Vertex）

env 由 `run_adk_bilibili_agent.sh` 自动加载 `.env` + `env/local.env`。

---

## 作为调度树子 Agent

`smart_agents/agent.py` 调用：

```python
build_bilibili_agent(standalone=False, mcp_server_url=...)
```

子 Agent 名：`Bilibili_Cloud_MCP_Agent`（见 `domains/bilibili/manifest.yaml`）。

---

## 云端 deploy

本机 MCP + 隧道（若 Engine 在云端）后：

```bash
adk deploy agent_engine bilibili_agent \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Bilibili Agent" \
  --agent_engine_id=$BILIBILI_MCP_AGENT_ENGINE_ID   # 更新时
```

包名与本地 **相同**，无需 `bilibili_cloud_agent_mcp`。

---

## 相关文档

- [`../user_guide.md`](../user_guide.md) §2
- [`../mcp_server/README.md`](../mcp_server/README.md)
- [`../skills/bilibili-rpa/SKILL.md`](../skills/bilibili-rpa/SKILL.md)
- [`../docs/agent_platform_learning_guide.md`](../docs/agent_platform_learning_guide.md) §8
