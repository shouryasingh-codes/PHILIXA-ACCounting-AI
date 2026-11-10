"""Test actual connector methods with injected startup failure; no Windows app launch.

AST isolation avoids importing Windows credential/UI APIs into the test process.
Only the current source methods execute, against synthetic clients and fake threads.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock


def methods(namespace):
    source = Path(__file__).resolve().parents[1] / 'helper/connect.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Connect')
    selected = [n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('poll','connect')]
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(source),'exec'),namespace)
    return namespace


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.factory=Mock(side_effect=FileNotFoundError('synthetic missing resource'))
        self.record=Mock(); self.events=Mock()
        self.ns=methods({'sync_client':self.factory,'milestone':self.events,
                         'record_failure':self.record,'HOME':Path('synthetic-unused'),
                         'threading':SimpleNamespace(Thread=Mock()),'PROTOCOL_VERSION':10})
        self.obj=SimpleNamespace(connected=True,settings={'paused':False},stop=threading.Event(),
                                 notify=Mock(),secret='synthetic-only',config=lambda:'https://synthetic.invalid')
        self.obj.poll=lambda *args:self.ns['poll'](self.obj,*args)

    def test_client_initialization_failure_releases_connected_flag(self):
        self.ns['poll'](self.obj,'https://synthetic.invalid','synthetic-only')
        self.assertFalse(self.obj.connected)
        self.record.assert_called_once()
        self.assertIn('Network startup failed',self.obj.notify.call_args.args[0])

    def test_failed_startup_can_retry_saved_connection(self):
        class InlineThread:
            def __init__(self,target,args,daemon): self.target,self.args=target,args
            def start(self): self.target(*self.args)
        self.ns['threading']=SimpleNamespace(Thread=InlineThread)
        self.obj.connected=False
        for _ in range(2): self.ns['connect'](self.obj)
        self.assertEqual(self.factory.call_count,2)
        self.assertFalse(self.obj.connected)
        self.assertEqual(self.obj.secret,'synthetic-only')

    def test_os_thread_start_failure_does_not_latch_connected(self):
        self.ns['threading'].Thread.return_value.start.side_effect=RuntimeError('synthetic thread failure')
        self.obj.connected=False
        self.ns['connect'](self.obj)
        self.assertFalse(self.obj.connected)
        self.assertIn('worker could not start',self.obj.notify.call_args.args[0])


if __name__=='__main__': unittest.main()
