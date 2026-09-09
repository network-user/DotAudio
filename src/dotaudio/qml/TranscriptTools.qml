import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Панель pro-инструментов транскрибации: поиск, замена, пресеты экспорта,
// качество, сравнение моделей, словарь, undo.
Rectangle {
    id: root
    property bool busy: false
    property var quality: ({ total: 0, flagged: 0, checked: 0, meanConfidence: -1 })
    property var presets: []
    property var compare: ({ phase: "idle", message: "", report: {} })
    property bool canUndo: false
    property bool canRedo: false
    property bool onlyFlagged: false
    property string findText: ""
    property string replaceText: ""

    signal undoRequested()
    signal redoRequested()
    signal replaceRequested(string find, string replace)
    signal dictionaryRequested()
    signal exportPresetRequested(string key, var options)
    signal compareRequested()
    signal onlyFlaggedToggled(bool value)
    signal assistantRequested()

    property bool exportTimestamps: true
    property bool exportSpeakers: true
    property bool exportConfidence: false
    property bool exportReviewFlags: false
    property bool exportHeader: false
    property bool exportPhraseNumbers: false

    function syncExportFromPreset() {
        var item = root.presets[presetPick.currentIndex]
        if (!item)
            return
        if (item.include_timestamps !== undefined)
            root.exportTimestamps = Boolean(item.include_timestamps)
        if (item.include_speakers !== undefined)
            root.exportSpeakers = Boolean(item.include_speakers)
        if (item.include_confidence !== undefined)
            root.exportConfidence = Boolean(item.include_confidence)
        if (item.include_review_flags !== undefined)
            root.exportReviewFlags = Boolean(item.include_review_flags)
        if (item.include_header !== undefined)
            root.exportHeader = Boolean(item.include_header)
        if (item.include_phrase_numbers !== undefined)
            root.exportPhraseNumbers = Boolean(item.include_phrase_numbers)
    }

    function exportOptions() {
        return {
            include_timestamps: root.exportTimestamps,
            include_speakers: root.exportSpeakers,
            include_confidence: root.exportConfidence,
            include_review_flags: root.exportReviewFlags,
            include_header: root.exportHeader,
            include_phrase_numbers: root.exportPhraseNumbers
        }
    }

    radius: Theme.radiusLg
    color: Theme.surface
    border.width: 1
    border.color: Theme.border
    implicitHeight: col.implicitHeight + 2 * Theme.padCard

    ColumnLayout {
        id: col
        anchors.fill: parent
        anchors.margins: Theme.padCard
        spacing: Theme.gapSm

        Flow {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            Label {
                text: "Инструменты"
                color: Theme.text
                font.pixelSize: Theme.fsLabel
                font.weight: Font.DemiBold
                verticalAlignment: Text.AlignVCenter
            }
            Label {
                text: {
                    var q = root.quality || {}
                    var parts = [(q.total || 0) + " фраз"]
                    if ((q.flagged || 0) > 0)
                        parts.push("на проверку: " + q.flagged)
                    if ((q.meanConfidence || -1) >= 0)
                        parts.push("ср. уверенность " + Math.round(q.meanConfidence * 100) + "%")
                    return parts.join(" · ")
                }
                color: Theme.muted
                font.pixelSize: Theme.fsMicro
                verticalAlignment: Text.AlignVCenter
            }
            PillButton {
                text: "↺"
                compact: true
                enabled: root.canUndo && !root.busy
                onClicked: root.undoRequested()
                ToolTip.visible: hovered
                ToolTip.text: "Отменить правку"
            }
            PillButton {
                text: "↻"
                compact: true
                enabled: root.canRedo && !root.busy
                onClicked: root.redoRequested()
                ToolTip.visible: hovered
                ToolTip.text: "Повторить правку"
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            TextField {
                id: findField
                width: Math.max(140, Math.min(220, (col.width - Theme.gapSm) / 2))
                placeholderText: "Найти в расшифровке"
                color: Theme.text
                placeholderTextColor: Theme.faint
                enabled: !root.busy
                text: root.findText
                onTextChanged: root.findText = text
                background: Rectangle {
                    radius: Theme.radiusSm
                    color: Theme.fill
                    border.width: 1
                    border.color: findField.activeFocus ? Theme.borderHi : Theme.hairline
                }
            }
            TextField {
                id: replaceField
                width: Math.max(140, Math.min(220, (col.width - Theme.gapSm) / 2))
                placeholderText: "Заменить на"
                color: Theme.text
                placeholderTextColor: Theme.faint
                enabled: !root.busy
                text: root.replaceText
                onTextChanged: root.replaceText = text
                background: Rectangle {
                    radius: Theme.radiusSm
                    color: Theme.fill
                    border.width: 1
                    border.color: replaceField.activeFocus ? Theme.borderHi : Theme.hairline
                }
            }
            PillButton {
                text: "Заменить всё"
                compact: true
                enabled: !root.busy && findField.text.length > 0
                onClicked: root.replaceRequested(findField.text, replaceField.text)
            }
            PillButton {
                text: "Словарь"
                compact: true
                enabled: !root.busy
                onClicked: root.dictionaryRequested()
                ToolTip.visible: hovered
                ToolTip.text: "Применить словарь замен ко всей записи"
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            Label {
                text: "Экспорт"
                color: Theme.muted
                font.pixelSize: Theme.fsLabel
                verticalAlignment: Text.AlignVCenter
            }
            Dropdown {
                id: presetPick
                width: Math.min(260, Math.max(180, col.width * 0.4))
                enabled: !root.busy
                model: root.presets
                textRole: "label"
                onCurrentIndexChanged: root.syncExportFromPreset()
                Component.onCompleted: root.syncExportFromPreset()
            }
            PillButton {
                text: "Сохранить пресет…"
                primary: true
                enabled: !root.busy && root.presets.length > 0
                onClicked: {
                    var item = root.presets[presetPick.currentIndex]
                    if (item)
                        root.exportPresetRequested(String(item.key), root.exportOptions())
                }
            }
            ToggleSwitch {
                text: "Только проблемные"
                checked: root.onlyFlagged
                enabled: !root.busy
                onToggled: {
                    root.onlyFlagged = checked
                    root.onlyFlaggedToggled(checked)
                }
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            visible: root.presets.length > 0
            ToggleSwitch {
                text: "Таймкоды"
                checked: root.exportTimestamps
                enabled: !root.busy
                onToggled: root.exportTimestamps = checked
            }
            ToggleSwitch {
                text: "Голоса"
                checked: root.exportSpeakers
                enabled: !root.busy
                onToggled: root.exportSpeakers = checked
            }
            ToggleSwitch {
                text: "Уверенность"
                checked: root.exportConfidence
                enabled: !root.busy
                onToggled: root.exportConfidence = checked
            }
            ToggleSwitch {
                text: "Метки проверки"
                checked: root.exportReviewFlags
                enabled: !root.busy
                onToggled: root.exportReviewFlags = checked
            }
            ToggleSwitch {
                text: "Шапка"
                checked: root.exportHeader
                enabled: !root.busy
                onToggled: root.exportHeader = checked
            }
            ToggleSwitch {
                text: "№ фраз"
                checked: root.exportPhraseNumbers
                enabled: !root.busy
                onToggled: root.exportPhraseNumbers = checked
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            PillButton {
                text: root.compare.phase === "working" ? "Сравниваем…" : "Тест моделей Whisper"
                enabled: !root.busy && root.compare.phase !== "working"
                onClicked: root.compareRequested()
                ToolTip.visible: hovered
                ToolTip.text: "По очереди прогоняет доступные модели и показывает отличия"
            }
            PillButton {
                text: "В ассистент"
                enabled: !root.busy
                onClicked: root.assistantRequested()
            }
            Label {
                visible: String(root.compare.message || "").length > 0
                text: String(root.compare.message || "")
                color: Theme.muted
                font.pixelSize: Theme.fsSmall
                elide: Text.ElideRight
                width: Math.min(360, Math.max(120, col.width - 280))
                verticalAlignment: Text.AlignVCenter
            }
        }

        Label {
            Layout.fillWidth: true
            visible: root.compare.phase === "done"
                     && root.compare.report
                     && String(root.compare.report.text || "").length > 0
            text: String((root.compare.report && root.compare.report.text) || "")
            color: Theme.faint
            font.pixelSize: Theme.fsMicro
            wrapMode: Text.Wrap
            maximumLineCount: 8
            elide: Text.ElideRight
        }
    }
}
