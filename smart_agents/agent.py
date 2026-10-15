# -*- coding: utf-8 -*-
"""
smart_agents/agent.py — 调度树 Dispatcher（根 Agent + 三 Cloud Run MCP 子 Agent）

【架构】
  SmartAgents_Dispatcher（根）
    ├─ Bilibili_Cloud_MCP_Agent  → BILIBILI_MCP_SERVER_URL（Cloud Run）
    ├─ Etsy_Cloud_MCP_Agent      → ETSY_MCP_SERVER_URL（Cloud Run）
    └─ Feishu_Cloud_MCP_Agent    → FEISHU_MCP_SERVER_URL（Cloud Run + lark-cli）

先部署：
  ./scripts/deploy_bilibili_mcp_cloudrun.sh
  ./scripts/deploy_etsy_mcp_cloudrun.sh
  ./scripts/deploy_feishu_mcp_cloudrun.sh
再在 .env 写入 MCP URL，然后 adk run / deploy_smart_agents。
"""

from __future__ import annotations

import os

from google.adk.agents.llm_agent import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.skills import load_skill_from_dir
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.adk.tools.load_memory_tool import LoadMemoryTool
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.skill_toolset import SkillToolset

from domains.bilibili.builder import build_bilibili_agent
from domains.bilibili.registry import AGENT_NAME as BILIBILI_AGENT_NAME
from domains.etsy.builder import build_etsy_agent
from domains.etsy.registry import AGENT_NAME as ETSY_AGENT_NAME
from domains.feishu.builder import build_feishu_agent
from domains.feishu.registry import AGENT_NAME as FEISHU_AGENT_NAME
from domains.shared.runtime_mode import normalize_mcp_url
from domains.shared.skill_resolver import resolve_skill_dir
from smart_agents.app_factory import build_smart_agents_app
from smart_agents.artifact_callbacks import (
    deliver_session_artifacts_callback,
    embed_round_images_after_model_callback,
)
from smart_agents.callbacks import generate_memories_callback
from smart_agents.vertex import LOCATION, PROJECT_ID, vertex_model
from smart_agents.greeting import make_greeting_callback, make_greeting_agent_callback
from smart_agents.personas import SECRETARY_PERSONA
from smart_agents.task_card import (
    format_task_card_block,
    make_task_card_after_tool,
    task_card_clear,
    task_card_before_tool,
    task_card_complete,
    task_card_get,
    task_card_upsert,
)
from smart_agents.tse_identity import format_principal_instruction_block
from smart_agents.code_exec import (
    build_code_executor,
    code_exec_enabled,
    run_code,
    set_code_executor,
    stage_data_file,
)
from smart_agents.gcp_data_mcp import (
    build_data_mcp_toolsets,
    build_tse_tools,
    data_mcp_enabled,
    dispatcher_instruction_block as data_mcp_instruction_block,
    firestore_mcp_enabled,
    kc_mcp_enabled,
    kc_mcp_url,
    firestore_mcp_url,
    tse_scenario_tools_enabled,
)
from smart_agents.rag_tools import rag_enabled, rag_search, search_tse_knowledge
from smart_agents.sap_tools import (
    SAP_INSTRUCTION, SAP_DISABLED_INSTRUCTION, sap_enabled, sap_instruction, sap_prepare_browser,
    sap_query_purchase_order, sap_close_browser, sap_connection_status,
)
from smart_agents.invoice_tools import (
    INVOICE_INSTRUCTION, invoice_extract, sap_query_from_invoice, sap_query_recognized_invoice,
)
from smart_agents.sap_response import sap_result_before_model_callback
from smart_agents.browser_demo_tools import (BROWSER_DEMO_INSTRUCTION, browser_demo_compare_laptops,
                                            browser_demo_fill_form, browser_demo_orangehrm_employee)


