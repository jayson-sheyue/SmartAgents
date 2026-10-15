# -*- coding: utf-8 -*-
"""MCP 可达性探测 + 子 Agent 防空转重试。

当 B 站 / Etsy MCP 因隧道、进程或网络不可达时：
- before_model：仅在「领域工具循环」或「明确的领域新请求」时短路；
  用户要交回小智 / 跨域时必须放行模型，否则无法 transfer_to_agent
- FunctionTool：供小智/专家主动查询状态
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional, Sequence

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from domains.shared.mcp_health import probe_mcp_endpoint
from domains.shared.runtime_mode import normalize_mcp_url
from smart_agents.task_card import unwrap_tool_envelope

_PROBE_CACHE_KEY = "_mcp_probe_cache"
_HARD_FAIL_KEY = "_mcp_hard_fail"
_PROBE_TTL_SEC = 20.0

_NETWORK_ERROR_HINTS = (
    "unreachable",
    "timed out",
    "timeout",
    "connecterror",
    "connection",
    "connect refused",
    "name resolution",
    "nodename nor servname",
    "temporary failure",
    "tunnel",
    "502",
    "503",
    "504",
    "ssl",
    "session not found",
    "invalid or expired session",
    "不可达",
    "连接失败",
    "连接被拒绝",
    "网络",
)


_HANDBACK_HINTS = (
    "转小智",
    "交回小智",
    "找小智",
    "回小智",
    "小智秘书",
    "交给小智",
    "换小智",
    "smartagents_dispatcher",
    "dispatcher",
)

# 仅小智有 Code Exec / stage_data_file；专家必须交回，禁止「我做不到」空转
_CODE_EXEC_HANDBACK_HINTS = (
    "run_code",
    "stage_data_file",
    "code execution",
    "code exec",
    "pandas",
    "matplotlib",
    "调研报告",
    "数据分析",
    "统计分析",
    "做统计",
    "算一下",
    "画图",
    "画张图",
    "柱状图",
    "饼图",
    "折线图",
    "散点图",
    "可视化",
    "excel 分析",
    "csv 分析",
    "读一下这",
    "读一下附",
    "分析这表",
    "分析表格",
    "分析附件",
    "分析文件",
    "分析这份",
    "生成报告",
    "出一份报告",
    "环比",
    "同比",
    "词频",
    "聚合",
    "分组统计",
    ".xlsx",
    ".xls",
    ".csv",
    "storage.googleapis.com",
    "gs://",
)


def expert_handback_instruction(dispatcher_name: str) -> str:
    """子 Agent 交回小智的统一硬规则（含 Code Exec）。"""
    return f"""
