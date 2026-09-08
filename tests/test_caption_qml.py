"""Real Qt Quick regressions, without a microphone or an ASR model."""

import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest

from dotaudio.controller import Controller

QML_DIR = Path(__file__).resolve().parents[1] / "src" / "dotaudio" / "qml"


@pytest.fixture(scope="module")
def gui():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


@pytest.fixture
def caption(gui):
    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(560, 160)
    view.setSource(QUrl.fromLocalFile(str(QML_DIR / "CaptionText.qml")))
    assert view.status() == QQuickView.Ready, [error.toString() for error in view.errors()]
    view.show()
    root = view.rootObject()
    yield root
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def settle():
    # callLater(sync) schedules callLater(relayout) in the following event turn.
    for _ in range(3):
        QCoreApplication.processEvents()


def words(root):
    # Repeater delegates have visual parents, but QObject ownership belongs
    # to the model context and is not necessarily below the visual root.
    found = []
    for child in root.childItems():
        if child.objectName() == "captionWord":
            found.append(child)
        else:
            found.extend(words(child))
    return found


def test_confirmation_keeps_words_and_metrics(caption):
    caption.setProperty("confirmed", "Сегодня")
    caption.setProperty("pending", "прекрасная погода")
    settle()
    QTest.qWait(180)
    before = words(caption)
    assert [word.property("text") for word in before] == ["Сегодня", "прекрасная", "погода"]
    positions = [(word.property("x"), word.property("y")) for word in before]
    widths = [word.property("implicitWidth") for word in before]

    # These two binding updates happen together on the same controller signal.
    caption.setProperty("confirmed", "Сегодня прекрасная")
    caption.setProperty("pending", "погода")
    settle()
    after = words(caption)
    assert after == before
    assert [word.property("implicitWidth") for word in after] == widths
    assert [(word.property("x"), word.property("y")) for word in after] == positions
    assert all(word.property("enter") == 1 for word in after)
    assert [word.property("soft") for word in after] == [False, False, True]


def test_punctuation_and_append_preserve_existing_words(caption):
    caption.setProperty("pending", "привет мир")
    settle()
    QTest.qWait(180)
    before = words(caption)
    caption.setProperty("confirmed", "Привет, мир!")
    caption.setProperty("pending", "Как дела?")
    settle()
    after = words(caption)
    assert after[:2] == before
    assert [word.property("text") for word in after] == ["Привет,", "мир!", "Как", "дела?"]
    assert all(word.property("enter") == 1 for word in before)
    assert all(word.property("scale") == 1 for word in after)
    QTest.qWait(180)
    assert all(word.property("enter") == 1 for word in after)


def test_rewritten_draft_reuses_words_instead_of_flashing_the_line(caption):
    # Music-style drafts share nothing with the previous one. Rebuilding the
    # delegates re-played the entrance for every word on every update.
    caption.setProperty("pending", "раз два три четыре")
    settle()
    QTest.qWait(200)
    before = words(caption)
    assert [word.property("text") for word in before] == ["раз", "два", "три", "четыре"]

    caption.setProperty("pending", "пять шесть семь")
    settle()
    after = words(caption)
    assert after == before[:3]
    assert [word.property("text") for word in after] == ["пять", "шесть", "семь"]
    assert all(word.property("enter") == 1 for word in after)

    caption.setProperty("pending", "пять шесть семь восемь девять")
    settle()
    grown = words(caption)
    assert grown[:3] == after
    assert [word.property("text") for word in grown[3:]] == ["восемь", "девять"]
    QTest.qWait(200)
    assert all(word.property("enter") == 1 for word in grown)


def test_confirmed_words_keep_positions_while_the_tail_rewrites(caption):
    caption.setProperty("width", 420)
    caption.setProperty("maxLines", 3)
    caption.setProperty("confirmed", "первые слова стоят")
    caption.setProperty("pending", "на месте твёрдо")
    settle()
    QTest.qWait(200)
    before = words(caption)
    assert [word.property("soft") for word in before[:3]] == [False] * 3
    anchors = [(word.property("x"), word.property("y")) for word in before[:3]]

    caption.setProperty("pending", "совсем другой текст")
    settle()
    after = words(caption)
    assert [(word.property("x"), word.property("y")) for word in after[:3]] == anchors


