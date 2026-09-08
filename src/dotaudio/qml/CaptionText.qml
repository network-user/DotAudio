import QtQuick
import "Theme.js" as Theme

// Живая строка субтитра. Весь текст идёт целыми строками: слова не
// всплывают по одному, черновик не приглушается и ничто не «дозревает»
// волной подтверждения. Подтверждённая и предварительная части просто
// следуют друг за другом одним сплошным текстом - это то, как читаются
// обычные субтитры.
//
// Видны последние maxLines строк: блок текста выровнен по низу корневого
// прямоугольника, а вышедшие наверх строки отсекаются. Фраза растёт вниз,
// сцена ведёт читателя без перестроенных строк и прыгающих слов.
Item {
    id: root

    property string confirmed: ""
    property string pending: ""
    // Совместимость с местами, где показывается одна готовая строка.
    property string text: ""

    property int pixelSize: Theme.fsStage
    property int weight: Font.DemiBold
    property color ink: Theme.text
    property int maxLines: 2
    property int align: Text.AlignLeft
    property real lineHeightFactor: Theme.captionLineFactor

    readonly property real lineHeight: Math.round(pixelSize * lineHeightFactor)

    // confirmed и pending приходят одним сигналом контроллера. Никакого
    // промежуточного снимка: склейка происходит в одном месте и не даёт
    // разрыва между подтверждённым текстом и живым хвостом.
    readonly property string content: {
        var stable = String(confirmed === undefined || confirmed === null ? "" : confirmed).trim()
        var live = String(pending === undefined || pending === null ? "" : pending).trim()
        if (stable.length && live.length)
            return stable + " " + live
        if (stable.length)
            return stable
        if (live.length)
            return live
        return String(text === undefined || text === null ? "" : text)
    }

    readonly property bool empty: block.text.length === 0

    // Высота фиксирована и не зависит от длины фразы, поэтому сцена и окно
    // не двигаются, когда текст становится длиннее. Явная привязка держит
    // контейнер (сцену, страницу диктовки) на постоянной высоте даже без
    // layout; там, где CaptionText растягивается лейаутом, высота своя.
    implicitHeight: lineHeight * Math.max(1, maxLines)
    height: implicitHeight
    clip: true

    Text {
        id: block
        objectName: "captionBlock"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        // Блок всегда занимает свою полную высоту, а не область корня:
        // при длинной фразе он уходит вверх и отсекается clip родителя,
        // оставляя на виду последние строки.
        height: block.contentHeight
        text: root.content
        color: root.ink
        font.family: Theme.fontFamily
        font.pixelSize: root.pixelSize
        font.weight: root.weight
        lineHeight: root.lineHeight
        lineHeightMode: Text.FixedHeight
        // Только по границам слов. Перенос «где угодно» разрезал слово, и на
        // следующем черновике разрез уезжал в другое место - строка от этого
        // перекладывалась целиком, хотя дописали одно слово.
        wrapMode: Text.Wrap
        horizontalAlignment: root.align
        visible: block.text.length > 0
    }
}
