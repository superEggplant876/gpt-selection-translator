from pathlib import Path
import sys
import ctypes as C
from ctypes import wintypes as W
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop


class Watcher:
    def __init__(self,_):pass
    def close(self):pass


class Client:
    def __init__(self,_):
        self.first=threading.Event();self.finish=threading.Event();self.failed=False
    def load_models(self):return [{'slug':'synthetic-model','display_name':'Test Model'}]
    def translate(self,text,model,on_delta):
        self.first.wait(4);on_delta('你')
        self.finish.wait(4)
        if self.failed:raise desktop.VerificationError('模拟连接中断')
        on_delta('好，世界！');return '你好，世界！'


class Tests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.patches=[patch.object(desktop,'TranslationClient',Client),
                      patch.object(desktop.native,'Hotkey',Watcher),
                      patch.object(desktop.native,'MouseWatcher',Watcher),
                      patch.object(desktop.Desktop,'selection_worker',lambda self:None)]
        for item in self.patches:item.start()
        self.event=desktop.native.api(desktop.native.k,'CreateEventW',W.HANDLE,C.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR)(None,False,False,None)
        self.app=desktop.Desktop(self.temporary.name,self.event,background=True)
        self.pump(lambda:bool(self.app.models))
    def tearDown(self):
        self.app.client.first.set();self.app.client.finish.set()
        self.app.exit()
        desktop.native.api(desktop.native.k,'CloseHandle',W.BOOL,W.HANDLE)(self.event)
        for item in reversed(self.patches):item.stop()
        self.temporary.cleanup()
    def pump(self,predicate,timeout=3):
        limit=time.monotonic()+timeout
        while time.monotonic()<limit:
            self.app.root.update()
            if predicate():return
            time.sleep(.015)
        self.fail('UI condition did not complete')
    def start(self):self.app.translate('Hello',floating=True,position=(150,150))

    def test_loading_flows_and_first_character_replaces_the_action(self):
        self.start()
        self.pump(lambda:self.app.popup.shimmer_tick>=3)
        self.assertEqual(self.app.popup.phase,'loading')
        self.assertFalse(self.app.root.winfo_viewable())
        self.app.client.first.set()
        self.pump(lambda:self.app.popup.value=='你')
        self.assertEqual(self.app.popup.phase,'result')
        self.assertIsNone(self.app.popup.animation)
        self.assertEqual(self.app.popup.text.cget('font'),str(self.app.popup.font))
        self.assertFalse(self.app.root.winfo_viewable())
        self.app.client.finish.set();self.pump(lambda:not self.app.busy)
        self.assertEqual(self.app.popup.value,'你好，世界！')
        self.assertFalse(self.app.root.winfo_viewable())

    def test_context_menu_opens_dashboard_only_on_explicit_action(self):
        self.start()
        self.app.popup.context_menu(SimpleNamespace(x_root=200,y_root=180))
        menu=self.app.popup.menu
        self.assertTrue(menu.winfo_viewable())
        canvas=menu.winfo_children()[0]
        self.pump(lambda:canvas.winfo_viewable())
        canvas.event_generate('<ButtonRelease-1>',x=20,y=20)
        self.pump(lambda:self.app.root.winfo_viewable())
        self.assertFalse(self.app.translation_floating)
        self.assertFalse(self.app.popup.winfo_viewable())
        self.assertGreater(self.app.result.cget('corner_radius'),0)

    def test_partial_failure_is_visible_without_opening_dashboard(self):
        self.start();self.app.client.first.set()
        self.pump(lambda:self.app.popup.value=='你')
        self.app.client.failed=True;self.app.client.finish.set()
        self.pump(lambda:not self.app.busy)
        self.assertEqual(self.app.popup.phase,'error')
        self.assertIn('未完成',self.app.popup.value)
        self.assertFalse(self.app.root.winfo_viewable())

    def test_long_result_is_bounded_and_keeps_the_small_font(self):
        value='这是一段较长的译文。'*250
        self.app.popup.loading((150,150));self.app.popup.set_text(value)
        self.pump(lambda:self.app.popup.text.get('1.0','end-1c')==value)
        self.assertLessEqual(self.app.popup.width,round(420*self.app.popup.scale))
        self.assertLessEqual(self.app.popup.height,round(320*self.app.popup.scale))
        self.assertEqual(self.app.popup.font.cget('size'),9)

    def test_dismissed_result_does_not_reappear_on_a_later_delta(self):
        self.start();self.app.popup.dismiss();self.app.client.first.set();self.app.client.finish.set()
        self.pump(lambda:not self.app.busy)
        self.assertFalse(self.app.popup.winfo_viewable())


if __name__=='__main__':unittest.main(verbosity=2)
