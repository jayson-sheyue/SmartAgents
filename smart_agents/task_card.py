# -*- coding: utf-8 -*-
"""Session Task Card — deliverable-typed mainline for multi-agent Feishu tasks.

Survives handoffs better than chat alone: IDs / pending rows / next_action live in
ADK ``session.state`` (shared by 小智 + experts). Injected into dynamic instructions
every turn so compaction / short transfer replies cannot erase the goal.

State machine: ``deliverable`` + ``phase`` + ``status``. Tool results advance the
card via ``ingest_tool_result``; completion contracts are branched by deliverable
(not a single bitable-only block).
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

try:
    from google.adk.tools.tool_context import ToolContext
except ImportError:  # unit tests without ADK installed
    ToolContext = Any  # type: ignore[misc, assignment]

STATE_KEY = "smart_agents_task_card"
_ACTIVE_STATUSES = frozenset({"active", "blocked"})

# Canonical deliverable enum (TSE continue + prompts must use these strings).
DELIVERABLES = frozenset(
    {
        "bitable_with_rows",
        "bitable_link_only",
        "doc_search_answer",
        "doc_fetch",
        "doc_created",
        "calendar_event",
        "calendar_agenda",
        "im_message_sent",
        "im_chat_topic_summary",
        "sheet_updated",
        "sheet_read",
        "contact_resolved",
        "chat_resolved",
        "oauth_setup",
    }
)

# Multi-step write pipelines — TSE may auto-continue until success tool fires.
MULTI_STEP_WRITE = frozenset(
    {
        "bitable_with_rows",
        "doc_created",
        "calendar_event",
        "im_message_sent",
        "sheet_updated",
    }
)

# Read-only / single-shot — never treated as bitable incomplete.
READ_ONLY = frozenset(
    {
        "doc_search_answer",
        "doc_fetch",
        "calendar_agenda",
        "sheet_read",
        "contact_resolved",
        "chat_resolved",
        "im_chat_topic_summary",
        "bitable_link_only",
        "oauth_setup",
    }
)

_PHASES = frozenset(
    {
        "planned",
        "in_progress",
        "created",
        "searched",
        "written",
        "sent",
        "blocked",
        "done",
    }
)

_CAPTURE_OAUTH = frozenset({"feishu_oauth_start"})
_CAPTURE_OAUTH_DONE = frozenset({"feishu_oauth_complete"})
_CAPTURE_CREATE = frozenset({"feishu_bitable_create"})
_CAPTURE_COORDS = frozenset(
    {
        "feishu_bitable_parse_url",
        "feishu_bitable_table_list",
        "feishu_bitable_field_list",
    }
)
_CAPTURE_WRITE_OK = frozenset(
    {
        "feishu_bitable_record_batch_create",
        "feishu_bitable_write_tse_records",
        "feishu_bitable_record_upsert",
    }
)
_CAPTURE_DOC_SEARCH = frozenset({"feishu_doc_search"})
_CAPTURE_DOC_FETCH = frozenset({"feishu_doc_fetch"})
_CAPTURE_DOC_CREATE = frozenset({"feishu_doc_create_markdown"})
_CAPTURE_CAL_CREATE = frozenset({"feishu_calendar_create"})
_CAPTURE_CAL_AGENDA = frozenset({"feishu_calendar_agenda", "feishu_calendar_freebusy"})
_CAPTURE_IM_SEND = frozenset({"feishu_im_send_text"})
_CAPTURE_IM_TOPIC = frozenset(
    {"feishu_im_messages_search", "feishu_im_chat_messages_list"}
)
_CAPTURE_CONTACT = frozenset({"feishu_contact_search_user"})
_CAPTURE_CHAT = frozenset({"feishu_im_chat_search"})
_CAPTURE_SHEET_WRITE = frozenset({"feishu_sheet_write_csv"})
_CAPTURE_SHEET_READ = frozenset({"feishu_sheet_read"})

_AUTH_ERROR_CODES = frozenset(
    {
        "NEED_USER_OAUTH",
        "NEED_REAUTH",
        "MISSING_APP_SCOPE",
        "OAUTH_REFRESH_FAILED",
        "NEED_TSE_API_KEY",
        "NEED_TSE_API_BASE_URL",
    }
)

# tool name → (deliverable_hint, phase_on_ok, next_action_on_ok, marks_done)
_TOOL_SUCCESS_SPEC: dict[str, tuple[str, str, str, bool]] = {
    "feishu_bitable_create": (
        "bitable_with_rows",
        "created",
        "feishu_bitable_record_batch_create",
        False,
    ),
    "feishu_bitable_parse_url": (
        "bitable_with_rows",
        "in_progress",
        "feishu_bitable_field_list_or_record_batch_create",
        False,
    ),
    "feishu_bitable_table_list": (
        "bitable_with_rows",
        "in_progress",
        "feishu_bitable_record_batch_create",
        False,
    ),
    "feishu_bitable_field_list": (
        "bitable_with_rows",
        "in_progress",
        "feishu_bitable_record_batch_create_or_write_tse",
        False,
    ),
    "feishu_bitable_record_batch_create": (
        "bitable_with_rows",
        "done",
        "report_url_to_user",
        True,
    ),
    "feishu_bitable_write_tse_records": (
        "bitable_with_rows",
        "done",
        "report_url_to_user",
        True,
    ),
    "feishu_bitable_record_upsert": (
        "bitable_with_rows",
        "done",
        "report_url_to_user",
        True,
    ),
    "feishu_doc_search": (
        "doc_search_answer",
        "searched",
        "report_search_results_to_user",
        False,
    ),
    "feishu_doc_fetch": (
        "doc_fetch",
        "done",
        "report_doc_content_to_user",
        True,
    ),
    "feishu_doc_create_markdown": (
        "doc_created",
        "done",
        "report_url_to_user",
        True,
    ),
    "feishu_calendar_create": (
        "calendar_event",
        "done",
        "report_event_to_user",
        True,
    ),
    "feishu_calendar_agenda": (
        "calendar_agenda",
        "done",
        "report_agenda_to_user",
        True,
    ),
    "feishu_calendar_freebusy": (
        "calendar_agenda",
        "done",
        "report_freebusy_to_user",
        True,
    ),
    "feishu_im_send_text": (
        "im_message_sent",
        "done",
        "report_sent_to_user",
        True,
    ),
    "feishu_im_messages_search": (
        "im_chat_topic_summary",
        "searched",
        "report_topic_hits_to_user",
        False,
    ),
    "feishu_im_chat_messages_list": (
        "im_chat_topic_summary",
        "in_progress",
        "paginate_or_report_messages",
        False,
    ),
    "feishu_contact_search_user": (
        "contact_resolved",
        "searched",
        "confirm_then_send_or_invite",
        False,
    ),
    "feishu_im_chat_search": (
        "chat_resolved",
        "searched",
        "confirm_then_im_send_text",
        False,
    ),
    "feishu_sheet_write_csv": (
        "sheet_updated",
        "done",
        "report_sheet_to_user",
        True,
    ),
    "feishu_sheet_read": (
        "sheet_read",
        "done",
        "report_sheet_to_user",
        True,
    ),
    "feishu_oauth_complete": (
        "oauth_setup",
        "done",
        "resume_prior_goal",
        True,
    ),
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _state_mapping(obj: Any) -> Any:
    if obj is None:
        return None
    state = getattr(obj, "state", None)
    if state is None:
        return None
    if hasattr(state, "get") and (
        hasattr(state, "__setitem__") or isinstance(state, dict)
    ):
        return state
    return None


def get_card(state_or_ctx: Any) -> dict[str, Any]:
    state = _state_mapping(state_or_ctx)
    if state is None:
        return {}
    raw = state.get(STATE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _record_rows(raw: Any) -> Optional[list[dict[str, Any]]]:
    """Normalize supported record payloads without losing the original JSON."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if isinstance(raw, dict):
        if isinstance(raw.get("fields"), list) and isinstance(raw.get("rows"), list):
            fields = [str(field) for field in raw["fields"]]
            if any(not isinstance(row, list) or len(row) != len(fields) for row in raw["rows"]):
                return None
            raw = [dict(zip(fields, row)) for row in raw["rows"]]
        else:
            for key in ("create_records", "records", "items", "rows"):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
            else:
                return None
    if not isinstance(raw, list):
        return None
    rows = []
    for row in raw:
        if isinstance(row, str) and row.strip():
            rows.append({"名称": row.strip()})
        elif isinstance(row, dict):
            rows.append(row["fields"] if isinstance(row.get("fields"), dict) else row)
        else:
            return None
    return rows


