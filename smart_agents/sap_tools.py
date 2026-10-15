"""Optional SAP browser worker client. No browser or SDK added to Agent Engine."""
from __future__ import annotations

import os
import base64
import asyncio
from urllib.parse import urlsplit

import httpx
from google.adk.tools import ToolContext

from domains.sap.policy import validate_order
from smart_agents.tse_identity import resolve_tse_principal


def sap_enabled() -> bool:
    return os.getenv("SAP_COMPUTER_USE_ENABLED", "false").strip().lower() in {"true", "1", "yes"}


def _identity(context: ToolContext) -> str:
    principal = resolve_tse_principal(context)
    if principal["scoped"]:
        return "tse:" + principal["email"]
    user = getattr(context, "user_id", "")
    if not user:
        raise ValueError("SAP 查询需要已绑定用户的会话")
    return "adk:" + user


async def _request_raw(action: str, context: ToolContext, order: str = "") -> dict:
    if not sap_enabled():
        return {"ok": False, "wait_user": True, "error": {"code": "SAP_DISABLED",
            "message": "项目已接入 SAP Computer Use，但当前部署未启用。请由管理员在 SmartAgents "
                       "Agent Engine 运行环境设置 SAP_COMPUTER_USE_ENABLED=true，并配置云端可达的 "
                       "SAP 浏览器服务 HTTPS 地址和认证令牌后重新部署。仅更新 TSE 或本机 env/local.env 不会开启云端能力。"}}
    url = os.getenv("SAP_COMPUTER_USE_WORKER_URL", "").strip().rstrip("/")
    token = os.getenv("SAP_COMPUTER_USE_TOKEN", "").strip()
    parsed = urlsplit(url)
    if (not token or len(token) < 32 or parsed.username or parsed.password or parsed.query
            or parsed.fragment or not parsed.hostname or (parsed.scheme != "https"
            and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}))):
        return {"ok": False, "wait_user": True, "error": {"code": "SAP_WORKER_NOT_CONFIGURED",
                "message": "请配置 SAP 浏览器执行服务地址和至少 32 字符的认证令牌"}}
    try:
        user = _identity(context)
        from smart_agents.sap_transport import worker_headers
        cloud = os.getenv('SAP_BROWSER_EXECUTION_MODE', 'local') == 'cloud'
        headers = await asyncio.to_thread(worker_headers, url, token,
            iam=os.getenv('SAP_COMPUTER_USE_IAM_AUTH', 'true' if cloud else 'false').lower() in {'true', '1', 'yes'})
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(200, connect=5),
                                     follow_redirects=False) as client:
            response = await client.post(url + "/" + action,
                headers=headers,
                json={"user_id": user, "purchase_order": order})
        if response.status_code != 200:
            if response.status_code in {401, 403}:
                code, message = ("SAP_AUTH_FAILED", "本机 SAP 节点认证失败，请核对 Agent Engine 与本机节点的令牌。") if response.status_code == 401 else (
                    "SAP_USER_NOT_ALLOWED", "当前 TSE 账号尚未绑定到这台电脑。请用该登录邮箱重新启动本机 SAP 接入脚本。")
                return {"ok": False, "wait_user": True, "error": {"code": code, "message": message}}
            return {"ok": False, "wait_user": True, "error": {"code": "SAP_WORKER_ERROR",
                    "message": f"SAP 本机接入服务返回 HTTP {response.status_code}，请检查电脑和 HTTPS 隧道是否仍在运行"}}
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise ValueError("invalid worker result")
        return result
    except httpx.TimeoutException:
        return {"ok": False, "wait_user": True, "error": {"code": "SAP_TIMEOUT",
                "message": "SAP 查询超时；请查看浏览器状态后重试"}}
    except httpx.ConnectError:
        return {"ok": False, "wait_user": True, "error": {"code": "SAP_UNAVAILABLE",
                "message": "无法连接本机 SAP 节点的 HTTPS 入口。请检查 worker 和隧道是否仍在线；"
                           "若临时域名已失效或地址发生变化，需同步新地址并更新 SmartAgents Agent Engine。"}}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "wait_user": True, "error": {"code": "SAP_UNAVAILABLE",
                "message": "无法连接本机 SAP 节点。请保持电脑、worker 和 HTTPS 隧道运行，确认隧道地址未变更以及会话身份已绑定。"}}


