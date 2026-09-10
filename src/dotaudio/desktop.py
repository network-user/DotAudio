"""Small Windows integration surface; other desktops keep clipboard fallback."""

import ctypes
import os
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

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_V = 0x56
VK_LWIN = 0x5B
VK_RWIN = 0x5C
KEYEVENTF_KEYUP = 0x0002
_ASYNC_DOWN = 0x8000

_HOTKEY_IDS = {
    "dictate": 41,
    "island": 42,
    "paste_last": 43,
    "quit": 44,
    "cancel": 45,
}
VK_ESCAPE = 0x1B
_REQUIRED_HOTKEYS = {"dictate", "island"}
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

# UIPI: SendInput into a higher-integrity window looks successful but is dropped.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25


def combo_is_held(key_down, hotkey: Hotkey) -> bool:
    """Return True when every modifier and the action key are currently down.

    ``RegisterHotKey`` only reports the press.  Hold-to-talk polls this until
    the user releases the combination.  ``key_down`` takes a virtual-key code.
    """

    if hotkey.modifiers & MOD_CONTROL and not key_down(VK_CONTROL):
        return False
    if hotkey.modifiers & MOD_ALT and not key_down(VK_MENU):
        return False
    if hotkey.modifiers & MOD_SHIFT and not key_down(VK_SHIFT):
        return False
    if hotkey.modifiers & MOD_WIN and not (key_down(VK_LWIN) or key_down(VK_RWIN)):
        return False
    return bool(key_down(hotkey.key))


def hotkey_tokens(hotkey: Hotkey) -> frozenset[str]:
    """Normalized token set for cross-platform matching (ctrl/alt/shift/cmd + key)."""

    parts: set[str] = set()
    if hotkey.modifiers & MOD_CONTROL:
        parts.add("ctrl")
    if hotkey.modifiers & MOD_ALT:
        parts.add("alt")
    if hotkey.modifiers & MOD_SHIFT:
        parts.add("shift")
    if hotkey.modifiers & MOD_WIN:
        parts.add("cmd")
    key = int(hotkey.key)
    if key == 0x20:
        parts.add("space")
    elif key == VK_ESCAPE:
        parts.add("esc")
    elif 0x30 <= key <= 0x39:
        parts.add(chr(key))
    elif 0x41 <= key <= 0x5A:
        parts.add(chr(key).lower())
    else:
        parts.add(f"vk:{key:02x}")
    return frozenset(parts)


def _pynput_key_token(key: object) -> str | None:
    """Map a pynput key object to the same token vocabulary as ``hotkey_tokens``."""

    try:
        from pynput.keyboard import Key, KeyCode
    except ImportError:
        return None
    mapping = {
        Key.ctrl: "ctrl",
        Key.ctrl_l: "ctrl",
        Key.ctrl_r: "ctrl",
        Key.alt: "alt",
        Key.alt_l: "alt",
        Key.alt_r: "alt",
        Key.alt_gr: "alt",
        Key.shift: "shift",
        Key.shift_l: "shift",
        Key.shift_r: "shift",
        Key.cmd: "cmd",
        Key.cmd_l: "cmd",
        Key.cmd_r: "cmd",
        Key.space: "space",
        Key.esc: "esc",
    }
    token = mapping.get(key)  # type: ignore[arg-type]
    if token:
        return token
    if isinstance(key, KeyCode) and key.char and len(key.char) == 1:
        ch = key.char.lower()
        if ch.isalnum():
            return ch
    return None


