"""Windows selection access and hotkeys for the translator product itself."""
import ctypes as C
from ctypes import wintypes as W
from contextlib import contextmanager
import os
from pathlib import Path
import queue
import sys
import threading
import time

u = C.WinDLL('user32', use_last_error=True)
k = C.WinDLL('kernel32', use_last_error=True)


def api(dll, name, restype, *args):
    fn = getattr(dll, name); fn.restype = restype; fn.argtypes = args
    return fn


foreground = api(u, 'GetForegroundWindow', W.HWND)
ancestor = api(u, 'GetAncestor', W.HWND, W.HWND, W.UINT)
window_pid = api(u, 'GetWindowThreadProcessId', W.DWORD, W.HWND, C.POINTER(W.DWORD))
key_state = api(u, 'GetAsyncKeyState', C.c_short, C.c_int)
cursor = api(u, 'GetCursorPos', W.BOOL, C.POINTER(W.POINT))
open_clip = api(u, 'OpenClipboard', W.BOOL, W.HWND)
close_clip = api(u, 'CloseClipboard', W.BOOL)
enum_clip = api(u, 'EnumClipboardFormats', W.UINT, W.UINT)
get_clip = api(u, 'GetClipboardData', W.HANDLE, W.UINT)
set_clip = api(u, 'SetClipboardData', W.HANDLE, W.UINT, W.HANDLE)
empty_clip = api(u, 'EmptyClipboard', W.BOOL)
sequence = api(u, 'GetClipboardSequenceNumber', W.DWORD)
clip_owner = api(u, 'GetClipboardOwner', W.HWND)
global_size = api(k, 'GlobalSize', C.c_size_t, W.HANDLE)
global_lock = api(k, 'GlobalLock', C.c_void_p, W.HANDLE)
global_unlock = api(k, 'GlobalUnlock', W.BOOL, W.HANDLE)
global_alloc = api(k, 'GlobalAlloc', W.HANDLE, W.UINT, C.c_size_t)
global_free = api(k, 'GlobalFree', W.HANDLE, W.HANDLE)
get_long = api(u, 'GetWindowLongPtrW', C.c_ssize_t, W.HWND, C.c_int)
set_long = api(u, 'SetWindowLongPtrW', C.c_ssize_t, W.HWND, C.c_int, C.c_ssize_t)
set_pos = api(u, 'SetWindowPos', W.BOOL, W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)


class SelectionError(Exception):
    pass


def point():
    value = W.POINT(); cursor(C.byref(value)); return value.x, value.y


def work_area(x, y):
    class MonitorInfo(C.Structure):
        _fields_ = [('cbSize', W.DWORD), ('rcMonitor', W.RECT), ('rcWork', W.RECT), ('dwFlags', W.DWORD)]
    monitor = api(u, 'MonitorFromPoint', W.HANDLE, W.POINT, W.DWORD)(W.POINT(x, y), 2)
    info = MonitorInfo(); info.cbSize = C.sizeof(info)
    if not api(u, 'GetMonitorInfoW', W.BOOL, W.HANDLE, C.POINTER(MonitorInfo))(monitor, C.byref(info)):
        raise SelectionError('暂时无法确定屏幕位置。')
    r = info.rcWork
    return r.left, r.top, r.right, r.bottom


def pid(hwnd):
    value = W.DWORD(); window_pid(hwnd, C.byref(value)); return value.value


def no_activate(hwnd):
    set_long(hwnd, -20, get_long(hwnd, -20) | 0x08000000 | 0x00000080)


def show_no_activate(hwnd, x, y, width, height):
    set_pos(hwnd, W.HWND(-1), x, y, width, height, 0x0010 | 0x0040)


@contextmanager
def clipboard(hwnd):
    for _ in range(12):
        if open_clip(hwnd):
            break
        time.sleep(.025)
    else:
        raise SelectionError('剪贴板正被其他软件使用，请稍后重试。')
    try:
        yield
    finally:
        close_clip()