def task_card_snapshot(card: dict[str, Any]) -> dict[str, Any]:
    """Small authoritative state for clients; never send pending business data."""
    snapshot = {key: card[key] for key in (
        "status", "phase", "deliverable", "next_action", "blocked_reason",
        "expected_record_count", "written_record_count", "completion_evidence",
    ) if key in card}
    rows = _record_rows(card.get("pending_records_json"))
    snapshot["pending_record_count"] = len(rows) if rows is not None else 0
    return snapshot


def is_active(card: dict[str, Any] | None) -> bool:
    if not card:
        return False
    return str(card.get("status") or "").strip().lower() in _ACTIVE_STATUSES


def normalize_deliverable(raw: str, *, goal: str = "", next_action: str = "") -> str:
    """Map free-text / aliases to a canonical deliverable enum value."""
    text = (raw or "").strip().lower()
    if text in DELIVERABLES:
        return text
    aliases = {
        "bitable": "bitable_with_rows",
        "bitable_rows": "bitable_with_rows",
        "多维表格": "bitable_with_rows",
        "doc_search": "doc_search_answer",
        "search_docs": "doc_search_answer",
        "calendar": "calendar_event",
        "im": "im_message_sent",
        "message": "im_message_sent",
        "im_topic": "im_chat_topic_summary",
        "chat_history": "im_chat_topic_summary",
        "群聊记录": "im_chat_topic_summary",
        "sheet": "sheet_updated",
        "oauth": "oauth_setup",
    }
    if text in aliases:
        return aliases[text]
    blob = f"{raw} {goal} {next_action}".lower()
    if any(
        x in blob
        for x in (
            "bitable",
            "多维",
            "batch_create",
            "record_batch",
            "write_tse",
            "建表",
        )
    ):
        if "link_only" in blob or "只要链接" in blob:
            return "bitable_link_only"
        return "bitable_with_rows"
    if any(
        x in blob
        for x in ("doc_search", "搜文档", "搜索文档", "云文档", "飞书文档")
    ) and "多维" not in blob and "bitable" not in blob:
        return "doc_search_answer"
    if "doc_fetch" in blob or "读文档" in blob:
        return "doc_fetch"
    if "doc_create" in blob or "创建文档" in blob:
        return "doc_created"
    if "calendar_create" in blob or "约会议" in blob or "建日程" in blob:
        return "calendar_event"
    if "agenda" in blob or "查日历" in blob or "今天日程" in blob:
        return "calendar_agenda"
    if "im_send" in blob or "发消息" in blob:
        return "im_message_sent"
    if any(
        x in blob
        for x in (
            "im_chat_topic",
            "messages_search",
            "群聊记录",
            "聊天记录",
            "按话题",
            "群里聊过",
            "群待办",
        )
    ):
        return "im_chat_topic_summary"
    if "sheet_write" in blob or "写表格" in blob:
        return "sheet_updated"
    if "sheet_read" in blob or "读表格" in blob:
        return "sheet_read"
    if "oauth" in blob:
        return "oauth_setup"
    return text  # may be empty; caller decides


def _ensure_artifacts(card: dict[str, Any]) -> dict[str, Any]:
    arts = card.get("artifacts")
    if not isinstance(arts, dict):
        arts = {}
    for key in ("base_token", "table_id", "url", "table_name", "doc_token", "event_id", "message_id"):
        top = card.get(key)
        if top and key not in arts:
            arts[key] = top
    card["artifacts"] = arts
    return arts


def _put_card(state_or_ctx: Any, card: dict[str, Any]) -> dict[str, Any]:
    state = _state_mapping(state_or_ctx)
    if state is None:
        raise RuntimeError("session.state 不可用，无法写入 Task Card")
    cleaned = {k: v for k, v in card.items() if v is not None}
    cleaned["updated_at"] = _now_iso()
    _ensure_artifacts(cleaned)
    state[STATE_KEY] = cleaned
    return cleaned


