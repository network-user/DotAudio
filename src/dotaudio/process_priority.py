"""Lower Windows process priority while the app is idle."""

from __future__ import annotations

import ctypes
import sys

# Win32 priority classes
_NORMAL = 0x00000020
_BELOW_NORMAL = 0x00004000

_current = "normal"


def set_process_priority(level: str) -> bool:
    """level: 'normal' | 'below_normal'. No-op on non-Windows."""

    global _current
    if sys.platform != "win32":
        return False
    wanted = str(level or "normal").lower()
    if wanted in {"below", "below_normal", "low"}:
        value = _BELOW_NORMAL
        label = "below_normal"
    else:
        value = _NORMAL
        label = "normal"
    if label == _current:
        return True
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = bool(ctypes.windll.kernel32.SetPriorityClass(handle, value))
    except (AttributeError, OSError):
        return False
    if ok:
        _current = label
    return ok


def current_priority() -> str:
    return _current


__all__ = ["current_priority", "set_process_priority"]