async def _request(action: str, context: ToolContext, order: str = '') -> dict:
    result = await _request_raw(action, context, order)
    if os.getenv('SAP_BROWSER_EXECUTION_MODE', 'local') == 'cloud':
        result.setdefault('execution_location', 'cloud_browser')
        result.setdefault('connection_mode', 'cloud_to_cloud')
        error = result.get('error')
        if isinstance(error, dict):
            code = error.get('code')
            messages = {
                'SAP_UNAVAILABLE': '无法连接云端 SAP 浏览器服务，请管理员检查服务状态、IAM 调用权限和云端地址配置。无需本机隧道。',
                'SAP_WORKER_ERROR': '云端 SAP 浏览器服务返回异常，请管理员检查服务状态和日志。',
                'SAP_AUTH_FAILED': '云端 SAP 浏览器认证失败，请管理员核对 IAM 调用权限及服务令牌。',
                'SAP_USER_NOT_ALLOWED': '云端 SAP 访问被拒绝，请管理员核对 Cloud Run IAM 调用权限与当前 TSE 账号范围。',
                'SAP_TIMEOUT': '云端 SAP 查询超时，尚未确认完成，请稍后检查连接再试。',
            }
            if code in messages:
                error['message'] = messages[code]
    return result


async def sap_connection_status(tool_context: ToolContext) -> dict:
    """检查 SAP 浏览器服务连通性和当前用户登录状态，不打开浏览器或查询。"""
    return await _request("status", tool_context)


async def sap_prepare_browser(tool_context: ToolContext) -> dict:
    """连接 SAP：先检查当前部署是否启用；启用后准备独立浏览器并给出对应登录方式。"""
    return await _request("prepare", tool_context)


async def sap_query_purchase_order(purchase_order: str, tool_context: ToolContext) -> dict:
    """通过 Computer Use 查询 10 位采购订单，返回结果截图；未登录时打开专用浏览器供人登录。"""
    try:
        validate_order(purchase_order)
    except ValueError as exc:
        return {"ok": False, "error": {"code": "INVALID_ORDER", "message": str(exc)}}
    result = await _request("query", tool_context, purchase_order)
    if not result.get("ok") and result.get("error", {}).get("code") == "LOGIN_REQUIRED":
        prepared = await sap_prepare_browser(tool_context)
        if not prepared.get("ok"):
            return {**prepared, "purchase_order": purchase_order}
        if prepared.get("logged_in") is True and not prepared.get("wait_user"):
            # The saved login may restore a ready browser; execute the original
            # read once. Never retry arbitrary failures or loop through login.
            result = await _request("query", tool_context, purchase_order)
        else:
            return {**result, "wait_user": True, "purchase_order": purchase_order,
                    "user_prompt": prepared.get("user_prompt") or prepared.get("message") or
                        "请在本机专用 SAP 浏览器亲自登录，完成后回复‘已登录，继续查询’。",
                    "browser_opened": True, "execution_location": prepared.get('execution_location', 'local_browser'),
                    "browser_login_required": prepared.get('browser_login_required', False),
                    "next_action": "sap_query_purchase_order"}
    encoded = result.pop("screenshot_base64", None)
    if result.get("ok") and encoded:
        from google.genai import types
        from smart_agents.artifact_callbacks import record_image_artifact_for_delivery
        filename = f"sap-order-{purchase_order}.png"
        try:
            version = await tool_context.save_artifact(filename=filename,
                artifact=types.Part.from_bytes(data=base64.b64decode(encoded, validate=True), mime_type="image/png"))
            record_image_artifact_for_delivery(tool_context.state, filename=filename, version=version, mime_type="image/png")
            result["artifacts"] = [{"filename": filename, "version": version, "mime_type": "image/png"}]
        except Exception:
            result["screenshot_delivery_failed"] = True
            result["message"] = "SAP 查询成功，但当前聊天未配置截图 Artifact 服务；请使用本地 Demo 脚本查看截图。"
    return result


async def sap_close_browser(tool_context: ToolContext) -> dict:
    """关闭当前用户的 SAP 浏览器，释放资源；登录资料保留在该用户独立目录。"""
    return await _request("close", tool_context)


