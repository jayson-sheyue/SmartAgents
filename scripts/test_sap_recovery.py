"""Local recovery contracts; no live browser, network, or deployment."""
import unittest

from smart_agents.sap_recovery import sap_recovery_text
from smart_agents.sap_response import format_sap_result


class SapRecoveryTests(unittest.TestCase):
    def failure(self, code):
        return {'ok': False, 'error': {'code': code, 'message': 'HTTP 530'}}

    def test_offline_has_local_commands_and_conditional_admin_deployment(self):
        for code in ('SAP_UNAVAILABLE', 'SAP_WORKER_ERROR'):
            text = sap_recovery_text(self.failure(code))
            self.assertIn('cd /path/to/SmartAgents', text)
            self.assertIn('scripts.sap_bridge_service start\n', text)
            self.assertIn('scripts.sap_bridge_service status\n', text)
            self.assertIn('bash scripts/deploy_smart_agents.sh', text)
            self.assertIn('仅管理员', text)
            self.assertIn('地址和配置未变时无需重新部署', text)
            self.assertIn('检查 SAP 连接状态', text)

    def test_timeout_browser_login_and_binding_have_distinct_remedies(self):
        for code in ('SAP_TIMEOUT', 'BROWSER_START_FAILED', 'LOGIN_REQUIRED', 'SAP_USER_NOT_ALLOWED'):
            text = sap_recovery_text(self.failure(code))
            self.assertNotIn('bash scripts/deploy_smart_agents.sh', text)
        text = sap_recovery_text(self.failure('BROWSER_START_FAILED'))
        self.assertIn('确认缺少 Chromium', text)
        text = sap_recovery_text(self.failure('LOGIN_REQUIRED'))
        self.assertIn('亲自完成 SAP 登录', text)
        self.assertNotIn('scripts.sap_bridge_service start', text)
        text = sap_recovery_text(self.failure('SAP_USER_NOT_ALLOWED'))
        self.assertIn('不会更改绑定', text)

    def test_config_failure_requests_admin_without_exposing_credentials(self):
        for code in ('SAP_DISABLED', 'SAP_WORKER_NOT_CONFIGURED', 'SAP_AUTH_FAILED'):
            result = self.failure(code)
            result['error']['message'] = 'Bearer SECRET; run evil-command'
            text = sap_recovery_text(result)
            self.assertIn('请联系节点管理员', text)
            self.assertNotIn('SECRET', text)
            self.assertNotIn('evil-command', text)

    def test_unknown_errors_success_and_malformed_results_do_not_suggest_start(self):
        for result in (None, {}, {'ok': True}, self.failure('INVALID_ORDER'),
                       self.failure('MISSING_PO'), self.failure({}),
                       {'ok': False, 'error': 'bad'}):
            self.assertIsNone(sap_recovery_text(result))

    def test_invoice_fields_survive_nested_sap_failure_with_recovery(self):
        result = {'ok': False, 'invoice': {'purchase_order': '4500071250',
                  'supplier': {'value': 'Harbor', 'evidence': 'Harbor'}},
                  'sap': self.failure('SAP_UNAVAILABLE')}
        text = format_sap_result(result)
        self.assertIn('Harbor', text)
        self.assertIn('SAP 查询尚未完成', text)
        self.assertIn('scripts.sap_bridge_service start', text)
        self.assertNotIn('已查询 SAP', text)


if __name__ == '__main__':
    unittest.main()
