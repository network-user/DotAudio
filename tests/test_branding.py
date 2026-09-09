from __future__ import annotations

import sys

from PySide6.QtGui import QGuiApplication

from dotaudio.branding import APP_ICON_ICO, APP_ICON_PNG, APP_USER_MODEL_ID, assets_dir, load_app_icon


def test_packaged_icon_files_exist() -> None:
    assert assets_dir().is_dir()
    assert APP_ICON_ICO.is_file()
    assert APP_ICON_PNG.is_file()
    assert APP_ICON_ICO.stat().st_size > 1000


def test_load_app_icon_is_usable() -> None:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    icon = load_app_icon()
    assert not icon.isNull()
    assert icon.availableSizes()
    assert APP_USER_MODEL_ID.startswith("DotCore.")
    assert app is not None
