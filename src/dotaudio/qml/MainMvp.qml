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

    property string shellMode: "island"
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
    property var pageKeys: ["live", "dictation", "media", "models", "history", "settings", "transcript"]
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
    property bool stayOnTop: true
    flags: Qt.FramelessWindowHint | (stayOnTop ? Qt.WindowStaysOnTopHint : 0)
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
        if (Number(bridge.settings.island_x) >= 0) {
            root.x = Number(bridge.settings.island_x)
            root.y = Number(bridge.settings.island_y)
            root.islandCenterX = root.x + root.islandW / 2
            root.islandTopY = root.y
        } else {
            root.islandCenterX = Screen.width / 2
            root.islandTopY = 32
            root.x = Math.round(root.islandCenterX - root.islandW / 2)
            root.y = root.islandTopY
        }
        if (Boolean(bridge.settings.island_click_through))
            bridge.applyIslandClickThrough(true)
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

    // Страницы переключаются с клавиатуры: Ctrl+1…6 по порядку разделов,
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
                        Layout.preferredHeight: 7 * rowH + 6 * rowGap

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
                                    { key: "transcript", icon: "media", title: "Транскрибация", detail: "Файл + голоса" }
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
                              + "\nCtrl+1…7 разделы\nEsc в остров"
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
                                settings: "Настройки"
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
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 14
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 220
                                radius: Theme.radiusXl
                                color: Theme.surface
                                border.width: 1
                                border.color: Theme.border
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 24
                                    spacing: Theme.gapSm
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 9
                                        StatusDot { active: bridge.recording }
                                        Label {
                                            text: bridge.recording
                                                  ? (bridge.inputState === "Нет входного сигнала" ? "Не слышу микрофон" : "Слушаю")
                                                  : bridge.busy ? "Распознаю" : "Готов к диктовке"
                                            color: Theme.muted
                                            font.pixelSize: Theme.fsSmall
                                            font.weight: Font.DemiBold
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
                                    }
                                    // Пока текста нет - приглашение и горячая клавиша.
                                    // Как только фраза распознана, она занимает это же
                                    // место и появляется словами.
                                    Item {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        ColumnLayout {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.verticalCenter: parent.verticalCenter
                                            spacing: Theme.gapSm
                                            visible: opacity > 0.01
                                            opacity: bridge.caption.length ? 0 : 1
                                            Behavior on opacity { NumberAnimation { duration: Theme.contentMs } }
                                            Label {
                                                Layout.fillWidth: true
                                                text: bridge.recording ? "Говорите естественно" : "Скажите мысль, текст попадёт в буфер"
                                                color: Theme.text
                                                font.pixelSize: Theme.fsHero
                                                font.weight: Font.DemiBold
                                                wrapMode: Text.Wrap
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: Boolean(bridge.settings.dictate_hold)
                                                      ? "Удерживайте " + bridge.settings.dictate_hotkey + ", чтобы диктовать. Отпустите - текст попадёт в буфер. Вставка последнего: " + bridge.settings.paste_last_hotkey + "."
                                                      : "После остановки расшифровка сохранится в истории. Горячая клавиша: " + bridge.settings.dictate_hotkey + ". Вставка последнего: " + bridge.settings.paste_last_hotkey + "."
                                                color: Theme.muted
                                                font.pixelSize: Theme.fsBody
                                                wrapMode: Text.Wrap
                                            }
                                        }
                                        CaptionText {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.verticalCenter: parent.verticalCenter
                                            confirmed: bridge.caption
                                            pixelSize: Theme.fsHero
                                            maxLines: 3
                                            align: Text.AlignLeft
                                            opacity: bridge.caption.length ? 1 : 0
                                            Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        PillButton { text: bridge.recording ? "Стоп" : bridge.busy ? "Остановить" : "Диктовать"; primary: true; onClicked: bridge.toggleRecording() }
                                        PillButton { text: "Копировать"; enabled: bridge.text.length > 0; onClicked: bridge.copyText() }
                                        PillButton { text: "Вставить последний"; enabled: bridge.lastTranscript.length > 0 && !bridge.recording; onClicked: bridge.pasteLastTranscript() }
                                        Item { Layout.fillWidth: true }
                                        Waveform { Layout.preferredWidth: 180; bars: 22; barH: 18 }
                                    }
                                }
                            }
                            TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; editable: true }
                        }
                    }
                    Item {
                        RowLayout {
                            anchors.fill: parent
                            spacing: Theme.gapLg
                            ColumnLayout {
                                // Доля ширины задаётся растяжением, а не через
                                // parent.width: прежняя привязка зацикливалась и
                                // выдавливала редактор за край окна.
                                Layout.fillWidth: true
                                Layout.horizontalStretchFactor: 53
                                Layout.fillHeight: true
                                spacing: Theme.gapMd
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    radius: Theme.radiusXl
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    clip: true
                                    VideoOutput { id: mediaVideo; anchors.fill: parent; anchors.margins: 10; visible: mediaPlayer.hasVideo; fillMode: VideoOutput.PreserveAspectFit }
                                    Image { anchors.fill: parent; anchors.margins: 10; visible: !mediaPlayer.hasVideo && bridge.coverUrl.length > 0; source: bridge.coverUrl; fillMode: Image.PreserveAspectCrop }
                                    KaraokePreview { visible: bridge.mediaUrl.length > 0; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: Theme.padCard; height: 126; player: mediaPlayer; segments: bridge.segments }
                                    ColumnLayout {
                                        anchors.centerIn: parent
                                        width: Math.min(parent.width - 64, 330)
                                        visible: !bridge.mediaUrl
                                        spacing: 10
                                        Icon { Layout.alignment: Qt.AlignHCenter; name: "media"; width: 28; height: 28 }
                                        Label { Layout.fillWidth: true; text: "Аудио в караоке"; horizontalAlignment: Text.AlignHCenter; color: Theme.text; font.pixelSize: Theme.fsLead; font.weight: Font.DemiBold }
                                        Text { Layout.fillWidth: true; text: "Откройте аудио или видео, получите текст по словам и доведите таймкоды."; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.fsBody }
                                        PillButton { Layout.alignment: Qt.AlignHCenter; text: "Выбрать медиа"; primary: true; onClicked: bridge.importFile() }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    PillButton { text: "Открыть"; onClicked: bridge.importFile() }
                                    PillButton { text: "Обложка"; enabled: bridge.mediaUrl.length > 0; onClicked: bridge.chooseCover() }
                                    IconButton { iconName: "undo"; enabled: bridge.canUndoEdit; onClicked: bridge.undoEdit(); ToolTip.visible: hovered; ToolTip.text: "Отменить правку" }
                                    IconButton { iconName: "redo"; enabled: bridge.canRedoEdit; onClicked: bridge.redoEdit(); ToolTip.visible: hovered; ToolTip.text: "Повторить правку" }
                                    Item { Layout.fillWidth: true }
                                    PillButton { text: "слова→тишина"; enabled: bridge.segments.length > 0; onClicked: bridge.realignKaraoke(); ToolTip.visible: hovered; ToolTip.text: "Притянуть границы слов к тишине аудио (без повторного распознавания)" }
                                    PillButton { text: "ASS"; enabled: bridge.segments.length > 0; onClicked: bridge.exportKaraokeFile() }
                                    PillButton { text: bridge.rendering ? "Рендер…" : "MP4"; primary: true; enabled: bridge.segments.length > 0 && !bridge.rendering; onClicked: bridge.exportKaraokeVideo() }
                                }
                            }
                            KaraokeEditor { Layout.fillWidth: true; Layout.horizontalStretchFactor: 47; Layout.fillHeight: true; player: mediaPlayer; segments: bridge.segments; editable: true }
                        }
                        MediaPlayer { id: mediaPlayer; source: bridge.mediaUrl; videoOutput: mediaVideo; audioOutput: AudioOutput {} }
                    }
                    Item {
                        // Одна прокрутка на страницу. Раньше список моделей скроллился
                        // внутри страницы и последняя карточка обрезалась половиной.
                        Flickable {
                            anchors.fill: parent
                            contentWidth: width
                            contentHeight: modelsColumn.implicitHeight
                            clip: true
                            ScrollBar.vertical: ScrollBar {}
                            ColumnLayout {
                                id: modelsColumn
                                width: parent.width
                                spacing: 10

                                // Сводка устройства и рекомендация. Числа здесь
                                // фактические: потоки CPU, ОЗУ и то, что видит
                                // CTranslate2. Проба доезжает фоном, поэтому пока
                                // она не готова, поля честно показывают прочерк.
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: hwBody.implicitHeight + 2 * Theme.padCard
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: hwBody
                                        anchors.fill: parent
                                        anchors.margins: Theme.padCard
                                        spacing: Theme.gapSm
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: Theme.gapSm
                                            Label { text: "Ваше устройство"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                            Label {
                                                text: bridge.hardware.compute_label && bridge.hardware.compute_label.length ? bridge.hardware.compute_label : "Определяем…"
                                                color: Theme.muted
                                                font.pixelSize: Theme.fsSmall
                                                font.family: Theme.monoFamily
                                            }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: Theme.gapLg
                                            HwStat { label: "Потоки CPU"; value: bridge.hardware.threads > 0 ? String(bridge.hardware.threads) : "-" }
                                            HwStat { label: "ОЗУ"; value: bridge.hardware.ram_gb ? bridge.hardware.ram_gb + " ГБ" : "-" }
                                            HwStat { label: "CUDA"; value: bridge.hardware.cuda_devices > 0 ? "есть" : "нет" }
                                            HwStat { label: "Рекомендуем"; value: bridge.recommendedModel }
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: "Подходит и не подходит оцениваются по факту: память сравнивается с реальным ОЗУ, скорость - рекомендация по числу потоков, не замер. Замер появится после первого распознавания."
                                            color: Theme.muted
                                            font.pixelSize: Theme.fsSmall
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }

                            Repeater {
                                model: ["tiny", "base", "small", "medium", "large-v3", "turbo"]
                                delegate: Rectangle {
                                    id: modelCard
                                    required property string modelData
                                    required property int index
                                    readonly property var disk: {
                                        var lib = bridge.modelLibrary
                                        for (var i = 0; i < lib.length; i++) {
                                            if (lib[i].model === modelCard.modelData)
                                                return lib[i]
                                        }
                                        return { "ready": false, "bytes": 0 }
                                    }
                                    readonly property var spec: bridge.modelCatalog[modelCard.modelData] || null
                                    readonly property var fit: {
                                        // Чтение hardware держит привязку живой: сводка
                                        // доезжает фоном, и оценка пересчитывается сама.
                                        var hw = bridge.hardware
                                        return bridge.modelFit(modelCard.modelData)
                                    }
                                    readonly property bool selected: bridge.settings.model === modelData
                                    readonly property bool preparing: bridge.modelPreparing && bridge.modelState.model === modelData
                                    readonly property bool cached: Boolean(disk.ready)
                                    // Снимок загрузки относится к этой карточке, пока
                                    // идёт скачивание файлов модели.
                                    readonly property var dl: bridge.modelDownload
                                    readonly property bool downloading: preparing
                                        && dl.model === modelData && dl.phase === "download"
                                    Layout.fillWidth: true
                                    implicitHeight: cardBody.implicitHeight + 2 * 16
                                    radius: Theme.radiusLg
                                    color: selected ? Theme.fill : Theme.surface
                                    border.width: 1
                                    border.color: selected ? Theme.borderHi : Theme.border
                                    Behavior on color { ColorAnimation { duration: Theme.baseMs } }
                                    Behavior on border.color { ColorAnimation { duration: Theme.baseMs } }

                                    ColumnLayout {
                                        id: cardBody
                                        anchors.fill: parent
                                        anchors.margins: 16
                                        spacing: Theme.gapSm

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: Theme.gapSm
                                            Icon { name: "models"; width: 18; height: 18; ink: modelCard.selected ? Theme.text : Theme.muted }
                                            Label { text: modelCard.modelData; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                            // Бейджи состояния: выбрана / в кеше / рекомендована.
                                            // Состояние не передаётся одним цветом.
                                            Rectangle {
                                                visible: modelCard.selected
                                                radius: 8
                                                implicitHeight: 16
                                                implicitWidth: badgeSel.implicitWidth + 12
                                                color: Theme.text
                                                Label { id: badgeSel; anchors.centerIn: parent; text: "выбрана"; color: Theme.bg; font.pixelSize: Theme.fsMicro; font.weight: Font.DemiBold }
                                            }
                                            Rectangle {
                                                visible: modelCard.cached && !modelCard.selected
                                                radius: 8
                                                implicitHeight: 16
                                                implicitWidth: badgeCache.implicitWidth + 12
                                                color: Theme.fill
                                                border.width: 1
                                                border.color: Theme.border
                                                Label {
                                                    id: badgeCache
                                                    anchors.centerIn: parent
                                                    text: modelCard.disk.bytes > 0 ? "в кеше · " + Math.round(modelCard.disk.bytes / 1048576) + " МБ" : "в кеше"
                                                    color: Theme.muted
                                                    font.pixelSize: Theme.fsMicro
                                                }
                                            }
                                            Rectangle {
                                                visible: !modelCard.selected && bridge.recommendedModel === modelCard.modelData
                                                radius: 8
                                                implicitHeight: 16
                                                implicitWidth: badgeRec.implicitWidth + 12
                                                color: "transparent"
                                                border.width: 1
                                                border.color: Theme.borderHi
                                                Label { id: badgeRec; anchors.centerIn: parent; text: "для этого ПК"; color: Theme.muted; font.pixelSize: Theme.fsMicro }
                                            }
                                            Item { Layout.fillWidth: true }
                                            Label {
                                                visible: modelCard.spec !== null
                                                text: modelCard.spec ? modelCard.spec.params + " параметров" : ""
                                                color: Theme.muted
                                                font.pixelSize: Theme.fsSmall
                                                font.family: Theme.monoFamily
                                            }
                                        }

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: Theme.gapSm
                                            // Справочная шкала нагрузки: пять сегментов по
                                            // числу параметров из каталога. Это ориентир
                                            // архитектуры, не замер скорости машины.
                                            Item {
                                                Layout.preferredWidth: 84
                                                Layout.preferredHeight: 5
                                                Layout.alignment: Qt.AlignVCenter
                                                Repeater {
                                                    model: 5
                                                    Rectangle {
                                                        required property int index
                                                        x: index * 17
                                                        width: 14
                                                        radius: 2
                                                        anchors.top: parent.top
                                                        anchors.bottom: parent.bottom
                                                        color: modelCard.spec && index < modelCard.spec.load
                                                               ? (modelCard.selected ? Theme.text : Theme.muted)
                                                               : Theme.hairline
                                                        Behavior on color { ColorAnimation { duration: Theme.baseMs } }
                                                    }
                                                }
                                            }
                                            Label {
                                                visible: modelCard.spec !== null
                                                text: modelCard.spec ? "скачать ~" + modelCard.spec.download_mb + " МБ · память ~" + modelCard.spec.ram_gb + " ГБ" : ""
                                                color: Theme.muted
                                                font.pixelSize: Theme.fsSmall
                                            }
                                            Item { Layout.fillWidth: true }
                                            Label {
                                                text: modelCard.fit.note
                                                color: modelCard.fit.state === "tight" || modelCard.fit.state === "slow" ? Theme.muted : Theme.faint
                                                font.pixelSize: Theme.fsSmall
                                                font.italic: modelCard.fit.state === "tight" || modelCard.fit.state === "slow"
                                            }
                                        }

                                        // Прогресс подготовки. Во время скачивания
                                        // проценты, объём и скорость берутся из факта
                                        // полученных байтов; после - модель грузится в
                                        // память без процента, там честный свип.
                                        ColumnLayout {
                                            visible: modelCard.preparing
                                            Layout.fillWidth: true
                                            spacing: 5

                                            Item {
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 4
                                                clip: true
                                                Rectangle {
                                                    anchors.fill: parent
                                                    radius: 2
                                                    color: Theme.hairline
                                                }
                                                Rectangle {
                                                    visible: modelCard.downloading
                                                    width: parent.width * Math.min(1, (modelCard.dl.percent || 0) / 100)
                                                    height: parent.height
                                                    radius: 2
                                                    color: Theme.text
                                                    Behavior on width {
                                                        NumberAnimation {
                                                            duration: Theme.fastMs
                                                            easing.type: Easing.OutQuad
                                                        }
                                                    }
                                                }
                                                Rectangle {
                                                    id: sweep
                                                    visible: !modelCard.downloading
                                                    width: parent.width * 0.3
                                                    height: parent.height
                                                    radius: 2
                                                    color: Theme.text
                                                    SequentialAnimation on x {
                                                        loops: Animation.Infinite
                                                        running: modelCard.preparing && !modelCard.downloading
                                                        NumberAnimation { from: -sweep.width; to: modelCard.width; duration: 1100; easing.type: Easing.InOutQuad }
                                                    }
                                                }
                                            }

                                            Label {
                                                visible: modelCard.downloading
                                                text: Math.round(modelCard.dl.percent || 0) + "%"
                                                      + " · " + Math.round(modelCard.dl.received_mb || 0)
                                                      + " из " + Math.round(modelCard.dl.total_mb || 0) + " МБ"
                                                      + " · " + (modelCard.dl.speed_mb_s || 0) + " МБ/с"
                                                color: Theme.muted
                                                font.pixelSize: Theme.fsSmall
                                                font.family: Theme.monoFamily
                                            }
                                            Label {
                                                visible: !modelCard.downloading && bridge.modelState.message.length > 0
                                                text: bridge.modelState.message
                                                color: Theme.muted
                                                font.pixelSize: Theme.fsSmall
                                            }
                                        }

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: Theme.gapSm
                                            PillButton {
                                                text: modelCard.selected ? "Выбрана" : "Выбрать"
                                                enabled: !modelCard.selected && !bridge.busy
                                                onClicked: bridge.setSetting("model", modelCard.modelData)
                                            }
                                            PillButton {
                                                visible: modelCard.preparing
                                                text: "Отмена"
                                                onClicked: bridge.cancelModelPrepare()
                                            }
                                            PillButton {
                                                visible: !modelCard.preparing && !modelCard.cached
                                                text: "Загрузить"
                                                primary: true
                                                enabled: !bridge.busy && !bridge.modelPreparing
                                                onClicked: { bridge.setSetting("model", modelCard.modelData); bridge.prepareSelectedModel() }
                                            }
                                            Label {
                                                visible: modelCard.cached && !modelCard.preparing
                                                text: "Готова к работе"
                                                color: Theme.muted
                                                font.pixelSize: Theme.fsSmall
                                            }
                                            Item { Layout.fillWidth: true }
                                        }
                                    }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: rulesBox.implicitHeight + 2 * Theme.padCard
                                radius: Theme.radiusLg
                                color: Theme.surface
                                border.width: 1
                                border.color: Theme.border
                                ColumnLayout {
                                    id: rulesBox
                                    anchors.fill: parent
                                    anchors.margins: Theme.padCard
                                    spacing: Theme.gapSm
                                    Label { text: "Словарь и snippets"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                    Text { Layout.fillWidth: true; text: "Термины помогают Whisper, а замены применяются только к финальному тексту диктовки. Всё остаётся на этом устройстве."; color: Theme.muted; font.pixelSize: Theme.fsSmall; wrapMode: Text.Wrap }
                                    RowLayout {
                                        id: termRow
                                        Layout.fillWidth: true
                                        // Enter в любом поле добавляет запись: до этого
                                        // словарь пополнялся только мышью.
                                        function addTerm() {
                                            if (!termInput.text.length)
                                                return
                                            bridge.addDictionaryEntry(termInput.text, mistakeInput.text)
                                            termInput.clear()
                                            mistakeInput.clear()
                                            termInput.forceActiveFocus()
                                        }
                                        TextField { id: termInput; Layout.fillWidth: true; placeholderText: "Термин"; color: Theme.text; placeholderTextColor: Theme.muted; onAccepted: termRow.addTerm(); background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                                        TextField { id: mistakeInput; Layout.preferredWidth: 180; placeholderText: "Вариант ошибки"; color: Theme.text; placeholderTextColor: Theme.muted; onAccepted: termRow.addTerm(); background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                                        PillButton { text: "+"; onClicked: termRow.addTerm(); ToolTip.visible: hovered; ToolTip.text: "Добавить термин" }
                                    }
                                    ListView { Layout.fillWidth: true; Layout.preferredHeight: Math.min(70, contentHeight); model: bridge.dictionary; clip: true; delegate: RowLayout { required property var modelData; required property int index; width: ListView.view.width; Text { Layout.fillWidth: true; text: modelData.term + (modelData.misheard ? " ← " + modelData.misheard : ""); color: Theme.muted; elide: Text.ElideRight; font.pixelSize: Theme.fsSmall } PillButton { text: "×"; onClicked: bridge.removeDictionaryEntry(index) } } }
                                    RowLayout {
                                        id: snippetRow
                                        Layout.fillWidth: true
                                        function addSnippet() {
                                            if (!snippetInput.text.length)
                                                return
                                            bridge.addSnippet(snippetInput.text, expansionInput.text)
                                            snippetInput.clear()
                                            expansionInput.clear()
                                            snippetInput.forceActiveFocus()
                                        }
                                        TextField { id: snippetInput; Layout.preferredWidth: 180; placeholderText: "Фраза"; color: Theme.text; placeholderTextColor: Theme.muted; onAccepted: snippetRow.addSnippet(); background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                                        TextField { id: expansionInput; Layout.fillWidth: true; placeholderText: "Вставляемый текст"; color: Theme.text; placeholderTextColor: Theme.muted; onAccepted: snippetRow.addSnippet(); background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                                        PillButton { text: "+"; onClicked: snippetRow.addSnippet(); ToolTip.visible: hovered; ToolTip.text: "Добавить замену" }
                                    }
                                }
                            }
                            }
                        }
                    }
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: Theme.gapMd
                            TextField {
                                Layout.fillWidth: true
                                placeholderText: "Поиск по названию или тексту"
                                color: Theme.text
                                placeholderTextColor: Theme.muted
                                leftPadding: 16
                                rightPadding: 16
                                onTextChanged: bridge.refreshHistory(text)
                                background: Rectangle { radius: 14; color: Theme.surface; border.width: 1; border.color: Theme.border }
                            }
                            Item {
                                Layout.fillWidth: true
                                Layout.fillHeight: true

                                ColumnLayout {
                                    anchors.centerIn: parent
                                    width: Math.min(parent.width - 60, 360)
                                    visible: bridge.history.length === 0
                                    spacing: Theme.gapSm
                                    Icon {
                                        Layout.alignment: Qt.AlignHCenter
                                        name: "history"
                                        ink: Theme.faint
                                        width: 30
                                        height: 30
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        horizontalAlignment: Text.AlignHCenter
                                        text: "Пока нет сессий"
                                        color: Theme.text
                                        font.pixelSize: Theme.fsLead
                                        font.weight: Font.DemiBold
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        horizontalAlignment: Text.AlignHCenter
                                        wrapMode: Text.Wrap
                                        text: "Сессии появятся здесь после первой диктовки, Live или разбора файла."
                                        color: Theme.muted
                                        font.pixelSize: Theme.fsBody
                                    }
                                }

                                ListView {
                                    anchors.fill: parent
                                    model: bridge.history
                                    spacing: Theme.gapSm
                                    clip: true
                                    add: Transition {
                                        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.baseMs }
                                        NumberAnimation {
                                            property: "y"
                                            from: 12
                                            duration: Theme.slowMs
                                            easing.type: Easing.Bezier
                                            easing.bezierCurve: Theme.easeOut
                                        }
                                    }
                                    delegate: Rectangle {
                                        id: historyCard
                                        required property var modelData
                                        width: ListView.view.width
                                        height: 74
                                        radius: Theme.radiusMd
                                        color: historyMouse.containsMouse ? Theme.fill : Theme.surface
                                        border.width: 1
                                        border.color: historyMouse.containsMouse ? Theme.borderHi : Theme.border
                                        scale: historyMouse.pressed ? 0.99 : 1
                                        Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                                        Behavior on border.color { ColorAnimation { duration: Theme.fastMs } }
                                        Behavior on scale { NumberAnimation { duration: Theme.fastMs } }
                                        MouseArea { id: historyMouse; anchors.fill: parent; hoverEnabled: true; onClicked: bridge.openSession(historyCard.modelData.id) }
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 14
                                            Icon { name: "history"; width: 16; height: 16; ink: Theme.muted }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 3
                                                Text { text: historyCard.modelData.title; color: Theme.text; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                                                Text { text: historyCard.modelData.mode + " · " + historyCard.modelData.segment_count + " фрагм."; color: Theme.muted; font.pixelSize: Theme.fsSmall }
                                            }
                                            Icon { name: "expand"; width: 14; height: 14; ink: Theme.muted; rotation: -90 }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Item {
                        Flickable {
                            anchors.fill: parent
                            contentWidth: width
                            contentHeight: settingsColumn.implicitHeight
                            clip: true
                            ColumnLayout {
                                id: settingsColumn
                                width: parent.width
                                spacing: Theme.gapMd
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: dictEngineBox.implicitHeight + 2 * Theme.padCard
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: dictEngineBox
                                        anchors.fill: parent
                                        anchors.margins: Theme.padCard
                                        spacing: Theme.gapSm
                                        Label { text: "Движок распознавания Live"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        Text { Layout.fillWidth: true; text: "Vosk - лёгкая потоковая Kaldi-модель для слабого CPU (по умолчанию). Whisper - точнее, но заметно тяжелее. Диктовка и медиа всегда на Whisper."; color: Theme.muted; font.pixelSize: Theme.fsLabel; wrapMode: Text.Wrap }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            PillButton { text: "Vosk"; primary: String(bridge.settings.live_engine) === "vosk"; onClicked: bridge.setSetting("live_engine", "vosk") }
                                            PillButton { text: "Whisper"; primary: String(bridge.settings.live_engine) !== "vosk"; onClicked: bridge.setSetting("live_engine", "whisper") }
                                            Item { Layout.fillWidth: true }
                                            Label { text: bridge.liveModelText; color: Theme.faint; font.pixelSize: Theme.fsSmall }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            visible: String(bridge.settings.live_engine) === "vosk"
                                            Label { text: "Модель vosk"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.fillWidth: true }
                                            PillButton { text: "Малая (~44 МБ)"; primary: String(bridge.settings.vosk_size) === "small"; onClicked: bridge.setSetting("vosk_size", "small"); ToolTip.visible: hovered; ToolTip.text: "vosk-model-small-ru-0.22 · для слабого CPU" }
                                            PillButton { text: "Большая (~1,8 ГБ)"; primary: String(bridge.settings.vosk_size) !== "small"; onClicked: bridge.setSetting("vosk_size", "big"); ToolTip.visible: hovered; ToolTip.text: "vosk-model-ru-0.42 · точнее, тяжелее" }
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: languageBox.implicitHeight + 2 * Theme.padCard
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: languageBox
                                        anchors.fill: parent
                                        anchors.margins: Theme.padCard
                                        spacing: Theme.gapSm
                                        Label { text: "Язык и вывод"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text { Layout.fillWidth: true; text: "Распознавание ориентировано на русский язык."; color: Theme.muted; font.pixelSize: Theme.fsLabel; wrapMode: Text.Wrap }
                                            PillButton { text: "Русский"; primary: bridge.settings.language === "ru" && bridge.settings.task === "transcribe"; onClicked: { bridge.setSetting("language", "ru"); bridge.setSetting("task", "transcribe") } }
                                            PillButton { text: "English subtitles"; primary: bridge.settings.task === "translate"; onClicked: bridge.setSetting("task", "translate") }
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: deviceBox.implicitHeight + 2 * Theme.padCard
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: deviceBox
                                        anchors.fill: parent
                                        anchors.margins: Theme.padCard
                                        spacing: 10
                                        Label { text: "Источник Live и устройства"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        Text { Layout.fillWidth: true; text: "Диктовка всегда с микрофона. Live: микрофон, звук компьютера или Авто - оба сразу. На острове источник переключается кнопкой."; color: Theme.muted; font.pixelSize: Theme.fsSmall; wrapMode: Text.Wrap }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: "Источник Live"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.fillWidth: true }
                                            PillButton { text: "Микрофон"; primary: String(bridge.settings.live_source) === "microphone"; onClicked: bridge.setSetting("live_source", "microphone") }
                                            PillButton { text: "Звук системы"; primary: String(bridge.settings.live_source) === "system"; onClicked: bridge.setSetting("live_source", "system") }
                                            PillButton { text: "Авто"; primary: String(bridge.settings.live_source) === "mixed"; onClicked: bridge.setSetting("live_source", "mixed"); ToolTip.visible: hovered; ToolTip.text: "Микрофон и звук компьютера одновременно" }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            visible: String(bridge.settings.live_source) === "microphone" || String(bridge.settings.live_source) === "mixed"
                                            Dropdown {
                                                id: inputChooser
                                                Layout.fillWidth: true
                                                model: [{ name: "Системный микрофон", id: "" }].concat(bridge.devices)
                                                textRole: "name"
                                                currentIndex: {
                                                    var selected = String(bridge.settings.input_device)
                                                    for (var i = 0; i < model.length; i++) {
                                                        if (String(model[i].id) === selected) return i
                                                    }
                                                    return 0
                                                }
                                                onActivated: function(index) {
                                                    var device = inputChooser.model[index]
                                                    bridge.setSetting("input_device", String(device.id))
                                                }
                                            }
                                            PillButton { text: "Обновить"; onClicked: bridge.refreshDevices() }
                                            PillButton { text: "Проверить Live"; primary: true; onClicked: bridge.testLiveSource() }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            visible: String(bridge.settings.live_source) === "system" || String(bridge.settings.live_source) === "mixed"
                                            Dropdown {
                                                id: loopbackChooser
                                                Layout.fillWidth: true
                                                model: [{ name: "Системный вывод Windows", id: "" }].concat(bridge.loopbacks)
                                                textRole: "name"
                                                currentIndex: {
                                                    var selected = String(bridge.settings.loopback_device)
                                                    for (var i = 0; i < model.length; i++) {
                                                        if (String(model[i].id) === selected) return i
                                                    }
                                                    return 0
                                                }
                                                onActivated: function(index) {
                                                    var device = loopbackChooser.model[index]
                                                    bridge.setSetting("loopback_device", String(device.id))
                                                }
                                            }
                                            PillButton { text: "Обновить"; onClicked: bridge.refreshLoopbacks() }
                                            PillButton { text: "Проверить Live"; primary: true; onClicked: bridge.testLiveSource() }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Dropdown {
                                                id: outputChooser
                                                Layout.fillWidth: true
                                                model: [{ name: "Системный вывод", id: "" }].concat(bridge.outputs)
                                                textRole: "name"
                                                currentIndex: {
                                                    var selected = String(bridge.settings.output_device)
                                                    for (var i = 0; i < model.length; i++) {
                                                        if (String(model[i].id) === selected) return i
                                                    }
                                                    return 0
                                                }
                                                onActivated: function(index) {
                                                    var device = outputChooser.model[index]
                                                    bridge.setSetting("output_device", String(device.id))
                                                }
                                            }
                                            PillButton { text: "Обновить"; onClicked: bridge.refreshOutputs() }
                                            PillButton { text: "Тон"; onClicked: bridge.testOutputDevice() }
                                            PillButton { text: "Loopback"; primary: String(bridge.settings.live_source) === "system" || String(bridge.settings.live_source) === "mixed"; onClicked: bridge.testSystemLoopback() }
                                        }
                                        // Уровень проверки устройства. Шкала та же,
                                        // что у осциллограммы, поэтому «тихо» здесь
                                        // и «тихо» на острове выглядят одинаково.
                                        Item {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 6
                                            Rectangle {
                                                anchors.fill: parent
                                                radius: 3
                                                color: Theme.hairline
                                            }
                                            Rectangle {
                                                height: parent.height
                                                radius: 3
                                                width: parent.width * Theme.levelShape(bridge.deviceTest.level)
                                                color: Theme.text
                                                Behavior on width { NumberAnimation { duration: 110; easing.type: Easing.OutQuad } }
                                            }
                                        }
                                        Label { text: bridge.deviceTest.message || "Проверка не сохраняет запись."; color: Theme.muted; font.pixelSize: Theme.fsSmall }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: islandBox.implicitHeight + 2 * Theme.padCard
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: islandBox
                                        anchors.fill: parent
                                        anchors.margins: Theme.padCard
                                        spacing: Theme.gapSm
                                        Label { text: "Остров"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: "Диктовка"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.preferredWidth: 90 }
                                            Repeater {
                                                model: ["Ctrl+Alt+Space", "Ctrl+Shift+Space", "Ctrl+Win+Space"]
                                                PillButton {
                                                    required property string modelData
                                                    text: modelData
                                                    primary: bridge.settings.dictate_hotkey === modelData
                                                    onClicked: bridge.setHotkeys(modelData, bridge.settings.island_hotkey)
                                                }
                                            }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: "Остров"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.preferredWidth: 90 }
                                            Repeater {
                                                model: ["Ctrl+Alt+O", "Ctrl+Shift+O", "Ctrl+Win+O"]
                                                PillButton {
                                                    required property string modelData
                                                    text: modelData
                                                    primary: bridge.settings.island_hotkey === modelData
                                                    onClicked: bridge.setHotkeys(bridge.settings.dictate_hotkey, modelData)
                                                }
                                            }
                                        }
                                        ToggleSwitch {
                                            text: "Удерживать клавишу, чтобы диктовать"
                                            checked: Boolean(bridge.settings.dictate_hold)
                                            onToggled: bridge.setSetting("dictate_hold", checked)
                                        }
                                        Label {
                                            text: "По умолчанию повтор " + bridge.settings.dictate_hotkey + " начинает и останавливает запись. Вставка последнего текста: " + bridge.settings.paste_last_hotkey + "."
                                            color: Theme.muted
                                            font.pixelSize: Theme.fsSmall
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: "Непрозрачность"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.preferredWidth: 118 }
                                            Slider {
                                                id: opacitySlider
                                                Layout.fillWidth: true
                                                from: 0.86
                                                to: 1
                                                value: Number(bridge.settings.island_opacity)
                                                onMoved: bridge.setSetting("island_opacity", value)
                                                background: Rectangle {
                                                    x: opacitySlider.leftPadding
                                                    y: (opacitySlider.height - height) / 2
                                                    width: opacitySlider.availableWidth
                                                    height: 4
                                                    radius: 2
                                                    color: Theme.fill
                                                    Rectangle {
                                                        width: opacitySlider.position * parent.width
                                                        height: parent.height
                                                        radius: 2
                                                        color: Theme.text
                                                    }
                                                }
                                                handle: Rectangle {
                                                    x: opacitySlider.leftPadding + opacitySlider.visualPosition * (opacitySlider.availableWidth - width)
                                                    y: (opacitySlider.height - height) / 2
                                                    width: 18
                                                    height: 18
                                                    radius: 9
                                                    color: opacitySlider.pressed ? "#d6d6d2" : Theme.text
                                                    border.width: 1
                                                    border.color: Theme.borderHi
                                                    scale: opacitySlider.pressed ? 1.1 : 1
                                                    Behavior on scale {
                                                        NumberAnimation {
                                                            duration: Theme.fastMs
                                                            easing.type: Easing.Bezier
                                                            easing.bezierCurve: Theme.easeSpring
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ToggleSwitch { text: "Пропускать клики"; checked: Boolean(bridge.settings.island_click_through); onToggled: bridge.setIslandClickThrough(checked) }
                                            Item { Layout.fillWidth: true }
                                            ToggleSwitch { text: "Запоминать позицию"; checked: Boolean(bridge.settings.island_snap); onToggled: bridge.setSetting("island_snap", checked) }
                                        }
                                        Label {
                                            visible: Boolean(bridge.settings.island_click_through)
                                            text: "Клики проходят сквозь остров. Запись: Ctrl+Alt+Space"
                                            color: Theme.muted
                                            font.pixelSize: Theme.fsSmall
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: overlayBox.implicitHeight + 2 * Theme.padCard
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: overlayBox
                                        anchors.fill: parent
                                        anchors.margins: Theme.padCard
                                        spacing: Theme.gapSm
                                        Label { text: "Субтитры на экране"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        Text { Layout.fillWidth: true; text: "Отдельное окно для зала: крупный текст, без кнопок, клики проходят сквозь."; color: Theme.muted; font.pixelSize: Theme.fsLabel; wrapMode: Text.Wrap }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ToggleSwitch { text: "Показать на экране"; checked: Boolean(bridge.settings.caption_overlay); onToggled: bridge.setSetting("caption_overlay", checked) }
                                            Item { Layout.fillWidth: true }
                                            PillButton { text: "Меньше"; primary: bridge.settings.caption_size === "sm"; onClicked: bridge.setSetting("caption_size", "sm") }
                                            PillButton { text: "Средние"; primary: bridge.settings.caption_size === "md"; onClicked: bridge.setSetting("caption_size", "md") }
                                            PillButton { text: "Крупные"; primary: bridge.settings.caption_size === "lg"; onClicked: bridge.setSetting("caption_size", "lg") }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            PillButton { text: "Обычный контраст"; primary: String(bridge.settings.caption_contrast) !== "high"; onClicked: bridge.setSetting("caption_contrast", "normal") }
                                            PillButton { text: "Высокий контраст"; primary: String(bridge.settings.caption_contrast) === "high"; onClicked: bridge.setSetting("caption_contrast", "high") }
                                            Item { Layout.fillWidth: true }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            PillButton { text: "Сверху"; primary: String(bridge.settings.caption_position) === "top"; onClicked: bridge.setSetting("caption_position", "top") }
                                            PillButton { text: "Снизу"; primary: String(bridge.settings.caption_position) !== "top" && String(bridge.settings.caption_position) !== "floating"; onClicked: bridge.setSetting("caption_position", "bottom") }
                                            PillButton { text: "Плавающие"; primary: String(bridge.settings.caption_position) === "floating"; onClicked: bridge.setSetting("caption_position", "floating") }
                                            Item { Layout.fillWidth: true }
                                            PillButton {
                                                compact: true
                                                visible: String(bridge.settings.caption_position) === "floating"
                                                text: "Вернуть вниз"
                                                onClicked: bridge.resetCaptionPosition()
                                                ToolTip.visible: hovered
                                                ToolTip.text: "Сбросить сохранённое положение плавающих субтитров"
                                            }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ToggleSwitch { text: "Скрывать в паузе"; checked: Boolean(bridge.settings.caption_autohide); onToggled: bridge.setSetting("caption_autohide", checked) }
                                            Item { Layout.fillWidth: true }
                                            ToggleSwitch { text: "Закрепить (клики сквозь)"; checked: Boolean(bridge.settings.caption_locked); onToggled: bridge.setSetting("caption_locked", checked) }
                                        }
                                        ToggleSwitch {
                                            text: "Без анимации слов"
                                            checked: Boolean(bridge.settings.reduce_motion)
                                            onToggled: bridge.setSetting("reduce_motion", checked)
                                        }
                                        Label {
                                            text: Boolean(bridge.settings.caption_locked)
                                                  ? "Субтитры не перехватывают мышь. Снимите закрепление, чтобы перетащить окно зала."
                                                  : "Перетащите окно субтитров. Положение сохранится как плавающее."
                                            color: Theme.muted
                                            font.pixelSize: Theme.fsSmall
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Repeater {
                                                model: Qt.application.screens
                                                PillButton {
                                                    required property int index
                                                    text: index === 0 ? "Экран 1" : "Экран " + (index + 1)
                                                    primary: Number(bridge.settings.caption_screen) === index || (Number(bridge.settings.caption_screen) < 0 && index === 0)
                                                    onClicked: bridge.setSetting("caption_screen", index)
                                                }
                                            }
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: liveBox.implicitHeight + 2 * Theme.padCard
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: liveBox
                                        anchors.fill: parent
                                        anchors.margins: Theme.padCard
                                        spacing: Theme.gapSm
                                        Label { text: "Live-окно и текст"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        Text { Layout.fillWidth: true; text: "При Live остров превращается в одно окно. Размер - пресетами или руками за угол, замок фиксирует положение и размер."; color: Theme.muted; wrapMode: Text.Wrap; font.pixelSize: Theme.fsSmall }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ToggleSwitch { text: "Авто-окно при старте Live"; checked: Boolean(bridge.settings.live_auto_window); onToggled: bridge.setSetting("live_auto_window", checked) }
                                            Item { Layout.fillWidth: true }
                                            ToggleSwitch { text: "Замок"; checked: Boolean(bridge.settings.live_locked); onToggled: bridge.setSetting("live_locked", checked) }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: "Размер пресет"; color: Theme.muted; font.pixelSize: Theme.fsLabel }
                                            PillButton { text: "Малый"; primary: String(bridge.settings.live_size) === "small"; onClicked: bridge.setSetting("live_size", "small") }
                                            PillButton { text: "Средний"; primary: String(bridge.settings.live_size) === "standard"; onClicked: bridge.setSetting("live_size", "standard") }
                                            PillButton { text: "Широкий"; primary: String(bridge.settings.live_size) === "wide"; onClicked: bridge.setSetting("live_size", "wide") }
                                            PillButton { text: "Высокий"; primary: String(bridge.settings.live_size) === "tall"; onClicked: bridge.setSetting("live_size", "tall") }
                                            Item { Layout.fillWidth: true }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ToggleSwitch { text: "Таймкод у каждой фразы"; checked: Boolean(bridge.settings.live_show_times); onToggled: bridge.setSetting("live_show_times", checked) }
                                            Item { Layout.fillWidth: true }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ToggleSwitch {
                                                text: "Экономный режим финалов (greedy)"
                                                checked: Boolean(bridge.settings.live_greedy_finals)
                                                onToggled: bridge.setSetting("live_greedy_finals", checked)
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignVCenter
                                                text: "для слабых машин: финалы лучом 1"
                                                color: Theme.faint
                                                font.pixelSize: Theme.fsMicro
                                            }
                                            Item { Layout.fillWidth: true }
                                        }
                                        Label {
                                            text: "Комбинация выхода: закрывает программу целиком из консоли и по горячей клавише."
                                            color: Theme.faint
                                            font.pixelSize: Theme.fsMicro
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            TextField {
                                                id: quitInput
                                                Layout.fillWidth: true
                                                text: String(bridge.settings.quit_hotkey || "Ctrl+Alt+X")
                                                placeholderText: "Ctrl+Alt+A"
                                                selectByMouse: true
                                                color: Theme.text
                                                placeholderTextColor: Theme.faint
                                                font.family: Theme.fontFamily
                                                inputMethodHints: Qt.ImhNoPredictiveText
                                                background: Rectangle { radius: 10; color: Theme.fill; border.width: 1; border.color: Theme.hairline }
                                            }
                                            PillButton {
                                                compact: true
                                                text: "Применить"
                                                primary: true
                                                onClicked: {
                                                    bridge.setQuitHotkey(quitInput.text)
                                                    // После валидации показываем каноничный вид.
                                                    quitInput.text = String(bridge.settings.quit_hotkey)
                                                }
                                            }
                                        }
                                        Row {
                                            Layout.fillWidth: true
                                            spacing: 6
                                            Repeater {
                                                model: ["Ctrl+Alt+X", "Ctrl+Alt+C", "Ctrl+Alt+Q"]
                                                PillButton {
                                                    required property string modelData
                                                    text: modelData
                                                    primary: String(bridge.settings.quit_hotkey) === modelData
                                                    onClicked: { bridge.setSetting("quit_hotkey", modelData); quitInput.text = modelData }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    TranscriptView { Layout.fillWidth: true; Layout.fillHeight: true }
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
