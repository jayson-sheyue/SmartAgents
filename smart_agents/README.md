# SmartAgents — 调度树（Dispatcher + 双 MCP 子 Agent）

葫芦娃架构：**秘书小智** 接待闲聊、知识库与记忆，并路由到 **阿B**（B 站）、**E姐**（Etsy）；RPA 执行仍在 **本机 MCP**。

## 架构

```
SmartAgents_Dispatcher（小智）
  ├─ tools: GoogleSearch · Memory · rag_search（可选）
  ├─ Bilibili_Cloud_MCP_Agent   → BILIBILI_MCP_SERVER_URL (:8002)
  └─ Etsy_Cloud_MCP_Agent       → ETSY_MCP_SERVER_URL (:8003)
```

- 路由：`transfer_to_agent`（子 Agent **禁止** peer 互转，跨域须回调度器）
- 共享构建器：[`bilibili_mcp_sub.py`](bilibili_mcp_sub.py) · [`etsy_mcp_sub.py`](etsy_mcp_sub.py)
- Vertex / 代理：[`vertex.py`](vertex.py)
- **仅小智**：Memory（`PreloadMemoryTool` / `LoadMemoryTool` + callback / plugin）、联网搜索、**知识库 RAG**（[`rag_tools.py`](rag_tools.py)）
- Session 压缩：[`app_factory.py`](app_factory.py)（`EventsCompactionConfig`）
- 单领域 MCP 包与调度树 **共用** 上述 sub builder

### 记忆与用户隔离（单 Agent Runtime）

| 入口 | `user_id` | `session_id` | Memory Bank |
|------|-----------|--------------|-------------|
| 飞书 | `feishu_{open_id}`（跨群共享长期记忆） | `feishu_{chat}_{user}`（每群独立短期上下文） | 小智 only；**cloud** 模式持久化 |
| Widget | `web_{随机}`（匿名 tab） | 每 tab 独立 | **关闭** |
| GE App（预留） | `google_{sub}` | 按产品定 | 小智 only |

飞书发送 **`新对话`** 或 **`/新对话`**：仅清空当前群/私聊 Session，**不**删除 Memory Bank。

### 知识库 RAG（PoC）

平台侧在 **Agent Platform → RAG Engine** 建 corpus 并 Import 文档（Status=`Imported`），再配置：

```env
RAG_ENABLED=true
RAG_CORPUS_NAME=projects/<project>/locations/<loc>/ragCorpora/<id>
RAG_LOCATION=<loc>    # 与 corpus 同 region（如 asia-east1）
```

| 能力 | 工具 | 用途 |
|------|------|------|
| 文档知识 | `rag_search` | 手册 / PDF / FAQ |
| 时效事实 | `google_search` | 新闻、天气等 |
| 用户偏好 | Memory Bank | 称呼、习惯 |
| 领域 RPA | transfer | B 站 / Etsy |

改完后执行 `./scripts/deploy_smart_agents.sh`（会把 `RAG_*` 写入 `smart_agents/.env`）。  
操作细则：[`../user_guide.md`](../user_guide.md) §10。

本地 smoke：

```bash
RAG_ENABLED=true \
RAG_CORPUS_NAME='projects/.../ragCorpora/...' \
RAG_LOCATION=asia-east1 \
python -c "from smart_agents.rag_tools import rag_search; print(rag_search('权限配置', 3))"
```

## 本地测试（整棵树）

### 1. 双 MCP

```bash
# 终端 1
python mcp_server/bilibili_mcp.py --http

# 终端 2
python mcp_server/etsy_mcp.py --http
```

### 2. 调度 Agent

```bash
./scripts/run_adk_smart_agents.sh
```

等价：

```bash
export BILIBILI_MCP_SERVER_URL=http://127.0.0.1:8002/mcp
export ETSY_MCP_SERVER_URL=http://127.0.0.1:8003/mcp
export PYTHONPATH=.
adk run smart_agents
```

> `adk run` 加载 `root_agent`，不含 Memory Plugin / 事件压缩；RAG 工具只要环境变量齐全即可本地调用。

### 3. 对话示例

- B 站：`帮我查 Excel 里所有 UP 主的粉丝数`
- Etsy：`导出 listing 12345678 的评论`
- 闲聊：`你好，你能做什么？`（小智直接答，不 transfer）
- 知识库：`Gemini Enterprise 权限怎么配？`（`rag_search`）

## 单独测试子 Agent（不经过调度）

| 子 Agent | 脚本 | 说明 |
|----------|------|------|
| 阿B（B 站 MCP） | `./scripts/run_adk_bilibili_cloud_agent_mcp.sh` | 同 [`bilibili_cloud_agent_mcp`](../bilibili_cloud_agent_mcp/) |
| E姐（Etsy MCP） | `./scripts/run_adk_etsy_cloud_agent_mcp.sh` | 同 [`etsy_cloud_agent_mcp`](../etsy_cloud_agent_mcp/) |

## 飞书入口

```bash
./scripts/run_feishu_smart_agents.sh
```

见 [`integrations/feishu/README.md`](../integrations/feishu/README.md)（含主人忠诚护栏、身份上下文）。

## 环境变量

| 变量 | 默认（`run_adk_smart_agents.sh`） | 说明 |
|------|-----------------------------------|------|
| `GCP_PROJECT_ID` | — | Vertex（必填） |
| `BILIBILI_MCP_SERVER_URL` | `http://127.0.0.1:8002/mcp` | B 站 MCP |
| `ETSY_MCP_SERVER_URL` | `http://127.0.0.1:8003/mcp` | Etsy MCP |
| `SMART_AGENTS_BILIBILI_MCP_SERVER_URL` | — | 覆盖 B 站（隧道演示） |
| `SMART_AGENTS_ETSY_MCP_SERVER_URL` | — | 覆盖 Etsy |
| `SMART_AGENTS_ENGINE_ID` | — | 云端部署 Engine ID |
| `RAG_ENABLED` | `false` | 是否挂载 `rag_search` |
| `RAG_CORPUS_NAME` | — | corpus 完整 resource name |
| `RAG_LOCATION` | 从 corpus 解析 | 须与 corpus 同区 |
| `RAG_PROJECT_ID` | `GCP_PROJECT_ID` | 可选 |
| `VERTEX_HTTP_PROXY` | 从代理环境继承 | 国内访问 Vertex |

## 云端部署（Agent Engine）

前置：本机 **双 MCP + 隧道**（若要做 RPA），`.env` 中 MCP URL 为公网 HTTPS；RAG 仅需 `RAG_*` + redeploy。

**注意**：`adk deploy` 只打包 `smart_agents/`；Skill 放在 `smart_agents/skills/`；密钥与端点写在 **`smart_agents/.env`**（deploy 脚本生成）。

```bash
./scripts/deploy_smart_agents.sh
```

脚本会：同步 `skills/`、写入 MCP + **RAG** 到 `smart_agents/.env`、`--adk_app_object=app`。

## 相关文档

- 操作手册：[`../user_guide.md`](../user_guide.md) §4（调度树）· §5（飞书）· §6（部署）· §10（RAG）
- 导读：[`../README.md`](../README.md)
- ADK：[`../docs/adk_learning_guide.md`](../docs/adk_learning_guide.md)
- 脚本：[`../scripts/README.md`](../scripts/README.md)
