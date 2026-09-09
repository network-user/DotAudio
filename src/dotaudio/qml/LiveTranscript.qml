import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

// Живой текст одним потоком: сказанные фразы читаются сверху вниз, а строка,
// которую распознают прямо сейчас, стоит последней и не двигается с места.
//
// До этого одно и то же показывали три разных места - лента однострочных
// огрызков, «предыдущая фраза» внутри сцены и отдельная панель истории.
// Текст рвался на куски, выравнивание менялось от блока к блоку, а высота
// ленты ездила на каждой фразе. Здесь колонка одна: и прошлые фразы, и живая
// строка стоят на одной левой границе и набраны одним шрифтом, поэтому глаз
// продолжает читать, а не ищет, куда переехал текст.
Item {
    id: root

    // Завершённые фразы (bridge.segments) и текущая, ещё не завершённая.
    property var segments: []
    // Последняя фраза списка ещё не закончила предложение и уже стоит в
    // живой строке как confirmed: в колонке её не повторяем, иначе одно и то
    // же предложение читается дважды - выше мелко и ниже крупно.
    property bool hideLast: false
    property string confirmed: ""
    property string pending: ""
    property string placeholder: ""

    readonly property var shown: {
        var items = segments || []
        if (hideLast && items.length)
            return items.slice(0, items.length - 1)
        return items
    }

    property int pixelSize: Theme.fsStageSm
    // Сколько строк держит живая строка. Место отводится заранее, поэтому
    // растущая фраза не выталкивает историю вверх на каждом черновике.
    property int liveLines: 2
    property bool showTimes: true
    property bool reduceMotion: false
    // Цвет фона под потоком: по нему строится затухание у верхнего края.
    property color fadeColor: Theme.surface

    readonly property int historySize: Math.max(Theme.fsBody, Math.round(pixelSize * 0.62))
    readonly property int liveHeight: Math.round(pixelSize * Theme.captionLineFactor) * Math.max(1, liveLines)
    readonly property bool hasLive: String(confirmed).length + String(pending).length > 0
    readonly property bool following: list.followsLive

    signal copyRequested(string text)
    signal seekRequested(real seconds)

    function toBottom() {
        list.followsLive = true
        list.positionViewAtEnd()
    }

    function timecode(seconds) {
        var total = Math.max(0, Math.round(Number(seconds)))
        var minutes = Math.floor(total / 60)
        var rest = total % 60
        return (minutes < 10 ? "0" : "") + minutes + ":" + (rest < 10 ? "0" : "") + rest
    }

    ListView {
        id: list
        objectName: "livePhrases"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: liveRow.top
        anchors.bottomMargin: Theme.gapSm
        // Сказанное стоит вплотную к живой строке и растёт вверх: при двух
        // фразах между ними и текущей речью не зияет пустое поле, а когда
        // разговор длинный, список упирается в верх и прокручивается.
        // Пустоту забирает отступ, а не высота списка: высота, посчитанная от
        // собственного содержимого, оставила бы короткий список нулевым
        // навсегда - делегаты не создаются в области нулевой высоты.
        topMargin: Math.max(0, height - contentHeight)
        clip: true
        spacing: Theme.gapSm
        model: root.shown
        boundsBehavior: Flickable.StopAtBounds
        // Список читают, а не перелистывают: колесо двигает на строку,
        // а не пролетает половину разговора.
        flickDeceleration: 4000
        maximumFlickVelocity: 1400
        cacheBuffer: 400

        // Лента следует за речью, пока пользователь сам не отмотал вверх.
        property bool followsLive: true
        onMovementEnded: followsLive = atYEnd
        onContentHeightChanged: if (followsLive) positionViewAtEnd()

        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        delegate: Item {
            id: phrase
            required property var modelData
            required property int index

            width: ListView.view.width
            implicitHeight: body.implicitHeight + 2 * Theme.gapXs
            height: implicitHeight

            readonly property string phraseText: String(modelData.text || "")
            readonly property bool latest: index === list.count - 1

            HoverHandler { id: rowHover }

            Rectangle {
                anchors.fill: parent
                anchors.leftMargin: -Theme.gapSm
                anchors.rightMargin: -Theme.gapSm
                radius: Theme.radiusSm
                color: rowHover.hovered ? Theme.fill : "transparent"
                Behavior on color { ColorAnimation { duration: Theme.fastMs } }
            }

            Row {
                id: body
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.gapSm

                Text {
                    width: root.showTimes ? timeMetrics.width : 0
                    visible: root.showTimes
                    text: root.timecode(phrase.modelData.start)
                    color: Theme.faint
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.fsMicro
                    // Таймкод стоит на первой строке фразы, а не по центру
                    // многострочного блока: колонка времени остаётся ровной.
                    topPadding: Math.round(root.historySize * 0.28)
                    TextMetrics {
                        id: timeMetrics
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.fsMicro
                        text: "00:00"
                    }
                }

                TextEdit {
                    id: phraseBody
                    objectName: "livePhraseText"
                    width: body.width - (root.showTimes ? timeMetrics.width + Theme.gapSm : 0)
                           - copyButton.width - Theme.gapSm
                    text: phrase.phraseText
                    readOnly: true
                    selectByMouse: true
                    // Готовый текст можно выделить и скопировать мышью: это
                    // расшифровка, а не картинка.
                    persistentSelection: false
                    color: phrase.latest ? Theme.text : Theme.muted
                    selectionColor: Theme.fillHi
                    selectedTextColor: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: root.historySize
                    wrapMode: Text.Wrap
                    textFormat: TextEdit.PlainText
                }

                IconButton {
                    id: copyButton
                    iconName: "copy"
                    glyph: 13
                    implicitWidth: 24
                    implicitHeight: 24
                    opacity: rowHover.hovered ? 1 : 0
                    visible: opacity > 0.02
                    onClicked: root.copyRequested(phrase.phraseText)
                    ToolTip.visible: hovered
                    ToolTip.text: "Скопировать фразу"
                    Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }
                }
            }

            // Новая фраза не выталкивает соседей движением: она проявляется
            // на своём месте, а лента доезжает вниз сама.
            opacity: 0
            Component.onCompleted: appear.start()
            NumberAnimation {
                id: appear
                target: phrase
                property: "opacity"
                to: 1
                duration: root.reduceMotion ? 0 : Theme.contentMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
    }

    // Верхний край прокрутки не рвёт строку пополам: она уходит в фон.
    // Градиент дешевле маски и не требует слоя для всего списка.
    Rectangle {
        anchors.left: list.left
        anchors.right: list.right
        anchors.top: list.top
        height: Math.round(root.historySize * 1.1)
        visible: list.contentHeight > list.height
        gradient: Gradient {
            GradientStop { position: 0.0; color: root.fadeColor }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    // Пустое состояние занимает место списка, поэтому появление первой фразы
    // не сдвигает живую строку.
    Text {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: liveRow.top
        anchors.bottomMargin: Theme.gapMd
        visible: opacity > 0.01
        opacity: list.count === 0 && !root.hasLive ? 1 : 0
        text: root.placeholder
        color: Theme.faint
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fsBody
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
        Behavior on opacity { NumberAnimation { duration: Theme.contentMs } }
    }

    // Живая строка. Её место отведено заранее и не зависит от длины фразы.
    Item {
        id: liveRow
        objectName: "liveRow"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.liveHeight

        CaptionText {
            id: live
            objectName: "liveCaption"
            anchors.fill: parent
            confirmed: root.confirmed
            pending: root.pending
            pixelSize: root.pixelSize
            maxLines: root.liveLines
            align: Text.AlignLeft
        }
    }

    // Возврат к речи после ручной прокрутки. Пока лента следует сама, кнопки
    // нет: она нужна только когда пользователь ушёл читать сказанное раньше.
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: liveRow.top
        anchors.bottomMargin: Theme.gapXs
        visible: opacity > 0.02
        opacity: list.followsLive || list.count === 0 ? 0 : 1
        implicitWidth: backLabel.implicitWidth + 22
        implicitHeight: 26
        radius: 13
        color: Theme.surface3
        border.width: 1
        border.color: Theme.borderHi
        Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }

        Text {
            id: backLabel
            anchors.centerIn: parent
            text: "К текущей речи"
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsSmall
            font.weight: Font.DemiBold
        }

        TapHandler { onTapped: root.toBottom() }
    }
}
