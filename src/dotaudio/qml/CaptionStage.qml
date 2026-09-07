import QtQuick
import "Theme.js" as Theme

// Сцена живой речи: одна крупная фраза в фокусе, предыдущая уходит вверх
// уменьшаясь, как будто её повысили в историю. Одна и та же сцена
// используется в Live-окне и в субтитрах зала, поэтому движение текста
// везде одинаковое.
Item {
    id: stage

    property string previous: ""
    property string confirmed: ""
    property string pending: ""
    property string placeholder: ""

    property int pixelSize: Theme.fsStage
    property int maxLines: 2
    property int align: Text.AlignHCenter
    property color ink: Theme.text
    property color mutedInk: Theme.muted
    property bool showPrevious: true
    property bool animateWords: true

    readonly property bool hasCaption: String(confirmed).length + String(pending).length > 0
    readonly property int previousSize: Math.max(13, Math.round(pixelSize * 0.46))

    onPreviousChanged: stage.pushPrevious()
    Component.onCompleted: stage.pushPrevious()

    function pushPrevious() {
        var value = String(stage.previous || "")
        if (history.count && history.get(history.count - 1).body === value)
            return
        // Уходящая строка остаётся в модели, пока доигрывает исчезновение;
        // глубже двух строк история сцене не нужна.
        while (history.count >= 2)
            history.remove(0)
        history.append({ "body": value })
    }

    ListModel { id: history }

    // Предыдущая фраза. Новая строка приезжает снизу и уменьшается со
    // сценического размера, прежняя уходит выше и растворяется.
    Item {
        id: promoted
        visible: stage.showPrevious
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: live.top
        anchors.bottomMargin: Math.round(stage.pixelSize * 0.34)
        height: Math.round(stage.previousSize * 1.3)

        Repeater {
            model: history

            delegate: Text {
                id: line
                required property string body
                required property int index
                readonly property bool active: line.index === history.count - 1
                property real entry: Math.round(stage.pixelSize * 0.6)
                property real bloom: 1.3

                width: promoted.width
                text: line.body
                color: stage.mutedInk
                font.family: Theme.fontFamily
                font.pixelSize: stage.previousSize
                horizontalAlignment: stage.align
                elide: Text.ElideRight
                maximumLineCount: 1
                wrapMode: Text.NoWrap
                opacity: line.active && line.body.length ? Theme.historyAlpha : 0
                y: line.active ? 0 : -Math.round(stage.previousSize * 0.9)
                scale: bloom
                transformOrigin: stage.align === Text.AlignHCenter ? Item.Center : Item.Left
                transform: Translate { y: line.entry }

                Behavior on y {
                    NumberAnimation {
                        duration: Theme.promoteMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                }
                Behavior on opacity {
                    NumberAnimation {
                        duration: Theme.promoteMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                }

                Component.onCompleted: promote.start()

                ParallelAnimation {
                    id: promote
                    NumberAnimation {
                        target: line
                        property: "entry"
                        to: 0
                        duration: Theme.promoteMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                    NumberAnimation {
                        target: line
                        property: "bloom"
                        to: 1
                        duration: Theme.promoteMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                }
            }
        }
    }

    CaptionText {
        id: live
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
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
        anchors.verticalCenter: parent.verticalCenter
        visible: opacity > 0.01
        opacity: stage.hasCaption || !String(stage.placeholder).length ? 0 : 1
        text: stage.placeholder
        color: stage.mutedInk
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(14, Math.round(stage.pixelSize * 0.52))
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
