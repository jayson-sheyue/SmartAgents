# integrations — 外部 IM / 平台接入

| 目录 | 说明 |
|------|------|
| [`feishu/`](feishu/) | 飞书群聊/私聊 → `smart_agents`（local 本机 Runner / cloud Agent Engine） |

飞书 Bridge 支持双通道：

- **local**：进程内 ADK Runner，与 `adk run smart_agents` 等价
- **cloud**：`streamQuery` 调用已部署的 Agent Engine（须 `--adk_app_object=app` 才有完整记忆）

知识库 RAG、主人忠诚护栏等能力见：

- [`../user_guide.md`](../user_guide.md) §5 / §10
- [`feishu/README.md`](feishu/)

总览：[`../README.md`](../README.md)
