import QtQuick
import "Theme.js" as Theme

Item {
    id: root
    property string name: "live"
    property color ink: Theme.ink
    property real stroke: 1.6
    width: 20
    height: 20

    onNameChanged: canvas.requestPaint()
    onInkChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
    onStrokeChanged: canvas.requestPaint()

    RotationAnimator on rotation {
        running: root.name === "spinner"
        loops: Animation.Infinite
        duration: 900
        from: 0
        to: 360
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.scale(width / 20, height / 20)
            ctx.strokeStyle = root.ink
            ctx.fillStyle = root.ink
            ctx.lineWidth = root.stroke
            ctx.lineCap = "round"
            ctx.lineJoin = "round"
            switch (root.name) {
            case "live":
                rounded(ctx, 3.5, 5.5, 13, 9, 2.5)
                ctx.stroke()
                line(ctx, 6.5, 8.5, 13.5, 8.5)
                line(ctx, 6.5, 11.5, 11.5, 11.5)
                break
            case "dictation":
                rounded(ctx, 7.5, 3.5, 5, 8, 2.5)
                ctx.stroke()
                ctx.beginPath()
                ctx.moveTo(5.5, 10)
                ctx.quadraticCurveTo(5.5, 14.5, 10, 14.5)
                ctx.quadraticCurveTo(14.5, 14.5, 14.5, 10)
                ctx.stroke()
                line(ctx, 10, 14.5, 10, 16.5)
                line(ctx, 7.5, 16.5, 12.5, 16.5)
                break
            case "rec":
                ctx.beginPath()
                ctx.arc(10, 10, 5, 0, Math.PI * 2)
                ctx.fill()
                break
            case "stop":
                rounded(ctx, 6, 6, 8, 8, 1.5)
                ctx.fill()
                break
            case "expand":
                line(ctx, 5, 8, 10, 13)
                line(ctx, 10, 13, 15, 8)
                break
            case "collapse":
                line(ctx, 5, 12, 10, 7)
                line(ctx, 10, 7, 15, 12)
                break
            case "copy":
                rounded(ctx, 6.5, 6.5, 8.5, 10, 1.6)
                ctx.stroke()
                rounded(ctx, 4.2, 3.8, 8.5, 10, 1.6)
                ctx.stroke()
                break
            case "close":
                line(ctx, 6, 6, 14, 14)
                line(ctx, 14, 6, 6, 14)
                break
            case "warning":
                ctx.beginPath()
                ctx.moveTo(10, 3.5)
                ctx.lineTo(17.2, 16.2)
                ctx.lineTo(2.8, 16.2)
                ctx.closePath()
                ctx.stroke()
                line(ctx, 10, 8, 10, 12.2)
                ctx.beginPath()
                ctx.arc(10, 14.4, 0.7, 0, Math.PI * 2)
                ctx.fill()
                break
            case "spinner":
                ctx.beginPath()
                ctx.arc(10, 10, 6, 0.2, Math.PI * 1.55)
                ctx.stroke()
                break
            case "overlay":
                rounded(ctx, 3.5, 4.5, 13, 11, 2)
                ctx.stroke()
                line(ctx, 5.5, 13.5, 14.5, 13.5)
                break
            case "check":
                ctx.beginPath()
                ctx.moveTo(4.5, 10.5)
                ctx.lineTo(8.2, 14.2)
                ctx.lineTo(15.5, 6.2)
                ctx.stroke()
                break
            case "media":
                ctx.beginPath()
                ctx.moveTo(7, 5)
                ctx.lineTo(15, 10)
                ctx.lineTo(7, 15)
                ctx.closePath()
                ctx.stroke()
                break
            case "models":
                ctx.beginPath()
                ctx.arc(10, 6.5, 2.1, 0, Math.PI * 2)
                ctx.stroke()
                ctx.beginPath()
                ctx.arc(6, 13.5, 2.1, 0, Math.PI * 2)
                ctx.stroke()
                ctx.beginPath()
                ctx.arc(14, 13.5, 2.1, 0, Math.PI * 2)
                ctx.stroke()
                line(ctx, 9, 8.2, 7.2, 11.6)
                line(ctx, 11, 8.2, 12.8, 11.6)
                break
            case "history":
                ctx.beginPath()
                ctx.arc(10, 10.5, 6.2, 0, Math.PI * 2)
                ctx.stroke()
                line(ctx, 10, 10.5, 10, 6.8)
                line(ctx, 10, 10.5, 13.2, 12.4)
                break
            case "settings":
                line(ctx, 4, 7, 16, 7)
                line(ctx, 4, 13, 16, 13)
                ctx.beginPath()
                ctx.arc(8, 7, 1.7, 0, Math.PI * 2)
                ctx.stroke()
                ctx.beginPath()
                ctx.arc(13, 13, 1.7, 0, Math.PI * 2)
                ctx.stroke()
                break
            case "undo":
                ctx.beginPath()
                ctx.arc(10, 11, 5.2, Math.PI, Math.PI * 2.1)
                ctx.stroke()
                line(ctx, 4.8, 11, 4.8, 6.6)
                line(ctx, 4.8, 11, 9.2, 11)
                break
            case "redo":
                ctx.beginPath()
                ctx.arc(10, 11, 5.2, Math.PI * 0.9, Math.PI * 2)
                ctx.stroke()
                line(ctx, 15.2, 11, 15.2, 6.6)
                line(ctx, 15.2, 11, 10.8, 11)
                break
            case "logs":
                line(ctx, 5, 6, 15, 6)
                line(ctx, 5, 10, 15, 10)
                line(ctx, 5, 14, 12, 14)
                break
            default:
                ctx.beginPath()
                ctx.arc(10, 10, 5.5, 0, Math.PI * 2)
                ctx.stroke()
                break
            }
        }
    }

    function line(ctx, x1, y1, x2, y2) {
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.stroke()
    }

    function rounded(ctx, x, y, w, h, r) {
        ctx.beginPath()
        ctx.moveTo(x + r, y)
        ctx.lineTo(x + w - r, y)
        ctx.quadraticCurveTo(x + w, y, x + w, y + r)
        ctx.lineTo(x + w, y + h - r)
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
        ctx.lineTo(x + r, y + h)
        ctx.quadraticCurveTo(x, y + h, x, y + h - r)
        ctx.lineTo(x, y + r)
        ctx.quadraticCurveTo(x, y, x + r, y)
        ctx.closePath()
    }
}
