# -*- coding: utf-8 -*-
"""
smart_agents/agent.py — 调度树 Dispatcher（根 Agent + 双 MCP 子 Agent）

【架构】
  SmartAgents_Dispatcher（根）
    ├─ Bilibili_Cloud_MCP_Agent  → BILIBILI_MCP_SERVER_URL (:8002)
    └─ Etsy_Cloud_MCP_Agent      → ETSY_MCP_SERVER_URL (:8003)

【本地 adk run】
  终端 1: python mcp_server/bilibili_mcp.py --http
  终端 2: python mcp_server/etsy_mcp.py --http
  终端 3: ./scripts/run_adk_smart_agents.sh
"""

from __future__ import annotations

import os

from google.adk.agents.llm_agent import Agent
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.adk.tools.load_memory_tool import LoadMemoryTool
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

from smart_agents.app_factory import build_smart_agents_app
from smart_agents.callbacks import generate_memories_callback
from smart_agents.bilibili_mcp_sub import (
    AGENT_NAME as BILIBILI_AGENT_NAME,
    build_bilibili_mcp_sub_agent,
)
from smart_agents.etsy_mcp_sub import (
    AGENT_NAME as ETSY_AGENT_NAME,
    build_etsy_mcp_sub_agent,
)
from smart_agents.personas import SECRETARY_PERSONA
from smart_agents.rag_tools import rag_enabled, rag_search
from smart_agents.vertex import vertex_model

BILIBILI_MCP_SERVER_URL = os.getenv("BILIBILI_MCP_SERVER_URL", "http://127.0.0.1:8002/mcp").rstrip("/")
if not BILIBILI_MCP_SERVER_URL.endswith("/mcp"):
    BILIBILI_MCP_SERVER_URL = f"{BILIBILI_MCP_SERVER_URL.rstrip('/')}/mcp"

ETSY_MCP_SERVER_URL = os.getenv("ETSY_MCP_SERVER_URL", "http://127.0.0.1:8003/mcp").rstrip("/")
if not ETSY_MCP_SERVER_URL.endswith("/mcp"):
    ETSY_MCP_SERVER_URL = f"{ETSY_MCP_SERVER_URL.rstrip('/')}/mcp"

print(f"🔌 Bilibili MCP：{BILIBILI_MCP_SERVER_URL}")
print(f"🔌 Etsy MCP：{ETSY_MCP_SERVER_URL}")

bilibili_mcp_sub_agent = build_bilibili_mcp_sub_agent(
    model=vertex_model,
    mcp_server_url=BILIBILI_MCP_SERVER_URL,
)
etsy_mcp_sub_agent = build_etsy_mcp_sub_agent(
    model=vertex_model,
    mcp_server_url=ETSY_MCP_SERVER_URL,
)

