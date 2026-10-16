"""Personal Windows selection translator, using the user's ChatGPT plan."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import tkinter as tk

import native_windows as native
from ui_theme import build_dashboard
from popup_style import create_popup
from translation_client import TranslationClient
from verify_connection import VerificationError, atomic_write
from model_catalog import REFRESH_SECONDS, choose_model

BASE = Path(__file__).resolve().parent


class Desktop:
    def __init__(self, directory, show_event, background=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.show_event = show_event
        self.events = queue.Queue()
        self.selections = queue.Queue(maxsize=1)
        self.client = TranslationClient(self.directory)
        self.models = []
        self.model_refreshing = False
        self.model_retry_seconds = 30
        self.next_model_refresh = 0
        self.models_updated_at = None
        self.pending_models = None
        self.busy = False
        self.last_selection = None
        self.popup_text = ''
        self.popup_source = None
        self.popup_timer = None
        self.selection_generation = 0
        self.mouse_start = None
        self.previous_click = None
        self.mouse_hook_ready = False
        self.stopping = False
        self.cancel = threading.Event()
        self.settings = {}
        try:
            self.settings = json.loads((self.directory / 'settings.json').read_text())
        except (OSError, ValueError):
            pass
        self.translation_floating = False
        self.stream_text = ''
        build_dashboard(self, background)
        self.popup = create_popup(self.root, self.translate_popup, self.show,
                                  self.copy_result, self.cancel.set)
        self.root.update_idletasks()
        self.hwnd = native.ancestor(self.root.winfo_id(), 2)
        self.popup_hwnd = native.ancestor(self.popup.winfo_id(), 2)
        native.no_activate(self.popup_hwnd)
        self.mouse_down = bool(native.key_state(1) & 0x8000)
        self.hotkey_ready = False
        self.hotkey = native.Hotkey(self.events)
        self.mouse_watcher = native.MouseWatcher(self.events)
        threading.Thread(target=self.selection_worker, daemon=True).start()
        self.refresh_models()
        self.write_runtime_status()
        self.root.after(60, self.tick)

    def set_result(self, text):
        self.result.configure(state='normal'); self.result.delete('1.0', 'end'); self.result.insert('1.0', text); self.result.configure(state='disabled')

    def append_result(self, text):
        self.result.configure(state='normal'); self.result.insert('end', text); self.result.see('end'); self.result.configure(state='disabled')

    def save_settings(self):
        index = self.model.current()
        current = self.models[index]['slug'] if 0 <= index < len(self.models) else self.settings.get('model', '')
        self.settings = {'auto_popup': self.auto.get(), 'model': current, 'auto_model':self.auto_model.get()}
        atomic_write(self.directory / 'settings.json', json.dumps(self.settings).encode())
        if not self.auto.get():
            self.popup.withdraw()

    def write_runtime_status(self):
        index = self.model.current()
        atomic_write(self.directory / 'desktop.json', json.dumps({
            'pid':os.getpid(), 'version':'1.3', 'hotkey':'Ctrl+Alt+T',
            'hotkey_ready':self.hotkey_ready, 'mouse_ready':self.mouse_hook_ready,
            'auto_popup':self.auto.get(), 'models_ready':bool(self.models),
            'model_count':len(self.models), 'model':self.models[index]['slug'] if 0 <= index < len(self.models) else None,
            'auto_model':self.auto_model.get(), 'models_updated_at':self.models_updated_at,
            'visible':bool(self.root.winfo_viewable()),
            'popup_phase':self.popup.phase}).encode())

    def model_selected(self, event=None):
        self.auto_model.set(False)
        self.save_settings(); self.write_runtime_status()

    def model_mode_changed(self):
        if self.auto_model.get() and self.models:
            self.model.current(0)
        self.save_settings(); self.write_runtime_status()

    def refresh_models(self, manual=False):
        if self.model_refreshing or self.stopping:
            return
        if self.busy:
            self.next_model_refresh = time.monotonic() + 5
            return
        self.model_refreshing = True
        if manual:
            self.status.set('正在更新账号可用的模型……')
        threading.Thread(target=self.models_worker, args=(manual,), daemon=True).start()

    def models_worker(self, manual=False):
        try:
            self.events.put(('models', self.client.load_models()))
        except VerificationError as e:
            self.events.put(('models_error', (str(e), manual)))
        except Exception:
            self.events.put(('models_error', ('模型列表暂时无法读取，联网后会自动重试。', manual)))

    def apply_models(self, value):
        current = self.settings.get('model', '')
        if self.models and 0 <= self.model.current() < len(self.models):
            current = self.models[self.model.current()]['slug']
        self.models = value
        self.model['values'] = [m.get('display_name') or m['slug'] for m in value]
        self.model.current(choose_model(value, current, self.auto_model.get()))
        self.models_updated_at = time.time()
        self.status.set('已连接 ChatGPT 套餐 · 模型列表已更新。')
        self.save_settings(); self.write_runtime_status()

    def selection_worker(self):
        try:
            reader = native.SelectionReader()
        except Exception:
            reader = None
            self.events.put(('selection_warning', None))
        while not self.stopping:
            try:
                kind, hwnd, position, generation, allow_copy_button = self.selections.get(timeout=.3)
            except queue.Empty:
                continue
            try:
                if generation != self.selection_generation:
                    continue
                text = reader.selection(hwnd, position if kind == 'auto' else None) if reader else ''
                if not text.strip() and kind in ('hotkey', 'popup'):
                    text = native.copy_selection(hwnd, self.hwnd)
                self.events.put(('selected', (kind, text, hwnd, position, generation, allow_copy_button)))
            except native.SelectionError as e:
                if kind in ('hotkey', 'popup'):
                    self.events.put(('capture_error', str(e)))
            except Exception:
                if kind in ('hotkey', 'popup'):
                    self.events.put(('capture_error', '没有读到选中文字，请复制后右键进入后台，使用“翻译剪贴板”。'))

    def capture(self, kind, hwnd, position, generation=None, allow_copy_button=False):
        generation = self.selection_generation if generation is None else generation
        if self.busy or self.stopping or generation != self.selection_generation or native.foreground() != hwnd:
            return
        try:
            self.selections.put_nowait((kind, hwnd, position, generation, allow_copy_button))
        except queue.Full:
            pass

    def selected(self, kind, text, hwnd, position, generation, allow_copy_button=False):
        if self.busy or generation != self.selection_generation or native.foreground() != hwnd:
            return
        if not text.strip():
            if not (kind == 'auto' and allow_copy_button):
                return
            if self.popup_text.strip() and self.popup_source == (hwnd, position, generation):
                return
        if len(text) > 20000:
            if kind == 'hotkey':
                self.popup.error('选中文字超过 20,000 字，请分段翻译。')
            return
        if kind in ('hotkey', 'popup'):
            position=(position[0]+14,position[1]+16)
            self.translate(text, floating=True, position=position if kind=='hotkey' else None)
            return
        selection = (hwnd, text, generation)
        if self.auto.get() and selection != self.last_selection:
            self.last_selection = selection
            self.popup_text = text
            self.popup_source = (hwnd, position, generation)
            x, y = position
            self.popup.idle((x+14,y+16))
            if self.popup_timer:
                self.popup.after_cancel(self.popup_timer)
            self.popup_timer = self.popup.after(10000, self.popup.withdraw)

    def translate_popup(self):
        text = self.popup_text
        if self.popup_timer:
            self.popup.after_cancel(self.popup_timer);self.popup_timer=None
        if text.strip():
            self.translate(text, floating=True)
        elif self.popup_source:
            hwnd, position, generation = self.popup_source
            self.popup.loading()
            self.capture('popup', hwnd, position, generation)

    def mouse_event(self, pressed, hwnd, position):
        x, y = position
        inside = self.popup.contains(x,y)
        if inside:
            return
        if pressed:
            if self.busy:
                self.popup.close_menu()
                return
            self.popup.dismiss()
            self.selection_generation += 1
            self.last_selection = None
            self.mouse_start = (hwnd, position)
            return
        if self.busy or not self.auto.get() or native.pid(hwnd) == os.getpid():
            return
        gesture = False
        if self.mouse_start and self.mouse_start[0] == hwnd:
            px, py = self.mouse_start[1]
            gesture = abs(x-px) + abs(y-py) >= 5
        now = time.monotonic()
        if self.previous_click:
            previous_hwnd, (px, py), when = self.previous_click
            gesture |= previous_hwnd == hwnd and now-when < .65 and abs(x-px)+abs(y-py) < 8
        gesture |= bool(native.key_state(0x10) & 0x8000)
        self.previous_click = (hwnd, position, now)
        generation = self.selection_generation
        # A browser selection can be unavailable to accessibility. Offer an
        # explicit button for selection gestures, and copy only after its click.
        class_name = C.create_unicode_buffer(128)
        native.api(native.u, 'GetClassNameW', C.c_int, W.HWND, W.LPWSTR, C.c_int)(hwnd, class_name, 128)
        allow_copy_button = gesture and class_name.value.startswith('Chrome_WidgetWin')
        for delay in (100, 350, 800):
            self.root.after(delay, lambda h=hwnd,p=position,g=generation,l=allow_copy_button:
                            self.capture('auto', h, p, g, l))

    def translate_clipboard(self):
        try:
            self.translate(native.read_clipboard(self.hwnd), floating=False)
        except native.SelectionError as e:
            self.status.set(str(e))

    def translate(self, text, floating=True, position=None):
        if self.busy:
            if floating:
                self.popup.reveal(position)
            return
        self.translation_floating = floating
        if self.popup_timer:
            self.popup.after_cancel(self.popup_timer);self.popup_timer=None
        if floating:self.popup.loading(position)
        else:self.popup.dismiss()
        if not text.strip():
            self.status.set('请先选中文字，或在原文框里粘贴内容。')
            if floating:self.popup.error('请先选中文字。')
            return
        if len(text) > 20000:
            self.status.set('选中文字超过 20,000 字，请分段翻译。')
            if floating:self.popup.error('选中文字超过 20,000 字，请分段翻译。')
            return
        self.source.delete('1.0', 'end'); self.source.insert('1.0', text)
        index = self.model.current()
        if not 0 <= index < len(self.models):
            self.status.set('模型尚未就绪，请稍后或点击“登录 / 重新连接”。')
            if floating:self.popup.error('模型尚未就绪。右键进入后台，可查看登录状态。')
            return
        model = self.models[index]['slug']
        self.busy = True; self.cancel.clear(); self.set_result('');self.stream_text=''
        self.translate_button.configure(state='disabled'); self.cancel_button.configure(state='normal')
        self.status.set('正在翻译……')
        def worker():
            def delta(value):
                if self.cancel.is_set():
                    raise VerificationError('已取消本次翻译。')
                self.events.put(('delta', value))
            try:
                result = self.client.translate(text, model, on_delta=delta)
                if self.cancel.is_set():
                    raise VerificationError('已取消本次翻译。')
                self.events.put(('completed', result))
            except VerificationError as e:
                self.events.put(('translation_error', str(e)))
            except Exception:
                self.events.put(('translation_error', '翻译连接中断，请检查网络后重试。'))
        threading.Thread(target=worker, daemon=True).start()

    def finish(self):
        self.busy = False; self.translate_button.configure(state='normal'); self.cancel_button.configure(state='disabled')
        if self.pending_models:
            models, self.pending_models = self.pending_models, None
            self.apply_models(models)

    def tick(self):
        if self.stopping:
            return
        if native.api(native.k, 'WaitForSingleObject', W.DWORD, W.HANDLE, W.DWORD)(self.show_event, 0) == 0:
            self.show()
        for _ in range(120):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'models':
                self.model_refreshing = False
                self.model_retry_seconds = 30
                self.next_model_refresh = time.monotonic() + REFRESH_SECONDS
                if self.busy:
                    self.pending_models = value
                else:
                    self.apply_models(value)
            elif kind == 'models_error':
                self.model_refreshing = False
                self.next_model_refresh = time.monotonic() + self.model_retry_seconds
                self.model_retry_seconds = min(300, self.model_retry_seconds * 2)
                message, manual = value
                if not self.busy and (manual or not self.models):
                    self.status.set(message + ' 将自动重试。')
                self.write_runtime_status()
            elif kind == 'hotkey_ready':
                self.hotkey_ready = True
                self.write_runtime_status()
            elif kind == 'hotkey':
                self.capture('hotkey', *value)
            elif kind == 'selected':
                self.selected(*value)
            elif kind == 'mouse_ready':
                self.mouse_hook_ready = True
                self.write_runtime_status()
            elif kind == 'mouse':
                self.mouse_event(*value)
            elif kind == 'capture_error':
                self.status.set(value);self.popup.error(value)
            elif kind in ('error', 'hotkey_error'):
                self.status.set(value)
            elif kind == 'selection_warning':
                self.auto.set(False)
                self.status.set('此环境未能启用划词按钮，可先使用 Ctrl+Alt+T。')
            elif kind == 'delta':
                self.append_result(value)
                self.stream_text+=value
                if self.translation_floating and value:self.popup.append(value)
            elif kind == 'completed':
                self.set_result(value)
                if self.translation_floating:self.popup.set_text(value)
                self.finish(); self.status.set('翻译完成 · 使用 ChatGPT 套餐')
                self.write_runtime_status()
            elif kind == 'translation_error':
                self.finish(); self.status.set(value + ' 当前显示的内容可能不完整。')
                if self.translation_floating:
                    message=(self.stream_text+'\n\n'+value+'（译文未完成）') if self.stream_text else value
                    self.popup.error(message)
                self.write_runtime_status()
        pressed = bool(native.key_state(1) & 0x8000)
        if not self.mouse_hook_ready and pressed != self.mouse_down:
            self.mouse_event(pressed, native.foreground(), native.point())
        self.mouse_down = pressed
        if not self.model_refreshing and time.monotonic() >= self.next_model_refresh:
            self.refresh_models()
        self.root.after(60, self.tick)

    def copy_result(self):
        text = self.result.get('1.0', 'end-1c')
        if text:
            self.root.clipboard_clear(); self.root.clipboard_append(text); self.root.update_idletasks()
            self.status.set('译文已复制。')

    def show(self):
        self.translation_floating=False
        self.popup.dismiss()
        self.root.deiconify(); self.root.lift()
        self.root.after_idle(self.write_runtime_status)

    def hide(self):
        self.root.withdraw()
        self.write_runtime_status()

    def login(self):
        if self.busy:
            return
        subprocess.Popen([str(Path(os.sys.executable).with_name('pythonw.exe')), str(BASE/'verify_connection.py'), '--state-dir', str(self.directory)], creationflags=0x08000000)
        self.status.set('完成官方登录后，再点击这里重新读取模型。')
        self.refresh_models()

    def exit(self):
        self.stopping = True; self.cancel.set(); self.hotkey.close(); self.mouse_watcher.close()
        self.popup.destroy()
        for task in self.root.tk.call('after','info'):
            self.root.tk.call('after','cancel',task)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', default=str(BASE/'data'))
    parser.add_argument('--background', action='store_true')
    args = parser.parse_args()
    native.api(native.u, 'SetProcessDPIAware', W.BOOL)()
    tag = __import__('hashlib').sha256(str(Path(args.state_dir).resolve()).lower().encode()).hexdigest()[:24]
    create_mutex = native.api(native.k, 'CreateMutexW', W.HANDLE, C.c_void_p, W.BOOL, W.LPCWSTR)
    create_event = native.api(native.k, 'CreateEventW', W.HANDLE, C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR)
    mutex = create_mutex(None, False, 'Local\\GPTSelectionTranslatorDesktop-'+tag)
    existed = C.get_last_error() == 183
    event = create_event(None, False, False, 'Local\\GPTSelectionTranslatorShow-'+tag)
    if existed:
        if not args.background:
            native.api(native.k, 'SetEvent', W.BOOL, W.HANDLE)(event)
        return
    app = Desktop(args.state_dir, event, background=args.background)
    try:
        app.root.mainloop()
    finally:
        native.api(native.k, 'CloseHandle', W.BOOL, W.HANDLE)(event)
        native.api(native.k, 'CloseHandle', W.BOOL, W.HANDLE)(mutex)


if __name__ == '__main__':
    main()