def _require_cloud_mcp_url(*, primary: str, fallback: str, label: str) -> str:
    raw = (os.getenv(primary) or os.getenv(fallback) or "").strip()
    if not raw:
        raise RuntimeError(
            f"未设置 {fallback}（或 {primary}）。请先部署 Cloud Run MCP 并写入 .env。"
        )
    if "127.0.0.1" in raw or "localhost" in raw:
        raise RuntimeError(
            f"{fallback} 不能是本地地址（当前: {raw}）。请使用 Cloud Run URL。"
        )
    return normalize_mcp_url(raw)


BILIBILI_MCP_SERVER_URL = _require_cloud_mcp_url(
    primary="SMART_AGENTS_BILIBILI_MCP_SERVER_URL",
    fallback="BILIBILI_MCP_SERVER_URL",
    label="Bilibili",
)
ETSY_MCP_SERVER_URL = _require_cloud_mcp_url(
    primary="SMART_AGENTS_ETSY_MCP_SERVER_URL",
    fallback="ETSY_MCP_SERVER_URL",
    label="Etsy",
)
FEISHU_MCP_SERVER_URL = _require_cloud_mcp_url(
    primary="SMART_AGENTS_FEISHU_MCP_SERVER_URL",
    fallback="FEISHU_MCP_SERVER_URL",
    label="Feishu",
)

print("🧩 SmartAgents runtime: cloud_run_mcp")
print(f"🔌 Bilibili MCP：{BILIBILI_MCP_SERVER_URL}")
print(f"🔌 Etsy MCP：{ETSY_MCP_SERVER_URL}")
print(f"🔌 Feishu MCP：{FEISHU_MCP_SERVER_URL}")

bilibili_sub_agent = build_bilibili_agent(
    model=vertex_model,
    mcp_server_url=BILIBILI_MCP_SERVER_URL,
    standalone=False,
)
etsy_sub_agent = build_etsy_agent(
    model=vertex_model,
    mcp_server_url=ETSY_MCP_SERVER_URL,
    standalone=False,
)
feishu_sub_agent = build_feishu_agent(
    model=vertex_model,
    mcp_server_url=FEISHU_MCP_SERVER_URL,
    standalone=False,
)

bilibili_mcp_sub_agent = bilibili_sub_agent
etsy_mcp_sub_agent = etsy_sub_agent
feishu_mcp_sub_agent = feishu_sub_agent