def test_large_confirmation_arrives_word_by_word(caption):
    caption.setProperty("pending", " ".join(f"слово{i}" for i in range(8)))
    settle()
    QTest.qWait(200)
    caption.setProperty("confirmed", " ".join(f"слово{i}" for i in range(8)))
    caption.setProperty("pending", "")
    settle()
    # Волна стартует с первым тиком таймера: в кадре после синхронизации
    # слова ещё приглушены.
    assert all(word.property("soft") for word in words(caption))
    QTest.qWait(120)
    middle = [word for word in words(caption) if word.property("soft")]
    assert 0 < len(middle) < 8
    QTest.qWait(1000)
    assert all(not word.property("soft") for word in words(caption))


def test_wrapping_reserves_height_and_displays_only_last_lines(caption):
    caption.setProperty("width", 260)
    caption.setProperty("maxLines", 2)
    caption.setProperty("pending", "первое слово")
    settle()
    height = caption.property("implicitHeight")
    caption.setProperty("pending", "первое слово " + "длинная русская фраза " * 15)
    settle()
    assert caption.property("lineCount") > 2
    assert caption.property("implicitHeight") == height
    visible = [word for word in words(caption) if word.property("visible")]
    assert len({word.property("y") for word in visible}) == 2
    assert words(caption)[-1].property("visible")
    assert not words(caption)[0].property("visible")


def test_long_caption_burst_keeps_event_loop_responsive(caption):
    ticks = []
    timer = QTimer()
    timer.setInterval(0)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    started = time.monotonic()
    try:
        prefix = " ".join(f"слово{i}" for i in range(1200))
        for index in range(100):
            caption.setProperty("pending", prefix + f" конец{index}")
        settle()
        before = words(caption)
        assert len(before) <= 192
        assert before[-1].property("text") == "конец99"
        caption.setProperty("pending", prefix + " конец99 новое")
        settle()
        after = words(caption)
        assert after[:-1] == before[1:]
        assert after[-1].property("text") == "новое"
        assert ticks
        # Deliberately loose ceiling: catches stalls, not a hardware benchmark.
        assert time.monotonic() - started < 5
    finally:
        timer.stop()


def test_segment_binding_ignores_unrelated_controller_signals(gui):
    controller = Controller.__new__(Controller)
    QObject.__init__(controller)
    controller._segments = []
    engine = QQmlEngine()
    engine.rootContext().setContextProperty("bridge", controller)
    component = QQmlComponent(engine)
    component.setData(b"""
        import QtQml
        QtObject {
            property var observed: bridge.segments
            property int refreshes: 0
            onObservedChanged: refreshes++
        }
    """, QUrl())
    root = component.create()
    assert root is not None, [error.toString() for error in component.errors()]
    baseline = root.property("refreshes")
    try:
        for _ in range(50):
            controller.changed.emit()
        settle()
        assert root.property("refreshes") == baseline
        controller.segmentsChanged.emit()
        settle()
        assert root.property("refreshes") == baseline + 1
    finally:
        root.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_stage_keeps_previous_and_live_inside_reserved_space(gui):
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML_DIR / "CaptionStage.qml")))
    stage = component.create()
    assert stage is not None, [error.toString() for error in component.errors()]
    try:
        stage.setProperty("width", 520)
        stage.setProperty("height", stage.property("implicitHeight"))
        stage.setProperty("previous", "Предыдущая фраза")
        stage.setProperty("pending", "Начало")
        settle()
        previous = stage.findChild(QObject, "previousCaption")
        live = stage.findChild(QObject, "liveCaption")
        assert previous.property("y") >= 0
        assert previous.property("y") + previous.property("height") <= live.property("y")
        assert live.property("y") + live.property("height") <= stage.property("height")
        before = (previous.property("y"), live.property("y"), live.property("height"))
        stage.setProperty("pending", "Начало " + "ещё несколько слов " * 10)
        settle()
        assert (previous.property("y"), live.property("y"), live.property("height")) == before
    finally:
        stage.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
