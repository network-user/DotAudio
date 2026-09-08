import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Live-сцена. Главное здесь - текущая фраза, поэтому статус, время и
// кнопки собраны в две тонкие полосы, а середина отдана тексту.
Rectangle {
    id: root

    property bool embedded: false
    // Лента появляется, как только есть завершённая фраза: пустое место под
    // сценой раньше просто копилось, а контекст разговора терялся.
    property bool showTape: bridge.segments.length > 0

    color: Theme.surface
    radius: Theme.radiusXl
    border.width: 1
    border.color: Theme.border
    clip: true

    signal requestIsland()
    signal requestApp()

    readonly property var segments: bridge.segments
    readonly property string previousText: {
        var items = bridge.segments
        if (bridge.partialCaption.length > 0 && items.length)
            return String(items[items.length - 1].text)
        if (items.length >= 2)
            return String(items[items.length - 2].text)
        return ""
    }
    // Лента не съедает сцену: в отдельном окне ей треть, в окне приложения
    // половина - там высоты хватает, и разговор виден глубже.
    readonly property int tapeBudget: Math.round(root.height * (embedded ? 0.5 : 0.32))
    readonly property bool overlayOn: Boolean(bridge.settings.caption_overlay)
    readonly property string stageHint: bridge.liveActive
        ? bridge.liveStatusText
        : "Нажмите «Слушать» - фраза появится здесь"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.padCard
        spacing: Theme.gapMd

        // Полоса состояния. Одна строка вместо прежних двух: заголовок и
        // индикатор больше не повторяют друг друга.
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            spacing: Theme.gapSm

            StatusDot { active: bridge.recording }

            Label {
                text: bridge.liveActive ? bridge.liveStatusText
                      : bridge.busy ? "Завершаем" : "Live не запущен"
                color: bridge.recording ? Theme.text : Theme.muted
                font.pixelSize: Theme.fsSmall
                font.weight: Font.DemiBold
                font.family: Theme.fontFamily
                Behavior on color { ColorAnimation { duration: Theme.slowMs } }
            }

            Item { Layout.fillWidth: true }

            Label {
                opacity: bridge.recording || bridge.busy ? 1 : 0
                text: bridge.elapsed
                color: Theme.muted
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fsSmall
                Behavior on opacity { NumberAnimation { duration: Theme.baseMs } }
            }

            PillButton {
                compact: true
                text: bridge.liveSourceLabel
                enabled: !bridge.recording && !bridge.busy
                onClicked: bridge.cycleLiveSource()
                ToolTip.visible: hovered
                ToolTip.text: "Микрофон, звук компьютера или оба сразу"
            }

            PillButton {
                compact: true
                text: bridge.liveSensitivityLabel
                enabled: !bridge.recording && !bridge.busy
                onClicked: bridge.toggleLiveSensitivity()
                ToolTip.visible: hovered
                ToolTip.text: "«Речь» показывает только речь, «Всё» - любой звук, включая песни"
            }

            IconButton {
                iconName: "overlay"
                ink: root.overlayOn ? Theme.text : Theme.muted
                onClicked: bridge.setSetting("caption_overlay", !root.overlayOn)
                ToolTip.visible: hovered
                ToolTip.text: root.overlayOn ? "Скрыть субтитры зала" : "Показать субтитры зала"
            }

            IconButton {
                iconName: "copy"
                enabled: bridge.text.length > 0
                onClicked: bridge.copyText()
                ToolTip.visible: hovered
                ToolTip.text: "Скопировать расшифровку"
            }

            IconButton {
                visible: !root.embedded
                iconName: "expand"
                onClicked: root.requestApp()
                ToolTip.visible: hovered
                ToolTip.text: "Открыть окно приложения"
            }

            IconButton {
                visible: !root.embedded
                iconName: "collapse"
                onClicked: root.requestIsland()
                ToolTip.visible: hovered
                ToolTip.text: "Свернуть в остров"
            }
        }

        // Пустое место собирается над лентой, поэтому текст всегда прижат к
        // сцене, а не плавает в середине окна.
        Item { Layout.fillWidth: true; Layout.fillHeight: true }

        // Лента завершённых фраз стоит над текущей: разговор читается сверху
        // вниз, и движение совпадает с промоушеном строки внутри сцены.
        ListView {
            id: tape
            visible: root.showTape
            property bool followsLive: true
            Layout.fillWidth: true
            Layout.preferredHeight: root.showTape ? Math.min(contentHeight, root.tapeBudget) : 0
            Layout.maximumHeight: root.tapeBudget
            clip: true
            spacing: 2
            model: bridge.segments
            boundsBehavior: Flickable.StopAtBounds
            onMovementStarted: followsLive = false

            delegate: Item {
                required property var modelData
                required property int index
                width: tape.width
                height: 26
                opacity: Math.max(0.3, 1.0 - (tape.count - 1 - index) * 0.22)

                Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: parent.modelData.text
                    // Лента тише текущей фразы: главная строка на сцене одна.
                    color: parent.index === tape.count - 1 ? Theme.muted : Theme.faint
                    font.pixelSize: parent.index === tape.count - 1 ? Theme.fsBody : Theme.fsLabel
                    font.family: Theme.fontFamily
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
            }

            add: Transition {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.baseMs }
                NumberAnimation {
                    property: "y"
                    from: 18
                    duration: Theme.slowMs
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easeOut
                }
            }
            displaced: Transition {
                NumberAnimation {
                    properties: "x,y"
                    duration: Theme.slowMs
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easeOut
                }
            }

            Connections {
                target: bridge
                function onSegmentsChanged() {
                    if (tape.followsLive && tape.count > 0)
                        tape.positionViewAtEnd()
                }
            }
        }

        PillButton {
            visible: root.showTape && !tape.followsLive && tape.count > 0
            compact: true
            Layout.alignment: Qt.AlignHCenter
            text: "К текущему тексту"
            onClicked: {
                tape.followsLive = true
                tape.positionViewAtEnd()
            }
        }

        // Сцена занимает ровно столько, сколько нужно строкам фразы. Пока
        // лента показывает предыдущие фразы, сцена не дублирует их сама.
        // Выравнивание влево: центр заставлял бы всю строку ехать на каждом
        // обновлении черновика, и читать было бы нечего.
        CaptionStage {
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
            previous: root.previousText
            showPrevious: !root.showTape
            confirmed: bridge.confirmedCaption
            pending: bridge.partialCaption
            placeholder: root.stageHint
            pixelSize: root.embedded ? Theme.fsStageSm : Theme.fsStage
            maxLines: 3
            align: Text.AlignLeft
        }

        // Пока фраз нет, сцена стоит по центру: пустой экран не должен
        // выглядеть прижатым к кнопкам. Как только появляется лента, нижняя
        // распорка исчезает и текст держится у сцены.
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !root.showTape
        }

        // Управление. Уровень стоит прямо над кнопкой: видно, слышит ли
        // приложение источник, до того как нажали «Слушать».
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.gapSm

            Waveform {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredHeight: 20
                bars: 48
                barH: 20
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gapSm

                Item { Layout.fillWidth: true }

                PillButton {
                    text: bridge.recording ? "Стоп" : bridge.busy ? "Останавливаем" : "Слушать"
                    primary: true
                    enabled: !bridge.busy || bridge.recording
                    onClicked: bridge.toggleRecording()
                }

                PillButton {
                    visible: bridge.busy
                    compact: true
                    text: bridge.recording ? "Отменить" : "Остановить сейчас"
                    onClicked: bridge.forceStop()
                    ToolTip.visible: hovered
                    ToolTip.text: "Остановить без сохранения незавершённой фразы"
                }

                Item { Layout.fillWidth: true }
            }
        }
    }
}