def blob(handle):
    length = global_size(handle)
    if not length or length > 32 * 1024 * 1024:
        raise SelectionError('当前剪贴板含有不能安全还原的内容。请先复制原文，再点击“翻译剪贴板”。')
    ptr = global_lock(handle)
    if not ptr:
        raise SelectionError('暂时无法读取剪贴板。')
    try:
        return C.string_at(ptr, length)
    finally:
        global_unlock(handle)


def read_clipboard(hwnd, with_sequence=False):
    with clipboard(hwnd):
        handle = get_clip(13)
        if not handle:
            raise SelectionError('剪贴板中没有文字。请先复制原文。')
        text = blob(handle).decode('utf-16-le', errors='replace').split('\x00', 1)[0]
        return (text, sequence()) if with_sequence else text


def snapshot_clipboard(hwnd):
    items = []
    with clipboard(hwnd):
        fmt = 0
        while True:
            fmt = enum_clip(fmt)
            if not fmt:
                break
            if fmt == 2:
                # Windows synthesizes a bitmap handle from DIB on demand. Keep
                # its full DIB bytes rather than treating HBITMAP as HGLOBAL.
                dib = get_clip(8)
                if not dib:
                    raise SelectionError('无法备份剪贴板图片，请先复制原文后再翻译。')
                if not any(saved_fmt == 8 for saved_fmt, _ in items):
                    items.append((8, blob(dib)))
                continue
            if fmt in {3, 9, 14, 0x80, 0x82, 0x83, 0x8E} or 0x200 <= fmt <= 0x3FF:
                raise SelectionError('当前剪贴板含有图片或特殊格式。请先复制原文，再点击“翻译剪贴板”。')
            if not any(saved_fmt == fmt for saved_fmt, _ in items):
                items.append((fmt, blob(get_clip(fmt))))
            if sum(len(b) for _, b in items) > 32 * 1024 * 1024:
                raise SelectionError('当前剪贴板内容较大。请先复制原文，再点击“翻译剪贴板”。')
        return items, sequence()


def restore_clipboard(hwnd, items, expected):
    handles = []
    try:
        # Allocate every replacement before emptying the clipboard.
        for fmt, data in items:
            handle = global_alloc(0x0002, len(data))
            if not handle:
                raise SelectionError('剪贴板备份无法还原。')
            handles.append([fmt, handle])
            ptr = global_lock(handle)
            if not ptr:
                raise SelectionError('剪贴板备份无法还原。')
            C.memmove(ptr, data, len(data)); global_unlock(handle)
        with clipboard(hwnd):
            if sequence() != expected:
                return  # Never overwrite a newer clipboard change by another app.
            if not empty_clip():
                raise SelectionError('暂时无法还原剪贴板。')
            for entry in handles:
                if not set_clip(entry[0], entry[1]):
                    raise SelectionError('部分剪贴板格式无法还原。')
                entry[1] = None  # Ownership transferred to Windows.
    finally:
        for _, handle in handles:
            if handle:
                global_free(handle)


class KeyInput(C.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]


class MouseInput(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]


class InputUnion(C.Union):
    _fields_ = [('ki', KeyInput), ('mi', MouseInput)]


class Input(C.Structure):
    _fields_ = [('type', W.DWORD), ('value', InputUnion)]


send_input = api(u, 'SendInput', W.UINT, W.UINT, C.POINTER(Input), C.c_int)


def copy_selection(source_hwnd, owner_hwnd):
    for _ in range(40):
        if not any(key_state(vk) & 0x8000 for vk in (0x10, 0x11, 0x12)):
            break
        time.sleep(.025)
    else:
        raise SelectionError('请松开快捷键后再试。')
    if foreground() != source_hwnd:
        raise SelectionError('当前窗口已经改变，请重新选中文字。')
    backup, before = snapshot_clipboard(owner_hwnd)
    inputs = (Input * 4)()
    for item, vk, flags in zip(inputs, [0x11, 0x43, 0x43, 0x11], [0, 0, 2, 2]):
        item.type = 1; item.value.ki = KeyInput(vk, 0, flags, 0, 0)
    if send_input(4, inputs, C.sizeof(Input)) != 4:
        raise SelectionError('当前软件不允许读取选区。请复制文字后点击“翻译剪贴板”。')
    for _ in range(35):
        if sequence() != before:
            break
        time.sleep(.02)
    else:
        raise SelectionError('没有读到新选区。请先选中文字；也可以复制后点击“翻译剪贴板”。')
    if foreground() != source_hwnd or pid(clip_owner()) != pid(source_hwnd):
        raise SelectionError('剪贴板来源发生变化，已取消翻译，请重试。')
    text = None
    captured = sequence()
    try:
        text, captured = read_clipboard(owner_hwnd, with_sequence=True)
    finally:
        restore_clipboard(owner_hwnd, backup, captured)
    return text