def merge_card(state_or_ctx: Any, **fields: Any) -> dict[str, Any]:
    """Merge non-empty fields into the session Task Card."""
    card = get_card(state_or_ctx)
    artifacts_patch = fields.pop("artifacts", None)
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip() and key not in (
            "blocked_reason",
            "pending_records_json",
        ):
            continue
        if key == "pending_records_json" and isinstance(value, str):
            text = value.strip()
            if text and _record_rows(text) is None:
                raise ValueError("pending_records_json 须为合法的记录数组或 create_records 对象")
            card["pending_records_truncated"] = False
            card.pop("pending_note", None)
            card[key] = text
            if text != str(get_card(state_or_ctx).get("pending_records_json") or ""):
                rows = _record_rows(text) or []
                card["expected_record_count"] = len(rows)
                card["written_record_count"] = 0
            continue
        if key == "deliverable" and isinstance(value, str):
            norm = normalize_deliverable(
                value,
                goal=str(fields.get("goal") or card.get("goal") or ""),
                next_action=str(fields.get("next_action") or card.get("next_action") or ""),
            )
            card[key] = norm if norm else value.strip()
            continue
        if key == "phase" and isinstance(value, str):
            ph = value.strip().lower()
            card[key] = ph if ph in _PHASES else ph
            continue
        card[key] = value
    if isinstance(artifacts_patch, dict):
        arts = _ensure_artifacts(card)
        for ak, av in artifacts_patch.items():
            if av is None or (isinstance(av, str) and not str(av).strip()):
                continue
            arts[ak] = av
            if ak in ("base_token", "table_id", "url", "table_name"):
                card[ak] = av
        card["artifacts"] = arts
    # Mirror top-level coords into artifacts
    for key in ("base_token", "table_id", "url", "table_name"):
        if card.get(key):
            arts = _ensure_artifacts(card)
            arts[key] = card[key]
    if not card.get("status"):
        card["status"] = "active"
    if not card.get("phase"):
        st = str(card.get("status") or "active")
        if st == "blocked":
            card["phase"] = "blocked"
        elif st == "done":
            card["phase"] = "done"
        else:
            card["phase"] = "planned"
    return _put_card(state_or_ctx, card)


def _completion_contract(deliverable: str) -> list[str]:
    """Per-deliverable completion rules injected into instructions."""
    d = (deliverable or "").strip()
    common_head = [
        "【完成契约 — 强制】",
        "1. 未把 goal 做到 done 前：禁止再次征求方案确认；用户已同意则只执行。",
        "5. 用户问进度：若未 done，立刻继续执行 next_action，禁止空口答应。",
        "6. 交付完成后 `task_card_complete`，并把结果给用户。",
    ]
    if d in ("bitable_with_rows", "bitable_link_only", "") or d.startswith("bitable"):
        return [
            "",
            "【完成契约 — 强制 · bitable】",
            "1. 未把 goal 做到 done 前：禁止再次征求方案确认；用户已同意则只执行。",
            "2. 跨 Agent 转交时必须带上 Task Card 中的 base_token/table_id/url；"
            "禁止只甩 Base 链接却丢掉 table_id。",
            "3. 建表成功后本轮优先写记录；禁止建完就交回调度员空转。",
            "4. 缺少 table_id 时先 `feishu_bitable_table_list`，禁止让用户去浏览器找 table=。",
            "5. 用户问「写好了吗/挂起等待」：若未 done，立刻继续执行 next_action，禁止空口答应。",
            "6. 交付完成后 `task_card_complete`，并把最终链接给用户。",
            "7. **禁止**在 create+写入成功前用「请稍候/正在创建/正在写入」结束本轮；"
            "要么继续调工具直到写完，要么明确卡在 OAuth（已发 verification_url）。",
        ]
    if d == "doc_search_answer":
        return [
            "",
            "【完成契约 — 强制 · 文档搜索】",
            "1. 用 `data.items[]` 的 **title + url** 列表交付用户，然后 `task_card_complete`。",
            "2. **链接只能来自** `items[].url`（`links_from_tool_only=true`）；禁止臆造飞书 URL。",
            "3. `count=0` / `empty=true`：如实说「未在飞书云文档找到」，禁止编造、禁止改走建多维表格。",
            "4. **禁止**空转 `task_card_get`；需要正文时再 `feishu_doc_fetch`；OAuth 阻塞则发 verification_url 后结束。",
        ]
    if d in ("doc_fetch", "doc_created"):
        return [
            "",
            "【完成契约 — 强制 · 文档】",
            "1. fetch/create 成功后向用户交付内容或链接，再 `task_card_complete`。",
            "2. 不要改走多维表格主线。",
        ]
    if d == "calendar_event":
        return [
            "",
            "【完成契约 — 强制 · 日历创建】",
            "1. `feishu_calendar_create` 成功后确认事件信息给用户，再 `task_card_complete`。",
            "2. 多人候选先确认再创建；OAuth 阻塞则发链接后结束。",
        ]
    if d == "calendar_agenda":
        return [
            "",
            "【完成契约 — 强制 · 查日历】",
            "1. 按工具返回的 server_today / 事件列表向用户播报，再 `task_card_complete`。",
            "2. 禁止臆测日期。",
        ]
    if d == "im_message_sent":
        return [
            "",
            "【完成契约 — 强制 · 发消息】",
            "1. 已解析收件人后本轮 `feishu_im_send_text`；成功后告知用户，再 `task_card_complete`。",
            "2. 多候选先确认；禁止建多维表格。",
        ]
    if d == "im_chat_topic_summary":
        return [
            "",
            "【完成契约 — 强制 · 群聊时间窗/话题汇总】",
            "1. `feishu_im_chat_search` 解析群。",
            "2. **无主题词**（最近N天聊天/总结要点）→ 必须 "
            "`feishu_im_chat_messages_list(chat_id,start,end,page_size=50,as_user=true)`，"
            "有 has_more 继续 page_token；**禁止** messages_search。",
            "3. **有主题词**（如 BQCA）→ `feishu_im_messages_search`"
            "（query=主题词，page_all）；0 命中再 list 复核，勿直接说群里无消息。",
            "4. 汇总须给出日期+发送人+要点；交付后 `task_card_complete`。",
        ]
    if d in ("sheet_updated", "sheet_read"):
        return [
            "",
            "【完成契约 — 强制 · 电子表格】",
            "1. 读写成功后向用户汇报，再 `task_card_complete`。",
        ]
    if d in ("contact_resolved", "chat_resolved"):
        return [
            "",
            "【完成契约 — 中间态 · 联系人/群】",
            "1. 搜索成功后列出候选并确认下游动作（发消息/邀约），必要时 upsert 下游 deliverable。",
            "2. 不要误判为多维表格未写完。",
        ]
    if d == "oauth_setup":
        return [
            "",
            "【完成契约 — OAuth】",
            "1. 已发 verification_url：结束本轮等用户；用户回复后 `feishu_oauth_complete` 再恢复原 goal。",
        ]
    # blocked_reason-driven (card may keep original deliverable e.g. bitable_with_rows)
    return [
        "",
        *common_head[:2],
        "2. 按 card.next_action 推进；完成后 `task_card_complete`。",
        "3. **禁止**把非多维表格任务当成「建表+写入」空转续跑。",
        "4. 若 status=blocked（waiting_tse_api_key / waiting_user_oauth / waiting_app_scope）："
        "只向用户要输入，禁止绕过继续写表。",
        *common_head[2:],
    ]


