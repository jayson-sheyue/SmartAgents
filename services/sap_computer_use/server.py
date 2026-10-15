"""Run with python -m services.sap_computer_use.server (loopback only by default)."""
from contextlib import asynccontextmanager
import asyncio
import hmac
import logging
import os
import re
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from domains.sap.browser import SapBrowserWorker, failure

logger = logging.getLogger(__name__)


class Request(BaseModel):
    user_id: str = Field(min_length=1, max_length=320)
    purchase_order: str = ""
    action: dict | None = None
    revision: int | None = None


def create_app(worker: SapBrowserWorker, token: str, *, allowed_users: set[str] | None = None,
               query_timeout: float = 90) -> FastAPI:
    if len(token) < 32:
        raise ValueError("SAP_COMPUTER_USE_TOKEN 必须至少 32 字符")
    cloud = getattr(worker, 'execution_location', '') == 'cloud_browser'

    @asynccontextmanager
    async def lifespan(app):
        yield
        await worker.shutdown()

    app = FastAPI(title="SAP Computer Use Worker", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    async def authenticate(authorization: str = Header(default="")):
        if not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            raise HTTPException(401, "Unauthorized")

    async def authorize_user(request: Request):
        if cloud and not re.fullmatch(r'tse:[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}', request.user_id):
            raise HTTPException(403, 'A trusted TSE identity is required')
        if allowed_users is not None and request.user_id not in allowed_users:
            raise HTTPException(403, "User not bound to this local worker")

    def local_result(result: dict) -> dict:
        if cloud:
            return {**result, 'execution_location': 'cloud_browser', 'connection_mode': 'cloud_to_cloud'}
        return {**result, "execution_location": "local_browser", "connection_mode": "cloud_to_local"}

    @app.middleware('http')
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "sap_computer_use", "bridge_protocol": 1}

    @app.post("/status", dependencies=[Depends(authenticate), Depends(authorize_user)])
    async def status(request: Request):
        try:
            return {**local_result(await worker.status(request.user_id)), "user_bound": cloud or allowed_users is not None}
        except Exception as exc:
            logger.error('SAP status failed type=%s', type(exc).__name__)
            return local_result(failure('SAP_STATE_UNAVAILABLE', 'SAP 会话状态暂不可用，请重新连接或联系管理员。', wait_user=True))

    @app.post("/prepare", dependencies=[Depends(authenticate), Depends(authorize_user)])
    async def prepare(request: Request):
        try:
            prepared = await asyncio.wait_for(worker.prepare(request.user_id), 75) if cloud else await worker.prepare(request.user_id)
            result = local_result(prepared)
            if result.get("wait_user"):
                result["user_prompt"] = result.get("message") or result.get("error", {}).get("message", "")
            return result
        except Exception as exc:
            # Do not log exception text, which may contain cookies or private URLs.
            logger.error("SAP browser prepare failed type=%s", type(exc).__name__)
            return local_result(failure("BROWSER_START_FAILED", ('云端' if cloud else '本机') +
                " SAP 专用浏览器未能打开。请管理员检查执行服务日志、浏览器依赖与登录资料存储。", wait_user=True))

    @app.post("/query", dependencies=[Depends(authenticate), Depends(authorize_user)])
    async def query(request: Request):
        try:
            result = await asyncio.wait_for(worker.query(request.user_id, request.purchase_order), query_timeout)
        except asyncio.TimeoutError:
            result = failure("SAP_TIMEOUT", ('云端' if cloud else '本机') + " SAP 查询达到时间上限，未确认完成；请检查浏览器后重试。", wait_user=True)
        except Exception as exc:
            logger.error('SAP query failed type=%s', type(exc).__name__)
            result = failure('SAP_QUERY_FAILED', 'SAP 查询未完成，请管理员检查执行服务日志。', wait_user=True)
        return local_result(result)

    @app.post("/close", dependencies=[Depends(authenticate), Depends(authorize_user)])
    async def close(request: Request):
        try:
            return local_result(await worker.close(request.user_id))
        except Exception as exc:
            logger.error('SAP close failed type=%s', type(exc).__name__)
            return local_result(failure('SAP_STATE_UNAVAILABLE', '会话关闭或保存未确认完成，请刷新状态。', wait_user=True))

    @app.post("/snapshot", dependencies=[Depends(authenticate), Depends(authorize_user)])
    async def snapshot(request: Request):
        if cloud:
            raise HTTPException(403, 'Use the human-only login snapshot endpoint')
        session = worker.sessions.get(request.user_id)
        if not session or session.page.is_closed():
            raise HTTPException(404, "Browser not open")
        return Response(await session.page.screenshot(animations="disabled"), media_type="image/png")

    if cloud:
        demo_lock = asyncio.Lock()

        @app.post('/demo/form-controls', dependencies=[Depends(authenticate), Depends(authorize_user)])
        async def form_controls_demo(request: Request):
            if demo_lock.locked():
                return local_result(failure('WEB_DEMO_BUSY', '当前已有网页演示在运行，请稍后再试。'))
            from domains.sap.form_demo import run_form_demo
            async with demo_lock:
                try:
                    return local_result(await asyncio.wait_for(run_form_demo(
                        client=worker.client, model=worker.model), 180))
                except Exception as exc:
                    logger.error('Form demo failed type=%s', type(exc).__name__)
                    return local_result(failure('FORM_DEMO_FAILED', '表单演示未完成或已超时，请稍后再试。'))

        @app.post('/demo/demoblaze', dependencies=[Depends(authenticate), Depends(authorize_user)])
        async def demoblaze_demo(request: Request):
            if demo_lock.locked():
                return local_result(failure('WEB_DEMO_BUSY', '当前已有网页演示在运行，请稍后再试。'))
            from domains.sap.web_demo import run_demoblaze_demo
            async with demo_lock:
                try:
                    return local_result(await asyncio.wait_for(run_demoblaze_demo(
                        client=worker.client, model=worker.model), 180))
                except Exception as exc:
                    logger.error('Web demo failed type=%s', type(exc).__name__)
                    return local_result(failure('WEB_DEMO_FAILED', '公开网页演示未完成或已超时，请稍后再试。'))

        @app.post('/login/snapshot', dependencies=[Depends(authenticate), Depends(authorize_user)])
        async def login_snapshot(request: Request):
            try:
                return local_result(await worker.login_snapshot(request.user_id))
            except Exception as exc:
                logger.error('SAP login snapshot failed type=%s', type(exc).__name__)
                return local_result(failure('SAP_STATE_UNAVAILABLE', '云端登录画面或会话存储暂不可用，请刷新或联系管理员。', wait_user=True))

        @app.post('/login/action', dependencies=[Depends(authenticate), Depends(authorize_user)])
        async def login_action(request: Request):
            try:
                return local_result(await worker.login_action(request.user_id, request.action, request.revision))
            except Exception as exc:
                # Never log manual login values, screenshot contents or exception text.
                logger.error('SAP human login action failed type=%s', type(exc).__name__)
                return local_result(failure('SAP_STATE_UNAVAILABLE', '云端登录操作未确认完成，请刷新画面；本次不会自动重试输入。', wait_user=True))

    return app


