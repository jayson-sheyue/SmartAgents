# etsy_agent — Etsy ADK 包

Etsy 专家 **E姐**：通过 **MCP + 双 Skill** 完成评论导出与上架素材换场景生图（异步）。

---

## 组成

| 部分 | 路径 |
|------|------|
| ADK 入口 | `agent.py` → `build_etsy_agent(standalone=True)` |
| L1 工具 | [`domains/etsy/`](../domains/etsy/)（`etsy_tools` · `image_tools` · `preset_tools`） |
| Agent 构建 | [`domains/etsy/builder.py`](../domains/etsy/builder.py) |
| MCP 服务 | `mcp_server/etsy_mcp.py` → **:8003/mcp** |
| Skills | `skills/etsy-review/` · `skills/etsy-listing-assets/` |
| 内置预设 | `domains/etsy/presets/builtin/*.yaml` |

---

## 本地运行

**终端 1 — MCP（必须先起）**

```bash
python mcp_server/etsy_mcp.py --http
```

**终端 2 — Agent**

```bash
./scripts/run_adk_etsy_agent.sh
```

> Etsy 凭证写在根 `.env`；`env/local.env` 设本地 MCP URL。须先起 `etsy_mcp.py --http`。

---

## 前置条件

| 能力 | 环境变量 |
|------|----------|
| 评论 API | `ETSY_KEYSTRING` · `ETSY_SHARED_SECRET` |
| 生图上传 GCS | `ETSY_IMAGE_GCS_BUCKET` 等 |
| Vertex | `GCP_PROJECT_ID`（ADC：`gcloud auth application-default login`） |

凭证自检：

```bash
python scripts/test_etsy_local.py --check-credentials --verify-api
```

---

## Skill 分工

| Skill | 场景 |
|-------|------|
| `etsy-review` | 拉评论、写 Excel |
| `etsy-listing-assets` | 预设、换场景、异步 `etsy_submit_scene_variants_job` |

Agent instruction 要求：**先 `load_skill`，再调 MCP 工具**。

---

## 作为调度树子 Agent

`smart_agents/agent.py` 使用 `build_etsy_agent(standalone=False)`。  
子 Agent 名：`Etsy_Cloud_MCP_Agent`。

---

## 云端 deploy

```bash
adk deploy agent_engine etsy_agent \
  --project=$GCP_PROJECT_ID \
  --region=$GCP_LOCATION \
  --display_name="Etsy Agent" \
  --agent_engine_id=$ETSY_MCP_AGENT_ENGINE_ID
```

云端须能访问本机 `:8003` MCP（通常经 Cloudflare 隧道）。

---

## 相关文档

- [`../user_guide.md`](../user_guide.md) §3
- [`../skills/etsy-review/SKILL.md`](../skills/etsy-review/SKILL.md)
- [`../skills/etsy-listing-assets/SKILL.md`](../skills/etsy-listing-assets/SKILL.md)
- [`../docs/agent_platform_learning_guide.md`](../docs/agent_platform_learning_guide.md) §8
