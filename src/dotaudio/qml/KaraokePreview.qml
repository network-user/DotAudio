import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Караоке-просмотр. Текущее слово выделяется кеглем, начертанием и яркостью
// сразу: на светлом кадре видео одной яркости не хватает.
Rectangle {
    id: root
    property var player: null
    property var segments: []
    // Скрытый просмотр не считает: страница караоке остаётся в памяти, пока
    // пользователь работает в другом разделе, и не должна ничего пересчитывать.
    property real playbackSeconds: player && root.visible ? player.position / 1000 : 0
    property var activeCue: null

    radius: Theme.radiusLg
    color: Theme.islandFill
    border.color: Theme.border
    border.width: 1

    function cueAt(position) {
        for (var i = 0; i < segments.length; i++) {
            var cue = segments[i]
            if (position >= Number(cue.start) && position < Number(cue.end))
                return cue
        }
        return segments.length ? segments[0] : null
    }

    // Плеер сообщает позицию несколько раз в секунду. Пока играет одна и та же
    // фраза, перебирать весь список незачем: он может быть длиной в час записи.
    function refreshCue() {
        var position = root.playbackSeconds
        var current = root.activeCue
        if (current
                && position >= Number(current.start)
                && position < Number(current.end))
            return
        root.activeCue = cueAt(position)
    }

    onPlaybackSecondsChanged: refreshCue()
    onSegmentsChanged: { root.activeCue = null; refreshCue() }
    Component.onCompleted: refreshCue()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.gapLg
        spacing: Theme.gapSm

        Label {
            text: root.activeCue && root.activeCue.words ? "KARAOKE · ПО СЛОВАМ" : "KARAOKE · ФРАЗА"
            color: Theme.muted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsMicro
            font.weight: Font.DemiBold
            font.letterSpacing: 1.1
        }

        Flow {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            Repeater {
                model: root.activeCue && root.activeCue.words ? root.activeCue.words : []
                delegate: Text {
                    required property var modelData
                    property bool active: root.playbackSeconds >= Number(modelData.start)
                                          && root.playbackSeconds < Number(modelData.end)
                    text: modelData.text
                    color: active ? Theme.text
                         : root.playbackSeconds >= Number(modelData.end) ? Theme.muted
                         : Theme.faint
                    font.family: Theme.fontFamily
                    font.pixelSize: active ? Theme.fsHero : Theme.fsLead
                    font.weight: active ? Font.DemiBold : Font.Normal
                    scale: active ? 1.04 : 1
                    Behavior on color { ColorAnimation { duration: Theme.instantMs } }
                    Behavior on font.pixelSize { NumberAnimation { duration: Theme.instantMs } }
                    Behavior on scale {
                        NumberAnimation {
                            duration: Theme.fastMs
                            easing.type: Easing.Bezier
                            easing.bezierCurve: Theme.easeSpring
                        }
                    }
                }
            }
        }

        Text {
            visible: !root.activeCue || !root.activeCue.words
            Layout.fillWidth: true
            text: root.activeCue ? root.activeCue.text : "После распознавания здесь будет караоке-текст."
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsLead
            font.weight: Font.DemiBold
            wrapMode: Text.Wrap
        }
    }
}