class SelectionReader:
    """Instantiate and use on the same dedicated COM thread."""
    def __init__(self):
        sys.path.insert(0, str(Path(__file__).parent / 'lib'))
        sys.coinit_flags = 0
        import comtypes.client
        self.comtypes = comtypes
        module = comtypes.client.GetModule('UIAutomationCore.dll')
        self.interfaces = module
        self.automation = comtypes.client.CreateObject(module.CUIAutomation, interface=module.IUIAutomation)
        try:
            options = self.automation.QueryInterface(module.IUIAutomation2)
            options.ConnectionTimeout = 1000
            options.TransactionTimeout = 1000
        except comtypes.COMError:
            pass

    def selected_text(self, element):
        """Read only actual selections, never names or whole document content."""
        if element.CurrentIsPassword:
            raise SelectionError('密码输入框不能用于翻译。')
        try:
            pattern = element.GetCurrentPattern(10014).QueryInterface(self.interfaces.IUIAutomationTextPattern)
            ranges = pattern.GetSelection()
            parts, remaining = [], 20001
            for index in range(min(ranges.Length, 64)):
                text = ranges.GetElement(index).GetText(remaining) or ''
                if text:
                    parts.append(text); remaining -= len(text) + 1
                if remaining <= 0:
                    break
            return '\n'.join(parts)
        except self.comtypes.COMError:
            return ''

    def selection(self, hwnd, position=None):
        if not hwnd or foreground() != hwnd:
            return ''
        try:
            focused = self.automation.GetFocusedElement()
            if focused and focused.CurrentIsPassword:
                raise SelectionError('密码输入框不能用于翻译。')
            root = self.automation.ElementFromHandle(hwnd)
            walker = self.automation.RawViewWalker
            starts = []
            if position is not None:
                x, y = position
                hit_hwnd = api(u, 'WindowFromPoint', W.HWND, W.POINT)(W.POINT(x, y))
                if ancestor(hit_hwnd, 2) == hwnd:
                    try:
                        starts.append(self.automation.ElementFromPoint(self.interfaces.tagPOINT(x, y)))
                    except self.comtypes.COMError:
                        pass
            starts.append(focused)
            seen = set()
            deadline = time.monotonic() + 1.25
            for start in starts:
                element = start
                for _ in range(40):
                    if not element or time.monotonic() > deadline or foreground() != hwnd:
                        break
                    if element.CurrentProcessId == os.getpid():
                        break
                    try:
                        key = tuple(element.GetRuntimeId())
                        if key and key in seen:
                            break
                        if key:
                            seen.add(key)
                        text = self.selected_text(element)
                        if text.strip() and foreground() == hwnd:
                            return text
                    except self.comtypes.COMError:
                        pass
                    if self.automation.CompareElements(element, root):
                        break
                    element = walker.GetParentElement(element)
            # Chrome may focus a notebook cell or the outer mail document while
            # the selection belongs to an embedded document. Search documents in
            # this foreground window, including frames and shadow-hosted views.
            if foreground() != hwnd:
                return ''
            condition = self.automation.CreatePropertyCondition(30003, 50030)
            documents = root.FindAll(4, condition)
            for index in range(min(documents.Length, 48)):
                if time.monotonic() > deadline or foreground() != hwnd:
                    return ''
                try:
                    element = documents.GetElement(index)
                    if element.CurrentIsOffscreen:
                        continue
                    text = self.selected_text(element)
                    if text.strip() and foreground() == hwnd:
                        return text
                except self.comtypes.COMError:
                    pass
        except SelectionError:
            raise
        except Exception:
            pass
        return ''


