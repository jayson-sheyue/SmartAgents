"""Deliver terminal SAP PoC results without a second model generation."""
from __future__ import annotations

import asyncio
import html

from google.adk.models.llm_response import LlmResponse
from google.genai import types

from smart_agents.artifact_callbacks import _load_image_data_uris, mark_image_artifacts_delivered
from smart_agents.sap_recovery import sap_recovery_text

SAP_QUERY_TOOLS = frozenset({"sap_query_purchase_order", "sap_query_from_invoice", "sap_query_recognized_invoice", "browser_demo_compare_laptops", "browser_demo_fill_form", "browser_demo_orangehrm_employee", "browser_demo_orangehrm_public_account", "orangehrm_prepare_browser", "orangehrm_logout"})


def _cell(value) -> str:
    return html.escape(str(value or "未识别到")[:500]).replace("|", "\\|").replace("\n", " ").replace("\r", " ").replace("`", "&#96;")


def format_sap_result(result: dict) -> str:
    """Only tool-grounded fields; never infer SAP fields from the invoice."""
    lines = []
    invoice = result.get("invoice")
    if not isinstance(invoice, dict) and "can_query_sap" in result and isinstance(result.get("data"), dict):
        invoice = result["data"]
    if isinstance(invoice, dict):
        lines += ["**发票识别结果**", "", "| 字段 | 识别内容 | 原文证据 |", "| --- | --- | --- |"]
        for key, label in (("invoice_number", "发票编号"), ("supplier", "附件供应商"),
                           ("currency", "币种"), ("total_amount", "总金额"), ("invoice_date", "发票日期")):
            field = invoice.get(key) or {}
            if isinstance(field, dict):
                lines.append(f"| {label} | {_cell(field.get('value'))} | {_cell(field.get('evidence'))} |")
        po_evidence = next((field.get("evidence") for field in invoice.get("purchase_orders", [])
                            if isinstance(field, dict) and field.get("value") == invoice.get("purchase_order")), None)
        lines += [f"| 采购订单号 | {_cell(invoice.get('purchase_order'))} | {_cell(po_evidence)} |", ""]
    sap = result.get("sap") if isinstance(result.get("sap"), dict) else result
    order = sap.get("purchase_order") or (invoice.get("purchase_order") if isinstance(invoice, dict) else None)
    if sap.get("ok") is True and order and not result.get("wait_user"):
        lines += [f"已查询 SAP 采购订单 **{_cell(order)}**。", "",
                  "SAP 结果以本次截图为准；本次未自动核验供应商或金额一致性，未修改或过账任何单据。"]
    else:
        error = sap.get("error") if isinstance(sap.get("error"), dict) else {}
        message = sap.get("user_prompt") or error.get("message") or sap.get("message") or "尚未完成 SAP 查询。"
        lines += ["**SAP 查询尚未完成**", "", _cell(message)]
        recovery = sap_recovery_text(result)
        if recovery:
            lines += ["", recovery]
    return "\n".join(lines)


async def sap_result_before_model_callback(callback_context, llm_request):
    """Only intercept the latest terminal SAP tool response, never a new user turn."""
    contents = llm_request.contents or []
    if not contents or contents[-1].role != "user":
        return None
    responses = [part.function_response for part in contents[-1].parts or [] if part.function_response]
    if len(responses) != 1 or responses[0].name not in SAP_QUERY_TOOLS:
        return None
    result = responses[0].response
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        return None
    if responses[0].name == 'browser_demo_compare_laptops':
        from smart_agents.browser_demo_tools import format_browser_demo_result
        text = format_browser_demo_result(result, _cell)
    elif responses[0].name == 'browser_demo_fill_form':
        from smart_agents.browser_demo_tools import format_form_demo_result
        text = format_form_demo_result(result, _cell)
    elif responses[0].name in {'browser_demo_orangehrm_employee', 'browser_demo_orangehrm_public_account', 'orangehrm_prepare_browser', 'orangehrm_logout'}:
        from smart_agents.browser_demo_tools import format_orangehrm_demo_result
        text = format_orangehrm_demo_result(result, _cell)
    else:
        text = format_sap_result(result)
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    # The tool only produces one screenshot; keep this callback bounded even if malformed.
    entries = [entry for entry in artifacts[:4] if isinstance(entry, dict) and entry.get("filename")]
    if result.get("ok") is True and entries:
        try:
            images = await asyncio.wait_for(_load_image_data_uris(callback_context, entries), timeout=5)
        except Exception:
            images = []
        if images:
            text += "".join(f"\n\n![{filename}]({uri})" for filename, _mime, uri in images)
            sent = {filename for filename, _mime, _uri in images}
            mark_image_artifacts_delivered(callback_context, [entry for entry in entries if entry['filename'] in sent])
        else:
            text += "\n\n查询工具已返回，但截图暂未交付，请勿将其视为已收到截图。"
    elif result.get("ok") is True and (result.get("screenshot_delivery_failed") or
            (isinstance(result.get("sap"), dict) and result["sap"].get("screenshot_delivery_failed"))):
        text += "\n\n截图交付失败，请重新查询。"
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))