SAP_INSTRUCTION = """
【SAP Computer Use（只读）】
- 执行架构是云端小智调用 HTTPS 本机节点，由该电脑的专用 SAP 浏览器执行动作。
  接入/登录提示必须明确‘请切换到运行节点的电脑上的浏览器’，不要让用户在 TSE 网页寻找 SAP 登录弹窗。
- 用户检查连接、电脑在线或登录状态时调用 sap_connection_status，不依据历史消息声称连接成功。
- 用户已经要求‘去 SAP 查询/查订单’就是授权本次只读操作与打开专用浏览器，无需再问‘是否现在连接 SAP’。
  若先调用 status 发现 browser_open=false 或 logged_in=false，应直接调用 sap_prepare_browser，再提示人亲自登录。
  纯粹询问连接状态时仍只检查，不自动打开窗口；密码、验证码和 MFA 仍由人完成。
- SAP / 采购订单查询由你调用 sap_query_purchase_order；需要 10 位订单号，不确定时询问用户。
- 本 Demo 仅按明确订单号查询采购订单并返回截图；不支持无条件列出/分页全量订单，不能把订单列表请求当作已完成。
  无订单号时可以先打开 SAP 登录窗口，并简短提示补充订单号/发票，不输出长篇能力介绍，不默认查询示例订单。
- mode=computer-use 表示 Gemini 截图判断动作；mode=script 表示固定定位器脚本，不得把脚本模式描述为模型自主操作。
  两者都不直接调用 SAP 业务 API；不可创建、编辑、审批、收货或发票过账。
- 用户要求连接/登录 SAP 时调用 sap_prepare_browser；密码、MFA、验证码由用户在独立浏览器亲自完成。
- LOGIN_REQUIRED / CONFIRMATION_REQUIRED 或 wait_user=true：原样说明需要的人工操作，结束本轮，不自动重试。
- 成功后根据工具 data 中文回答，并标注订单号；缺失字段明确未读到，不得从历史消息或示例补齐。
- 本版只返回查询结果截图，没有结构化提取 SAP 明细字段，不承诺详情页、完整行项目或自动金额匹配。
- 黄金路径只返回订单号和结果截图，未返回 data 字段时只报告已查询和提供截图，不编造供应商或金额。
- 非 ok 结果如实说明失败；禁止声称查询已完成，也不要在 SAP 任务上走知识检索瀑布。
- 用户要求断开 SAP 时调用 sap_close_browser。
"""

SAP_DISABLED_INSTRUCTION = """
【SAP 配置诊断】
本项目已实现 SAP Computer Use 和发票/PDF前置识别，但当前实例 SAP_COMPUTER_USE_ENABLED 未启用。
用户要求连接/登录 SAP 时必须调用 sap_prepare_browser，按返回的 SAP_DISABLED 解释管理员需配置什么。
不要声称团队从未集成 SAP，不要把此问题误报为用户尚未登录，也不要让用户用 Excel 替代连接。
查询和发票识别工具在此实例尚未挂载，不能声称已查询或识别。仅修改 TSE 配置无法启用 Agent Engine 工具。
"""


def sap_instruction() -> str:
    if os.getenv('SAP_BROWSER_EXECUTION_MODE', 'local') != 'cloud':
        return SAP_INSTRUCTION
    return """
【SAP Computer Use 云端浏览器（只读）】
- 执行架构是小智调用云端 SAP 浏览器服务，每个 TSE 用户拥有独立会话。不依赖用户电脑、桌面或本机隧道。
- 用户检查连接时调用 sap_connection_status；用户要求连接/登录时调用 sap_prepare_browser。
- 用户要求查询采购订单时调用 sap_query_purchase_order；需要明确的 10 位订单号，不默认使用示例号。
- 未登录时工具准备独立的云端浏览器，并返回 TSE 的 SAP 云端登录页面链接。原样给出链接，请用户亲自登录。
  不提示切换到本机桌面、不提示启动本机服务；密码、验证码、MFA 不得写进聊天或模型工具参数。
- 查询授权包含本次只读连接与准备浏览器；不要额外询问是否连接。登录或人工确认需要时暂停，完成后再继续。
- 仅支持按订单号查单笔采购订单，或识别本轮发票/PDF后查询，不支持无条件全量订单列表。
- mode=computer-use 是模型根据截图决定动作；mode=script 是固定脚本，必须按实际报告。
- 成功以返回截图为准；无结构化 SAP 字段时不得编造供应商、金额匹配、详情或行项目。
- 不得创建、编辑、审批、收货或过账任何 SAP 单据。失败如实说明，不自动反复重试。
- 用户要求断开时调用 sap_close_browser，只关闭当前用户的会话。
"""
