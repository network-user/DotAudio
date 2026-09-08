"""Страница «Ассистент» в настоящем Qt Quick, без модели и без сети.

Главное, что здесь проверяется: каждая привязка страницы находит своё
свойство у контроллера. Опечатка в имени свойства не ломает загрузку QML -
она превращается в тихое предупреждение и пустое место в интерфейсе,
поэтому предупреждения тут считаются ошибкой.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QtMsgType,
    QUrl,
    qInstallMessageHandler,
)
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickView

from dotaudio.assistant_controller import AssistantController
from dotaudio.controller import DEFAULTS
from dotaudio.storage import Store

QML_DIR = Path(__file__).resolve().parents[1] / "src" / "dotaudio" / "qml"

SPEECH = [
    {"start": 0.0, "end": 11.0, "text": "Добрый день, начнём с бюджета."},
    {"start": 12.0, "end": 23.0, "text": "Смета выросла до трёх миллионов."},
    {"start": 24.0, "end": 35.0, "text": "Сроки сдвигаются на две недели."},
]


class _StubController:
    def __init__(self) -> None:
        self.values = dict(DEFAULTS)

    def setting(self, name, default=None):
        return self.values.get(name, default)

    def setSetting(self, name, value):  # noqa: N802 - имя как в Qt-слоте
        self.values[name] = value


@pytest.fixture(scope="module")
def gui():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Плагин offscreen не приносит своих шрифтов: без системных подбор глифов
    # идёт долго, а элементы управления рисуются пустыми.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QGuiApplication.instance() or QGuiApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "segoeuisl.ttf", "consola.ttf"):
        path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    yield app


@pytest.fixture
def warnings():
    collected: list[str] = []

    def handler(mode, _context, message):
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            collected.append(str(message))

    previous = qInstallMessageHandler(handler)
    yield collected
    qInstallMessageHandler(previous)


@pytest.fixture
def page(gui, tmp_path, warnings):
    store = Store(tmp_path / "dotaudio.sqlite3")
    session = store.create_session("Планёрка", "live", "system", "small")
    store.append_segments(session, SPEECH)
    assistant = AssistantController(tmp_path, store, _StubController())
    # Список записей приходит из воркера; для проверки вёрстки он подставляется,
    # чтобы тест не зависел от гонки с потоком.
    assistant._on_records(
        [{"id": session, "title": "Планёрка", "mode": "live", "createdAt": "", "segments": 3, "preview": "Смета"}]
    )

    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1100, 700)
    view.rootContext().setContextProperty("assistant", assistant)
    view.setSource(QUrl.fromLocalFile(str(QML_DIR / "AssistantPage.qml")))
    assert view.status() == QQuickView.Ready, [error.toString() for error in view.errors()]
    view.show()
    settle()
    yield view.rootObject(), assistant, session
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def settle() -> None:
    for _ in range(6):
        QCoreApplication.processEvents()


def wait_until(predicate, attempts: int = 80) -> None:
    import time

    for _ in range(attempts):
        if predicate():
            return
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert predicate()


def find(root, name):
    return root.findChild(QObject, name)


def assert_clean(collected) -> None:
    broken = [
        line
        for line in collected
        if any(
            marker in line
            for marker in (
                "ReferenceError",
                "TypeError",
                "is not a function",
                "Unable to assign",
                "Cannot assign",
                "Binding loop",
            )
        )
    ]
    assert broken == []


def test_page_binds_every_property_it_reads(page, warnings) -> None:
    root, _assistant, _session = page

    assert find(root, "assistantChat") is not None
    assert find(root, "recordList") is not None
    assert find(root, "assistantInput") is not None
    assert_clean(warnings)


def test_record_selection_shows_the_ready_made_actions(page, warnings) -> None:
    root, assistant, session = page
    actions = find(root, "assistantActions")

    # Готовые действия работают по записи, поэтому в свободном чате их нет.
    assistant.selectRecord("")
    wait_until(lambda: assistant.status == "Свободный разговор без записи")
    assert actions.property("visible") is False

    assistant.selectRecord(session)
    wait_until(lambda: assistant.recordId == session)
    assert actions.property("visible") is True
    assert_clean(warnings)


def test_conversation_grows_with_the_answer(page, warnings) -> None:
    root, assistant, _session = page
    chat = find(root, "assistantChat")

    assistant._messages = [
        {"role": "user", "content": "Что со сметой?", "pending": False},
        {"role": "assistant", "content": "Выросла до 3 млн [00:12].", "pending": False},
    ]
    assistant.messagesChanged.emit()
    settle()

    assert chat.property("count") == 2
    assert chat.property("visible") is True
    assert_clean(warnings)


def test_model_catalog_opens_over_the_page(page, warnings) -> None:
    root, assistant, _session = page
    loader = find(root, "assistantModels")

    assert loader is not None
    assert loader.property("active") is False
    root.setProperty("catalogOpen", True)
    wait_until(lambda: bool(loader.property("active")))
    assistant._on_catalog({"cards": [], "recommended": "qwen3-4b"})
    settle()

    assert loader.property("visible") is True
    assert_clean(warnings)
