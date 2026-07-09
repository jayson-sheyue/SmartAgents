# bilibili_agent — B 站粉丝 RPA Agent（进程内）

与 [`etsy_agent/`](../etsy_agent/) 对称：**本地 ADK + Skill + 进程内工具**，不经 REST/MCP。

## 三条路径（B 站域）

| 路径 | 目录 | 执行方式 | 本地联调 |
|------|------|----------|----------|
| **进程内** | `bilibili_agent/`（本目录） | Skill + 直连 `bilibili_tools` | `./scripts/run_adk_bilibili_agent.sh` |
| **REST** | `bilibili_cloud_agent/` | Skill + HTTP → `:8001` | `./scripts/run_adk_bilibili_cloud_agent.sh` |
| **MCP** | `bilibili_cloud_agent_mcp/` | Skill + MCP → `:8002` | `./scripts/run_adk_bilibili_cloud_agent_mcp.sh` |

企业 demo / 飞书调度推荐 **MCP**；快速改 Skill、本机直跑 RPA 用 **本目录**。

## 调用链

```
adk run bilibili_agent
  → load_skill('bilibili-rpa')
  → get_up_list / fetch_fans_data / write_excel
  → bilibili_tools.py（Playwright + P0 envelope）
```

## 本地运行

**前置**

```bash
python -m bilibili_agent login   # bilibili_state.json
# 桌面放置 Up主名称.xlsx（或按 SKILL 指定路径）
```

**启动**

```bash
./scripts/run_adk_bilibili_agent.sh
```

等价：

```bash
source .venvAgents/bin/activate
export PYTHONPATH=.
adk run bilibili_agent
```

## 目录结构

```
bilibili_agent/bilibili_tools.py  ← L1 唯一实现（Playwright + envelope）
rpa_tools.py                      ← 兼容 re-export（REST/MCP 调用链）
skills/bilibili-rpa/              ← Skill SOP
bilibili_cloud_agent/             ← REST Agent
bilibili_cloud_agent_mcp/         ← MCP Agent
smart_agents/                     ← 调度树（阿B 走 MCP 子 Agent）
```

## 部署（可选）

进程内 Agent 部署到 Agent Engine 需本机 Playwright，通常 **不推荐**；生产入口用 `bilibili_cloud_agent_mcp` + 本机 MCP。

```bash
adk deploy agent_engine bilibili_agent --project=... --region=...
```

## 相关文档

- 操作手册：[`../user_guide.md`](../user_guide.md) §2（B 站域）
- 导读：[`../README.md`](../README.md)
- 脚本：[`../scripts/README.md`](../scripts/README.md)
- Skill：[`../skills/bilibili-rpa/SKILL.md`](../skills/bilibili-rpa/SKILL.md)
