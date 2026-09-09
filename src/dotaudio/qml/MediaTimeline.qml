import QtQuick
import "Theme.js" as Theme

// Таймлайн медиа (не Live Waveform): peaks из bridge.mediaPeaks (воркер),
// клик = seek, подсветка активного слова. Waveform.qml для Live не трогаем.
Item {
    id: root

    property var player: null
    property var segments: []
    property var peaks: []
    property real peaksDuration: 0

    readonly property real durationSec: {
        var fromPeaks = Number(root.peaksDuration)
        if (fromPeaks > 0)
            return fromPeaks
        if (root.player && root.player.duration > 0)
            return root.player.duration / 1000
        return 1
    }
    readonly property real positionSec: root.player ? root.player.position / 1000 : 0

    function activeWord() {
        var pos = root.positionSec
        for (var i = 0; i < root.segments.length; i++) {
            var seg = root.segments[i]
            var words = seg.words || []
            for (var j = 0; j < words.length; j++) {
                var w = words[j]
                var a = Number(w.start)
                var b = Number(w.end)
                if (pos >= a && pos < b)
                    return { start: a, end: b }
            }
            var s = Number(seg.start)
            var e = Number(seg.end)
            if (pos >= s && pos < e)
                return { start: s, end: e }
        }
        return null
    }

    implicitHeight: 56

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusMd
        color: Theme.surface2
        border.width: 1
        border.color: Theme.border
        clip: true

        Canvas {
            id: canvas
            anchors.fill: parent
            anchors.margins: 6
            renderStrategy: Canvas.Immediate

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var list = root.peaks || []
                var n = list.length
                var w = width
                var h = height
                ctx.fillStyle = Theme.fill
                ctx.fillRect(0, 0, w, h)

                if (n > 0) {
                    var barW = Math.max(1, w / n)
                    ctx.fillStyle = Theme.ink
                    for (var i = 0; i < n; i++) {
                        var amp = Math.max(0, Math.min(1, Number(list[i]) || 0))
                        amp = Theme.levelShape(amp / Theme.levelGain)
                        var barH = Math.max(2, amp * (h - 4))
                        ctx.globalAlpha = 0.45 + 0.55 * amp
                        ctx.fillRect(i * barW, (h - barH) / 2, Math.max(1, barW - 0.5), barH)
                    }
                    ctx.globalAlpha = 1
                }

                var word = root.activeWord()
                var dur = Math.max(0.001, root.durationSec)
                if (word) {
                    var x0 = (Number(word.start) / dur) * w
                    var x1 = (Number(word.end) / dur) * w
                    ctx.fillStyle = Theme.recSoft
                    ctx.fillRect(x0, 0, Math.max(2, x1 - x0), h)
                }

                var playX = (root.positionSec / dur) * w
                ctx.strokeStyle = Theme.text
                ctx.lineWidth = 1
                ctx.beginPath()
                ctx.moveTo(playX, 0)
                ctx.lineTo(playX, h)
                ctx.stroke()
            }
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: function(mouse) {
                if (!root.player)
                    return
                var ratio = Math.max(0, Math.min(1, mouse.x / Math.max(1, width)))
                var sec = ratio * root.durationSec
                root.player.position = Math.round(sec * 1000)
            }
        }
    }

    Connections {
        target: root.player
        function onPositionChanged() { canvas.requestPaint() }
        function onDurationChanged() { canvas.requestPaint() }
    }

    onPeaksChanged: canvas.requestPaint()
    onPeaksDurationChanged: canvas.requestPaint()
    onSegmentsChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
}
