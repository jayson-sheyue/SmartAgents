"""Headless cloud SAP sessions and human-only login interaction.

Login inputs go directly to the browser, never to Gemini or an Agent session.
The existing read-only query implementation remains unchanged.
"""
import asyncio
import base64
from contextlib import suppress
import hashlib
import json
import time
from urllib.parse import urlsplit

from domains.sap.browser import BrowserSession, SapBrowserWorker, failure

LOGIN_PATH = '/api/system/smart_agents/sap/browser'


def origin(url):
    parsed = urlsplit(url)
    return parsed.scheme + '://' + parsed.netloc


class CloudSapBrowserWorker(SapBrowserWorker):
    execution_location = 'cloud_browser'

    def __init__(self, *, state_store, login_origins=(), login_start_url=None, max_sessions=4, idle_seconds=900, **kwargs):
        super().__init__(**kwargs)
        self.store = state_store
        self.login_origins = {origin(self.url)}
        for value in login_origins:
            p = urlsplit(value)
            if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
                raise ValueError('Login origins must be HTTPS origins')
            if p.path not in ('', '/') or p.query or p.fragment:
                raise ValueError('Configure exact login origins, not URLs')
            self.login_origins.add(origin(value))
        self.login_start_url = login_start_url or self.url
        start = urlsplit(self.login_start_url)
        if start.scheme != 'https' or start.username or start.password or origin(self.login_start_url) not in self.login_origins:
            raise ValueError('Login start URL must use an approved HTTPS origin')
        if not 1 <= max_sessions <= 16 or not 60 <= idle_seconds <= 3600:
            raise ValueError('Invalid cloud browser limits')
        self.max_sessions, self.idle_seconds = max_sessions, idle_seconds
        self.generations, self.state_hashes, self.touched, self.revisions = {}, {}, {}, {}
        self._browser = None

    def _touch(self, user):
        self.touched[user] = time.monotonic()

    async def _discard(self, user):
        session = self.sessions.pop(user, None)
        if session:
            with suppress(Exception):
                await session.context.close()
        for entries in (self.generations, self.state_hashes, self.touched, self.revisions):
            entries.pop(user, None)

    async def prepare(self, user):
        async with self._creation_lock:
            existing = self.sessions.get(user)
            if existing and existing.lock.locked():
                return failure('SAP_BUSY', '当前云端会话正在操作，请稍后再试。', wait_user=True)
            if self._browser and not self._browser.is_connected():
                for owner in list(self.sessions):
                    await self._discard(owner)
                self._browser = None
            if existing and existing.page.is_closed():
                await self._discard(user)
            now = time.monotonic()
            for owner, session in list(self.sessions.items()):
                if owner != user and not session.lock.locked() and now-self.touched.get(owner, now) > self.idle_seconds:
                    await self._discard(owner)
            if user not in self.sessions:
                if len(self.sessions) >= self.max_sessions:
                    return failure('SAP_CAPACITY', '云端浏览器会话已满，请关闭不用的 SAP 会话或稍后再试。', wait_user=True)
                state, generation = await asyncio.to_thread(self.store.load, user)
                if self._browser is None:
                    from playwright.async_api import async_playwright
                    if self._playwright is None:
                        self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch(headless=True,
                        args=['--disable-dev-shm-usage'])
                context = await self._browser.new_context(storage_state=state,
                    viewport={'width': 1440, 'height': 900}, accept_downloads=False, service_workers='block')
                try:
                    page = await context.new_page()
                    await page.goto(self.url if state else self.login_start_url, wait_until='domcontentloaded', timeout=30000)
                    if state and self.login_start_url != self.url and not await self._logged_in(page):
                        await page.goto(self.login_start_url, wait_until='domcontentloaded', timeout=30000)
                except BaseException:
                    await context.close()
                    raise
                self.sessions[user] = BrowserSession(context, page)
                self.generations[user] = generation
                self.revisions[user] = 0
            self._touch(user)
            async with self.sessions[user].lock:
                return await self._ready(user)

    async def _ready(self, user):
        session = self.sessions[user]
        # SAP/SSO portals may open the business app in a new tab. Follow that tab
        # inside this user's context; origin authorization still precedes manual input.
        pages = [p for p in session.context.pages if not p.is_closed()]
        if pages and pages[-1] is not session.page:
            latest = pages[-1]
            with suppress(Exception):
                await latest.wait_for_url(lambda url: str(url) != 'about:blank', timeout=3000)
                await latest.wait_for_load_state('domcontentloaded', timeout=3000)
            session.page = latest
        if await self._logged_in(session.page):
            await self._save_login(user, session)
            return {'ok': True, 'status': 'browser_ready', 'logged_in': True, 'wait_user': False,
                    'message': '你的云端 SAP 浏览器已登录，可以查询采购订单。'}
        return {'ok': True, 'status': 'browser_open', 'logged_in': False, 'wait_user': True,
                'browser_login_required': True,
                'user_prompt': '已准备你的独立云端 SAP 浏览器。请点击[打开 SAP 云端登录页面]('
                    + LOGIN_PATH + ')，亲自完成登录和验证，再回到对话继续查询。无需启动本机服务或隧道。',
                'message': '请在 TSE 的 SAP 云端浏览器页面亲自登录。'}

    async def _save_login(self, user, session):
        state = await session.context.storage_state()
        digest = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
        if digest != self.state_hashes.get(user):
            from google.api_core.exceptions import PreconditionFailed
            try:
                generation = await asyncio.to_thread(self.store.save, user, state, self.generations[user])
            except PreconditionFailed:
                await self._discard(user)
                raise ValueError('Cloud session changed; reconnect to restore current state') from None
            self.generations[user] = generation
            self.state_hashes[user] = digest

    async def status(self, user):
        session = self.sessions.get(user)
        if not session or session.page.is_closed():
            return {'ok': True, 'browser_open': False, 'logged_in': False, 'busy': False,
                    'message': '云端 SAP 服务已连接；请发送“连接 SAP”准备你的独立浏览器。'}
        self._touch(user)
        if session.lock.locked():
            return {'ok': True, 'browser_open': True, 'logged_in': None, 'busy': True,
                    'message': '云端 SAP 浏览器正在操作，请等待结果。'}
        async with session.lock:
            ready = await self._ready(user)
            return {**ready, 'browser_open': True, 'busy': False}

    async def login_snapshot(self, user):
        session = self.sessions.get(user)
        if not session or session.page.is_closed():
            return failure('LOGIN_REQUIRED', '云端浏览器会话已关闭或服务已重启，请点击连接重新打开。', wait_user=True)
        if session.lock.locked():
            return failure('SAP_BUSY', '当前云端会话正在操作，请稍后刷新。', wait_user=True)
        async with session.lock:
            self._touch(user)
            ready = await self._ready(user)
            if ready.get('logged_in'):
                return ready  # No interactive screenshot or manual controls after login.
            current = origin(session.page.url)
            if current not in self.login_origins:
                return {**failure('LOGIN_ORIGIN_BLOCKED', '请管理员将此登录站点加入 SAP_LOGIN_ALLOWED_ORIGINS 后再连接。', wait_user=True),
                        'current_origin': current}
            image = await session.page.screenshot(animations='disabled', timeout=15000)
            self.revisions[user] += 1
            return {**ready, 'current_origin': current, 'revision': self.revisions[user],
                    'mime': 'image/png', 'image_base64': base64.b64encode(image).decode()}

    async def login_action(self, user, action, revision):
        session = self.sessions.get(user)
        if not session or session.page.is_closed():
            return failure('LOGIN_REQUIRED', '请先连接云端 SAP 浏览器。', wait_user=True)
        if session.lock.locked():
            return failure('SAP_BUSY', '当前云端会话正在操作，请稍后再试。', wait_user=True)
        async with session.lock:
            self._touch(user)
            if await self._logged_in(session.page):
                return await self._ready(user)
            if origin(session.page.url) not in self.login_origins:
                return failure('LOGIN_ORIGIN_BLOCKED', '当前登录站点尚未获准人工操作。', wait_user=True)
            if type(revision) is not int or revision != self.revisions[user]:
                return failure('STALE_SCREENSHOT', '画面已更新，请刷新后再操作；本次输入未执行。', wait_user=True)
            if not isinstance(action, dict):
                return failure('INVALID_LOGIN_ACTION', '无效登录操作。')
            kind = action.get('kind')
            if kind == 'click':
                x, y = action.get('x'), action.get('y')
                if type(x) not in (int, float) or type(y) not in (int, float) or not (0 <= x < 1440 and 0 <= y < 900):
                    return failure('INVALID_LOGIN_ACTION', '无效坐标。')
                await session.page.mouse.click(x, y)
            elif kind == 'text':
                text = action.get('text')
                if not isinstance(text, str) or not 1 <= len(text) <= 2048:
                    return failure('INVALID_LOGIN_ACTION', '输入内容长度无效。')
                if not await session.page.evaluate("document.activeElement?.matches('input:not([type=file]):not([disabled]):not([readonly]),textarea') || false"):
                    return failure('INVALID_LOGIN_ACTION', '请先在画面中点击登录输入框。')
                await session.page.keyboard.type(text)
            elif kind == 'key':
                key = action.get('key')
                if key not in {'Tab', 'Shift+Tab', 'Enter', 'Backspace', 'Escape', 'Control+A'}:
                    return failure('INVALID_LOGIN_ACTION', '不支持该按键。')
                await session.page.keyboard.press(key)
            elif kind == 'scroll':
                amount = action.get('y')
                if type(amount) not in (int, float) or not -900 <= amount <= 900:
                    return failure('INVALID_LOGIN_ACTION', '无效滚动距离。')
                await session.page.mouse.wheel(0, amount)
            else:
                return failure('INVALID_LOGIN_ACTION', '不支持该登录操作。')
            self.revisions[user] += 1
            await session.page.wait_for_timeout(300)
            return await self._ready(user)

    async def query(self, user, order):
        self._touch(user)
        result = await super().query(user, order)
        if isinstance(result.get('error'), dict):
            result['error']['message'] = result['error']['message'].replace('本机专用', '云端独立').replace('独立浏览器登录', 'TSE 云端浏览器页面登录')
        return result

    async def close(self, user):
        async with self._creation_lock:
            session = self.sessions.get(user)
            if session and session.lock.locked():
                return failure('SAP_BUSY', '当前查询尚未结束，请稍后关闭。', wait_user=True)
            if session and not session.page.is_closed() and await self._logged_in(session.page):
                await self._save_login(user, session)
            await self._discard(user)
        return {'ok': True, 'status': 'browser_closed', 'message': '你的云端浏览器已关闭，有效登录资料已保留。'}

    async def shutdown(self):
        for user in list(self.sessions):
            with suppress(Exception):
                await self.close(user)
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