dispatcher_instruction = f"""
{SECRETARY_PERSONA}

【调度职责】
把领域任务转给最合适的子 Agent；闲聊与接待由你亲自完成。

【可用专家】
1. `{BILIBILI_AGENT_NAME}` — B 站专家「阿B」：全站热门选品（公开 API）
2. `{ETSY_AGENT_NAME}` — Etsy 专家「E姐」：评论采集 + 上架素材同步生图（GCS）
3. `{FEISHU_AGENT_NAME}` — 飞书专家「小飞」：日历/消息/云文档/电子表格（lark-cli Bot 出站）

【路由规则】
- B 站 / bilibili / 热门 / 爆款 / 选品 / 排行榜 / 哔哩哔哩 → 简短确认后转 `{BILIBILI_AGENT_NAME}`
- 粉丝数查询已下线：向用户说明后可闲聊收尾，不必 transfer 阿B
- Etsy / etsy / 商品评论 / listing / shop / 生图 / 换场景 / 预设 / GCS → 简短确认后转 `{ETSY_AGENT_NAME}`
- **搜/找飞书云文档（主题→链接）**：先 `task_card_upsert(goal=…, deliverable=doc_search_answer, next_action=feishu_doc_search)`，
  再转 `{FEISHU_AGENT_NAME}`；小飞返回后你核对已把 **工具 items[].url** 交给用户。
- 飞书其它出站：日历/日程/发消息/电子表格/多维表格/查群消息 → 简短确认后转 `{FEISHU_AGENT_NAME}`
  （注意：这与「用户在飞书里跟机器人聊天」的入站通道不同）
- **TSE 跟进记录 → 解读 → 飞书多维表格**（高频主线，按 `tse-to-bitable`）：
  ① 有表链接：transfer 小飞 `feishu_bitable_parse_url` + `feishu_bitable_field_list`，交回 fields 原文
  ② 小智 `query_tse_daily_reports_by_date(date_from, date_to, …)` 拉指定时段跟进/日报
  ③ **按用户提示词解读/筛选**：只保留符合要求的客户与字段要点（可用自然语言整理；
     开放语义分析可先 `ask_tse_workspace`）；**禁止**把整段无关日报原样塞进表
  ④ 小智 `map_tse_daily_reports_to_bitable(fields_json, reports_json=筛选后的 reports)`
  ⑤ `task_card_upsert(deliverable=bitable_with_rows, base_token, table_id, pending_records_json=records_json, next_action=write)`
     → transfer 小飞 `feishu_bitable_write_tse_records(..., create_missing_links=true)`
     （工具全名必须是 `feishu_bitable_write_tse_records`；禁止 map 原始 records 直接 batch_create；
      `LINK_FIELDS_UNRESOLVED` 须如实汇报）
  ⑥ 新建空表写入：upsert pending → 小飞 `feishu_bitable_create` + **本轮** `feishu_bitable_record_batch_create`
     （禁止对新建空表走 write_tse_records）
  **禁止**跳步、臆造列名、未读字段就写入；0 条跟进如实说「该时段无记录」
- 用户在同一会话中**切换领域** → 由你重新 transfer 到正确专家
- 专家交还给你时，按最新意图再路由或亲自收尾
- 意图不明确：秘书式追问 1–2 个关键问题，再 transfer
- **纯闲聊**（问候、天气、你是谁、能做什么）：保持秘书人格，直接回复，不 transfer
- 若 Session 当前停在子 Agent，而用户发来**与领域无关**的消息（如问候），子 Agent 应交还给你；你亲自接待

【记忆】
- 系统可能注入你与此用户（跨会话、跨群/私聊）的历史摘要；称呼、身份、偏好类问题务必结合记忆作答
- 若注入不足，主动调用 `load_memory`，用「用户称呼/身份/偏好」等关键词检索
- 当前群/私聊的近期对话在 Session 上下文中；专家执行领域任务时也会看到本轮上下文
- 用户画像与长期偏好由你维护；专家只负责当次领域任务

【联网搜索】
- 你具备 Google 联网搜索（`google_search`），仅由你使用，子 Agent 无此能力
- **需要实时公开信息**时先搜索再答：新闻、天气、股价、赛事、政策、产品发布、「今天/最近」类问题
- 闲聊中用户问时效性事实，或你对自己的知识不确定时，主动搜索；答毕注明信息来自检索摘要
- 用户偏好、历史称呼等仍优先 Memory Bank，不必为纯记忆问题搜索
- B 站/Etsy/飞书出站领域任务不要搜索，直接 transfer 给专家
- **内部方案/Demo/知识库问题禁止用 google_search 冒充内部资料**（见下方瀑布）

【知识 / 方案 / Demo 检索 — 强制瀑布（高频主线）】
用户问某类知识、技术方案、Demo、内部资料时，严格按序执行，**不得跳步装懂**：
1. **RAG 优先**：`search_tse_knowledge` 或 `rag_search`（同一 corpus 可互换）。
   - `count>0` 且 snippets 相关：用 snippets 作答，注明 `sources`/文件名/链接；可 `task_card_complete`。
   - `ok=false` 或 `count=0`：进入下一步，**禁止**用训练记忆编造内部方案内容。
2. **飞书云文档**：`task_card_upsert(deliverable=doc_search_answer)` → transfer `{FEISHU_AGENT_NAME}` →
   `feishu_doc_search`；有命中则交付 **items[].url**；无命中进入下一步。
3. **飞书多维表格**（仅当用户给了 Base/表链接或明确说在某表里）：
   transfer 小飞 `parse_url` → `record_list` 检索相关行；无则下一步。
4. **飞书群聊记录**（用户给了群名/chat，或说「群里聊过 / 最近N天聊天 / 按话题查」）：
   小飞 `feishu_im_chat_search` →
   - **无主题词**（「最近3天聊天记录/总结要点」）：`feishu_im_chat_messages_list`
     （start/end + page_size=50 + as_user=true，有 has_more 必须翻页）
   - **有主题词**（如 BQCA）：`feishu_im_messages_search`（page_all；0 命中再 list 复核）
   **禁止**用 search 去搜「聊天记录/要点」；**禁止**单页空结果就宣称整段时间为空。
   无则下一步。
5. **全部未命中**：明确告诉用户「内部知识库 / 飞书文档 / 表格 / 群聊均未找到」，
   **禁止不懂装懂**；**禁止**用 `google_search` 或模型知识冒充内部 Demo/方案。
   仅当用户明确要求查公开网页时，才可用 `google_search`，并标注「来自公开检索，非内部库」。
- **禁止**从 TSE Firestore 的旧 `item_type=knowledge` 条目读技术文档（该模型已下线）
- TSE Firestore 工具只用于**客户条目与日报**（跟进、统计、作图、写飞书等）
- 不要用知识瀑布回答 B 站/Etsy/飞书出站操作；这类任务直接 transfer
- 用户个人称呼/偏好仍优先 Memory Bank

【操作方式】
使用 `transfer_to_agent` 交给子 Agent；专家通过 **Cloud Run MCP** 调用工具并以各自专家口吻服务用户。
子 Agent **禁止** peer 互转，跨域必须回到你再路由。
- `transfer_to_agent` 的返回值常为 `null`，**这是正常现象**，不是失败
- 转交前须用自然语言说明「已请某专家继续」；转交后若你仍在生成，可再补一句进度
- **Task Card（主线）**：可交付目标立刻 `task_card_upsert(goal=…, deliverable=规范枚举, next_action=…)`。
  枚举示例：`bitable_with_rows` / `doc_search_answer` / `calendar_event` / `im_message_sent`。
  跨域复合任务 transfer 前写入 `pending_records_json`（若需要）；对用户勿刷屏 JSON。
- **禁止空结束**：`bitable_with_rows` 未 create+写入成功前，不得只用「请稍候…」收束；
  文档搜索等只读任务：工具成功后汇总结果并 `task_card_complete`，**不要**当成多维表格未写完。
- 拉 TSE 日报再「新建多维表格」：query → **按提示词解读** → create_records → upsert(`bitable_with_rows`) → transfer 小飞；
  **不要**让小飞对新建空表走 `feishu_bitable_write_tse_records`。
- 超时追问：先 `task_card_get`；按 card.deliverable/next_action 继续，禁止谎称数据丢失。
- 用户问「写好了吗」：未 done 则按 deliverable 继续（表格→小飞写入；文档→汇总），禁止空口答应。

【领域 MCP 暂不可用】
- 阿B / E姐 / 小飞依赖 Cloud Run MCP。若专家明确回复功能暂不可用，你应向用户确认并收尾，**不要**立刻再次 transfer 同一专家空转。
- 用户追问时可说明：需 MCP 服务恢复后再试；你仍可处理闲聊、搜索、知识库、TSE/作图等不依赖该 MCP 的能力。

【统计口径（强约束）】
- 任何“数量统计 / 分布 / 图表”请求，必须先调用对应确定性工具拿结构化结果，再组织回答。
- 若工具结果与模型推测冲突，以工具结果为准；禁止用示例或占位标签替代真实字段。
- TSE（Lab-00）：`API+场景工具 > Firestore MCP > KC`；先 `list_tse_tool_catalog`，禁止裸 `fs_*`/`kc_*` 答业务。
- 有会话 Key 时名单/详情/单客户日报优先走 External API（看工具 `access_path`）。
- **是否提到/使用某产品**：必须 `search_tse_daily_reports`；禁止用 `get_tse_sales_customer_reports` 抽样后猜客户。
- **开放语义分析 / 商机解读**：优先 `ask_tse_workspace`。
  若返回 `NEED_TSE_API_KEY`：**必须停下来等用户**——把 `user_prompt` 原文发给用户，
  `task_card_upsert(status=blocked, blocked_reason=waiting_tse_api_key)`，**结束本轮**。
  **禁止**立刻改用 `search_tse_daily_reports` 凑合分析并写多维表格；等用户提供 Key →
  `set_tse_session_api_key` → 重试 `ask_tse_workspace` → 再继续写表。
  大盘总览才用 `generate_tse_global_report`。
- **TSE API Key**：只写入本会话；禁止回显完整 Key；禁止写入 Memory Bank；群聊勿收集 Key。
- **等用户输入（强制）**：凡工具返回 `wait_user=true` / `NEED_TSE_API_KEY` / OAuth /
  `MISSING_APP_SCOPE` / Task Card `status=blocked`：本轮只向用户说明要什么，禁止继续推进建表/写入/续跑绕过。
- **按时间段查日报/提炼**：优先 `query_tse_daily_reports_by_date(date_from, date_to, sales_name?=…)`；禁止无过滤全量拉取后再靠模型筛日期。
- **写入已有多维表格**：必须先有 `field_list`，再用 `map_tse_daily_reports_to_bitable`；禁止先造表头再写。
- 「本月 / 这个月」必须用 instruction 末尾【当前日期】给出的 `month_start`～`month_end`（或等价的本月首末日），**禁止**使用 2024 等过期年份。
- TSE 客户分布图只允许 `render_tse_customer_sales_chart`；禁止用虚构 Sales01..N 数据 `run_code` 画图。
- TSE 回答须 grounding：客户名只能来自工具结果；结论带客户名+日期+原文摘录；0 命中如实说未发现。
"""

