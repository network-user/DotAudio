import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

// Отдельный режим «Транскрибация»: файл -> расшифровка с таймкодами и
// говорящими. Весь обмен идёт через мост bridge.*; распознавание всегда
// локально (bridge.runTranscript никогда не выбирает сервер), а голоса
// определяет выбранный движок: NVIDIA NeMo Sortformer или ECAPA.
//
// Воспроизведение - через TranscriptPlayer (sibling); busy - через
// TranscriptBusy. Оба компонента подхватываются Qt Quick по имени файла.
Rectangle {
    id: view
    color: "transparent"
    focus: true

    property string phase: String(bridge.transcribeState.phase || "idle")
    property string stage: String(bridge.transcribeState.stage || "")
    property string file: String(bridge.transcribeState.file || "")
    property real progress: {
        var raw = bridge.transcribeState.progress
        return raw === undefined || raw === null ? -1 : Number(raw)
    }
    property bool busyPhase: phase === "working"
    property var segs: bridge.transcribeSegments
    property var speakers: bridge.transcribeState.speakers || []
    property string engineNote: String(bridge.transcribeState.engineNote || "")
    property var voices: bridge.diarizeStatus
    property var engines: bridge.diarizeEngines
    property string mediaUrl: String(bridge.transcribeMediaUrl || "")

    // Показывать только один голос. 0 - показывать всех.
    property int focusKey: 0
    // Фраза, к которой только что перешли с полосы голосов или кликом.
    property int markedIndex: -1
    // Глобальный индекс сегмента, который сейчас играет (по позиции плеера).
    property int playIndex: -1
    // Глобальный индекс карточки в режиме правки (-1 = никто).
    property int editingIndex: -1
    // Панель сохранения: формат и фильтры экспорта.
    property bool exportOpen: false
    property int exportFormatIndex: 0
    property bool exportTimestamps: false
    property bool exportSpeakers: true
    property bool exportFocusedOnly: false
    property bool onlyFlagged: false
    property var mutedKeys: ({})
    property var soloKeys: ({})

    readonly property var exportFormats: [
        { key: "txt", label: "TXT - простой текст" },
        { key: "md", label: "MD - Markdown" },
        { key: "srt", label: "SRT - субтитры" },
        { key: "vtt", label: "VTT - веб-субтитры" },
        { key: "json", label: "JSON - данные" }
    ]
    readonly property string exportFormatKey: view.exportFormats[Math.max(0, Math.min(view.exportFormatIndex, view.exportFormats.length - 1))].key
    readonly property bool exportTimesForced: view.exportFormatKey === "srt" || view.exportFormatKey === "vtt"

    readonly property var rows: {
        var list = view.segs || []
        var out = []
        for (var i = 0; i < list.length; ++i) {
            var row = list[i]
            if (view.focusKey > 0 && Number(row.role) !== view.focusKey)
                continue
            if (view.onlyFlagged) {
                var conf = Number(row.confidence)
                var reviewed = Boolean(row.reviewed)
                var low = (conf >= 0 && conf < 0.55) || (conf < 0 && String(row.text || "").length < 2)
                if (!(low && !reviewed))
                    continue
            }
            if (view.speakerTrackHidden(row))
                continue
            out.push(row)
        }
        return out
    }
    readonly property real total: Math.max(0.001, Number(bridge.transcribeState.duration || 0))
    readonly property bool hasMedia: mediaUrl.length > 0 || view.file.length > 0
    readonly property var activePhrase: {
        var list = view.segs || []
        if (view.playIndex >= 0 && view.playIndex < list.length)
            return list[view.playIndex]
        if (view.markedIndex >= 0 && view.markedIndex < list.length)
            return list[view.markedIndex]
        return null
    }

    Component.onCompleted: bridge.refreshDiarizeStatus()

    function timecode(seconds) {
        var total = Math.max(0, Math.round(Number(seconds) * 1000))
        var hours = Math.floor(total / 3600000)
        total -= hours * 3600000
        var minutes = Math.floor(total / 60000)
        total -= minutes * 60000
        var rest = (total / 1000).toFixed(1)
        if (rest.length < 4) rest = "0" + rest
        return (hours > 0 ? (hours < 10 ? "0" : "") + hours + ":" : "")
               + (minutes < 10 ? "0" : "") + minutes + ":" + rest
    }

    function applyPendingSeek() {
        if (bridge.pendingSeekMs < 0 || player.duration <= 0)
            return
        player.seekSeconds(bridge.pendingSeekMs / 1000)
        bridge.clearPendingSeek()
    }

    function duration(seconds) {
        var whole = Math.max(0, Math.round(Number(seconds)))
        var minutes = Math.floor(whole / 60)
        var rest = whole % 60
        return minutes > 0 ? minutes + " мин " + rest + " с" : rest + " с"
    }

    function phrases(count) {
        var value = Number(count)
        var tail = Math.abs(value) % 100
        var last = tail % 10
        if (tail > 10 && tail < 20) return value + " реплик"
        if (last === 1) return value + " реплика"
        if (last >= 2 && last <= 4) return value + " реплики"
        return value + " реплик"
    }

    function engineIndex() {
        var key = String(view.voices.engine || "off")
        for (var i = 0; i < view.engines.length; ++i)
            if (String(view.engines[i].key) === key)
                return i
        return 0
    }

    readonly property var whisperModels: [
        { key: "tiny", label: "tiny · быстро" },
        { key: "base", label: "base · легче" },
        { key: "small", label: "small · баланс" },
        { key: "medium", label: "medium · точнее" },
        { key: "large-v3", label: "large-v3 · качество" },
        { key: "turbo", label: "turbo · быстрее large" }
    ]

    function whisperModelIndex() {
        var key = String(bridge.settings.model || "small")
        for (var i = 0; i < view.whisperModels.length; ++i)
            if (String(view.whisperModels[i].key) === key)
                return i
        return 2
    }

    function whisperDisk(modelKey) {
        var lib = bridge.modelLibrary || []
        for (var i = 0; i < lib.length; ++i) {
            if (String(lib[i].model) === String(modelKey))
                return lib[i]
        }
        return { ready: false, bytes: 0 }
    }

    function whisperModelNote() {
        var key = String(bridge.settings.model || "small")
        var spec = bridge.modelCatalog[key] || null
        var disk = view.whisperDisk(key)
        var fit = bridge.modelFit(key)
        var parts = []
        if (disk.ready)
            parts.push("в кеше")
        else if (bridge.modelPreparing && String(bridge.modelState.model) === key)
            parts.push(bridge.modelDownload.phase === "download"
                       ? ("скачивание " + Math.round(bridge.modelDownload.percent || 0) + "%")
                       : "готовим…")
        else
            parts.push("не загружена")
        if (spec)
            parts.push("~" + spec.download_mb + " МБ · ~" + spec.ram_gb + " ГБ ОЗУ")
        if (String(bridge.recommendedModel || "") === key)
            parts.push("рекомендуем для этого ПК")
        else if (fit && fit.note)
            parts.push(String(fit.note))
        return parts.join(" · ")
    }

    function speakerTrackHidden(row) {
        var key = Number(row.role || 0)
        if (key <= 0)
            return false
        var soloOn = false
        for (var k in view.soloKeys) {
            if (view.soloKeys[k]) {
                soloOn = true
                break
            }
        }
        if (soloOn)
            return !Boolean(view.soloKeys[String(key)])
        return Boolean(view.mutedKeys[String(key)])
    }

    function toggleMuteKey(key) {
        var next = Object.assign({}, view.mutedKeys)
        var k = String(key)
        next[k] = !Boolean(next[k])
        view.mutedKeys = next
    }

    function toggleSoloKey(key) {
        var next = Object.assign({}, view.soloKeys)
        var k = String(key)
        next[k] = !Boolean(next[k])
        view.soloKeys = next
    }

    function confidenceLabel(row) {
        var conf = Number(row.confidence)
        if (!(conf >= 0))
            return ""
        return Math.round(conf * 100) + "%"
    }

    function confidenceTint(row) {
        var conf = Number(row.confidence)
        if (!(conf >= 0))
            return Theme.faint
        if (conf < 0.55)
            return Theme.rec
        if (conf < 0.72)
            return Theme.muted
        return Theme.text
    }

    function selectWhisperModel(index) {
        if (view.busyPhase || index < 0 || index >= view.whisperModels.length)
            return
        var key = String(view.whisperModels[index].key)
        if (key === String(bridge.settings.model || ""))
            return
        bridge.setSetting("model", key)
        var disk = view.whisperDisk(key)
        if (!disk.ready && !bridge.modelPreparing)
            bridge.prepareSelectedModel()
    }

    function busyMessage() {
        var model = String(bridge.settings.model || "small")
        if (view.stage === "voices")
            return "Слова готовы. Определяем, кто из говорящих что произнёс…"
        return "Распознаём моделью Whisper «" + model
               + "». На длинной записи это занимает время."
    }

    function focusIsTextEdit() {
        var win = view.Window.window
        var item = win ? win.activeFocusItem : null
        if (!item)
            return false
        var name = item.toString()
        return name.indexOf("TextField") >= 0
               || name.indexOf("TextInput") >= 0
               || name.indexOf("TextEdit") >= 0
               || name.indexOf("TextArea") >= 0
    }

    // Глобальный индекс в bridge.transcribeSegments / view.segs.
    // При focusKey > 0 список отфильтрован, index делегата не подходит.
    function globalIndexOf(row) {
        if (!row)
            return -1
        for (var i = 0; i < view.segs.length; ++i) {
            var s = view.segs[i]
            if (Number(s.start) === Number(row.start) && Number(s.end) === Number(row.end)
                    && String(s.text) === String(row.text)
                    && String(s.speaker || "") === String(row.speaker || ""))
                return i
        }
        return -1
    }

    function speakerKindLabel(kind) {
        var key = String(kind || "voice").toLowerCase()
        if (key === "male") return "Парень"
        if (key === "female") return "Девушка"
        return "Голос"
    }

    function nextSpeakerKind(kind) {
        var key = String(kind || "voice").toLowerCase()
        if (key === "voice") return "male"
        if (key === "male") return "female"
        return "voice"
    }

    function speakerPickModel() {
        var items = [{ label: "без метки", value: "" }]
        for (var i = 0; i < view.speakers.length; ++i) {
            var sp = view.speakers[i]
            items.push({ label: String(sp.label || ("Голос " + sp.key)), value: String(sp.label || "") })
        }
        return items
    }

    onBusyPhaseChanged: {
        if (busyPhase)
            view.editingIndex = -1
    }

    onFocusKeyChanged: {
        if (view.focusKey <= 0)
            view.exportFocusedOnly = false
    }

    // Воспроизвести фразу и кратко подсветить её в полном списке.
    function playPhraseAt(startSec, endSec, globalIndex) {
        if (globalIndex !== undefined && globalIndex >= 0 && view.focusKey === 0) {
            view.markedIndex = globalIndex
            markTimer.restart()
        }
        if (view.hasMedia)
            player.playPhrase(Number(startSec), Number(endSec))
    }

    // Переход с полосы голосов к фразе. Фильтр снимается: иначе номер
    // фразы на полосе не совпал бы с номером строки в отфильтрованном списке.
    function revealPhrase(index) {
        view.focusKey = 0
        Qt.callLater(function () {
            segList.positionViewAtIndex(index, ListView.Center)
            view.markedIndex = index
            markTimer.restart()
        })
    }

    function syncPlayIndex() {
        var t = Number(player.position) / 1000
        var found = -1
        for (var i = 0; i < view.segs.length; ++i) {
            var row = view.segs[i]
            if (t >= Number(row.start) && t < Number(row.end)) {
                found = i
                break
            }
        }
        // Между фразами: ближайшая уже начавшаяся (для паузы/скролла по шкале).
        if (found < 0 && view.segs.length > 0 && t > 0) {
            for (var j = view.segs.length - 1; j >= 0; --j) {
                if (t >= Number(view.segs[j].start)) {
                    found = j
                    break
                }
            }
        }
        if (found !== view.playIndex)
            view.playIndex = found
        if (!player.playing || found < 0 || view.focusKey !== 0)
            return
        segList.positionViewAtIndex(found, ListView.Contain)
    }

    Timer {
        id: markTimer
        interval: 1600
        onTriggered: view.markedIndex = -1
    }

    // Space: play/pause, если фокус не в поле имени говорящего.
    Shortcut {
        sequence: "Space"
        context: Qt.WindowShortcut
        enabled: view.visible && view.hasMedia
        onActivated: {
            if (view.focusIsTextEdit())
                return
            player.toggle()
        }
    }
    Shortcut {
        sequence: "Left"
        context: Qt.WindowShortcut
        enabled: view.visible && view.hasMedia && !view.focusIsTextEdit()
        onActivated: player.skipBy(-1)
    }
    Shortcut {
        sequence: "Right"
        context: Qt.WindowShortcut
        enabled: view.visible && view.hasMedia && !view.focusIsTextEdit()
        onActivated: player.skipBy(1)
    }
    Shortcut {
        sequence: "I"
        context: Qt.WindowShortcut
        enabled: view.visible && view.hasMedia && !view.focusIsTextEdit()
        onActivated: player.markIn()
    }
    Shortcut {
        sequence: "O"
        context: Qt.WindowShortcut
        enabled: view.visible && view.hasMedia && !view.focusIsTextEdit()
        onActivated: player.markOut()
    }
    Shortcut {
        sequence: "L"
        context: Qt.WindowShortcut
        enabled: view.visible && view.hasMedia && !view.focusIsTextEdit()
        onActivated: {
            if (player.loopRegion) {
                player.loopRegion = false
                player.clearPhraseRange()
            } else {
                player.playAbRegion()
            }
        }
    }
    Shortcut {
        sequence: "R"
        context: Qt.WindowShortcut
        enabled: view.visible && view.hasMedia && !view.focusIsTextEdit()
        onActivated: player.repeatPhrase()
    }
    Shortcut {
        sequence: "Ctrl+Z"
        context: Qt.WindowShortcut
        enabled: view.visible && !view.busyPhase
        onActivated: bridge.undoTranscriptEdit()
    }
    Shortcut {
        sequence: "Ctrl+Y"
        context: Qt.WindowShortcut
        enabled: view.visible && !view.busyPhase
        onActivated: bridge.redoTranscriptEdit()
    }

    DropArea {
        anchors.fill: parent
        enabled: !view.busyPhase
        keys: ["text/uri-list"]
        onDropped: function (drop) {
            if (!drop.hasUrls || drop.urls.length === 0)
                return
            bridge.pickTranscriptFilename(String(drop.urls[0]))
            drop.acceptProposedAction()
        }
    }

    readonly property real chromeShare: view.segs.length > 0 ? 0.40 : 0.55

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gapSm

        // Текущий текст по таймкоду плеера - всегда в самом верху страницы.
        Rectangle {
            Layout.fillWidth: true
            visible: view.segs.length > 0 && view.activePhrase !== null
            implicitHeight: liveCaptionCol.implicitHeight + 2 * Theme.padCard
            radius: Theme.radiusLg
            color: player.playing ? Theme.liveSurface : Theme.surface3
            border.width: player.playing ? 2 : 1
            border.color: player.playing ? Theme.liveBorder : Theme.borderHi
            Behavior on color { ColorAnimation { duration: Theme.fastMs } }
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 4
                radius: 2
                visible: player.playing
                color: Theme.liveBar
            }
            ColumnLayout {
                id: liveCaptionCol
                anchors.fill: parent
                anchors.margins: Theme.padCard
                anchors.leftMargin: Theme.padCard + (player.playing ? 6 : 0)
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    Label {
                        text: player.playing ? "Сейчас звучит" : "По таймкоду"
                        color: player.playing ? Theme.text : Theme.muted
                        font.pixelSize: Theme.fsMicro
                        font.weight: Font.DemiBold
                    }
                    Label {
                        visible: view.activePhrase && String(view.activePhrase.speaker || "").length > 0
                        text: view.activePhrase ? String(view.activePhrase.speaker) : ""
                        color: Theme.speakerInk(view.activePhrase ? view.activePhrase.role : 0)
                        font.pixelSize: Theme.fsSmall
                        font.weight: Font.DemiBold
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        visible: view.activePhrase !== null
                        text: view.activePhrase
                              ? (view.timecode(view.activePhrase.start) + " - "
                                 + view.timecode(view.activePhrase.end))
                              : ""
                        color: Theme.faint
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.fsMicro
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: view.activePhrase ? String(view.activePhrase.text || "") : ""
                    color: Theme.text
                    font.pixelSize: player.playing ? Theme.fsTitle : Theme.fsLead
                    font.weight: Font.Bold
                    wrapMode: Text.Wrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }
            }
        }

    SplitView {
        id: mainSplit
        Layout.fillWidth: true
        Layout.fillHeight: true
        orientation: Qt.Vertical
        handle: Item {
            implicitWidth: 1
            implicitHeight: 10
            Rectangle {
                anchors.centerIn: parent
                width: 56
                height: 3
                radius: 1.5
                color: SplitHandle.pressed || SplitHandle.hovered ? Theme.text : Theme.border
            }
        }

        // Верх: шапка, плеер, инструменты, голоса - свой скролл и высота ручкой.
        ScrollView {
            id: chromeScroll
            SplitView.preferredHeight: Math.max(160, Math.round(mainSplit.height * view.chromeShare))
            SplitView.minimumHeight: 140
            SplitView.maximumHeight: Math.max(180, mainSplit.height - 150)
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                id: chromeCol
                width: chromeScroll.availableWidth
                spacing: Theme.gapSm

                // Панель выбора, запуска и движка голосов.
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: topRow.implicitHeight + 2 * Theme.padCard
                    radius: Theme.radiusLg
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.border
                    clip: true
                    ColumnLayout {
                        id: topRow
                        anchors.fill: parent
                        anchors.margins: Theme.padCard
                        spacing: Theme.gapSm
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Label {
                                    text: view.file.length ? view.file : "Расшифровка аудио или видео"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Label {
                                    text: view.file.length
                                          ? "Обработка локально. Аудио не покидает этот компьютер."
                                          : "Откройте запись или перетащите файл сюда. Слова с таймкодами и метки говорящих."
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                                Label {
                                    visible: String(bridge.transcribeState.origin || "") === "live"
                                             && !view.hasMedia && !view.busyPhase
                                    text: "Запись Live · звук удалён после обработки"
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                }
                            }
                            PillButton { text: "Открыть файл"; enabled: !view.busyPhase; onClicked: bridge.pickTranscriptFile() }
                            PillButton {
                                text: view.busyPhase ? "Стоп" : "Расшифровать"
                                primary: !view.busyPhase
                                enabled: view.busyPhase || view.hasMedia
                                onClicked: view.busyPhase ? bridge.stopTranscript() : bridge.runTranscript()
                            }
                            PillButton {
                                text: bridge.speechModeLabel
                                enabled: !view.busyPhase
                                onClicked: bridge.cycleSpeechMode()
                                ToolTip.visible: hovered
                                ToolTip.text: bridge.speechModeHint
                            }
                            PillButton {
                                text: "Очистить"
                                enabled: (view.file.length > 0 || view.segs.length > 0) && !view.busyPhase
                                onClicked: {
                                    view.exportOpen = false
                                    bridge.clearTranscript()
                                }
                            }
                            PillButton {
                                text: view.exportOpen ? "Скрыть сохранение" : "Сохранить…"
                                enabled: view.segs.length > 0 && !view.busyPhase
                                onClicked: view.exportOpen = !view.exportOpen
                            }
                            PillButton {
                                text: "В ассистент"
                                primary: true
                                visible: view.phase === "done" && view.segs.length > 0
                                         && String(bridge.transcribeState.sessionId || "").length > 0
                                enabled: !view.busyPhase
                                onClicked: bridge.openTranscriptInAssistant()
                                ToolTip.visible: hovered
                                ToolTip.text: "Открыть эту расшифровку в чате ассистента"
                            }
                        }

                        // Фильтры сохранения: формат, таймкоды, голоса.
                        Rectangle {
                            Layout.fillWidth: true
                            visible: view.exportOpen && view.segs.length > 0 && !view.busyPhase
                            implicitHeight: exportBox.implicitHeight + 2 * Theme.padCard
                            radius: Theme.radiusMd
                            color: Theme.surface2
                            border.width: 1
                            border.color: Theme.border
                            ColumnLayout {
                                id: exportBox
                                anchors.fill: parent
                                anchors.margins: Theme.padCard
                                spacing: Theme.gapSm
                                Label {
                                    text: "Сохранение расшифровки"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsLabel
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: "Выберите формат и что включить в файл: таймкоды, имена говорящих или только выбранный голос."
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.gapSm
                                    Label {
                                        text: "Формат"
                                        color: Theme.muted
                                        font.pixelSize: Theme.fsLabel
                                    }
                                    Dropdown {
                                        id: formatPick
                                        Layout.preferredWidth: 220
                                        model: view.exportFormats
                                        textRole: "label"
                                        currentIndex: view.exportFormatIndex
                                        onActivated: function (index) {
                                            view.exportFormatIndex = index
                                            if (view.exportTimesForced)
                                                view.exportTimestamps = true
                                        }
                                    }
                                    Item { Layout.fillWidth: true }
                                    PillButton {
                                        text: "Скачать файл"
                                        primary: true
                                        onClicked: {
                                            bridge.transcriptExport(
                                                view.exportFormatKey,
                                                view.exportTimesForced || view.exportTimestamps,
                                                view.exportSpeakers,
                                                view.exportFocusedOnly ? view.focusKey : 0
                                            )
                                        }
                                    }
                                }
                                Flow {
                                    Layout.fillWidth: true
                                    spacing: Theme.gapMd
                                    ToggleSwitch {
                                        text: view.exportTimesForced
                                              ? "Таймкоды (обязательны для субтитров)"
                                              : "Таймкоды у строк"
                                        checked: view.exportTimesForced || view.exportTimestamps
                                        enabled: !view.exportTimesForced
                                        onToggled: view.exportTimestamps = checked
                                    }
                                    ToggleSwitch {
                                        text: "Имена говорящих"
                                        checked: view.exportSpeakers
                                        onToggled: view.exportSpeakers = checked
                                    }
                                    ToggleSwitch {
                                        text: view.focusKey > 0
                                              ? "Только выбранный голос"
                                              : "Только выбранный голос (сначала фильтр сверху)"
                                        checked: view.exportFocusedOnly
                                        enabled: view.focusKey > 0
                                        onToggled: view.exportFocusedOnly = checked
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: {
                                        var parts = [view.exportFormatKey.toUpperCase()]
                                        if (view.exportTimesForced || view.exportTimestamps)
                                            parts.push("с таймкодами")
                                        else
                                            parts.push("без таймкодов")
                                        parts.push(view.exportSpeakers ? "с голосами" : "только текст")
                                        if (view.exportFocusedOnly && view.focusKey > 0)
                                            parts.push("один голос")
                                        return "Будет сохранено: " + parts.join(" · ")
                                              + " · " + view.phrases(view.exportFocusedOnly && view.focusKey > 0
                                                                      ? view.rows.length : view.segs.length)
                                    }
                                    color: Theme.faint
                                    font.pixelSize: Theme.fsMicro
                                    wrapMode: Text.Wrap
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.topMargin: 2
                            implicitHeight: 1
                            color: Theme.hairline
                        }

                        // Модель Whisper для этой расшифровки (общая настройка приложения).
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            Label {
                                text: "Whisper"
                                color: Theme.muted
                                font.pixelSize: Theme.fsLabel
                            }
                            Dropdown {
                                id: whisperPick
                                Layout.preferredWidth: 210
                                enabled: !view.busyPhase && !bridge.modelPreparing
                                model: view.whisperModels
                                textRole: "label"
                                currentIndex: view.whisperModelIndex()
                                onActivated: function (index) {
                                    view.selectWhisperModel(index)
                                }
                            }
                            StatusDot {
                                active: Boolean(view.whisperDisk(bridge.settings.model).ready)
                                tint: Boolean(view.whisperDisk(bridge.settings.model).ready)
                                      ? Theme.text
                                      : (bridge.modelPreparing
                                         && String(bridge.modelState.model) === String(bridge.settings.model)
                                         ? Theme.muted : Theme.rec)
                            }
                            Label {
                                Layout.fillWidth: true
                                text: view.whisperModelNote()
                                color: Theme.muted
                                font.pixelSize: Theme.fsSmall
                                elide: Text.ElideRight
                            }
                            PillButton {
                                text: "Загрузить"
                                compact: true
                                visible: !Boolean(view.whisperDisk(bridge.settings.model).ready)
                                         && !(bridge.modelPreparing
                                              && String(bridge.modelState.model) === String(bridge.settings.model))
                                enabled: !view.busyPhase && !bridge.modelPreparing
                                onClicked: bridge.prepareSelectedModel()
                                ToolTip.visible: hovered
                                ToolTip.text: "Скачать выбранную модель Whisper в локальный кеш"
                            }
                            PillButton {
                                text: "Отмена"
                                compact: true
                                visible: bridge.modelPreparing
                                         && String(bridge.modelState.model) === String(bridge.settings.model)
                                onClicked: bridge.cancelModelPrepare()
                            }
                        }

                        // Выбор движка голосов и его готовность.
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            Label {
                                text: "Голоса"
                                color: Theme.muted
                                font.pixelSize: Theme.fsLabel
                            }
                            Dropdown {
                                id: enginePick
                                Layout.preferredWidth: 190
                                enabled: !view.busyPhase
                                model: view.engines
                                textRole: "label"
                                currentIndex: view.engineIndex()
                                onActivated: function (index) {
                                    bridge.setDiarizeEngine(String(view.engines[index].key))
                                }
                            }
                            StatusDot {
                                active: view.voices.ready === true
                                tint: view.voices.ready === true ? Theme.text
                                      : view.voices.checking === true ? Theme.muted : Theme.rec
                            }
                            Label {
                                Layout.fillWidth: true
                                text: String(view.voices.message || "")
                                color: view.voices.ready === true ? Theme.muted : Theme.text
                                font.pixelSize: Theme.fsSmall
                                elide: Text.ElideRight
                            }
                            PillButton {
                                text: "Проверить снова"
                                compact: true
                                visible: String(view.voices.engine || "") === "nemo"
                                enabled: view.voices.checking !== true && !view.busyPhase
                                onClicked: bridge.refreshDiarizeStatus()
                            }
                        }

                        TranscriptBusy {
                            Layout.fillWidth: true
                            active: view.busyPhase
                            stage: view.stage
                            progress: view.progress
                            fileName: view.file
                            message: view.busyMessage()
                        }
                    }
                }

                // Плеер исходника: доступен сразу после выбора файла, до ASR.
                TranscriptPlayer {
                    id: player
                    Layout.fillWidth: true
                    compact: view.segs.length > 0
                    visible: view.hasMedia
                    source: view.mediaUrl
                    segments: view.segs
                    peaks: bridge.mediaPeaks
                    peaksDuration: bridge.mediaPeaksDuration
                    selectedIndex: view.playIndex >= 0 ? view.playIndex : view.editingIndex
                    editableEdges: view.segs.length > 0 && !view.busyPhase
                    onPlayingChanged: view.syncPlayIndex()
                    onPositionChanged: view.syncPlayIndex()
                    onDurationChanged: view.applyPendingSeek()
                    onEdgeChanged: function (index, start, end) {
                        bridge.setTranscriptPhraseWindow(index, start, end)
                    }
                }

                TranscriptTools {
                    Layout.fillWidth: true
                    visible: view.segs.length > 0
                    busy: view.busyPhase
                    quality: bridge.transcriptQuality
                    presets: bridge.transcriptExportPresets
                    compare: bridge.transcriptCompare
                    canUndo: bridge.transcriptCanUndo
                    canRedo: bridge.transcriptCanRedo
                    onlyFlagged: view.onlyFlagged
                    onUndoRequested: bridge.undoTranscriptEdit()
                    onRedoRequested: bridge.redoTranscriptEdit()
                    onReplaceRequested: function (find, replace) {
                        bridge.replaceInTranscript(find, replace, false)
                    }
                    onDictionaryRequested: bridge.applyDictionaryToTranscript()
                    onExportPresetRequested: function (key, options) {
                        bridge.transcriptExportPreset(key, options || {})
                    }
                    onCompareRequested: bridge.runTranscriptModelCompare()
                    onOnlyFlaggedToggled: function (value) {
                        view.onlyFlagged = value
                    }
                    onAssistantRequested: bridge.openTranscriptInAssistant()
                }

                Connections {
                    target: bridge
                    function onChanged() { view.applyPendingSeek() }
                }

                // Как включить выбранный движок, если его нет на машине.
                Rectangle {
                    Layout.fillWidth: true
                    visible: view.segs.length === 0
                             && view.voices.ready !== true && view.voices.checking !== true
                             && String(view.voices.hint || "").length > 0
                    implicitHeight: setupBox.implicitHeight + 2 * Theme.padCard
                    radius: Theme.radiusLg
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.borderHi
                    ColumnLayout {
                        id: setupBox
                        anchors.fill: parent
                        anchors.margins: Theme.padCard
                        spacing: Theme.gapSm
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            Icon { name: "warning"; ink: Theme.text; width: 16; height: 16 }
                            Label {
                                Layout.fillWidth: true
                                text: String(view.voices.hint || "")
                                color: Theme.text
                                font.pixelSize: Theme.fsBody
                                wrapMode: Text.Wrap
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: String(view.voices.install || "").length > 0
                            spacing: Theme.gapSm
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: Math.max(34, command.implicitHeight + 14)
                                radius: Theme.radiusMd
                                color: Theme.fill
                                border.width: 1
                                border.color: Theme.hairline
                                TextEdit {
                                    id: command
                                    anchors.fill: parent
                                    anchors.margins: 9
                                    text: String(view.voices.install || "")
                                    readOnly: true
                                    selectByMouse: true
                                    wrapMode: TextEdit.WrapAnywhere
                                    color: Theme.text
                                    selectionColor: Theme.fillPress
                                    font.family: Theme.monoFamily
                                    font.pixelSize: Theme.fsSmall
                                }
                            }
                            PillButton { text: "Копировать"; compact: true; onClicked: bridge.copyDiarizeInstall() }
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: String(view.voices.engine || "") === "nemo"
                            text: "Python-пакет NeMo не поддерживает Windows, поэтому используется нативный рантайм NVIDIA NeMo-Speech.cpp. Он не тянет torch и работает на процессоре."
                            color: Theme.faint
                            font.pixelSize: Theme.fsSmall
                            wrapMode: Text.Wrap
                        }
                    }
                }

                // Легенда говорящих: цвет, имя (правится), доля речи, фильтр.
                Rectangle {
                    Layout.fillWidth: true
                    Layout.maximumHeight: 140
                    visible: view.speakers.length > 0
                    implicitHeight: Math.min(140, speakerBox.implicitHeight + 2 * Theme.padCard)
                    radius: Theme.radiusLg
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.border
                    clip: true
                    ColumnLayout {
                        id: speakerBox
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: Theme.padCard
                        spacing: Theme.gapSm

                        Flow {
                            id: speakerRow
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            Repeater {
                                model: view.speakers
                                delegate: Rectangle {
                                    id: chip
                                    required property var modelData
                                    readonly property bool focused: view.focusKey === Number(modelData.key)
                                    readonly property string kind: String(modelData.kind || "voice")
                                    function commit() {
                                        var label = nameField.text.trim()
                                        if (label.length) bridge.renameTranscriptSpeaker(Number(modelData.key), label)
                                    }
                                    function cycleKind() {
                                        if (view.busyPhase)
                                            return
                                        bridge.setTranscriptSpeakerKind(
                                            Number(chip.modelData.key),
                                            view.nextSpeakerKind(chip.kind)
                                        )
                                    }
                                    width: Math.min(360, Math.max(250, nameField.implicitWidth + share.implicitWidth + kindBtn.implicitWidth + 86))
                                    implicitHeight: 38
                                    radius: Theme.radiusLg
                                    color: chip.focused ? Theme.fillHi : Theme.fill
                                    border.width: 1
                                    border.color: chip.focused ? Theme.borderHi : Theme.hairline
                                    Behavior on color { ColorAnimation { duration: Theme.fastMs } }

                                    MouseArea {
                                        anchors.fill: parent
                                        acceptedButtons: Qt.LeftButton
                                        onClicked: view.focusKey = chip.focused ? 0 : Number(chip.modelData.key)
                                        // Имя и вид правятся элементами поверх этой области.
                                        propagateComposedEvents: true
                                    }

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 10
                                        spacing: Theme.gapSm
                                        Rectangle {
                                            Layout.preferredWidth: 8
                                            Layout.preferredHeight: 8
                                            radius: 4
                                            color: Theme.speakerInk(chip.modelData.key)
                                        }
                                        TextField {
                                            id: nameField
                                            Layout.fillWidth: true
                                            text: String(chip.modelData.label || "")
                                            color: Theme.text
                                            font.pixelSize: Theme.fsLabel
                                            enabled: !view.busyPhase
                                            onActiveFocusChanged: if (!activeFocus) chip.commit()
                                            onEditingFinished: chip.commit()
                                            background: Item {}
                                        }
                                        PillButton {
                                            id: kindBtn
                                            text: view.speakerKindLabel(chip.kind)
                                            compact: true
                                            enabled: !view.busyPhase
                                            onClicked: chip.cycleKind()
                                            ToolTip.visible: hovered
                                            ToolTip.text: "Вид: Голос / Парень / Девушка. Своё имя не затирается."
                                        }
                                        Label {
                                            id: share
                                            text: view.phrases(chip.modelData.count) + " · "
                                                  + view.duration(chip.modelData.seconds)
                                            color: Theme.faint
                                            font.pixelSize: Theme.fsMicro
                                        }
                                    }
                                }
                            }
                        }

                        // Полоса голосов по всей записи: видно, кто и когда говорит.
                        SpeakerTracks {
                            Layout.fillWidth: true
                            visible: view.speakers.length > 0 && view.segs.length > 0
                            speakers: view.speakers
                            segments: view.segs
                            duration: view.total
                            focusKey: view.focusKey
                            mutedKeys: view.mutedKeys
                            soloKeys: view.soloKeys
                            onFocusRequested: function (key) { view.focusKey = key }
                            onMuteToggled: function (key) { view.toggleMuteKey(key) }
                            onSoloToggled: function (key) { view.toggleSoloKey(key) }
                            onSeekRequested: function (start, end, index) {
                                view.revealPhrase(index)
                                view.playPhraseAt(start, end, index)
                            }
                        }

                        Item {
                            id: timeline
                            Layout.fillWidth: true
                            implicitHeight: 26
                            visible: false

                            Rectangle {
                                anchors.fill: parent
                                radius: Theme.radiusSm
                                color: Theme.surface2
                                border.width: 1
                                border.color: Theme.hairline
                            }
                            Repeater {
                                model: view.segs
                                delegate: Rectangle {
                                    required property var modelData
                                    required property int index
                                    readonly property bool dimmed: view.focusKey > 0
                                                                   && Number(modelData.role) !== view.focusKey
                                    x: 3 + (timeline.width - 6) * Math.min(1, Number(modelData.start) / view.total)
                                    width: Math.max(2, (timeline.width - 6)
                                           * Math.min(1, (Number(modelData.end) - Number(modelData.start)) / view.total))
                                    y: 5
                                    height: parent.height - 10
                                    radius: 3
                                    color: Theme.speakerInk(modelData.role)
                                    opacity: dimmed ? 0.22 : 0.85
                                    Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }
                                    MouseArea {
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            view.revealPhrase(parent.index)
                                            view.playPhraseAt(parent.modelData.start, parent.modelData.end, parent.index)
                                        }
                                        ToolTip.visible: containsMouse
                                        ToolTip.text: view.timecode(parent.modelData.start) + " · "
                                                      + (parent.modelData.speaker || "голос не определён")
                                                      + " · воспроизвести"
                                    }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Label {
                                    Layout.fillWidth: true
                                    visible: view.engineNote.length > 0
                                    text: view.engineNote
                                    color: Theme.faint
                                    font.pixelSize: Theme.fsSmall
                                    elide: Text.ElideRight
                                }
                                // Подсказка про фильтр нужна ровно тогда, когда есть
                                // между кем выбирать, и мешает, когда фильтр уже стоит.
                                Label {
                                    Layout.fillWidth: true
                                    visible: view.focusKey === 0 && view.speakers.length > 1
                                    text: "Нажмите на голос, чтобы оставить в списке только его реплики, или на полосу - чтобы перейти к фразе и услышать её."
                                    color: Theme.faint
                                    font.pixelSize: Theme.fsSmall
                                    elide: Text.ElideRight
                                }
                                Label {
                                    Layout.fillWidth: true
                                    visible: view.focusKey > 0
                                    text: "Показаны реплики одного голоса: " + view.rows.length + " из " + view.segs.length + "."
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                }
                            }
                            PillButton {
                                text: "Показать всех"
                                compact: true
                                visible: view.focusKey > 0
                                onClicked: view.focusKey = 0
                            }
                        }
                    }
                }

                // Причина, по которой голоса не определились: текст всё равно есть.
                Label {
                    Layout.fillWidth: true
                    visible: view.speakers.length === 0 && view.engineNote.length > 0
                    text: view.engineNote
                    color: Theme.muted
                    font.pixelSize: Theme.fsSmall
                    wrapMode: Text.Wrap
                }


            }
        }

        // Низ: список фраз - отдельная панель, тянется ручкой SplitView.
        Item {
            SplitView.fillHeight: true
            SplitView.minimumHeight: 150
            clip: true
            ColumnLayout {
                anchors.centerIn: parent
                visible: view.segs.length === 0 && !view.file.length
                width: Math.min(parent.width - 80, 360)
                spacing: Theme.gapSm
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Готово к транскрибации"
                    color: Theme.text
                    font.pixelSize: Theme.fsLead
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: "Откройте или перетащите запись. Сверху появится плеер: можно сразу слушать весь файл. После расшифровки нажмите на фразу, чтобы услышать её."
                    color: Theme.muted
                    font.pixelSize: Theme.fsBody
                }
            }
            ColumnLayout {
                anchors.centerIn: parent
                visible: view.segs.length === 0 && view.file.length && !view.busyPhase
                width: Math.min(parent.width - 80, 360)
                spacing: Theme.gapSm
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Файл выбран"
                    color: Theme.text
                    font.pixelSize: Theme.fsLead
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: Theme.muted
                    font.pixelSize: Theme.fsBody
                    text: "Слушайте весь файл кнопкой ▶ в плеере выше. После расшифровки нажмите на фразу, чтобы услышать её отдельно."
                }
            }
            ListView {
                id: segList
                objectName: "segmentList"
                anchors.fill: parent
                model: view.rows
                spacing: Theme.gapSm
                clip: true
                visible: view.segs.length > 0
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 10 }
                header: Item {
                    width: segList.width
                    height: phraseHead.implicitHeight + Theme.gapSm
                    Label {
                        id: phraseHead
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        text: "Фразы · " + view.phrases(view.rows.length)
                              + (player.playing ? " · идут синхронно со звуком" : "")
                        color: Theme.muted
                        font.pixelSize: Theme.fsLabel
                        font.weight: Font.DemiBold
                    }
                }
                delegate: Rectangle {
                    id: segCard
                    required property var modelData
                    required property int index
                    readonly property string label: modelData.speaker || ""
                    readonly property real startSec: Number(modelData.start)
                    readonly property real endSec: Number(modelData.end)
                    readonly property int globalIndex: view.globalIndexOf(modelData)
                    readonly property bool editing: view.editingIndex >= 0
                        && segCard.globalIndex === view.editingIndex
                    // В полном списке index совпадает с глобальным; при фильтре
                    // подсветка markedIndex не ставится (как раньше).
                    readonly property bool playingNow: player.playing
                        && view.playIndex >= 0
                        && view.playIndex === segCard.globalIndex
                    readonly property bool marked: segCard.playingNow
                        || (view.focusKey === 0 && (view.markedIndex === index || view.playIndex === index))
                    width: ListView.view.width
                    implicitHeight: segBody.implicitHeight + 24
                    radius: Theme.radiusMd
                    color: segCard.playingNow
                           ? Theme.liveSurface
                           : (segCard.marked ? Theme.surface3 : Theme.surface2)
                    border.width: segCard.playingNow ? 2 : 1
                    border.color: segCard.playingNow
                                  ? Theme.liveBorder
                                  : (segCard.marked ? Theme.borderHi : Theme.border)
                    opacity: player.playing && !segCard.playingNow ? Theme.historyAlpha : 1
                    Behavior on color { ColorAnimation { duration: Theme.baseMs } }
                    Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }
                    Behavior on border.width { NumberAnimation { duration: Theme.fastMs } }

                    onEditingChanged: {
                        if (editing)
                            segCard.prepareEdit()
                    }

                    Component.onCompleted: {
                        if (editing)
                            segCard.prepareEdit()
                    }

                    function prepareEdit() {
                        phraseEdit.text = String(segCard.modelData.text || "")
                        speakerPick.currentIndex = segCard.speakerPickIndex()
                        Qt.callLater(function () {
                            if (segCard.editing)
                                phraseEdit.forceActiveFocus()
                        })
                    }

                    function replay() {
                        view.playPhraseAt(segCard.startSec, segCard.endSec,
                                          view.focusKey === 0 ? segCard.index : -1)
                    }

                    function speakerPickIndex() {
                        var current = String(segCard.label || "")
                        var model = speakerPick.model
                        for (var i = 0; i < model.length; ++i) {
                            if (String(model[i].value) === current)
                                return i
                        }
                        return 0
                    }

                    function beginEdit() {
                        if (view.busyPhase)
                            return
                        var gi = segCard.globalIndex
                        if (gi < 0)
                            return
                        view.editingIndex = gi
                    }

                    function savePhrase() {
                        var gi = segCard.globalIndex
                        if (gi < 0) {
                            view.editingIndex = -1
                            return
                        }
                        if (view.busyPhase) {
                            view.editingIndex = -1
                            return
                        }
                        var next = phraseEdit.text
                        if (String(next) !== String(segCard.modelData.text || ""))
                            bridge.editTranscriptSegment(gi, next)
                        view.editingIndex = -1
                    }

                    function applySpeaker(pickIndex) {
                        var gi = segCard.globalIndex
                        if (gi < 0 || view.busyPhase)
                            return
                        var model = speakerPick.model
                        if (pickIndex < 0 || pickIndex >= model.length)
                            return
                        var value = String(model[pickIndex].value || "")
                        if (value === String(segCard.label || ""))
                            return
                        // Сначала текст: смена автора обновляет модель и может
                        // пересобрать карточку до blur.
                        var next = phraseEdit.text
                        if (String(next) !== String(segCard.modelData.text || ""))
                            bridge.editTranscriptSegment(gi, next)
                        bridge.setTranscriptSegmentSpeaker(gi, value)
                        view.editingIndex = gi
                    }

                    RowLayout {
                        id: segBody
                        anchors.fill: parent
                        anchors.margins: 11
                        spacing: 10
                        Rectangle {
                            Layout.preferredWidth: segCard.playingNow ? 7 : 4
                            Layout.fillHeight: true
                            radius: 2
                            color: segCard.playingNow ? Theme.liveBar : Theme.speakerInk(segCard.modelData.role)
                            Behavior on Layout.preferredWidth { NumberAnimation { duration: Theme.fastMs } }
                        }
                        // Клик по тексту/таймкоду - воспроизвести фразу.
                        // Отдельный MouseArea, чтобы не перехватывать кнопки и поля.
                        Item {
                            Layout.fillWidth: true
                            implicitHeight: phraseCol.implicitHeight
                            ColumnLayout {
                                id: phraseCol
                                width: parent.width
                                spacing: 4
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.gapSm
                                    Label {
                                        text: view.timecode(segCard.startSec) + " - " + view.timecode(segCard.endSec)
                                        color: Theme.muted
                                        font.family: Theme.monoFamily
                                        font.pixelSize: Theme.fsSmall
                                    }
                                    Item { Layout.fillWidth: true }
                                    Label {
                                        visible: !segCard.editing && segCard.label.length > 0
                                        text: segCard.label
                                        color: Theme.speakerInk(segCard.modelData.role)
                                        font.pixelSize: Theme.fsSmall
                                        font.weight: Font.DemiBold
                                    }
                                    Label {
                                        visible: view.confidenceLabel(segCard.modelData).length > 0
                                        text: view.confidenceLabel(segCard.modelData)
                                        color: view.confidenceTint(segCard.modelData)
                                        font.pixelSize: Theme.fsMicro
                                        font.family: Theme.monoFamily
                                    }
                                    Label {
                                        visible: Boolean(segCard.modelData.reviewed)
                                        text: "проверено"
                                        color: Theme.faint
                                        font.pixelSize: Theme.fsMicro
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    visible: !segCard.editing
                                    text: segCard.modelData.text || "-"
                                    color: Theme.text
                                    font.pixelSize: segCard.playingNow ? Theme.fsCompact : Theme.fsBody
                                    font.weight: segCard.playingNow ? Font.Bold : Font.Normal
                                    wrapMode: Text.Wrap
                                    textFormat: Text.PlainText
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    visible: segCard.editing
                                    spacing: Theme.gapSm
                                    TextArea {
                                        id: phraseEdit
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: Math.max(56, contentHeight + 16)
                                        wrapMode: TextEdit.Wrap
                                        color: Theme.text
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fsBody
                                        selectByMouse: true
                                        selectionColor: Theme.fillPress
                                        selectedTextColor: Theme.text
                                        placeholderText: "Текст фразы"
                                        placeholderTextColor: Theme.faint
                                        enabled: !view.busyPhase
                                        Keys.onReturnPressed: function (event) {
                                            if (event.modifiers & Qt.ShiftModifier) {
                                                event.accepted = false
                                                return
                                            }
                                            segCard.savePhrase()
                                            event.accepted = true
                                        }
                                        Keys.onEnterPressed: function (event) {
                                            if (event.modifiers & Qt.ShiftModifier) {
                                                event.accepted = false
                                                return
                                            }
                                            segCard.savePhrase()
                                            event.accepted = true
                                        }
                                        onActiveFocusChanged: {
                                            if (activeFocus || !segCard.editing)
                                                return
                                            // Откладываем: фокус мог уйти на Dropdown или «Готово».
                                            Qt.callLater(function () {
                                                if (!segCard.editing)
                                                    return
                                                if (phraseEdit.activeFocus
                                                        || speakerPick.activeFocus
                                                        || doneBtn.activeFocus
                                                        || speakerPick.popup.visible)
                                                    return
                                                segCard.savePhrase()
                                            })
                                        }
                                        background: Rectangle {
                                            radius: Theme.radiusSm
                                            color: Theme.fill
                                            border.width: 1
                                            border.color: phraseEdit.activeFocus ? Theme.borderHi : Theme.hairline
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Theme.gapSm
                                        Dropdown {
                                            id: speakerPick
                                            Layout.fillWidth: true
                                            Layout.preferredWidth: 160
                                            enabled: !view.busyPhase
                                            model: view.speakerPickModel()
                                            textRole: "label"
                                            currentIndex: segCard.speakerPickIndex()
                                            onActivated: function (index) {
                                                segCard.applySpeaker(index)
                                            }
                                            ToolTip.visible: hovered
                                            ToolTip.text: "Кто произнёс эту фразу"
                                        }
                                        PillButton {
                                            id: doneBtn
                                            text: "Готово"
                                            compact: true
                                            primary: true
                                            enabled: !view.busyPhase
                                            onClicked: segCard.savePhrase()
                                            ToolTip.visible: hovered
                                            ToolTip.text: "Сохранить текст фразы"
                                        }
                                    }
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: !segCard.editing
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: segCard.replay()
                                ToolTip.visible: containsMouse && !segCard.editing
                                ToolTip.text: "Воспроизвести фразу"
                            }
                        }
                        IconButton {
                            iconName: "edit"
                            Layout.alignment: Qt.AlignVCenter
                            enabled: !view.busyPhase
                            onClicked: {
                                if (segCard.editing)
                                    segCard.savePhrase()
                                else
                                    segCard.beginEdit()
                            }
                            ToolTip.visible: hovered
                            ToolTip.text: segCard.editing
                                          ? "Сохранить правку"
                                          : "Править слова или автора"
                        }
                        IconButton {
                            iconName: "media"
                            Layout.alignment: Qt.AlignVCenter
                            onClicked: segCard.replay()
                            ToolTip.visible: hovered
                            ToolTip.text: "Воспроизвести фразу"
                        }
                        PillButton {
                            text: "✂"
                            compact: true
                            Layout.alignment: Qt.AlignVCenter
                            enabled: !view.busyPhase
                            onClicked: {
                                var mid = (segCard.startSec + segCard.endSec) / 2
                                bridge.splitTranscriptSegment(segCard.globalIndex, mid)
                            }
                            ToolTip.visible: hovered
                            ToolTip.text: "Разрезать фразу пополам"
                        }
                        PillButton {
                            text: "＋"
                            compact: true
                            Layout.alignment: Qt.AlignVCenter
                            enabled: !view.busyPhase
                                     && segCard.globalIndex >= 0
                                     && segCard.globalIndex < view.segs.length - 1
                            onClicked: bridge.mergeTranscriptSegment(segCard.globalIndex)
                            ToolTip.visible: hovered
                            ToolTip.text: "Склеить со следующей"
                        }
                        PillButton {
                            text: Boolean(segCard.modelData.reviewed) ? "✓" : "?"
                            compact: true
                            Layout.alignment: Qt.AlignVCenter
                            enabled: !view.busyPhase
                            onClicked: bridge.markTranscriptReviewed(
                                segCard.globalIndex,
                                !Boolean(segCard.modelData.reviewed)
                            )
                            ToolTip.visible: hovered
                            ToolTip.text: "Отметить как проверенную"
                        }
                        PillButton {
                            text: "AI"
                            compact: true
                            Layout.alignment: Qt.AlignVCenter
                            enabled: !view.busyPhase
                            onClicked: bridge.openTranscriptPhraseInAssistant(
                                "Разбери фразу на " + view.timecode(segCard.startSec)
                                + ": " + String(segCard.modelData.text || "")
                            )
                            ToolTip.visible: hovered
                            ToolTip.text: "Открыть в ассистенте с этой фразой"
                        }
                    }
                }
            }

            // Подсказка под готовым списком - только когда есть фразы и не busy.
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Theme.gapSm
                visible: view.segs.length > 0 && view.phase === "done" && !view.busyPhase
                         && view.focusKey === 0 && view.playIndex < 0 && view.markedIndex < 0
                text: "▶ слушает весь файл · клик по фразе - только её · Править - слова или автор · Сохранить - формат и фильтры · Пробел - пауза"
                color: Theme.faint
                font.pixelSize: Theme.fsMicro
            }
        }
    }
    }
}
