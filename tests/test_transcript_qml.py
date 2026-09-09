"""Страница транскрибации: загрузка, раскладка и прокрутка списка фраз."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMetaObject,
    QObject,
    Qt,
    QtMsgType,
    QUrl,
    Signal,
    qInstallMessageHandler,
)
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickView

from dotaudio.controller import Controller

QML_DIR = Path(__file__).resolve().parents[1] / "src" / "dotaudio" / "qml"

PHRASES = [
    {
        "start": float(i * 4),
        "end": float(i * 4 + 3.4),
        "text": f"Фраза {i + 1}. Длинный текст, чтобы карточка заняла больше одной строки.",
        "speaker": "Голос 1" if i % 2 == 0 else "Голос 2",
        "role": 1 if i % 2 == 0 else 2,
    }
    for i in range(18)
]


class _Desktop(QObject):
    dictate = Signal()
    island = Signal()
    paste_last = Signal()
    quit_requested = Signal()
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.available = False

    def set_hotkeys(self, _bindings):
        return True


@pytest.fixture(scope="module")
def gui():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
    controller = Controller(tmp_path, _Desktop())
    controller._trans_state.update(
        {
            "phase": "done",
            "file": "meeting.wav",
            "path": "",
            "segments": list(PHRASES),
            "speakers": [
                {"key": 1, "label": "Голос 1", "count": 9, "seconds": 30},
                {"key": 2, "label": "Голос 2", "count": 9, "seconds": 30},
            ],
            "duration": 72.0,
            "progress": 1.0,
        }
    )
    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(900, 640)
    view.rootContext().setContextProperty("bridge", controller)
    view.setSource(QUrl.fromLocalFile(str(QML_DIR / "TranscriptView.qml")))
    assert view.status() == QQuickView.Ready, [error.toString() for error in view.errors()]
    view.show()
    settle()
    yield view.rootObject(), controller
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def settle() -> None:
    for _ in range(8):
        QCoreApplication.processEvents()


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


def test_page_loads_without_binding_errors(page, warnings) -> None:
    root, _controller = page
    assert find(root, "segmentList") is not None
    assert find(root, "transcriptHead") is not None
    assert find(root, "phrasePane") is not None
    assert_clean(warnings)


def test_head_and_list_do_not_overlap(page, warnings) -> None:
    root, _controller = page
    head = find(root, "transcriptHead")
    pane = find(root, "phrasePane")
    assert head is not None and pane is not None
    assert pane.y() >= head.y() + head.height() - 1
    assert pane.height() >= 160
    assert_clean(warnings)


def test_phrase_list_scrolls_to_the_last_card(page, warnings) -> None:
    root, _controller = page
    lst = find(root, "segmentList")
    assert lst is not None
    assert lst.property("count") == 18
    assert lst.property("visible") is True
    content_h = float(lst.property("contentHeight") or 0)
    height = float(lst.property("height") or 0)
    assert height >= 140
    assert content_h > height + 40
    QMetaObject.invokeMethod(lst, "positionViewAtEnd", Qt.ConnectionType.DirectConnection)
    settle()
    content_h = float(lst.property("contentHeight") or 0)
    height = float(lst.property("height") or 0)
    leftover = content_h - float(lst.property("contentY") or 0) - height
    assert leftover <= 24
    assert_clean(warnings)
