import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Остров. HWND - фиксированный холст в MainMvp. Drag только сигналит
// порог сдвига: само окно двигает MainMvp визуально (translate на
// развёрнутом холсте), без SetWindowPos на каждый кадр.
Rectangle {
    id: root

    property string phase: "ready"
    property bool hoveredIsland: false
    property bool clickThrough: false
    property real visualScale: 1
    // Подъём при появлении оболочки задаёт родитель; держим здесь, чтобы не
    // перетереть Scale снаружи одним transform.
    property real shellRise: 0

    color: Theme.islandFill
    border.width: 1
    border.color: bridge.recording || bridge.busy ? Theme.borderHi : Theme.border
    clip: true
    transform: [
        Scale {
            origin.x: root.width / 2
            origin.y: root.height / 2
            xScale: root.visualScale
            yScale: root.visualScale
        },
        Translate { y: root.shellRise }
    ]

    Behavior on border.color { ColorAnimation { duration: Theme.slowMs } }
    Behavior on radius {
        NumberAnimation {
            duration: Theme.morphMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
    }
    Behavior on visualScale {
        NumberAnimation {
            duration: Theme.morphMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
    }

    property int _prevW: 0
    property int _prevH: 0
    onWidthChanged: root._pulseScale()
    onHeightChanged: root._pulseScale()
    function _pulseScale() {
        // Один кадр «из прошлого размера», затем Behavior дотягивает до 1.
        if (_prevW < 8 || _prevH < 8 || width < 8 || height < 8) {
            _prevW = Math.round(width)
            _prevH = Math.round(height)
            visualScale = 1
            return
        }
        var sx = _prevW / width
        var sy = _prevH / height
        var s = Math.max(0.82, Math.min(1.18, Math.min(sx, sy)))
        _prevW = Math.round(width)
        _prevH = Math.round(height)
        if (Math.abs(s - 1) < 0.02)
            return
        visualScale = s
        Qt.callLater(function () { root.visualScale = 1 })
    }

    signal requestTheater()
    signal requestApp(string page)
    signal dragStarted(real screenX, real screenY)
    signal dragReleased()
    signal requestModePick()
    signal closeModes()

    readonly property bool livePage: bridge.page === "live"
    readonly property bool liveMode: Boolean(bridge.liveActive)
    readonly property bool dictationMode: bridge.page === "dictation" && !liveMode
    // Пока новая речь не началась, остров держит последнее законченное
    // предложение: истории на нём нет, а пустая строка сразу после фразы
    // читалась бы как потеря текста.
    readonly property string capConfirmed: {
        if (liveMode)
            return bridge.displayCaption.length ? bridge.confirmedCaption : bridge.settledCaption
        if (root.phase === "result")
            return bridge.lastTranscript.length ? bridge.lastTranscript : bridge.text
        return bridge.text.length ? bridge.text : bridge.caption
    }
    readonly property string capPending: liveMode
        ? bridge.partialCaption
        : (bridge.recording || bridge.busy ? bridge.partialCaption : "")
    readonly property int recSize: phase === "ready" ? 28 : 32
    readonly property string phaseLabel: {
        if (root.liveMode)
            return bridge.liveStatusText
        if (bridge.busy && !bridge.recording)
            return bridge.status.length ? bridge.status : "Распознаю"
        if (bridge.recording)
            return bridge.inputState === "Нет входного сигнала" ? "Не слышу источник" : "Слушаю"
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
        property real pressSX: 0
        property real pressSY: 0
        property bool dragArmed: false
        onEntered: root.hoveredIsland = true
        onExited: root.hoveredIsland = false
        onPressed: function (mouse) {
            pressSX = mouse.screenX
            pressSY = mouse.screenY
            dragArmed = true
        }
        onPositionChanged: function (mouse) {
            if (!pressed || !dragArmed)
                return
            var dx = mouse.screenX - pressSX
            var dy = mouse.screenY - pressSY
            // 4 px: клик и double-click остаются кликами.
            if (dx * dx + dy * dy < 16)
                return
            dragArmed = false
            // MainMvp отдаёт жест DWM через startSystemMove.
            root.dragStarted(mouse.screenX, mouse.screenY)
        }
        // Не эмитить dragReleased здесь: после startSystemMove Qt сразу
        // шлёт Released, а кнопка ещё зажата — Binding снова включится.
        onReleased: dragArmed = false
        onCanceled: dragArmed = false
        onDoubleClicked: {
            dragArmed = false
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

            Label {
                text: bridge.speechModeLabel
                color: Theme.muted
                font.pixelSize: Theme.fsSmall
                font.family: Theme.fontFamily
                TapHandler {
                    enabled: !bridge.recording && !bridge.busy
                    onTapped: bridge.cycleSpeechMode()
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
                        text: root.phaseLabel
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.fontFamily
                        elide: Text.ElideRight
                    }
                }

                Label {
                    visible: root.liveMode
                    text: bridge.liveModelText
                    color: Theme.faint
                    font.pixelSize: Theme.fsSmall
                    opacity: 0.85
                    font.family: Theme.fontFamily
                    elide: Text.ElideRight
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
                    visible: root.dictationMode && bridge.busy && !bridge.recording
                    spacing: 8
                    Label {
                        text: bridge.status.length ? bridge.status : "Уточняем…"
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.fontFamily
                    }
                }

                RowLayout {
                    // Ручная «Вставить» только вне диктовки: hotkey-диктовка
                    // вставляет сама и закрывает остров.
                    visible: root.phase === "result" && !root.dictationMode
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
                    reduceMotion: Boolean(bridge.settings.reduce_motion)
                }

                Waveform {
                    visible: bridge.recording || (bridge.busy && root.dictationMode)
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
        // Смена фазы читается как лёгкий подъём новой панели: вместе с
        // масштабом это отделяет морф контента от морфа самой геометрии.
        transform: Translate { y: yShift }
        property real yShift: 3
        z: 1
        onShownChanged: yShift = shown ? 3 : 0
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
        Behavior on yShift {
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
                Behavior on scale {
                    NumberAnimation {
                        duration: Theme.fastMs
                        easing.type: Easing.OutQuad
                    }
                }
                Behavior on opacity {
                    NumberAnimation { duration: Theme.fastMs }
                }
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