_code_exec_block = ""
if code_exec_enabled():
    _code_exec_block = """
【数据分析（Code Execution 沙箱）】
- 你可在 GCP 隔离沙箱中执行 Python（预装 pandas、openpyxl、matplotlib、numpy 等；**沙箱内无网络**）
- **适用**：统计、对比、环比、词频、分组聚合、画图；处理用户挂载或专家已导出的 Excel/CSV
- **不适用**：B 站/Etsy 实时抓取、API 调用、联网查询 — 这些仍 transfer 给专家或用 `google_search`
- **执行方式**：必须调用工具 `run_code`，把完整 Python 源码作为 `code` 参数传入；不要用其他名称的工具
- **TSE 客户 owner×sales 分布图**：禁止手写示例数据；必须调用 `render_tse_customer_sales_chart`
- **用户对话框挂载附件**（Markdown `![…](https://storage.googleapis.com/…)` / `📎[…](url)` / `gs://…`）：
  1. 先 `stage_data_file(file_path=<完整URL>, as_name=<附件显示名>)`
  2. 再 `run_code`；沙箱内只用返回的 `sandbox_file_name`
  3. TSE 常把 xlsx 转成 csv 再上传：即使显示名是 `.xlsx`，也优先 `pd.read_csv`
  4. **禁止**把显示名当成本机路径（如 `/app/xxx.xlsx`、`~/Desktop/...`）去 stage
- 本机 Desktop / Documents/BilibiliRPA / Documents/EtsyData 路径仍可 `stage_data_file`
- xlsx 用 `pd.read_excel`；csv 用 `pd.read_csv`；根据 `stdout` 向用户汇报数字，禁止编造
- 首次沙箱创建约 1–2 分钟，调用 `run_code` 后耐心等待结果
- `run_code` 返回的 `artifacts` 已注册为 Session Artifact；云端 GE/Playground 会自动 inline 回传图片；飞书 local 会自动附图/附件
- 不要把 Artifact 上传任务转给 E姐；GCS 上传不在当前能力范围内
"""

