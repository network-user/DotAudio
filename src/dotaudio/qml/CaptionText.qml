import QtQuick
import "Theme.js" as Theme

// Живая строка субтитра. Подтверждённые слова застывают на своих местах:
// переписанный хвост меняет текст на месте, не сдвигая уже прочитанное и
// не пересобирая строку заново. Строка едет вверх только когда появляется
// новая строка, а не на каждом черновике.
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
    property int align: Text.AlignLeft
    property real lineHeightFactor: Theme.captionLineFactor
    property bool animateWords: true

    readonly property real lineHeight: Math.round(pixelSize * lineHeightFactor)
    // Пробел берётся из метрик шрифта, но если метрика недоступна, ширина
    // считается от кегля: без этого слова слипались в одну строку.
    readonly property real spaceWidth: {
        var measured = spacedMetrics.advanceWidth - tightMetrics.advanceWidth
        return measured > 1 ? measured : Math.round(pixelSize * 0.28)
    }
    readonly property bool empty: words.count === 0

    property int lineCount: 1
    property int firstWordIndex: 0
    // Слово с индексом ниже frozenCount уже стоит на своём месте: позиция
    // переживает любой черновик, живой хвост продолжается от его конца.
    property int frozenCount: 0
    // Индексы слов, ожидающих подтверждения волной.
    property var confirmQueue: []
    property int confirmStep: 24
    // Confirmed и pending приходят одним сигналом контроллера, но QML меняет
    // привязки по отдельности. Сводим их к одному кадру, чтобы не делать две
    // раскладки и не показать промежуточное состояние строки.
    property bool syncScheduled: false

    implicitHeight: lineHeight * Math.max(1, maxLines)
    clip: true

    // Один сигнал контроллера меняет обе привязки. Промежуточный снимок
    // содержит старый pending и новый confirmed и не должен попасть в модель.
    onConfirmedChanged: root.scheduleSync()
    onPendingChanged: root.scheduleSync()
    onTextChanged: root.scheduleSync()
    // Смена ширины или шрифта недействительна для всех застывших позиций.
    onWidthChanged: root.reflowAll()
    onPixelSizeChanged: root.reflowAll()
    onWeightChanged: root.reflowAll()
    onLineHeightChanged: root.reflowAll()
    onSpaceWidthChanged: root.reflowAll()
    onMaxLinesChanged: Qt.callLater(root.relayout)
    onAlignChanged: Qt.callLater(root.relayout)
    Component.onCompleted: root.scheduleSync()

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

    Timer {
        id: confirmTicker
        interval: root.confirmStep > 0 ? root.confirmStep : 24
        repeat: true
        running: false
        onTriggered: root.confirmNext()
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

    function scheduleSync() {
        if (root.syncScheduled)
            return
        root.syncScheduled = true
        Qt.callLater(function() {
            root.syncScheduled = false
            root.sync()
        })
    }

    function comparable(value) {
        // Пунктуация и регистр часто уточняются при финализации фразы.
        return String(value).toLowerCase().replace(/[.,!?;:…«»\"“”()[\]{}]+/g, "")
    }

    function reflowAll() {
        root.frozenCount = 0
        Qt.callLater(root.relayout)
    }

    // Обновление без пересборки: совпадающий префикс переиспользуется, его
    // слова не проигрывают появление снова. Переписанный хвост меняет текст
    // в уже существующих словах, поэтому черновик не мигает всей строкой.
    function sync() {
        var next = root.tokens()
        // История остаётся в контроллере; сцене нужен только конец фразы.
        var first = Math.max(0, next.length - Theme.captionWordLimit)
        next = next.slice(first)
        if (first !== root.firstWordIndex) {
            var dropped = first - root.firstWordIndex
            if (dropped > 0 && dropped < words.count)
                words.remove(0, dropped)
            else
                words.clear()
            root.firstWordIndex = first
        }
        var keep = 0
        var wave = []
        while (keep < words.count && keep < next.length
               && root.comparable(words.get(keep).token) === root.comparable(next[keep].token)) {
            if (words.get(keep).token !== next[keep].token)
                words.setProperty(keep, "token", next[keep].token)
            if (words.get(keep).soft !== next[keep].soft) {
                if (!next[keep].soft)
                    wave.push(keep)
                else
                    words.setProperty(keep, "soft", next[keep].soft)
            }
            keep++
        }
        var overlap = Math.min(next.length, words.count) - keep
        for (var r = 0; r < overlap; r++) {
            var idx = keep + r
            if (words.get(idx).token !== next[idx].token)
                words.setProperty(idx, "token", next[idx].token)
            if (words.get(idx).soft !== next[idx].soft) {
                if (!next[idx].soft)
                    wave.push(idx)
                else
                    words.setProperty(idx, "soft", next[idx].soft)
            }
        }
        if (words.count > keep + overlap)
            words.remove(keep + overlap, words.count - keep - overlap)
        for (var i = keep + overlap; i < next.length; i++) {
            words.append({
                "token": next[i].token,
                "soft": next[i].soft
            })
        }
        // Крупное подтверждение читается волной по словам: взгляд видит,
        // какие слова финализированы, а не ловит мгновенную смену строки.
        root.confirmQueue = []
        if (wave.length > Theme.confirmWaveWords) {
            root.confirmStep = Math.max(16, Math.min(48, Math.round(360 / wave.length)))
            root.confirmQueue = wave
        } else {
            for (var w = 0; w < wave.length; w++) {
                words.setProperty(wave[w], "soft", false)
                var c = rows.itemAt(wave[w])
                if (c)
                    c.confirmIn()
            }
        }
        confirmTicker.running = root.confirmQueue.length > 0
        root.frozenCount = keep
        root.relayout()
    }

    function confirmNext() {
        while (root.confirmQueue.length) {
            var idx = root.confirmQueue.shift()
            if (idx < words.count && words.get(idx).soft) {
                words.setProperty(idx, "soft", false)
                var chip = rows.itemAt(idx)
                if (chip)
                    chip.confirmIn()
                break
            }
        }
        confirmTicker.running = root.confirmQueue.length > 0
    }

    // Раскладка инкрементальная: застывшие слова задают точку продолжения,
    // живой хвост заполняет строку дальше и переносится, когда она полна.
    function relayout() {
        if (root.width <= 1)
            return
        var row = 0
        var x = 0
        var placed = []
        var frozen = Math.min(root.frozenCount, rows.count)
        for (var i = 0; i < rows.count; i++) {
            var chip = rows.itemAt(i)
            if (!chip)
                continue
            if (i < frozen) {
                row = Math.round(chip.y / root.lineHeight)
                x = chip.x + chip.width + root.spaceWidth
            } else {
                var chipWidth = Math.min(root.width, chip.implicitWidth)
                if (x > 0 && x + chipWidth > root.width) {
                    row++
                    x = 0
                }
                chip.x = Math.round(x)
                chip.y = Math.round(row * root.lineHeight)
                x += chipWidth + root.spaceWidth
            }
            placed.push({ "chip": chip, "row": row })
        }
        var lines = row + 1
        root.lineCount = Math.max(1, lines)
        // Видны последние maxLines строк: сцена уезжает вверх, как лента.
        var visibleFrom = Math.max(0, lines - Math.max(1, root.maxLines))
        for (var k = 0; k < placed.length; k++)
            placed[k].chip.visible = placed[k].row >= visibleFrom
        if (root.align !== Text.AlignLeft)
            root.indentRows(placed, lines)
        flow.shift = -Math.max(0, lines - Math.max(1, root.maxLines)) * root.lineHeight
    }

    function indentRows(placed, lines) {
        var widths = []
        for (var l = 0; l < lines; l++)
            widths.push({ "min": -1, "max": 0 })
        for (var k = 0; k < placed.length; k++) {
            var row = placed[k].row
            var chip = placed[k].chip
            if (widths[row].min < 0 || chip.x < widths[row].min)
                widths[row].min = chip.x
            widths[row].max = Math.max(widths[row].max, chip.x + chip.width)
        }
        for (var n = 0; n < placed.length; n++) {
            var item = placed[n]
            var extent = widths[item.row]
            if (extent.min < 0)
                continue
            var slack = Math.max(0, root.width - (extent.max - extent.min))
            var indent = root.align === Text.AlignHCenter ? slack / 2 : slack
            item.chip.x = Math.round(item.chip.x + indent - extent.min)
        }
    }

    Item {
        id: flow
        width: root.width
        height: root.lineHeight * Math.max(1, root.lineCount)
        property real shift: 0
        y: shift
        // Сдвиг происходит один раз на новую строку, поэтому лента едет
        // спокойно, а не дёргается на каждом черновике.
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
                property real enter: root.animateWords ? 0 : 1
                property real lit: chip.soft ? root.pendingOpacity : 1
                property real rise: 0

                objectName: "captionWord"
                text: chip.token
                width: Math.min(root.width, implicitWidth)
                elide: Text.ElideRight
                color: root.ink
                font.family: Theme.fontFamily
                font.pixelSize: root.pixelSize
                // Подтверждение не меняет ширину слова и переносы строк.
                font.weight: root.weight
                opacity: chip.lit * chip.enter
                // Сдвиг вниз - только отрисовка (translate), раскладку не
                // двигает: соседние слова не разъезжаются при подтверждении.
                transform: Translate { y: chip.rise }

                Behavior on lit {
                    NumberAnimation {
                        duration: Theme.wordMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                }
                // Новое слово всплывает снизу на своё место; подтверждение
                // «дозревает» коротким опусканием с ростом проявления.
                Component.onCompleted: {
                    if (!root.animateWords) {
                        chip.enter = 1
                        return
                    }
                    chip.enter = 0
                    chip.rise = -Theme.wordRise
                    wordIn.start()
                    wordRise.start()
                }

                // Однократное дозревание готового слова: из черновика в
                // строку. Вызывается явно из confirmNext / small-wave пути.
                function confirmIn() {
                    chip.rise = Theme.confirmRise
                    confirmFall.start()
                }

                NumberAnimation {
                    id: wordIn
                    target: chip
                    property: "enter"
                    to: 1
                    duration: Theme.wordMs
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easeOut
                }
                NumberAnimation {
                    id: wordRise
                    target: chip
                    property: "rise"
                    to: 0
                    duration: Theme.wordMs
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easeOut
                }
                NumberAnimation {
                    id: confirmFall
                    target: chip
                    property: "rise"
                    to: 0
                    duration: Theme.wordMs
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easeOut
                }
            }
        }
    }
}
