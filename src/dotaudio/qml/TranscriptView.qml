import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Отдельный режим «Транскрибация»: файл -> расшифровка с таймкодами и
// говорящими. Весь обмен идёт через мост bridge.*; распознавание всегда
// локально (bridge.runTranscript никогда не выбирает сервер), а голоса
// определяет выбранный движок: NVIDIA NeMo Sortformer или ECAPA.
Rectangle {
    id: view
    color: "transparent"

    property string phase: String(bridge.transcribeState.phase || "idle")
    property string stage: String(bridge.transcribeState.stage || "")
    property string file: String(bridge.transcribeState.file || "")
    property bool busyPhase: phase === "working"
    property var segs: bridge.transcribeSegments
    property var speakers: bridge.transcribeState.speakers || []
    property string engineNote: String(bridge.transcribeState.engineNote || "")
    property var voices: bridge.diarizeStatus
    property var engines: bridge.diarizeEngines

    // Показывать только один голос. 0 - показывать всех.
    property int focusKey: 0
    // Фраза, к которой только что перешли с полосы голосов.
    property int markedIndex: -1

    readonly property var rows: focusKey > 0
        ? segs.filter(function (row) { return Number(row.role) === view.focusKey })
        : segs
    readonly property real total: Math.max(0.001, Number(bridge.transcribeState.duration || 0))

    Component.onCompleted: bridge.refreshDiarizeStatus()

    function timecode(seconds) {
        var total = Math.max(0, Math.round(Number(seconds) * 1000))
        var hours = Math.floor(total / 3600000)
        total -= hours * 3600000
        var minutes = Math.floor(total / 60000)
        total -= minutes * 60000
        var rest = (total / 1000).toFixed(1)
        if (rest.length < 4) rest = "0" + rest
        return (hours > 0 ? (hours < 10 ? "0" : "") + hours + ":" : "")
               + (minutes < 10 ? "0" : "") + minutes + ":" + rest
    }

    function duration(seconds) {
        var whole = Math.max(0, Math.round(Number(seconds)))
        var minutes = Math.floor(whole / 60)
        var rest = whole % 60
        return minutes > 0 ? minutes + " мин " + rest + " с" : rest + " с"
    }

    function phrases(count) {
        var value = Number(count)
        var tail = Math.abs(value) % 100
        var last = tail % 10
        if (tail > 10 && tail < 20) return value + " реплик"
        if (last === 1) return value + " реплика"
        if (last >= 2 && last <= 4) return value + " реплики"
        return value + " реплик"
    }

    function engineIndex() {
        var key = String(view.voices.engine || "off")
        for (var i = 0; i < view.engines.length; ++i)
            if (String(view.engines[i].key) === key)
                return i
        return 0
    }

    // Переход с полосы голосов к фразе. Фильтр снимается: иначе номер
    // фразы на полосе не совпал бы с номером строки в отфильтрованном списке.
    function revealPhrase(index) {
        view.focusKey = 0
        Qt.callLater(function () {
            segList.positionViewAtIndex(index, ListView.Center)
            view.markedIndex = index
            markTimer.restart()
        })
    }

    Timer {
        id: markTimer
        interval: 1600
        onTriggered: view.markedIndex = -1
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gapMd

        // Панель выбора, запуска и движка голосов.
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: topRow.implicitHeight + 2 * Theme.padCard
            radius: Theme.radiusLg
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            ColumnLayout {
                id: topRow
                anchors.fill: parent
                anchors.margins: Theme.padCard
                spacing: Theme.gapSm
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Label {
                            text: view.file.length ? view.file : "Расшифровка аудио или видео"
                            color: Theme.text
                            font.pixelSize: Theme.fsTitle
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Label {
                            text: view.file.length
                                  ? "Обработка локально. Аудио не покидает этот компьютер."
                                  : "Откройте запись, получите слова с таймкодами и метки говорящих."
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                            wrapMode: Text.Wrap
                        }
                    }
                    PillButton { text: "Открыть"; enabled: !view.busyPhase; onClicked: bridge.pickTranscriptFile() }
                    PillButton { text: view.busyPhase ? "Стоп" : "Транскрибировать"; primary: !view.busyPhase; enabled: view.file.length > 0; onClicked: view.busyPhase ? bridge.stopTranscript() : bridge.runTranscript() }
                    PillButton { text: "Очистить"; enabled: (view.file.length > 0 || view.segs.length > 0) && !view.busyPhase; onClicked: bridge.clearTranscript() }
                    PillButton { text: "Сохранить…"; enabled: view.segs.length > 0 && !view.busyPhase; onClicked: bridge.transcriptExport() }
                    PillButton {
                        text: "В ассистент"
                        primary: true
                        visible: view.phase === "done" && view.segs.length > 0
                                 && String(bridge.transcribeState.sessionId || "").length > 0
                        enabled: !view.busyPhase
                        onClicked: bridge.openTranscriptInAssistant()
                        ToolTip.visible: hovered
                        ToolTip.text: "Открыть эту расшифровку в чате ассистента"
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.topMargin: 2
                    implicitHeight: 1
                    color: Theme.hairline
                }

                // Выбор движка голосов и его готовность.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    Label {
                        text: "Голоса"
                        color: Theme.muted
                        font.pixelSize: Theme.fsLabel
                    }
                    Dropdown {
                        id: enginePick
                        Layout.preferredWidth: 190
                        enabled: !view.busyPhase
                        model: view.engines
                        textRole: "label"
                        currentIndex: view.engineIndex()
                        onActivated: function (index) {
                            bridge.setDiarizeEngine(String(view.engines[index].key))
                        }
                    }
                    StatusDot {
                        active: view.voices.ready === true
                        tint: view.voices.ready === true ? Theme.text
                              : view.voices.checking === true ? Theme.muted : Theme.rec
                    }
                    Label {
                        Layout.fillWidth: true
                        text: String(view.voices.message || "")
                        color: view.voices.ready === true ? Theme.muted : Theme.text
                        font.pixelSize: Theme.fsSmall
                        elide: Text.ElideRight
                    }
                    PillButton {
                        text: "Проверить снова"
                        compact: true
                        visible: String(view.voices.engine || "") === "nemo"
                        enabled: view.voices.checking !== true && !view.busyPhase
                        onClicked: bridge.refreshDiarizeStatus()
                    }
                }

                Label {
                    visible: view.busyPhase
                    Layout.fillWidth: true
                    text: view.stage === "voices"
                          ? "Слова готовы. Определяем, кто из говорящих что произнёс…"
                          : "Распознаём на процессоре и расставляем таймкоды. На длинной записи это занимает время."
                    color: Theme.faint
                    font.pixelSize: Theme.fsSmall
                    wrapMode: Text.Wrap
                }
            }
        }

        // Как включить выбранный движок, если его нет на машине.
        Rectangle {
            Layout.fillWidth: true
            visible: view.voices.ready !== true && view.voices.checking !== true
                     && String(view.voices.hint || "").length > 0
            implicitHeight: setupBox.implicitHeight + 2 * Theme.padCard
            radius: Theme.radiusLg
            color: Theme.surface
            border.width: 1
            border.color: Theme.borderHi
            ColumnLayout {
                id: setupBox
                anchors.fill: parent
                anchors.margins: Theme.padCard
                spacing: Theme.gapSm
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    Icon { name: "warning"; ink: Theme.text; width: 16; height: 16 }
                    Label {
                        Layout.fillWidth: true
                        text: String(view.voices.hint || "")
                        color: Theme.text
                        font.pixelSize: Theme.fsBody
                        wrapMode: Text.Wrap
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: String(view.voices.install || "").length > 0
                    spacing: Theme.gapSm
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: Math.max(34, command.implicitHeight + 14)
                        radius: Theme.radiusMd
                        color: Theme.fill
                        border.width: 1
                        border.color: Theme.hairline
                        TextEdit {
                            id: command
                            anchors.fill: parent
                            anchors.margins: 9
                            text: String(view.voices.install || "")
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.WrapAnywhere
                            color: Theme.text
                            selectionColor: Theme.fillPress
                            font.family: Theme.monoFamily
                            font.pixelSize: Theme.fsSmall
                        }
                    }
                    PillButton { text: "Копировать"; compact: true; onClicked: bridge.copyDiarizeInstall() }
                }
                Label {
                    Layout.fillWidth: true
                    visible: String(view.voices.engine || "") === "nemo"
                    text: "Python-пакет NeMo не поддерживает Windows, поэтому используется нативный рантайм NVIDIA NeMo-Speech.cpp. Он не тянет torch и работает на процессоре."
                    color: Theme.faint
                    font.pixelSize: Theme.fsSmall
                    wrapMode: Text.Wrap
                }
            }
        }

        // Легенда говорящих: цвет, имя (правится), доля речи, фильтр.
        Rectangle {
            Layout.fillWidth: true
            visible: view.speakers.length > 0
            implicitHeight: speakerBox.implicitHeight + 2 * Theme.padCard
            radius: Theme.radiusLg
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            ColumnLayout {
                id: speakerBox
                anchors.fill: parent
                anchors.margins: Theme.padCard
                spacing: Theme.gapSm

                Flow {
                    id: speakerRow
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    Repeater {
                        model: view.speakers
                        delegate: Rectangle {
                            id: chip
                            required property var modelData
                            readonly property bool focused: view.focusKey === Number(modelData.key)
                            function commit() {
                                var label = nameField.text.trim()
                                if (label.length) bridge.renameTranscriptSpeaker(Number(modelData.key), label)
                            }
                            width: Math.min(320, Math.max(230, nameField.implicitWidth + share.implicitWidth + 74))
                            implicitHeight: 38
                            radius: Theme.radiusLg
                            color: chip.focused ? Theme.fillHi : Theme.fill
                            border.width: 1
                            border.color: chip.focused ? Theme.borderHi : Theme.hairline
                            Behavior on color { ColorAnimation { duration: Theme.fastMs } }

                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton
                                onClicked: view.focusKey = chip.focused ? 0 : Number(chip.modelData.key)
                                // Имя правится текстовым полем поверх этой области.
                                propagateComposedEvents: true
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                spacing: Theme.gapSm
                                Rectangle {
                                    Layout.preferredWidth: 8
                                    Layout.preferredHeight: 8
                                    radius: 4
                                    color: Theme.speakerInk(chip.modelData.key)
                                }
                                TextField {
                                    id: nameField
                                    Layout.fillWidth: true
                                    text: String(chip.modelData.label || "")
                                    color: Theme.text
                                    font.pixelSize: Theme.fsLabel
                                    onActiveFocusChanged: if (!activeFocus) chip.commit()
                                    onEditingFinished: chip.commit()
                                    background: Item {}
                                }
                                Label {
                                    id: share
                                    text: view.phrases(chip.modelData.count) + " · "
                                          + view.duration(chip.modelData.seconds)
                                    color: Theme.faint
                                    font.pixelSize: Theme.fsMicro
                                }
                            }
                        }
                    }
                }

                // Полоса голосов по всей записи: видно, кто и когда говорит.
                Item {
                    id: timeline
                    Layout.fillWidth: true
                    implicitHeight: 26
                    visible: view.segs.length > 0

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusSm
                        color: Theme.surface2
                        border.width: 1
                        border.color: Theme.hairline
                    }
                    Repeater {
                        model: view.segs
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            readonly property bool dimmed: view.focusKey > 0
                                                           && Number(modelData.role) !== view.focusKey
                            x: 3 + (timeline.width - 6) * Math.min(1, Number(modelData.start) / view.total)
                            width: Math.max(2, (timeline.width - 6)
                                   * Math.min(1, (Number(modelData.end) - Number(modelData.start)) / view.total))
                            y: 5
                            height: parent.height - 10
                            radius: 3
                            color: Theme.speakerInk(modelData.role)
                            opacity: dimmed ? 0.22 : 0.85
                            Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }
                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: view.revealPhrase(parent.index)
                                ToolTip.visible: containsMouse
                                ToolTip.text: view.timecode(parent.modelData.start) + " · "
                                              + (parent.modelData.speaker || "голос не определён")
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Label {
                            Layout.fillWidth: true
                            visible: view.engineNote.length > 0
                            text: view.engineNote
                            color: Theme.faint
                            font.pixelSize: Theme.fsSmall
                            elide: Text.ElideRight
                        }
                        // Подсказка про фильтр нужна ровно тогда, когда есть
                        // между кем выбирать, и мешает, когда фильтр уже стоит.
                        Label {
                            Layout.fillWidth: true
                            visible: view.focusKey === 0 && view.speakers.length > 1
                            text: "Нажмите на голос, чтобы оставить в списке только его реплики, или на полосу - чтобы перейти к фразе."
                            color: Theme.faint
                            font.pixelSize: Theme.fsSmall
                            elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: view.focusKey > 0
                            text: "Показаны реплики одного голоса: " + view.rows.length + " из " + view.segs.length + "."
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                        }
                    }
                    PillButton {
                        text: "Показать всех"
                        compact: true
                        visible: view.focusKey > 0
                        onClicked: view.focusKey = 0
                    }
                }
            }
        }

        // Причина, по которой голоса не определились: текст всё равно есть.
        Label {
            Layout.fillWidth: true
            visible: view.speakers.length === 0 && view.engineNote.length > 0
            text: view.engineNote
            color: Theme.muted
            font.pixelSize: Theme.fsSmall
            wrapMode: Text.Wrap
        }

        // Список фраз с говорящим и таймкодом.
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ColumnLayout {
                anchors.centerIn: parent
                visible: view.segs.length === 0 && !view.file.length
                width: Math.min(parent.width - 80, 360)
                spacing: Theme.gapSm
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Готово к транскрибации"
                    color: Theme.text
                    font.pixelSize: Theme.fsLead
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: "Этот раздел не касается караоке: выбирается запись, а при желании определяется, кто из говорящих что произнёс."
                    color: Theme.muted
                    font.pixelSize: Theme.fsBody
                }
            }
            ColumnLayout {
                anchors.centerIn: parent
                visible: view.segs.length === 0 && view.file.length && !view.busyPhase
                spacing: Theme.gapSm
                Label {
                    text: "Файл выбран"
                    color: Theme.text
                    font.pixelSize: Theme.fsLead
                    font.weight: Font.DemiBold
                }
                Label {
                    color: Theme.muted
                    font.pixelSize: Theme.fsBody
                    text: "Определение голосов заработает после распознавания."
                }
            }
            ListView {
                id: segList
                objectName: "segmentList"
                anchors.fill: parent
                model: view.rows
                spacing: Theme.gapSm
                clip: true
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    id: segCard
                    required property var modelData
                    required property int index
                    readonly property string label: modelData.speaker || ""
                    readonly property bool marked: view.focusKey === 0 && view.markedIndex === index
                    width: ListView.view.width
                    implicitHeight: segBody.implicitHeight + 24
                    radius: Theme.radiusMd
                    color: segCard.marked ? Theme.surface3 : Theme.surface2
                    border.width: 1
                    border.color: segCard.marked ? Theme.borderHi : Theme.border
                    Behavior on color { ColorAnimation { duration: Theme.baseMs } }
                    RowLayout {
                        id: segBody
                        anchors.fill: parent
                        anchors.margins: 11
                        spacing: 10
                        Rectangle {
                            Layout.preferredWidth: 4
                            Layout.fillHeight: true
                            radius: 2
                            color: Theme.speakerInk(segCard.modelData.role)
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.gapSm
                                Label {
                                    text: view.timecode(segCard.modelData.start) + " – " + view.timecode(segCard.modelData.end)
                                    color: Theme.muted
                                    font.family: Theme.monoFamily
                                    font.pixelSize: Theme.fsSmall
                                }
                                Item { Layout.fillWidth: true }
                                Label {
                                    visible: segCard.label.length > 0
                                    text: segCard.label
                                    color: Theme.speakerInk(segCard.modelData.role)
                                    font.pixelSize: Theme.fsSmall
                                    font.weight: Font.DemiBold
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: segCard.modelData.text || "-"
                                color: Theme.text
                                font.pixelSize: Theme.fsBody
                                wrapMode: Text.Wrap
                                textFormat: Text.PlainText
                            }
                        }
                    }
                }
            }
        }
    }
}
