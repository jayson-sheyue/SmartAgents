# -*- coding: utf-8 -*-
"""SmartAgents A2A Agent Card（能力名片，供 GE / RemoteA2aAgent 发现）。"""

from __future__ import annotations

from a2a.types import AgentInterface, AgentSkill
from a2a.utils.constants import TransportProtocol
from vertexai.agent_engines.templates.a2a import create_agent_card

A2A_DISPLAY_NAME = "SmartAgents A2A"
A2A_DESCRIPTION = (
    "SmartAgents dispatcher (小智): greets users, routes Bilibili/Etsy RPA experts, "
    "optional RAG / TSE Firestore read-only tools / Code Execution. "
    "Cloud RPA requires reachable MCP endpoints."
)


def build_agent_skills() -> list[AgentSkill]:
    return [
        AgentSkill(
            id="orchestration",
            name="Dispatcher Orchestration",
            description=(
                "Greet users, clarify intent, and transfer to Bilibili or Etsy "
                "domain experts when RPA is needed."
            ),
            tags=["orchestration", "dispatcher", "multi-agent"],
            examples=[
                "你好，你能做什么？",
                "帮我查 B 站 UP 主粉丝",
                "导出 Etsy listing 评论",
            ],
        ),
        AgentSkill(
            id="rag_search",
            name="Knowledge Base RAG",
            description="Search team documents via Vertex RAG Engine (when RAG_ENABLED).",
            tags=["rag", "knowledge"],
            examples=["Gemini Enterprise 权限怎么配？"],
        ),
        AgentSkill(
            id="search_tse_knowledge",
            name="TSE Knowledge Deposit RAG",
            description=(
                "Search TSE tech-knowledge deposits via Vertex RAG (not Firestore knowledge items). "
                "Prefer for TSE 技术知识库 / recently deposited files."
            ),
            tags=["rag", "tse", "knowledge"],
            examples=["知识库里关于 Vertex RAG 怎么说？"],
        ),
        AgentSkill(
            id="tse_readonly",
            name="TSE Workspace Data (read-only)",
            description=(
                "Query TSE Firestore customers, sales reports, shares, and stats "
                "via deterministic tools; keyword evidence search; optional TSE /chat "
                "(when GCP_DATA_MCP_ENABLED / TSE_API_*)."
            ),
            tags=["tse", "firestore", "readonly"],
            examples=[
                "TSE 有多少客户？",
                "梁伶飞的客户和日报",
                "张方琼的客户有没有提到 BigQuery",
                "画一张客户分布图",
            ],
        ),
        AgentSkill(
            id="code_execution",
            name="Code Execution Charts",
            description=(
                "Run sandboxed Python for analytics/charts (when CODE_EXECUTION_ENABLED)."
            ),
            tags=["code-execution", "charts"],
            examples=["用真实 TSE 数据画客户分布图"],
        ),
        AgentSkill(
            id="domain_rpa",
            name="Bilibili / Etsy RPA",
            description=(
                "Delegate to domain MCP tools for Bilibili fans Excel RPA and "
                "Etsy reviews/assets (requires reachable :8002/:8003 MCP)."
            ),
            tags=["bilibili", "etsy", "mcp", "rpa"],
            examples=["更新桌面上 UP 主粉丝数 Excel"],
        ),
    ]


def build_agent_card():
    """返回 Runtime A2A 模板兼容的 AgentCard。

    Vertex ``A2aAgent.set_up`` 只在 Card 声明 ``protocol_version=0.3`` 时
    挂载 GE 所需的 ``GET /a2a/v1/card``（a2a-sdk REST03Adapter）。
    同时保留 1.0，以满足 A2aAgent 构造校验。
    """
    card = create_agent_card(
        agent_name=A2A_DISPLAY_NAME,
        description=A2A_DESCRIPTION,
        skills=build_agent_skills(),
        default_input_modes=["text/plain"],
        default_output_modes=[
            "text/plain",
            "image/png",
            "image/jpeg",
            "application/json",
        ],
        streaming=False,
    )
    has_v03 = any(
        iface.protocol_version == "0.3"
        and iface.protocol_binding == TransportProtocol.HTTP_JSON
        for iface in card.supported_interfaces
    )
    if not has_v03:
        base_url = "http://localhost:9999/"
        if card.supported_interfaces:
            base_url = card.supported_interfaces[0].url or base_url
        card.supported_interfaces.append(
            AgentInterface(
                url=base_url,
                protocol_binding=TransportProtocol.HTTP_JSON,
                protocol_version="0.3",
            )
        )
    return card