def format_task_card_block(state_or_ctx: Any) -> str:
    """Instruction fragment injected every turn when a card is active/done."""
    card = get_card(state_or_ctx)
    if not card:
        return (
            "\n\n【Task Card】当前无进行中的主线任务。"
            "一旦用户给出可交付目标，立刻 `task_card_upsert` 锁定 "
            "goal / deliverable（枚举如 bitable_with_rows、doc_search_answer、"
            "calendar_event、im_message_sent）/ next_action，再执行。"
        )
    status = str(card.get("status") or "active")
    deliverable = str(card.get("deliverable") or "")
    phase = str(card.get("phase") or "")
    lines = [
        "",
        "【Task Card — 会话主线（优先于聊天摘要）】",
        f"- status: {status}",
        f"- deliverable: {deliverable or '（未填）'}",
        f"- phase: {phase or '（未填）'}",
        f"- goal: {card.get('goal') or '（未填）'}",
        f"- next_action: {card.get('next_action') or '（未填）'}",
    ]
    arts = card.get("artifacts") if isinstance(card.get("artifacts"), dict) else {}
    for label, key in (
        ("base_token", "base_token"),
        ("table_id", "table_id"),
        ("url", "url"),
        ("table_name", "table_name"),
        ("doc_token", "doc_token"),
        ("event_id", "event_id"),
        ("message_id", "message_id"),
    ):
        val = card.get(key) or arts.get(key)
        if val:
            lines.append(f"- {label}: {val}")
    if card.get("blocked_reason"):
        lines.append(f"- blocked_reason: {card.get('blocked_reason')}")
    pending = str(card.get("pending_records_json") or "").strip()
    if pending:
        preview = pending if len(pending) <= 800 else pending[:800] + "…"
        lines.append(f"- pending_records_json: {preview}")
        if card.get("pending_records_truncated"):
            lines.append(f"- pending_note: {card.get('pending_note') or 'truncated'}")
    if status in _ACTIVE_STATUSES:
        lines.extend(_completion_contract(deliverable))
        if str(card.get("blocked_reason") or "") == "waiting_tse_api_key":
            lines.extend(
                [
                    "",
                    "【阻塞 — 等待 TSE API Key】",
                    "把 user_prompt 发给用户后**结束本轮**；禁止 search_tse 绕过；"
                    "用户提供 Key 后 set_tse_session_api_key → 重试原 ask_tse_workspace。",
                ]
            )
        if str(card.get("blocked_reason") or "") == "write_result_uncertain":
            lines.append("【写入结果待核查】保留待写数据；先核查远端已创建的记录/表/事件，禁止盲目重复写入或宣称完成。")
    elif status == "done":
        lines.append("主线已完成；若用户提出新任务，先 `task_card_clear` 再 upsert 新 goal。")
    return "\n".join(lines)


def unwrap_tool_envelope(tool_response: Any) -> Optional[dict[str, Any]]:
    """Best-effort unwrap MCP / ADK tool payloads into ``{ok, data, error}``."""
    if tool_response is None:
        return None
    if isinstance(tool_response, dict):
        if "ok" in tool_response:
            return tool_response
        content = tool_response.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if item.get("type") == "text" and isinstance(text, str) and text.strip():
                    try:
                        parsed = json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(parsed, dict):
                        return parsed
        for key in ("result", "response", "output"):
            nested = tool_response.get(key)
            if nested is not None and nested is not tool_response:
                found = unwrap_tool_envelope(nested)
                if found:
                    return found
        structured = tool_response.get("structuredContent")
        if isinstance(structured, dict) and "ok" in structured:
            return structured
        return tool_response
    if isinstance(tool_response, str) and tool_response.strip():
        try:
            parsed = json.loads(tool_response)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(parsed, dict):
            return unwrap_tool_envelope(parsed)
    for attr in ("structuredContent", "content", "data"):
        if hasattr(tool_response, attr):
            found = unwrap_tool_envelope(getattr(tool_response, attr))
            if found:
                return found
    return None


