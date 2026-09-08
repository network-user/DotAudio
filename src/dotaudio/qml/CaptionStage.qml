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
    readonly property int lineStep: Math.round(pixelSize * Theme.captionLineFactor)
    readonly property int previousSize: Math.max(Theme.fsBody, Math.round(pixelSize * Theme.previousLineFactor))
    readonly property int previousWeight: Theme.previousWeight

    // Естественная высота сцены: строки фразы плюс блок предыдущей строки.
    // По ней окно зала и Live-сцена отводят место заранее, поэтому текст не
    // перемещается, когда фраза становится длиннее. Блок предыдущей строки
    // держит контекст разговора видимым и заметнее глухой подписи.
    readonly property int previousPad: Math.round(pixelSize * 0.20)
    readonly property int previousHeight: Math.round(previousSize * 1.35)
    readonly property int previousBlock: showPrevious
        ? previousHeight + previousPad
        : 0
    implicitHeight: lineStep * Math.max(1, maxLines) + previousBlock

    Text {
        id: promoted
        objectName: "previousCaption"
        visible: stage.showPrevious && stage.previous.length > 0 && opacity > 0.01
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: live.top
        height: stage.showPrevious ? stage.previousBlock : 0
        verticalAlignment: Text.AlignBottom
        anchors.bottomMargin: 0
        text: stage.previous
        color: stage.mutedInk
        font.family: Theme.fontFamily
        font.pixelSize: stage.previousSize
        font.weight: stage.previousWeight
        horizontalAlignment: stage.align
        elide: Text.ElideRight
        maximumLineCount: 1
        wrapMode: Text.NoWrap
        opacity: stage.previous.length > 0 ? Theme.historyAlpha : 0
        // Прежняя фраза не возникал внезапно: она проявляется с лёгким
        // сдвигом вверх, как строка, уходящая в историю поверх сцены.
        transform: Translate { y: promoted.riseAnim }
        property real riseAnim: 2
        Behavior on riseAnim {
            NumberAnimation {
                duration: Theme.promoteMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
        onTextChanged: if (stage.previous.length) {
            promoted.opacity = 0
            promoted.riseAnim = 8
            promoteIn.restart()
            promoteRise.restart()
        }
        Behavior on opacity {
            NumberAnimation {
                duration: Theme.promoteMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
        NumberAnimation {
            id: promoteIn
            target: promoted
            property: "opacity"
            to: Theme.historyAlpha
            duration: Theme.promoteMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
        NumberAnimation {
            id: promoteRise
            target: promoted
            property: "riseAnim"
            to: 0
            duration: Theme.promoteMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
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
