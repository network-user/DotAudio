import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Остров. Размер окна меняет MainMvp по фазе, а здесь фазы сменяют друг
// друга кроссфейдом: содержимое не режется по кадру, а растворяется, пока
// геометрия доезжает до новой формы.
Rectangle {
    id: root

    property string phase: "ready"
    property bool hoveredIsland: false
    property bool clickThrough: false

    color: Theme.islandFill
    border.width: 1
    border.color: bridge.recording || bridge.busy ? Theme.borderHi : Theme.border
    clip: true

    Behavior on border.color { ColorAnimation { duration: Theme.slowMs } }
    Behavior on radius {
        NumberAnimation {
            duration: Theme.morphMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
    }

    signal requestTheater()
    signal requestApp(string page)
    signal dragStarted()
    signal dragReleased()
    signal requestModePick()
    signal closeModes()

    readonly property bool livePage: bridge.page === "live"
    readonly property bool liveMode: Boolean(bridge.liveActive)
    readonly property string capConfirmed: liveMode ? bridge.confirmedCaption : bridge.caption
    readonly property string capPending: liveMode ? bridge.partialCaption : ""
    readonly property int recSize: phase === "ready" ? 28 : 32
    readonly property string phaseLabel: {
        if (root.liveMode)
            return bridge.liveStatusText
        if (bridge.recording)
            return bridge.inputState === "Нет входного сигнала" ? "Не слышу источник" : "Слушаю"
        if (bridge.busy)
            return "Распознаю"
        return ""
    }

    // Внутренняя кромка. Дешёвая глубина без размытия и без шейдеров.
    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.max(0, root.radius - 1)
        color: "transparent"
        border.width: 1
        border.color: "#12ffffff"
        z: 3
    }

    MouseArea {
        id: dragArea
        anchors.fill: parent
        hoverEnabled: !root.clickThrough
        z: 0
        onEntered: root.hoveredIsland = true
        onExited: root.hoveredIsland = false
        onPressed: root.dragStarted()
        onReleased: root.dragReleased()
        onDoubleClicked: {
            if (root.livePage)
                root.requestTheater()
            else
                root.requestApp(bridge.page)
        }
    }

    // Покой: режим, источник и приглашение к действию.
    PhasePane {
        shown: root.phase === "ready"
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            anchors.topMargin: 8
            anchors.bottomMargin: 8
            spacing: 10

            RecordControl {
                Layout.preferredWidth: root.recSize
                Layout.preferredHeight: root.recSize
            }

            Icon {
                name: root.livePage ? "live" : "dictation"
                ink: Theme.text
                width: 16
                height: 16
                TapHandler {
                    enabled: !bridge.recording && !bridge.busy
                    onTapped: root.requestModePick()
                }
            }

            Label {
                text: root.livePage ? "Live" : "Диктовка"
                color: Theme.text
                font.pixelSize: Theme.fsBody
                font.weight: Font.DemiBold
                font.family: Theme.fontFamily
                TapHandler {
                    enabled: !bridge.recording && !bridge.busy
                    onTapped: root.requestModePick()
                }
            }

            Label {
                visible: root.livePage
                text: bridge.liveSourceLabel
                color: Theme.muted
                font.pixelSize: Theme.fsSmall
                font.family: Theme.fontFamily
                TapHandler {
                    enabled: !bridge.recording && !bridge.busy
                    onTapped: bridge.cycleLiveSource()
                }
            }

            Item { Layout.fillWidth: true }

            IconButton {
                iconName: "expand"
                implicitWidth: 28
                implicitHeight: 28
                opacity: root.hoveredIsland && !root.clickThrough ? 1 : 0
                visible: opacity > 0.02
                onClicked: root.livePage ? root.requestTheater() : root.requestApp(bridge.page)
                ToolTip.visible: hovered
                ToolTip.text: root.livePage ? "Субтитры" : "Окно"
                Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }
            }
        }
    }

    // Слушает или догоняет звук: уровень, статус, время.
    PhasePane {
        shown: root.phase === "listen" || root.phase === "quiet" || root.phase === "process"
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            anchors.topMargin: 8
            anchors.bottomMargin: 8
            spacing: 10

            RecordControl {
                Layout.preferredWidth: root.recSize
                Layout.preferredHeight: root.recSize
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 7
                    StatusDot { active: bridge.recording }
                    Label {
                        Layout.fillWidth: true
                        text: root.phase === "process" && !root.liveMode
                              ? (bridge.recording ? "Распознаю" : "Завершаем")
                              : root.phaseLabel
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.fontFamily
                        elide: Text.ElideRight
                    }
                }

                Waveform {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 14
                    bars: 22
                    barH: 14
                }
            }

            Label {
                visible: bridge.recording || bridge.busy
                text: bridge.elapsed
                color: Theme.muted
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fsSmall
            }

            ForceStopButton {}
        }
    }

    // Есть текст: фраза занимает почти весь остров.
    PhasePane {
        shown: root.phase === "caption" || root.phase === "result"
        RowLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 10

            RecordControl {
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                Layout.alignment: Qt.AlignTop
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 5

                RowLayout {
                    visible: root.phase === "result"
                    spacing: 8
                    Label {
                        text: "В буфере"
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.fontFamily
                    }
                    Label {
                        visible: bridge.lastTranscript.length > 0
                        text: "Вставить"
                        color: Theme.text
                        font.pixelSize: Theme.fsSmall
                        font.weight: Font.DemiBold
                        font.family: Theme.fontFamily
                        TapHandler { onTapped: bridge.pasteLastTranscript() }
                    }
                }

                CaptionText {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    confirmed: root.capConfirmed
                    pending: root.capPending
                    pixelSize: Theme.fsCompact
                    maxLines: 2
                    align: Text.AlignLeft
                }

                Waveform {
                    visible: bridge.recording
                    Layout.fillWidth: true
                    Layout.preferredHeight: 10
                    bars: 24
                    barH: 10
                }
            }

            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                spacing: 4
                Label {
                    visible: bridge.recording || bridge.busy
                    Layout.alignment: Qt.AlignRight
                    text: bridge.elapsed
                    color: Theme.muted
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.fsSmall
                }
                ForceStopButton { Layout.alignment: Qt.AlignRight }
            }
        }
    }

    PhasePane {
        shown: root.phase === "error"
        RowLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 10
            Icon { name: "warning"; ink: Theme.text; width: 18; height: 18 }
            Text {
                Layout.fillWidth: true
                text: bridge.notice
                color: Theme.text
                font.pixelSize: Theme.fsLabel
                font.family: Theme.fontFamily
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            IconButton { iconName: "close"; onClicked: bridge.clearNotice() }
        }
    }

    PhasePane {
        shown: root.phase === "modePick"
        z: 2
        RowLayout {
            anchors.fill: parent
            anchors.margins: 8
            spacing: 8
            PillButton {
                Layout.fillWidth: true
                text: "Live"
                primary: root.livePage
                onClicked: {
                    bridge.selectPage("live")
                    root.closeModes()
                }
            }
            PillButton {
                Layout.fillWidth: true
                text: "Диктовка"
                primary: !root.livePage
                onClicked: {
                    bridge.selectPage("dictation")
                    root.closeModes()
                }
            }
            IconButton {
                iconName: "close"
                onClicked: root.closeModes()
            }
        }
    }

    // Один слой на фазу. Уходящий слой не принимает нажатия, поэтому
    // кроссфейд не создаёт невидимых кнопок.
    component PhasePane: Item {
        property bool shown: false
        anchors.fill: parent
        anchors.margins: 0
        visible: opacity > 0.02
        enabled: shown
        opacity: shown ? 1 : 0
        scale: shown ? 1 : 0.97
        z: 1
        Behavior on opacity {
            NumberAnimation {
                duration: shown ? Theme.baseMs : Theme.fastMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
        Behavior on scale {
            NumberAnimation {
                duration: Theme.baseMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
    }

    component ForceStopButton: IconButton {
        visible: bridge.busy
        iconName: "close"
        implicitWidth: 28
        implicitHeight: 28
        onClicked: bridge.forceStop()
        ToolTip.visible: hovered
        ToolTip.text: "Остановить сейчас без сохранения незавершённой фразы"
    }

    // Кнопка записи. Кольцо дышит по измеренному уровню входа, поэтому по
    // острову видно, что источник действительно слышен.
    component RecordControl: Button {
        id: rec
        implicitWidth: 32
        implicitHeight: 32
        padding: 0
        hoverEnabled: true
        scale: rec.down ? 0.92 : rec.hovered ? 1.05 : 1
        Behavior on scale {
            NumberAnimation {
                duration: Theme.fastMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeSpring
            }
        }
        onClicked: {
            if (!bridge.recording && bridge.busy)
                bridge.forceStop()
            else
                bridge.toggleRecording()
        }
        ToolTip.visible: hovered && !bridge.recording && bridge.busy
        ToolTip.text: "Остановить принудительно"

        background: Item {
            Rectangle {
                id: levelRing
                anchors.centerIn: parent
                width: rec.width
                height: rec.height
                radius: width / 2
                color: "transparent"
                border.width: 1
                border.color: Theme.recRing
                visible: bridge.recording
                opacity: 0.25 + 0.5 * Theme.levelShape(bridge.level)
                scale: 1 + 0.3 * Theme.levelShape(bridge.level)
                Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
                Behavior on opacity { NumberAnimation { duration: 120 } }
            }
            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: rec.down ? Theme.fillPress : rec.hovered ? Theme.fillHi : Theme.surface2
                border.width: 1
                border.color: bridge.recording ? Theme.borderHi : Theme.border
                Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                Behavior on border.color { ColorAnimation { duration: Theme.baseMs } }
            }
        }

        contentItem: Item {
            Icon {
                visible: bridge.busy && !bridge.recording
                anchors.centerIn: parent
                name: "spinner"
                width: 14
                height: 14
            }
            Rectangle {
                visible: !bridge.busy || bridge.recording
                anchors.centerIn: parent
                width: bridge.recording ? 12 : 10
                height: bridge.recording ? 12 : 10
                radius: bridge.recording ? 3 : 5
                color: bridge.recording ? Theme.rec : Theme.ink
                Behavior on width { NumberAnimation { duration: Theme.baseMs; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easeSpring } }
                Behavior on height { NumberAnimation { duration: Theme.baseMs; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easeSpring } }
                Behavior on radius { NumberAnimation { duration: Theme.baseMs } }
                Behavior on color { ColorAnimation { duration: Theme.baseMs } }
            }
        }
    }
}
