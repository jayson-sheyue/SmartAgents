"""Trusted recovery guidance for the local SAP PoC; mirrored in TSE.

Commands are fixed installation guidance, never taken from tool messages or invoices.
"""
from __future__ import annotations
import os

SAP_RECOVERY_TOOLS = frozenset({
    "sap_prepare_browser", "sap_connection_status", "sap_query_purchase_order",
    "sap_close_browser", "sap_query_from_invoice", "sap_query_recognized_invoice",
})
_LOCAL_CHECK = """请在**运行 SAP 节点的电脑**上打开终端执行（本演示机路径如下，其他电脑请换成实际安装目录）：

```bash
cd /path/to/SmartAgents
.venvAgents/bin/python -m scripts.sap_bridge_service start
.venvAgents/bin/python -m scripts.sap_bridge_service status
```

`start` 会复用已运行的后台节点；首次启动或提示缺少账号绑定时，请由节点管理员使用 `start --tse-email 你的TSE登录邮箱` 配置。保持电脑、网络和 HTTPS 隧道在线。
"""
_DEPLOY = """**仅管理员在 HTTPS 地址、令牌或云端 SAP 配置变化后执行：**确认本机服务检查通过、根 `.env` 已同步新配置，再在同一目录运行：

```bash
bash scripts/deploy_smart_agents.sh
```

地址和配置未变时无需重新部署。部署不会启动本机服务；本机入口变化也不需要重新部署 TSE。
"""


def sap_recovery_text(result: dict) -> str | None:
    """Select instructions by known error code; do not forward arbitrary commands."""
    if not isinstance(result, dict):
        return None
    sap = result.get("sap") if isinstance(result.get("sap"), dict) else result
    if sap.get("ok") is not False:
        return None
    error = sap.get("error") if isinstance(sap.get("error"), dict) else {}
    code = error.get("code")
    if not isinstance(code, str):
        return None
    if sap.get('execution_location') == 'cloud_browser' or os.getenv('SAP_BROWSER_EXECUTION_MODE', 'local') == 'cloud':
        if code == 'LOGIN_REQUIRED':
            body = '请点击[打开 SAP 云端登录页面](/api/system/smart_agents/sap/browser)，亲自完成登录和验证，再回到此对话继续查询。'
        elif code in {'SAP_BUSY', 'SAP_CAPACITY'}:
            body = '云端 SAP 浏览器正在操作或会话已满。请稍后重试，或发送“断开 SAP”关闭自己不用的会话。'
        elif code in {'SAP_UNAVAILABLE', 'SAP_WORKER_ERROR', 'SAP_TIMEOUT', 'BROWSER_START_FAILED',
                      'SAP_DISABLED', 'SAP_WORKER_NOT_CONFIGURED', 'SAP_AUTH_FAILED', 'SAP_USER_NOT_ALLOWED',
                      'SAP_STATE_UNAVAILABLE', 'SAP_QUERY_FAILED', 'SAP_DEMO_FAILED', 'LOGIN_ORIGIN_BLOCKED'}:
            body = '请联系管理员检查云端 SAP 浏览器服务、IAM 调用权限、服务令牌、会话存储或登录站点配置。不要在聊天中发送密码、令牌或登录资料。'
        else:
            return None
        return '**SAP Computer Use 恢复指引**\n\n' + body + '\n\n本次使用云端浏览器，无需在电脑上启动 worker 或 HTTPS 隧道。'
    if code in {"SAP_UNAVAILABLE", "SAP_WORKER_ERROR"}:
        body = (_LOCAL_CHECK + "\n若 `status` 仍失败，请把报错交给节点管理员检查 HTTPS 隧道；"
                "反复部署无法修复离线入口。\n\n" + _DEPLOY)
    elif code == "SAP_TIMEOUT":
        body = (_LOCAL_CHECK + "\n如果节点在线，请查看专用 SAP 浏览器是否卡在加载或登录页，再尝试查询。"
                "单次查询超时无需重新部署。")
    elif code == "BROWSER_START_FAILED":
        body = (_LOCAL_CHECK + "\n节点在线但窗口打不开时，请由节点管理员检查本机服务日志和图形界面；"
                "如果日志确认缺少 Chromium，在同一目录执行：\n\n"
                "```bash\n.venvAgents/bin/python -m playwright install chromium\n```\n\n"
                "浏览器启动失败无需重新部署。")
    elif code == "LOGIN_REQUIRED":
        body = ("请在 TSE 发送「连接 SAP」，然后切换到运行节点电脑上的专用浏览器，亲自完成 SAP 登录和验证。"
                "登录失效无需重启节点或重新部署。")
    elif code in {"SAP_DISABLED", "SAP_WORKER_NOT_CONFIGURED", "SAP_AUTH_FAILED"}:
        body = ("请联系节点管理员检查 SmartAgents 云端是否启用 SAP、HTTPS 地址及认证令牌是否与本机一致。"
                "不要把令牌、密码或 `.env` 内容发到聊天里。\n\n" + _LOCAL_CHECK + "\n" + _DEPLOY)
    elif code == "SAP_USER_NOT_ALLOWED":
        body = ("请联系节点管理员核对当前 TSE 登录邮箱与本机允许的账号绑定。"
                "已有后台节点时，单独执行 `start` 不会更改绑定；需按节点配置流程调整后再检查连接。"
                "账号绑定问题无需盲目重新部署。")
    else:
        return None
    return ("**SAP Computer Use 恢复指引**\n\n" + body +
            "\n\n处理完成后，回到 TSE 发送「检查 SAP 连接状态」；连接正常后再发送原查询，"
            "需要登录时请在专用浏览器亲自登录。")
