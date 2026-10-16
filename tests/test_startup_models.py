from pathlib import Path
import ctypes as C
from ctypes import wintypes as W
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop


class Client:
    def __init__(self, _): pass
    def load_models(self): return [{'slug':'future-one','display_name':'Future One'},{'slug':'older-one','display_name':'Older One'}]


class Watcher:
    def __init__(self, _): pass
    def close(self): pass


class Tests(unittest.TestCase):
    def test_background_launch_refresh_manual_pin_and_retry(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder, \
             patch.object(desktop,'TranslationClient',Client), \
             patch.object(desktop.native,'Hotkey',Watcher), \
             patch.object(desktop.native,'MouseWatcher',Watcher):
            handle = desktop.native.api(desktop.native.k,'CreateEventW',W.HANDLE,C.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR)(None,False,False,None)
            app = desktop.Desktop(folder,handle,background=True)
            try:
                deadline = time.monotonic()+3
                while not app.models and time.monotonic()<deadline:
                    app.root.update();time.sleep(.02)
                self.assertTrue(app.models)
                self.assertFalse(app.root.winfo_viewable())
                self.assertEqual(app.model.current(),0)
                app.model.current(1);app.model_selected()
                app.apply_models([{'slug':'new-future-model'},{'slug':'older-one'}])
                self.assertEqual(app.model.current(),1)
                app.auto_model.set(True);app.model_mode_changed()
                self.assertEqual(app.model.current(),0)
                app.events.put(('models_error',('Synthetic offline error',False)))
                app.tick()
                self.assertTrue(app.models)
                self.assertFalse(app.root.winfo_viewable())
                self.assertGreater(app.next_model_refresh,time.monotonic())
                state=json.loads((Path(folder)/'desktop.json').read_text())
                self.assertTrue(state['models_ready']);self.assertTrue(state['auto_model'])
            finally:
                app.exit()
                desktop.native.api(desktop.native.k,'CloseHandle',W.BOOL,W.HANDLE)(handle)


if __name__=='__main__': unittest.main(verbosity=2)

