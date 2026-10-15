"""Background lifecycle and deployment gate; no cloud calls or SAP writes."""
import asyncio
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock,patch

import httpx
from scripts import sap_bridge_service as service
from scripts import sap_local_bridge as bridge
from scripts.check_sap_deployment import validate_sap_online

TOKEN='t'*32
USER='tse:owner@example.com'
ENV={'SAP_COMPUTER_USE_ENABLED':'true','SAP_COMPUTER_USE_WORKER_URL':'https://node.example.com','SAP_COMPUTER_USE_TOKEN':TOKEN}


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_start_checks_existing_process_without_rotating_url(self):
        info={'pid':42,'instance_id':'a'*32}
        with patch.object(service,'record',return_value=info),patch.object(service,'is_owned_running',return_value=True), \
             patch.object(service,'check',AsyncMock(return_value={'ok':True})) as check, \
             patch.object(service.subprocess,'Popen') as spawn:
            await service.start(USER,8011)
        check.assert_awaited_once_with(USER)
        spawn.assert_not_called()

    async def test_background_child_detaches_with_private_logs_and_no_credentials_in_args(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'env').mkdir();(root/'env/local.env').write_text('SAP_COMPUTER_USE_TOKEN='+TOKEN+'\n')
            process=Mock(pid=42);process.poll.return_value=None
            with patch.object(service,'ROOT',root),patch.object(service,'LOG',root/'service.log'), \
                 patch.object(service,'record',return_value=None),patch.object(service,'probe',AsyncMock(side_effect=httpx.ConnectError('offline'))), \
                 patch.object(service,'check',AsyncMock(return_value={'ok':True})),patch.object(service,'save_record') as save, \
                 patch.object(service.sys,'platform','linux'),patch.object(service.subprocess,'Popen',return_value=process) as spawn:
                await service.start(USER,8011)
            kwargs=spawn.call_args.kwargs
            self.assertTrue(kwargs['start_new_session'])
            self.assertEqual(kwargs['stdin'],subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'],subprocess.STDOUT)
            self.assertEqual((root/'service.log').stat().st_mode & 0o777,0o600)
            self.assertNotIn(TOKEN,str(spawn.call_args))
            save.assert_called_once()

    async def test_foreground_service_is_not_replaced_silently(self):
        with patch.object(service,'record',return_value=None),patch.object(service,'probe',AsyncMock(return_value={'ok':True})), \
             patch.object(service.subprocess,'Popen') as spawn:
            with self.assertRaises(ValueError): await service.start(USER,8011)
        spawn.assert_not_called()

    def test_stop_never_signals_a_reused_or_unowned_pid(self):
        with patch.object(service,'record',return_value=None),patch.object(service.os,'kill') as kill:
            service.stop_owned()
        kill.assert_not_called()
        info={'pid':42,'instance_id':'a'*32}
        with patch.object(service.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='python unrelated.py')):
            self.assertFalse(service.is_owned_running(info))
        command='python -m scripts.sap_local_bridge --instance-id '+('a'*32)
        with patch.object(service.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=command)):
            self.assertTrue(service.is_owned_running(info))

    def test_control_lock_rejects_concurrent_start_or_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(service,'BRIDGE_DIR',root),patch.object(service,'LOCK',root/'control.lock'):
                with service.control_lock():
                    with self.assertRaises(ValueError):
                        with service.control_lock(): pass

    async def test_direct_foreground_launch_reuses_healthy_tunnel(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cloud=root/'cloud.env'
            cloud.write_text('SAP_COMPUTER_USE_WORKER_URL=https://same.example.com\nSAP_COMPUTER_USE_TOKEN='+TOKEN+'\n')
            with patch.object(bridge,'CLOUD_ENV',cloud),patch.object(bridge,'load_runtime_env',lambda:None), \
                 patch.dict('os.environ',{'SAP_COMPUTER_USE_TOKEN':TOKEN}), \
                 patch.object(bridge.sys,'argv',['bridge','--tse-email','owner@example.com']), \
                 patch.object(bridge.shutil,'which',return_value='cloudflared'), \
                 patch.object(bridge,'probe',AsyncMock(return_value={'ok':True})), \
                 patch.object(bridge.asyncio,'create_subprocess_exec') as spawn:
                await bridge.main()
            spawn.assert_not_called()


class DeploymentGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_sap_does_not_add_network_check(self):
        with patch.object(bridge,'probe',AsyncMock()) as probe:
            self.assertIsNone(await validate_sap_online({'SAP_COMPUTER_USE_ENABLED':'false'}))
        probe.assert_not_awaited()

    async def test_healthy_endpoint_passes_even_before_browser_login(self):
        with patch.object(bridge,'probe',AsyncMock(return_value={'ok':True,'logged_in':False})) as probe:
            result=await validate_sap_online(ENV,user=USER)
        self.assertFalse(result['logged_in'])
        probe.assert_awaited_once_with(ENV['SAP_COMPUTER_USE_WORKER_URL'],TOKEN,USER)

    async def test_dead_tunnel_blocks_deployment_without_secret_output_or_restart(self):
        with patch.object(bridge,'probe',AsyncMock(side_effect=httpx.ConnectError('Bearer '+TOKEN))), \
             patch.object(bridge.asyncio,'create_subprocess_exec') as spawn:
            with self.assertRaises(ValueError) as exc:await validate_sap_online(ENV,user=USER)
        self.assertIn('已阻止部署',str(exc.exception))
        self.assertNotIn(TOKEN,str(exc.exception))
        spawn.assert_not_called()

    def test_deployment_failure_stops_before_any_cloud_update(self):
        from scripts import deploy_smart_agents as deployment
        with patch.dict('os.environ', {'GCP_PROJECT_ID':'test-project','GCP_LOCATION':'us-central1','SMART_AGENTS_ENGINE_ID':'test-engine'}), \
             patch('scripts.check_sap_deployment.validate_sap_online',AsyncMock(side_effect=ValueError('offline'))), \
             patch.object(deployment,'_install_deploy_patches') as prepare_cloud:
            with self.assertRaises(ValueError): deployment.main()
        prepare_cloud.assert_not_called()

if __name__=='__main__':unittest.main()
