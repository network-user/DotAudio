from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from platformdirs import user_data_path
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from dotaudio.assistant_controller import AssistantController
from dotaudio.branding import apply_dark_titlebar, apply_windows_app_identity, load_app_icon
from dotaudio.controller import Controller
from dotaudio.cuda_runtime import register_cuda_dll_directories
from dotaudio.desktop import Desktop
from dotaudio.setup_controller import SetupController


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
    # До импорта/опроса CTranslate2: иначе pip-пакеты nvidia-* не видны.
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    register_cuda_dll_directories()
    parser = argparse.ArgumentParser(description="DotAudio · Whisper workspace")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--smoke-test", action="store_true", help="Load QML, then exit without capturing audio")
    parser.add_argument("--screenshot", type=Path, help="Save a screenshot and exit; no audio capture")
    args = parser.parse_args()
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    # До создания окон: иначе Windows группирует процесс как python.exe.
    apply_windows_app_identity()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("DotAudio")
    app.setApplicationDisplayName("DotAudio")
    app.setOrganizationName("DotCore")
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
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
    data_dir = args.data_dir or user_data_path("DotAudio", "DotCore")
    controller = Controller(data_dir, desktop)
    # Ассистент - отдельный объект с собственным состоянием: поток токенов не
    # должен заставлять интерфейс записи пересчитывать свои привязки.
    assistant = AssistantController(data_dir, controller.store, controller)
    setup = SetupController(data_dir, controller, assistant)

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
    engine.rootContext().setContextProperty("assistant", assistant)
    engine.rootContext().setContextProperty("setup", setup)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "MainMvp.qml")))
    if not engine.rootObjects():
        desktop.close()
        return 1
    window = engine.rootObjects()[0]
    if not app_icon.isNull():
        window.setIcon(app_icon)
    controller.set_window(window)
    # Тёмный системный заголовок под палитру приложения (рамка есть только в app).
    def refresh_titlebar():
        try:
            apply_dark_titlebar(int(window.winId()))
        except (RuntimeError, TypeError, ValueError):
            pass

    QTimer.singleShot(0, refresh_titlebar)
    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable() and not args.smoke_test and not args.screenshot:
        tray = QSystemTrayIcon(app_icon if not app_icon.isNull() else load_app_icon(), app)
        menu = QMenu()
        show_island = menu.addAction("Остров")
        show_app = menu.addAction("Окно")
        menu.addSeparator()
        quit_action = menu.addAction("Выйти")
        def show_island_shell():
            # Трей обходит enterShell: выставляем пару свойств сами.
            window.setProperty("stayOnTop", True)
            window.setProperty("shellMode", "island")

        def show_app_shell():
            window.setProperty("stayOnTop", False)
            window.setProperty("shellMode", "app")
            QTimer.singleShot(0, refresh_titlebar)

        show_island.triggered.connect(show_island_shell)
        show_app.triggered.connect(show_app_shell)
        quit_action.triggered.connect(app.quit)
        tray.setContextMenu(menu)
        tray.setToolTip("DotAudio")
        tray.setIcon(app_icon)
        def on_tray_activated(reason):
            # ЛКМ по иконке возвращает окно, ПКМ оставляет меню.
            if int(reason) == int(QSystemTrayIcon.ActivationReason.Trigger):
                show_app_shell()
                window.show()
                window.raise_()
                window.requestActivate()
        tray.activated.connect(on_tray_activated)
        tray.show()
        window.setProperty("trayPresent", True)
    # По умолчанию - полное окно (навигация + главная страница Live).
    # DOTAUDIO_SHELL=island|theater|app перекрывает для отладки и smoke.
    shell = os.environ.get("DOTAUDIO_SHELL", "app")
    if shell in ("island", "theater", "app"):
        window.setProperty("shellMode", shell)
        window.setProperty("stayOnTop", shell != "app")
        if shell == "app":
            # Центр экрана: до первого кадра QML onCompleted координаты
            # ещё нулевые, поэтому здесь тоже выставляем разумный старт.
            screen = app.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                w = int(window.property("width") or 1220)
                h = int(window.property("height") or 790)
                window.setProperty("x", max(40, (geo.width() - w) // 2 + geo.x()))
                window.setProperty("y", max(40, (geo.height() - h) // 2 + geo.y()))
            QTimer.singleShot(0, refresh_titlebar)
    controller.shutdownReady.connect(app.quit)
    app.aboutToQuit.connect(desktop.close)
    app.aboutToQuit.connect(assistant.shutdown)
    app.aboutToQuit.connect(controller.shutdown)
    # Warm the selected local model after the UI is ready.  Preparation runs in
    # Controller's worker thread and never blocks the Qt event loop.  Smoke
    # tests and screenshots must remain model/network free.  First-run setup
    # takes over downloads when the wizard is still needed.
    if not args.smoke_test and not args.screenshot:
        from dotaudio.process_priority import set_process_priority

        set_process_priority("below_normal")
        if setup.needed:
            QTimer.singleShot(0, setup.begin)
        else:
            controller.enableModelWarmup()
            QTimer.singleShot(0, controller.prepareSelectedModel)
        controller.scheduleStartupUpdateCheck()
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
