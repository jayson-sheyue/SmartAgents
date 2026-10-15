"""Query intent bootstraps the browser; credentials remain a human step."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from smart_agents.sap_tools import sap_query_purchase_order

ORDER = "4500071250"
LOGIN = {"ok": False, "wait_user": True, "error": {"code": "LOGIN_REQUIRED", "message": "请登录"}}


class LoginFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_opens_login_window_and_pauses_without_claiming_success(self):
        prepared = {"ok": True, "wait_user": True, "logged_in": False, "message": "已在本机打开 SAP，请亲自登录"}
        with patch("smart_agents.sap_tools._request", AsyncMock(side_effect=[LOGIN, prepared])) as request:
            result = await sap_query_purchase_order(ORDER, SimpleNamespace())
        self.assertEqual([call.args[0] for call in request.await_args_list], ["query", "prepare"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["wait_user"])
        self.assertTrue(result["browser_opened"])
        self.assertEqual(result["purchase_order"], ORDER)
        self.assertEqual(result["user_prompt"], prepared["message"])
        self.assertNotIn("artifacts", result)

    async def test_restored_login_runs_original_read_once(self):
        with patch("smart_agents.sap_tools._request", AsyncMock(side_effect=[LOGIN,
                {"ok": True, "wait_user": False, "logged_in": True}, {"ok": True, "purchase_order": ORDER}])) as request:
            result = await sap_query_purchase_order(ORDER, SimpleNamespace())
        self.assertTrue(result["ok"])
        self.assertEqual([call.args[0] for call in request.await_args_list], ["query", "prepare", "query"])
        self.assertEqual(request.await_args_list[-1].args[2], ORDER)

    async def test_repeated_login_failure_does_not_loop(self):
        with patch("smart_agents.sap_tools._request", AsyncMock(side_effect=[LOGIN,
                {"ok": True, "wait_user": False, "logged_in": True}, LOGIN])) as request:
            result = await sap_query_purchase_order(ORDER, SimpleNamespace())
        self.assertFalse(result["ok"])
        self.assertEqual(request.await_count, 3)

    async def test_prepare_error_is_preserved(self):
        failure = {"ok": False, "wait_user": True, "error": {"code": "SAP_USER_NOT_ALLOWED"}}
        with patch("smart_agents.sap_tools._request", AsyncMock(side_effect=[LOGIN, failure])):
            result = await sap_query_purchase_order(ORDER, SimpleNamespace())
        self.assertEqual(result["error"]["code"], "SAP_USER_NOT_ALLOWED")
        self.assertEqual(result["purchase_order"], ORDER)

    async def test_network_failures_are_not_retried(self):
        with patch("smart_agents.sap_tools._request", AsyncMock(return_value={
                "ok": False, "error": {"code": "SAP_UNAVAILABLE"}})) as request:
            result = await sap_query_purchase_order(ORDER, SimpleNamespace())
        self.assertFalse(result["ok"])
        request.assert_awaited_once()

    async def test_missing_order_is_not_guessed_and_does_not_open_browser(self):
        with patch("smart_agents.sap_tools._request", AsyncMock()) as request:
            result = await sap_query_purchase_order("", SimpleNamespace())
        self.assertEqual(result["error"]["code"], "INVALID_ORDER")
        request.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
