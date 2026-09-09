"""Application identity for Windows: icon, taskbar id, dark title bar."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtGui import QIcon

ASSETS = Path(__file__).resolve().parent / "assets"
APP_ICON_ICO = ASSETS / "app_icon.ico"
APP_ICON_PNG = ASSETS / "app_icon.png"
# Stable id so the taskbar groups DotAudio instead of python.exe.
APP_USER_MODEL_ID = "DotCore.DotAudio"


def assets_dir() -> Path:
    return ASSETS


def load_app_icon() -> QIcon:
    """Load the packaged multi-size icon; empty icon if assets are missing."""
    if APP_ICON_ICO.is_file():
        return QIcon(str(APP_ICON_ICO))
    if APP_ICON_PNG.is_file():
        return QIcon(str(APP_ICON_PNG))
    return QIcon()


def apply_windows_app_identity() -> None:
    """Tell Windows this process is DotAudio, not a generic Python host."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def apply_dark_titlebar(window_id: int) -> bool:
    """Match the native caption bar to the dark app chrome on Windows 10/11."""
    if sys.platform != "win32" or not window_id:
        return False
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 on 20H1+, 19 on older builds.
        value = ctypes.c_int(1)
        hwnd = wintypes_hwnd(window_id)
        for attr in (20, 19):
            hr = dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
            if hr == 0:
                return True
    except (AttributeError, OSError, ValueError, TypeError):
        return False
    return False


def wintypes_hwnd(window_id: int):
    from ctypes import wintypes

    return wintypes.HWND(int(window_id))
