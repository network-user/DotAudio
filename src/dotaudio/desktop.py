"""Small Windows integration surface; other desktops keep clipboard fallback."""

import ctypes
import sys
from collections.abc import Mapping
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002

_HOTKEY_IDS = {"dictate": 41, "island": 42}
_ALLOWED_MODIFIERS = MOD_ALT | MOD_CONTROL | MOD_SHIFT | MOD_WIN | MOD_NOREPEAT


@dataclass(frozen=True)
class Hotkey:
    """A validated Win32 global-hotkey combination.

    ``key`` is a Windows virtual-key code.  ``modifiers`` accepts only the
    modifier flags supported by ``RegisterHotKey`` plus ``MOD_NOREPEAT``.
    """

    modifiers: int
    key: int

    def __post_init__(self) -> None:
        if self.modifiers & ~_ALLOWED_MODIFIERS:
            raise ValueError("Unsupported hotkey modifier")
        if not 1 <= self.key <= 0xFF:
            raise ValueError("Hotkey virtual-key code must be between 1 and 255")


_ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


INPUT_KEYBOARD = 1


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
        self._registered_hotkeys: dict[str, Hotkey] = {}
        if sys.platform == "win32":
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._configure_win32_functions()
            app.installNativeEventFilter(self)
            self.available = self.set_hotkeys(
                {
                    "dictate": Hotkey(MOD_NOREPEAT | MOD_ALT | MOD_CONTROL, 0x20),
                    "island": Hotkey(MOD_NOREPEAT | MOD_ALT | MOD_CONTROL, 0x4F),
                }
            )

    def _configure_win32_functions(self) -> None:
        """Declare every Win32 call used here to avoid pointer-size truncation."""

        assert self.user32 is not None
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsWindow.restype = wintypes.BOOL
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user32.RegisterHotKey.restype = wintypes.BOOL
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.UnregisterHotKey.restype = wintypes.BOOL
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT

    def set_hotkeys(self, bindings: Mapping[str, Hotkey]) -> bool:
        """Atomically register the application hotkeys.

        The public API deliberately accepts Win32 virtual-key codes rather
        than strings so callers can validate keyboard-layout-independent
        combinations before saving them.  Either both DotAudio actions are
        active or the last known working pair is restored.
        """

        if set(bindings) != set(_HOTKEY_IDS):
            raise ValueError("Hotkey bindings must define dictate and island actions")
        if any(not isinstance(hotkey, Hotkey) for hotkey in bindings.values()):
            raise TypeError("Hotkey bindings must contain Hotkey values")
        if len({(hotkey.modifiers, hotkey.key) for hotkey in bindings.values()}) != len(bindings):
            raise ValueError("DotAudio actions cannot use the same hotkey")
        if not self.user32:
            return False

        previous = self._registered_hotkeys.copy()
        self._unregister_hotkeys()
        for action, hotkey_id in _HOTKEY_IDS.items():
            hotkey = bindings[action]
            if not self.user32.RegisterHotKey(None, hotkey_id, hotkey.modifiers, hotkey.key):
                self._unregister_hotkeys()
                self.available = self._register_hotkeys(previous)
                return False
            self._registered_hotkeys[action] = hotkey
        self.available = True
        return True

    def _register_hotkeys(self, bindings: Mapping[str, Hotkey]) -> bool:
        """Best-effort restore used only after an unsuccessful replacement."""

        assert self.user32 is not None
        for action, hotkey_id in _HOTKEY_IDS.items():
            hotkey = bindings.get(action)
            if hotkey and self.user32.RegisterHotKey(None, hotkey_id, hotkey.modifiers, hotkey.key):
                self._registered_hotkeys[action] = hotkey
            elif hotkey:
                self._unregister_hotkeys()
                return False
        return bool(bindings)

    def _unregister_hotkeys(self) -> None:
        if not self.user32:
            return
        for action, hotkey_id in _HOTKEY_IDS.items():
            if action in self._registered_hotkeys:
                self.user32.UnregisterHotKey(None, hotkey_id)
        self._registered_hotkeys.clear()

    def nativeEventFilter(self, event_type, message):
        event_name = event_type.encode() if isinstance(event_type, str) else bytes(event_type)
        if self.user32 and event_name in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
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
        inputs = (_INPUT * 4)(
            self._keyboard_input(VK_CONTROL),
            self._keyboard_input(VK_V),
            self._keyboard_input(VK_V, KEYEVENTF_KEYUP),
            self._keyboard_input(VK_CONTROL, KEYEVENTF_KEYUP),
        )
        sent = int(self.user32.SendInput(len(inputs), inputs, ctypes.sizeof(_INPUT)))
        if sent == len(inputs):
            return True
        # A partial SendInput can leave Ctrl down.  Key-up events are harmless
        # in another window, unlike a second Ctrl+V attempt, and prevent that
        # stuck modifier state without ever inserting or submitting text.
        if sent:
            release = (_INPUT * 2)(
                self._keyboard_input(VK_V, KEYEVENTF_KEYUP),
                self._keyboard_input(VK_CONTROL, KEYEVENTF_KEYUP),
            )
            self.user32.SendInput(len(release), release, ctypes.sizeof(_INPUT))
        return False

    @staticmethod
    def _keyboard_input(key: int, flags: int = 0) -> _INPUT:
        return _INPUT(type=INPUT_KEYBOARD, ki=_KEYBDINPUT(key, 0, flags, 0, 0))

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
            self._unregister_hotkeys()
            self.app.removeNativeEventFilter(self)
