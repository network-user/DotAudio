import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var player: null
    property var segments: []
    property real playbackSeconds: player ? player.position / 1000 : 0
    property var activeCue: cueAt(playbackSeconds)

    radius: 18
    color: "#10141be8"
    border.color: "#ffffff20"
    border.width: 1

    function cueAt(position) {
        for (var i = 0; i < segments.length; i++) {
            var cue = segments[i]
            if (position >= Number(cue.start) && position < Number(cue.end))
                return cue
        }
        return segments.length ? segments[0] : null
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 7

        Label {
            text: root.activeCue && root.activeCue.words ? "KARAOKE · WORD TIMESTAMPS" : "KARAOKE · ФРАЗА"
            color: "#86dfbf"
            font.pixelSize: 9
            font.bold: true
            font.letterSpacing: 1.1
        }

        Flow {
            Layout.fillWidth: true
            spacing: 7
            Repeater {
                model: root.activeCue && root.activeCue.words ? root.activeCue.words : []
                delegate: Text {
                    required property var modelData
                    property bool active: root.playbackSeconds >= Number(modelData.start)
                                          && root.playbackSeconds < Number(modelData.end)
                    text: modelData.text
                    color: active ? "#ffffff" : root.playbackSeconds >= Number(modelData.end) ? "#7ae0bd" : "#8392a3"
                    font.pixelSize: active ? 23 : 19
                    font.weight: active ? Font.DemiBold : Font.Normal
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Behavior on font.pixelSize { NumberAnimation { duration: 120 } }
                }
            }
        }

        Text {
            visible: !root.activeCue || !root.activeCue.words
            Layout.fillWidth: true
            text: root.activeCue ? root.activeCue.text : "После распознавания здесь будет караоке-текст."
            color: "#f1f5f7"
            font.pixelSize: 21
            font.weight: Font.DemiBold
            wrapMode: Text.Wrap
        }
    }
}
