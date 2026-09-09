"""Окно сохранения расшифровки в настоящем Qt Quick, без диска и без модели.

Главное, что здесь проверяется: предпросмотр показывает тот же текст, который
уйдёт в файл, и меняется вместе с параметрами. Опечатка в имени свойства моста
не ломает загрузку QML - она превращается в тихое предупреждение и пустое
место в интерфейсе, поэтому предупреждения тут считаются ошибкой.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import (
    Property,
    QCoreApplication,
    QEvent,
    QMetaObject,
    QObject,
    QtMsgType,
    QUrl,
    Signal,
    Slot,
    qInstallMessageHandler,
)
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickView

from dotaudio.controller import DEFAULTS
from dotaudio.transcript_pro import (
    export_format_list,
    export_option_choices,
    export_rows,
    render_export,
)

QML_DIR = Path(__file__).resolve().parents[1] / "src" / "dotaudio" / "qml"

# Popup нельзя сделать корнем QQuickView, поэтому окно поднимается внутри
# обёртки. Базовый URL в каталоге qml даёт компоненту соседние файлы без
# отдельного import.
PROBE = b"""
import QtQuick
Item {
    anchors.fill: parent
    TranscriptExportDialog { objectName: 'exportDialog' }
}
"""

SPEECH = [
    {
        "start": 16.08,
        "end": 20.12,
        "text": "потихонечку сокращается.",
        "speaker": "Диктор 2",
        "role": 2,
        "confidence": 0.91,
    },
    {
        "start": 20.5,
        "end": 24.0,
        "text": "а вот и ответ.",
        "speaker": "Диктор 1",
        "role": 1,
        "confidence": 0.42,
    },
]


class _ExportBridge(QObject):
    """Мост только с тем, что читает окно сохранения.

    Предпросмотр считается теми же функциями, что и в контроллере, поэтому
    тест ловит расхождение окна с настоящим экспортом, а не с копией правил.
    """

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._settings = dict(DEFAULTS)
        self.saved: list[dict] = []

    @Property("QVariantMap", notify=changed)
    def settings(self):
        return dict(self._settings)

    @Property("QVariantList", notify=changed)
    def transcriptExportFormats(self):  # noqa: N802 - имя как в Qt-свойстве
        return export_format_list()

    @Property("QVariantMap", notify=changed)
    def transcriptExportChoices(self):  # noqa: N802 - имя как в Qt-свойстве
        return export_option_choices()

    @Slot("QVariantMap", result="QVariantMap")
    def transcriptExportInfo(self, options=None):  # noqa: N802 - имя как в Qt-слоте
        body, ext = render_export(SPEECH, options)
        return {
            "text": body,
            "notice": "",
            "lines": len(body.splitlines()),
            "chars": len(body),
            "phrases": len(export_rows(SPEECH, options)),
            "truncated": False,
            "ext": ext,
            "filename": f"беседа.{ext}",
        }

    @Slot("QVariantMap")
    def transcriptExportWithOptions(self, options=None):  # noqa: N802 - имя как в Qt-слоте
        self.saved.append(dict(options or {}))


@pytest.fixture(scope="module")
def gui():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QGuiApplication.instance() or QGuiApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
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
def dialog(gui, warnings):
    bridge = _ExportBridge()
    view = QQuickView()
    view.resize(1100, 720)
    view.rootContext().setContextProperty("bridge", bridge)
    component = QQmlComponent(view.engine())
    component.setData(PROBE, QUrl.fromLocalFile(str(QML_DIR / "ExportDialogProbe.qml")))
    assert component.status() == QQmlComponent.Ready, component.errorString()
    host = component.create(view.rootContext())
    assert host is not None, component.errorString()
    host.setParentItem(view.contentItem())
    view.show()
    root = host.findChild(QObject, "exportDialog")
    assert root is not None
    root.setProperty("focusKey", 2)
    QMetaObject.invokeMethod(root, "open")
    settle()
    yield root, bridge
    QMetaObject.invokeMethod(root, "close")
    view.close()
    host.deleteLater()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def settle(attempts: int = 16) -> None:
    # Предпросмотр собирается таймером, поэтому событиям нужно дать время.
    for _ in range(attempts):
        QCoreApplication.processEvents()
        time.sleep(0.01)


def format_keys(root) -> list[str]:
    return [str(row["key"]) for row in root.property("formats")]


def apply(root, **values) -> None:
    """Задать параметры и пересчитать предпросмотр, как это делает интерфейс."""

    for name, value in values.items():
        root.setProperty(name, value)
    QMetaObject.invokeMethod(root, "refresh")
    settle()


def preview(root) -> str:
    info = root.property("info")
    payload = info.toVariant() if hasattr(info, "toVariant") else info
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("notice") or "") or str(payload.get("text") or "")


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


def test_dialog_loads_and_previews_the_saved_text(dialog, warnings) -> None:
    root, _bridge = dialog

    # Каталог форматов приходит из transcript_pro, а не из копии в QML.
    assert format_keys(root)[:2] == ["txt", "line"]
    assert preview(root)
    assert_clean(warnings)


def test_line_format_shows_time_speaker_and_text_in_one_row(dialog, warnings) -> None:
    root, _bridge = dialog

    apply(
        root,
        formatIndex=format_keys(root).index("line"),
        includeTimestamps=True,
        timePrecision="millis",
        timeMode="range",
        speakerStyle="bracket",
        fieldSeparator="space",
    )
    assert "00:16.080 - 00:20.120 [Диктор 2] потихонечку сокращается." in preview(root)

    # Секунды вместо миллисекунд - то, ради чего появилась настройка точности.
    apply(root, timePrecision="seconds")
    assert "00:16 - 00:20 [Диктор 2] потихонечку сокращается." in preview(root)

    # Своя разметка строки: время:голос:текст.
    apply(root, fieldSeparator="colon", speakerStyle="plain", timeMode="start")
    assert "00:16:Диктор 2:потихонечку сокращается." in preview(root)
    assert_clean(warnings)


def test_subtitle_format_keeps_its_own_precision(dialog, warnings) -> None:
    root, _bridge = dialog

    apply(root, formatIndex=format_keys(root).index("srt"), timePrecision="seconds")

    assert root.property("timesLocked") is True
    assert root.property("precisionLocked") is True
    # Субтитры не теряют синхронизацию из-за точности, выбранной для текста.
    assert "00:00:16,080 --> 00:00:20,120" in preview(root)
    assert_clean(warnings)


def test_save_sends_exactly_what_the_preview_showed(dialog, warnings) -> None:
    root, bridge = dialog

    apply(
        root,
        formatIndex=format_keys(root).index("csv"),
        includeHeader=True,
        includePhraseNumbers=True,
        includeTimestamps=True,
        focusedOnly=True,
    )

    shown = preview(root)
    assert shown.startswith("№")
    # Фильтр по голосу применён: в файл идёт только выбранная роль.
    assert "Диктор 1" not in shown

    button = root.findChild(QObject, "exportSaveButton")
    assert button is not None
    button.clicked.emit()
    settle()

    assert len(bridge.saved) == 1
    saved = bridge.saved[0]
    assert saved["format"] == "csv"
    assert saved["include_header"] is True
    assert saved["speaker_key"] == 2
    assert render_export(SPEECH, saved)[0] == shown
    assert_clean(warnings)
