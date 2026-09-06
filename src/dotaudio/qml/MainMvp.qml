import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtMultimedia

ApplicationWindow {
    id: root
    property bool compact: true
    property bool logsOpen: false
    property var pageKeys: ["live", "dictation", "media", "models", "history", "settings"]
    width: compact ? 620 : 1180
    height: compact ? 166 : 760
    minimumWidth: compact ? 520 : 920
    minimumHeight: compact ? 140 : 620
    visible: true
    color: compact ? "transparent" : "#090b0f"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    opacity: compact ? Math.max(0.78, Number(bridge.settings.island_opacity)) : 1
    font.family: "Segoe UI"

    function accent() {
        if (bridge.recording) return "#ff5b78"
        if (bridge.busy || bridge.modelPreparing) return "#efbd62"
        return "#77dfba"
    }
    function expand(page) {
        if (page) bridge.selectPage(page)
        bridge.applyIslandClickThrough(false)
        compact = false
    }
    function collapse() {
        compact = true
        bridge.applyIslandClickThrough(Boolean(bridge.settings.island_click_through))
    }
    Component.onCompleted: {
        if (Number(bridge.settings.island_x) >= 0) {
            x = Number(bridge.settings.island_x)
            y = Number(bridge.settings.island_y)
        }
    }
    Connections {
        target: bridge
        function onIslandRequested() { root.compact = true }
    }
    Shortcut { sequence: "Escape"; enabled: bridge.busy; onActivated: bridge.cancel() }

    Rectangle {
        visible: root.compact
        anchors.fill: parent
        radius: 29
        color: "#171a20"
        border.width: 1
        border.color: bridge.recording ? "#a94158" : "#343e4b"
        Rectangle { anchors.fill: parent; anchors.margins: 1; radius: 28; color: "transparent"; border.color: "#ffffff16" }
        MouseArea {
            anchors.fill: parent
            z: 1
            onPressed: root.startSystemMove()
            onReleased: bridge.saveIslandPosition(root.x, root.y)
        }
        RowLayout {
            z: 2
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12
            Button {
                id: recordButton
                Layout.preferredWidth: 54
                Layout.preferredHeight: 54
                text: bridge.recording ? "■" : "●"
                onClicked: bridge.toggleRecording()
                contentItem: Text { text: recordButton.text; color: "#101218"; font.bold: true; font.pixelSize: bridge.recording ? 16 : 27; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 27; color: root.accent() }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: bridge.recording ? "LIVE · СЛУШАЮ" : bridge.busy ? "WHISPER · ОБРАБОТКА" : "DOTAUDIO · ГОТОВ"; color: root.accent(); font.pixelSize: 9; font.bold: true; font.letterSpacing: 1.4 }
                    Item { Layout.fillWidth: true }
                    Label { visible: bridge.recording || bridge.busy; text: bridge.elapsed; color: "#9da9b8"; font.family: "Consolas"; font.pixelSize: 11 }
                }
                Text { Layout.fillWidth: true; text: bridge.caption.length ? bridge.caption : bridge.recording ? "Говорите. Текст появится после первой фразы." : "Нажмите запись для живых субтитров"; color: "#f4f7f8"; font.pixelSize: 15; font.weight: Font.DemiBold; elide: Text.ElideRight }
                Row {
                    Layout.fillWidth: true
                    height: 18
                    spacing: 3
                    Repeater {
                        model: 40
                        delegate: Rectangle {
                            required property int index
                            property real shape: 0.25 + Math.abs(Math.sin(index * 2.1)) * 0.75
                            width: 5
                            height: 3 + (bridge.recording ? bridge.level * 18 * shape : 1)
                            radius: 3
                            anchors.verticalCenter: parent.verticalCenter
                            color: bridge.recording ? "#ff6d85" : "#465363"
                            Behavior on height { NumberAnimation { duration: 90 } }
                        }
                    }
                }
            }
            Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 54; color: "#ffffff16" }
            Button { Layout.preferredWidth: 42; Layout.preferredHeight: 42; text: "⌁"; onClicked: root.expand("models") }
            Button { Layout.preferredWidth: 42; Layout.preferredHeight: 42; text: "↗"; onClicked: root.expand("live") }
        }
    }

    Rectangle {
        visible: !root.compact
        anchors.fill: parent
        color: "#090b0f"
        RowLayout {
            anchors.fill: parent
            spacing: 0
            Rectangle {
                Layout.preferredWidth: 230
                Layout.fillHeight: true
                color: "#10131a"
                border.color: "#252d38"
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 8
                    RowLayout {
                        Rectangle { width: 38; height: 38; radius: 13; color: "#e8eef0"; Label { anchors.centerIn: parent; text: ".a"; color: "#101218"; font.bold: true } }
                        ColumnLayout { Label { text: ".аудио"; color: "#f3f6f8"; font.pixelSize: 21; font.bold: true } Label { text: "DOTCORE / WHISPER"; color: "#7f8d9d"; font.pixelSize: 9 } }
                    }
                    Label { text: "ЖИВАЯ РЕЧЬ"; color: "#718297"; font.pixelSize: 9; font.letterSpacing: 1.2; Layout.topMargin: 15 }
                    Repeater {
                        model: [
                            {key:"live", icon:"◉", label:"Live-субтитры"}, {key:"dictation", icon:"✦", label:"Диктовка"},
                            {key:"media", icon:"▣", label:"Караоке"}, {key:"models", icon:"⌁", label:"Модели"},
                            {key:"history", icon:"◷", label:"История"}, {key:"settings", icon:"⚙", label:"Настройки"}
                        ]
                        delegate: Button {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 46
                            onClicked: bridge.selectPage(modelData.key)
                            contentItem: RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 11; spacing: 9
                                Label { text: modelData.icon; color: bridge.page === modelData.key ? "#101218" : "#9aabbd"; font.pixelSize: 17; Layout.preferredWidth: 20 }
                                Label { text: modelData.label; color: bridge.page === modelData.key ? "#101218" : "#edf2f6"; font.pixelSize: 12; font.bold: true }
                            }
                            background: Rectangle { radius: 13; color: bridge.page === modelData.key ? "#e8f0f2" : "transparent" }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Label { text: "Ctrl + Alt + Space\nзапись\n\nCtrl + Alt + O\nостров"; color: "#758497"; font.pixelSize: 10 }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 26
                spacing: 14
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Label { text: ({live:"Live-субтитры", dictation:"Диктовка", media:"Караоке-студия", models:"Модели Whisper", history:"История", settings:"Настройки"})[bridge.page]; color: "#f2f5f7"; font.pixelSize: 27; font.bold: true }
                        Label { text: bridge.status; color: "#8594a5"; font.pixelSize: 12 }
                    }
                    Item { Layout.fillWidth: true }
                    Button { text: "Журнал"; onClicked: root.logsOpen = !root.logsOpen }
                    Button { text: "Свернуть"; onClicked: root.collapse() }
                }
                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: root.pageKeys.indexOf(bridge.page)
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 14
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 250
                                radius: 22
                                color: "#151a22"
                                border.color: bridge.recording ? "#914355" : "#2b3948"
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 24
                                    spacing: 10
                                    Label { text: bridge.recording ? "Эфир в работе" : "Готов к прямым субтитрам"; color: "#f5f7fa"; font.pixelSize: 22; font.bold: true }
                                    Text {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        text: bridge.caption.length ? bridge.caption : "Нажмите «Начать live». Здесь появится первая завершённая фраза."
                                        color: bridge.caption.length ? "#ffffff" : "#96a5b5"
                                        font.pixelSize: bridge.caption.length ? 28 : 16
                                        font.weight: bridge.caption.length ? Font.DemiBold : Font.Normal
                                        wrapMode: Text.Wrap
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    Row {
                                        Layout.fillWidth: true
                                        height: 24
                                        spacing: 4
                                        Repeater {
                                            model: 52
                                            delegate: Rectangle {
                                                required property int index
                                                property real shape: 0.2 + Math.abs(Math.sin(index * 1.9)) * 0.8
                                                width: 6
                                                height: 3 + bridge.level * 21 * shape
                                                radius: 3
                                                anchors.verticalCenter: parent.verticalCenter
                                                color: bridge.recording ? "#ff6c84" : "#354252"
                                                Behavior on height { NumberAnimation { duration: 80 } }
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Button { text: bridge.recording ? "Завершить" : "Начать live"; enabled: !bridge.busy || bridge.recording; onClicked: bridge.toggleRecording() }
                                        Button { visible: bridge.busy; text: "Отмена"; onClicked: bridge.cancel() }
                                        Item { Layout.fillWidth: true }
                                        Label { text: bridge.elapsed; color: "#c6d0da"; font.family: "Consolas" }
                                    }
                                }
                            }
                            TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; editable: false; showEmptyHint: false }
                        }
                    }
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 14
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 190
                                radius: 22
                                color: "#151a22"
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 22
                                    Label { text: "Голос в текст и буфер обмена"; color: "#f2f5f7"; font.pixelSize: 22; font.bold: true }
                                    Text { Layout.fillWidth: true; text: "Запуск горячей клавишей сохранит целевое окно. Текст останется в истории и буфере обмена."; color: "#93a2b2"; wrapMode: Text.Wrap }
                                    Item { Layout.fillHeight: true }
                                    RowLayout {
                                        Button { text: bridge.recording ? "Завершить" : "Записать"; onClicked: bridge.toggleRecording() }
                                        Button { text: "Копировать"; enabled: bridge.text.length > 0; onClicked: bridge.copyText() }
                                    }
                                }
                            }
                            TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; editable: true }
                        }
                    }
                    Item {
                        RowLayout {
                            anchors.fill: parent
                            spacing: 14
                            ColumnLayout {
                                Layout.preferredWidth: parent.width * 0.52
                                Layout.fillHeight: true
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    radius: 22
                                    color: "#121720"
                                    VideoOutput { id: mediaVideo; anchors.fill: parent; anchors.margins: 8; visible: mediaPlayer.hasVideo; fillMode: VideoOutput.PreserveAspectFit }
                                    KaraokePreview {
                                        visible: bridge.mediaUrl.length > 0
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.bottom: parent.bottom
                                        anchors.margins: 16
                                        height: 118
                                        player: mediaPlayer
                                        segments: bridge.segments
                                    }
                                    ColumnLayout {
                                        anchors.centerIn: parent
                                        width: parent.width - 60
                                        visible: !bridge.mediaUrl
                                        Label { text: "Аудио в караоке-субтитры"; color: "#f1f5f7"; font.pixelSize: 20; font.bold: true; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
                                        Text { text: "Импортируйте файл, отредактируйте тайминги и экспортируйте ASS или MP4."; color: "#92a2b3"; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                        Button { text: "Выбрать медиа"; Layout.alignment: Qt.AlignHCenter; onClicked: bridge.importFile() }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Button { text: "Открыть"; onClicked: bridge.importFile() }
                                    Button { text: "Обложка"; enabled: bridge.mediaUrl.length > 0; onClicked: bridge.chooseCover() }
                                    Button { text: "ASS"; enabled: bridge.segments.length > 0; onClicked: bridge.exportKaraokeFile() }
                                    Button { text: bridge.rendering ? "Рендер…" : "MP4"; enabled: bridge.segments.length > 0 && !bridge.rendering; onClicked: bridge.exportKaraokeVideo() }
                                }
                            }
                            TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; player: mediaPlayer; editable: true }
                        }
                        MediaPlayer { id: mediaPlayer; source: bridge.mediaUrl; videoOutput: mediaVideo; audioOutput: AudioOutput {} }
                    }
                    Item {
                        ListView {
                            anchors.fill: parent
                            spacing: 9
                            clip: true
                            model: ["tiny", "base", "small", "medium", "large-v3", "turbo"]
                            delegate: Rectangle {
                                required property string modelData
                                width: ListView.view.width
                                height: 76
                                radius: 17
                                color: bridge.settings.model === modelData ? "#203139" : "#151a22"
                                border.color: bridge.settings.model === modelData ? "#76d5ba" : "#293643"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 15
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Label { text: modelData; color: "#f0f5f7"; font.pixelSize: 16; font.bold: true }
                                        Label { text: bridge.settings.model === modelData ? bridge.modelState.message : "Выберите модель и подготовьте её заранее"; color: "#91a1b1"; font.pixelSize: 11 }
                                    }
                                    Button { text: "Выбрать"; enabled: !bridge.busy; onClicked: bridge.setSetting("model", modelData) }
                                    Button { text: bridge.modelPreparing && bridge.modelState.model === modelData ? "…" : "Скачать"; enabled: !bridge.busy && !bridge.modelPreparing; onClicked: { bridge.setSetting("model", modelData); bridge.prepareSelectedModel() } }
                                }
                            }
                        }
                    }
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            TextField { Layout.fillWidth: true; placeholderText: "Поиск по истории"; onTextChanged: bridge.refreshHistory(text) }
                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                model: bridge.history
                                spacing: 7
                                clip: true
                                delegate: Rectangle {
                                    required property var modelData
                                    width: ListView.view.width
                                    height: 70
                                    radius: 14
                                    color: "#151a22"
                                    MouseArea { anchors.fill: parent; onClicked: bridge.openSession(modelData.id) }
                                    Column {
                                        anchors.fill: parent
                                        anchors.margins: 11
                                        spacing: 3
                                        Text { text: modelData.title; color: "#edf2f6"; font.bold: true }
                                        Text { text: modelData.mode + " · " + modelData.segment_count + " сегм."; color: "#91a0af"; font.pixelSize: 11 }
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
                                spacing: 14
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 126
                                    radius: 18
                                    color: "#151a22"
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 16
                                        Label { text: "Язык и субтитры"; color: "#f0f5f7"; font.bold: true; font.pixelSize: 16 }
                                        RowLayout {
                                            Label { text: "Русский язык выбран по умолчанию"; color: "#a1afbd"; Layout.fillWidth: true }
                                            Button { text: "Русский"; onClicked: bridge.setSetting("language", "ru") }
                                            Button { text: "English subtitles"; onClicked: bridge.setSetting("task", "translate") }
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 210
                                    radius: 18
                                    color: "#151a22"
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 16
                                        Label { text: "Микрофон и наушники"; color: "#f0f5f7"; font.bold: true; font.pixelSize: 16 }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ComboBox { Layout.fillWidth: true; model: ["Системный микрофон"].concat(bridge.devices.map(function(d) { return d.name })) }
                                            Button { text: "Обновить"; onClicked: bridge.refreshDevices() }
                                            Button { text: "Тест 3 сек"; onClicked: bridge.testMicrophone() }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ComboBox { Layout.fillWidth: true; model: ["Системный вывод"].concat(bridge.outputs.map(function(d) { return d.name })) }
                                            Button { text: "Тест тона"; onClicked: bridge.testOutputDevice() }
                                        }
                                        ProgressBar { Layout.fillWidth: true; from: 0; to: 0.35; value: bridge.deviceTest.level }
                                        Label { text: bridge.deviceTest.message || "Проверка не сохраняет аудио."; color: "#8fa0b1"; font.pixelSize: 11 }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 176
                                    radius: 18
                                    color: "#151a22"
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 16
                                        Label { text: "Мини-островок"; color: "#f0f5f7"; font.bold: true; font.pixelSize: 16 }
                                        RowLayout {
                                            Label { text: "Прозрачность"; color: "#a1afbd"; Layout.preferredWidth: 115 }
                                            Slider { Layout.fillWidth: true; from: 0.78; to: 1; value: Number(bridge.settings.island_opacity); onMoved: bridge.setSetting("island_opacity", value) }
                                        }
                                        Switch { text: "Пропускать клики"; checked: Boolean(bridge.settings.island_click_through); onToggled: bridge.setIslandClickThrough(checked) }
                                        Switch { text: "Запоминать позицию"; checked: Boolean(bridge.settings.island_snap); onToggled: bridge.setSetting("island_snap", checked) }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        Rectangle {
            visible: root.logsOpen
            width: 350
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            color: "#151a22"
            border.color: "#344251"
            z: 10
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Журнал"; color: "#f2f5f7"; font.pixelSize: 19; font.bold: true }
                    Item { Layout.fillWidth: true }
                    Button { text: "×"; onClicked: root.logsOpen = false }
                }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: bridge.logs
                    spacing: 7
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width
                        implicitHeight: logEntry.implicitHeight + 16
                        radius: 10
                        color: "#202832"
                        Text { id: logEntry; anchors.fill: parent; anchors.margins: 8; text: modelData.time + "  " + modelData.message; color: "#dce5ec"; wrapMode: Text.Wrap; font.pixelSize: 11 }
                    }
                }
            }
        }
    }
}
