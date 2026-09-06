from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from platformdirs import user_data_path
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from dotaudio.controller import Controller
from dotaudio.desktop import Desktop


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
    controller.set_window(engine.rootObjects()[0])
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