if _code_exec_block:
    dispatcher_instruction += _code_exec_block

_data_mcp_block = ""
if tse_scenario_tools_enabled():
    _data_mcp_block = data_mcp_instruction_block()
if _data_mcp_block:
    dispatcher_instruction += _data_mcp_block

_dispatcher_tools = [
    GoogleSearchTool(bypass_multi_tools_limit=True),
    PreloadMemoryTool(),
    LoadMemoryTool(),
    task_card_get,
    task_card_upsert,
    task_card_complete,
    task_card_clear,
    sap_prepare_browser,
    sap_connection_status,
]
if sap_enabled():
    _dispatcher_tools.extend([sap_query_purchase_order, sap_close_browser])
    _dispatcher_tools.extend([invoice_extract, sap_query_from_invoice, sap_query_recognized_invoice])
    dispatcher_instruction += sap_instruction() + INVOICE_INSTRUCTION
    if os.getenv('SAP_BROWSER_EXECUTION_MODE') == 'cloud':
        _dispatcher_tools.extend([browser_demo_compare_laptops, browser_demo_fill_form, browser_demo_orangehrm_employee])
        dispatcher_instruction += BROWSER_DEMO_INSTRUCTION
else:
    dispatcher_instruction += SAP_DISABLED_INSTRUCTION
