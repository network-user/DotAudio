import QtQuick
import "Theme.js" as Theme

// Таймлайн медиа: peaks, seek, подсветка активной фразы и ручки границ.
Item {
    id: root

    property var player: null
    property var segments: []
    property var peaks: []
    property real peaksDuration: 0
    property int selectedIndex: -1
    property bool editable: false

    signal seeked(real seconds)
    signal edgeChanged(int index, real start, real end)

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

    function selectedSeg() {
        if (root.selectedIndex < 0 || root.selectedIndex >= root.segments.length)
            return null
        return root.segments[root.selectedIndex]
    }

    implicitHeight: 56

    Rectangle {
        id: frame
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

                var sel = root.selectedSeg()
                if (sel) {
                    var sx0 = (Number(sel.start) / dur) * w
                    var sx1 = (Number(sel.end) / dur) * w
                    ctx.fillStyle = Theme.borderHi
                    ctx.globalAlpha = 0.25
                    ctx.fillRect(sx0, 0, Math.max(2, sx1 - sx0), h)
                    ctx.globalAlpha = 1
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
                root.seeked(sec)
            }
        }

        // Ручки границ выбранной фразы.
        Item {
            id: handles
            anchors.fill: parent
            anchors.margins: 6
            visible: root.editable && root.selectedSeg() !== null

            readonly property var seg: root.selectedSeg()
            readonly property real dur: Math.max(0.001, root.durationSec)
            readonly property real x0: seg ? (Number(seg.start) / dur) * width : 0
            readonly property real x1: seg ? (Number(seg.end) / dur) * width : 0

            Rectangle {
                x: handles.x0 - 3
                width: 6
                height: parent.height
                radius: 2
                color: Theme.text
                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -4
                    cursorShape: Qt.SizeHorCursor
                    drag.target: parent
                    drag.axis: Drag.XAxis
                    drag.minimumX: -3
                    drag.maximumX: handles.x1 - 10
                    onReleased: {
                        if (!handles.seg)
                            return
                        var start = Math.max(0, (parent.x + 3) / Math.max(1, handles.width) * handles.dur)
                        root.edgeChanged(root.selectedIndex, start, Number(handles.seg.end))
                    }
                }
            }
            Rectangle {
                x: handles.x1 - 3
                width: 6
                height: parent.height
                radius: 2
                color: Theme.text
                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -4
                    cursorShape: Qt.SizeHorCursor
                    drag.target: parent
                    drag.axis: Drag.XAxis
                    drag.minimumX: handles.x0 + 4
                    drag.maximumX: handles.width - 3
                    onReleased: {
                        if (!handles.seg)
                            return
                        var end = Math.min(handles.dur, (parent.x + 3) / Math.max(1, handles.width) * handles.dur)
                        root.edgeChanged(root.selectedIndex, Number(handles.seg.start), end)
                    }
                }
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
    onSelectedIndexChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
}
