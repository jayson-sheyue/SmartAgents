"""Per-user, per-site human login for OrangeHRM. Never calls a model for login."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import secrets
import time
from urllib.parse import urlsplit

from domains.sap.browser import BrowserSession, failure
from domains.sap.cloud_browser import CloudSapBrowserWorker
from domains.sap.orangehrm_demo import (ROOT, LOGIN, EMPLOYEES, approved_request,
                                       restricted_state, run_employee_query)

LOGIN_PAGE = '/api/system/smart_agents/orangehrm/browser'
MANUAL = 'manual-v1'
PUBLIC = 'public-demo-v1'


class ScopedAuthStore:
    """Legacy automatic sessions never become manual sessions. Tombstones prevent ABA."""
    def __init__(self, store, mode=MANUAL):
        if mode not in {MANUAL, PUBLIC}:
            raise ValueError('Invalid login mode')
        self.store, self.mode = store, mode

    def key(self, user):
        return user + '|' + ROOT + '|' + self.mode

    def load(self, user):
        record, generation = self.store.load(self.key(user))
        if (not record or record.get('auth_mode') != self.mode or record.get('site') != ROOT
                or record.get('revoked') is True):
            return None, generation
        return restricted_state(record), generation

    def save(self, user, state, generation):
        return self.store.save(self.key(user), {**restricted_state(state),
            'auth_mode': self.mode, 'site': ROOT, 'revoked': False}, generation)

    def clear(self, user, generation):
        return self.store.save(self.key(user), {'cookies': [], 'origins': [],
            'auth_mode': self.mode, 'site': ROOT, 'revoked': True}, generation)


def login_required():
    return {'ok': True, 'logged_in': False, 'wait_user': True, 'status': 'login_required',
        'auth_mode': 'manual', 'login_url': LOGIN_PAGE,
        'message': '请在你的专属 OrangeHRM 云端浏览器中亲自登录，再回到对话继续查询。',
        'user_prompt': '请点击[打开 OrangeHRM 登录页面](' + LOGIN_PAGE + ')，亲自完成登录，'
            '然后回到对话发送“已登录，继续 OrangeHRM 查询”。密码或验证码请只输入登录页面。'}


class OrangeHRMSessions(CloudSapBrowserWorker):
    def __init__(self, *, state_store, max_sessions=4, idle_seconds=900):
        # Reuse human-input/snapshot primitives without SAP's tenant URL policy.
        if not 1 <= max_sessions <= 16 or not 60 <= idle_seconds <= 3600:
            raise ValueError('Invalid browser limits')
        self.url, self.login_start_url = EMPLOYEES, LOGIN
        self.store, self.login_origins = ScopedAuthStore(state_store), {ROOT}
        self.max_sessions, self.idle_seconds = max_sessions, idle_seconds
        self.sessions, self.generations, self.state_hashes = {}, {}, {}
        self.touched, self.revisions = {}, {}
        self._creation_lock = asyncio.Lock()
        self._browser = self._playwright = None

    async def _logged_in(self, page):
        if page.is_closed() or urlsplit(page.url).netloc != urlsplit(ROOT).netloc:
            return False
        if urlsplit(page.url).path not in {'/web/index.php/dashboard/index',
                '/web/index.php/pim/viewEmployeeList', '/web/index.php/pim/viewPimModule'}:
            return False
        return await page.locator('.oxd-userdropdown-name').is_visible()

    async def _ready(self, user):
        session = self.sessions[user]
        if await self._logged_in(session.page):
            await self._save_login(user, session)
            return {'ok': True, 'logged_in': True, 'wait_user': False, 'status': 'browser_ready',
                    'auth_mode': 'manual', 'message': '你的 OrangeHRM 已登录，请回到 TSE 对话继续查询。'}
        return login_required()

    async def prepare(self, user):
        async with self._creation_lock:
            existing = self.sessions.get(user)
            if existing and existing.lock.locked():
                return failure('ORANGEHRM_BUSY', '当前查询正在执行，请等待结果。', wait_user=True)
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
                    return failure('ORANGEHRM_CAPACITY', '会话已满，请关闭不用的 OrangeHRM 浏览器后重试。', wait_user=True)
                state, generation = await asyncio.to_thread(self.store.load, user)
                if self._browser is None:
                    from playwright.async_api import async_playwright
                    if self._playwright is None:
                        self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
                context = await self._browser.new_context(storage_state=state,
                    viewport={'width': 1440, 'height': 900}, accept_downloads=False, service_workers='block')
                async def guard(route):
                    r = route.request
                    # Logout is only invoked explicitly by the human logout endpoint.
                    logout = r.method == 'GET' and r.url == ROOT + '/web/index.php/auth/logout'
                    if approved_request(r.url, r.method, r.resource_type) or logout:
                        await route.continue_()
                    else:
                        await route.abort()
                await context.route('**/*', guard)
                try:
                    page = await context.new_page()
                    await page.goto(EMPLOYEES if state else LOGIN, wait_until='networkidle', timeout=35000)
                except BaseException:
                    await context.close()
                    raise
                self.sessions[user] = BrowserSession(context, page)
                self.generations[user] = generation
                self.revisions[user] = secrets.randbits(40)
            self._touch(user)
            async with self.sessions[user].lock:
                return await self._ready(user)

    async def status(self, user):
        session = self.sessions.get(user)
        if not session or session.page.is_closed():
            return {**login_required(), 'browser_open': False, 'busy': False}
        if session.lock.locked():
            return {'ok': True, 'busy': True, 'logged_in': None, 'message': 'OrangeHRM 正在执行查询。'}
        async with session.lock:
            self._touch(user)
            return {**await self._ready(user), 'browser_open': True, 'busy': False}

    async def login_snapshot(self, user):
        if user not in self.sessions or self.sessions[user].page.is_closed():
            return {**login_required(), 'ok': False, 'error': {'code': 'ORANGEHRM_RECONNECT',
                'message': '浏览器会话已关闭或服务已重启，请点击连接重新打开。'}}
        result = await super().login_snapshot(user)
        return self._orange_messages(result)

    async def login_action(self, user, action, revision):
        # Human input goes straight to Playwright; no model/client is available here.
        result = await super().login_action(user, action, revision)
        return self._orange_messages(result)

    @staticmethod
    def _orange_messages(result):
        error = result.get('error')
        if isinstance(error, dict):
            error['code'] = error.get('code', '').replace('SAP_', 'ORANGEHRM_')
            error['message'] = error.get('message', '').replace('SAP', 'OrangeHRM')
        return result

    async def query(self, user, *, client, model):
        ready = await self.prepare(user)
        if ready.get('logged_in') is not True:
            return ready  # No screenshot/credentials are sent to any model.
        session = self.sessions[user]
        if session.lock.locked():
            return failure('ORANGEHRM_BUSY', '当前会话正在操作，请稍后再试。', wait_user=True)
        async with session.lock:
            self._touch(user)
            if not await self._logged_in(session.page):
                return login_required()
            result = await run_employee_query(page=session.page, client=client, model=model)
            if result.get('ok') and not result.get('wait_user'):
                await self._save_login(user, session)
            return result

    async def close(self, user):
        async with self._creation_lock:
            session = self.sessions.get(user)
            if session and session.lock.locked():
                return failure('ORANGEHRM_BUSY', '查询尚未完成，请稍后关闭。', wait_user=True)
            if session and await self._logged_in(session.page):
                await self._save_login(user, session)
            await self._discard(user)
        return {'ok': True, 'status': 'browser_closed', 'message': '浏览器已关闭，有效的人工登录态已保留。'}

    async def logout(self, user):
        async with self._creation_lock:
            session = self.sessions.get(user)
            if session and session.lock.locked():
                return failure('ORANGEHRM_BUSY', '查询尚未完成，请稍后退出。', wait_user=True)
            # Write a tombstone before closing: a stale generation cannot restore old cookies.
            _, generation = await asyncio.to_thread(self.store.load, user)
            await asyncio.to_thread(self.store.clear, user, generation)
            if session:
                with suppress(Exception):
                    await session.page.goto(ROOT + '/web/index.php/auth/logout',
                                            wait_until='domcontentloaded', timeout=12000)
            await self._discard(user)
        return {'ok': True, 'logged_in': False, 'status': 'logged_out', 'auth_mode': 'manual',
                'message': '已关闭浏览器并清除此 OrangeHRM 连接的登录态；再次连接需亲自登录。'}