【调度交还 — 强制】
你**没有** `run_code` / `stage_data_file` / RAG / TSE Firestore 工具。遇到下列任一情况，
**立刻** `transfer_to_agent` 给 `{dispatcher_name}`，一句交接即可，禁止反复说「我做不到」「没有代码能力」：
- 数据分析、统计、调研报告、画图/可视化、pandas/Excel/CSV 深度分析
- 用户挂载了表格附件（`📎[…](url)` / `![…](url)` / `gs://` / storage.googleapis.com）并要求解读数字
- **需要从 TSE / Firestore /「系统日报」取数或按表字段映射**（你只能写飞书；取数/映射必须小智先做；你可先 `field_list` 交回）
- 非本领域任务，或用户说「转小智 / 交回秘书」
交接话术示例：「这个要走数据分析沙箱，我请小智接手。」 / 「表字段我已读完，请小智按字段映射 TSE 后再交给我写入。」然后 transfer，不要空转辩解。
`transfer_to_agent` 返回 null 属正常。你被转交接手时，必须立刻自然语言开口并继续任务，禁止静默。
""".strip()



def _cache_get(state: Any, url: str) -> Optional[dict[str, Any]]:
    raw = state.get(_PROBE_CACHE_KEY) if hasattr(state, "get") else None
    if not isinstance(raw, dict):
        return None
    entry = raw.get(url)
    if not isinstance(entry, dict):
        return None
    ts = entry.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    if time.time() - float(ts) > _PROBE_TTL_SEC:
        return None
    result = entry.get("result")
    return result if isinstance(result, dict) else None


def _cache_set(state: Any, url: str, result: dict[str, Any]) -> None:
    raw = {}
    existing = state.get(_PROBE_CACHE_KEY) if hasattr(state, "get") else None
    if isinstance(existing, dict):
        raw = dict(existing)
    raw[url] = {"ts": time.time(), "result": result}
    state[_PROBE_CACHE_KEY] = raw


def probe_mcp_cached(state: Any, url: str, *, label: str) -> dict[str, Any]:
    mcp_url = normalize_mcp_url(url)
    cached = _cache_get(state, mcp_url)
    if cached is not None:
        return cached
    result = probe_mcp_endpoint(mcp_url, label=label)
    _cache_set(state, mcp_url, result)
    return result


def is_networkish_failure(message: str) -> bool:
    text = (message or "").lower()
    return any(h in text for h in _NETWORK_ERROR_HINTS)


def is_tool_missing_failure(message: str) -> bool:
    """ADK 在 McpToolset 未挂上工具时会抛 Tool 'x' not found。"""
    text = (message or "").lower()
    return "tool '" in text and "not found" in text


def user_facing_mcp_down_message(
    *,
    expert_name: str,
    domain_label: str,
    mcp_url: str,
    detail: str = "",
) -> str:
    detail_line = f"\n（技术详情：{detail}）" if detail else ""
    return (
        f"抱歉，我是{expert_name}。当前 **{domain_label} MCP 暂不可用**"
        f"（常见原因：Cloud Run 上有状态会话失效 / Session not found，"
        f"不一定是网络不通）。\n\n"
        f"请稍后再试或开新会话；维护人员请确认 MCP 已以 "
        f"`stateless_http` 部署（`{mcp_url}`）。"
        f"{detail_line}\n\n"
        "我不会继续反复重试同一操作。"
        "若要做其它事或切换助手，请直接说「转小智」或说明新需求，我会交回秘书处理。"
    )


def _latest_user_text(llm_request: LlmRequest) -> str:
    for content in reversed(llm_request.contents or []):
        if content.role != "user" or not content.parts:
            continue
        chunks = [p.text for p in content.parts if p.text]
        if chunks:
            return "".join(chunks)
    return ""


def _is_tool_loop_continuation(llm_request: LlmRequest) -> bool:
    """上一跳是工具结果 → 仍在同轮工具循环，可短路防空转。"""
    contents = list(llm_request.contents or [])
    if not contents:
        return False
    last = contents[-1]
    if getattr(last, "role", None) == "user":
        return False
    for part in last.parts or []:
        if getattr(part, "function_response", None) is not None:
            return True
        # 部分运行时用 function_call 后的 user/tool 角色承载结果
        fr = getattr(part, "function_response", None)
        if fr is not None:
            return True
    role = (getattr(last, "role", None) or "").lower()
    return role in {"tool", "function"}


def _text_has_any(text: str, hints: Sequence[str]) -> bool:
    hay = (text or "").lower()
    return any(h.lower() in hay for h in hints if h)


def _clear_hard_fail(state: Any) -> None:
    if hasattr(state, "__setitem__"):
        state[_HARD_FAIL_KEY] = ""


def make_mcp_guard_before_model(
    *,
    mcp_url: str,
    label: str,
    expert_name: str,
    domain_label: str,
    domain_request_hints: Sequence[str] = (),
    other_domain_hints: Sequence[str] = (),
) -> Callable:
    """MCP 不可达时有条件短路，避免挡住 transfer / 跨域。"""
    url = normalize_mcp_url(mcp_url)

    def _canned(detail: str = "") -> LlmResponse:
        msg = user_facing_mcp_down_message(
            expert_name=expert_name,
            domain_label=domain_label,
            mcp_url=url,
            detail=detail,
        )
        return LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=msg)])
        )

    async def _guard(
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        state = callback_context.state
        hard = state.get(_HARD_FAIL_KEY) if hasattr(state, "get") else None
        hard_text = str(hard).strip() if hard else ""

        status = await asyncio.to_thread(probe_mcp_cached, state, url, label=label)
        if status.get("ok") and not (hard_text and _is_tool_loop_continuation(llm_request)):
            _clear_hard_fail(state)
            return None

        detail = hard_text or str(
            status.get("message") or status.get("error") or ""
        )[:200]

        # 工具循环内：短路，禁止换工具名空转
        if _is_tool_loop_continuation(llm_request):
            return _canned(detail)

        user_text = _latest_user_text(llm_request)
        # 交回秘书 / 跨域 / Code Exec：必须放行模型，否则人格卡死
        if (
            _text_has_any(user_text, _HANDBACK_HINTS)
            or _text_has_any(user_text, _CODE_EXEC_HANDBACK_HINTS)
            or _text_has_any(user_text, other_domain_hints)
        ):
            _clear_hard_fail(state)
            return None

        # 新用户轮次且仍是本领域请求：直接告知不可用
        if _text_has_any(user_text, domain_request_hints):
            return _canned(detail)

        # 其它（闲聊、模糊、未识别意图）：放行，让专家自行交还或说明
        _clear_hard_fail(state)
        return None

    return _guard


def make_mcp_fail_fast_after_tool(
    *,
    mcp_url: str,
    label: str,
) -> Callable:
    """工具结果像网络故障时打标，下一轮 before_model 直接告知用户。"""

    async def _after_tool(tool, args, tool_context, tool_response):
        envelope = unwrap_tool_envelope(tool_response)
        if not isinstance(envelope, dict) or envelope.get("ok") is not False:
            return None
        err = envelope.get("error")
        if not isinstance(err, dict):
            return None
        code = str(err.get("code") or "").upper()
        text = f"{code} {err.get('message', '')}"
        # CLI/business errors are not transport failures, even if they mention
        # timeout/SSL. Successful search content must never be scanned.
        if code in {"MCP_UNAVAILABLE", "MCP_TOOLS_UNAVAILABLE", "UNREACHABLE", "SESSION_ERROR", "CONNECTION_ERROR"}:
            tool_context.state[_HARD_FAIL_KEY] = text[:300]
            return {
                "ok": False,
                "tool": getattr(tool, "name", "mcp_tool"),
                "data": envelope.get("data") or {},
                "error": {
                    "code": "MCP_UNAVAILABLE",
                    "message": (
                        f"{label} MCP 疑似网络不可达，请停止重试并告知用户功能暂不可用。"
                        f" detail={text[:180]}"
                    ),
                    "retryable": False,
                },
                "meta": {**(envelope.get("meta") or {}), "mcp_url": normalize_mcp_url(mcp_url)},
            }
        return None

    return _after_tool


def make_mcp_on_tool_error(
    *,
    mcp_url: str,
    label: str,
) -> Callable:
    """工具抛连接异常时，转为不可重试 envelope，避免 ADK 空转。"""

    async def _on_error(tool, args, tool_context, error: Exception):
        text = f"{type(error).__name__}: {error}"
        tool_missing = is_tool_missing_failure(text)
        if not is_networkish_failure(text) and not tool_missing:
            return None
        tool_context.state[_HARD_FAIL_KEY] = text[:300]
        if tool_missing:
            code = "MCP_TOOLS_UNAVAILABLE"
            message = (
                f"{label} MCP 工具未挂载到当前 Agent（常见于 Streamable HTTP "
                f"会话 404 / Session not found，不是 VPC 断网）。"
                f"请停止重试并建议用户开新会话；维护人员检查 Cloud Run MCP "
                f"是否已启用 stateless_http。 detail={text[:160]}"
            )
        else:
            code = "MCP_UNAVAILABLE"
            message = (
                f"{label} MCP 调用失败（连接/会话异常），请停止重试并告知用户。"
                f" detail={text[:180]}"
            )
        return {
            "ok": False,
            "tool": getattr(tool, "name", "mcp_tool"),
            "data": {},
            "error": {
                "code": code,
                "message": message,
                "retryable": False,
            },
            "meta": {"mcp_url": normalize_mcp_url(mcp_url)},
        }

    return _on_error


def build_check_mcp_tool(*, mcp_url: str, label: str, tool_name: str) -> FunctionTool:
    """始终可用的探测工具（不依赖 McpToolset 是否挂载成功）。"""
    url = normalize_mcp_url(mcp_url)

    def _check() -> dict[str, Any]:
        result = probe_mcp_endpoint(url, label=label)
        result["tool"] = tool_name
        if not result.get("ok"):
            result["retryable"] = False
            result["advice"] = (
                "请停止重试领域 MCP 工具，直接告知用户因网络原因功能暂不可用。"
            )
        return result

    _check.__name__ = tool_name
    _check.__doc__ = (
        f"检查 {label} MCP 端点是否可达（{url}）。"
        "在调用领域工具前或工具连续失败时使用；"
        "若 ok=false，必须停止重试并告知用户功能暂不可用。"
    )
    return FunctionTool(_check)


def mcp_fail_fast_instruction(*, domain_label: str, check_tool_name: str) -> str:
    return f"""
【MCP 不可用 — 强制规则】
- 可先调用 `{check_tool_name}` 检查 {domain_label} MCP 是否可达。
- 若探测失败，或任意 MCP 工具返回连接/会话/`MCP_UNAVAILABLE`/`MCP_TOOLS_UNAVAILABLE`/`retryable=false`：
  **最多尝试 1 次后立即停止**，用口语说明「{domain_label} 服务暂不可用」，
  **不要**把 Session not found / 工具未挂载说成用户侧网络故障；**禁止**反复 `load_skill`、禁止换工具名空转重试。
- 若当前可用工具列表里没有领域 MCP 工具（仅有 load_skill 等），视为 MCP 未挂载，同样直接告知用户，禁止编造工具名。
- **人格切换优先**：用户说「转小智 / 交回秘书」、提出数据分析/调研报告/画图、或非本领域任务时，即使 MCP 不可用，
  也必须立刻 `transfer_to_agent` 给 `SmartAgents_Dispatcher`，禁止重复粘贴同一段 MCP 不可用话术。
""".strip()
