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
    property int selectedIndex: -1
    property bool editableEdges: false
    readonly property real playbackRate: media.playbackRate
    readonly property bool canRepeatPhrase: root._phraseEndSec >= 0
    readonly property bool muted: audio.muted || audio.volume <= 0.001

    // Конец текущей фразы в мс; < 0 - без автопаузы.
    property real _phraseEndMs: -1
    property real _phraseStartSec: -1
    property real _phraseEndSec: -1
    property real _volumeBeforeMute: 0.85
    property real inPointSec: -1
    property real outPointSec: -1
    property bool loopRegion: false

    signal edgeChanged(int index, real start, real end)
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

    readonly property var rateChoices: [
        0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0
    ]

    readonly property string rateLabel: root.formatRate(root.playbackRate)

    function formatRate(value) {
        var r = Number(value)
        if (!isFinite(r) || r <= 0)
            return "1×"
        if (Math.abs(r - 1.0) < 0.01)
            return "Обычная"
        var labels = {
            "0.25": "0.25×", "0.5": "0.5×", "0.75": "0.75×",
            "1.25": "1.25×", "1.5": "1.5×", "1.75": "1.75×", "2": "2×"
        }
        for (var i = 0; i < root.rateChoices.length; ++i) {
            var choice = root.rateChoices[i]
            if (Math.abs(choice - r) < 0.01) {
                var key = String(choice)
                return labels[key] || (choice + "×")
            }
        }
        return r.toFixed(2).replace(/\.?0+$/, "") + "×"
    }

    function setPlaybackRate(value) {
        var r = Number(value)
        if (!isFinite(r) || r <= 0)
            return
        media.playbackRate = Math.max(0.25, Math.min(2.0, r))
        rateMenu.close()
    }

    function rateSelected(value) {
        return Math.abs(Number(value) - root.playbackRate) < 0.01
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

    function skipBy(deltaSec) {
        root.clearPhraseRange()
        var next = Math.max(0, Number(root.position) / 1000 + Number(deltaSec))
        if (root.duration > 0)
            next = Math.min(root.duration / 1000, next)
        root.seekSeconds(next)
    }

    function markIn() {
        root.inPointSec = Number(root.position) / 1000
        if (root.outPointSec >= 0 && root.outPointSec <= root.inPointSec)
            root.outPointSec = -1
    }

    function markOut() {
        root.outPointSec = Number(root.position) / 1000
        if (root.inPointSec >= 0 && root.outPointSec <= root.inPointSec)
            root.inPointSec = Math.max(0, root.outPointSec - 0.25)
    }

    function clearAbRegion() {
        root.inPointSec = -1
        root.outPointSec = -1
        root.loopRegion = false
    }

    function playAbRegion() {
        if (root.inPointSec < 0 || root.outPointSec <= root.inPointSec)
            return
        root.loopRegion = true
        root.playPhrase(root.inPointSec, root.outPointSec)
    }

    MediaPlayer {
        id: media
        source: root.source
        audioOutput: audio
        onPositionChanged: {
            if (root._phraseEndMs >= 0 && position >= root._phraseEndMs) {
                root._phraseEndMs = -1
                if (root.loopRegion && root.inPointSec >= 0 && root.outPointSec > root.inPointSec) {
                    root.playPhrase(root.inPointSec, root.outPointSec)
                    return
                }
                media.pause()
                return
            }
            if (root.loopRegion && root.inPointSec >= 0 && root.outPointSec > root.inPointSec) {
                if (position / 1000 >= root.outPointSec) {
                    root.seekSeconds(root.inPointSec)
                    media.play()
                }
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
            selectedIndex: root.selectedIndex
            editable: root.editableEdges && root.selectedIndex >= 0
            visible: root.peaks.length > 0 || root.duration > 0
            onSeeked: root.clearPhraseRange()
            onEdgeChanged: function (index, start, end) {
                root.edgeChanged(index, start, end)
            }
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
                text: "I"
                compact: true
                onClicked: root.markIn()
                ToolTip.visible: hovered
                ToolTip.text: "In-точка (I)"
            }
            PillButton {
                text: "O"
                compact: true
                onClicked: root.markOut()
                ToolTip.visible: hovered
                ToolTip.text: "Out-точка (O)"
            }
            PillButton {
                text: root.loopRegion ? "Loop●" : "Loop"
                compact: true
                enabled: root.inPointSec >= 0 && root.outPointSec > root.inPointSec
                onClicked: {
                    if (root.loopRegion) {
                        root.loopRegion = false
                        root.clearPhraseRange()
                    } else {
                        root.playAbRegion()
                    }
                }
                ToolTip.visible: hovered
                ToolTip.text: "Цикл In–Out"
            }
            PillButton {
                text: "−1с"
                compact: true
                onClicked: root.skipBy(-1)
            }
            PillButton {
                text: "+1с"
                compact: true
                onClicked: root.skipBy(1)
            }

            PillButton {
                id: rateBtn
                text: root.rateLabel === "Обычная" ? "1×" : root.rateLabel
                compact: true
                onClicked: rateMenu.open()
                ToolTip.visible: hovered && !rateMenu.visible
                ToolTip.text: "Скорость воспроизведения"
            }

            Popup {
                id: rateMenu
                parent: Overlay.overlay
                x: {
                    var pos = rateBtn.mapToItem(Overlay.overlay, 0, 0)
                    return Math.max(8, Math.min(pos.x, Overlay.overlay.width - implicitWidth - 8))
                }
                y: {
                    var below = rateBtn.mapToItem(Overlay.overlay, 0, rateBtn.height).y + 6
                    if (below + implicitHeight <= Overlay.overlay.height - 8)
                        return below
                    return Math.max(8, rateBtn.mapToItem(Overlay.overlay, 0, 0).y - implicitHeight - 6)
                }
                padding: 6
                modal: false
                focus: true
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                implicitWidth: 132
                background: Rectangle {
                    radius: Theme.radiusMd
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.borderHi
                }
                contentItem: ColumnLayout {
                    spacing: 2
                    Label {
                        Layout.fillWidth: true
                        Layout.leftMargin: 8
                        Layout.rightMargin: 8
                        Layout.topMargin: 4
                        Layout.bottomMargin: 2
                        text: "Скорость"
                        color: Theme.muted
                        font.pixelSize: Theme.fsMicro
                        font.weight: Font.DemiBold
                    }
                    Repeater {
                        model: root.rateChoices
                        delegate: Item {
                            id: rateRow
                            required property real modelData
                            Layout.fillWidth: true
                            implicitHeight: 32
                            readonly property bool selected: root.rateSelected(rateRow.modelData)
                            Rectangle {
                                anchors.fill: parent
                                radius: Theme.radiusSm
                                color: rateRow.selected ? Theme.fillHi
                                       : (rateHover.containsMouse ? Theme.fill : "transparent")
                                Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: Theme.gapSm
                                Label {
                                    Layout.fillWidth: true
                                    text: root.formatRate(rateRow.modelData)
                                    color: Theme.text
                                    font.pixelSize: Theme.fsLabel
                                    font.weight: rateRow.selected ? Font.DemiBold : Font.Normal
                                }
                                Icon {
                                    visible: rateRow.selected
                                    name: "check"
                                    width: 14
                                    height: 14
                                    ink: Theme.text
                                }
                            }
                            MouseArea {
                                id: rateHover
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.setPlaybackRate(rateRow.modelData)
                            }
                        }
                    }
                }
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
