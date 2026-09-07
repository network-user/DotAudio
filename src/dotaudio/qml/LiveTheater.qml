import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    property bool embedded: false
    color: Theme.surface
    radius: embedded ? 24 : 28
    border.width: 1
    border.color: Theme.border
    clip: true

    signal requestIsland()
    signal requestApp()

    readonly property var currentSegment: bridge.segments.length ? bridge.segments[bridge.segments.length - 1] : null
    readonly property var previousSegment: bridge.segments.length >= 2 ? bridge.segments[bridge.segments.length - 2] : null
    readonly property var captionWords: currentSegment && currentSegment.words ? currentSegment.words : []
    readonly property string captionKey: currentSegment ? String(currentSegment.id) : ""
    readonly property string sourceLabel: String(bridge.settings.live_source) === "microphone" ? "Микрофон" : "Звук системы"
    readonly property bool overlayOn: Boolean(bridge.settings.caption_overlay)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            spacing: 10
            Label {
                text: "Live"
                color: Theme.text
                font.pixelSize: 15
                font.weight: Font.DemiBold
                font.family: Theme.fontFamily
            }
            Label {
                text: root.sourceLabel
                color: Theme.muted
                font.pixelSize: 11
                font.family: Theme.fontFamily
            }
            Item { Layout.fillWidth: true }
            Label {
                visible: bridge.recording || bridge.busy
                text: bridge.elapsed
                color: Theme.muted
                font.family: Theme.monoFamily
                font.pixelSize: 11
            }
            PillButton {
                text: bridge.recording ? "Стоп" : "Слушать"
                primary: true
                enabled: !bridge.busy || bridge.recording
                onClicked: bridge.toggleRecording()
            }
            PillButton {
                visible: bridge.busy
                text: "Отмена"
                onClicked: bridge.cancel()
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -12
                spacing: 10

                Text {
                    visible: root.previousSegment !== null
                    width: parent.width
                    text: root.previousSegment ? root.previousSegment.text : ""
                    color: Theme.muted
                    font.pixelSize: 15
                    font.family: Theme.fontFamily
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    wrapMode: Text.NoWrap
                }

                CaptionText {
                    width: parent.width
                    visible: bridge.caption.length > 0
                    text: bridge.caption
                    words: root.captionWords
                    segmentKey: root.captionKey
                    pixelSize: 32
                    maxLines: 3
                    weight: Font.DemiBold
                }

                Text {
                    visible: bridge.caption.length === 0
                    width: parent.width
                    text: "Запустите Live, текст появится после первой фразы"
                    color: Theme.muted
                    font.pixelSize: 15
                    font.family: Theme.fontFamily
                    wrapMode: Text.Wrap
                }
            }
        }

        Waveform {
            visible: bridge.recording
            Layout.fillWidth: true
            Layout.preferredHeight: 20
            bars: 28
            barH: 20
        }

        ListView {
            id: tape
            Layout.fillWidth: true
            Layout.preferredHeight: 88
            clip: true
            spacing: 6
            model: bridge.segments
            boundsBehavior: Flickable.StopAtBounds
            delegate: Text {
                required property var modelData
                required property int index
                width: tape.width
                text: modelData.text
                color: index === tape.count - 1 ? Theme.text : Theme.muted
                font.pixelSize: 13
                font.family: Theme.fontFamily
                elide: Text.ElideRight
                maximumLineCount: 1
            }
            Connections {
                target: bridge
                function onChanged() {
                    if (tape.count > 0)
                        tape.positionViewAtEnd()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PillButton {
                text: "Копировать"
                enabled: bridge.text.length > 0
                onClicked: bridge.copyText()
            }
            PillButton {
                text: "На экран"
                primary: root.overlayOn
                onClicked: bridge.setSetting("caption_overlay", !root.overlayOn)
            }
            Item { Layout.fillWidth: true }
            PillButton {
                visible: !root.embedded
                text: "В приложение"
                onClicked: root.requestApp()
            }
            PillButton {
                text: "Остров"
                onClicked: root.requestIsland()
            }
        }
    }
}
