import QtQuick
import "Theme.js" as Theme

// Живая строка субтитра. Один поток: подтверждённое полным чернилом,
// уточняемый хвост чуть тише. Без пословных всплытий - они мигали на каждом
// переписанном черновике.
//
// Видны последние maxLines строк. Длину фразы режет контроллер (одно
// предложение + мягкое окно символов), сцена только обрезает верх.
Item {
    id: root

    property string confirmed: ""
    property string pending: ""
    property string text: ""
    property bool reduceMotion: false

    property int pixelSize: Theme.fsStage
    property int weight: Font.DemiBold
    property color ink: Theme.text
    property color pendingInk: Theme.muted
    property int maxLines: 2
    property int align: Text.AlignLeft
    property real lineHeightFactor: Theme.captionLineFactor

    readonly property real lineHeight: Math.round(pixelSize * lineHeightFactor)

    readonly property string stable: String(confirmed === undefined || confirmed === null ? "" : confirmed).trim()
    readonly property string draft: String(pending === undefined || pending === null ? "" : pending).trim()
    readonly property string fallback: String(text === undefined || text === null ? "" : text).trim()

    readonly property string content: {
        if (stable.length && draft.length)
            return stable + " " + draft
        if (stable.length)
            return stable
        if (draft.length)
            return draft
        return fallback
    }

    readonly property bool empty: content.length === 0
    readonly property bool splitDraft: stable.length > 0 && draft.length > 0

    function escapeXml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
    }

    function colorHex(value) {
        var name = String(value)
        if (name.charAt(0) === "#")
            return name.length >= 7 ? name.substring(0, 7) : name
        return "#a8a8a4"
    }

    readonly property string displayMarkup: {
        if (!root.splitDraft)
            return root.content
        return root.escapeXml(root.stable)
            + " <font color=\"" + root.colorHex(root.pendingInk) + "\">"
            + root.escapeXml(root.draft) + "</font>"
    }

    readonly property string phraseKey: root.stable.length
        ? root.stable
        : (root.draft.length ? "" : root.fallback)

    implicitHeight: lineHeight * Math.max(1, maxLines)
    height: implicitHeight
    clip: true
    opacity: empty ? 0 : 1

    Behavior on opacity {
        enabled: !root.reduceMotion
        NumberAnimation {
            duration: Theme.baseMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
    }

    Text {
        id: block
        objectName: "captionBlock"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: block.contentHeight
        textFormat: root.splitDraft ? Text.RichText : Text.PlainText
        text: root.displayMarkup
        color: root.ink
        font.family: Theme.fontFamily
        font.pixelSize: root.pixelSize
        font.weight: root.weight
        lineHeight: root.lineHeight
        lineHeightMode: Text.FixedHeight
        wrapMode: Text.Wrap
        horizontalAlignment: root.align
        visible: !root.empty
        // Хвост черновика чуть мягче вспыхивает, когда дописываются слова.
        opacity: block.inkFade
        transform: Translate { y: block.rise }
        property real rise: 0
        property real inkFade: 1
        property string settledKey: ""
        property string lastMarkup: ""
    }

    onDisplayMarkupChanged: {
        if (root.reduceMotion || root.empty)
            return
        // Не анимируем каждый тик: только когда текст реально вырос или сменился.
        if (displayMarkup === block.lastMarkup)
            return
        var grew = displayMarkup.length > block.lastMarkup.length
                && displayMarkup.indexOf(block.lastMarkup) === 0
        block.lastMarkup = displayMarkup
        if (!grew && !root.splitDraft)
            return
        block.inkFade = 0.72
        inkIn.restart()
    }

    onPhraseKeyChanged: {
        if (root.reduceMotion || root.empty)
            return
        if (phraseKey.length && phraseKey !== block.settledKey) {
            block.settledKey = phraseKey
            block.rise = 5
            riseIn.restart()
        } else if (!phraseKey.length) {
            block.settledKey = ""
        }
    }

    NumberAnimation {
        id: riseIn
        target: block
        property: "rise"
        to: 0
        duration: root.reduceMotion ? 0 : Theme.baseMs
        easing.type: Easing.Bezier
        easing.bezierCurve: Theme.easeOut
    }

    NumberAnimation {
        id: inkIn
        target: block
        property: "inkFade"
        to: 1
        duration: root.reduceMotion ? 0 : Theme.contentMs
        easing.type: Easing.Bezier
        easing.bezierCurve: Theme.easeOut
    }
}
