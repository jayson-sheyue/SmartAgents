# -*- coding: utf-8 -*-
"""
飞书 SDK SSL 补丁。

公司代理 / Clash MITM 会导致 websockets 连接飞书时报：
  CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain

本地开发可设 FEISHU_SSL_VERIFY=false（仅开发环境，勿用于生产）。
"""

from __future__ import annotations

import logging
import ssl
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PATCHED = False
_INSECURE_SSL_CTX: ssl.SSLContext | None = None


def _insecure_ssl_context() -> ssl.SSLContext:
    global _INSECURE_SSL_CTX
    if _INSECURE_SSL_CTX is None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _INSECURE_SSL_CTX = ctx
    return _INSECURE_SSL_CTX


def apply_feishu_ssl_patch(*, verify: bool) -> None:
    """在创建 lark.ws.Client 之前调用。"""
    global _PATCHED
    if verify or _PATCHED:
        return

    import requests
    import urllib3
    import websockets

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    _orig_ws_connect: Callable[..., Any] = websockets.connect

    def _ws_connect(uri: str, **kwargs: Any):
        kwargs.setdefault("ssl", _insecure_ssl_context())
        return _orig_ws_connect(uri, **kwargs)

    websockets.connect = _ws_connect  # type: ignore[assignment]

    _orig_post = requests.post

    def _post(*args: Any, **kwargs: Any):
        kwargs.setdefault("verify", False)
        return _orig_post(*args, **kwargs)

    requests.post = _post  # type: ignore[assignment]

    _PATCHED = True
    logger.warning(
        "FEISHU_SSL_VERIFY=false：已跳过飞书 HTTPS/WSS 证书校验（仅建议本地开发使用）"
    )
