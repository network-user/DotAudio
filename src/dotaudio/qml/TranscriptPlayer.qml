import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import "Theme.js" as Theme

// Транспорт аудио для страницы транскрибации: play/pause, seek,
// скорость, воспроизведение одной фразы и повтор последней.
RowLayout {
    id: root

    spacing: Theme.gapSm
    visible: root.source.length > 0

    property string source: ""
    property bool playing: media.playbackState === MediaPlayer.PlayingState
    property real position: media.position
    property real duration: media.duration
    readonly property real playbackRate: media.playbackRate
    readonly property bool canRepeatPhrase: root._phraseEndSec >= 0

    // Конец текущей фразы в мс; < 0 - без автопаузы.
    property real _phraseEndMs: -1
    // Последний диапазон фразы (секунды) для repeatPhrase.
    property real _phraseStartSec: -1
    property real _phraseEndSec: -1

    function clock(milliseconds) {
        var total = Math.max(0, Math.round(Number(milliseconds) / 1000))
        var minutes = Math.floor(total / 60)
        var seconds = total % 60
        return (minutes < 10 ? "0" : "") + minutes
            + ":" + (seconds < 10 ? "0" : "") + seconds
    }

    readonly property string rateLabel: {
        var r = root.playbackRate
        if (Math.abs(r - 1.0) < 0.01)
            return "1×"
        if (Math.abs(r - 0.75) < 0.01)
            return "0.75×"
        if (Math.abs(r - 1.25) < 0.01)
            return "1.25×"
        return Number(r).toFixed(2).replace(/\.?0+$/, "") + "×"
    }

    function cyclePlaybackRate() {
        var r = media.playbackRate
        if (Math.abs(r - 0.75) < 0.01)
            media.playbackRate = 1.0
        else if (Math.abs(r - 1.0) < 0.01)
            media.playbackRate = 1.25
        else
            media.playbackRate = 0.75
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
        root._phraseStartSec = Number(startSec)
        root._phraseEndSec = Number(endSec)
        root._phraseEndMs = Number(endSec) * 1000
        root.seekSeconds(startSec)
        media.play()
    }

    function repeatPhrase() {
        if (root._phraseStartSec >= 0 && root._phraseEndSec >= 0)
            root.playPhrase(root._phraseStartSec, root._phraseEndSec)
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

    IconButton {
        iconName: "redo"
        enabled: root.canRepeatPhrase
        onClicked: root.repeatPhrase()
        ToolTip.visible: hovered
        ToolTip.text: "Ещё раз"
    }

    PillButton {
        text: root.rateLabel
        compact: true
        onClicked: root.cyclePlaybackRate()
        ToolTip.visible: hovered
        ToolTip.text: "Скорость воспроизведения"
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
