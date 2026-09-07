from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from platformdirs import user_data_path
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from dotaudio.controller import Controller
from dotaudio.desktop import Desktop


def _register_ui_fonts():
    """Load Segoe UI from Windows so offscreen and custom Qt plugins can render text."""
    font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if not font_dir.is_dir():
        return
    for name in ("segoeui.ttf", "segoeuib.ttf", "segoeuil.ttf", "segoeuiz.ttf", "segoeuisl.ttf", "consola.ttf"):
        path = font_dir / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))


def main():
    parser = argparse.ArgumentParser(description="DotAudio · Whisper workspace")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--smoke-test", action="store_true", help="Load QML, then exit without capturing audio")
    parser.add_argument("--screenshot", type=Path, help="Save a screenshot and exit; no audio capture")
    args = parser.parse_args()
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("DotAudio")
    app.setOrganizationName("DotCore")
    _register_ui_fonts()
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    for role, color in ((QPalette.Window, "#111214"), (QPalette.WindowText, "#eeeeef"),
                        (QPalette.Base, "#1b1c20"), (QPalette.Text, "#eeeeef"),
                        (QPalette.Button, "#25262b"), (QPalette.ButtonText, "#eeeeef"),
                        (QPalette.Highlight, "#d9dde5"), (QPalette.HighlightedText, "#111214")):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    desktop = Desktop(app)
    controller = Controller(args.data_dir or user_data_path("DotAudio", "DotCore"), desktop)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bridge", controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "MainMvp.qml")))
    if not engine.rootObjects():
        desktop.close()
        return 1
    window = engine.rootObjects()[0]
    controller.set_window(window)
    shell = os.environ.get("DOTAUDIO_SHELL", "")
    if shell in ("island", "theater", "app"):
        window.setProperty("shellMode", shell)
    controller.shutdownReady.connect(app.quit)
    app.aboutToQuit.connect(desktop.close)
    app.aboutToQuit.connect(controller.shutdown)
    if args.smoke_test or args.screenshot:
        def finish():
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                window = engine.rootObjects()[0]
                screenshot = window.screen().grabWindow(window.winId())
                if not screenshot.save(str(args.screenshot)):
                    app.exit(2)
                    return
            app.quit()
        QTimer.singleShot(1800, finish)
    return app.exec()
