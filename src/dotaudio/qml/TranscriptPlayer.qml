import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import "Theme.js" as Theme

// Транспорт аудио для страницы транскрибации: play/pause, seek,
// воспроизведение одной фразы до её конца.
RowLayout {
    id: root

    spacing: Theme.gapSm
    visible: root.source.length > 0

    property string source: ""
    property bool playing: media.playbackState === MediaPlayer.PlayingState
    property real position: media.position
    property real duration: media.duration

    // Конец текущей фразы в мс; < 0 — без автопаузы.
    property real _phraseEndMs: -1

    function clock(milliseconds) {
        var total = Math.max(0, Math.round(Number(milliseconds) / 1000))
        var minutes = Math.floor(total / 60)
        var seconds = total % 60
        return (minutes < 10 ? "0" : "") + minutes
            + ":" + (seconds < 10 ? "0" : "") + seconds
    }

    function play() {
        root.clearPhraseRange()
        media.play()
    }

    function pause() {
        root.clearPhraseRange()
        media.pause()
    }

    function toggle() {
        if (media.playbackState === MediaPlayer.PlayingState)
            root.pause()
        else
            root.play()
    }

    function seekSeconds(sec) {
        media.position = Math.max(0, Number(sec) * 1000)
    }

    function playPhrase(startSec, endSec) {
        root._phraseEndMs = Number(endSec) * 1000
        root.seekSeconds(startSec)
        media.play()
    }

    function clearPhraseRange() {
        root._phraseEndMs = -1
    }

    MediaPlayer {
        id: media
        source: root.source
        audioOutput: AudioOutput {}
        onPositionChanged: {
            if (root._phraseEndMs < 0)
                return
            if (position >= root._phraseEndMs) {
                root._phraseEndMs = -1
                media.pause()
            }
        }
    }

    IconButton {
        iconName: root.playing ? "stop" : "live"
        onClicked: root.toggle()
        ToolTip.visible: hovered
        ToolTip.text: root.playing ? "Пауза" : "Воспроизвести"
    }

    Label {
        text: root.clock(root.position)
        color: Theme.muted
        font.family: Theme.monoFamily
        font.pixelSize: Theme.fsSmall
    }

    Slider {
        id: seek
        Layout.fillWidth: true
        from: 0
        to: Math.max(1, root.duration)
        value: pressed ? value : root.position
        onMoved: {
            root.clearPhraseRange()
            media.position = value
        }
        background: Rectangle {
            x: seek.leftPadding
            y: seek.topPadding + seek.availableHeight / 2 - height / 2
            width: seek.availableWidth
            height: 3
            radius: 2
            color: Theme.fill
            Rectangle {
                width: seek.visualPosition * parent.width
                height: parent.height
                radius: 2
                color: Theme.text
            }
        }
        handle: Rectangle {
            x: seek.leftPadding
                + seek.visualPosition * (seek.availableWidth - width)
            y: seek.topPadding + seek.availableHeight / 2 - height / 2
            width: 12
            height: 12
            radius: 6
            color: Theme.text
        }
    }

    Label {
        text: root.clock(root.duration)
        color: Theme.faint
        font.family: Theme.monoFamily
        font.pixelSize: Theme.fsSmall
    }
}