class _UnixHotkeyListener:
    """Global hotkeys via pynput for Linux/macOS (Wayland may require permissions)."""

    def __init__(self, emit) -> None:
        self._emit = emit
        self._bindings: dict[str, frozenset[str]] = {}
        self._pressed: set[str] = set()
        self._fired: set[str] = set()
        self._listener = None

    @property
    def active(self) -> bool:
        return self._listener is not None

    def set_bindings(self, bindings: Mapping[str, Hotkey]) -> bool:
        self.stop()
        self._bindings = {action: hotkey_tokens(hotkey) for action, hotkey in bindings.items()}
        self._pressed.clear()
        self._fired.clear()
        try:
            from pynput import keyboard
        except ImportError:
            return False
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.daemon = True
            self._listener.start()
        except Exception:
            self._listener = None
            return False
        return True

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
        self._pressed.clear()
        self._fired.clear()

    def combo_held(self, action: str) -> bool:
        needed = self._bindings.get(action)
        return bool(needed and needed <= self._pressed)

    def _on_press(self, key: object) -> None:
        token = _pynput_key_token(key)
        if not token:
            return
        self._pressed.add(token)
        for action, needed in self._bindings.items():
            if action in self._fired:
                continue
            if needed <= self._pressed:
                self._fired.add(action)
                try:
                    self._emit(action)
                except Exception:
                    pass

    def _on_release(self, key: object) -> None:
        token = _pynput_key_token(key)
        if not token:
            return
        self._pressed.discard(token)
        done: list[str] = []
        for action in self._fired:
            needed = self._bindings.get(action) or frozenset()
            if token in needed or not (needed <= self._pressed):
                done.append(action)
        for action in done:
            self._fired.discard(action)


def _token_integrity_level(process_handle) -> int | None:
    """Mandatory integrity level of a process, or None when the query fails."""

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()
    open_token = advapi32.OpenProcessToken
    open_token.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    open_token.restype = wintypes.BOOL
    if not open_token(process_handle, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:

        class _SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

        class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
            _fields_ = [("Label", _SID_AND_ATTRIBUTES)]

        # Extra room: the SID bytes live inside this buffer; Label.Sid points in.
        size = ctypes.sizeof(_TOKEN_MANDATORY_LABEL) + 256
        buffer = ctypes.create_string_buffer(size)
        needed = wintypes.DWORD()
        get_info = advapi32.GetTokenInformation
        get_info.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_info.restype = wintypes.BOOL
        if not get_info(token, TOKEN_INTEGRITY_LEVEL, buffer, size, ctypes.byref(needed)):
            return None
        label = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_MANDATORY_LABEL)).contents
        sid = label.Label.Sid
        if not sid:
            return None
        count_fn = advapi32.GetSidSubAuthorityCount
        count_fn.argtypes = [ctypes.c_void_p]
        count_fn.restype = ctypes.POINTER(ctypes.c_ubyte)
        count_ptr = count_fn(sid)
        if not count_ptr:
            return None
        count = count_ptr.contents.value
        auth_fn = advapi32.GetSidSubAuthority
        auth_fn.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        auth_fn.restype = ctypes.POINTER(wintypes.DWORD)
        level_ptr = auth_fn(sid, count - 1)
        if not level_ptr:
            return None
        # Keep buffer alive until after the SID reads above complete.
        _ = buffer.raw
        return int(level_ptr.contents.value)
    finally:
        kernel32.CloseHandle(token)


def foreground_is_elevated(user32) -> bool:
    """True when the foreground window runs above this process (UIPI).

    Any failure returns False: better a no-op paste than blocking a working one.
    """

    if not user32 or sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        own = _token_integrity_level(kernel32.GetCurrentProcess())
        if own is None:
            return False
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return False
        try:
            target = _token_integrity_level(handle)
            return target is not None and target > own
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError, TypeError):
        return False


