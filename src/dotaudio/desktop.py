"""Small Windows integration surface; other desktops keep clipboard fallback."""

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal


class Desktop(QObject, QAbstractNativeEventFilter):
    dictate = Signal()
    island = Signal()

    def __init__(self, app):
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self.app = app
        self.available = False
        self.target = 0
        self.user32 = None
        if sys.platform == "win32":
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.user32.GetForegroundWindow.restype = wintypes.HWND
            self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            self.user32.IsWindow.argtypes = [wintypes.HWND]
            self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            app.installNativeEventFilter(self)
            self.available = bool(self.user32.RegisterHotKey(None, 41, 0x4000 | 0x0001 | 0x0002, 0x20))
            self.user32.RegisterHotKey(None, 42, 0x4000 | 0x0001 | 0x0002, 0x4F)

    def nativeEventFilter(self, event_type, message):
        if self.user32 and bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312:
                if msg.wParam == 41:
                    self.dictate.emit()
                elif msg.wParam == 42:
                    self.island.emit()
        return False, 0

    def remember_target(self):
        self.target = 0
        if self.user32:
            window = self.user32.GetForegroundWindow()
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
            import os
            if pid.value != os.getpid():
                self.target = window

    def paste(self):
        if not self.user32 or not self.target or not self.user32.IsWindow(self.target):
            return False
        if self.user32.GetForegroundWindow() != self.target:
            return False
        # Called after the shortcut modifiers are released; no Enter is ever sent.
        self.user32.keybd_event(0x11, 0, 0, 0)
        self.user32.keybd_event(0x56, 0, 0, 0)
        self.user32.keybd_event(0x56, 0, 2, 0)
        self.user32.keybd_event(0x11, 0, 2, 0)
        return True

    def set_click_through(self, window_id: int, enabled: bool) -> bool:
        """Let a transparent island pass mouse input through on Windows.

        The option changes only the extended window style.  It never installs
        a global mouse hook and it is turned off when the full workspace opens.
        """

        if not self.user32 or not window_id:
            return False
        get_style = self.user32.GetWindowLongPtrW
        set_style = self.user32.SetWindowLongPtrW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t
        style_index = -20  # GWL_EXSTYLE
        transparent = 0x00000020  # WS_EX_TRANSPARENT
        window = wintypes.HWND(window_id)
        style = int(get_style(window, style_index))
        desired = style | transparent if enabled else style & ~transparent
        if desired != style:
            set_style(window, style_index, desired)
        return True

    def close(self):
        if self.user32:
            self.user32.UnregisterHotKey(None, 41)
            self.user32.UnregisterHotKey(None, 42)
            self.app.removeNativeEventFilter(self)
