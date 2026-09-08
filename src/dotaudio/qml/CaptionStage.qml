import QtQuick
import "Theme.js" as Theme

// Сцена живой речи: фиксированное место для текущей и предыдущей фразы.
// Общая для Live-окна и субтитров зала.
Item {
    id: stage

    property string previous: ""
    property string confirmed: ""
    property string pending: ""
    property string placeholder: ""

    property int pixelSize: Theme.fsStage
    property int maxLines: 2
    property int align: Text.AlignLeft
    property color ink: Theme.text
    property color mutedInk: Theme.muted
    property bool showPrevious: true
    property bool animateWords: true

    readonly property bool hasCaption: String(confirmed).length + String(pending).length > 0
    readonly property int previousSize: Math.max(Theme.fsBody, Math.round(pixelSize * 0.46))

    // Естественная высота сцены: строки фразы плюс блок предыдущей строки.
    // По ней окно зала и Live-сцена отводят место заранее, поэтому текст не
    // перемещается, когда фраза становится длиннее.
    readonly property int lineStep: Math.round(pixelSize * Theme.captionLineFactor)
    readonly property int previousBlock: showPrevious
        ? Math.round(previousSize * 1.3) + Math.round(pixelSize * 0.34)
        : 0
    implicitHeight: lineStep * Math.max(1, maxLines) + previousBlock

    Text {
        id: promoted
        objectName: "previousCaption"
        visible: stage.showPrevious && stage.previous.length > 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: live.top
        anchors.bottomMargin: Math.round(stage.pixelSize * 0.34)
        height: Math.round(stage.previousSize * 1.3)
        text: stage.previous
        color: stage.mutedInk
        font.family: Theme.fontFamily
        font.pixelSize: stage.previousSize
        horizontalAlignment: stage.align
        elide: Text.ElideRight
        maximumLineCount: 1
        wrapMode: Text.NoWrap
        opacity: Theme.historyAlpha
    }

    CaptionText {
        id: live
        objectName: "liveCaption"
        anchors.left: parent.left
        anchors.right: parent.right
        y: stage.previousBlock + Math.round((stage.height - stage.previousBlock - height) / 2)
        confirmed: stage.confirmed
        pending: stage.pending
        pixelSize: stage.pixelSize
        maxLines: stage.maxLines
        align: stage.align
        ink: stage.ink
        animateWords: stage.animateWords
        opacity: stage.hasCaption ? 1 : 0
        Behavior on opacity {
            NumberAnimation {
                duration: Theme.fastMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
    }

    // Подсказка занимает то же место, что и фраза, поэтому взгляд не
    // перескакивает, когда появляется первый текст.
    Text {
        anchors.left: parent.left
        anchors.right: parent.right
        y: live.y + Math.round((live.height - height) / 2)
        visible: opacity > 0.01
        opacity: stage.hasCaption || !String(stage.placeholder).length ? 0 : 1
        text: stage.placeholder
        color: stage.mutedInk
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(Theme.fsBody, Math.round(stage.pixelSize * 0.52))
        horizontalAlignment: stage.align
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
        Behavior on opacity {
            NumberAnimation {
                duration: Theme.contentMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
    }
}
