import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: root
    width: 1160
    height: 780
    minimumWidth: 800
    minimumHeight: 600
    visible: true
    title: "DotAudio · основа проекта"
    color: "#111214"
    property var pages: ["dictation", "live", "media", "monitor", "history", "settings"]
    property var titles: ["Диктовка", "Живые субтитры", "Аудио и видео", "Мониторинг эфира", "История", "Настройки"]
    onClosing: function(close) {
        if (bridge.busy) {
            close.accepted = false
            bridge.cancel()
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.preferredWidth: 210
            Layout.fillHeight: true
            color: "#0c0d0f"
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 22
                spacing: 12
                Label { text: ".аудио"; font.pixelSize: 30; font.bold: true; color: "#f3f3f1"; Layout.topMargin: 12 }
                Label { text: "DOTCORE / WHISPER"; font.pixelSize: 10; color: "#81838a"; Layout.bottomMargin: 32 }
                Repeater {
                    model: root.titles
                    Button {
                        required property int index
                        required property string modelData
                        text: modelData
                        Layout.fillWidth: true
                        checked: bridge.page === root.pages[index]
                        onClicked: bridge.selectPage(root.pages[index])
                    }
                }
                Item { Layout.fillHeight: true }
                Label { text: "Основа для разработки\nИнтерфейс пока черновой"; color: "#81838a"; font.pixelSize: 11 }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 30
            spacing: 16
            RowLayout {
                Layout.fillWidth: true
                Label { text: root.titles[root.pages.indexOf(bridge.page)]; font.pixelSize: 28; font.bold: true }
                Item { Layout.fillWidth: true }
                Button { text: "Остров"; onClicked: bridge.showIsland() }
            }
            Label { text: bridge.status; color: "#a6a7ab"; elide: Text.ElideRight; Layout.fillWidth: true }
            Rectangle {
                visible: bridge.notice.length > 0
                Layout.fillWidth: true
                implicitHeight: noticeText.implicitHeight + 24
                radius: 8
                color: "#292b31"
                Label { id: noticeText; anchors.fill: parent; anchors.margins: 12; text: bridge.notice; wrapMode: Text.Wrap }
                TapHandler { onTapped: bridge.clearNotice() }
            }
            RowLayout {
                visible: bridge.page !== "history" && bridge.page !== "settings"
                spacing: 12
                Button {
                    text: bridge.recording ? "Завершить запись" : "Начать запись"
                    visible: bridge.page !== "media"
                    enabled: !bridge.busy || bridge.recording
                    onClicked: bridge.toggleRecording()
                }
                Button { text: "Открыть файл"; visible: bridge.page === "media"; enabled: !bridge.busy; onClicked: bridge.importFile() }
                Button { text: "Отменить"; visible: bridge.busy; onClicked: bridge.cancel() }
                Label { text: bridge.elapsed; color: "#a6a7ab" }
                ProgressBar { value: bridge.level; Layout.preferredWidth: 100; visible: bridge.recording }
                Item { Layout.fillWidth: true }
            }
            Label {
                visible: bridge.page === "dictation"
                text: "Ctrl+Alt+Space: диктовка в активном приложении. После остановки текст остаётся в буфере."
                wrapMode: Text.Wrap
                color: "#81838a"
                Layout.fillWidth: true
            }
            ColumnLayout {
                visible: bridge.page === "settings"
                Layout.fillWidth: true
                spacing: 12
                Repeater {
                    model: [
                        {key:"model", title:"Модель", choices:["tiny","base","small","medium","large-v3","turbo"]},
                        {key:"device", title:"Устройство", choices:["auto","cpu","cuda"]},
                        {key:"language", title:"Язык", choices:["auto","ru","en","de","es","fr","zh"]},
                        {key:"source", title:"Источник", choices:["microphone","system"]},
                        {key:"backend", title:"Обработка", choices:["local","remote"]},
                        {key:"task", title:"Задача", choices:["transcribe","translate"]}
                    ]
                    RowLayout {
                        required property var modelData
                        Label { text: modelData.title; Layout.preferredWidth: 130 }
                        ComboBox {
                            model: modelData.choices
                            currentIndex: modelData.choices.indexOf(bridge.settings[modelData.key])
                            enabled: !bridge.busy
                            Layout.preferredWidth: 250
                            onActivated: bridge.setSetting(modelData.key, currentText)
                        }
                    }
                }
                TextField {
                    Layout.fillWidth: true
                    placeholderText: "Адрес сервера"
                    text: bridge.settings.server_url
                    enabled: !bridge.busy
                    onEditingFinished: bridge.setSetting("server_url", text)
                }
                Label { text: "translate переводит речь на английский. Модель скачивается при первом распознавании."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: "#81838a" }
            }
            ColumnLayout {
                visible: bridge.page === "monitor"
                Layout.fillWidth: true
                TextField {
                    Layout.fillWidth: true
                    placeholderText: "Ключевые слова через запятую"
                    text: bridge.settings.keywords
                    enabled: !bridge.busy
                    onEditingFinished: bridge.setSetting("keywords", text)
                }
                TextArea {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 85
                    placeholderText: "Название | https://прямая-ссылка-на-эфир\nОдин источник на строку, до четырёх"
                    text: bridge.settings.channels
                    enabled: !bridge.busy
                    onActiveFocusChanged: if (!activeFocus) bridge.setSetting("channels", text)
                }
                Label { text: "Совпадений в текущей сессии: " + bridge.hits.length; color: "#a6a7ab" }
            }
            TextField {
                visible: bridge.page === "history"
                Layout.fillWidth: true
                placeholderText: "Поиск по названию и тексту"
                onTextChanged: bridge.refreshHistory(text)
            }
            ListView {
                visible: bridge.page === "history"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 6
                model: bridge.history
                delegate: Button {
                    required property var modelData
                    width: ListView.view.width
                    text: modelData.title + " · " + modelData.created_at + " · " + modelData.segment_count + " фраз"
                    onClicked: bridge.openSession(modelData.id)
                }
            }
            Rectangle {
                visible: bridge.page !== "history" && bridge.page !== "settings"
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "#191a1e"
                radius: 16
                border.color: "#2c2d32"
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 20
                    TextArea {
                        readOnly: true
                        text: bridge.text || "Здесь появится расшифровка."
                        wrapMode: Text.Wrap
                        font.pixelSize: bridge.page === "live" ? 28 : 18
                        color: bridge.text ? "#f3f3f1" : "#74767e"
                        background: null
                    }
                }
            }
            Item { visible: bridge.page === "settings"; Layout.fillHeight: true }
            RowLayout {
                visible: bridge.page !== "history" && bridge.page !== "settings"
                Button { text: "Копировать"; enabled: bridge.segments.length > 0; onClicked: bridge.copyText() }
                Repeater {
                    model: ["txt", "srt", "vtt", "json"]
                    Button { required property string modelData; text: modelData.toUpperCase(); enabled: bridge.segments.length > 0; onClicked: bridge.exportFile(modelData) }
                }
            }
        }
    }
    Window {
        id: island
        width: 520
        height: 130
        color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        x: Screen.width / 2 - width / 2
        y: 40
        Rectangle {
            anchors.fill: parent
            radius: 28
            color: "#ed141518"
            border.color: "#424349"
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                Label { text: ".аудио  /  " + bridge.status; font.pixelSize: 11; color: "#a6a7ab"; Layout.fillWidth: true; elide: Text.ElideRight }
                Label { text: bridge.caption; font.pixelSize: 19; maximumLineCount: 2; wrapMode: Text.Wrap; elide: Text.ElideRight; Layout.fillWidth: true; Layout.fillHeight: true }
            }
            TapHandler { onDoubleTapped: island.visible = false }
        }
    }
    Connections {
        target: bridge
        function onIslandRequested() { island.visible = !island.visible }
    }
}