dispatcher_instruction = f"""
{SECRETARY_PERSONA}

【调度职责】
把领域任务转给最合适的子 Agent；闲聊与接待由你亲自完成。

【可用专家】
1. `{BILIBILI_AGENT_NAME}` — B 站专家「阿B」：UP 主粉丝数、Excel RPA
2. `{ETSY_AGENT_NAME}` — Etsy 专家「E姐」：商品评论采集与 Excel 导出

【路由规则】
- B 站 / bilibili / UP 主 / 粉丝数 / 哔哩哔哩 → 简短确认后转 `{BILIBILI_AGENT_NAME}`
- Etsy / etsy / 商品评论 / listing / shop → 简短确认后转 `{ETSY_AGENT_NAME}`
- 用户在同一会话中**切换领域** → 由你重新 transfer 到正确专家
- 专家交还给你时，按最新意图再路由或亲自收尾
- 意图不明确：秘书式追问 1–2 个关键问题，再 transfer
- **纯闲聊**（问候、天气、你是谁、能做什么）：保持秘书人格，直接回复，不 transfer
- 若 Session 当前停在子 Agent，而用户发来**与领域无关**的消息（如问候），子 Agent 应交还给你；你亲自接待

【记忆】
- 系统可能注入你与此用户（跨会话、跨群/私聊）的历史摘要；称呼、身份、偏好类问题务必结合记忆作答
- 若注入不足，主动调用 `load_memory`，用「用户称呼/身份/偏好」等关键词检索
- 当前群/私聊的近期对话在 Session 上下文中；专家执行领域任务时也会看到本轮上下文
- 用户画像与长期偏好由你维护；专家只负责当次 RPA/采集任务

【联网搜索】
- 你具备 Google 联网搜索（`google_search`），仅由你使用，子 Agent 无此能力
- **需要实时信息**时先搜索再答：新闻、天气、股价、赛事、政策、产品发布、「今天/最近」类问题
- 闲聊中用户问时效性事实，或你对自己的知识不确定时，主动搜索；答毕注明信息来自检索摘要
- 用户偏好、历史称呼等仍优先 Memory Bank，不必为纯记忆问题搜索
- B 站/Etsy RPA 任务不要搜索，直接 transfer 给专家

【知识库检索】
- 你具备内部文档检索工具 `rag_search`（仅你使用）
- **文档/知识库问题**先调用 `rag_search`：产品说明、GCP/Vertex/Gemini 手册、权限配置、错误排查、内部 PDF 内容
- 用检索到的 snippets 作答，并简要注明来源（文件名或 source）
- 若 `ok=false` 或 snippets 为空：如实说明知识库未命中，可再问用户补充，或必要时用 `google_search` 查公开信息
- 不要用知识库回答 B 站/Etsy RPA 操作；这类任务直接 transfer
- 用户个人称呼/偏好仍优先 Memory Bank

【操作方式】
使用 `transfer_to_agent` 交给子 Agent；专家会 load_skill 并以各自专家口吻服务用户。
子 Agent **禁止** peer 互转，跨域必须回到你再路由。
"""

_dispatcher_tools = [
    GoogleSearchTool(bypass_multi_tools_limit=True),
    PreloadMemoryTool(),
    LoadMemoryTool(),
]
if rag_enabled():
    _dispatcher_tools.append(rag_search)
    print(
        f"📚 RAG 已启用：{(os.getenv('RAG_CORPUS_NAME') or '').strip()} "
        f"loc={(os.getenv('RAG_LOCATION') or '').strip() or 'from-corpus'}"
    )
else:
    print("📚 RAG 未启用（设置 RAG_ENABLED=true 且 RAG_CORPUS_NAME 后生效）")

print("🧩 正在初始化 SmartAgents 调度树（Dispatcher + 2×MCP 子 Agent）...")

_dispatcher_agent = Agent(
    name="SmartAgents_Dispatcher",
    model=vertex_model,
    description="私人秘书小智：接待闲聊、澄清意图，检索知识库，并调度 B 站/Etsy 领域专家",
    instruction=dispatcher_instruction,
    tools=_dispatcher_tools,
    after_agent_callback=generate_memories_callback,
    sub_agents=[bilibili_mcp_sub_agent, etsy_mcp_sub_agent],
)

# 部署 Agent Engine 时导出 app（含 Memory Plugin + 事件压缩）；adk run 仍用 root_agent
app = build_smart_agents_app(
    name="smart_agents",
    root_agent=_dispatcher_agent,
    enable_memory=True,
)
root_agent = _dispatcher_agent
smart_agents_dispatcher = root_agent

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "deploy":
        pid = os.getenv("GCP_PROJECT_ID", "<GCP_PROJECT_ID>")
        loc = os.getenv("GCP_LOCATION", "us-central1")
        eid = os.getenv("SMART_AGENTS_ENGINE_ID", "<SMART_AGENTS_ENGINE_ID>")
        print("🚀 部署命令:")
        print(
            f"  adk deploy agent_engine smart_agents "
            f"--project={pid} --region={loc} "
            f'--display_name="SmartAgents Dispatcher" '
            f"--agent_engine_id={eid} "
            f"--adk_app_object=app"
        )
    else:
        print("💡 本地: ./scripts/run_adk_smart_agents.sh")
        print("💡 需先启动 bilibili_mcp (:8002) 与 etsy_mcp (:8003)")
