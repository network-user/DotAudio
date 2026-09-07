import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var player: null
    property var segments: []
    property real playbackSeconds: player ? player.position / 1000 : 0
    property var activeCue: cueAt(playbackSeconds)

    radius: 20
    color: "#e814161a"
    border.color: "#22ffffff"
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
        anchors.margins: 16
        spacing: 8

        Label {
            text: root.activeCue && root.activeCue.words ? "KARAOKE · ПО СЛОВАМ" : "KARAOKE · ФРАЗА"
            color: "#a6a7ab"
            font.pixelSize: 9
            font.bold: true
            font.letterSpacing: 1.1
        }

        Flow {
            Layout.fillWidth: true
            spacing: 8
            Repeater {
                model: root.activeCue && root.activeCue.words ? root.activeCue.words : []
                delegate: Text {
                    required property var modelData
                    property bool active: root.playbackSeconds >= Number(modelData.start)
                                          && root.playbackSeconds < Number(modelData.end)
                    text: modelData.text
                    color: active ? "#f3f3f1" : root.playbackSeconds >= Number(modelData.end) ? "#d1d1d6" : "#a6a7ab"
                    font.pixelSize: active ? 24 : 19
                    font.weight: active ? Font.DemiBold : Font.Normal
                    scale: active ? 1.04 : 1
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Behavior on font.pixelSize { NumberAnimation { duration: 120 } }
                    Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
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