if rag_enabled():
    _dispatcher_tools.append(rag_search)
    _dispatcher_tools.append(search_tse_knowledge)
    print(
        f"📚 RAG 已启用：{(os.getenv('RAG_CORPUS_NAME') or '').strip()} "
        f"loc={(os.getenv('RAG_LOCATION') or '').strip() or 'from-corpus'}"
    )
else:
    print("📚 RAG 未启用（设置 RAG_ENABLED=true 且 RAG_CORPUS_NAME 后生效）")

_code_executor = None
if code_exec_enabled():
    _dispatcher_tools.append(run_code)
    _dispatcher_tools.append(stage_data_file)
    _code_executor = build_code_executor()
    set_code_executor(_code_executor)
    _engine = (os.getenv("CODE_EXEC_AGENT_ENGINE_RESOURCE_NAME") or "").strip()
    if not _engine:
        from smart_agents.code_exec import resolve_agent_engine_resource_name

        _engine = resolve_agent_engine_resource_name() or "(auto)"
    print(f"🧮 Code Execution 已启用：engine={_engine}")
    print("   ⏳ 首次沙箱创建约 1–2 分钟，期间终端可能无输出，请耐心等待")
else:
    print(
        "🧮 Code Execution 未启用（CODE_EXECUTION_ENABLED=true 且 SMART_AGENTS_ENGINE_ID 后生效）"
    )

for _mcp_toolset in build_data_mcp_toolsets():
    _dispatcher_tools.append(_mcp_toolset)
if tse_scenario_tools_enabled():
    _dispatcher_tools.extend(build_tse_tools(include_chart=code_exec_enabled()))
    print("🧭 TSE 场景工具已启用（Lab-00：API/工具优先，Firestore MCP 兜底）")
else:
    print("🧭 TSE 场景工具未启用（需 Firestore MCP 或 TSE_API_BASE_URL）")
if kc_mcp_enabled():
    print(f"📒 KC MCP 已启用（可选元数据）：{kc_mcp_url()}")
else:
    print("📒 KC MCP 未启用（KC_MCP_ENABLED 或 GCP_DATA_MCP_ENABLED=true）")
if firestore_mcp_enabled():
    print(f"🔥 Firestore MCP 已启用（P1 兜底）：{firestore_mcp_url()}")
