from dotaudio.desktop import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_WIN,
    Hotkey,
    combo_is_held,
)


def test_combo_is_held_requires_every_modifier_and_the_key() -> None:
    hotkey = Hotkey(MOD_CONTROL | MOD_ALT, 0x20)
    down = {0x11, 0x12, 0x20}
    assert combo_is_held(down.__contains__, hotkey) is True
    assert combo_is_held({0x11, 0x20}.__contains__, hotkey) is False
    assert combo_is_held({0x11, 0x12}.__contains__, hotkey) is False


def test_combo_is_held_accepts_either_windows_key() -> None:
    hotkey = Hotkey(MOD_CONTROL | MOD_WIN, 0x20)
    assert combo_is_held({0x11, 0x5B, 0x20}.__contains__, hotkey) is True
    assert combo_is_held({0x11, 0x5C, 0x20}.__contains__, hotkey) is True
    assert combo_is_held({0x11, 0x20}.__contains__, hotkey) is False