class MouseWatcher:
    """Capture button transitions without polling gaps; never suppress input."""
    def __init__(self, events):
        self.events = events
        self.thread_id = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        class MouseData(C.Structure):
            _fields_ = [('pt', W.POINT), ('mouseData', W.DWORD), ('flags', W.DWORD),
                        ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]
        callback_type = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, W.WPARAM, W.LPARAM)
        next_hook = api(u, 'CallNextHookEx', C.c_ssize_t, W.HANDLE, C.c_int, W.WPARAM, W.LPARAM)
        self.thread_id = api(k, 'GetCurrentThreadId', W.DWORD)()
        # Create the message queue before advertising readiness/allowing close.
        message = W.MSG()
        api(u, 'PeekMessageW', W.BOOL, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT)(C.byref(message), None, 0, 0, 0)
        def callback(code, message_id, address):
            if code >= 0 and message_id in (0x0201, 0x0202):
                data = C.cast(address, C.POINTER(MouseData)).contents
                self.events.put(('mouse', (message_id == 0x0201, foreground(), (data.pt.x, data.pt.y))))
            return next_hook(None, code, message_id, address)
        self.callback = callback_type(callback)
        hook = api(u, 'SetWindowsHookExW', W.HANDLE, C.c_int, callback_type, W.HINSTANCE, W.DWORD)(14, self.callback, None, 0)
        if not hook:
            self.events.put(('mouse_fallback', None)); return
        self.events.put(('mouse_ready', None))
        try:
            get_message = api(u, 'GetMessageW', W.BOOL, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
            while get_message(C.byref(message), None, 0, 0) > 0:
                pass
        finally:
            api(u, 'UnhookWindowsHookEx', W.BOOL, W.HANDLE)(hook)

    def close(self):
        if self.thread_id:
            api(u, 'PostThreadMessageW', W.BOOL, W.DWORD, W.UINT, W.WPARAM, W.LPARAM)(self.thread_id, 0x0012, 0, 0)


class Hotkey:
    def __init__(self, events):
        self.events = events
        self.thread_id = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        self.thread_id = api(k, 'GetCurrentThreadId', W.DWORD)()
        register = api(u, 'RegisterHotKey', W.BOOL, W.HWND, C.c_int, W.UINT, W.UINT)
        unregister = api(u, 'UnregisterHotKey', W.BOOL, W.HWND, C.c_int)
        if not register(None, 1, 0x4000 | 0x0001 | 0x0002, ord('T')):
            self.events.put(('hotkey_error', 'Ctrl+Alt+T 已被其他软件占用；划词按钮仍可使用。'))
            return
        self.events.put(('hotkey_ready', None))
        msg = W.MSG()
        get_message = api(u, 'GetMessageW', W.BOOL, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
        try:
            while get_message(C.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:
                    self.events.put(('hotkey', (foreground(), point())))
        finally:
            unregister(None, 1)

    def close(self):
        if self.thread_id:
            api(u, 'PostThreadMessageW', W.BOOL, W.DWORD, W.UINT, W.WPARAM, W.LPARAM)(self.thread_id, 0x0012, 0, 0)


def round_window(hwnd, width, height, radius):
    """Clip the floating action itself, including its clickable corners."""
    gdi = C.WinDLL('gdi32', use_last_error=True)
    region = api(gdi, 'CreateRoundRectRgn', W.HANDLE, C.c_int, C.c_int,
                 C.c_int, C.c_int, C.c_int, C.c_int)(0, 0, width+1, height+1, radius*2, radius*2)
    if region:
        if not api(u, 'SetWindowRgn', C.c_int, W.HWND, W.HANDLE, W.BOOL)(hwnd, region, True):
            api(gdi, 'DeleteObject', W.BOOL, W.HANDLE)(region)
