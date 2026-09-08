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
    // Пользователь тянет окно / растягивает за угол (нативные окно-действия).
    signal requestWindowMove()
    signal requestWindowEdgeResize()
    // Замок фиксирует положение и размер окна Live и делает клики сквозными.
    readonly property bool locked: Boolean(bridge.settings.live_locked)

    // Раскрытая история фраз поверх сцены. Открывается кликом по самому
    // тексту или кнопкой-журналом рядом со статусом; повторный клик, Esc и
    // клик по фону закрывают. Прокрутка - мышью (колёсико/полоса) и жестами:
    // история живёт над лентой и не спорит с ней за чтение.
    property bool historyOpen: false

    // Esc сначала закрывает открытую историю, и только затем оболочка
    // сворачивается в остров: не теряем раскрытый список случайным Esc.
    Shortcut {
        sequence: "Escape"
        enabled: root.historyOpen
        onActivated: root.historyOpen = false
    }

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
    // Это измеренное отставание последнего принятого фрагмента, а не обещание
    // скорости модели. После первой фразы оно помогает сразу увидеть, успевает
    // ли выбранный профиль за текущим источником.
    readonly property string latencyLabel: {
        var ms = Math.max(0, Number(bridge.liveLatencyMs))
        if (!bridge.liveActive || ms < 1)
            return ""
        return ms < 1000 ? "≈ " + Math.round(ms) + " мс"
                         : "≈ " + (Math.round(ms / 100) / 10) + " с"
    }
    readonly property string sourceCheckText: String(bridge.deviceTest.message || "")

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

            Label {
                visible: root.latencyLabel.length > 0
                text: root.latencyLabel
                color: Theme.faint
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fsSmall
                ToolTip.visible: latencyHover.containsMouse
                ToolTip.text: "Отставание последнего текста от аудио"
                HoverHandler { id: latencyHover }
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

            PillButton {
                compact: true
                text: bridge.liveModelText
                enabled: !bridge.recording && !bridge.busy
                onClicked: bridge.cycleLiveModel()
                ToolTip.visible: hovered
                ToolTip.text: "Каким движком распознавать Live. Цикл: Vosk малая/большая, затем Whisper"
            }

            PillButton {
                compact: true
                visible: !bridge.recording && !bridge.busy
                text: bridge.deviceTest.phase === "starting" || bridge.deviceTest.phase === "listening"
                    ? "Проверяем…" : "Проверить"
                enabled: bridge.deviceTest.phase !== "starting" && bridge.deviceTest.phase !== "listening"
                onClicked: bridge.testLiveSource()
                ToolTip.visible: hovered
                ToolTip.text: "Коротко проверить выбранный источник без сохранения записи"
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
                iconName: "lock"
                ink: root.locked ? Theme.text : Theme.muted
                onClicked: bridge.setSetting("live_locked", !root.locked)
                ToolTip.visible: hovered
                ToolTip.text: root.locked
                    ? "Положение и размер зафиксированы"
                    : "Зафиксировать положение и размер Live-окна"
            }

            // Ребро-захват: тянуть приложенное маленькое поле - перемещать окно.
            Item {
                id: moveGrip
                Layout.preferredWidth: 16
                Layout.preferredHeight: 22
                visible: !root.locked
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.SizeAllCursor
                    onPressed: root.requestWindowMove()
                }
                Icon { name: "move"; ink: Theme.muted; width: 15; height: 15; anchors.centerIn: parent }
            }

            // Ребро-захват: растянуть окно за угол (native resize).
            Item {
                Layout.preferredWidth: 12
                Layout.preferredHeight: 22
                visible: !root.locked
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.SizeFDiagCursor
                    onPressed: root.requestWindowEdgeResize()
                }
                Icon { name: "sizer"; ink: Theme.muted; width: 12; height: 22; anchors.centerIn: parent }
            }

            IconButton {
                iconName: "history"
                ink: root.historyOpen ? Theme.text : Theme.muted
                enabled: bridge.segments.length > 0
                onClicked: root.historyOpen = !root.historyOpen
                ToolTip.visible: hovered
                ToolTip.text: bridge.segments.length > 0
                    ? "История сказанных фраз (" + bridge.segments.length + ")"
                    : "Пока нет завершённых фраз"
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

        // Перед стартом результат проверки остаётся рядом с кнопкой запуска:
        // не нужно уходить в настройки, чтобы понять, слышит ли Live источник.
        Label {
            Layout.fillWidth: true
            visible: !bridge.liveActive && root.sourceCheckText.length > 0
            text: root.sourceCheckText
            color: bridge.deviceTest.phase === "error" || bridge.deviceTest.phase === "silent"
                ? Theme.rec : Theme.muted
            font.pixelSize: Theme.fsSmall
            font.family: Theme.fontFamily
            wrapMode: Text.Wrap
        }

        // Пустое место собирается над лентой, поэтому текст всегда прижат к
        // сцене, а не плавает в середине окна.
        Item { Layout.fillWidth: true; Layout.fillHeight: true }

        // Лента завершённых фраз стоит над текущей: разговор читается сверху
        // вниз, и движение совпадает с промоушеном строки внутри сцены.
        ListView {
            id: tape
            visible: root.showTape && !root.historyOpen
            property bool followsLive: true
            Layout.fillWidth: true
            Layout.preferredHeight: (root.showTape && !root.historyOpen)
                ? Math.min(contentHeight, root.tapeBudget) : 0
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
                // Готовая фраза не выпрыгивает: она проявляется на своём
                // конечном месте, затем лента плавно сдвигается под неё.
                ParallelAnimation {
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.baseMs; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easeOut }
                    NumberAnimation {
                        property: "y"
                        from: 26
                        duration: Theme.slowMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
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
            animateWords: !Boolean(bridge.settings.reduce_motion)

            // Клик по самому тексту или прокрутка над раскрывают историю
            // сказанных фраз (пока пользователь её не открыл вручную - кнопкой).
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (!Boolean(bridge.settings.live_click_history))
                        return
                    if (bridge.segments.length > 0 && !root.historyOpen)
                        root.historyOpen = true
                    else if (root.historyOpen)
                        root.historyOpen = false
                }
                onWheel: {
                    if (Boolean(bridge.settings.live_click_history)
                            && bridge.segments.length > 0 && !root.historyOpen)
                        root.historyOpen = true
                    wheel.accepted = true
                }
            }
        }

        // Панель истории: раскрывается кликом по тексту или кнопкой-журналом
        // сверху. Показывает все завершённые фразы этой сессии, прокрутку
        // мышью и стрелками. Открытая панель съедает большую часть окна и
        // заменяет собой ленту, чтобы не показывать один текст дважды.
        Rectangle {
            id: historyPanel
            visible: root.historyOpen
            Layout.fillWidth: true
            Layout.preferredHeight: historyOpen ? Math.round(root.height * 0.55) : 0
            radius: Theme.radiusLg
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            clip: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Icon { name: "history"; ink: Theme.text; width: 15; height: 15 }
                    Label {
                        Layout.fillWidth: true
                        text: "История сказанных фраз · " + bridge.segments.length
                        color: Theme.text
                        font.pixelSize: Theme.fsLabel
                        font.weight: Font.DemiBold
                        font.family: Theme.fontFamily
                    }
                    Text {
                        text: "Колёсико или стрелки листают"
                        color: Theme.faint
                        font.pixelSize: Theme.fsMicro
                        font.family: Theme.fontFamily
                    }
                    IconButton { iconName: "close"; onClicked: root.historyOpen = false }
                }

                ListView {
                    id: historyList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 4
                    interactive: true
                    clip: true
                    model: bridge.segments
                    keyNavigationEnabled: true
                    flickableDirection: Flickable.VerticalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    delegate: Rectangle {
                        id: histRow
                        required property var modelData
                        required property int index
                        width: historyList.width
                        height: Math.min(54, 34 + modelData.text.length / 60)
                        radius: Theme.radiusSm
                        color: histRow.latest ? Theme.fill : "transparent"
                        property bool latest: index === bridge.segments.length - 1
                        Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }
                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusSm
                            color: "transparent"
                            border.width: histRow.latest ? 1 : 0
                            border.color: histRow.latest ? Theme.borderHi : "transparent"
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 10
                            spacing: 10
                            Text {
                                Layout.alignment: Qt.AlignVCenter
                                text: histRow.latest ? "↳" : String(index + 1)
                                color: histRow.latest ? Theme.text : Theme.faint
                                font.pixelSize: Theme.fsMicro
                                font.family: Theme.monoFamily
                                width: 24
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignVCenter
                                text: histRow.modelData.text
                                color: histRow.latest ? Theme.text : Theme.muted
                                font.pixelSize: histRow.latest ? Theme.fsBody : Theme.fsSmall
                                font.family: Theme.fontFamily
                                font.weight: histRow.latest ? Font.DemiBold : Font.Normal
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                            }
                        }
                    }
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Item { Layout.fillWidth: true }
                    PillButton {
                        compact: true
                        text: "К последней"
                        enabled: bridge.segments.length > 0
                        onClicked: historyList.positionViewAtEnd()
                    }
                    Label {
                        visible: bridge.segments.length === 0
                        text: "Пока нет завершённых фраз"
                        color: Theme.faint
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.fontFamily
                    }
                }
            }
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
