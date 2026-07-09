# -*- coding: utf-8 -*-
"""
飞书长连接 Bridge — 群聊/私聊入口 → smart_agents（路径 A）

启动：
  ./scripts/run_feishu_smart_agents.sh

前置（另开终端）：
  python mcp_server/bilibili_mcp.py --http
  python mcp_server/etsy_mcp.py --http
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    PatchMessageRequest,
    PatchMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

# 保证项目根在 PYTHONPATH
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from integrations.feishu.agent_client import ProgressCallback, SmartAgentsClient
from integrations.feishu.config import FeishuBridgeConfig
from integrations.feishu.ssl_patch import apply_feishu_ssl_patch
from integrations.feishu.message_utils import (
    build_identity_prompt,
    build_session_id,
    build_user_id,
    detect_loyalty_attack,
    extract_mentions,
    get_sender_open_id,
    is_new_session_command,
    parse_incoming_text,
    should_handle_message,
    violates_loyalty_in_reply,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("feishu_bridge")

# 飞书要求 handler 3 秒内返回；Agent 异步执行
_ASYNC_LOOP = asyncio.new_event_loop()
_DEDUP_LOCK = threading.Lock()
# message_id → True，LRU 淘汰（禁止整表 clear，否则重推会重复处理）
_PROCESSED_MESSAGE_IDS: OrderedDict[str, bool] = OrderedDict()
_MAX_PROCESSED_CACHE = 5000
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


def _mark_message_seen(message_id: str) -> bool:
    """同步去重（在 on_message 入口调用）。返回 True 表示首次处理。"""
    if not message_id:
        return True
    with _DEDUP_LOCK:
        if message_id in _PROCESSED_MESSAGE_IDS:
            return False
        _PROCESSED_MESSAGE_IDS[message_id] = True
        while len(_PROCESSED_MESSAGE_IDS) > _MAX_PROCESSED_CACHE:
            _PROCESSED_MESSAGE_IDS.popitem(last=False)
        return True


def _session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _SESSION_LOCKS:
        _SESSION_LOCKS[session_id] = asyncio.Lock()
    return _SESSION_LOCKS[session_id]


def _start_async_loop() -> None:
    asyncio.set_event_loop(_ASYNC_LOOP)
    _ASYNC_LOOP.run_forever()


def _text_payload(text: str) -> str:
    return json.dumps({"text": text}, ensure_ascii=False)


def _chunk_text(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + limit])
        start += limit
    return chunks


class _ProgressUpdater:
    """节流更新飞书「处理中」消息，避免刷接口。"""

    def __init__(
        self,
        bridge: "FeishuBridge",
        message_id: str,
        *,
        min_interval_sec: float,
    ) -> None:
        self._bridge = bridge
        self._message_id = message_id
        self._min_interval_sec = min_interval_sec
        self._last_text = ""
        self._last_patch_at = 0.0
        self._pending: Optional[str] = None

    def __call__(self, text: str) -> None:
        if not self._message_id or not text or text == self._last_text:
            return
        now = time.monotonic()
        if (
            self._last_text
            and now - self._last_patch_at < self._min_interval_sec
        ):
            self._pending = text
            return
        self._flush(text, now)

    def flush_pending(self) -> None:
        if self._pending and self._pending != self._last_text:
            self._flush(self._pending, time.monotonic())

    def _flush(self, text: str, now: float) -> None:
        self._pending = None
        self._last_text = text
        self._last_patch_at = now
        self._bridge._patch_text(self._message_id, text)


class FeishuBridge:
    def __init__(self, cfg: FeishuBridgeConfig) -> None:
        self.cfg = cfg
        self.agent = SmartAgentsClient(cfg)
        self.api = (
            lark.Client.builder()
            .app_id(cfg.app_id)
            .app_secret(cfg.app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

    def _reply(self, message_id: str, text: str) -> Optional[str]:
        status_message_id: Optional[str] = None
        for chunk in _chunk_text(text):
            body = (
                ReplyMessageRequestBody.builder()
                .msg_type("text")
                .content(_text_payload(chunk))
                .build()
            )
            req = (
                ReplyMessageRequest.builder()
                .message_id(message_id)
                .request_body(body)
                .build()
            )
            resp = self.api.im.v1.message.reply(req)
            if not resp.success():
                logger.error("回复失败: code=%s msg=%s", resp.code, resp.msg)
                break
            if resp.data and resp.data.message_id:
                status_message_id = resp.data.message_id
        return status_message_id

    def _patch_text(self, message_id: str, text: str) -> None:
        body = (
            PatchMessageRequestBody.builder()
            .content(_text_payload(text))
            .build()
        )
        req = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        resp = self.api.im.v1.message.patch(req)
        if not resp.success():
            logger.debug("进度更新失败: code=%s msg=%s", resp.code, resp.msg)

    async def _handle_message_async(self, data: P2ImMessageReceiveV1) -> None:
        event = data.event
        if not event or not event.message:
            return
        msg = event.message
        message_id = msg.message_id or ""

        if not should_handle_message(
            data,
            bot_open_id=self.cfg.bot_open_id,
            group_require_mention=self.cfg.group_require_mention,
        ):
            logger.debug("忽略消息（群聊未@机器人）message_id=%s", message_id)
            return

        text = parse_incoming_text(data)
        if not text:
            self._reply(message_id, "暂仅支持文本消息，请用文字描述您的需求。")
            return

        sender_open_id = get_sender_open_id(data)
        sender_name = ""
        if event.sender and event.sender.sender_id:
            sender_name = (
                event.sender.sender_id.open_id
                or event.sender.sender_id.user_id
                or ""
            )
        mentions = extract_mentions(data)
        if self.cfg.strict_loyalty_mode:
            reject_reason = detect_loyalty_attack(
                text=text,
                sender_open_id=sender_open_id,
                owner_open_id=self.cfg.owner_open_id,
                owner_aliases=self.cfg.owner_aliases,
            )
            if reject_reason:
                logger.warning(
                    "拦截可疑越权指令 sender=%s chat=%s text=%r",
                    sender_open_id,
                    msg.chat_id,
                    text[:120],
                )
                self._reply(message_id, reject_reason)
                return

        user_id = build_user_id(data)
        session_id = build_session_id(data)

        if is_new_session_command(text):
            try:
                await self.agent.delete_session(user_id=user_id, session_id=session_id)
                self._reply(
                    message_id,
                    "已开启新对话：当前群/私聊的短期上下文已清空。"
                    "您的长期偏好仍由小智记住（云端 Memory Bank）。",
                )
            except Exception:
                logger.exception("删除 Session 失败")
                self._reply(message_id, "清空对话失败，请稍后重试。")
            return

        logger.info(
            "收到消息 user=%s session=%s chat=%s text=%r",
            user_id,
            session_id,
            msg.chat_id,
            text[:80],
        )

        lock = _session_lock(session_id)
        if lock.locked():
            logger.info("会话忙，跳过并发重复 session=%s", session_id)
            return

        async with lock:
            status_message_id: Optional[str] = None
            progress: Optional[ProgressCallback] = None

            if self.cfg.send_ack or self.cfg.send_progress:
                status_message_id = self._reply(message_id, self.cfg.ack_text)

            if self.cfg.send_progress and status_message_id:
                updater = _ProgressUpdater(
                    self,
                    status_message_id,
                    min_interval_sec=self.cfg.progress_min_interval_sec,
                )
                progress = updater

            try:
                reply = await self.agent.ask(
                    user_id=user_id,
                    session_id=session_id,
                    text=build_identity_prompt(
                        text=text,
                        sender_open_id=sender_open_id,
                        sender_name=sender_name,
                        chat_id=msg.chat_id or "",
                        mentions=mentions,
                    ),
                    on_progress=progress,
                )
            except Exception:
                logger.exception("Agent 调用失败")
                if status_message_id:
                    self._patch_text(
                        status_message_id,
                        "抱歉，处理时遇到错误，请稍后重试或检查 MCP 服务是否已启动。",
                    )
                else:
                    self._reply(
                        message_id,
                        "抱歉，处理时遇到错误，请稍后重试或检查 MCP 服务是否已启动。",
                    )
                return

            if isinstance(progress, _ProgressUpdater):
                progress.flush_pending()

            if (
                self.cfg.strict_loyalty_mode
                and sender_open_id != self.cfg.owner_open_id
                and violates_loyalty_in_reply(
                    reply=reply,
                    owner_aliases=self.cfg.owner_aliases,
                )
            ):
                logger.warning(
                    "拦截风险回复 sender=%s chat=%s reply=%r",
                    sender_open_id,
                    msg.chat_id,
                    reply[:120],
                )
                reply = "抱歉，我不会生成任何针对主人的攻击或贬损内容。"

            self._reply(message_id, reply)

    def on_message(self, data: P2ImMessageReceiveV1) -> None:
        """同步回调：立即返回，后台跑 Agent。"""
        message_id = ""
        if data.event and data.event.message:
            message_id = data.event.message.message_id or ""
        if not _mark_message_seen(message_id):
            logger.info("跳过重复飞书事件 message_id=%s", message_id)
            return

        fut = asyncio.run_coroutine_threadsafe(
            self._handle_message_async(data), _ASYNC_LOOP
        )

        def _log_result(f):
            exc = f.exception()
            if exc:
                logger.error("消息处理协程异常: %s", exc)

        fut.add_done_callback(_log_result)

    def run(self) -> None:
        handler = (
            lark.EventDispatcherHandler.builder(
                self.cfg.verification_token,
                self.cfg.encrypt_key,
            )
            .register_p2_im_message_receive_v1(self.on_message)
            .build()
        )
        ws = lark.ws.Client(
            self.cfg.app_id,
            self.cfg.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
        )
        logger.info("飞书长连接启动中… app_id=%s", self.cfg.app_id)
        logger.info(
            "模式=%s | 群聊@过滤=%s | 处理中反馈=%s | 进度更新=%s | MCP %s | Etsy MCP %s",
            self.cfg.run_mode,
            self.cfg.group_require_mention,
            self.cfg.send_ack,
            self.cfg.send_progress,
            self.cfg.mcp_server_url,
            self.cfg.etsy_mcp_server_url,
        )
        ws.start()


def main() -> None:
    cfg = FeishuBridgeConfig.from_env()
    apply_feishu_ssl_patch(verify=cfg.ssl_verify)
    t = threading.Thread(target=_start_async_loop, name="feishu-async-loop", daemon=True)
    t.start()

    bridge = FeishuBridge(cfg)
    try:
        bridge.run()
    except KeyboardInterrupt:
        logger.info("已停止")
    finally:
        fut = asyncio.run_coroutine_threadsafe(bridge.agent.close(), _ASYNC_LOOP)
        try:
            fut.result(timeout=10)
        except Exception:
            pass
        _ASYNC_LOOP.call_soon_threadsafe(_ASYNC_LOOP.stop)


if __name__ == "__main__":
    main()
