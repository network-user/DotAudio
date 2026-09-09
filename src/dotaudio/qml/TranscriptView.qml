import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

// Транскрибация: файл, распознавание, плеер и список фраз.
// Модель и голоса выбираются здесь коротко; остальное - в настройках.
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

    property int focusKey: 0
    property int markedIndex: -1
    property int playIndex: -1
    property int editingIndex: -1

    readonly property var rows: {
        var list = view.segs || []
        if (view.focusKey <= 0)
            return list
        var out = []
        for (var i = 0; i < list.length; ++i) {
            if (Number(list[i].role) === view.focusKey)
                out.push(list[i])
        }
        return out
    }
    readonly property bool hasMedia: mediaUrl.length > 0 || view.file.length > 0
    readonly property var whisperModels: [
        { key: "tiny", label: "tiny" },
        { key: "base", label: "base" },
        { key: "small", label: "small" },
        { key: "medium", label: "medium" },
        { key: "large-v3", label: "large-v3" },
        { key: "turbo", label: "turbo" }
    ]
    readonly property var exportFormats: [
        { key: "txt", label: "Текст" },
        { key: "md", label: "Markdown" },
        { key: "srt", label: "SRT" },
        { key: "vtt", label: "VTT" },
        { key: "json", label: "JSON" }
    ]
    readonly property string shortName: {
        var path = String(view.file || "")
        if (!path.length)
            return ""
        var slash = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"))
        return slash >= 0 ? path.slice(slash + 1) : path
    }

    Component.onCompleted: bridge.refreshDiarizeStatus()

    function timecode(seconds) {
        var total = Math.max(0, Math.round(Number(seconds) * 1000))
        var hours = Math.floor(total / 3600000)
        total -= hours * 3600000
        var minutes = Math.floor(total / 60000)
        total -= minutes * 60000
        var rest = (total / 1000).toFixed(1)
        if (rest.length < 4)
            rest = "0" + rest
        return (hours > 0 ? (hours < 10 ? "0" : "") + hours + ":" : "")
               + (minutes < 10 ? "0" : "") + minutes + ":" + rest
    }

    function phrases(count) {
        var value = Number(count)
        var tail = Math.abs(value) % 100
        var last = tail % 10
        if (tail > 10 && tail < 20)
            return value + " реплик"
        if (last === 1)
            return value + " реплика"
        if (last >= 2 && last <= 4)
            return value + " реплики"
        return value + " реплик"
    }

    function applyPendingSeek() {
        if (bridge.pendingSeekMs < 0 || player.duration <= 0)
            return
        player.seekSeconds(bridge.pendingSeekMs / 1000)
        bridge.clearPendingSeek()
    }

    function engineIndex() {
        var key = String(view.voices.engine || "off")
        for (var i = 0; i < view.engines.length; ++i)
            if (String(view.engines[i].key) === key)
                return i
        return 0
    }

    function whisperModelIndex() {
        var key = String(bridge.settings.model || "small")
        for (var i = 0; i < view.whisperModels.length; ++i)
            if (String(view.whisperModels[i].key) === key)
                return i
        return 2
    }

    function selectWhisperModel(index) {
        if (view.busyPhase || index < 0 || index >= view.whisperModels.length)
            return
        var key = String(view.whisperModels[index].key)
        if (key === String(bridge.settings.model || ""))
            return
        bridge.setSetting("model", key)
        var lib = bridge.modelLibrary || []
        var ready = false
        for (var i = 0; i < lib.length; ++i) {
            if (String(lib[i].model) === key && Boolean(lib[i].ready)) {
                ready = true
                break
            }
        }
        if (!ready && !bridge.modelPreparing)
            bridge.prepareSelectedModel()
    }

    function busyMessage() {
        if (view.stage === "voices")
            return "Слова готовы. Определяем, кто говорит…"
        return "Распознаём речь и расставляем таймкоды."
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

    function speakerPickModel() {
        var items = [{ label: "без метки", value: "" }]
        for (var i = 0; i < view.speakers.length; ++i) {
            var sp = view.speakers[i]
            items.push({ label: String(sp.label || ("Голос " + sp.key)), value: String(sp.label || "") })
        }
        return items
    }

    function playPhraseAt(startSec, endSec, globalIndex) {
        if (globalIndex !== undefined && globalIndex >= 0 && view.focusKey === 0) {
            view.markedIndex = globalIndex
            markTimer.restart()
        }
        if (view.hasMedia)
            player.playPhrase(Number(startSec), Number(endSec))
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

    function exportNow(fmt) {
        var times = fmt === "srt" || fmt === "vtt" || fmt === "json" || fmt === "md"
        bridge.transcriptExport(fmt, times, true, view.focusKey)
        exportMenu.close()
    }

    onBusyPhaseChanged: {
        if (busyPhase)
            view.editingIndex = -1
    }

    Timer {
        id: markTimer
        interval: 1600
        onTriggered: view.markedIndex = -1
    }

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

    Connections {
        target: bridge
        function onChanged() { view.applyPendingSeek() }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gapSm

        Rectangle {
            id: transcriptHead
            objectName: "transcriptHead"
            Layout.fillWidth: true
            implicitHeight: headCol.implicitHeight + 2 * Theme.padCard
            radius: Theme.radiusLg
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            ColumnLayout {
                id: headCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.padCard
                spacing: Theme.gapSm

                Label {
                    Layout.fillWidth: true
                    text: view.shortName.length ? view.shortName : "Файл не выбран"
                    color: Theme.text
                    font.pixelSize: Theme.fsTitle
                    font.weight: Font.DemiBold
                    elide: Text.ElideMiddle
                }
                Label {
                    visible: String(bridge.transcribeState.origin || "") === "live"
                             && !view.hasMedia && !view.busyPhase
                    Layout.fillWidth: true
                    text: "Запись Live · звук удалён после обработки"
                    color: Theme.muted
                    font.pixelSize: Theme.fsLabel
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    PillButton {
                        text: "Открыть"
                        enabled: !view.busyPhase
                        onClicked: bridge.pickTranscriptFile()
                    }
                    PillButton {
                        text: view.busyPhase ? "Стоп" : "Расшифровать"
                        primary: !view.busyPhase
                        enabled: view.busyPhase || view.hasMedia
                        onClicked: view.busyPhase ? bridge.stopTranscript() : bridge.runTranscript()
                    }
                    PillButton {
                        id: saveBtn
                        text: "Сохранить"
                        enabled: view.segs.length > 0 && !view.busyPhase
                        onClicked: exportMenu.open()
                    }
                    PillButton {
                        text: "Очистить"
                        enabled: (view.file.length > 0 || view.segs.length > 0) && !view.busyPhase
                        onClicked: bridge.clearTranscript()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    Label {
                        text: "Модель"
                        color: Theme.muted
                        font.pixelSize: Theme.fsLabel
                    }
                    Dropdown {
                        Layout.preferredWidth: 140
                        enabled: !view.busyPhase && !bridge.modelPreparing
                        model: view.whisperModels
                        textRole: "label"
                        currentIndex: view.whisperModelIndex()
                        onActivated: function (index) { view.selectWhisperModel(index) }
                    }
                    Label {
                        text: "Голоса"
                        color: Theme.muted
                        font.pixelSize: Theme.fsLabel
                    }
                    Dropdown {
                        Layout.preferredWidth: 180
                        enabled: !view.busyPhase
                        model: view.engines
                        textRole: "label"
                        currentIndex: view.engineIndex()
                        onActivated: function (index) {
                            bridge.setDiarizeEngine(String(view.engines[index].key))
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        visible: view.engineNote.length > 0
                        Layout.fillWidth: true
                        text: view.engineNote
                        color: Theme.faint
                        font.pixelSize: Theme.fsSmall
                        elide: Text.ElideRight
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

        TranscriptPlayer {
            id: player
            Layout.fillWidth: true
            compact: true
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

        Flow {
            Layout.fillWidth: true
            Layout.maximumHeight: 76
            clip: true
            visible: view.speakers.length > 0
            spacing: Theme.gapSm
            Repeater {
                model: view.speakers
                delegate: Rectangle {
                    id: chip
                    required property var modelData
                    readonly property bool focused: view.focusKey === Number(modelData.key)
                    implicitHeight: 32
                    implicitWidth: Math.min(280, Math.max(120, nameField.implicitWidth + 36))
                    radius: Theme.radiusLg
                    color: chip.focused ? Theme.fillHi : Theme.fill
                    border.width: 1
                    border.color: chip.focused ? Theme.borderHi : Theme.hairline
                    MouseArea {
                        anchors.fill: parent
                        onClicked: view.focusKey = chip.focused ? 0 : Number(chip.modelData.key)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
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
                            onEditingFinished: {
                                var label = text.trim()
                                if (label.length)
                                    bridge.renameTranscriptSpeaker(Number(chip.modelData.key), label)
                            }
                            background: Item {}
                        }
                    }
                }
            }
            PillButton {
                text: "Все голоса"
                compact: true
                visible: view.focusKey > 0
                onClicked: view.focusKey = 0
            }
        }

        Item {
            id: phrasePane
            objectName: "phrasePane"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 160
            clip: true

            ColumnLayout {
                anchors.centerIn: parent
                visible: view.segs.length === 0 && !view.busyPhase
                width: Math.min(parent.width - 80, 360)
                spacing: Theme.gapSm
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: view.file.length ? "Файл выбран" : "Готово к расшифровке"
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
                    text: view.file.length
                          ? "Нажмите «Расшифровать». Пока идёт распознавание, файл уже можно слушать."
                          : "Откройте или перетащите запись. После расшифровки клик по фразе воспроизводит её."
                }
            }

            ListView {
                id: segList
                objectName: "segmentList"
                anchors.fill: parent
                anchors.rightMargin: 2
                model: view.rows
                spacing: Theme.gapSm
                clip: true
                visible: view.segs.length > 0
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.VerticalFlick
                cacheBuffer: 800
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    implicitWidth: 8
                }
                footer: Item {
                    width: 1
                    height: Theme.gapLg
                }
                header: Item {
                    width: segList.width
                    height: phraseHead.implicitHeight + Theme.gapSm
                    Label {
                        id: phraseHead
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        text: view.phrases(view.rows.length)
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
                    readonly property bool playingNow: player.playing
                        && view.playIndex >= 0
                        && view.playIndex === segCard.globalIndex
                    readonly property bool marked: segCard.playingNow
                        || (view.focusKey === 0 && (view.markedIndex === index || view.playIndex === index))
                    width: ListView.view.width
                    implicitHeight: segBody.implicitHeight + 22
                    height: implicitHeight
                    radius: Theme.radiusMd
                    color: segCard.playingNow
                           ? Theme.liveSurface
                           : (segCard.marked ? Theme.surface3 : Theme.surface2)
                    border.width: segCard.playingNow ? 2 : 1
                    border.color: segCard.playingNow
                                  ? Theme.liveBorder
                                  : (segCard.marked ? Theme.borderHi : Theme.border)

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
                        if (gi < 0 || view.busyPhase) {
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
                        var next = phraseEdit.text
                        if (String(next) !== String(segCard.modelData.text || ""))
                            bridge.editTranscriptSegment(gi, next)
                        bridge.setTranscriptSegmentSpeaker(gi, value)
                        view.editingIndex = gi
                    }

                    RowLayout {
                        id: segBody
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 11
                        spacing: 10
                        Rectangle {
                            Layout.preferredWidth: 4
                            Layout.fillHeight: true
                            radius: 2
                            color: segCard.playingNow ? Theme.liveBar : Theme.speakerInk(segCard.modelData.role)
                        }
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
                                        text: view.timecode(segCard.startSec)
                                        color: Theme.muted
                                        font.family: Theme.monoFamily
                                        font.pixelSize: Theme.fsSmall
                                    }
                                    Label {
                                        visible: !segCard.editing && segCard.label.length > 0
                                        text: segCard.label
                                        color: Theme.speakerInk(segCard.modelData.role)
                                        font.pixelSize: Theme.fsSmall
                                        font.weight: Font.DemiBold
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    visible: !segCard.editing
                                    text: segCard.modelData.text || "-"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsBody
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
                                            enabled: !view.busyPhase
                                            model: view.speakerPickModel()
                                            textRole: "label"
                                            currentIndex: segCard.speakerPickIndex()
                                            onActivated: function (index) { segCard.applySpeaker(index) }
                                        }
                                        PillButton {
                                            id: doneBtn
                                            text: "Готово"
                                            compact: true
                                            primary: true
                                            enabled: !view.busyPhase
                                            onClicked: segCard.savePhrase()
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
                            ToolTip.text: segCard.editing ? "Сохранить" : "Править"
                        }
                    }
                }
            }
        }
    }

    Popup {
        id: exportMenu
        parent: view
        x: {
            var pos = saveBtn.mapToItem(view, 0, 0)
            return Math.max(8, Math.min(pos.x, view.width - implicitWidth - 8))
        }
        y: {
            var below = saveBtn.mapToItem(view, 0, saveBtn.height).y + 6
            if (below + implicitHeight <= view.height - 8)
                return below
            return Math.max(8, saveBtn.mapToItem(view, 0, 0).y - implicitHeight - 6)
        }
        padding: 6
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        implicitWidth: 168
        background: Rectangle {
            radius: Theme.radiusMd
            color: Theme.surface
            border.width: 1
            border.color: Theme.borderHi
        }
        contentItem: ColumnLayout {
            spacing: 2
            Label {
                Layout.fillWidth: true
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                Layout.topMargin: 4
                Layout.bottomMargin: 2
                text: "Формат"
                color: Theme.muted
                font.pixelSize: Theme.fsMicro
                font.weight: Font.DemiBold
            }
            Repeater {
                model: view.exportFormats
                delegate: Item {
                    id: fmtRow
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 32
                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusSm
                        color: fmtHover.containsMouse ? Theme.fill : "transparent"
                    }
                    Label {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        text: fmtRow.modelData.label
                        color: Theme.text
                        font.pixelSize: Theme.fsLabel
                        verticalAlignment: Text.AlignVCenter
                    }
                    MouseArea {
                        id: fmtHover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: view.exportNow(String(fmtRow.modelData.key))
                    }
                }
            }
        }
    }
}
