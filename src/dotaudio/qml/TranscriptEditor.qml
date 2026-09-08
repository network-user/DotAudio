import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Список фраз с правкой. Активный сегмент подсвечивается кромкой и меткой
// времени, а не цветом текста: палитра монохромная, и состояние должно
// читаться на любом мониторе.
Rectangle {
    id: root
    property var player: null
    property bool editable: true
    property bool showEmptyHint: true
    property bool followLatest: !editable
    property string emptyMessage: "Расшифровка появится после первой завершённой фразы."
    property int observedSegmentCount: 0
    color: Theme.surface
    radius: Theme.radiusLg
    border.width: 1
    border.color: Theme.border
    clip: true

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

    Label {
        visible: root.showEmptyHint && bridge.segments.length === 0
        anchors.centerIn: parent
        width: Math.max(0, parent.width - 60)
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        text: root.emptyMessage
        color: Theme.muted
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fsBody
    }

    Connections {
        target: bridge
        // Список реагирует на список, а не на любое изменение в приложении.
        function onSegmentsChanged() {
            var count = bridge.segments.length
            if (root.followLatest && count > root.observedSegmentCount) {
                root.observedSegmentCount = count
                transcript.positionViewAtEnd()
            } else if (count < root.observedSegmentCount) {
                root.observedSegmentCount = count
            }
        }
    }

    ListView {
        id: transcript
        anchors.fill: parent
        anchors.margins: 12
        clip: true
        spacing: 8
        model: bridge.segments
        Component.onCompleted: root.observedSegmentCount = bridge.segments.length
        ScrollBar.vertical: ScrollBar { }

        // Новая фраза приезжает снизу и проявляется: видно, что список пополнился,
        // без прыжка всей ленты.
        add: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.baseMs }
            NumberAnimation {
                property: "y"
                from: 14
                duration: Theme.slowMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
        displaced: Transition {
            NumberAnimation {
                properties: "y"
                duration: Theme.reflowMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }

        delegate: Rectangle {
            required property var modelData
            // Подсветку двигает только видимый плеер: скрытая страница не
            // пересчитывает каждую строку на каждом кадре воспроизведения.
            property bool active: root.player !== null && root.visible
                                  && root.player.position >= Math.round(Number(modelData.start) * 1000)
                                  && root.player.position < Math.round(Number(modelData.end) * 1000)
            width: transcript.width
            implicitHeight: editor.implicitHeight + 22
            radius: Theme.radiusMd
            color: active || segmentMouse.containsMouse ? Theme.surface2 : Theme.surface
            border.color: active ? Theme.borderHi : Theme.border
            border.width: 1
            Behavior on color { ColorAnimation { duration: Theme.fastMs } }
            Behavior on border.color { ColorAnimation { duration: Theme.fastMs } }
            MouseArea { id: segmentMouse; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }

            RowLayout {
                anchors.fill: parent
                anchors.margins: 11
                spacing: 10
                Button {
                    id: timestampButton
                    Layout.alignment: Qt.AlignTop
                    implicitHeight: 24
                    padding: 7
                    text: root.timecode(modelData.start)
                    enabled: root.player !== null
                    hoverEnabled: true
                    scale: timestampButton.down ? 0.94 : 1
                    Behavior on scale {
                        NumberAnimation {
                            duration: Theme.fastMs
                            easing.type: Easing.Bezier
                            easing.bezierCurve: Theme.easeSpring
                        }
                    }
                    onClicked: {
                        root.player.position = Math.round(Number(modelData.start) * 1000)
                        root.player.play()
                    }
                    contentItem: Text {
                        text: timestampButton.text
                        color: active ? Theme.text : Theme.muted
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.fsSmall
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                    }
                    background: Rectangle {
                        radius: 8
                        color: timestampButton.down ? Theme.fillPress
                             : timestampButton.hovered ? Theme.fillHi
                             : Theme.fill
                        border.width: 1
                        border.color: active ? Theme.borderHi : Theme.hairline
                        Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                    }
                }
                TextArea {
                    id: editor
                    Layout.fillWidth: true
                    readOnly: !root.editable
                    text: modelData.text
                    wrapMode: TextEdit.Wrap
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fsBody
                    placeholderText: "Пустой сегмент"
                    placeholderTextColor: Theme.faint
                    selectByMouse: true
                    selectionColor: Theme.fillPress
                    selectedTextColor: Theme.text
                    padding: 3
                    background: null
                    onActiveFocusChanged: {
                        if (!activeFocus && root.editable && text !== modelData.text)
                            bridge.editSegment(Number(modelData.id), text)
                    }
                }
            }
        }
    }
}