def _auth_block_from_env(env: dict[str, Any], data: dict[str, Any]) -> Optional[dict[str, Any]]:
    err = env.get("error") if isinstance(env.get("error"), dict) else {}
    code = str(err.get("code") or "")
    vurl = str(data.get("verification_url") or "").strip()
    aurl = str(data.get("action_url") or data.get("scope_enable_url") or "").strip()
    if code == "NEED_TSE_API_KEY" or str(env.get("blocked_reason") or "") == "waiting_tse_api_key":
        return {
            "status": "blocked",
            "phase": "blocked",
            "blocked_reason": "waiting_tse_api_key",
            "next_action": "user_provide_tse_api_key_then_set_tse_session_api_key",
        }
    if code == "NEED_TSE_API_BASE_URL":
        return {
            "status": "blocked",
            "phase": "blocked",
            "blocked_reason": "waiting_ops_tse_base_url",
            "next_action": "ops_set_TSE_API_BASE_URL",
        }
    if code == "MISSING_APP_SCOPE" or aurl:
        return {
            "status": "blocked",
            "phase": "blocked",
            "blocked_reason": "waiting_app_scope",
            "next_action": "user_enable_app_scope_then_retry",
        }
    if vurl or code in ("NEED_USER_OAUTH", "NEED_REAUTH", "OAUTH_REFRESH_FAILED"):
        return {
            "status": "blocked",
            "phase": "blocked",
            "blocked_reason": "waiting_user_oauth",
            "next_action": "user_reply_authorized_then_oauth_complete",
        }
    return None


def _ensure_deliverable(
    state_or_ctx: Any,
    hint: str,
    *,
    goal_fallback: str = "",
) -> None:
    card = get_card(state_or_ctx)
    if card.get("deliverable"):
        return
    if hint:
        merge_card(
            state_or_ctx,
            deliverable=hint,
            goal=card.get("goal") or goal_fallback or "",
            phase=card.get("phase") or "planned",
        )


