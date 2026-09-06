import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var player: null
    property bool editable: true
    property bool showEmptyHint: true
    property string emptyMessage: "Расшифровка появится после первой завершённой фразы."
    color: "#17181c"
    radius: 18
    border.width: 1
    border.color: "#2e3037"

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
        color: "#777981"
        font.pixelSize: 14
    }

    ListView {
        id: transcript
        anchors.fill: parent
        anchors.margins: 10
        clip: true
        spacing: 6
        model: bridge.segments
        ScrollBar.vertical: ScrollBar { }
        delegate: Rectangle {
            required property var modelData
            property bool active: root.player !== null
                                  && root.player.position >= Math.round(Number(modelData.start) * 1000)
                                  && root.player.position < Math.round(Number(modelData.end) * 1000)
            width: transcript.width
            implicitHeight: editor.implicitHeight + 18
            radius: 12
            color: active ? "#262931" : "#1d1e23"
            border.color: active ? "#e9ebee" : "#2d2f36"
            border.width: active ? 1 : 0

            RowLayout {
                anchors.fill: parent
                anchors.margins: 9
                spacing: 9
                Button {
                    id: timestampButton
                    Layout.alignment: Qt.AlignTop
                    text: root.timecode(modelData.start)
                    enabled: root.player !== null
                    onClicked: {
                        root.player.position = Math.round(Number(modelData.start) * 1000)
                        root.player.play()
                    }
                    contentItem: Text {
                        text: timestampButton.text
                        color: "#b7bbc4"
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle { radius: 8; color: timestampButton.down ? "#363943" : "#292b32" }
                }
                TextArea {
                    id: editor
                    Layout.fillWidth: true
                    readOnly: !root.editable
                    text: modelData.text
                    wrapMode: TextEdit.Wrap
                    color: "#f0f1f2"
                    placeholderText: "Пустой сегмент"
                    selectByMouse: true
                    padding: 2
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