class Desktop(QObject, QAbstractNativeEventFilter):
    dictate = Signal()
    island = Signal()
    paste_last = Signal()
    quit_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, app):
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self.app = app
        self.available = False
        self.target = 0
        self.user32 = None
        self._unix = None
        self._registered_hotkeys: dict[str, Hotkey] = {}
        # Ctrl+Alt+X - мгновенный выход без подтверждения. Хранится отдельно,
        # потому что пользователь переопределяет только dictate/island/пасту
        # последнего, а quit обязан пережить это переназначение.
        self._quit_hotkey = Hotkey(MOD_NOREPEAT | MOD_ALT | MOD_CONTROL, 0x58)
        self._cancel_hotkey = Hotkey(MOD_NOREPEAT, VK_ESCAPE)
        # Why the last paste() returned False: "" | "no_target" | "focus" | "elevated" | "sendinput".
        self.last_paste_block = ""
        defaults = {
            "dictate": Hotkey(MOD_NOREPEAT | MOD_ALT | MOD_CONTROL, 0x20),
            "island": Hotkey(MOD_NOREPEAT | MOD_ALT | MOD_CONTROL, 0x4F),
            "paste_last": Hotkey(MOD_NOREPEAT | MOD_SHIFT | MOD_ALT, 0x5A),
            "quit": self._quit_hotkey,
            "cancel": self._cancel_hotkey,
        }
        if sys.platform == "win32":
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._configure_win32_functions()
            app.installNativeEventFilter(self)
            self.available = self.set_hotkeys(defaults)
        else:
            self._unix = _UnixHotkeyListener(self._emit_hotkey_action)
            self.available = self.set_hotkeys(defaults)

    def _emit_hotkey_action(self, action: str) -> None:
        if action == "dictate":
            self.dictate.emit()
        elif action == "island":
            self.island.emit()
        elif action == "paste_last":
            self.paste_last.emit()
        elif action == "quit":
            self.quit_requested.emit()
        elif action == "cancel":
            self.cancel_requested.emit()

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
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = wintypes.SHORT
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.SetForegroundWindow.restype = wintypes.BOOL
        self.user32.ReleaseCapture.argtypes = []
        self.user32.ReleaseCapture.restype = wintypes.BOOL
        self.user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.SendMessageW.restype = wintypes.LPARAM

    def set_hotkeys(self, bindings: Mapping[str, Hotkey]) -> bool:
        """Atomically register the application hotkeys.

        The public API deliberately accepts Win32 virtual-key codes rather
        than strings so callers can validate keyboard-layout-independent
        combinations before saving them.  Either both DotAudio actions are
        active or the last known working pair is restored.
        """

        unknown = set(bindings) - set(_HOTKEY_IDS)
        if unknown:
            raise ValueError(f"Unknown hotkey actions: {sorted(unknown)}")
        if not _REQUIRED_HOTKEYS <= set(bindings):
            raise ValueError("Hotkey bindings must define dictate and island actions")
        if any(not isinstance(hotkey, Hotkey) for hotkey in bindings.values()):
            raise TypeError("Hotkey bindings must contain Hotkey values")
        if "quit" in bindings and isinstance(bindings["quit"], Hotkey):
            # A caller may explicitly set a different emergency shortcut.
            self._quit_hotkey = bindings["quit"]
        # The emergency quit is never dropped when the UI reassigns only the
        # dictate/island/paste-last combos: it is merged back here so a rebind
        # on the hotkeys page cannot silently unregister the exit shortcut.
        merged = dict(bindings)
        merged.setdefault("quit", self._quit_hotkey)
        if "cancel" in bindings and isinstance(bindings["cancel"], Hotkey):
            self._cancel_hotkey = bindings["cancel"]
        merged.setdefault("cancel", self._cancel_hotkey)
        bindings = merged
        if len({(hotkey.modifiers, hotkey.key) for hotkey in bindings.values()}) != len(bindings):
            raise ValueError("DotAudio actions cannot use the same hotkey")
        if self._unix is not None:
            previous = self._registered_hotkeys.copy()
            ok = self._unix.set_bindings(bindings)
            if not ok:
                if previous:
                    self._unix.set_bindings(previous)
                    self._registered_hotkeys = previous
                self.available = bool(previous) and self._unix.active
                return False
            self._registered_hotkeys = dict(bindings)
            self.available = True
            return True
        if not self.user32:
            return False

        previous = self._registered_hotkeys.copy()
        self._unregister_hotkeys()
        for action, hotkey_id in _HOTKEY_IDS.items():
            hotkey = bindings.get(action)
            if hotkey is None:
                continue
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
                elif msg.wParam == 43:
                    self.paste_last.emit()
                elif msg.wParam == 44:
                    self.quit_requested.emit()
                elif msg.wParam == 45:
                    self.cancel_requested.emit()
        return False, 0

    def remember_target(self):
        self.target = 0
        if self.user32:
            window = self.user32.GetForegroundWindow()
            if window and not self._is_current_process(window):
                self.target = window
            return
        # Non-Windows: mark that a best-effort paste into the focused app is OK.
        if self._unix is not None:
            self.target = 1

    def combo_held(self, action: str = "dictate") -> bool:
        """True while the registered combination for ``action`` is still down."""

        hotkey = self._registered_hotkeys.get(action)
        if hotkey is None:
            return False
        if self._unix is not None:
            return self._unix.combo_held(action)
        if not self.user32:
            return False
        return combo_is_held(
            lambda vk: bool(self.user32.GetAsyncKeyState(vk) & _ASYNC_DOWN),
            hotkey,
        )

    def _is_current_process(self, window) -> bool:
        if not self.user32 or not window:
            return False
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        return int(pid.value) == os.getpid()

    def paste(self):
        self.last_paste_block = ""
        if self.user32:
            return self._paste_win32()
        if not self.target:
            self.last_paste_block = "no_target"
            return False
        if self._paste_unix():
            return True
        self.last_paste_block = "sendinput"
        return False

    def _paste_win32(self) -> bool:
        if not self.user32 or not self.target or not self.user32.IsWindow(self.target):
            self.last_paste_block = "no_target"
            return False
        foreground = self.user32.GetForegroundWindow()
        if foreground != self.target:
            # The island is our window.  If it stole focus, return it to the
            # remembered target.  If the user switched to another app, do not paste.
            if not self._is_current_process(foreground):
                self.last_paste_block = "focus"
                return False
            if not self.user32.SetForegroundWindow(self.target):
                self.last_paste_block = "focus"
                return False
            if self.user32.GetForegroundWindow() != self.target:
                self.last_paste_block = "focus"
                return False
        if foreground_is_elevated(self.user32):
            # UIPI silently drops synthetic input into elevated windows.
            self.last_paste_block = "elevated"
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
        self.last_paste_block = "sendinput"
        return False

    def _paste_unix(self) -> bool:
        """Best-effort Cmd/Ctrl+V. Clipboard is already filled by the controller."""

        import shutil
        import subprocess

        try:
            if sys.platform == "darwin":
                proc = subprocess.run(
                    [
                        "osascript",
                        "-e",
                        'tell application "System Events" to keystroke "v" using command down',
                    ],
                    capture_output=True,
                    timeout=5.0,
                    check=False,
                )
                return proc.returncode == 0
            if sys.platform.startswith("linux"):
                if shutil.which("xdotool"):
                    proc = subprocess.run(
                        ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                        capture_output=True,
                        timeout=5.0,
                        check=False,
                    )
                    return proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
        return False

    @staticmethod
    def _keyboard_input(key: int, flags: int = 0) -> _INPUT:
        return _INPUT(type=INPUT_KEYBOARD, ki=_KEYBDINPUT(key, 0, flags, 0, 0))

    def primary_button_down(self) -> bool:
        if not self.user32:
            return False
        try:
            return bool(self.user32.GetAsyncKeyState(0x01) & _ASYNC_DOWN)
        except (OSError, AttributeError):
            return False

    def begin_window_drag(self, window_id: int) -> bool:
        """Hand the drag to Windows (HTCAPTION). Blocks until the mouse is released.

        Moving a frameless HWND from QML each mouse event fights DWM and looks
        stuttery.  The caption-drag message lets the compositor own the move.
        """

        if not self.user32 or not window_id:
            return False
        try:
            hwnd = wintypes.HWND(int(window_id))
            self.user32.ReleaseCapture()
            # WM_NCLBUTTONDOWN + HTCAPTION: the system move loop until button up.
            self.user32.SendMessageW(hwnd, 0x00A1, 2, 0)
            return True
        except (OSError, ValueError, TypeError, OverflowError):
            return False

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
        if self._unix is not None:
            self._unix.stop()
        if self.user32:
            self._unregister_hotkeys()
            self.app.removeNativeEventFilter(self)