def ingest_tool_result(
    *,
    tool_name: str,
    tool_response: Any,
    args: Any = None,
    state_or_ctx: Any,
) -> Optional[dict[str, Any]]:
    """Auto-update Task Card from Feishu MCP tool results. Returns new card or None."""
    name = (tool_name or "").strip()
    if not name:
        return None
    env = unwrap_tool_envelope(tool_response)
    if not isinstance(env, dict):
        return None
    data = env.get("data") if isinstance(env.get("data"), dict) else {}
    meta = env.get("meta") if isinstance(env.get("meta"), dict) else {}
    ok = bool(env.get("ok"))
    args_d = args if isinstance(args, dict) else {}
    error = env.get("error") if isinstance(env.get("error"), dict) else {}
    if error.get("code") == "TASK_BLOCKED":
        return None

    # Prefer explicit hints from tool envelope
    hint_d = str(
        data.get("deliverable_hint")
        or meta.get("deliverable_hint")
        or ""
    ).strip()
    hint_p = str(data.get("phase_hint") or meta.get("phase_hint") or "").strip()
    hint_na = str(data.get("next_action") or meta.get("next_action") or "").strip()

    try:
        # --- Wait-for-user blocking (Feishu OAuth/scope OR TSE API Key, etc.) ---
        if not ok:
            err = env.get("error") if isinstance(env.get("error"), dict) else {}
            code = str(err.get("code") or "")
            wait = bool(env.get("wait_user")) or code in _AUTH_ERROR_CODES
            if wait or data.get("verification_url") or data.get("action_url"):
                # Flatten top-level fields into data for block helper
                flat = dict(data)
                for k in ("verification_url", "action_url", "user_prompt", "blocked_reason"):
                    if env.get(k) and k not in flat:
                        flat[k] = env[k]
                block = _auth_block_from_env(env, flat)
                if block:
                    return merge_card(state_or_ctx, **block)
        if name.startswith("feishu_") and not ok:
            err = env.get("error") if isinstance(env.get("error"), dict) else {}
            code = str(err.get("code") or "")
            if code in _AUTH_ERROR_CODES or data.get("verification_url") or data.get(
                "action_url"
            ):
                block = _auth_block_from_env(env, data)
                if block:
                    return merge_card(state_or_ctx, **block)

        if name in _CAPTURE_OAUTH and (ok or isinstance(env.get("error"), dict)):
            block = _auth_block_from_env(env, data)
            if block or ok:
                patch = block or {
                    "status": "blocked",
                    "phase": "blocked",
                    "blocked_reason": "waiting_user_oauth",
                    "next_action": "user_reply_authorized_then_oauth_complete",
                }
                if not get_card(state_or_ctx).get("deliverable"):
                    patch["deliverable"] = "oauth_setup"
                return merge_card(state_or_ctx, **patch)

        if name in _CAPTURE_OAUTH_DONE and ok:
            return merge_card(
                state_or_ctx,
                status="active",
                phase="in_progress",
                blocked_reason="",
                deliverable=get_card(state_or_ctx).get("deliverable") or "oauth_setup",
                next_action=hint_na or "resume_prior_goal",
            )

        if not ok and name in _TOOL_SUCCESS_SPEC:
            err = env.get("error") if isinstance(env.get("error"), dict) else {}
            code = str(err.get("code") or "")
            if code in {"CLI_TIMEOUT", "MCP_UNAVAILABLE", "MCP_TOOLS_UNAVAILABLE", "CLI_NOT_READY"}:
                is_write = name in _CAPTURE_CREATE or _TOOL_SUCCESS_SPEC[name][0] in MULTI_STEP_WRITE
                uncertain = is_write and code != "CLI_NOT_READY"
                return merge_card(
                    state_or_ctx, status="blocked", phase="blocked",
                    blocked_reason="write_result_uncertain" if uncertain else "service_unavailable",
                    next_action="verify_remote_result_before_retry" if uncertain else "wait_service_recovery",
                )

        # --- Bitable create ---
        if name in _CAPTURE_CREATE and ok:
            bt = str(data.get("base_token") or "").strip()
            tid = str(data.get("table_id") or data.get("default_table_id") or "").strip()
            url = str(data.get("url") or "").strip()
            tname = str(data.get("table_name") or "").strip()
            fields: dict[str, Any] = {
                "status": "active",
                "phase": hint_p or "created",
                "blocked_reason": "",
                "base_token": bt,
                "table_id": tid,
                "url": url,
                "table_name": tname,
                "artifacts": {
                    "base_token": bt,
                    "table_id": tid,
                    "url": url,
                    "table_name": tname,
                },
                "next_action": hint_na
                or (
                    "feishu_bitable_record_batch_create"
                    if tid
                    else "feishu_bitable_table_list_then_batch_create"
                ),
            }
            if not get_card(state_or_ctx).get("deliverable"):
                fields["deliverable"] = hint_d or "bitable_with_rows"
            if not get_card(state_or_ctx).get("goal"):
                fields["goal"] = f"向多维表格写入数据（{tname or '新建表'}）"
            return merge_card(state_or_ctx, **fields)

        if name in _CAPTURE_COORDS and ok:
            previous = get_card(state_or_ctx)
            blocked = previous.get("status") == "blocked"
            bt = str(
                data.get("base_token") or args_d.get("base_token") or ""
            ).strip()
            tid = str(data.get("table_id") or args_d.get("table_id") or "").strip()
            url = str(data.get("url") or args_d.get("url") or "").strip()
            if name == "feishu_bitable_table_list" and not tid:
                tables = data.get("tables")
                if isinstance(tables, list) and tables:
                    first = tables[0] if isinstance(tables[0], dict) else {}
                    tid = str(
                        first.get("table_id")
                        or first.get("tableId")
                        or first.get("id")
                        or ""
                    ).strip()
            patch: dict[str, Any] = {
                "status": "blocked" if blocked else "active",
                "phase": "blocked" if blocked else hint_p or "in_progress",
                "blocked_reason": previous.get("blocked_reason") if blocked else "",
            }
            arts: dict[str, Any] = {}
            if bt:
                patch["base_token"] = bt
                arts["base_token"] = bt
            if tid:
                patch["table_id"] = tid
                arts["table_id"] = tid
                patch["next_action"] = previous.get("next_action") if blocked else hint_na or "feishu_bitable_record_batch_create"
            if url:
                patch["url"] = url
                arts["url"] = url
            if arts:
                patch["artifacts"] = arts
            _ensure_deliverable(state_or_ctx, hint_d or "bitable_with_rows")
            if len(patch) > 3 or arts:
                return merge_card(state_or_ctx, **patch)

        if name in _CAPTURE_WRITE_OK and ok:
            card = get_card(state_or_ctx)
            if card.get("deliverable") and card["deliverable"] != "bitable_with_rows":
                return None
            pending = _record_rows(card.get("pending_records_json"))
            if card.get("pending_records_truncated"):
                return merge_card(state_or_ctx, status="blocked", phase="blocked",
                                  blocked_reason="pending_records_invalid",
                                  next_action="reload_complete_pending_records")
            if pending:
                submitted = _record_rows(args_d.get("records_json"))
                if name == "feishu_bitable_record_upsert":
                    try:
                        fields = json.loads(args_d.get("fields_json") or "null")
                    except (ValueError, TypeError):
                        fields = None
                    submitted = [fields] if isinstance(fields, dict) else None
                count = None
                for blob in (data, data.get("result"), data.get("batch_create")):
                    if not isinstance(blob, dict):
                        continue
                    for key in ("created", "created_count", "create_record_count"):
                        value = blob.get(key)
                        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                            count = value
                            break
                    if count is not None:
                        break
                # A successful atomic batch confirms its submitted rows. Without
                # args, only an explicit full count can safely confirm the goal.
                if submitted is None and count == len(pending):
                    submitted = pending
                remaining = list(pending)
                matched = bool(submitted) and (count is None or count == len(submitted))
                if matched:
                    for row in submitted:
                        if row not in remaining:
                            matched = False
                            break
                        remaining.remove(row)
                if not matched:
                    return merge_card(
                        state_or_ctx, status="blocked", phase="blocked",
                        blocked_reason="write_result_uncertain",
                        next_action="verify_written_records_before_retry",
                        last_result_summary="写入已返回成功，但无法确认覆盖哪些待写记录；核查后再继续，勿重复创建。",
                    )
                written = int(card.get("written_record_count") or 0) + len(submitted)
                if remaining:
                    return merge_card(
                        state_or_ctx, status="active", phase="written", blocked_reason="",
                        pending_records_json=json.dumps({"create_records": remaining}, ensure_ascii=False),
                        expected_record_count=card.get("expected_record_count") or len(pending),
                        written_record_count=written,
                        next_action=name if name != "feishu_bitable_record_upsert" else "feishu_bitable_record_batch_create",
                        last_result_summary=f"已写入 {written} 条，剩余 {len(remaining)} 条。",
                    )
                card["written_record_count"] = written
            url = str(card.get("url") or data.get("url") or "").strip()
            summary = "记录已写入多维表格"
            if url:
                summary = f"{summary}：{url}"
            return merge_card(
                state_or_ctx,
                status="done",
                phase="done",
                blocked_reason="",
                deliverable=card.get("deliverable") or hint_d or "bitable_with_rows",
                next_action=hint_na or "report_url_to_user",
                pending_records_json="",
                last_result_summary=summary,
                expected_record_count=card.get("expected_record_count", 0),
                written_record_count=card.get("written_record_count", 0),
                completion_evidence=name,
                artifacts={"url": url} if url else None,
            )

        if not ok and name.startswith("feishu_bitable_"):
            err = env.get("error") if isinstance(env.get("error"), dict) else {}
            msg = str(err.get("message") or err.get("code") or "bitable_error")[:240]
            code = str(err.get("code") or "")
            if code in {"CLI_TIMEOUT", "MCP_UNAVAILABLE", "MCP_TOOLS_UNAVAILABLE"}:
                return merge_card(
                    state_or_ctx, status="blocked", phase="blocked",
                    blocked_reason="write_result_uncertain" if name in _CAPTURE_WRITE_OK or name in _CAPTURE_CREATE else "service_unavailable",
                    next_action="verify_remote_result_before_retry",
                    last_result_summary=msg,
                )
            next_act = "fix_cell_shape_or_field_list_then_retry_write"
            if "table_id" in msg.lower() or "NOTEXIST" in msg.upper():
                next_act = "feishu_bitable_table_list_then_retry"
            return merge_card(
                state_or_ctx,
                status="active",
                phase="in_progress",
                blocked_reason=msg,
                next_action=next_act,
                deliverable=get_card(state_or_ctx).get("deliverable")
                or "bitable_with_rows",
            )

        # --- Generic success path via TOOL_SUCCESS_SPEC / hints ---
        if ok and (
            name in _TOOL_SUCCESS_SPEC
            or name
            in (
                _CAPTURE_DOC_SEARCH
                | _CAPTURE_DOC_FETCH
                | _CAPTURE_DOC_CREATE
                | _CAPTURE_CAL_CREATE
                | _CAPTURE_CAL_AGENDA
                | _CAPTURE_IM_SEND
                | _CAPTURE_IM_TOPIC
                | _CAPTURE_CONTACT
                | _CAPTURE_CHAT
                | _CAPTURE_SHEET_WRITE
                | _CAPTURE_SHEET_READ
            )
        ):
            spec = _TOOL_SUCCESS_SPEC.get(name)
            d_hint = hint_d or (spec[0] if spec else "")
            phase = hint_p or (spec[1] if spec else "in_progress")
            next_act = hint_na or (spec[2] if spec else "report_to_user")
            marks_done = bool(spec[3]) if spec else False
            if phase == "done":
                marks_done = True

            arts: dict[str, Any] = {}
            for k in (
                "doc_token",
                "document_id",
                "url",
                "event_id",
                "message_id",
                "chat_id",
                "open_id",
                "spreadsheet_token",
            ):
                v = data.get(k)
                if v:
                    arts[k if k != "document_id" else "doc_token"] = v

            card = get_card(state_or_ctx)
            # Don't overwrite an active multi-step bitable card with a
            # contact/chat intermediate deliverable.
            # Also preserve topic-summary / other active read deliverables when
            # an intermediate chat/contact search runs in the same pipeline.
            existing = str(card.get("deliverable") or "")
            if existing in MULTI_STEP_WRITE and d_hint != existing:
                marks_done = False
                phase = "in_progress"
            _preserve_over_resolve = MULTI_STEP_WRITE | {
                "im_chat_topic_summary",
                "doc_search_answer",
                "calendar_event",
                "calendar_agenda",
            }
            if (
                existing in _preserve_over_resolve
                and d_hint in ("contact_resolved", "chat_resolved")
                and existing != d_hint
            ):
                d_hint = existing
                marks_done = False
                phase = "in_progress"
                next_act = card.get("next_action") or next_act

            patch: dict[str, Any] = {
                "status": "done" if marks_done else "active",
                "phase": "done" if marks_done else phase,
                "blocked_reason": "",
                "next_action": next_act,
            }
            if card.get("status") == "blocked":
                patch.update(status="blocked", phase="blocked",
                             blocked_reason=card.get("blocked_reason"), next_action=card.get("next_action"))
                marks_done = False
            if d_hint and (
                not existing
                or existing in ("", "oauth_setup")
                or existing == d_hint
                or d_hint not in ("contact_resolved", "chat_resolved")
            ):
                if not existing or existing == "oauth_setup":
                    patch["deliverable"] = d_hint
            if not card.get("goal") and d_hint:
                patch["goal"] = f"飞书任务：{d_hint}"
            if arts:
                patch["artifacts"] = arts
                if arts.get("url"):
                    patch["url"] = arts["url"]
            if marks_done:
                patch["completion_evidence"] = name
                patch["last_result_summary"] = (
                    str(data.get("summary") or "")[:240]
                    or f"{name} 成功"
                )
                if d_hint == "doc_search_answer":
                    # Search alone is not fully done until agent reports —
                    # keep active so agent must summarize + task_card_complete.
                    patch["status"] = "active"
                    patch["phase"] = "searched"
                    patch["next_action"] = "report_search_results_to_user"
            return merge_card(state_or_ctx, **patch)

    except RuntimeError:
        return None
    return None


