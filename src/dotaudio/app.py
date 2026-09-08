from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from platformdirs import user_data_path
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from dotaudio.controller import Controller
from dotaudio.desktop import Desktop


def _tray_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#0a0b0d"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#f3f3f1"), 2))
    painter.drawRoundedRect(6, 8, 20, 16, 4, 4)
    painter.end()
    return QIcon(pixmap)


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

    # Экстренный выход. Ctrl+C / Ctrl+Break в консоли запуска (python -m
    # dotaudio, dotaudio.exe) и глобальная Ctrl+Alt+X обязаны закрыть программу
    # целиком, даже если модель занята распознаванием. Полный выход сразу:
    # останавливаем захват/декодер через controller.abortEmergency, а если за
    # grace-интервал нативный compute не вернул управление - процесс всё равно
    # завершается (workers - daemon threads, они умирают вместе с процессом).
    aborted = {"once": False}

    def force_exit():
        os._exit(0)

    def finish_abort():
        if aborted["once"]:
            force_exit()
            return
        aborted["once"] = True
        try:
            controller.abortEmergency()
        except Exception:
            pass
        app.quit()
        # Qt app.quit() завершает цикл, но native decode в демон-потоке может
        # не отпустить GIL быстро. Даём короткую паузу и закрываемся жёстко.
        QTimer.singleShot(2500, force_exit)

    def request_abort(*_unused):
        # Сигнал приходит на границе интерпретатора, ещё во время Qt-цикла.
        # Не трогаем QML прямо из обработчика: прокладываем в event loop через
        # singleShot, а heartbeat ниже будит цикл, если приложение молчит.
        QTimer.singleShot(0, finish_abort)

    if not args.smoke_test and not args.screenshot:
        # Ctrl+C (SIGINT) и Ctrl+Break (SIGBREAK) в консоли.
        signal.signal(signal.SIGINT, request_abort)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, request_abort)

    # Heartbeat Qt-сообщениями: пока нативный Qt-цикл ждёт события, обработчик
    # SIGINT добирается до Python только когда исполняется байткод. Лёгкий таймер
    # с интервалом ~250 мс гарантирует, что сигнал доставят в течение долей секунды.
    heartbeat = QTimer()
    heartbeat.setInterval(250)
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start()

    desktop.quit_requested.connect(finish_abort)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bridge", controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "MainMvp.qml")))
    if not engine.rootObjects():
        desktop.close()
        return 1
    window = engine.rootObjects()[0]
    controller.set_window(window)
    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable() and not args.smoke_test and not args.screenshot:
        tray = QSystemTrayIcon(_tray_icon(), app)
        menu = QMenu()
        show_island = menu.addAction("Остров")
        show_app = menu.addAction("Окно")
        menu.addSeparator()
        quit_action = menu.addAction("Выйти")
        show_island.triggered.connect(lambda: window.setProperty("shellMode", "island"))
        show_app.triggered.connect(lambda: window.setProperty("shellMode", "app"))
        quit_action.triggered.connect(app.quit)
        tray.setContextMenu(menu)
        tray.setToolTip("DotAudio")
        tray.show()
        window.setProperty("trayPresent", True)
    shell = os.environ.get("DOTAUDIO_SHELL", "")
    if shell in ("island", "theater", "app"):
        window.setProperty("shellMode", shell)
    controller.shutdownReady.connect(app.quit)
    app.aboutToQuit.connect(desktop.close)
    app.aboutToQuit.connect(controller.shutdown)
    # Warm the selected local model after the UI is ready.  Preparation runs in
    # Controller's worker thread and never blocks the Qt event loop.  Smoke
    # tests and screenshots must remain model/network free.
    if not args.smoke_test and not args.screenshot:
        QTimer.singleShot(0, controller.prepareSelectedModel)
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
