from __future__ import annotations

from dotaudio.desktop import Desktop


class _App:
    def installNativeEventFilter(self, _filter) -> None:
        return None

    def removeNativeEventFilter(self, _filter) -> None:
        return None


def test_begin_window_drag_rejects_invalid_hwnd() -> None:
    desktop = Desktop(_App())
    assert desktop.begin_window_drag(0) is False


def test_primary_button_down_safe_without_press() -> None:
    desktop = Desktop(_App())
    assert desktop.primary_button_down() in (True, False)