def make_task_card_after_tool() -> Callable:
    """after_tool_callback that captures Feishu coords into session Task Card."""

    async def _after_tool(tool, args, tool_context, tool_response):
        name = getattr(tool, "name", None) or ""
        call_id = getattr(tool_context, "function_call_id", None)
        processed = list(tool_context.state.get("_task_card_processed_calls") or [])
        if not call_id or call_id not in processed:
            updated = ingest_tool_result(
                tool_name=str(name),
                tool_response=tool_response,
                args=args,
                state_or_ctx=tool_context,
            )
            if updated and call_id:
                tool_context.state["_task_card_processed_calls"] = [*processed, call_id][-128:]
        card = get_card(tool_context)
        env = unwrap_tool_envelope(tool_response)
        if card and isinstance(env, dict) and "ok" in env:
            meta = env.get("meta") if isinstance(env.get("meta"), dict) else {}
            return {**env, "meta": {**meta, "task_card": task_card_snapshot(card)}}
        return None

    return _after_tool


def task_card_before_tool(tool, args, tool_context) -> Optional[dict[str, Any]]:
    """Pause mutations while authorization or a previous write is unresolved."""
    card = get_card(tool_context)
    name = getattr(tool, "name", "")
    mutating = (_CAPTURE_CREATE | _CAPTURE_WRITE_OK | _CAPTURE_DOC_CREATE |
                _CAPTURE_CAL_CREATE | _CAPTURE_IM_SEND | _CAPTURE_SHEET_WRITE |
                {"feishu_bitable_record_batch_update", "feishu_bitable_enrich_tse_records"})
    if card.get("status") != "blocked" or name not in mutating:
        return None
    reason = str(card.get("blocked_reason") or "")
    result = _card_error(str(name), "TASK_BLOCKED", "任务已暂停，请先解决授权或核查前次写入结果，避免重复操作。")
    result["wait_user"] = reason.startswith("waiting_")
    result["meta"] = {"task_card": task_card_snapshot(card)}
    return result


def compose_after_tool_callbacks(*callbacks: Optional[Callable]) -> Callable:
    """Run after_tool callbacks in order; last non-None rewrite is returned to ADK."""

    active = [c for c in callbacks if c is not None]

    async def _composed(tool, args, tool_context, tool_response):
        current = tool_response
        override = None
        for cb in active:
            result = cb(tool, args, tool_context, current)
            if hasattr(result, "__await__"):
                result = await result
            if result is not None:
                override = result
                current = result
        return override

    return _composed


# ---------------------------------------------------------------------------
# Agent-facing tools (ADK FunctionTool via plain functions + ToolContext)
# ---------------------------------------------------------------------------


def task_card_get(tool_context: ToolContext) -> dict[str, Any]:
    """读取本会话 Task Card（主线目标 / deliverable / phase / coords / next_action）。"""
    card = get_card(tool_context)
    return {
        "ok": True,
        "tool": "task_card_get",
        "data": {"card": card, "active": is_active(card)},
        "error": None,
    }


