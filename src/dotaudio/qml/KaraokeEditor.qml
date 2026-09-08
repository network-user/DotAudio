import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Караоке-редактор раздела «Аудио и видео».
// Слева/по списку: фразы bridge.segments (клик по строке выбирает фразу).
// Активная строка = выбранная. Строка «слушаю» внизу отвечает за выбранную
// фразу и её слова: кнопки перематывают по словам и проигрывают фрагмент.
// Поля «слово/от/до» правят выбранное слово; изменения пишутся в bridge
// (setWordEdge, editWordText) и сразу же пересобирают список.
Rectangle {
    id: root

    property var player: null
    property var segments: []
    property bool editable: true

    color: Theme.surface
    radius: Theme.radiusLg
    border.width: 1
    border.color: Theme.border
    clip: true

    property int focusIndex: -1
    property int focusWord: -1

    function pad(n) { return (n < 10 ? "0" : "") + n }
    function fmt(s) {
        var v = Number(s)
        if (!isFinite(v) || v < 0) v = 0
        var m = Math.max(0, Math.floor(v / 60))
        var sec = Math.max(0, Math.floor(v % 60))
        var cs = Math.round((v - Math.floor(v)) * 100) % 100
        return pad(m) + ":" + pad(sec) + "." + pad(cs)
    }
    function parseTime(s) {
        var t = String(s).trim().replace(",", ".")
        var colon = t.indexOf(":")
        if (colon > 0) return (Number(t.slice(0, colon)) || 0) * 60 + (Number(t.slice(colon + 1)) || 0)
        return Number(t)
    }

    function count() { return root.segments.length }
    function segAt(i) { return (i >= 0 && i < count()) ? root.segments[i] : null }
    function wordsAt(i) { var s = segAt(i); return s ? (s.words || []) : [] }

    // Возвращает индекс фразы, на которую направлено действие: если всё ещё
    // играет файл и курсор в пределах строки — это активная; иначе фокус.
    function activeIndex() {
        var p = root.focusIndex
        if (root.player && root.player.hasAudio) {
            var pos = root.player.position / 1000
            var guess = -1
            for (var i = 0; i < root.segments.length; i++) {
                var s = root.segments[i]
                if (pos >= Number(s.start) && pos < Number(s.end)) { guess = i; break }
            }
            if (guess >= 0) return guess
        }
        if (p < 0) return count() ? 0 : -1
        return Math.min(p, count() - 1)
    }
    function wordCount() {
        var a = activeIndex(); return a < 0 ? 0 : wordsAt(a).length
    }
    function wi() {
        if (wordCount() === 0) return -1
        var w = root.focusWord
        return (w < 0 || w >= wordCount()) ? 0 : w
    }
    function currentWord() {
        var a = activeIndex();
        if (a < 0) return null
        var ws = wordsAt(a)
        var j = wi()
        return { row: segAt(a), wi: j, word: ws[j], rowI: a }
    }

    function setMode(i, w) { root.focusIndex = i; root.focusWord = w; refresh() }

    function playPhraseFrag(i, w) {
        var ws = wordsAt(i)
        if (w < 0 || w >= ws.length) return
        setMode(i, w)
        playRange(Number(ws[w].start) - 0.06, Number(ws[w].end) + 0.5)
    }
    function playRow(i) {
        var s = segAt(i); if (!s) return
        setMode(i, -1)
        playRange(Number(s.start), Number(s.end))
    }
    function playRange(a, b) {
        if (!root.player) return
        root.player.stop()
        root.player.position = Math.round(Number(a) * 1000)
        root.rangeEnd = Math.round(Number(b) * 1000)
        root.playing = true
        watch.start()
        root.player.play()
    }
    property bool playing: false
    property real rangeEnd: 0
    Timer {
        id: watch
        interval: 25
        onTriggered: {
            if (!root.playing) return
            if (!root.player || root.player.position >= root.rangeEnd) {
                root.playing = false
                if (root.player) root.player.pause()
                watch.stop()
            }
        }
    }

    function walk(delta) {
        var a = activeIndex(); var n = wordCount()
        if (a < 0 || n === 0) return
        var j = wi()
        var next = (j + delta + n) % n
        var ws = wordsAt(a)
        setMode(a, next)
        playRange(Number(ws[next].start) - 0.06, Number(ws[next].end) + 0.5)
    }

    function bridgeAvailable() {
        return typeof bridge !== "undefined" && bridge && typeof bridge.setWordEdge === "function"
    }
    function commitEdge(fromStart) {
        var c = currentWord()
        if (!c || !bridgeAvailable()) { refresh(); return }
        var t = fromStart ? startField.text : endField.text
        var v = parseTime(t)
        if (!isFinite(v)) { refresh(); return }
        var id = Number(c.row.id)
        bridge.setWordEdge(id, c.wi, fromStart ? "start" : "end", v)
    }
    function setEdgePlayhead(fromStart) {
        var c = currentWord()
        if (!c || !bridgeAvailable() || !root.player) { refresh(); return }
        var v = root.player.position / 1000
        bridge.setWordEdge(Number(c.row.id), c.wi, fromStart ? "start" : "end", v)
        refresh()
    }
    function commitWordText() {
        var c = currentWord()
        if (!c || !bridgeAvailable()) return
        var t = wordBox.text
        if (t && t.trim()) bridge.editWordText(Number(c.row.id), c.wi, t)
    }
    function refresh() {
        var c = currentWord()
        if (typeof startField === "undefined") return
        startField.text = c ? fmt(Number(c.word.start)) : "00:00.00"
        endField.text = c ? fmt(Number(c.word.end)) : "00:00.00"
        wordBox.text = c ? String(c.word.text).trim() : ""
        capLabel.text = c
            ? "Слово «" + c.word.text + "», от " + fmt(Number(c.word.start)) + " до " + fmt(Number(c.word.end))
            : "Фраза без слов — можно добавлять таймкоды после распознавания текста по словам"
    }

    // --------------- верхний список фраз ---------------
    ListView {
        id: list
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 12
        anchors.bottom: panel.y
        spacing: 6
        clip: true
        model: root.segments
        ScrollBar.vertical: ScrollBar {}
        delegate: Rectangle {
            id: rowBox
            width: list.width
            color: rowMouse.containsMouse ? Theme.surface3 : (isFocus ? Theme.surface3 : Theme.surface2)
            radius: Theme.radiusMd
            border.width: 1
            border.color: isFocus ? Theme.borderHi : Theme.border
            implicitHeight: 44
            property bool isFocus: root.focusIndex === index
            MouseArea {
                id: rowMouse
                anchors.fill: parent
                onClicked: { root.focusIndex = index; root.focusWord = -1; root.refresh() }
            }
            RowLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 8
                Button {
                    text: root.fmt(Number(modelData.start))
                    flat: true
                    contentItem: Text {
                        text: parent.text
                        color: Theme.muted
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.fsSmall
                    }
                    onClicked: root.playRow(index)
                }
                Text {
                    Layout.fillWidth: true
                    text: modelData.text
                    color: rowBox.isFocus ? Theme.text : Theme.muted
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    font.pixelSize: Theme.fsBody
                }
                PillButton { text: "слова ▸"; compact: true; enabled: root.wordsAt(index).length > 0
                    onClicked: { root.focusIndex = index; root.walk(0) } }
            }
        }
    }

    Label {
        anchors.centerIn: list
        visible: root.segments.length === 0
        text: "Распознайте аудио/видео — появятся фразы и слова, которые здесь правят."
        color: Theme.muted
        font.pixelSize: Theme.fsBody
        horizontalAlignment: Text.AlignHCenter
    }

    // --------------- нижняя панель выбранного слова ---------------
    Rectangle {
        id: panel
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 150
        color: Theme.surface2
        border.color: Theme.border
        border.width: 1

        Column {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8

            Text { id: capLabel; width: parent.width; color: Theme.text; elide: Text.ElideRight; font.pixelSize: Theme.fsSmall }

            RowLayout {
                width: parent.width
                spacing: 8
                PillButton { text: "◂"
                    enabled: count() > 0
                    onClicked: root.walk(-1) }
                PillButton { text: "сл."; primary: true
                    enabled: root.currentWord() !== null
                    onClicked: { var c = root.currentWord(); if (c) root.playPhraseFrag(c.rowI, c.wi) } }
                PillButton { text: "‖"; enabled: !!player; onClicked: { if (player) player.pause() } }
                PillButton { text: "▸"
                    enabled: count() > 0
                    onClicked: root.walk(1) }
                PillButton { text: "фраза"
                    enabled: count() > 0
                    onClicked: root.playRow(root.activeIndex()) }
                PillButton { text: "нач ←"
                    enabled: root.currentWord() !== null && !!player
                    onClicked: root.setEdgePlayhead(true) }
                PillButton { text: "кон ←"
                    enabled: root.currentWord() !== null && !!player
                    onClicked: root.setEdgePlayhead(false) }
            }

            RowLayout {
                width: parent.width
                spacing: 6
                Text { text: "слово"; color: Theme.muted; font.pixelSize: Theme.fsSmall }
                TextField { id: wordBox; Layout.preferredWidth: 150
                    color: Theme.text; font.pixelSize: Theme.fsSmall
                    onAccepted: root.commitWordText()
                }
                TextField { id: startField; Layout.preferredWidth: 84
                    font.family: Theme.monoFamily; color: Theme.text; font.pixelSize: Theme.fsSmall
                    onEditingFinished: root.commitEdge(true)
                }
                TextField { id: endField; Layout.preferredWidth: 84
                    font.family: Theme.monoFamily; color: Theme.text; font.pixelSize: Theme.fsSmall
                    onEditingFinished: root.commitEdge(false)
                }
                Item { Layout.fillWidth: true }
                Text { text: root.player ? "курсор " + root.fmt(root.player.position/1000) : ""
                    color: Theme.muted; font.family: Theme.monoFamily; font.pixelSize: Theme.fsSmall }
            }
        }
    }
}
