import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtMultimedia
import "Theme.js" as Theme

ApplicationWindow {
    id: root
    property string shellMode: "island"
    property bool logsOpen: false
    property bool islandModesOpen: false
    property bool morphGeo: false
    property bool dragging: false
    property bool quietHeld: false
    property real islandCenterX: -1
    property real islandTopY: 32
    property var pageKeys: ["live", "dictation", "media", "models", "history", "settings"]
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
    width: shellMode === "app" ? 1220 : shellMode === "theater" ? 740 : islandW
    height: shellMode === "app" ? 790 : shellMode === "theater" ? 420 : islandH
    minimumWidth: shellMode === "app" ? 1000 : 180
    minimumHeight: shellMode === "app" ? 660 : 40
    visible: true
    color: shellMode === "app" ? Theme.bg : "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
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

    // Ширина едет с лёгким перелётом - это и читается как morph острова.
    // Высота идёт без отката, иначе содержимое подрезается на возврате.
    Behavior on width {
        enabled: root.morphGeo && !root.dragging
        NumberAnimation {
            duration: Theme.morphMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeSpring
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

    function openApp(page) {
        if (page)
            bridge.selectPage(page)
        root.morphGeo = false
        root.islandModesOpen = false
        bridge.applyIslandClickThrough(false)
        root.shellMode = "app"
        root.x = Math.max(40, Math.round((Screen.width - root.width) / 2))
        root.y = Math.max(40, Math.round((Screen.height - root.height) / 2))
    }
    function openTheater() {
        bridge.selectPage("live")
        root.islandModesOpen = false
        root.morphGeo = true
        bridge.applyIslandClickThrough(false)
        root.shellMode = "theater"
    }
    function collapse() {
        root.morphGeo = true
        root.islandModesOpen = false
        root.logsOpen = false
        root.shellMode = "island"
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
        embedded: false
        onRequestIsland: root.collapse()
        onRequestApp: root.openApp("live")
    }

    Rectangle {
        visible: root.shellMode === "app"
        anchors.fill: parent
        color: Theme.bg
        radius: 12
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
                            radius: 12
                            color: Theme.text
                            Text {
                                anchors.centerIn: parent
                                text: ".а"
                                color: Theme.bg
                                font.pixelSize: 13
                                font.weight: Font.Bold
                            }
                        }
                        ColumnLayout {
                            spacing: 0
                            Label { text: ".аудио"; color: Theme.text; font.pixelSize: 18; font.weight: Font.DemiBold }
                            Label { text: "локальная речь"; color: Theme.muted; font.pixelSize: 10 }
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
                        Layout.preferredHeight: 6 * rowH + 5 * rowGap

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
                                    { key: "settings", icon: "settings", title: "Среда", detail: "Устройства" }
                                ]
                                delegate: Button {
                                    id: nav
                                    required property var modelData
                                    readonly property bool selected: bridge.page === nav.modelData.key
                                    width: navBox.width
                                    height: navBox.rowH
                                    hoverEnabled: true
                                    onClicked: bridge.selectPage(nav.modelData.key)
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
                                        color: !nav.selected && nav.hovered ? "#0bffffff" : "transparent"
                                        Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                                    }
                                }
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Label { text: ".ядро"; color: Theme.muted; font.pixelSize: 10; opacity: 0.55 }
                    Text {
                        Layout.fillWidth: true
                        text: bridge.hotkeysAvailable
                              ? bridge.settings.dictate_hotkey + " диктовка\n" + bridge.settings.island_hotkey + " остров\n" + bridge.settings.paste_last_hotkey + " вставить"
                              : "Горячие клавиши недоступны"
                        color: Theme.muted
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 24
                spacing: 16
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        spacing: 2
                        opacity: root.pageFade
                        Label {
                            text: ({
                                live: "Живые субтитры",
                                dictation: "Диктовка",
                                media: "Караоке-студия",
                                monitor: "Мониторинг эфиров",
                                models: "Модели Whisper",
                                history: "История",
                                settings: "Настройки"
                            })[bridge.page]
                            color: Theme.text
                            font.pixelSize: 26
                            font.weight: Font.DemiBold
                        }
                        Label { text: bridge.status; color: Theme.muted; font.pixelSize: 12 }
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        visible: bridge.busy || bridge.recording
                        text: bridge.elapsed
                        color: Theme.muted
                        font.family: Theme.monoFamily
                        font.pixelSize: 12
                    }
                    IconButton { iconName: "logs"; onClicked: root.logsOpen = !root.logsOpen; ToolTip.visible: hovered; ToolTip.text: "Журнал" }
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
                        spacing: 8
                        Icon { name: "warning"; width: 16; height: 16 }
                        Text {
                            id: noticeText
                            Layout.fillWidth: true
                            text: bridge.notice
                            color: Theme.text
                            font.pixelSize: 12
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
                                    spacing: 8
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
                                            spacing: 8
                                            visible: opacity > 0.01
                                            opacity: bridge.caption.length ? 0 : 1
                                            Behavior on opacity { NumberAnimation { duration: Theme.contentMs } }
                                            Label {
                                                Layout.fillWidth: true
                                                text: bridge.recording ? "Говорите естественно" : "Скажите мысль, текст попадёт в буфер"
                                                color: Theme.text
                                                font.pixelSize: 24
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
                                            pixelSize: 24
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
                            spacing: 16
                            ColumnLayout {
                                // Доля ширины задаётся растяжением, а не через
                                // parent.width: прежняя привязка зацикливалась и
                                // выдавливала редактор за край окна.
                                Layout.fillWidth: true
                                Layout.horizontalStretchFactor: 53
                                Layout.fillHeight: true
                                spacing: 12
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
                                    KaraokePreview { visible: bridge.mediaUrl.length > 0; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 18; height: 126; player: mediaPlayer; segments: bridge.segments }
                                    ColumnLayout {
                                        anchors.centerIn: parent
                                        width: Math.min(parent.width - 64, 330)
                                        visible: !bridge.mediaUrl
                                        spacing: 10
                                        Icon { Layout.alignment: Qt.AlignHCenter; name: "media"; width: 28; height: 28 }
                                        Label { Layout.fillWidth: true; text: "Аудио в караоке"; horizontalAlignment: Text.AlignHCenter; color: Theme.text; font.pixelSize: 21; font.weight: Font.DemiBold }
                                        Text { Layout.fillWidth: true; text: "Откройте аудио или видео, получите текст по словам и доведите таймкоды."; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 13 }
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
                                    PillButton { text: "ASS"; enabled: bridge.segments.length > 0; onClicked: bridge.exportKaraokeFile() }
                                    PillButton { text: bridge.rendering ? "Рендер…" : "MP4"; primary: true; enabled: bridge.segments.length > 0 && !bridge.rendering; onClicked: bridge.exportKaraokeVideo() }
                                }
                            }
                            TranscriptEditor { Layout.fillWidth: true; Layout.horizontalStretchFactor: 47; Layout.fillHeight: true; player: mediaPlayer; editable: true }
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
                            Repeater {
                                model: ["tiny", "base", "small", "medium", "large-v3", "turbo"]
                                delegate: Rectangle {
                                    id: modelCard
                                    required property string modelData
                                    required property int index
                                    Layout.fillWidth: true
                                    implicitHeight: 82
                                    radius: Theme.radiusLg
                                    color: bridge.settings.model === modelData ? Theme.fill : Theme.surface
                                    border.width: 1
                                    border.color: bridge.settings.model === modelData ? Theme.borderHi : Theme.border
                                    Behavior on color { ColorAnimation { duration: Theme.baseMs } }
                                    Behavior on border.color { ColorAnimation { duration: Theme.baseMs } }
                                    readonly property string cacheText: {
                                        var lib = bridge.modelLibrary
                                        for (var i = 0; i < lib.length; i++) {
                                            if (lib[i].model === modelCard.modelData)
                                                return lib[i].message
                                        }
                                        return "Ещё не скачана · будет загружена при подготовке"
                                    }
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 16
                                        spacing: 12
                                        Icon { name: "models"; width: 20; height: 20 }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 2
                                            Label { Layout.fillWidth: true; text: modelCard.modelData; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                            // Без fillWidth подпись задавала минимальную
                                            // ширину колонки, и кнопки в карточках
                                            // моделей стояли на разной высоте строки.
                                            Label {
                                                Layout.fillWidth: true
                                                text: bridge.modelState.model === modelCard.modelData && bridge.modelState.message
                                                      ? bridge.modelState.message
                                                      : modelCard.cacheText
                                                color: Theme.muted
                                                font.pixelSize: Theme.fsSmall
                                                elide: Text.ElideRight
                                            }
                                        }
                                        PillButton { text: "Выбрать"; enabled: !bridge.busy; onClicked: bridge.setSetting("model", modelCard.modelData) }
                                        PillButton {
                                            visible: bridge.modelPreparing && bridge.modelState.model === modelCard.modelData
                                            text: "Отмена"
                                            onClicked: bridge.cancelModelPrepare()
                                        }
                                        PillButton {
                                            visible: !(bridge.modelPreparing && bridge.modelState.model === modelCard.modelData)
                                            text: "Загрузить"
                                            primary: true
                                            enabled: !bridge.busy && !bridge.modelPreparing
                                            onClicked: { bridge.setSetting("model", modelCard.modelData); bridge.prepareSelectedModel() }
                                        }
                                    }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: rulesBox.implicitHeight + 36
                                radius: Theme.radiusLg
                                color: Theme.surface
                                border.width: 1
                                border.color: Theme.border
                                ColumnLayout {
                                    id: rulesBox
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 8
                                    Label { text: "Словарь и snippets"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                    Text { Layout.fillWidth: true; text: "Термины помогают Whisper, а замены применяются только к финальному тексту диктовки. Всё остаётся на этом устройстве."; color: Theme.muted; font.pixelSize: Theme.fsSmall; wrapMode: Text.Wrap }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        TextField { id: termInput; Layout.fillWidth: true; placeholderText: "Термин"; color: Theme.text; placeholderTextColor: Theme.muted; background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                                        TextField { id: mistakeInput; Layout.preferredWidth: 180; placeholderText: "Вариант ошибки"; color: Theme.text; placeholderTextColor: Theme.muted; background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                                        PillButton { text: "+"; onClicked: { bridge.addDictionaryEntry(termInput.text, mistakeInput.text); termInput.clear(); mistakeInput.clear() } }
                                    }
                                    ListView { Layout.fillWidth: true; Layout.preferredHeight: Math.min(70, contentHeight); model: bridge.dictionary; clip: true; delegate: RowLayout { required property var modelData; required property int index; width: ListView.view.width; Text { Layout.fillWidth: true; text: modelData.term + (modelData.misheard ? " ← " + modelData.misheard : ""); color: Theme.muted; elide: Text.ElideRight; font.pixelSize: Theme.fsSmall } PillButton { text: "×"; onClicked: bridge.removeDictionaryEntry(index) } } }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        TextField { id: snippetInput; Layout.preferredWidth: 180; placeholderText: "Фраза"; color: Theme.text; placeholderTextColor: Theme.muted; background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                                        TextField { id: expansionInput; Layout.fillWidth: true; placeholderText: "Вставляемый текст"; color: Theme.text; placeholderTextColor: Theme.muted; background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                                        PillButton { text: "+"; onClicked: { bridge.addSnippet(snippetInput.text, expansionInput.text); snippetInput.clear(); expansionInput.clear() } }
                                    }
                                }
                            }
                            }
                        }
                    }
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 12
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

                                Label {
                                    anchors.centerIn: parent
                                    width: Math.min(parent.width - 60, 360)
                                    visible: bridge.history.length === 0
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.Wrap
                                    text: "Сессии появятся здесь после первой диктовки, Live или разбора файла."
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsBody
                                }

                                ListView {
                                    anchors.fill: parent
                                    model: bridge.history
                                    spacing: 8
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
                                spacing: 12
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: languageBox.implicitHeight + 36
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: languageBox
                                        anchors.fill: parent
                                        anchors.margins: 18
                                        spacing: 8
                                        Label { text: "Язык и вывод"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text { Layout.fillWidth: true; text: "Распознавание ориентировано на русский язык."; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
                                            PillButton { text: "Русский"; primary: bridge.settings.language === "ru" && bridge.settings.task === "transcribe"; onClicked: { bridge.setSetting("language", "ru"); bridge.setSetting("task", "transcribe") } }
                                            PillButton { text: "English subtitles"; primary: bridge.settings.task === "translate"; onClicked: bridge.setSetting("task", "translate") }
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: deviceBox.implicitHeight + 36
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: deviceBox
                                        anchors.fill: parent
                                        anchors.margins: 18
                                        spacing: 10
                                        Label { text: "Источник Live и устройства"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        Text { Layout.fillWidth: true; text: "Диктовка всегда с микрофона. Live: микрофон, звук компьютера или Авто - оба сразу. На острове источник переключается кнопкой."; color: Theme.muted; font.pixelSize: 11; wrapMode: Text.Wrap }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: "Источник Live"; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
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
                                        Label { text: bridge.deviceTest.message || "Проверка не сохраняет запись."; color: Theme.muted; font.pixelSize: 11 }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: islandBox.implicitHeight + 36
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: islandBox
                                        anchors.fill: parent
                                        anchors.margins: 18
                                        spacing: 8
                                        Label { text: "Остров"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: "Диктовка"; color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 90 }
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
                                            Label { text: "Остров"; color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 90 }
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
                                            font.pixelSize: 11
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: "Непрозрачность"; color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 118 }
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
                                            font.pixelSize: 11
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: overlayBox.implicitHeight + 36
                                    radius: Theme.radiusLg
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        id: overlayBox
                                        anchors.fill: parent
                                        anchors.margins: 18
                                        spacing: 8
                                        Label { text: "Субтитры на экране"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                        Text { Layout.fillWidth: true; text: "Отдельное окно для зала: крупный текст, без кнопок, клики проходят сквозь."; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
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
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ToggleSwitch { text: "Скрывать в паузе"; checked: Boolean(bridge.settings.caption_autohide); onToggled: bridge.setSetting("caption_autohide", checked) }
                                            Item { Layout.fillWidth: true }
                                            ToggleSwitch { text: "Закрепить (клики сквозь)"; checked: Boolean(bridge.settings.caption_locked); onToggled: bridge.setSetting("caption_locked", checked) }
                                        }
                                        Label {
                                            text: Boolean(bridge.settings.caption_locked)
                                                  ? "Субтитры не перехватывают мышь. Снимите закрепление, чтобы перетащить окно зала."
                                                  : "Перетащите окно субтитров. Положение сохранится как плавающее."
                                            color: Theme.muted
                                            font.pixelSize: 11
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
                            }
                        }
                    }
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 12
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 228
                                radius: Theme.radiusLg
                                color: Theme.surface
                                border.width: 1
                                border.color: Theme.border
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 9
                                    Label { text: "Прямые источники"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                                    Text { Layout.fillWidth: true; text: "Одна HTTP(S) аудио- или HLS-ссылка на строку. Формат: Название | URL. Максимум четыре источника."; color: Theme.muted; wrapMode: Text.Wrap; font.pixelSize: 12 }
                                    TextArea { id: monitorChannels; Layout.fillWidth: true; Layout.fillHeight: true; text: bridge.settings.channels; placeholderText: "Радио | https://example.org/live.m3u8"; color: Theme.text; placeholderTextColor: Theme.muted; onActiveFocusChanged: if (!activeFocus) bridge.setSetting("channels", text); background: Rectangle { radius: 12; color: Theme.fill; border.width: 1; border.color: Theme.border } }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 94
                                radius: Theme.radiusLg
                                color: Theme.surface
                                border.width: 1
                                border.color: Theme.border
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    TextField { Layout.fillWidth: true; text: bridge.settings.keywords; placeholderText: "Ключевые слова и фразы через запятую"; color: Theme.text; placeholderTextColor: Theme.muted; onEditingFinished: bridge.setSetting("keywords", text); background: Rectangle { radius: 12; color: Theme.fill; border.width: 1; border.color: Theme.border } }
                                    PillButton { text: bridge.recording ? "Стоп" : "Начать"; primary: true; onClicked: bridge.toggleRecording() }
                                }
                            }
                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                model: bridge.hits
                                clip: true
                                spacing: 8
                                delegate: Rectangle {
                                    required property var modelData
                                    width: ListView.view.width
                                    implicitHeight: hitText.implicitHeight + 22
                                    radius: 14
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    Text { id: hitText; anchors.fill: parent; anchors.margins: 11; text: modelData.source + " · " + modelData.matches + "\n" + modelData.text; color: Theme.text; wrapMode: Text.Wrap; font.pixelSize: 12 }
                                }
                            }
                        }
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
                spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Журнал работы"; color: Theme.text; font.pixelSize: 18; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    IconButton { iconName: "close"; onClicked: root.logsOpen = false }
                }
                Label { text: "События приложения и распознавания"; color: Theme.muted; font.pixelSize: 11 }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: bridge.logs
                    spacing: 8
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
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }

    CaptionOverlay { id: captionOverlay }
}
