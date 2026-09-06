import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var player: null
    property bool editable: true
    property bool showEmptyHint: true
    property string emptyMessage: "Расшифровка появится после первой завершённой фразы."
    color: "#151517"
    radius: 20
    border.width: 1
    border.color: "#0cffffff"

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
        width: parent.width - 60
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        text: root.emptyMessage
        color: "#8e8e93"
        font.pixelSize: 14
    }

    ListView {
        id: transcript
        anchors.fill: parent
        anchors.margins: 12
        clip: true
        spacing: 8
        model: bridge.segments
        ScrollBar.vertical: ScrollBar { }
        delegate: Rectangle {
            required property var modelData
            property bool active: root.player !== null
                                  && root.player.position >= Math.round(Number(modelData.start) * 1000)
                                  && root.player.position < Math.round(Number(modelData.end) * 1000)
            width: transcript.width
            implicitHeight: editor.implicitHeight + 22
            radius: 15
            color: active ? "#1b2a3c" : segmentMouse.containsMouse ? "#242426" : "#1c1c1e"
            border.color: active ? "#660a84ff" : "#0cffffff"
            border.width: 1
            Behavior on color { ColorAnimation { duration: 140 } }
            Behavior on border.color { ColorAnimation { duration: 140 } }
            MouseArea { id: segmentMouse; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }

            RowLayout {
                anchors.fill: parent
                anchors.margins: 11
                spacing: 10
                Button {
                    id: timestampButton
                    Layout.alignment: Qt.AlignTop
                    text: root.timecode(modelData.start)
                    enabled: root.player !== null
                    hoverEnabled: true
                    onClicked: {
                        root.player.position = Math.round(Number(modelData.start) * 1000)
                        root.player.play()
                    }
                    contentItem: Text {
                        text: timestampButton.text
                        color: active ? "#8dc6ff" : "#aeaeb2"
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle { radius: 9; color: timestampButton.down ? "#34506f" : timestampButton.hovered ? "#293846" : "#0effffff"; border.width: 1; border.color: "#0cffffff"; Behavior on color { ColorAnimation { duration: 120 } } }
                }
                TextArea {
                    id: editor
                    Layout.fillWidth: true
                    readOnly: !root.editable
                    text: modelData.text
                    wrapMode: TextEdit.Wrap
                    color: "#f5f5f7"
                    placeholderText: "Пустой сегмент"
                    selectByMouse: true
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