def task_card_upsert(
    tool_context: ToolContext,
    goal: str = "",
    deliverable: str = "",
    status: Optional[str] = None,
    next_action: str = "",
    base_token: str = "",
    table_id: str = "",
    url: str = "",
    table_name: str = "",
    pending_records_json: Optional[str] = None,
    blocked_reason: Optional[str] = None,
    phase: str = "",
) -> dict[str, Any]:
    """创建或更新会话主线 Task Card。跨 Agent 复合任务开场必调。

    deliverable 必须用枚举：``bitable_with_rows`` / ``doc_search_answer`` /
    ``calendar_event`` / ``im_message_sent`` / ``sheet_updated`` 等。
    status：``active`` | ``blocked`` | ``done`` | ``abandoned``。
    phase：``planned`` | ``in_progress`` | ``created`` | ``searched`` | ``done`` …
    """
    goal_s = (goal or "").strip()
    na_s = (next_action or "").strip()
    d_raw = (deliverable or "").strip()
    d_norm = normalize_deliverable(d_raw, goal=goal_s, next_action=na_s) if (
        d_raw or goal_s or na_s
    ) else ""
    existing = get_card(tool_context)
    st = (status or existing.get("status") or "active").strip()
    if st not in {"active", "blocked", "done", "abandoned"}:
        return _card_error("task_card_upsert", "INVALID_STATUS", "不支持的任务状态")
    if d_norm and d_norm not in DELIVERABLES:
        return _card_error("task_card_upsert", "INVALID_DELIVERABLE", "请使用支持的 deliverable 枚举")
    if st == "done" and existing.get("status") != "done":
        return _card_error("task_card_upsert", "COMPLETION_NOT_VERIFIED", "请通过 task_card_complete 校验后完成任务")
    ph = (phase or "").strip().lower()
    if not ph:
        if st == "blocked":
            ph = "blocked"
        elif st == "done":
            ph = "done"
        else:
            ph = "in_progress" if status == "active" and existing.get("status") == "blocked" else existing.get("phase") or "planned"
    if ph not in _PHASES:
        return _card_error("task_card_upsert", "INVALID_PHASE", "不支持的任务阶段")
    if ph == "done" and st != "done":
        return _card_error("task_card_upsert", "COMPLETION_NOT_VERIFIED", "done 阶段仅用于已验证完成的任务")
    try:
        card = merge_card(
            tool_context,
            goal=goal_s,
            deliverable=d_norm,
            status=st,
            phase=ph,
            next_action=na_s,
            base_token=(base_token or "").strip(),
            table_id=(table_id or "").strip(),
            url=(url or "").strip(),
            table_name=(table_name or "").strip(),
            pending_records_json=pending_records_json,
            blocked_reason="" if blocked_reason is None and status == "active" else blocked_reason,
            artifacts={
                k: v
                for k, v in {
                    "base_token": (base_token or "").strip(),
                    "table_id": (table_id or "").strip(),
                    "url": (url or "").strip(),
                    "table_name": (table_name or "").strip(),
                }.items()
                if v
            }
            or None,
        )
    except ValueError as exc:
        return _card_error("task_card_upsert", "INVALID_PENDING_RECORDS", str(exc))
    except RuntimeError as exc:
        return {
            "ok": False,
            "tool": "task_card_upsert",
            "data": {},
            "error": {"code": "NO_SESSION_STATE", "message": str(exc), "retryable": False},
        }
    return {
        "ok": True,
        "tool": "task_card_upsert",
        "data": {"card": card},
        "error": None,
        "meta": {
            "hint": "后续优先使用 card 内 deliverable/phase/base_token/table_id",
            "deliverable": card.get("deliverable"),
            "phase": card.get("phase"),
        },
    }


def _card_error(tool: str, code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "tool": tool, "data": {},
            "error": {"code": code, "message": message, "retryable": False}}


def task_card_complete(
    tool_context: ToolContext,
    summary: str = "",
) -> dict[str, Any]:
    """将主线标为 done，并清空 pending_records（保留 url/token 便于回访）。"""
    card = get_card(tool_context)
    if not card:
        return {
            "ok": True,
            "tool": "task_card_complete",
            "data": {"card": {}, "note": "无进行中任务"},
            "error": None,
        }
    if card.get("status") == "blocked":
        return _card_error("task_card_complete", "TASK_BLOCKED", "任务仍处于阻塞状态，请先解决阻塞")
    if card.get("pending_records_json") or card.get("pending_records_truncated"):
        return _card_error("task_card_complete", "PENDING_RECORDS", "仍有待核查或待写记录，不能宣称全部完成")
    if card.get("deliverable") in MULTI_STEP_WRITE and not card.get("completion_evidence"):
        return _card_error("task_card_complete", "COMPLETION_NOT_VERIFIED", "尚无对应写操作的成功证据")
    try:
        card = merge_card(
            tool_context,
            status="done",
            phase="done",
            blocked_reason="",
            next_action="none",
            pending_records_json="",
            last_result_summary=(summary or card.get("last_result_summary") or "").strip(),
        )
    except RuntimeError as exc:
        return {
            "ok": False,
            "tool": "task_card_complete",
            "data": {},
            "error": {"code": "NO_SESSION_STATE", "message": str(exc), "retryable": False},
        }
    return {
        "ok": True,
        "tool": "task_card_complete",
        "data": {"card": card},
        "error": None,
    }


def task_card_clear(tool_context: ToolContext) -> dict[str, Any]:
    """清除会话 Task Card（用户开新任务或明确取消时）。"""
    state = _state_mapping(tool_context)
    if state is None:
        return {
            "ok": False,
            "tool": "task_card_clear",
            "data": {},
            "error": {
                "code": "NO_SESSION_STATE",
                "message": "session.state 不可用",
                "retryable": False,
            },
        }
    if STATE_KEY in state:
        try:
            del state[STATE_KEY]
        except Exception:
            state[STATE_KEY] = {}
    return {
        "ok": True,
        "tool": "task_card_clear",
        "data": {"cleared": True},
        "error": None,
    }
