import QtQuick
import "Theme.js" as Theme

// Живая строка субтитра. Текст растёт словами: подтверждённый префикс
// остаётся на месте и не анимируется повторно, а уточняемый хвост
// приглушён. Перенос строки и сдвиг слов при новом переносе - анимация
// позиции, а не мгновенный прыжок.
Item {
    id: root

    property string confirmed: ""
    property string pending: ""
    // Совместимость с местами, где показывается одна готовая строка.
    property string text: ""

    property int pixelSize: Theme.fsStage
    property int weight: Font.DemiBold
    property color ink: Theme.text
    property real pendingOpacity: Theme.pendingAlpha
    property int maxLines: 2
    property int align: Text.AlignHCenter
    property real lineHeightFactor: 1.26
    property bool animateWords: true

    readonly property real lineHeight: Math.round(pixelSize * lineHeightFactor)
    readonly property real spaceWidth: Math.max(3, spacedMetrics.advanceWidth - tightMetrics.advanceWidth)
    readonly property bool empty: words.count === 0

    property int lineCount: 1
    property int sequence: 0

    implicitHeight: lineHeight * Math.min(maxLines, Math.max(1, lineCount))
    clip: true

    onConfirmedChanged: root.sync()
    onPendingChanged: root.sync()
    onTextChanged: root.sync()
    onWidthChanged: Qt.callLater(root.relayout)
    onPixelSizeChanged: Qt.callLater(root.relayout)
    onMaxLinesChanged: Qt.callLater(root.relayout)
    onAlignChanged: Qt.callLater(root.relayout)
    Component.onCompleted: root.sync()

    ListModel { id: words }

    TextMetrics {
        id: tightMetrics
        font.family: Theme.fontFamily
        font.pixelSize: root.pixelSize
        font.weight: root.weight
        text: "нн"
    }

    TextMetrics {
        id: spacedMetrics
        font.family: Theme.fontFamily
        font.pixelSize: root.pixelSize
        font.weight: root.weight
        text: "н н"
    }

    function split(value) {
        var parts = String(value === undefined || value === null ? "" : value).split(/\s+/)
        var out = []
        for (var i = 0; i < parts.length; i++) {
            if (parts[i].length)
                out.push(parts[i])
        }
        return out
    }

    function tokens() {
        var stable = root.split(root.confirmed)
        var live = root.split(root.pending)
        if (!stable.length && !live.length)
            stable = root.split(root.text)
        var out = []
        for (var i = 0; i < stable.length; i++)
            out.push({ "token": stable[i], "soft": false })
        for (var j = 0; j < live.length; j++)
            out.push({ "token": live[j], "soft": true })
        return out
    }

    // Обновление без пересборки: совпадающий префикс переиспользуется, и
    // его слова не проигрывают появление снова. Меняется только состояние
    // "уточняется / подтверждено" и добавляется новый хвост.
    function sync() {
        var next = root.tokens()
        var keep = 0
        while (keep < words.count && keep < next.length && words.get(keep).token === next[keep].token) {
            if (words.get(keep).soft !== next[keep].soft)
                words.setProperty(keep, "soft", next[keep].soft)
            keep++
        }
        while (words.count > keep)
            words.remove(words.count - 1)
        for (var i = keep; i < next.length; i++) {
            words.append({
                "token": next[i].token,
                "soft": next[i].soft,
                "seq": i - keep
            })
        }
        Qt.callLater(root.relayout)
    }

    function relayout() {
        if (root.width <= 1)
            return
        var lines = []
        var current = []
        var lineWidth = 0
        for (var i = 0; i < rows.count; i++) {
            var chip = rows.itemAt(i)
            if (!chip)
                continue
            var chipWidth = chip.implicitWidth
            if (current.length && lineWidth + root.spaceWidth + chipWidth > root.width) {
                lines.push({ "items": current, "width": lineWidth })
                current = []
                lineWidth = 0
            }
            if (current.length)
                lineWidth += root.spaceWidth
            current.push({ "chip": chip, "offset": lineWidth })
            lineWidth += chipWidth
        }
        if (current.length)
            lines.push({ "items": current, "width": lineWidth })
        root.lineCount = Math.max(1, lines.length)
        for (var l = 0; l < lines.length; l++) {
            var slack = Math.max(0, root.width - lines[l].width)
            var indent = root.align === Text.AlignHCenter ? slack / 2
                       : root.align === Text.AlignRight ? slack : 0
            for (var k = 0; k < lines[l].items.length; k++) {
                var item = lines[l].items[k]
                var placed = item.chip.placed
                item.chip.x = Math.round(indent + item.offset)
                item.chip.y = Math.round(l * root.lineHeight)
                if (!placed)
                    item.chip.placed = true
            }
        }
        // Видны последние maxLines строк: сцена уезжает вверх, как лента.
        flow.shift = -Math.max(0, lines.length - root.maxLines) * root.lineHeight
    }

    Item {
        id: flow
        width: root.width
        height: root.lineHeight * Math.max(1, root.lineCount)
        property real shift: 0
        y: shift
        Behavior on y {
            NumberAnimation {
                duration: Theme.reflowMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }

        Repeater {
            id: rows
            model: words

            delegate: Text {
                id: chip
                required property string token
                required property bool soft
                required property int seq

                property bool placed: false
                property real enter: root.animateWords ? 0 : 1
                property real rise: 0
                property real softness: chip.soft ? root.pendingOpacity : 1

                text: chip.token
                color: root.ink
                font.family: Theme.fontFamily
                font.pixelSize: root.pixelSize
                font.weight: root.weight
                opacity: chip.softness * chip.enter
                transform: Translate { y: chip.rise }

                Behavior on softness {
                    NumberAnimation {
                        duration: Theme.baseMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                }
                Behavior on x {
                    enabled: chip.placed
                    NumberAnimation {
                        duration: Theme.reflowMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                }
                Behavior on y {
                    enabled: chip.placed
                    NumberAnimation {
                        duration: Theme.reflowMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                }

                Component.onCompleted: {
                    if (!root.animateWords) {
                        chip.enter = 1
                        return
                    }
                    chip.rise = Math.round(root.pixelSize * 0.4)
                    chip.scale = 0.94
                    wordIn.start()
                }

                SequentialAnimation {
                    id: wordIn
                    PauseAnimation {
                        duration: Math.min(Theme.wordStaggerCapMs, Math.max(0, chip.seq) * Theme.wordStaggerMs)
                    }
                    ParallelAnimation {
                        NumberAnimation {
                            target: chip
                            property: "enter"
                            to: 1
                            duration: Theme.wordMs
                            easing.type: Easing.Bezier
                            easing.bezierCurve: Theme.easeOut
                        }
                        NumberAnimation {
                            target: chip
                            property: "rise"
                            to: 0
                            duration: Theme.wordMs
                            easing.type: Easing.Bezier
                            easing.bezierCurve: Theme.easeOut
                        }
                        NumberAnimation {
                            target: chip
                            property: "scale"
                            to: 1
                            duration: Theme.wordMs
                            easing.type: Easing.Bezier
                            easing.bezierCurve: Theme.easeOut
                        }
                    }
                }
            }
        }
    }
}
