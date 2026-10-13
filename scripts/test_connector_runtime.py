"""Windows lifecycle tests use isolated settings and mocks; no installation side effects."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from helper import runtime
from helper import connect

class Lifecycle(unittest.TestCase):
    def test_task_is_per_user_interactive_and_recovers(self):
        root=ET.fromstring(runtime.task_xml(r'PC\accountant',Path(r'C:\Users\A & B\connector.exe')))
        ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        self.assertEqual(root.find('t:Principals/t:Principal/t:LogonType',ns).text,'InteractiveToken')
        self.assertEqual(root.find('t:Principals/t:Principal/t:RunLevel',ns).text,'LeastPrivilege')
        self.assertEqual(root.find('t:Settings/t:RestartOnFailure/t:Interval',ns).text,'PT1M')
        self.assertEqual(root.find('t:Settings/t:ExecutionTimeLimit',ns).text,'PT0S')
        self.assertEqual(root.find('t:Actions/t:Exec/t:Arguments',ns).text,'--tray --managed')
    def test_task_file_encoding_matches_windows_utf16(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'task.xml'
            path.write_text(runtime.task_xml(r'PC\accountant',Path('connector.exe')),encoding='utf-16')
            self.assertEqual(ET.fromstring(path.read_bytes()).tag,'{http://schemas.microsoft.com/windows/2004/02/mit/task}Task')
            self.assertNotIn("encoding='utf-8'",path.read_text(encoding='utf-16'))

    def test_settings_preserve_pairing_configuration_and_pause(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(runtime,'HOME',Path(folder)):
            runtime.write_settings({'base':'https://example.test','paused':True,'startup_configured':True})
            self.assertTrue(runtime.read_settings()['paused'])
            runtime.write_settings({**runtime.read_settings(),'port':None})
            self.assertEqual(runtime.read_settings()['base'],'https://example.test')
    def test_corrupt_settings_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(runtime,'HOME',Path(folder)):
            p=Path(folder)/'settings.json';p.write_text('broken')
            with self.assertRaises(RuntimeError):runtime.read_settings()
            self.assertEqual(p.read_text(),'broken')
    def test_retry_bounded(self):
        self.assertEqual([runtime.backoff(n) for n in range(8)],[1,2,4,8,16,32,60,60])
    def make_connector(self):
        obj=object.__new__(connect.Connect)
        obj.settings={};obj.secret='synthetic';obj.connected=False;obj.stop=threading.Event()
        obj.config=Mock(return_value='https://example.test/api');obj.notify=Mock()
        obj.root=Mock();obj.lifecycle_lock=threading.RLock();obj.busy=False;obj.closing=False;obj.pending_until=0;obj.last_health=0;obj.health={}
        return obj
    def test_paused_start_has_no_polling_thread(self):
        obj=self.make_connector();obj.settings['paused']=True
        with patch.object(connect.threading,'Thread') as thread:obj.connect();thread.assert_not_called()
    def test_one_poll_thread_on_repeat_connect(self):
        obj=self.make_connector()
        with patch.object(connect.threading,'Thread') as thread:
            obj.connect();obj.connect();self.assertEqual(thread.call_count,1)
    def test_active_submission_defers_exit(self):
        obj=self.make_connector();obj.busy=True;obj.icon=Mock()
        obj.close();self.assertTrue(obj.closing);obj.icon.stop.assert_not_called();self.assertFalse(obj.stop.is_set())
    def test_network_outage_retries_without_pairing(self):
        obj=self.make_connector();obj.last_health=float('inf')
        client=Mock()
        def get(*args,**kwargs):
            if client.get.call_count==1:raise connect.httpx.ConnectError('offline')
            obj.stop.set();response=Mock(status_code=200);response.json.return_value={'job':None};return response
        client.get.side_effect=get
        with patch.object(connect.httpx,'Client') as ctor,patch.object(obj.stop,'wait',return_value=False),patch.object(connect,'milestone'):
            ctor.return_value.__enter__.return_value=client;obj.poll('https://example.test','synthetic')
        self.assertEqual(client.get.call_count,2);self.assertFalse(obj.connected)
    def test_revoked_credential_stops_retrying(self):
        obj=self.make_connector();client=Mock();client.get.return_value.status_code=401
        with patch.object(connect.httpx,'Client') as ctor,patch.object(connect,'milestone'):
            ctor.return_value.__enter__.return_value=client;obj.poll('https://example.test','synthetic')
        self.assertEqual(client.get.call_count,1);self.assertIn('revoked',obj.notify.call_args.args[0])
    def test_pause_is_persisted_and_resume_restarts(self):
        obj=self.make_connector();obj.connect=Mock()
        with patch.object(connect,'write_settings') as save:
            obj.toggle_pause();self.assertTrue(save.call_args.args[0]['paused']);self.assertTrue(obj.stop.is_set())
            obj.toggle_pause();self.assertFalse(save.call_args.args[0]['paused']);obj.connect.assert_called_once()
    def test_health_is_read_only_and_identity_scoped(self):
        obj=self.make_connector()
        with patch.object(connect,'candidates',return_value=([9000],True)),patch.object(connect,'local_operation',new=__import__('unittest.mock',fromlist=['AsyncMock']).AsyncMock(return_value={'companies':[{'identity':'a','name':'Pilot'}]})) as op:
            data=obj.check_health([{'identity':'a','name':'Pilot'},{'identity':'b','name':'Other'}])
        self.assertEqual(data['companies'],[{'identity':'a','reachable':True},{'identity':'b','reachable':False}])
        self.assertEqual(op.call_args.args,('discover',))
    def test_failed_update_restores_existing_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);old=home/'PhilixaConnect.exe';old.write_bytes(b'old-version')
            setup=home/'setup.exe';setup.write_bytes(b'new-version')
            with patch.object(connect,'HOME',home),patch.object(connect,'EXE',old),patch.object(connect.sys,'frozen',True,create=True),patch.object(connect.sys,'executable',str(setup)),patch.object(connect,'kernel',Mock()),patch.object(connect.psutil,'process_iter',return_value=[]),patch.object(connect,'register_startup',side_effect=RuntimeError('startup failed')),patch.object(connect,'write_settings') as save,patch.object(connect,'read_settings',return_value={'paused':True}):
                with self.assertRaises(RuntimeError):connect.install()
            self.assertEqual(old.read_bytes(),b'old-version')
            self.assertTrue(save.call_args.args[0]['paused'])
            self.assertFalse(save.call_args.args[0]['startup_configured'])
    def test_busy_update_defers_without_copy_or_kill(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);old=home/'PhilixaConnect.exe';old.write_bytes(b'old-version')
            with patch.object(connect,'HOME',home),patch.object(connect,'EXE',old),patch.object(connect.sys,'frozen',True,create=True),patch.object(connect.sys,'executable',str(home/'setup.exe')),patch.object(connect,'kernel',Mock()) as kernel,patch.object(connect.psutil,'process_iter',return_value=[SimpleNamespace(info={'exe':str(old)})]),patch.object(connect.time,'monotonic',side_effect=[0,31]),patch.object(connect,'register_startup') as register:
                with self.assertRaisesRegex(RuntimeError,'deferred'):connect.install()
            self.assertEqual(old.read_bytes(),b'old-version');register.assert_not_called()
            kernel.ResetEvent.assert_called_once()

if __name__=='__main__':unittest.main()
