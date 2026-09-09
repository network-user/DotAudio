import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Окно сохранения расшифровки: слева параметры файла, справа предпросмотр
// того же текста, который уйдёт на диск. Предпросмотр считает контроллер
// (bridge.transcriptExportInfo) теми же правилами, что и сохранение, поэтому
// показанное и сохранённое не могут разойтись.
//
// Каталог форматов и содержимое списков приходят из transcript_pro.py, здесь
// они не дублируются: новый формат появляется в окне сам.
Popup {
    id: dialog

    // Голос, выбранный фильтром на странице; 0 - фильтра нет.
    property int focusKey: 0

    readonly property var formats: bridge.transcriptExportFormats || []
    readonly property var choices: bridge.transcriptExportChoices || ({})
    readonly property bool reduceMotion: (bridge && bridge.settings)
                                        ? Boolean(bridge.settings.reduce_motion) : false

    property int formatIndex: 0
    property bool includeTimestamps: true
    property bool includeSpeakers: true
    property bool includeConfidence: false
    property bool includeReviewFlags: false
    property bool includeHeader: false
    property bool includePhraseNumbers: false
    property bool includeDuration: false
    property bool speakerOnce: false
    property bool mergeTurns: false
    property bool blankBetween: false
    property bool skipEmpty: true
    property bool onlyFlagged: false
    property bool focusedOnly: false
    property bool csvBom: true
    property string timePrecision: "seconds"
    property string timeMode: "range"
    property string timeHours: "auto"
    property string fieldSeparator: "space"
    property string rangeSeparator: "dash"
    property string speakerStyle: "bracket"
    property string csvDelimiter: "comma"
    property int subtitleChars: 42
    property real subtitleSeconds: 6.0

    property var info: ({})

    readonly property var formatMeta: dialog.formats.length > 0
        ? dialog.formats[Math.max(0, Math.min(dialog.formatIndex, dialog.formats.length - 1))]
        : ({ key: "txt", label: "TXT", hint: "", times: "optional" })
    readonly property string formatKey: String(dialog.formatMeta.key || "txt")
    readonly property bool timesLocked: String(dialog.formatMeta.times || "optional") === "locked"
    readonly property bool precisionLocked: Boolean(dialog.formatMeta.precision)
    readonly property bool timesOn: dialog.timesLocked || dialog.includeTimestamps

    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape
    anchors.centerIn: Overlay.overlay
    width: Math.min(1060, Overlay.overlay ? Overlay.overlay.width - 64 : 1060)
    height: Math.min(700, Overlay.overlay ? Overlay.overlay.height - 48 : 700)

    Overlay.modal: Rectangle { color: Theme.scrim }

    background: Rectangle {
        radius: Theme.radiusXl
        color: Theme.surface
        border.width: 1
        border.color: Theme.borderHi
    }

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: dialog.reduceMotion ? 0 : Theme.contentMs }
        NumberAnimation {
            property: "scale"
            from: 0.97
            to: 1
            duration: dialog.reduceMotion ? 0 : Theme.baseMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; to: 0; duration: dialog.reduceMotion ? 0 : Theme.fastMs }
    }

    // Параметры и предпросмотр готовятся до появления окна: иначе первый кадр
    // показывает пустое поле, пока идёт анимация открытия.
    onAboutToShow: {
        dialog.loadSettings()
        dialog.refresh()
    }

    function indexOfKey(list, key) {
        var want = String(key || "")
        for (var i = 0; i < (list || []).length; ++i)
            if (String(list[i].key) === want)
                return i
        return 0
    }

    function choiceModel(name) {
        return dialog.choices[name] || []
    }

    function choiceKey(name, index) {
        var list = dialog.choiceModel(name)
        if (index < 0 || index >= list.length)
            return ""
        return String(list[index].key)
    }

    function loadSettings() {
        var s = bridge.settings || {}
        dialog.formatIndex = dialog.indexOfKey(dialog.formats, s.export_format || "txt")
        dialog.includeTimestamps = Boolean(s.export_timestamps)
        dialog.includeSpeakers = s.export_speakers === undefined ? true : Boolean(s.export_speakers)
        dialog.includeConfidence = Boolean(s.export_confidence)
        dialog.includeReviewFlags = Boolean(s.export_review_flags)
        dialog.includeHeader = Boolean(s.export_header)
        dialog.includePhraseNumbers = Boolean(s.export_phrase_numbers)
        dialog.includeDuration = Boolean(s.export_duration)
        dialog.speakerOnce = Boolean(s.export_speaker_once)
        dialog.mergeTurns = Boolean(s.export_merge_turns)
        dialog.blankBetween = Boolean(s.export_blank_between)
        dialog.skipEmpty = s.export_skip_empty === undefined ? true : Boolean(s.export_skip_empty)
        dialog.onlyFlagged = Boolean(s.export_flagged_only)
        dialog.csvBom = s.export_csv_bom === undefined ? true : Boolean(s.export_csv_bom)
        dialog.timePrecision = String(s.export_time_precision || "seconds")
        dialog.timeMode = String(s.export_time_mode || "range")
        dialog.timeHours = String(s.export_time_hours || "auto")
        dialog.fieldSeparator = String(s.export_field_separator || "space")
        dialog.rangeSeparator = String(s.export_range_separator || "dash")
        dialog.speakerStyle = String(s.export_speaker_style || "bracket")
        dialog.csvDelimiter = String(s.export_csv_delimiter || "comma")
        dialog.subtitleChars = Number(s.export_subtitle_chars || 42)
        dialog.subtitleSeconds = Number(s.export_subtitle_seconds || 6.0)
        if (dialog.focusKey <= 0)
            dialog.focusedOnly = false
    }

    function options() {
        return {
            format: dialog.formatKey,
            include_timestamps: dialog.timesOn,
            include_speakers: dialog.includeSpeakers,
            include_confidence: dialog.includeConfidence,
            include_review_flags: dialog.includeReviewFlags,
            include_header: dialog.includeHeader,
            include_phrase_numbers: dialog.includePhraseNumbers,
            include_duration: dialog.includeDuration,
            speaker_once: dialog.speakerOnce,
            merge_turns: dialog.mergeTurns,
            blank_between: dialog.blankBetween,
            skip_empty: dialog.skipEmpty,
            only_flagged: dialog.onlyFlagged,
            csv_bom: dialog.csvBom,
            time_precision: dialog.timePrecision,
            time_mode: dialog.timeMode,
            time_hours: dialog.timeHours,
            field_separator: dialog.fieldSeparator,
            range_separator: dialog.rangeSeparator,
            speaker_style: dialog.speakerStyle,
            csv_delimiter: dialog.csvDelimiter,
            subtitle_max_chars: dialog.subtitleChars,
            subtitle_max_duration: dialog.subtitleSeconds,
            speaker_key: dialog.focusedOnly ? dialog.focusKey : 0,
            preview_lines: 200
        }
    }

    // Предпросмотр считается в контроллере, поэтому частые правки параметров
    // собираются в один вызов, а не пересчитывают файл на каждый переключатель.
    function refresh() {
        previewTimer.restart()
    }

    function phrasesLabel(count) {
        var value = Number(count)
        var tail = Math.abs(value) % 100
        var last = tail % 10
        if (tail > 10 && tail < 20) return value + " фраз"
        if (last === 1) return value + " фраза"
        if (last >= 2 && last <= 4) return value + " фразы"
        return value + " фраз"
    }

    Timer {
        id: previewTimer
        interval: 60
        onTriggered: dialog.info = bridge.transcriptExportInfo(dialog.options()) || ({})
    }

    // Шаблон = набор параметров под задачу. Дальше их можно править вручную.
    function applyTemplate(name) {
        dialog.includeConfidence = false
        dialog.includeReviewFlags = false
        dialog.includeDuration = false
        dialog.blankBetween = false
        dialog.mergeTurns = false
        dialog.speakerOnce = false
        dialog.includeHeader = false
        dialog.includePhraseNumbers = false
        if (name === "plain") {
            dialog.formatIndex = dialog.indexOfKey(dialog.formats, "txt")
            dialog.includeTimestamps = false
            dialog.includeSpeakers = false
        } else if (name === "line") {
            dialog.formatIndex = dialog.indexOfKey(dialog.formats, "line")
            dialog.includeTimestamps = true
            dialog.includeSpeakers = true
            dialog.timePrecision = "seconds"
            dialog.timeMode = "range"
            dialog.timeHours = "auto"
            dialog.rangeSeparator = "dash"
            dialog.fieldSeparator = "space"
            dialog.speakerStyle = "bracket"
        } else if (name === "compact") {
            dialog.formatIndex = dialog.indexOfKey(dialog.formats, "line")
            dialog.includeTimestamps = true
            dialog.includeSpeakers = true
            dialog.timePrecision = "seconds"
            dialog.timeMode = "start"
            dialog.fieldSeparator = "colon"
            dialog.speakerStyle = "plain"
        } else if (name === "protocol") {
            dialog.formatIndex = dialog.indexOfKey(dialog.formats, "txt")
            dialog.includeTimestamps = true
            dialog.includeSpeakers = true
            dialog.includeHeader = true
            dialog.includePhraseNumbers = true
            dialog.mergeTurns = true
            dialog.timePrecision = "seconds"
        } else if (name === "subtitles") {
            dialog.formatIndex = dialog.indexOfKey(dialog.formats, "srt")
            dialog.includeSpeakers = false
        } else if (name === "table") {
            dialog.formatIndex = dialog.indexOfKey(dialog.formats, "csv")
            dialog.includeTimestamps = true
            dialog.includeSpeakers = true
            dialog.includeHeader = true
            dialog.includePhraseNumbers = true
            dialog.includeConfidence = true
            dialog.timePrecision = "seconds"
        } else if (name === "data") {
            dialog.formatIndex = dialog.indexOfKey(dialog.formats, "json")
            dialog.includeTimestamps = true
            dialog.includeSpeakers = true
            dialog.includeConfidence = true
            dialog.timePrecision = "millis"
        }
        dialog.refresh()
    }

    // Подпись группы параметров.
    component Section: ColumnLayout {
        id: section
        property string title: ""
        Layout.fillWidth: true
        spacing: Theme.gapXs
        Label {
            Layout.topMargin: Theme.gapXs
            text: section.title
            color: Theme.muted
            font.pixelSize: Theme.fsMicro
            font.weight: Font.DemiBold
        }
    }

    // Строка «подпись - элемент управления» с общей шириной подписи.
    component OptionRow: RowLayout {
        id: optionRow
        property string label: ""
        Layout.fillWidth: true
        spacing: Theme.gapSm
        Label {
            Layout.preferredWidth: 116
            text: optionRow.label
            color: Theme.muted
            font.pixelSize: Theme.fsLabel
            wrapMode: Text.Wrap
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.gapXl
        spacing: Theme.gapMd

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    text: "Сохранить расшифровку"
                    color: Theme.text
                    font.pixelSize: Theme.fsSection
                    font.weight: Font.DemiBold
                }
                Label {
                    Layout.fillWidth: true
                    text: "Слева вид файла, справа он же целиком. На диск уйдёт именно этот текст."
                    color: Theme.muted
                    font.pixelSize: Theme.fsSmall
                    wrapMode: Text.Wrap
                }
            }
            IconButton {
                iconName: "close"
                ToolTip.visible: hovered
                ToolTip.text: "Закрыть без сохранения"
                onClicked: dialog.close()
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: Theme.gapXs
            Repeater {
                model: [
                    { key: "plain", label: "Только текст" },
                    { key: "line", label: "Время, голос, текст" },
                    { key: "compact", label: "Одна строка через двоеточие" },
                    { key: "protocol", label: "Протокол с шапкой" },
                    { key: "subtitles", label: "Субтитры" },
                    { key: "table", label: "Таблица" },
                    { key: "data", label: "Данные JSON" }
                ]
                delegate: PillButton {
                    required property var modelData
                    text: modelData.label
                    compact: true
                    onClicked: dialog.applyTemplate(String(modelData.key))
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.gapLg

            // Параметры файла.
            ScrollView {
                Layout.preferredWidth: 420
                Layout.fillHeight: true
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    width: parent.width - Theme.gapMd
                    spacing: Theme.gapXs

                    OptionRow {
                        label: "Формат"
                        Dropdown {
                            Layout.fillWidth: true
                            model: dialog.formats
                            textRole: "label"
                            currentIndex: dialog.formatIndex
                            onActivated: function (index) {
                                dialog.formatIndex = index
                                dialog.refresh()
                            }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        Layout.leftMargin: 116 + Theme.gapSm
                        text: String(dialog.formatMeta.hint || "")
                        color: Theme.faint
                        font.pixelSize: Theme.fsMicro
                        wrapMode: Text.Wrap
                    }

                    Section { title: "ВРЕМЯ" }
                    ToggleSwitch {
                        text: dialog.timesLocked ? "Таймкоды (формат без них не существует)" : "Таймкоды в файле"
                        checked: dialog.timesOn
                        enabled: !dialog.timesLocked
                        onToggled: {
                            dialog.includeTimestamps = checked
                            dialog.refresh()
                        }
                    }
                    OptionRow {
                        label: "Точность"
                        Dropdown {
                            Layout.fillWidth: true
                            enabled: dialog.timesOn && !dialog.precisionLocked
                            model: dialog.choiceModel("time_precision")
                            textRole: "label"
                            currentIndex: dialog.indexOfKey(dialog.choiceModel("time_precision"),
                                                            dialog.precisionLocked
                                                            ? String(dialog.formatMeta.precision)
                                                            : dialog.timePrecision)
                            onActivated: function (index) {
                                dialog.timePrecision = dialog.choiceKey("time_precision", index)
                                dialog.refresh()
                            }
                        }
                    }
                    OptionRow {
                        label: "Отметка"
                        // У субтитров начало и конец заданы форматом: строка
                        // без выбора только путала бы.
                        visible: !dialog.timesLocked
                        Dropdown {
                            Layout.fillWidth: true
                            enabled: dialog.timesOn
                            model: dialog.choiceModel("time_mode")
                            textRole: "label"
                            currentIndex: dialog.indexOfKey(dialog.choiceModel("time_mode"), dialog.timeMode)
                            onActivated: function (index) {
                                dialog.timeMode = dialog.choiceKey("time_mode", index)
                                dialog.refresh()
                            }
                        }
                    }
                    OptionRow {
                        label: "Часы"
                        visible: !dialog.timesLocked
                        Dropdown {
                            Layout.fillWidth: true
                            enabled: dialog.timesOn
                            model: dialog.choiceModel("time_hours")
                            textRole: "label"
                            currentIndex: dialog.indexOfKey(dialog.choiceModel("time_hours"), dialog.timeHours)
                            onActivated: function (index) {
                                dialog.timeHours = dialog.choiceKey("time_hours", index)
                                dialog.refresh()
                            }
                        }
                    }

                    Section {
                        title: "СТРОКА"
                        visible: Boolean(dialog.formatMeta.layout)
                    }
                    OptionRow {
                        label: "Между полями"
                        visible: Boolean(dialog.formatMeta.layout)
                        Dropdown {
                            Layout.fillWidth: true
                            model: dialog.choiceModel("field_separator")
                            textRole: "label"
                            currentIndex: dialog.indexOfKey(dialog.choiceModel("field_separator"), dialog.fieldSeparator)
                            onActivated: function (index) {
                                dialog.fieldSeparator = dialog.choiceKey("field_separator", index)
                                dialog.refresh()
                            }
                        }
                    }
                    OptionRow {
                        label: "Начало и конец"
                        visible: Boolean(dialog.formatMeta.layout) && dialog.timeMode === "range"
                        Dropdown {
                            Layout.fillWidth: true
                            model: dialog.choiceModel("range_separator")
                            textRole: "label"
                            currentIndex: dialog.indexOfKey(dialog.choiceModel("range_separator"), dialog.rangeSeparator)
                            onActivated: function (index) {
                                dialog.rangeSeparator = dialog.choiceKey("range_separator", index)
                                dialog.refresh()
                            }
                        }
                    }
                    OptionRow {
                        label: "Имя голоса"
                        visible: Boolean(dialog.formatMeta.layout)
                        Dropdown {
                            Layout.fillWidth: true
                            enabled: dialog.includeSpeakers
                            model: dialog.choiceModel("speaker_style")
                            textRole: "label"
                            currentIndex: dialog.indexOfKey(dialog.choiceModel("speaker_style"), dialog.speakerStyle)
                            onActivated: function (index) {
                                dialog.speakerStyle = dialog.choiceKey("speaker_style", index)
                                dialog.refresh()
                            }
                        }
                    }

                    Section { title: "СОДЕРЖИМОЕ" }
                    ToggleSwitch {
                        text: "Имена говорящих"
                        checked: dialog.includeSpeakers
                        onToggled: {
                            dialog.includeSpeakers = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: "Имя только при смене голоса"
                        visible: Boolean(dialog.formatMeta.layout)
                        enabled: dialog.includeSpeakers
                        checked: dialog.speakerOnce
                        onToggled: {
                            dialog.speakerOnce = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: "Уверенность распознавания"
                        visible: Boolean(dialog.formatMeta.notes)
                        checked: dialog.includeConfidence
                        onToggled: {
                            dialog.includeConfidence = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: "Метки «на проверку»"
                        visible: Boolean(dialog.formatMeta.notes)
                        checked: dialog.includeReviewFlags
                        onToggled: {
                            dialog.includeReviewFlags = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: "Длительность фразы"
                        visible: Boolean(dialog.formatMeta.layout) || Boolean(dialog.formatMeta.table)
                        checked: dialog.includeDuration
                        onToggled: {
                            dialog.includeDuration = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: Boolean(dialog.formatMeta.table) ? "Строка с названиями колонок" : "Шапка файла"
                        visible: Boolean(dialog.formatMeta.header)
                        checked: dialog.includeHeader
                        onToggled: {
                            dialog.includeHeader = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: "Номера фраз"
                        visible: Boolean(dialog.formatMeta.numbers)
                        checked: dialog.includePhraseNumbers
                        onToggled: {
                            dialog.includePhraseNumbers = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: "Склеивать подряд идущие фразы одного голоса"
                        checked: dialog.mergeTurns
                        onToggled: {
                            dialog.mergeTurns = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: "Пустая строка между фразами"
                        visible: Boolean(dialog.formatMeta.layout)
                        checked: dialog.blankBetween
                        onToggled: {
                            dialog.blankBetween = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: "Пропускать пустые фразы"
                        checked: dialog.skipEmpty
                        onToggled: {
                            dialog.skipEmpty = checked
                            dialog.refresh()
                        }
                    }

                    Section {
                        title: "СУБТИТРЫ"
                        visible: Boolean(dialog.formatMeta.subtitles)
                    }
                    OptionRow {
                        label: "Длина строки"
                        visible: Boolean(dialog.formatMeta.subtitles)
                        Repeater {
                            model: [32, 42, 56, 72]
                            delegate: PillButton {
                                required property var modelData
                                text: String(modelData)
                                compact: true
                                primary: dialog.subtitleChars === Number(modelData)
                                onClicked: {
                                    dialog.subtitleChars = Number(modelData)
                                    dialog.refresh()
                                }
                            }
                        }
                        Label {
                            text: "символов"
                            color: Theme.faint
                            font.pixelSize: Theme.fsMicro
                        }
                    }
                    OptionRow {
                        label: "Длина реплики"
                        visible: Boolean(dialog.formatMeta.subtitles)
                        Repeater {
                            model: [3, 4, 6, 8]
                            delegate: PillButton {
                                required property var modelData
                                text: String(modelData) + " с"
                                compact: true
                                primary: Math.abs(dialog.subtitleSeconds - Number(modelData)) < 0.01
                                onClicked: {
                                    dialog.subtitleSeconds = Number(modelData)
                                    dialog.refresh()
                                }
                            }
                        }
                    }

                    Section {
                        title: "ТАБЛИЦА"
                        visible: Boolean(dialog.formatMeta.table)
                    }
                    OptionRow {
                        label: "Разделитель"
                        visible: Boolean(dialog.formatMeta.table)
                        Dropdown {
                            Layout.fillWidth: true
                            model: dialog.choiceModel("csv_delimiter")
                            textRole: "label"
                            currentIndex: dialog.indexOfKey(dialog.choiceModel("csv_delimiter"), dialog.csvDelimiter)
                            onActivated: function (index) {
                                dialog.csvDelimiter = dialog.choiceKey("csv_delimiter", index)
                                dialog.refresh()
                            }
                        }
                    }
                    ToggleSwitch {
                        text: "Метка UTF-8 для Excel"
                        visible: Boolean(dialog.formatMeta.table)
                        checked: dialog.csvBom
                        onToggled: {
                            dialog.csvBom = checked
                            dialog.refresh()
                        }
                    }

                    Section { title: "ЧТО ПОПАДЁТ В ФАЙЛ" }
                    ToggleSwitch {
                        text: dialog.focusKey > 0
                              ? "Только выбранный голос"
                              : "Только выбранный голос (голос не выбран)"
                        enabled: dialog.focusKey > 0
                        checked: dialog.focusedOnly
                        onToggled: {
                            dialog.focusedOnly = checked
                            dialog.refresh()
                        }
                    }
                    ToggleSwitch {
                        text: "Только фразы на проверку"
                        checked: dialog.onlyFlagged
                        onToggled: {
                            dialog.onlyFlagged = checked
                            dialog.refresh()
                        }
                    }
                    Item { Layout.preferredHeight: Theme.gapMd }
                }
            }

            // Предпросмотр.
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.gapXs
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    Label {
                        text: String(dialog.info.filename || "")
                        color: Theme.text
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.fsLabel
                        elide: Text.ElideMiddle
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        text: {
                            var parts = []
                            parts.push(dialog.phrasesLabel(Number(dialog.info.phrases || 0)))
                            parts.push(Number(dialog.info.lines || 0) + " строк")
                            var chars = Number(dialog.info.chars || 0)
                            parts.push(chars > 2048 ? Math.round(chars / 1024) + " КБ" : chars + " симв.")
                            return parts.join(" · ")
                        }
                        color: Theme.faint
                        font.pixelSize: Theme.fsMicro
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: Theme.radiusSm
                    color: Theme.fill
                    border.width: 1
                    border.color: Theme.hairline
                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: 1
                        clip: true
                        TextArea {
                            readOnly: true
                            wrapMode: TextEdit.NoWrap
                            selectByMouse: true
                            color: Theme.text
                            font.family: Theme.monoFamily
                            font.pixelSize: Theme.fsSmall
                            text: String(dialog.info.notice || "") || String(dialog.info.text || "")
                            background: null
                        }
                    }
                }
                Label {
                    Layout.fillWidth: true
                    visible: Boolean(dialog.info.truncated)
                    text: "Показаны первые 200 строк. В файл попадёт весь текст."
                    color: Theme.faint
                    font.pixelSize: Theme.fsMicro
                    wrapMode: Text.Wrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: Theme.hairline
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gapSm
            Label {
                Layout.fillWidth: true
                text: "Выбор запоминается после сохранения."
                color: Theme.faint
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
            PillButton {
                text: "Отмена"
                onClicked: dialog.close()
            }
            PillButton {
                objectName: "exportSaveButton"
                text: "Сохранить файл"
                primary: true
                enabled: Number(dialog.info.phrases || 0) > 0
                onClicked: {
                    bridge.transcriptExportWithOptions(dialog.options())
                    dialog.close()
                }
            }
        }
    }
}