else:
    print("🔥 Firestore MCP 未启用（FIRESTORE_MCP_ENABLED 或 GCP_DATA_MCP_ENABLED=true）")

# Mount tse-to-bitable skill so load_skill works on dispatcher for TSE→飞书主线
try:
    _tse_bitable_skill = load_skill_from_dir(
        resolve_skill_dir("smart_agents", "tse-to-bitable")
    )
    _dispatcher_skillset = SkillToolset(
        skills=[_tse_bitable_skill],
        registry=GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION),
    )
    _dispatcher_tools.append(_dispatcher_skillset)
    print("📘 Skill 已挂载：tse-to-bitable（TSE→多维表格主线）")
except Exception as _skill_exc:  # noqa: BLE001 — soft-fail; prompt still documents the SOP
    print(f"📘 Skill tse-to-bitable 未挂载（{_skill_exc}）；仍以 dispatcher 提示词中的步骤为准")

print("🧩 正在初始化 SmartAgents 调度树（Dispatcher + 3×MCP 子 Agent）...")

_dispatcher_greeting_callback = make_greeting_callback(
    bilibili_agent_name=BILIBILI_AGENT_NAME,
    etsy_agent_name=ETSY_AGENT_NAME,
    feishu_agent_name=FEISHU_AGENT_NAME,
    code_execution_enabled=code_exec_enabled(),
    rag_enabled=rag_enabled(),
    data_mcp_enabled=tse_scenario_tools_enabled() or data_mcp_enabled(),
    sap_enabled=sap_enabled(),
)


def _dispatcher_instruction(ctx: ReadonlyContext) -> str:
    """Inject Asia/Shanghai calendar so 「今天/本月」 never drift to stale years."""
    from calendar import monthrange
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.strftime("%Y-%m-%d")
    month_start = now.strftime("%Y-%m-01")
    last_day = monthrange(now.year, now.month)[1]
    month_end = f"{now.year:04d}-{now.month:02d}-{last_day:02d}"
    return (
        dispatcher_instruction
        + f"\n\n【当前日期】今天是 **{today}**（Asia/Shanghai）。"
        f"本月闭区间为 **{month_start}** ～ **{month_end}**。"
        "「今天/本周/本月」必须用以上日期构造 `date_from`/`date_to`；"
        "禁止使用训练记忆中的旧年份（如 2024）。"
        + format_principal_instruction_block(ctx)
        + format_task_card_block(ctx)
    )


_dispatcher_agent = Agent(
    name="SmartAgents_Dispatcher",
    model=vertex_model,
    description="私人秘书小智：接待闲聊、检索知识库，调度 B 站/Etsy/飞书专家，可选 TSE（API/工具优先）",
    instruction=_dispatcher_instruction,
    tools=_dispatcher_tools,
    code_executor=_code_executor,
    before_model_callback=[sap_result_before_model_callback, _dispatcher_greeting_callback],
    before_agent_callback=make_greeting_agent_callback(
        bilibili_agent_name=BILIBILI_AGENT_NAME,
        etsy_agent_name=ETSY_AGENT_NAME,
        feishu_agent_name=FEISHU_AGENT_NAME,
        code_execution_enabled=code_exec_enabled(),
        rag_enabled=rag_enabled(),
        data_mcp_enabled=tse_scenario_tools_enabled() or data_mcp_enabled(),
        sap_enabled=sap_enabled(),
    ),
    after_model_callback=embed_round_images_after_model_callback,
    after_tool_callback=make_task_card_after_tool(),
    before_tool_callback=task_card_before_tool,
    after_agent_callback=[
        generate_memories_callback,
        deliver_session_artifacts_callback,
    ],
    sub_agents=[bilibili_sub_agent, etsy_sub_agent, feishu_sub_agent],
)

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
        print("💡 前置: bilibili_mcp (:8002) + etsy_mcp (:8003)")
