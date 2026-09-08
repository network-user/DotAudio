import QtQml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtMultimedia
import "Theme.js" as Theme

ApplicationWindow {
    id: root

    // Мини-статистика в сводке железа: подпись над значением.
    component HwStat: ColumnLayout {
        property string label: ""
        property string value: ""
        spacing: 1
        Label { text: label; color: Theme.faint; font.pixelSize: Theme.fsMicro }
        Label {
            text: value
            color: Theme.text
            font.pixelSize: Theme.fsBody
            font.weight: Font.DemiBold
            font.family: Theme.monoFamily
        }
    }

    // Старт - полное окно с навигацией. Остров и Live-сцена открываются
    // по запросу (свёртка / старт записи), а не вместо главной страницы.
    title: "DotAudio"
    property string shellMode: "app"
    property bool logsOpen: false
    property bool islandModesOpen: false
    property bool morphGeo: false
    property bool dragging: false
    property bool quietHeld: false
    property real islandCenterX: -1
    property real islandTopY: 32
    // Геометрия окна Live по выбранному пресету; пока окно не зафиксировано
    // замком, можно пододвинуть и расширить. Пресеты меняются в Настройках.
    readonly property var theaterSizes: {
        var s = String(bridge.settings.live_size || "standard")
        return { "small": [560, 300], "standard": [760, 440], "wide": [960, 360], "tall": [640, 560] }[s]
            || [760, 440]
    }
    readonly property int liveLocked: Boolean(bridge.settings.live_locked)
    property real dragGrabDx: 0
    property real dragGrabDy: 0
    property var pageKeys: [
        "live", "dictation", "media", "models", "history", "settings", "transcript", "assistant"
    ]
    // Страница не переключается в тот же кадр: содержимое сначала гаснет,
    // затем новое приезжает снизу. Индекс меняет сам переход.
    property int pageIndex: 0
    property real pageFade: 1
    property real pageSlide: 0
    readonly property int targetPageIndex: Math.max(0, pageKeys.indexOf(bridge.page))

    onTargetPageIndexChanged: {
        if (root.shellMode === "app")
            pageSwap.restart()
        else
            root.pageIndex = root.targetPageIndex
    }
    width: shellMode === "app" ? 1220 : shellMode === "theater"
              ? root.theaterSizes[0]
              : islandW
    height: shellMode === "app" ? 790 : shellMode === "theater"
              ? root.theaterSizes[1]
              : islandH
    // Поверх всех окон живут только остров и сцена Live: они должны быть
    // видны во время другой работы. Полное окно - обычное окно, его может
    // перекрыть любое другое, включая браузер с черновиком статьи.
    property bool stayOnTop: false
    // Qt.Window явно держит кнопку на панели задач; без Tool/Popup окно
    // остаётся обычным приложением и в режиме острова.
    flags: Qt.Window | Qt.FramelessWindowHint | (stayOnTop ? Qt.WindowStaysOnTopHint : 0)
    // Минимум один на все оболочки. Прежний минимум полного окна успевал
    // зажать высоту раньше, чем менялся режим, и остров не сворачивался:
    // окно оставалось высотой 660. Ручного изменения размера здесь нет,
    // размер задаёт сама оболочка.
    minimumWidth: 180
    minimumHeight: 40
    visible: true
    color: shellMode === "app" ? Theme.bg : "transparent"
    opacity: shellMode === "island" ? Math.max(0.9, Number(bridge.settings.island_opacity)) : 1
    font.family: Theme.fontFamily
    font.hintingPreference: Font.PreferDefaultHinting

    readonly property string islandPhase: {
        if (islandModesOpen && !bridge.recording && !bridge.busy)
            return "modePick"
        if (bridge.notice.length > 0 && !bridge.recording && !bridge.busy)
            return "error"
        if (bridge.liveActive && bridge.displayCaption.length)
            return "caption"
        if (bridge.liveActive && bridge.livePhase === "quiet")
            return "quiet"
        if (bridge.liveActive && (bridge.livePhase === "process" || bridge.livePhase === "decoding" || bridge.livePhase === "stopping"))
            return "process"
        if (bridge.liveActive)
            return "listen"
        if (bridge.recording && bridge.caption.length)
            return "caption"
        if (bridge.recording && quietHeld && bridge.inputState === "Нет входного сигнала")
            return "quiet"
        if (bridge.recording)
            return "listen"
        if (!bridge.recording && bridge.busy)
            return "process"
        if (bridge.page === "dictation" && bridge.caption.length && !bridge.busy)
            return "result"
        return "ready"
    }
    readonly property int islandW: {
        switch (islandPhase) {
        case "listen":
        case "quiet":
        case "process": return bridge.page === "live" ? 412 : 352
        case "caption":
        case "result": return 552
        case "error": return 380
        case "modePick": return 352
        default: return bridge.page === "live" ? 268 : 228
        }
    }
    readonly property int islandH: {
        switch (islandPhase) {
        case "listen":
        case "quiet":
        case "process": return 62
        case "caption":
        case "result": return 108
        case "error": return 68
        case "modePick": return 56
        default: return 52
        }
    }
    readonly property int islandR: {
        switch (islandPhase) {
        case "listen":
        case "quiet":
        case "process": return 30
        case "caption":
        case "result": return 32
        case "error": return 26
        case "modePick": return 28
        default: return 24
        }
    }

    // Морф меняет размер настоящего окна, а не прямоугольника на экране:
    // каждый кадр анимации - это запрос к оконной системе. Поэтому здесь нет
    // перелёта: пружина по ширине заставляла окно проехать мимо цели и
    // вернуться, и на этом возврате содержимое заметно дёргалось.
    Behavior on width {
        enabled: root.morphGeo && !root.dragging
        NumberAnimation {
            duration: Theme.morphMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
    }
    Behavior on height {
        enabled: root.morphGeo && !root.dragging
        NumberAnimation {
            duration: Theme.morphMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
    }
    Behavior on opacity {
        NumberAnimation { duration: Theme.baseMs }
    }

    Binding on x {
        when: !root.dragging && root.shellMode !== "app" && root.islandCenterX >= 0
        value: Math.round(root.islandCenterX - root.width / 2)
    }
    Binding on y {
        when: !root.dragging && root.shellMode !== "app"
        value: Math.round(root.islandTopY)
    }

    // Смена оболочки. Между островом и сценой Live разница в размере
    // небольшая, поэтому окно морфит. С полным окном морф пришлось бы гнать
    // на тысячу пикселей: размер меняется сразу, а въезжает содержимое.
    property real shellFade: 1
    property real shellRise: 0

    function enterShell(mode, morph) {
        root.morphGeo = morph
        root.islandModesOpen = false
        // Смена флага «поверх всех» требует пересоздания нативного окна
        // на Windows: короткое скрытие и показ. В этот момент окно
        // прозрачное, поэтому переключение не вспыхивает.
        var wantTop = mode !== "app"
        var needFlags = root.stayOnTop !== wantTop
        var wasVisible = root.visible
        if (needFlags && wasVisible)
            root.hide()
        root.stayOnTop = wantTop
        root.shellMode = mode
        if (needFlags && wasVisible)
            root.show()
        root.shellFade = 0
        root.shellRise = mode === "island" ? 6 : 14
        shellIn.restart()
        if (!morph)
            Qt.callLater(function () { root.morphGeo = true })
    }

    function openApp(page) {
        if (page)
            bridge.selectPage(page)
        bridge.applyIslandClickThrough(false)
        root.enterShell("app", false)
        root.x = Math.max(40, Math.round((Screen.width - root.width) / 2))
        root.y = Math.max(40, Math.round((Screen.height - root.height) / 2))
    }
    function openTheater() {
        bridge.selectPage("live")
        bridge.applyIslandClickThrough(false)
        // Единое Live-окно: отдельное окно зала не дублирует текст поверх.
        bridge.setSetting("caption_overlay", false)
        root.enterShell("theater", true)
    }
    function collapse() {
        root.logsOpen = false
        // Развёрнутое окно должно вернуть обычный размер до морфа в остров,
        // иначе остров растянется на весь экран.
        if (root.visibility === Window.Maximized)
            root.showNormal()
        // Из полного окна остров не сжимается кадр за кадром: анкер острова
        // всё равно переставляет окно, и морф читался бы как рывок.
        root.enterShell("island", root.shellMode !== "app")
        bridge.applyIslandClickThrough(Boolean(bridge.settings.island_click_through))
    }

    Component.onCompleted: {
        root.pageIndex = root.targetPageIndex
        // Якорь острова храним всегда: при свёртке окно вернётся сюда.
        if (Number(bridge.settings.island_x) >= 0) {
            root.islandCenterX = Number(bridge.settings.island_x) + root.islandW / 2
            root.islandTopY = Number(bridge.settings.island_y)
        } else {
            root.islandCenterX = Screen.width / 2
            root.islandTopY = 32
        }
        if (root.shellMode === "app") {
            // Главное окно по центру экрана, с боковой навигацией и Live.
            bridge.selectPage(bridge.page && bridge.page.length ? bridge.page : "live")
            bridge.applyIslandClickThrough(false)
            root.x = Math.max(40, Math.round((Screen.width - root.width) / 2))
            root.y = Math.max(40, Math.round((Screen.height - root.height) / 2))
        } else {
            root.x = Math.round(root.islandCenterX - root.islandW / 2)
            root.y = root.islandTopY
            if (Boolean(bridge.settings.island_click_through))
                bridge.applyIslandClickThrough(true)
        }
        Qt.callLater(function() { root.morphGeo = true })
    }

    Connections {
        target: bridge
        function onIslandRequested() {
            root.collapse()
            root.show()
            root.raise()
            root.requestActivate()
        }
        function onCaptureStarted(_sid, _when) {
            // Старт Live на «динамическом острове» по умолчанию разворачивает
            // единое Live-окно (авто), если пользователь не выключил это.
            if (Boolean(bridge.settings.live_auto_window)
                    && root.shellMode === "island" && bridge.page === "live") {
                root.openTheater()
            }
        }
        function onChanged() {
            if (bridge.recording && bridge.inputState === "Нет входного сигнала") {
                if (!quietTimer.running && !root.quietHeld)
                    quietTimer.start()
            } else {
                quietTimer.stop()
                root.quietHeld = false
            }
        }
    }

    Timer {
        id: quietTimer
        interval: 1200
        onTriggered: root.quietHeld = true
    }

    ParallelAnimation {
        id: shellIn
        NumberAnimation {
            target: root
            property: "shellFade"
            to: 1
            duration: Theme.baseMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
        NumberAnimation {
            target: root
            property: "shellRise"
            to: 0
            duration: Theme.slowMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
    }

    SequentialAnimation {
        id: pageSwap
        ParallelAnimation {
            NumberAnimation { target: root; property: "pageFade"; to: 0; duration: Theme.instantMs }
            NumberAnimation { target: root; property: "pageSlide"; to: -10; duration: Theme.instantMs }
        }
        ScriptAction {
            script: {
                root.pageIndex = root.targetPageIndex
                root.pageSlide = 16
            }
        }
        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "pageFade"
                to: 1
                duration: Theme.baseMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
            NumberAnimation {
                target: root
                property: "pageSlide"
                to: 0
                duration: Theme.slowMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
    }

    // Страницы переключаются с клавиатуры: Ctrl+1…8 по порядку разделов,
    // Ctrl+Tab по кругу. Это работает, пока окно приложения в фокусе, и не
    // мешает глобальным горячим клавишам системы.
    // Instantiator, а не Repeater: Repeater создаёт только Item, и сочетания
    // в нём просто не появлялись.
    Instantiator {
        model: root.pageKeys
        delegate: Shortcut {
            required property string modelData
            required property int index
            sequence: "Ctrl+" + (index + 1)
            enabled: root.shellMode === "app"
            onActivated: bridge.selectPage(modelData)
        }
    }

    Shortcut {
        sequences: ["Ctrl+Tab", "Ctrl+PgDown"]
        enabled: root.shellMode === "app"
        onActivated: bridge.selectPage(root.pageKeys[(root.targetPageIndex + 1) % root.pageKeys.length])
    }

    Shortcut {
        sequences: ["Ctrl+Shift+Tab", "Ctrl+PgUp"]
        enabled: root.shellMode === "app"
        onActivated: {
            var count = root.pageKeys.length
            bridge.selectPage(root.pageKeys[(root.targetPageIndex + count - 1) % count])
        }
    }

    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (bridge.busy)
                bridge.cancel()
            else if (bridge.notice.length > 0)
                bridge.clearNotice()
            else if (root.islandModesOpen)
                root.islandModesOpen = false
            else if (root.shellMode === "theater" || root.shellMode === "app")
                root.collapse()
        }
    }

    MiniIsland {
        visible: root.shellMode === "island"
        anchors.fill: parent
        opacity: root.shellFade
        transform: Translate { y: root.shellRise }
        phase: root.islandPhase
        radius: root.islandR
        clickThrough: Boolean(bridge.settings.island_click_through) && root.shellMode === "island"
        onRequestTheater: root.openTheater()
        onRequestApp: root.openApp(page)
        onRequestModePick: root.islandModesOpen = true
        onCloseModes: root.islandModesOpen = false
        onDragStarted: {
            root.dragging = true
            root.startSystemMove()
        }
        onDragReleased: {
            root.islandCenterX = root.x + root.width / 2
            root.islandTopY = root.y
            root.dragging = false
            bridge.saveIslandPosition(root.x, root.y)
        }
    }

    LiveTheater {
        visible: root.shellMode === "theater"
        anchors.fill: parent
        opacity: root.shellFade
        transform: Translate { y: root.shellRise }
        embedded: false
        onRequestIsland: root.collapse()
        onRequestApp: root.openApp("live")
        onRequestWindowMove: {
            if (!root.liveLocked)
                root.startSystemMove()
        }
        onRequestWindowEdgeResize: {
            if (!root.liveLocked)
                root.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
        }
    }

    Rectangle {
        visible: root.shellMode === "app"
        anchors.fill: parent
        opacity: root.shellFade
        transform: Translate { y: root.shellRise }
        color: Theme.bg
        radius: Theme.radiusSm
        border.width: 1
        border.color: Theme.border
        clip: true

        MouseArea {
            anchors.fill: parent
            z: 0
            onPressed: root.startSystemMove()
        }

        RowLayout {
            anchors.fill: parent
            spacing: 0
            z: 1
            Rectangle {
                Layout.preferredWidth: 228
                Layout.fillHeight: true
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.bottomMargin: 18
                        spacing: 10
                        Rectangle {
                            Layout.preferredWidth: 34
                            Layout.preferredHeight: 34
                            radius: Theme.radiusSm
                            color: Theme.text
                            border.width: 1
                            border.color: Theme.borderHi
                            Text {
                                anchors.centerIn: parent
                                text: ".а"
                                color: Theme.bg
                                font.pixelSize: Theme.fsBody
                                font.weight: Font.Bold
                            }
                        }
                        ColumnLayout {
                            spacing: 0
                            Label { text: ".аудио"; color: Theme.text; font.pixelSize: Theme.fsSection; font.weight: Font.DemiBold }
                            Label { text: "локальная речь"; color: Theme.muted; font.pixelSize: Theme.fsMicro }
                        }
                    }
                    // Навигация. Выделение - один переезжающий блок, а не
                    // мгновенная перекраска: видно, откуда и куда ушёл фокус.
                    Item {
                        id: navBox
                        readonly property int rowH: 48
                        readonly property int rowGap: 6
                        readonly property int current: Math.max(0, root.pageKeys.indexOf(bridge.page))
                        Layout.fillWidth: true
                        Layout.preferredHeight: root.pageKeys.length * rowH
                                                + (root.pageKeys.length - 1) * rowGap

                        function step(delta) {
                            var next = navBox.current + delta
                            if (next < 0 || next >= root.pageKeys.length)
                                return
                            bridge.selectPage(root.pageKeys[next])
                        }

                        Rectangle {
                            width: navBox.width
                            height: navBox.rowH
                            radius: Theme.radiusMd
                            color: Theme.fill
                            border.width: 1
                            border.color: Theme.hairline
                            y: navBox.current * (navBox.rowH + navBox.rowGap)
                            Behavior on y {
                                NumberAnimation {
                                    duration: Theme.slowMs
                                    easing.type: Easing.Bezier
                                    easing.bezierCurve: Theme.easeSpring
                                }
                            }
                        }

                        Column {
                            width: navBox.width
                            spacing: navBox.rowGap

                            Repeater {
                                model: [
                                    { key: "live", icon: "live", title: "Live", detail: "Субтитры" },
                                    { key: "dictation", icon: "dictation", title: "Диктовка", detail: "Голос в текст" },
                                    { key: "media", icon: "media", title: "Караоке", detail: "Аудио и видео" },
                                    { key: "models", icon: "models", title: "Модели", detail: "Whisper" },
                                    { key: "history", icon: "history", title: "История", detail: "Сессии" },
                                    { key: "settings", icon: "settings", title: "Среда", detail: "Устройства" },
                                    { key: "transcript", icon: "media", title: "Транскрибация", detail: "Файл + голоса" },
                                    { key: "assistant", icon: "assistant", title: "Ассистент", detail: "Чат по записи" }
                                ]
                                delegate: Button {
                                    id: nav
                                    required property var modelData
                                    readonly property bool selected: bridge.page === nav.modelData.key
                                    width: navBox.width
                                    height: navBox.rowH
                                    hoverEnabled: true
                                    onClicked: bridge.selectPage(nav.modelData.key)
                                    Accessible.role: Accessible.PageTab
                                    Accessible.name: nav.modelData.title + ", " + nav.modelData.detail
                                    // Стрелки ходят по разделам, когда фокус
                                    // уже в навигации; Tab уводит на страницу.
                                    Keys.onUpPressed: navBox.step(-1)
                                    Keys.onDownPressed: navBox.step(1)
                                    contentItem: RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 12
                                        spacing: 10
                                        Icon {
                                            name: nav.modelData.icon
                                            ink: nav.selected ? Theme.text : Theme.muted
                                            width: 16
                                            height: 16
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 0
                                            Label {
                                                text: nav.modelData.title
                                                color: nav.selected ? Theme.text : "#d1d1d6"
                                                font.pixelSize: Theme.fsBody
                                                font.weight: Font.DemiBold
                                                Behavior on color { ColorAnimation { duration: Theme.baseMs } }
                                            }
                                            Label {
                                                text: nav.modelData.detail
                                                color: Theme.muted
                                                font.pixelSize: Theme.fsMicro
                                                opacity: nav.selected ? 1 : 0.75
                                                Behavior on opacity { NumberAnimation { duration: Theme.baseMs } }
                                            }
                                        }
                                    }
                                    background: Rectangle {
                                        radius: Theme.radiusMd
                                        color: !nav.selected && nav.hovered ? Theme.hairline : "transparent"
                                        border.width: nav.activeFocus ? 1 : 0
                                        border.color: Theme.borderHi
                                        Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                                    }
                                }
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Label { text: ".ядро"; color: Theme.muted; font.pixelSize: Theme.fsMicro; opacity: 0.55 }
                    Text {
                        Layout.fillWidth: true
                        text: (bridge.hotkeysAvailable
                               ? bridge.settings.dictate_hotkey + " диктовка\n" + bridge.settings.island_hotkey + " остров\n" + bridge.settings.paste_last_hotkey + " вставить"
                               : "Горячие клавиши недоступны")
                              + "\nCtrl+1…8 разделы\nEsc в остров"
                        color: Theme.muted
                        font.pixelSize: Theme.fsMicro
                        wrapMode: Text.Wrap
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 24
                spacing: Theme.gapLg
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapMd
                    ColumnLayout {
                        id: titleColumn
                        spacing: 2
                        opacity: root.pageFade
                        // Заголовок приезжает со сменой раздела вместе с
                        // содержимым, а не просто растворяется на месте.
                        transform: Translate { y: titleColumn.titleRise }
                        property real titleRise: 0
                        Connections {
                            target: root
                            function onTargetPageIndexChanged() {
                                titleColumn.titleRise = 8
                                titleIn.restart()
                            }
                        }
                        NumberAnimation {
                            id: titleIn
                            target: titleColumn
                            property: "titleRise"
                            to: 0
                            duration: Theme.slowMs
                            easing.type: Easing.Bezier
                            easing.bezierCurve: Theme.easeOut
                        }
                        Label {
                            text: ({
                                live: "Живые субтитры",
                                dictation: "Диктовка",
                                media: "Караоке-студия",
                                transcript: "Транскрибация записи",
                                monitor: "Мониторинг эфиров",
                                models: "Модели Whisper",
                                history: "История",
                                settings: "Настройки",
                                assistant: "Ассистент"
                            })[bridge.page]
                            color: Theme.text
                            font.pixelSize: Theme.fsHead
                            font.weight: Font.DemiBold
                        }
                        Label { text: bridge.status; color: Theme.muted; font.pixelSize: Theme.fsLabel }
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        visible: bridge.busy || bridge.recording
                        text: bridge.elapsed
                        color: Theme.muted
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.fsLabel
                    }
                    IconButton { iconName: "logs"; onClicked: root.logsOpen = !root.logsOpen; ToolTip.visible: hovered; ToolTip.text: "Журнал" }
                    IconButton {
                        iconName: root.visibility === Window.Maximized ? "restore" : "maximize"
                        onClicked: root.visibility === Window.Maximized ? root.showNormal() : root.showMaximized()
                        ToolTip.visible: hovered
                        ToolTip.text: root.visibility === Window.Maximized ? "Вернуть обычный размер" : "Развернуть на весь экран"
                    }
                    PillButton { text: "Скрыть"; onClicked: root.hide(); ToolTip.visible: hovered; ToolTip.text: "Вернуть: Ctrl+Alt+O" }
                    IconButton { iconName: "close"; onClicked: Qt.quit(); ToolTip.visible: hovered; ToolTip.text: "Закрыть программу" }
                    IconButton { iconName: "collapse"; onClicked: root.collapse(); ToolTip.visible: hovered; ToolTip.text: "Свернуть в остров" }
                }
                Rectangle {
                    id: noticeCard
                    visible: bridge.notice.length > 0
                    Layout.fillWidth: true
                    Layout.preferredHeight: noticeText.implicitHeight + 22
                    radius: Theme.radiusMd
                    color: Theme.fill
                    border.width: 1
                    border.color: Theme.border
                    // Сообщение не выпрыгивает: короткое проявление на месте.
                    NumberAnimation on opacity {
                        running: noticeCard.visible
                        from: 0
                        to: 1
                        duration: Theme.baseMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 8
                        spacing: Theme.gapSm
                        Icon { name: "warning"; width: 16; height: 16 }
                        Text {
                            id: noticeText
                            Layout.fillWidth: true
                            text: bridge.notice
                            color: Theme.text
                            font.pixelSize: Theme.fsLabel
                            wrapMode: Text.Wrap
                        }
                        IconButton { iconName: "close"; onClicked: bridge.clearNotice() }
                    }
                }
                Rectangle {
                    id: gpuHintCard
                    visible: bridge.showGpuHint
                    Layout.fillWidth: true
                    implicitHeight: gpuHintBody.implicitHeight + 2 * Theme.padCard
                    radius: Theme.radiusMd
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.borderHi
                    NumberAnimation on opacity {
                        running: gpuHintCard.visible
                        from: 0
                        to: 1
                        duration: Theme.baseMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                    ColumnLayout {
                        id: gpuHintBody
                        anchors.fill: parent
                        anchors.margins: Theme.padCard
                        spacing: Theme.gapSm
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Label {
                                    text: bridge.gpuHintTitle
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: bridge.gpuHintBody
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsLabel
                                    wrapMode: Text.Wrap
                                }
                            }
                            IconButton {
                                visible: !bridge.gpuSetup.busy
                                iconName: "close"
                                onClicked: bridge.dismissGpuHint()
                                ToolTip.visible: hovered
                                ToolTip.text: "Скрыть подсказку"
                            }
                        }
                        Rectangle {
                            visible: bridge.gpuSetup.busy || Number(bridge.gpuSetup.percent) > 0
                            Layout.fillWidth: true
                            height: 6
                            radius: 3
                            color: Theme.fill
                            Rectangle {
                                width: parent.width * Math.max(0, Math.min(1, Number(bridge.gpuSetup.percent) / 100))
                                height: parent.height
                                radius: 3
                                color: Theme.text
                                Behavior on width { NumberAnimation { duration: Theme.baseMs } }
                            }
                        }
                        Label {
                            visible: bridge.gpuSetup.busy || String(bridge.gpuSetup.phase) === "error"
                            Layout.fillWidth: true
                            text: {
                                var p = Number(bridge.gpuSetup.percent)
                                var msg = String(bridge.gpuSetup.message || "")
                                if (bridge.gpuSetup.busy && p > 0)
                                    return Math.round(p) + "% · " + msg
                                return msg
                            }
                            color: Theme.faint
                            font.pixelSize: Theme.fsSmall
                            font.family: Theme.monoFamily
                            elide: Text.ElideRight
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            PillButton {
                                text: bridge.gpuSetup.busy ? "Отмена" : (String(bridge.hardware.computeAdvice) === "needs_runtime" ? "Настроить GPU" : "Включить видеокарту")
                                primary: !bridge.gpuSetup.busy
                                enabled: !bridge.busy && !bridge.recording
                                onClicked: bridge.gpuSetup.busy ? bridge.cancelGpuSetup() : bridge.setupGpu()
                            }
                            PillButton {
                                visible: String(bridge.hardware.computeAdvice) === "needs_runtime" && !bridge.gpuSetup.busy
                                text: "Инструкция"
                                onClicked: bridge.openCudaHelp()
                            }
                            PillButton {
                                visible: String(bridge.hardware.computeAdvice) === "needs_runtime" && !bridge.gpuSetup.busy
                                text: "Команда pip"
                                onClicked: bridge.copyCudaInstallCommand()
                                ToolTip.visible: hovered
                                ToolTip.text: "Скопировать pip install для CUDA runtime"
                            }
                            Item { Layout.fillWidth: true }
                            Label {
                                visible: Boolean(bridge.hardware.gpuLabel)
                                text: String(bridge.hardware.gpuLabel || "")
                                color: Theme.faint
                                font.pixelSize: Theme.fsSmall
                                font.family: Theme.monoFamily
                            }
                        }
                    }
                }
                StackLayout {
                    id: pageStack
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: root.pageIndex
                    opacity: root.pageFade
                    clip: true
                    transform: Translate { y: root.pageSlide }
                    LiveTheater {
                        embedded: true
                        onRequestIsland: root.collapse()
                        onRequestApp: {}
                    }
                    // Страница создаётся при первом открытии и дальше живёт: пока раздел
                    // не открывали, его привязки не считаются вовсе.
                    Loader {
                        readonly property bool current: StackLayout.isCurrentItem
                        property bool wanted: false
                        asynchronous: true
                        active: wanted
                        source: "DictationPage.qml"
                        onCurrentChanged: if (current) wanted = true
                        Component.onCompleted: if (current) wanted = true
                    }
                    // Страница создаётся при первом открытии и дальше живёт: пока раздел
                    // не открывали, его привязки не считаются вовсе.
                    Loader {
                        readonly property bool current: StackLayout.isCurrentItem
                        property bool wanted: false
                        asynchronous: true
                        active: wanted
                        source: "MediaPage.qml"
                        onCurrentChanged: if (current) wanted = true
                        Component.onCompleted: if (current) wanted = true
                    }
                    // Страница создаётся при первом открытии и дальше живёт: пока раздел
                    // не открывали, его привязки не считаются вовсе.
                    Loader {
                        readonly property bool current: StackLayout.isCurrentItem
                        property bool wanted: false
                        asynchronous: true
                        active: wanted
                        source: "ModelsPage.qml"
                        onCurrentChanged: if (current) wanted = true
                        Component.onCompleted: if (current) wanted = true
                    }
                    // Страница создаётся при первом открытии и дальше живёт: пока раздел
                    // не открывали, его привязки не считаются вовсе.
                    Loader {
                        readonly property bool current: StackLayout.isCurrentItem
                        property bool wanted: false
                        asynchronous: true
                        active: wanted
                        source: "HistoryPage.qml"
                        onCurrentChanged: if (current) wanted = true
                        Component.onCompleted: if (current) wanted = true
                    }
                    // Страница создаётся при первом открытии и дальше живёт: пока раздел
                    // не открывали, его привязки не считаются вовсе.
                    Loader {
                        readonly property bool current: StackLayout.isCurrentItem
                        property bool wanted: false
                        asynchronous: true
                        active: wanted
                        source: "SettingsPage.qml"
                        onCurrentChanged: if (current) wanted = true
                        Component.onCompleted: if (current) wanted = true
                    }
                    TranscriptView { Layout.fillWidth: true; Layout.fillHeight: true }
                    // Страница создаётся при первом открытии и дальше живёт: пока раздел
                    // не открывали, его привязки не считаются вовсе.
                    Loader {
                        readonly property bool current: StackLayout.isCurrentItem
                        property bool wanted: false
                        asynchronous: true
                        active: wanted
                        source: "AssistantPage.qml"
                        onCurrentChanged: if (current) wanted = true
                        Component.onCompleted: if (current) wanted = true
                    }
                }
            }
        }
        Rectangle {
            visible: root.logsOpen
            width: 340
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            z: 10
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: Theme.gapMd
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Журнал работы"; color: Theme.text; font.pixelSize: Theme.fsSection; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    IconButton { iconName: "close"; onClicked: root.logsOpen = false }
                }
                Label { text: "События приложения и распознавания"; color: Theme.muted; font.pixelSize: Theme.fsSmall }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: bridge.logs
                    spacing: Theme.gapSm
                    clip: true
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width
                        implicitHeight: eventText.implicitHeight + 20
                        radius: 12
                        color: Theme.fill
                        Text {
                            id: eventText
                            anchors.fill: parent
                            anchors.margins: 10
                            text: modelData.time + "  " + modelData.message
                            color: Theme.text
                            font.pixelSize: Theme.fsSmall
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }

    CaptionOverlay { id: captionOverlay }
}
