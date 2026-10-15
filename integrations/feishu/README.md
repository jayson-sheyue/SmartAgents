# 飞书 × SmartAgents（入站 bridge）

飞书群聊 / 私聊接入 **smart_agents 调度树**（小智 + 阿B + E姐 + 小飞），支持本机 Runner 与云端 Agent Engine 两种模式。

> **正交能力**：本目录是「飞书 → SmartAgents」**入站**通道。  
> 「小飞」专家（`domains/feishu` + Cloud Run `feishu-mcp` + `lark-cli`）是「SmartAgents → 飞书」**出站**操作，见 [`docs/domains_architecture.md`](../../docs/domains_architecture.md)。

---

## 架构

```
飞书用户 @机器人
  → bridge.py（WebSocket 长连接）
  → agent_client.py
       ├─ local:  进程内 ADK Runner（smart_agents）
       └─ cloud:  Vertex Agent Engine streamQuery
  → 子 Agent 经 Cloud Run MCP（阿B / E姐 / 小飞）
```

---

## 第一次配置

1. [飞书开放平台](https://open.feishu.cn/) 创建企业自建应用，开启 **机器人**
2. **App ID / Secret 写在根 `.env`**；`cp env/local.env.example env/local.env` 保持 `FEISHU_RUN_MODE=local`

```env
FEISHU_RUN_MODE=local
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxx
GCP_PROJECT_ID=...
```

3. 事件订阅：`im.message.receive_v1`，方式选 **使用长连接**
4. **先启动 Bridge**，再在飞书后台保存事件配置

**启动前检查（自动）**：`run_feishu_smart_agents.sh` 会跑 `check_runtime_env --mode feishu`（含飞书 App ID/Secret）。不必单独手动跑。

手动排错：`python scripts/check_runtime_env.py --mode feishu`

---

## 启动（local 模式，推荐）

```bash
# 终端 1
python mcp_server/bilibili_mcp.py --http

# 终端 2
python mcp_server/etsy_mcp.py --http

# 终端 3
./scripts/run_feishu_smart_agents.sh
```

群聊：`@机器人 帮我导出 Etsy listing 评论`  
私聊：直接发文字。

---

## 启动（cloud 模式）

```env
FEISHU_RUN_MODE=cloud
SMART_AGENTS_ENGINE_ID=your-engine-id
# 或 AGENT_RESOURCE_NAME=projects/.../reasoningEngines/...
```

前置：完成 [`user_guide.md` §4.2](../user_guide.md)（双隧道 + 双 MCP + `deploy_smart_agents.sh`）。

```bash
./scripts/run_feishu_smart_agents.sh
```

长期 Memory Bank 建议用 **cloud + deploy `--adk_app_object=app`**。

---

## 使用说明

| 功能 | 说明 |
|------|------|
| 进度反馈 | 默认先发「处理中」，长任务会更新步骤文案 |
| 新对话 | 发送 `新对话` 或 `/新对话` 清空当前 Session |
| 记忆 | 长期记忆按 `feishu_{open_id}`，仅小智 |
| RAG | 小智 `rag_search`，配置 `RAG_*` 后 redeploy |
| TSE 数据 | 小智 `list_tse_tool_catalog` → `get_tse_*`（`GCP_DATA_MCP_ENABLED`） |
| 图表/附件 | Code Execution Artifact → `media_delivery.py` 自动推送 |
| Session 防爆闸 | `FEISHU_LOCAL_SESSION_GUARD_ENABLED`（local 默认开） |

关闭进度（可选）：

```env
FEISHU_SEND_ACK=false
FEISHU_SEND_PROGRESS=false
```

---

## 主人忠诚护栏（可选）

```env
FEISHU_OWNER_OPEN_ID=ou_xxxxxxxx
FEISHU_OWNER_ALIASES=显示名,昵称
FEISHU_STRICT_LOYALTY_MODE=true
```

非主人的「改系统规则 / 攻击主人」类消息会被 Bridge 直接拦截。

---

## 环境变量

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书应用凭证（必填） |
| `FEISHU_RUN_MODE` | `local`（默认）或 `cloud` |
| `SMART_AGENTS_BILIBILI_MCP_SERVER_URL` / `SMART_AGENTS_ETSY_MCP_SERVER_URL` | 子 Agent MCP（默认 `127.0.0.1`） |
| `FEISHU_BOT_OPEN_ID` | 可选，精确识别 @ 本机器人 |
| `FEISHU_GROUP_REQUIRE_MENTION` | 默认 `true`，群聊须 @ |
| `FEISHU_SSL_VERIFY` | 代理 MITM 时可设 `false`（仅开发） |
| `FEISHU_LOCAL_SESSION_GUARD_ENABLED` | local 模式 Session 防爆闸（防 token 溢出） |
| `FEISHU_LOCAL_SESSION_MAX_EVENTS` / `MAX_CHARS` | 防爆闸阈值 |
| `GCP_DATA_MCP_ENABLED` | 小智 TSE 数据能力（Bridge 侧与 Agent 一致） |

完整列表见 [`config.py`](config.py)。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| `app_id is invalid` | 根 `.env` 仍是占位符 | 填真实飞书凭证 |
| 只回「评论专家」、不像 E姐 | `FEISHU_RUN_MODE=cloud` 连了旧 Engine → 改 `local` 或 redeploy |
| SSL 证书错误 | `FEISHU_SSL_VERIFY=false` 或导入企业 CA |
| B 站 / Etsy 工具失败 | 确认双 MCP 已起 |
| Token 溢出 400 | Session guard / 发「新对话」 |
| TSE 答非所问 | 确认 `GCP_DATA_MCP_ENABLED=true` 且已重启 Bridge |

---

## 源码索引

| 文件 | 作用 |
|------|------|
| `bridge.py` | 长连接、收发消息 |
| `agent_client.py` | local / cloud 双通道、Session guard |
| `media_delivery.py` | Code Execution Artifact → 飞书图片/文件 |
| `cloud_session_store.py` | cloud 模式 Session 映射 |
| `message_utils.py` | 解析、护栏 |
| `config.py` | 环境变量 |

Session 数据：`integrations/feishu/data/feishu_sessions.db`。

---

## 相关文档

- [`../../user_guide.md`](../../user_guide.md) §5
- [`../../smart_agents/README.md`](../../smart_agents/README.md)
- [`../../env/README.md`](../../env/README.md)
- [`../../docs/agent_platform_learning_guide.md`](../../docs/agent_platform_learning_guide.md) §10