def main():
    import uvicorn
    cloud = os.getenv('SAP_BROWSER_EXECUTION_MODE', 'local') == 'cloud'
    if not cloud:
        from smart_agents.env_runtime import load_runtime_env
        load_runtime_env()
    common = dict(
        url=os.environ["SAP_BROWSER_URL"],
        profile_dir=Path(os.getenv("SAP_BROWSER_PROFILE_DIR", ".sap_browser_profiles")).resolve(),
        model=os.getenv("SAP_COMPUTER_USE_MODEL", "gemini-3.8-flash"),
    )
    if cloud:
        from google import genai
        from google.cloud import storage
        from domains.sap.cloud_browser import CloudSapBrowserWorker
        from domains.sap.cloud_state import CloudStateStore
        project = os.environ['GCP_PROJECT_ID']
        common['client'] = genai.Client(vertexai=True, project=project,
            location=os.getenv('SAP_COMPUTER_USE_LOCATION', 'global'))
        store = CloudStateStore(storage.Client(project=project).bucket(os.environ['SAP_AUTH_STATE_BUCKET']),
                                os.environ['SAP_AUTH_STATE_KEY'])
        worker = CloudSapBrowserWorker(**common, state_store=store,
            login_origins=[v.strip() for v in os.getenv('SAP_LOGIN_ALLOWED_ORIGINS', '').split(',') if v.strip()],
            login_start_url=os.getenv('SAP_LOGIN_START_URL') or None,
            max_sessions=int(os.getenv('SAP_CLOUD_MAX_SESSIONS', '4')),
            idle_seconds=int(os.getenv('SAP_CLOUD_IDLE_SECONDS', '900')))
    else:
        worker = SapBrowserWorker(**common)
    allowed = {item.strip() for item in os.getenv("SAP_WORKER_ALLOWED_USERS", "").split(",") if item.strip()}
    app = create_app(worker, os.environ["SAP_COMPUTER_USE_TOKEN"], allowed_users=allowed or None)
    uvicorn.run(app, host="0.0.0.0" if cloud else "127.0.0.1", port=int(os.getenv("PORT" if cloud else "SAP_COMPUTER_USE_PORT", "8010")),
                access_log=False, workers=1)


if __name__ == "__main__":
    main()
