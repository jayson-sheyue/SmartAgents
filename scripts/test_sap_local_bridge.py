"""Cloud-to-local boundary, pairing and private configuration tests (offline)."""
import asyncio
import os
import signal
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from dotenv import dotenv_values

from services.sap_computer_use.server import create_app
from domains.sap.browser import SapBrowserWorker, BrowserSession
from scripts import sap_local_bridge as bridge
from smart_agents.sap_tools import _request, sap_connection_status

USER = "tse:owner@example.com"
TOKEN = "t" * 32


def worker():
    return SimpleNamespace(status=AsyncMock(return_value={"ok": True, "browser_open": False}),
        prepare=AsyncMock(return_value={"ok": True, "wait_user": True, "message": "请在本机登录"}),
        query=AsyncMock(return_value={"ok": True}), close=AsyncMock(return_value={"ok": True}),
        shutdown=AsyncMock(), sessions={})


class ConfigurationTests(unittest.TestCase):
    def test_principal_matches_tse_identity(self):
        self.assertEqual(bridge.tse_user(" Owner@Example.com "), USER)
        for email in ("", "one", "a@x.com,b@x.com", "a@x.com\nsecret", "a @x.com"):
            with self.assertRaises(ValueError):
                bridge.tse_user(email)

    def test_env_update_preserves_other_settings_and_protects_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.env"
            path.write_text("# existing\nOTHER=keep\nexport SAP_COMPUTER_USE_TOKEN=old\nSAP_COMPUTER_USE_TOKEN=duplicate\n")
            bridge.update_env(path, {"SAP_COMPUTER_USE_TOKEN": TOKEN})
            values = dotenv_values(path)
            self.assertEqual(values["OTHER"], "keep")
            self.assertEqual(values["SAP_COMPUTER_USE_TOKEN"], TOKEN)
            self.assertEqual(path.read_text().count("SAP_COMPUTER_USE_TOKEN="), 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_or_symlink_config_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "env"
            path.write_text("OTHER=keep\n")
            with self.assertRaises(ValueError):
                bridge.update_env(path, {"TOKEN": "bad\nvalue"})
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                bridge.update_env(link, {"TOKEN": TOKEN})
            self.assertEqual(path.read_text(), "OTHER=keep\n")

    def test_cloud_export_and_optional_root_sync_have_distinct_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "private/cloud.env"
            (root / ".env").write_text("OTHER=keep\nSAP_COMPUTER_USE_ENABLED=false\n")
            with patch.object(bridge, "ROOT", root), patch.object(bridge, "CLOUD_ENV", path):
                bridge.publish_configuration("https://node.example.com", TOKEN, sync_root=False)
                self.assertEqual(dotenv_values(root / ".env")["SAP_COMPUTER_USE_ENABLED"], "false")
                bridge.publish_configuration("https://node.example.com", TOKEN, sync_root=True)
            exported = dotenv_values(root / ".env")
            self.assertEqual(exported["OTHER"], "keep")
            self.assertEqual(exported["SAP_COMPUTER_USE_WORKER_URL"], "https://node.example.com")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            # Do not create a partial agent config without its other deployment keys.
            self.assertFalse((root / "smart_agents/.env").exists())

    def test_cloud_sync_updates_existing_packaged_agent_without_changing_other_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent_env = root / "smart_agents/.env"
            agent_env.parent.mkdir()
            agent_env.write_text("OTHER=keep\nSAP_COMPUTER_USE_WORKER_URL=https://old.example.com\n")
            with patch.object(bridge, "ROOT", root), patch.object(bridge, "CLOUD_ENV", root / "private/cloud.env"):
                bridge.publish_configuration("https://new.example.com", TOKEN, sync_root=False)
                self.assertEqual(dotenv_values(agent_env)["SAP_COMPUTER_USE_WORKER_URL"], "https://old.example.com")
                bridge.publish_configuration("https://new.example.com", TOKEN, sync_root=True)
            values = dotenv_values(agent_env)
            self.assertEqual(values["OTHER"], "keep")
            self.assertEqual(values["SAP_COMPUTER_USE_WORKER_URL"], "https://new.example.com")
            self.assertEqual(values["SAP_COMPUTER_USE_TOKEN"], TOKEN)
            self.assertEqual(values["SAP_COMPUTER_USE_ENABLED"], "true")
            self.assertEqual(agent_env.stat().st_mode & 0o777, 0o600)


class WorkerBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_configures_bound_worker_and_stops_owned_processes(self):
        class Process:
            returncode = None
            def __init__(self, output=b""):
                self.output = output
                self.stdout = self
                self.exited = asyncio.Event()
                self.terminated = False
            async def readline(self):
                output, self.output = self.output, b""
                return output
            async def wait(self):
                await self.exited.wait()
                return 0
            def terminate(self):
                self.terminated = True
                self.returncode = 0
                self.exited.set()

        owned_worker = Process()
        owned_tunnel = Process(b"https://your-sap-bridge.example.com\n")
        callbacks = {}
        loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cloud_env = root / ".sap_bridge/cloud.env"
            with patch.object(bridge, "ROOT", root), patch.object(bridge, "BRIDGE_DIR", root / ".sap_bridge"), \
                 patch.object(bridge, "CLOUD_ENV", cloud_env), patch.object(bridge, "load_runtime_env", lambda: None), \
                 patch.dict(os.environ, {"SAP_COMPUTER_USE_TOKEN": TOKEN, "SAP_BROWSER_URL": "https://your-tenant.s4hana.cloud.sap/ui#Shell-home"}), \
                 patch.object(sys, "argv", ["bridge", "--tse-email", "owner@example.com", "--sync-cloud-env"]), \
                 patch.object(loop, "add_signal_handler", side_effect=lambda sig, fn: callbacks.update({sig: fn})), \
                 patch.object(bridge.shutil, "which", return_value="cloudflared"), \
                 patch.object(bridge.asyncio, "create_subprocess_exec", AsyncMock(side_effect=[owned_worker, owned_tunnel])) as spawn, \
                 patch.object(bridge, "probe", AsyncMock(side_effect=[httpx.ConnectError("offline"), {"ok": True}, {"ok": True}])):
                task = asyncio.create_task(bridge.main())
                for _ in range(50):
                    if cloud_env.exists():
                        break
                    await asyncio.sleep(.01)
                self.assertTrue(cloud_env.exists())
                callbacks[signal.SIGTERM]()
                await asyncio.wait_for(task, 2)
            local = dotenv_values(root / "env/local.env")
            self.assertEqual(local["SAP_WORKER_ALLOWED_USERS"], USER)
            self.assertTrue(local["SAP_BROWSER_URL"].endswith("#PurchaseOrder-manage"))
            self.assertEqual(dotenv_values(root / ".env")["SAP_COMPUTER_USE_WORKER_URL"], "https://your-sap-bridge.example.com")
            self.assertTrue(owned_worker.terminated and owned_tunnel.terminated)
            self.assertEqual(spawn.await_count, 2)
            self.assertNotIn(TOKEN, str(spawn.call_args_list))

    async def test_all_sensitive_endpoints_require_auth_and_bound_user(self):
        node = worker()
        app = create_app(node, TOKEN, allowed_users={USER})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://node") as client:
            for endpoint in ("status", "prepare", "query", "close", "snapshot"):
                body = {"user_id": USER, "purchase_order": "4500071250"}
                self.assertEqual((await client.post("/" + endpoint, json=body)).status_code, 401)
                other = {**body, "user_id": "tse:other@example.com"}
                self.assertEqual((await client.post("/" + endpoint, json=other,
                    headers={"Authorization": "Bearer " + TOKEN})).status_code, 403)
            response = await client.post("/prepare", json={"user_id": USER}, headers={"Authorization": "Bearer " + TOKEN})
        node.prepare.assert_awaited_once_with(USER)
        self.assertEqual(response.json()["execution_location"], "local_browser")
        self.assertEqual(response.json()["user_prompt"], "请在本机登录")
        node.query.assert_not_awaited()

    async def test_query_deadline_returns_failure_and_cancels_work(self):
        node = worker()
        cancelled = asyncio.Event()
        async def slow(*args):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        node.query.side_effect = slow
        app = create_app(node, TOKEN, allowed_users={USER}, query_timeout=.01)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://node") as client:
            response = await client.post("/query", json={"user_id": USER, "purchase_order": "4500071250"},
                headers={"Authorization": "Bearer " + TOKEN})
        self.assertEqual(response.json()["error"]["code"], "SAP_TIMEOUT")
        self.assertTrue(cancelled.is_set())

    async def test_client_auth_and_binding_failures_are_actionable(self):
        node = worker()
        app = create_app(node, TOKEN, allowed_users={USER})
        original = httpx.AsyncClient
        def client(**kwargs):
            return original(transport=httpx.ASGITransport(app=app), **kwargs)
        ctx = SimpleNamespace(user_id="one", state={"tse_user_email": "owner@example.com", "tse_auth_source": "tse_app"})
        with patch.dict(os.environ, {"SAP_COMPUTER_USE_ENABLED": "true", "SAP_COMPUTER_USE_WORKER_URL": "https://node.example.com",
                "SAP_COMPUTER_USE_TOKEN": "wrong" * 8}), patch("smart_agents.sap_tools.httpx.AsyncClient", side_effect=client):
            self.assertEqual((await sap_connection_status(ctx))["error"]["code"], "SAP_AUTH_FAILED")
        ctx.state["tse_user_email"] = "other@example.com"
        with patch.dict(os.environ, {"SAP_COMPUTER_USE_ENABLED": "true", "SAP_COMPUTER_USE_WORKER_URL": "https://node.example.com",
                "SAP_COMPUTER_USE_TOKEN": TOKEN}), patch("smart_agents.sap_tools.httpx.AsyncClient", side_effect=client):
            self.assertEqual((await _request("prepare", ctx))["error"]["code"], "SAP_USER_NOT_ALLOWED")
        node.prepare.assert_not_awaited()

    async def test_bridge_probe_requires_bound_node_without_opening_browser(self):
        node = worker()
        app = create_app(node, TOKEN, allowed_users={USER})
        original = httpx.AsyncClient
        def client(**kwargs):
            return original(transport=httpx.ASGITransport(app=app), **kwargs)
        with patch.object(bridge.httpx, "AsyncClient", side_effect=client):
            self.assertTrue((await bridge.probe("https://node.example.com", TOKEN, USER))["user_bound"])
            with self.assertRaises(ValueError):
                await bridge.probe("https://node.example.com", TOKEN, "tse:other@example.com")
        node.prepare.assert_not_awaited()

    async def test_unbound_worker_cannot_be_published(self):
        app = create_app(worker(), TOKEN)
        original = httpx.AsyncClient
        with patch.object(bridge.httpx, "AsyncClient", side_effect=lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs)):
            with self.assertRaises(ValueError):
                await bridge.probe("https://node.example.com", TOKEN, USER)

    async def test_offline_node_stops_for_user_without_silent_retry(self):
        with patch.dict(os.environ, {"SAP_COMPUTER_USE_ENABLED": "true", "SAP_COMPUTER_USE_WORKER_URL": "https://node.example.com",
                "SAP_COMPUTER_USE_TOKEN": TOKEN}), patch("smart_agents.sap_tools.httpx.AsyncClient") as client:
            client.return_value.__aenter__.return_value.post.side_effect = httpx.ConnectError("offline")
            result = await sap_connection_status(SimpleNamespace(user_id="one", state={}))
        self.assertEqual(result["error"]["code"], "SAP_UNAVAILABLE")
        self.assertTrue(result["wait_user"])
        self.assertIn("HTTPS 入口", result["error"]["message"])
        self.assertIn("临时域名", result["error"]["message"])

    async def test_worker_status_missing_idle_and_busy_are_non_mutating(self):
        node = SapBrowserWorker(url="https://your-tenant.s4hana.cloud.sap/ui", profile_dir=Path("/tmp/test-status"))
        self.assertFalse((await node.status(USER))["browser_open"])
        page = SimpleNamespace(is_closed=lambda: False)
        session = BrowserSession(SimpleNamespace(), page)
        node.sessions[USER] = session
        node._logged_in = AsyncMock(return_value=True)
        self.assertTrue((await node.status(USER))["logged_in"])
        await session.lock.acquire()
        self.assertIsNone((await node.status(USER))["logged_in"])
        node._logged_in.assert_awaited_once()
        session.lock.release()

    async def test_prepare_reuses_logged_in_browser_without_asking_login_again(self):
        node = SapBrowserWorker(url="https://your-tenant.s4hana.cloud.sap/ui", profile_dir=Path("/tmp/test-ready"))
        page = SimpleNamespace(is_closed=lambda: False)
        node.sessions[USER] = BrowserSession(SimpleNamespace(), page)
        node._logged_in = AsyncMock(return_value=True)
        result = await node.prepare(USER)
        self.assertEqual(result["status"], "browser_ready")
        self.assertFalse(result["wait_user"])
        self.assertIsNone(node._playwright)


if __name__ == "__main__":
    unittest.main()
