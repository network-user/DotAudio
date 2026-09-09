import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import "Theme.js" as Theme

// Транспорт аудио для страницы транскрибации: play/pause всего файла,
// seek, громкость, скорость, волна peaks и воспроизведение одной фразы.
Rectangle {
    id: root

    property string source: ""
    property var segments: []
    property var peaks: []
    property real peaksDuration: 0

    property bool playing: media.playbackState === MediaPlayer.PlayingState
    property alias position: media.position
    property alias duration: media.duration
    property bool compact: false
    readonly property real playbackRate: media.playbackRate
    readonly property bool canRepeatPhrase: root._phraseEndSec >= 0
    readonly property bool muted: audio.muted || audio.volume <= 0.001

    // Конец текущей фразы в мс; < 0 - без автопаузы.
    property real _phraseEndMs: -1
    property real _phraseStartSec: -1
    property real _phraseEndSec: -1
    property real _volumeBeforeMute: 0.85

    visible: root.source.length > 0
    implicitHeight: body.implicitHeight + 2 * Theme.padCard
    radius: Theme.radiusLg
    color: Theme.surface
    border.width: 1
    border.color: Theme.border

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

    function toggleMute() {
        if (root.muted) {
            audio.muted = false
            if (audio.volume <= 0.001)
                audio.volume = root._volumeBeforeMute > 0.001 ? root._volumeBeforeMute : 0.85
        } else {
            root._volumeBeforeMute = audio.volume
            audio.muted = true
        }
    }

    MediaPlayer {
        id: media
        source: root.source
        audioOutput: audio
        onPositionChanged: {
            if (root._phraseEndMs < 0)
                return
            if (position >= root._phraseEndMs) {
                root._phraseEndMs = -1
                media.pause()
            }
        }
    }

    AudioOutput {
        id: audio
        volume: 0.85
    }

    ColumnLayout {
        id: body
        anchors.fill: parent
        anchors.margins: Theme.padCard
        spacing: Theme.gapSm

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            Label {
                text: "Прослушать запись"
                color: Theme.text
                font.pixelSize: Theme.fsLabel
                font.weight: Font.DemiBold
            }
            Label {
                Layout.fillWidth: true
                text: root.playing
                      ? (root._phraseEndMs >= 0 ? "фраза" : "весь файл")
                      : "Пробел - старт или пауза"
                color: Theme.faint
                font.pixelSize: Theme.fsMicro
                elide: Text.ElideRight
            }
        }

        MediaTimeline {
            id: wave
            Layout.fillWidth: true
            implicitHeight: root.compact ? 36 : 52
            player: media
            segments: root.segments
            peaks: root.peaks
            peaksDuration: root.peaksDuration
            visible: root.peaks.length > 0 || root.duration > 0
            onSeeked: root.clearPhraseRange()
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gapSm

            IconButton {
                iconName: root.playing ? "pause" : "media"
                glyph: 18
                implicitWidth: 36
                implicitHeight: 36
                onClicked: root.toggle()
                ToolTip.visible: hovered
                ToolTip.text: root.playing ? "Пауза" : "Слушать весь файл"
            }

            IconButton {
                iconName: "redo"
                enabled: root.canRepeatPhrase
                onClicked: root.repeatPhrase()
                ToolTip.visible: hovered
                ToolTip.text: "Повторить последнюю фразу"
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

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            visible: !root.compact

            IconButton {
                iconName: root.muted ? "mute" : "volume"
                onClicked: root.toggleMute()
                ToolTip.visible: hovered
                ToolTip.text: root.muted ? "Включить звук" : "Без звука"
            }

            Slider {
                id: volume
                Layout.preferredWidth: 120
                from: 0
                to: 1
                value: audio.muted ? 0 : audio.volume
                onMoved: {
                    audio.muted = false
                    audio.volume = value
                    if (value > 0.001)
                        root._volumeBeforeMute = value
                }
                background: Rectangle {
                    x: volume.leftPadding
                    y: volume.topPadding + volume.availableHeight / 2 - height / 2
                    width: volume.availableWidth
                    height: 3
                    radius: 2
                    color: Theme.fill
                    Rectangle {
                        width: volume.visualPosition * parent.width
                        height: parent.height
                        radius: 2
                        color: Theme.muted
                    }
                }
                handle: Rectangle {
                    x: volume.leftPadding
                        + volume.visualPosition * (volume.availableWidth - width)
                    y: volume.topPadding + volume.availableHeight / 2 - height / 2
                    width: 10
                    height: 10
                    radius: 5
                    color: Theme.text
                }
            }

            Label {
                text: Math.round((audio.muted ? 0 : audio.volume) * 100) + "%"
                color: Theme.faint
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fsMicro
                Layout.preferredWidth: 36
            }

            Item { Layout.fillWidth: true }

            Label {
                visible: root.peaks.length === 0 && root.duration > 0
                text: "Волна строится…"
                color: Theme.faint
                font.pixelSize: Theme.fsMicro
            }
        }
    }
}
