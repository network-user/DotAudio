import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Live-сцена. Главное здесь - текущая фраза, поэтому статус, время и
// кнопки собраны в две тонкие полосы, а середина отдана тексту.
Rectangle {
    id: root

    property bool embedded: false
    property bool showTape: embedded

    color: Theme.surface
    radius: embedded ? Theme.radiusXl : 28
    border.width: 1
    border.color: Theme.border
    clip: true

    signal requestIsland()
    signal requestApp()

    readonly property var segments: bridge.segments
    readonly property string previousText: {
        var items = bridge.segments
        if (bridge.partialCaption.length > 0 && items.length)
            return String(items[items.length - 1].text)
        if (items.length >= 2)
            return String(items[items.length - 2].text)
        return ""
    }
    readonly property bool overlayOn: Boolean(bridge.settings.caption_overlay)
    readonly property string stageHint: bridge.liveActive
        ? bridge.liveStatusText
        : "Нажмите «Слушать» - фраза появится здесь"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 14

        // Полоса состояния. Одна строка вместо прежних двух: заголовок и
        // индикатор больше не повторяют друг друга.
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            spacing: 9

            StatusDot { active: bridge.recording }

            Label {
                text: bridge.liveActive ? bridge.liveStatusText
                      : bridge.busy ? "Завершаем" : "Live не запущен"
                color: bridge.recording ? Theme.text : Theme.muted
                font.pixelSize: Theme.fsSmall
                font.weight: Font.DemiBold
                font.family: Theme.fontFamily
                Behavior on color { ColorAnimation { duration: Theme.slowMs } }
            }

            Item { Layout.fillWidth: true }

            Label {
                opacity: bridge.recording || bridge.busy ? 1 : 0
                text: bridge.elapsed
                color: Theme.muted
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fsSmall
                Behavior on opacity { NumberAnimation { duration: Theme.baseMs } }
            }

            PillButton {
                compact: true
                text: bridge.liveSourceLabel
                enabled: !bridge.recording && !bridge.busy
                onClicked: bridge.cycleLiveSource()
                ToolTip.visible: hovered
                ToolTip.text: "Микрофон, звук компьютера или оба сразу"
            }

            IconButton {
                iconName: "overlay"
                ink: root.overlayOn ? Theme.text : Theme.muted
                onClicked: bridge.setSetting("caption_overlay", !root.overlayOn)
                ToolTip.visible: hovered
                ToolTip.text: root.overlayOn ? "Скрыть субтитры зала" : "Показать субтитры зала"
            }

            IconButton {
                iconName: "copy"
                enabled: bridge.text.length > 0
                onClicked: bridge.copyText()
                ToolTip.visible: hovered
                ToolTip.text: "Скопировать расшифровку"
            }

            IconButton {
                visible: !root.embedded
                iconName: "expand"
                onClicked: root.requestApp()
                ToolTip.visible: hovered
                ToolTip.text: "Открыть окно приложения"
            }

            IconButton {
                visible: !root.embedded
                iconName: "collapse"
                onClicked: root.requestIsland()
                ToolTip.visible: hovered
                ToolTip.text: "Свернуть в остров"
            }
        }

        CaptionStage {
            Layout.fillWidth: true
            Layout.fillHeight: true
            previous: root.previousText
            confirmed: bridge.confirmedCaption
            pending: bridge.partialCaption
            placeholder: root.stageHint
            pixelSize: root.embedded ? 30 : 34
            maxLines: 3
            align: Text.AlignHCenter
        }

        // Лента последних завершённых фраз. Новая строка приезжает снизу,
        // остальные съезжают: видно, что текст накапливается.
        ListView {
            id: tape
            visible: root.showTape
            property bool followsLive: true
            Layout.fillWidth: true
            Layout.preferredHeight: root.showTape ? 84 : 0
            clip: true
            spacing: 2
            model: bridge.segments
            boundsBehavior: Flickable.StopAtBounds
            onMovementStarted: followsLive = false

            delegate: Item {
                required property var modelData
                required property int index
                width: tape.width
                height: 26
                opacity: Math.max(0.3, 1.0 - (tape.count - 1 - index) * 0.22)

                Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: parent.modelData.text
                    color: parent.index === tape.count - 1 ? Theme.text : Theme.muted
                    font.pixelSize: parent.index === tape.count - 1 ? 13 : 12
                    font.family: Theme.fontFamily
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
            }

            add: Transition {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.baseMs }
                NumberAnimation {
                    property: "y"
                    from: 18
                    duration: Theme.slowMs
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easeOut
                }
            }
            displaced: Transition {
                NumberAnimation {
                    properties: "x,y"
                    duration: Theme.slowMs
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easeOut
                }
            }

            Connections {
                target: bridge
                function onSegmentsChanged() {
                    if (tape.followsLive && tape.count > 0)
                        tape.positionViewAtEnd()
                }
            }
        }

        PillButton {
            visible: root.showTape && !tape.followsLive && tape.count > 0
            compact: true
            Layout.alignment: Qt.AlignHCenter
            text: "К текущему тексту"
            onClicked: {
                tape.followsLive = true
                tape.positionViewAtEnd()
            }
        }

        // Управление. Уровень стоит прямо над кнопкой: видно, слышит ли
        // приложение источник, до того как нажали «Слушать».
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 10

            Waveform {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredHeight: 20
                bars: 48
                barH: 20
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Item { Layout.fillWidth: true }

                PillButton {
                    text: bridge.recording ? "Стоп" : bridge.busy ? "Останавливаем" : "Слушать"
                    primary: true
                    enabled: !bridge.busy || bridge.recording
                    onClicked: bridge.toggleRecording()
                }

                PillButton {
                    visible: bridge.busy
                    compact: true
                    text: bridge.recording ? "Отменить" : "Остановить сейчас"
                    onClicked: bridge.forceStop()
                    ToolTip.visible: hovered
                    ToolTip.text: "Остановить без сохранения незавершённой фразы"
                }

                Item { Layout.fillWidth: true }
            }
        }
    }
}
