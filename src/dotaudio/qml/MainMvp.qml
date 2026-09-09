import QtQml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtMultimedia
import "Theme.js" as Theme

ApplicationWindow {
    id: root

    // Старт - полное окно с навигацией. Остров и Live-сцена открываются
    // по запросу (свёртка / старт записи), а не вместо главной страницы.
    // В режиме app - обычное окно Windows с системной рамкой и кнопками.
    readonly property string pageTitle: ({
        live: "Живые субтитры",
        dictation: "Диктовка",
        // Караоке UI скрыт 2026-09-09 — см. docs/HANDOFF.md «Караоке UI скрыт».
        // media: "Караоке-студия",
        transcript: "Транскрибация записи",
        monitor: "Мониторинг эфиров",
        models: "Модели Whisper",
        history: "История",
        settings: "Настройки",
        assistant: "Ассистент"
    })[bridge.page] || "DotAudio"
    title: shellMode === "app" ? ("DotAudio — " + pageTitle) : "DotAudio"
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
    // Без "media": раздел Караоке временно скрыт (код MediaPage.qml сохранён).
    // Включение: раскомментировать "media" ниже, пункт в nav и Loader MediaPage;
    // плюс KARAOKE_PAGE_ENABLED = True в controller.py. См. docs/HANDOFF.md.
    property var pageKeys: [
        "live", "dictation", "transcript", /* "media", */ "assistant",
        "history", "models", "settings"
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
    // Размеры оболочек запоминаются отдельно. Пресет Live только задаёт
    // старт; дальше пользователь тянет края без борьбы с Binding.
    property int appW: 1220
    property int appH: 790
    property int theaterW: 760
    property int theaterH: 440
    property real theaterX: -1
    property real theaterY: -1
    // Максимум фазы острова: HWND этого размера не прыгает при смене фазы,
    // морфит только MiniIsland внутри. Клики вне хрома режет setWindowMask.
    readonly property int islandCanvasW: 552
    readonly property int islandCanvasH: 108
    width: shellMode === "app" ? appW
           : shellMode === "theater" ? theaterW
           : islandCanvasW
    height: shellMode === "app" ? appH
            : shellMode === "theater" ? theaterH
            : islandCanvasH
    // Поверх всех окон живут только остров и сцена Live: они должны быть
    // видны во время другой работы. Полное окно - обычное окно, его может
    // перекрыть любое другое, включая браузер с черновиком статьи.
    property bool stayOnTop: false
    // App - обычное окно Windows (рамка, resize, snap, Alt+Space).
    // Остров и Live-сцена остаются безрамными и поверх других окон.
    flags: Qt.Window
           | (shellMode !== "app" ? Qt.FramelessWindowHint : 0)
           | (stayOnTop ? Qt.WindowStaysOnTopHint : 0)
    // В app разрешаем тянуть края; остров/сцена по-прежнему задают размер сами.
    minimumWidth: shellMode === "app" ? 960 : 180
    minimumHeight: shellMode === "app" ? 640 : 40
    visible: true
    // Остров: непрозрачный холст того же тона, что хром. «transparent» на
    // Windows часто даёт чёрный прямоугольник без текста, пока маска/fade
    // не догонят HWND после recreate флагов.
    color: shellMode === "app" ? Theme.bg
           : shellMode === "island" ? Theme.surface
           : "transparent"
    // Прозрачность острова — на хроме, не на HWND: иначе DWM дёргает при drag.
    opacity: 1
    font.family: Theme.fontFamily
    font.hintingPreference: Font.PreferDefaultHinting

    readonly property string islandPhase: {
        if (islandModesOpen && !bridge.recording && !bridge.busy)
            return "modePick"
        // После удачной диктовки notice про буфер не должен прятать результат.
        if (bridge.notice.length > 0 && !bridge.recording && !bridge.busy
                && !(bridge.page === "dictation" && bridge.lastTranscript.length))
            return "error"
        if (bridge.liveActive && bridge.displayCaption.length)
            return "caption"
        if (bridge.liveActive && bridge.livePhase === "quiet")
            return "quiet"
        if (bridge.liveActive && (bridge.livePhase === "process" || bridge.livePhase === "decoding" || bridge.livePhase === "stopping"))
            return "process"
        if (bridge.liveActive)
            return "listen"
        if (bridge.recording && (bridge.text.length || bridge.partialCaption.length || bridge.caption.length))
            return "caption"
        if (bridge.recording && quietHeld && bridge.inputState === "Нет входного сигнала")
            return "quiet"
        if (bridge.recording)
            return "listen"
        if (!bridge.recording && bridge.busy && (bridge.text.length || bridge.partialCaption.length || bridge.caption.length))
            return "caption"
        if (!bridge.recording && bridge.busy)
            return "process"
        if (bridge.page === "dictation" && (bridge.lastTranscript.length || bridge.caption.length || bridge.text.length) && !bridge.busy)
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

    // Геометрию HWND больше не анимируем: каждый кадр Behavior + Binding по
    // центру давал два SetWindowPos и дёргал остров. Размер фазы меняется
    // одним шагом, а плавность остаётся в кроссфейде содержимого MiniIsland.
    onWidthChanged: {
        if (root.visibility === Window.Maximized)
            return
        var w = Math.round(root.width)
        if (root.shellMode === "app" && w !== root.appW)
            root.appW = w
        else if (root.shellMode === "theater" && w !== root.theaterW)
            root.theaterW = w
    }
    onHeightChanged: {
        if (root.visibility === Window.Maximized)
            return
        var h = Math.round(root.height)
        if (root.shellMode === "app" && h !== root.appH)
            root.appH = h
        else if (root.shellMode === "theater" && h !== root.theaterH)
            root.theaterH = h
    }

    // Якорь только у острова и только вне drag — иначе Binding
    // перебивает startSystemMove и окно дёргается назад к центру.
    Binding on x {
        when: !root.dragging && root.shellMode === "island" && root.islandCenterX >= 0
        value: Math.round(root.islandCenterX - root.islandCanvasW / 2)
    }
    Binding on y {
        when: !root.dragging && root.shellMode === "island"
        value: Math.round(root.islandTopY)
    }

    function beginIslandDrag() {
        if (root.shellMode !== "island" || root.dragging)
            return
        // Маску снять до native move: иначе hit-region отстаёт от HWND.
        bridge.clearWindowMask()
        root.dragging = true
        root.startSystemMove()
    }

    function endIslandDrag() {
        if (!root.dragging || root.shellMode !== "island")
            return
        var winX = Math.round(root.x)
        var winY = Math.round(root.y)
        root.islandCenterX = winX + root.islandCanvasW / 2
        root.islandTopY = winY
        root.dragging = false
        bridge.saveIslandPosition(winX, winY)
        root.refreshIslandMask()
    }

    function refreshIslandMask() {
        if (root.shellMode !== "island") {
            bridge.clearWindowMask()
            return
        }
        // Во время native drag маску не трогаем — SetWindowMask даёт хитч.
        if (root.dragging)
            return
        var mx = Math.round((root.islandCanvasW - root.islandW) / 2)
        var my = Math.round((root.islandCanvasH - root.islandH) / 2)
        bridge.setWindowMask(mx, my, root.islandW, root.islandH, root.islandR)
    }

    onIslandWChanged: if (root.shellMode === "island") root.refreshIslandMask()
    onIslandHChanged: if (root.shellMode === "island") root.refreshIslandMask()
    onIslandRChanged: if (root.shellMode === "island") root.refreshIslandMask()
    onShellModeChanged: {
        if (root.shellMode === "island")
            Qt.callLater(root.refreshIslandMask)
        else
            bridge.clearWindowMask()
    }

    // Смена оболочки. Размер HWND меняется сразу; плавность даёт кроссфейд
    // содержимого (shellFade / shellRise), а не морф геометрии окна.
    property real shellFade: 1
    property real shellRise: 0

    function enterShell(mode, morph) {
        root.morphGeo = false
        root.islandModesOpen = false
        root.dragging = false
        // Смена «поверх всех» или рамки требует пересоздания HWND на Windows.
        var wantTop = mode !== "app"
        var wantFramed = mode === "app"
        var wasFramed = root.shellMode === "app"
        var sameShell = root.shellMode === mode
        var needFlags = root.stayOnTop !== wantTop || wantFramed !== wasFramed
        var wasVisible = root.visible
        if (needFlags && wasVisible)
            root.hide()
        root.stayOnTop = wantTop
        root.shellMode = mode
        if (needFlags && wasVisible)
            root.show()
        if (mode === "app")
            Qt.callLater(function () { bridge.refreshWindowChrome() })
        if (mode === "island") {
            // После hide/show анимация shellFade часто обрывается: хром остаётся
            // с opacity 0, а HWND - тёмный прямоугольник без подписей и кнопок.
            root.shellFade = 1
            root.shellRise = 0
            root.refreshIslandMask()
            Qt.callLater(root.refreshIslandMask)
        } else {
            bridge.clearWindowMask()
            if (!sameShell) {
                root.shellFade = 0
                root.shellRise = 14
                shellIn.restart()
            } else {
                root.shellFade = 1
                root.shellRise = 0
            }
        }
    }

    function openApp(page) {
        if (page)
            bridge.selectPage(page)
        bridge.applyIslandClickThrough(false)
        root.enterShell("app", false)
        root.x = Math.max(40, Math.round((Screen.width - root.appW) / 2))
        root.y = Math.max(40, Math.round((Screen.height - root.appH) / 2))
    }
    function openTheater() {
        bridge.selectPage("live")
        bridge.applyIslandClickThrough(false)
        // Единое Live-окно: отдельное окно зала не дублирует текст поверх.
        bridge.setSetting("caption_overlay", false)
        // Пресет размера подхватываем только если сцена ещё не тянулась.
        var preset = root.theaterSizes
        if (root.theaterX < 0) {
            root.theaterW = preset[0]
            root.theaterH = preset[1]
        }
        root.enterShell("theater", false)
        if (root.theaterX >= 0) {
            root.x = root.theaterX
            root.y = root.theaterY
        } else {
            root.x = Math.max(40, Math.round((Screen.width - root.theaterW) / 2))
            root.y = Math.max(40, Math.round((Screen.height - root.theaterH) / 2))
        }
    }
    function collapse() {
        root.logsOpen = false
        if (root.shellMode === "theater") {
            root.theaterX = root.x
            root.theaterY = root.y
            root.theaterW = Math.round(root.width)
            root.theaterH = Math.round(root.height)
        }
        if (root.visibility === Window.Maximized)
            root.showNormal()
        root.enterShell("island", false)
        // Во время диктовки остров обязан принимать клики (стоп / отмена).
        if (bridge.page === "dictation" && (bridge.recording || bridge.busy))
            bridge.applyIslandClickThrough(false)
        else
            bridge.applyIslandClickThrough(Boolean(bridge.settings.island_click_through))
    }

    Component.onCompleted: {
        root.pageIndex = root.targetPageIndex
        // Якорь острова храним всегда: при свёртке окно вернётся сюда.
        if (Number(bridge.settings.island_x) >= 0) {
            root.islandCenterX = Number(bridge.settings.island_x) + root.islandCanvasW / 2
            root.islandTopY = Number(bridge.settings.island_y)
        } else {
            root.islandCenterX = Screen.width / 2
            root.islandTopY = 32
        }
        var preset = root.theaterSizes
        root.theaterW = preset[0]
        root.theaterH = preset[1]
        if (root.shellMode === "app") {
            // Главное окно по центру экрана, с боковой навигацией и Live.
            bridge.selectPage(bridge.page && bridge.page.length ? bridge.page : "live")
            bridge.applyIslandClickThrough(false)
            root.x = Math.max(40, Math.round((Screen.width - root.appW) / 2))
            root.y = Math.max(40, Math.round((Screen.height - root.appH) / 2))
        } else {
            root.x = Math.round(root.islandCenterX - root.islandCanvasW / 2)
            root.y = root.islandTopY
            if (Boolean(bridge.settings.island_click_through))
                bridge.applyIslandClickThrough(true)
            Qt.callLater(root.refreshIslandMask)
        }
    }

    Connections {
        target: bridge
        function onIslandRequested() {
            dictationIsland.visible = false
            root.collapse()
            root.show()
            root.raise()
            root.shellFade = 1
            root.shellRise = 0
            bridge.applyIslandClickThrough(false)
            root.refreshIslandMask()
            Qt.callLater(root.refreshIslandMask)
        }
        function onDictationIslandRequested() {
            root.showDictationIsland()
        }
        function onDictationIslandDismiss() {
            dictationIsland.visible = false
            dictationIsland.dragging = false
        }
        function onCaptureStarted(_sid, _when) {
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
            if (root.shellMode === "island" && bridge.page === "dictation"
                    && (bridge.recording || bridge.busy))
                bridge.applyIslandClickThrough(false)
        }
    }

    function showDictationIsland() {
        if (!dictationIsland.userPlaced) {
            if (root.islandCenterX >= 0) {
                dictationIsland.x = Math.round(root.islandCenterX - root.islandW / 2)
                dictationIsland.y = Math.round(root.islandTopY)
            } else {
                dictationIsland.x = Math.round((Screen.width - root.islandW) / 2)
                dictationIsland.y = 32
            }
        }
        dictationIsland.visible = true
        dictationIsland.show()
        dictationIsland.raise()
    }

    function saveDictationIslandPos() {
        dictationIsland.userPlaced = true
        root.islandCenterX = dictationIsland.x + dictationIsland.width / 2
        root.islandTopY = dictationIsland.y
        bridge.saveIslandPosition(Math.round(dictationIsland.x), Math.round(dictationIsland.y))
    }

    // Остров диктовки. Не морфит главное окно - иначе Windows recreate HWND
    // оставляет чёрный квадрат без текста и ломает повтор hotkey.
    Window {
        id: dictationIsland
        title: "DotAudio · диктовка"
        visible: false
        width: root.islandW
        height: root.islandH
        color: Theme.surface
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        property bool userPlaced: false
        property bool dragging: false

        MiniIsland {
            id: dictationChrome
            anchors.fill: parent
            phase: root.islandPhase
            radius: root.islandR
            clickThrough: false
            shellRise: 0
            onRequestApp: {
                dictationIsland.visible = false
                root.openApp(page)
            }
            onRequestTheater: {
                dictationIsland.visible = false
                root.openTheater()
            }
            onRequestModePick: { }
            onCloseModes: { }
            onDragStarted: function (_screenX, _screenY) {
                // Как у CaptionOverlay: DWM ведёт Tool-окно. Раньше
                // onWidthChanged сбрасывал X и казалось, что drag «не работает».
                dictationIsland.dragging = true
                dictationIsland.userPlaced = true
                dictationIsland.startSystemMove()
            }
        }

        // Конец жеста - по отпусканию ЛКМ (MouseArea уже отдал захват системе).
        Timer {
            interval: 16
            repeat: true
            running: dictationIsland.dragging
            onTriggered: {
                if (bridge.primaryButtonDown())
                    return
                dictationIsland.dragging = false
                root.saveDictationIslandPos()
            }
        }

        onWidthChanged: {
            // Пока пользователь не двигал остров - держим по центру при морфе.
            if (!visible || dragging || userPlaced)
                return
            var cx = root.islandCenterX >= 0 ? root.islandCenterX : Screen.width / 2
            x = Math.round(cx - width / 2)
        }
    }

    Timer {
        id: quietTimer
        interval: 1200
        onTriggered: root.quietHeld = true
    }

    // Остров и Live-сцена: DWM ведёт HWND через startSystemMove.
    // Конец жеста — по отпусканию ЛКМ (MouseArea уже отдал захват системе).
    Timer {
        interval: 16
        running: root.dragging && (root.shellMode === "island" || root.shellMode === "theater")
        repeat: true
        onTriggered: {
            if (bridge.primaryButtonDown())
                return
            if (root.shellMode === "island") {
                root.endIslandDrag()
                return
            }
            root.dragging = false
            root.theaterX = root.x
            root.theaterY = root.y
            root.theaterW = Math.round(root.width)
            root.theaterH = Math.round(root.height)
        }
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
        id: islandChrome
        visible: root.shellMode === "island"
        width: root.islandW
        height: root.islandH
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        opacity: Math.max(0.92, root.shellFade) * Math.max(0.9, Number(bridge.settings.island_opacity))
        shellRise: root.shellRise
        phase: root.islandPhase
        radius: root.islandR
        // Диктовка всегда принимает клики: иначе «чёрный блок» без кнопок.
        clickThrough: Boolean(bridge.settings.island_click_through) && root.shellMode === "island"
                       && !root.dragging
                       && !(bridge.page === "dictation" && (bridge.recording || bridge.busy))
        onRequestTheater: root.openTheater()
        onRequestApp: root.openApp(page)
        onRequestModePick: root.islandModesOpen = true
        onCloseModes: root.islandModesOpen = false
        onDragStarted: root.beginIslandDrag()
    }

    LiveTheater {
        visible: root.shellMode === "theater"
        anchors.fill: parent
        opacity: root.shellFade
        transform: Translate { y: root.shellRise }
        embedded: false
        onRequestIsland: root.collapse()
        onRequestApp: root.openApp("live")
        onShellDragStarted: root.dragging = true
        onShellDragReleased: {
            root.dragging = false
            root.theaterX = root.x
            root.theaterY = root.y
            root.theaterW = Math.round(root.width)
            root.theaterH = Math.round(root.height)
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
        // Системная рамка уже рисует край окна — без второго «карточного» борта.
        color: Theme.bg
        radius: 0
        border.width: 0
        clip: true

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
                        Image {
                            Layout.preferredWidth: 34
                            Layout.preferredHeight: 34
                            source: Qt.resolvedUrl("../assets/app_icon_32.png")
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                            mipmap: true
                        }
                        ColumnLayout {
                            spacing: 0
                            Label { text: ".аудио"; color: Theme.text; font.pixelSize: Theme.fsSection; font.weight: Font.DemiBold }
                            Label { text: "локальная речь"; color: Theme.muted; font.pixelSize: Theme.fsMicro }
                        }
                    }
                    // Навигация. Выделение - один переезжающий блок, а не
                    // мгновенная перекраска: видно, откуда и куда ушёл фокус.
                    // История / Модели / Среда - внизу в раскрываемой группе.
                    Item {
                        id: navBox
                        readonly property int rowH: 48
                        readonly property int rowGap: 6
                        readonly property var primaryModel: [
                            { key: "live", icon: "live", title: "Live", detail: "Субтитры" },
                            { key: "dictation", icon: "dictation", title: "Диктовка", detail: "Голос в текст" },
                            { key: "transcript", icon: "media", title: "Транскрибация", detail: "Файл + голоса" },
                            // Караоке UI скрыт 2026-09-09 — см. docs/HANDOFF.md «Караоке UI скрыт».
                            // { key: "media", icon: "media", title: "Караоке", detail: "Аудио и видео" },
                            { key: "assistant", icon: "assistant", title: "Ассистент", detail: "Чат по записи" }
                        ]
                        readonly property var secondaryModel: [
                            { key: "history", icon: "history", title: "История", detail: "Сессии" },
                            { key: "models", icon: "models", title: "Модели", detail: "Whisper" },
                            { key: "settings", icon: "settings", title: "Среда", detail: "Устройства" }
                        ]
                        readonly property var secondaryKeys: ["history", "models", "settings"]
                        property bool moreUserOpen: false
                        readonly property bool moreExpanded: moreUserOpen
                                                          || secondaryKeys.indexOf(bridge.page) >= 0
                        readonly property int current: Math.max(0, root.pageKeys.indexOf(bridge.page))
                        // Индекс ряда под бегунком: после основных идёт заголовок
                        // группы, затем вторичные (когда раскрыты).
                        readonly property int highlightIndex: {
                            var i
                            for (i = 0; i < primaryModel.length; ++i) {
                                if (primaryModel[i].key === bridge.page)
                                    return i
                            }
                            for (i = 0; i < secondaryModel.length; ++i) {
                                if (secondaryModel[i].key === bridge.page)
                                    return primaryModel.length + 1 + i
                            }
                            return 0
                        }
                        readonly property int visibleCount: primaryModel.length + 1
                                                          + (moreExpanded ? secondaryModel.length : 0)
                        Layout.fillWidth: true
                        Layout.preferredHeight: visibleCount * rowH
                                                + (visibleCount - 1) * rowGap
                        Behavior on Layout.preferredHeight {
                            NumberAnimation {
                                duration: Theme.slowMs
                                easing.type: Easing.Bezier
                                easing.bezierCurve: Theme.easeOut
                            }
                        }

                        function step(delta) {
                            var next = navBox.current + delta
                            if (next < 0 || next >= root.pageKeys.length)
                                return
                            bridge.selectPage(root.pageKeys[next])
                        }

                        function toggleMore() {
                            // Пока открыт вторичный раздел, группу не сворачиваем:
                            // иначе пропадёт пункт с текущей страницей.
                            if (navBox.secondaryKeys.indexOf(bridge.page) >= 0)
                                return
                            navBox.moreUserOpen = !navBox.moreUserOpen
                        }

                        Component {
                            id: navButton
                            Button {
                                id: nav
                                required property var modelData
                                readonly property bool selected: bridge.page === nav.modelData.key
                                width: navBox.width
                                height: navBox.rowH
                                hoverEnabled: true
                                onClicked: bridge.selectPage(nav.modelData.key)
                                Accessible.role: Accessible.PageTab
                                Accessible.name: nav.modelData.title + ", " + nav.modelData.detail
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
                                            color: nav.selected ? Theme.text : Theme.muted
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

                        Rectangle {
                            width: navBox.width
                            height: navBox.rowH
                            radius: Theme.radiusMd
                            color: Theme.fill
                            border.width: 1
                            border.color: Theme.hairline
                            y: navBox.highlightIndex * (navBox.rowH + navBox.rowGap)
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
                                model: navBox.primaryModel
                                delegate: navButton
                            }

                            Button {
                                id: moreToggle
                                width: navBox.width
                                height: navBox.rowH
                                hoverEnabled: true
                                onClicked: navBox.toggleMore()
                                Accessible.role: Accessible.Button
                                Accessible.name: navBox.moreExpanded
                                                 ? "Свернуть служебные разделы"
                                                 : "Ещё: история, модели, среда"
                                Keys.onUpPressed: navBox.step(-1)
                                Keys.onDownPressed: navBox.step(1)
                                contentItem: RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 12
                                    spacing: 10
                                    Icon {
                                        name: "more"
                                        ink: Theme.muted
                                        width: 16
                                        height: 16
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 0
                                        Label {
                                            text: "Ещё"
                                            color: Theme.muted
                                            font.pixelSize: Theme.fsBody
                                            font.weight: Font.DemiBold
                                        }
                                        Label {
                                            text: "История, модели, среда"
                                            color: Theme.muted
                                            font.pixelSize: Theme.fsMicro
                                            opacity: 0.75
                                        }
                                    }
                                    Icon {
                                        name: navBox.moreExpanded ? "collapse" : "expand"
                                        ink: Theme.muted
                                        width: 14
                                        height: 14
                                    }
                                }
                                background: Rectangle {
                                    radius: Theme.radiusMd
                                    color: moreToggle.hovered ? Theme.hairline : "transparent"
                                    border.width: moreToggle.activeFocus ? 1 : 0
                                    border.color: Theme.borderHi
                                    Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                                }
                            }

                            Repeater {
                                model: navBox.moreExpanded ? navBox.secondaryModel : []
                                delegate: navButton
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
                            text: root.pageTitle
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
                    PillButton { text: "Скрыть"; onClicked: root.hide(); ToolTip.visible: hovered; ToolTip.text: "Вернуть: Ctrl+Alt+O" }
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
                    visible: bridge.showGpuHint && !(setup && setup.visible)
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
                    TranscriptView { Layout.fillWidth: true; Layout.fillHeight: true }
                    // Караоке UI скрыт 2026-09-09 — Loader убран из стека, чтобы индексы
                    // pageKeys совпадали. Файл MediaPage.qml не удалять.
                    // Включение: вернуть Loader ниже и "media" в pageKeys/nav.
                    // Loader {
                    //     readonly property bool current: StackLayout.isCurrentItem
                    //     property bool wanted: false
                    //     asynchronous: true
                    //     active: wanted
                    //     source: "MediaPage.qml"
                    //     onCurrentChanged: if (current) wanted = true
                    //     Component.onCompleted: if (current) wanted = true
                    // }
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
                        source: "SettingsPage.qml"
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

    // Мастер первого запуска поверх оболочки: опрос, брифинг, прогресс.
    SetupWizard {
        anchors.fill: parent
        z: 100
        visible: setup !== null && setup !== undefined && setup.visible
    }
}
