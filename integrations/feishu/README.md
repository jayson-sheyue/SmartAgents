# 飞书 × SmartAgents（双通道：local / cloud）

飞书群聊 / 私聊作为用户入口，支持两种 Agent Runtime：
- `local`：Bridge 进程内 ADK Runner（本机 `smart_agents`）
- `cloud`：Bridge 调用 Agent Engine Runtime（云端 `smart_agents`）

## 架构

```
飞书群 @机器人
  → integrations/feishu/bridge.py（WebSocket 长连接）
  → local: ADK Runner（smart_agents 小智 + 阿B + E姐）
  → cloud: Agent Engine streamQuery
```

## 前置条件

1. `.env` 中已有 `GCP_PROJECT_ID`（Vertex）
2. `.env` 中配置飞书凭证：

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx   # 或 FEISHU_APP_TOKEN
```

3. 飞书后台：事件 `im.message.receive_v1`，订阅方式为 **使用长连接接收事件**（需先启动本 Bridge 再保存）

## 启动

### A) local 模式（默认）

配置：
```bash
FEISHU_RUN_MODE=local
```

**终端 1 — Bilibili MCP**

```bash
python mcp_server/bilibili_mcp.py --http
```

**终端 2 — Etsy MCP**

```bash
python mcp_server/etsy_mcp.py --http
```

**终端 3 — 飞书 Bridge**

```bash
./scripts/run_feishu_smart_agents.sh
```

### B) cloud 模式（云端 Agent Runtime）

配置：
```bash
FEISHU_RUN_MODE=cloud
# 二选一
AGENT_RESOURCE_NAME=projects/<project_number>/locations/<location>/reasoningEngines/<engine_id>
# 或：
GCP_PROJECT_NUMBER=<project_number>
GCP_LOCATION=us-central1
SMART_AGENTS_ENGINE_ID=<smart_agents_engine_id>
```

启动：
```bash
./scripts/run_feishu_smart_agents.sh
```

## 使用

- **群聊**：`@你的机器人` + 指令，例如 `@小智 帮我拉 Etsy 评论 …`
- **私聊**：直接发文字
- 首条会先收到「小智已收到…」，处理过程中该条消息会更新为当前步骤（如转交专家、调用工具），完成后在同一线程收到最终回复

关闭反馈（可选）：

```bash
FEISHU_SEND_ACK=false          # 不发送「处理中」
FEISHU_SEND_PROGRESS=false     # 不更新进度文案
```

### 记忆与「新对话」

- 长期记忆（Memory Bank）按 **`feishu_{open_id}`** 隔离，跨群/私聊共享；仅小智使用
- 短期上下文（Session）按 **群/私聊 + 用户** 隔离
- **cloud 模式**：飞书 session 键与 Agent Engine 分配的 `session_id` 通过本地 SQLite 映射（`feishu_cloud_sessions.db`）；创建时不可传自定义 id
- **Memory Bank 刷写**：每轮对话后 Bridge 侧兜底调用 `memories.generate`（不依赖 Engine 内 callback 是否生效）
- 发送 **`新对话`** / **`/新对话`**：清空当前 Session 映射并删除云端 Session，**不**删除长期记忆
- 持久长期记忆需 **`FEISHU_RUN_MODE=cloud`** 并已 deploy（`--adk_app_object=app`）
- **知识库问答**由云端小智的 `rag_search` 处理（与飞书 Bridge 无关）；配置见根 `.env` 的 `RAG_*` 与 [`user_guide.md` §10](../../user_guide.md#10-知识库-rag-poc)

### 身份上下文与主人忠诚护栏

Bridge 在调用 Agent 前会注入结构化上下文（sender `open_id`、mentions、原始文本），见 `build_identity_prompt`。

忠诚模式（默认开启，可调）：

| 变量 | 说明 |
|------|------|
| `FEISHU_OWNER_OPEN_ID` | 主人 open_id |
| `FEISHU_OWNER_ALIASES` | 主人别名（逗号分隔） |
| `FEISHU_STRICT_LOYALTY_MODE` | `true`：拦截非主人的注入/改规则/攻击主人指令，并过滤风险回复 |

- 护栏**不阻止**其他用户写自己的 Memory Bank（记忆按 `user_id` 隔离）
- 命中注入关键词的消息会被直接拒绝，不进入 Agent

## 环境变量

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_ID` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 应用密钥（或 `FEISHU_APP_TOKEN`） |
| `FEISHU_BOT_OPEN_ID` | 可选，精确识别群聊 @ 本机器人 |
| `FEISHU_OWNER_OPEN_ID` | 可选，主人 open_id（开启忠诚防护时强烈建议填写） |
| `FEISHU_OWNER_ALIASES` | 可选，主人称呼别名，逗号分隔（如 `display_name,nickname`） |
| `FEISHU_STRICT_LOYALTY_MODE` | 默认 `true`；非主人注入/改规则/辱骂主人的指令将被拦截 |
| `FEISHU_GROUP_REQUIRE_MENTION` | 默认 `true`，群聊必须 @ |
| `FEISHU_SEND_ACK` | 默认 `true`，先回「处理中」 |
| `FEISHU_SEND_PROGRESS` | 默认 `true`，将「处理中」消息更新为当前步骤 |
| `FEISHU_PROGRESS_MIN_INTERVAL_SEC` | 进度消息最小更新间隔（秒），默认 `1.5` |
| `FEISHU_ACK_TEXT` | 「处理中」首条文案 |
| `FEISHU_RUN_MODE` | `local`（默认）或 `cloud` |
| `SMART_AGENTS_BILIBILI_MCP_SERVER_URL` | 默认 `http://127.0.0.1:8002/mcp` |
| `SMART_AGENTS_ETSY_MCP_SERVER_URL` | 默认 `http://127.0.0.1:8003/mcp` |
| `AGENT_RESOURCE_NAME` | cloud 模式可选（推荐，显式指定云端 Engine） |
| `GCP_PROJECT_NUMBER` / `SMART_AGENTS_ENGINE_ID` | cloud 模式下未设置 `AGENT_RESOURCE_NAME` 时必填 |

会话持久化：`integrations/feishu/data/feishu_sessions.db`（SQLite）。

## SSL 证书错误

若启动报 `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`，多为公司代理或 Clash MITM 导致。本地开发可在 `.env` 加：

```bash
FEISHU_SSL_VERIFY=false
```

然后重启 Bridge。生产环境应导入企业 CA 证书，而非关闭校验。

## 文件说明

| 文件 | 作用 |
|------|------|
| `bridge.py` | 长连接入口、消息收发、护栏与身份上下文注入 |
| `agent_client.py` | 双通道 Agent Client（local Runner / cloud Agent Engine） |
| `cloud_session_store.py` | 飞书逻辑 session → Engine session 映射（cloud） |
| `message_utils.py` | 解析文本、mentions、session 键、忠诚攻击检测 |
| `config.py` | 环境变量 |

## 相关文档

- 操作手册：[`../../user_guide.md`](../../user_guide.md) §5（飞书）· §4（调度树）· §10（RAG）
- 调度树：[`../../smart_agents/README.md`](../../smart_agents/README.md)
