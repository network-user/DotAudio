"""Real Qt Quick regressions, without a microphone or an ASR model.

Live captions are plain text wrapped in whole lines: words are not highlighted
or animated one by one, and the view keeps the last ``maxLines`` rows visible.
"""

import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickView

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
    view.resize(560, 200)
    view.setSource(QUrl.fromLocalFile(str(QML_DIR / "CaptionText.qml")))
    assert view.status() == QQuickView.Ready, [error.toString() for error in view.errors()]
    view.show()
    root = view.rootObject()
    yield root
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def settle():
    # Property changes and Text relayout are delivered in the following turns.
    for _ in range(4):
        QCoreApplication.processEvents()


def block(caption):
    return caption.findChild(QObject, "captionBlock")


def shown_plain(caption):
    return caption.property("content")


def test_whole_caption_is_plain_wrapped_text(caption):
    caption.setProperty("confirmed", "Сегодня")
    caption.setProperty("pending", "прекрасная погода")
    settle()
    text = block(caption)
    assert shown_plain(caption) == "Сегодня прекрасная погода"
    assert "прекрасная погода" in text.property("text")
    assert "<font" in text.property("text")
    assert caption.findChild(QObject, "captionWord") is None
    assert caption.property("empty") is False


def test_confirmed_and_pending_join_without_duplicate_space(caption):
    caption.setProperty("confirmed", "Привет,")
    caption.setProperty("pending", "мир!")
    settle()
    assert shown_plain(caption) == "Привет, мир!"
    caption.setProperty("confirmed", "Привет, мир!")
    caption.setProperty("pending", "")
    settle()
    assert shown_plain(caption) == "Привет, мир!"


def test_single_text_fallback(caption):
    caption.setProperty("confirmed", "")
    caption.setProperty("pending", "")
    caption.setProperty("text", "Одна готовая строка")
    settle()
    assert shown_plain(caption) == "Одна готовая строка"
    caption.setProperty("pending", "и продолжение")
    settle()
    # Поле text не смешивается с confirmed/pending: одно из двух.
    assert shown_plain(caption) == "и продолжение"


def test_empty_caption_hides_the_block(caption):
    caption.setProperty("confirmed", "")
    caption.setProperty("pending", "")
    caption.setProperty("text", "")
    settle()
    assert caption.property("empty") is True
    assert not block(caption).property("visible")


def test_long_text_is_clipped_to_the_bottom_last_lines(caption):
    # maxLines держат только последние строки на виду: блок прижат книзу корня
    # и уходит вверх, а верх корня обрезает уже прочитанное.
    caption.setProperty("pending", "первое слово " + "длинная русская фраза " * 30)
    settle()
    text = block(caption)
    assert text.property("height") > caption.property("height")
    assert abs(text.property("y") + text.property("height")
               - caption.property("height")) < 0.5


def test_word_rewrites_do_not_flash_the_line(caption):
    caption.setProperty("pending", "раз два три четыре")
    settle()
    assert shown_plain(caption) == "раз два три четыре"
    text = block(caption)
    assert text.property("scale") == 1.0

    caption.setProperty("pending", "пять шесть семь восемь")
    settle()
    assert shown_plain(caption) == "пять шесть семь восемь"
    assert text.property("scale") == 1.0


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
        assert shown_plain(caption).endswith("конец99")
        caption.setProperty("pending", prefix + " конец99 новое")
        settle()
        assert shown_plain(caption).endswith("новое")
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


@pytest.fixture
def transcript(gui):
    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(640, 420)
    view.setSource(QUrl.fromLocalFile(str(QML_DIR / "LiveTranscript.qml")))
    assert view.status() == QQuickView.Ready, [error.toString() for error in view.errors()]
    view.show()
    root = view.rootObject()
    yield root
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def phrases(count):
    return [
        {"id": index, "start": index * 5.0, "end": index * 5.0 + 4.0,
         "text": f"Фраза номер {index} с достаточно длинным текстом, чтобы проверить перенос."}
        for index in range(count)
    ]


def test_live_line_keeps_its_place_while_history_grows(transcript):
    transcript.setProperty("segments", phrases(2))
    transcript.setProperty("pending", "живая строка")
    settle()
    live = transcript.findChild(QObject, "liveCaption")
    place = (live.property("y"), live.property("height"))

    transcript.setProperty("segments", phrases(12))
    transcript.setProperty("confirmed", "живая строка стала заметно длиннее")
    transcript.setProperty("pending", "и продолжает расти ещё на несколько слов")
    settle()
    # Ни новые фразы, ни рост текущей фразы не двигают живую строку: место
    # под неё отведено заранее, поэтому читателю некуда «уплывать».
    assert (live.property("y"), live.property("height")) == place


def test_history_never_overlaps_the_live_line(transcript):
    transcript.setProperty("segments", phrases(20))
    transcript.setProperty("pending", "текущая речь")
    settle()
    live = transcript.findChild(QObject, "liveRow")
    history = transcript.findChild(QObject, "livePhrases")
    assert history.property("y") + history.property("height") <= live.property("y") + 0.5
    # Длинный разговор упирается в верх и прокручивается, а не выдавливает речь.
    assert history.property("height") <= transcript.property("height")


def test_phrases_keep_their_whole_text(transcript):
    transcript.setProperty("segments", phrases(3))
    settle()
    history = transcript.findChild(QObject, "livePhrases")
    # Делегаты видны как дочерние элементы contentItem, а не через findChildren
    # от корня: у созданных списком строк другой владелец.
    shown = []
    for item in history.property("contentItem").childItems():
        body = item.findChild(QObject, "livePhraseText")
        if body is not None:
            shown.append(body.property("text"))
    assert shown, "фразы не отрисованы"
    for text in shown:
        # Ничего не обрезано многоточием: расшифровку читают целиком.
        assert text.endswith("перенос.")


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
        # Отведённое место не зависит от длины фразы: ничего не прыгает.
        assert (previous.property("y"), live.property("y"), live.property("height")) == before
    finally:
        stage.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
