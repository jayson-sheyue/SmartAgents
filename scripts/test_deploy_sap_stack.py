"""Deployment coordination tests; no cloud calls or resource creation."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import deploy_sap_stack as deploy


class DeploymentTests(unittest.TestCase):
    def test_configuration_uses_actual_runtime_identities_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'env').mkdir()
            (root/'.env').write_text('OTHER_FEATURE=keep\n')
            (root/'env/local.env').write_text('SAP_BROWSER_URL=https://tenant.s4hana.cloud.sap/ui#PurchaseOrder-manage\nSAP_WORKER_ALLOWED_USERS=tse:user@example.com\n')
            env={'GCP_PROJECT_ID':'demo','GCP_LOCATION':'us-central1','SMART_AGENTS_ENGINE_ID':'123'}
            tse={'spec':{'template':{'spec':{'serviceAccountName':'123-compute@developer.gserviceaccount.com'}}}}
            engine={'spec':{'effectiveIdentity':'service-123@gcp-sa-aiplatform-re.iam.gserviceaccount.com'}}
            with patch.object(deploy,'ROOT',root),patch.object(deploy,'describe',return_value=tse),patch.object(deploy,'gcloud',side_effect=['123\n','private-token\n']),patch('requests.get',return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:engine)):
                _,runtime=deploy.configuration(env)
            self.assertEqual(runtime,'123-compute@developer.gserviceaccount.com')
            self.assertEqual(env['SAP_CLOUD_INVOKER_ACCOUNTS'],runtime+',service-123@gcp-sa-aiplatform-re.iam.gserviceaccount.com')
            self.assertIn('OTHER_FEATURE=keep',(root/'.env').read_text())
            self.assertNotIn('private-token',(root/'.env').read_text())

    def test_tse_preserves_settings_and_smoke_failure_does_not_promote(self):
        env={'GCP_PROJECT_ID':'demo','SAP_TSE_REGION':'us-central1','SAP_TSE_SERVICE':'tse',
             'SAP_COMPUTER_USE_WORKER_URL':'https://worker.run.app'}
        current={'status':{'latestReadyRevisionName':'tse-new','traffic':[{'tag':'sap-cloud','url':'https://sap-cloud-tse.run.app'}]}}
        with patch.object(deploy,'gcloud') as gc,patch.object(deploy,'describe',return_value=current),patch('requests.get',return_value=SimpleNamespace(status_code=500)):
            with self.assertRaisesRegex(RuntimeError,'smoke check failed'):
                deploy.tse_deploy(env,{},'runtime@demo.iam.gserviceaccount.com',Path('/tmp'))
            calls=[c.args for c in gc.call_args_list]
            update=next(c for c in calls if c[:3]==('run','services','update'))
            self.assertIn('--no-traffic',update)
            self.assertTrue(any(a.startswith('--update-env-vars=') for a in update))
            self.assertTrue(any(a.startswith('--update-secrets=') for a in update))
            self.assertFalse(any(c[:3]==('run','services','update-traffic') for c in calls))


if __name__=='__main__':
    unittest.main()
