import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtMultimedia

ApplicationWindow {
    id: root
    width: 1260
    height: 820
    minimumWidth: 920
    minimumHeight: 640
    visible: true
    title: "DotAudio"
    color: "#0b0c0e"
    font.family: "Segoe UI"
    font.pointSize: 10
    property var nav: [
        { key: "dictation", title: "Диктовка", hint: "Голос в текст" },
        { key: "live", title: "Субтитры", hint: "Здесь и сейчас" },
        { key: "media", title: "Аудио и видео", hint: "Файл и таймкоды" },
        { key: "monitor", title: "Эфиры", hint: "Ключевые новости" },
        { key: "history", title: "История", hint: "Все сессии" },
        { key: "settings", title: "Настройки", hint: "Модель и устройства" }
    ]
    property var titles: ({
        dictation: "Диктовка", live: "Живые субтитры", media: "Аудио и видео",
        monitor: "Мониторинг эфиров", history: "История", settings: "Настройки"
    })
    property int pageIndex: ["dictation", "live", "media", "monitor", "history", "settings"].indexOf(bridge.page)

    function timestamp(milliseconds) {
        var total = Math.max(0, Math.floor(milliseconds / 1000))
        var h = Math.floor(total / 3600)
        var m = Math.floor((total % 3600) / 60)
        var s = total % 60
        return (h > 0 ? (h < 10 ? "0" : "") + h + ":" : "")
            + (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
    }

    function startLabel() {
        if (bridge.recording) return "Завершить"
        if (bridge.page === "monitor") return "Запустить эфиры"
        if (bridge.page === "live") return "Начать субтитры"
        return "Начать запись"
    }

    onClosing: function(close) {
        if (bridge.busy) {
            close.accepted = false
            bridge.cancel()
        }
    }

    Shortcut { sequence: "Escape"; enabled: bridge.busy; onActivated: bridge.cancel() }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            id: sidebar
            Layout.preferredWidth: 238
            Layout.fillHeight: true
            color: "#101115"
            border.color: "#24262c"
            border.width: 1
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 8
                Item { Layout.preferredHeight: 16 }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Rectangle {
                        width: 38; height: 38; radius: 14
                        color: "#f0f1ef"
                        Label { anchors.centerIn: parent; text: ".a"; color: "#101115"; font.bold: true; font.pixelSize: 15 }
                    }
                    ColumnLayout {
                        spacing: 0
                        Label { text: ".аудио"; color: "#f2f3f1"; font.bold: true; font.pixelSize: 23 }
                        Label { text: "DOTCORE / WHISPER"; color: "#8d9098"; font.pixelSize: 9; font.letterSpacing: 1.4 }
                    }
                }
                Item { Layout.preferredHeight: 28 }
                Repeater {
                    model: root.nav
                    delegate: Button {
                        id: navButton
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: 48
                        text: modelData.title
                        checkable: true
                        checked: bridge.page === modelData.key
                        onClicked: bridge.selectPage(modelData.key)
                        contentItem: Column {
                            anchors.left: parent.left
                            anchors.leftMargin: 13
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 1
                            Text { text: navButton.text; color: navButton.checked ? "#121316" : "#e8e9e8"; font.pixelSize: 14; font.weight: Font.DemiBold }
                            Text { text: navButton.modelData.hint; color: navButton.checked ? "#46484e" : "#858892"; font.pixelSize: 10 }
                        }
                        background: Rectangle { radius: 13; color: navButton.checked ? "#eceeeb" : navButton.hovered ? "#1b1d22" : "transparent" }
                    }
                }
                Item { Layout.fillHeight: true }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 74
                    radius: 14
                    color: "#181a1f"
                    border.color: "#2a2c32"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 11; spacing: 3
                        Label { text: bridge.hotkeysAvailable ? "Горячая клавиша включена" : "Горячая клавиша занята"; color: "#dedfdf"; font.pixelSize: 11; font.weight: Font.DemiBold }
                        Label { text: bridge.hotkeysAvailable ? "Ctrl + Alt + Space" : "Используйте кнопку записи"; color: "#8c9099"; font.pixelSize: 10 }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 30
            spacing: 16
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    spacing: 2
                    Label { text: root.titles[bridge.page]; color: "#f2f3f1"; font.pixelSize: 30; font.weight: Font.DemiBold }
                    Label { text: bridge.sessionTitle || "Локальная расшифровка · история сохраняется на этом устройстве"; color: "#8e9199"; font.pixelSize: 12 }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    Layout.preferredWidth: Math.max(126, statusText.implicitWidth + 28)
                    Layout.preferredHeight: 34
                    radius: 17
                    color: bridge.recording ? "#f0f1ef" : "#1a1c21"
                    Label { id: statusText; anchors.centerIn: parent; text: bridge.status; color: bridge.recording ? "#121316" : "#b7bac1"; font.pixelSize: 11 }
                }
                Button {
                    id: islandButton
                    text: "Остров"
                    onClicked: bridge.showIsland()
                    contentItem: Text { text: "Остров"; color: "#e8e9e9"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 12 }
                    background: Rectangle { radius: 16; color: islandButton.down ? "#34363d" : "#24262d" }
                }
            }

            Rectangle {
                visible: bridge.notice.length > 0
                Layout.fillWidth: true
                implicitHeight: notice.implicitHeight + 22
                radius: 12
                color: "#272930"
                border.color: "#3a3d46"
                Label { id: notice; anchors.fill: parent; anchors.margins: 11; text: bridge.notice; wrapMode: Text.Wrap; color: "#e9eaeb"; font.pixelSize: 12 }
                TapHandler { onTapped: bridge.clearNotice() }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: root.pageIndex < 0 ? 0 : root.pageIndex

                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 16
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 252; radius: 22
                            color: "#17181c"; border.color: "#2c2e35"
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 26; spacing: 12
                                Label { text: bridge.recording ? "Говорите. Я сохраню текст в историю и буфер обмена." : "Скажите мысль - DotAudio подготовит текст для вставки."; color: "#f0f1ef"; font.pixelSize: 22; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Label { text: "Запись включается кнопкой или Ctrl + Alt + Space. После завершения текст попадёт в буфер; автовставка работает только при запуске горячей клавишей и сохранённом фокусе окна."; color: "#9b9ea6"; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Item { Layout.fillHeight: true }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Button {
                                        id: dictationButton
                                        text: root.startLabel(); enabled: !bridge.busy || bridge.recording
                                        onClicked: bridge.toggleRecording()
                                        contentItem: Text { text: dictationButton.text; color: "#111215"; font.pixelSize: 14; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        background: Rectangle { radius: 18; color: dictationButton.enabled ? "#eef0ed" : "#5d6067" }
                                    }
                                    Button { visible: bridge.busy; text: "Отменить"; onClicked: bridge.cancel() }
                                    Item { Layout.fillWidth: true }
                                    Label { text: bridge.elapsed; color: "#f0f1ef"; font.pixelSize: 20; font.family: "Consolas" }
                                }
                                ProgressBar { Layout.fillWidth: true; from: 0; to: 0.25; value: bridge.level; visible: bridge.recording }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Микрофон"; color: "#a7aab2" }
                            ComboBox {
                                id: inputDevices
                                Layout.preferredWidth: 310
                                model: [{id:"", name:"Системный микрофон"}].concat(bridge.devices)
                                textRole: "name"
                                currentIndex: {
                                    for (var i = 0; i < model.length; ++i) if (String(model[i].id) === String(bridge.settings.input_device)) return i
                                    return 0
                                }
                                enabled: !bridge.busy
                                onActivated: bridge.setSetting("input_device", String(model[currentIndex].id))
                            }
                            Button { text: "Обновить"; enabled: !bridge.busy; onClicked: bridge.refreshDevices() }
                            Item { Layout.fillWidth: true }
                            Switch { text: "Автовставка"; checked: bridge.settings.auto_paste; enabled: !bridge.busy; onToggled: bridge.setSetting("auto_paste", checked) }
                        }
                        TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; editable: true }
                    }
                }

                Item {
                    ColumnLayout {
                        anchors.fill: parent; spacing: 16
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 188; radius: 22
                            color: "#17181c"; border.color: "#2c2e35"
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 24; spacing: 10
                                Label { text: "Субтитры без отвлечения от события"; color: "#f0f1ef"; font.pixelSize: 22; font.weight: Font.DemiBold }
                                Label { text: "Выберите микрофон или системный звук в настройках. Остров можно вынести поверх презентации или видеозвонка."; color: "#9b9ea6"; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Item { Layout.fillHeight: true }
                                RowLayout {
                                    Button { text: root.startLabel(); enabled: !bridge.busy || bridge.recording; onClicked: bridge.toggleRecording() }
                                    Button { visible: bridge.busy; text: "Отменить"; onClicked: bridge.cancel() }
                                    Item { Layout.fillWidth: true }
                                    Label { text: bridge.caption; width: 400; elide: Text.ElideRight; color: "#d9dbdf"; font.pixelSize: 14 }
                                }
                            }
                        }
                        TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; editable: false }
                    }
                }

                Item {
                    RowLayout {
                        anchors.fill: parent; spacing: 16
                        ColumnLayout {
                            Layout.preferredWidth: Math.max(360, parent.width * 0.45)
                            Layout.fillHeight: true; spacing: 12
                            Rectangle {
                                Layout.fillWidth: true; Layout.fillHeight: true; radius: 20
                                color: "#15161a"; border.color: "#2b2d34"
                                VideoOutput { id: mediaVideo; anchors.fill: parent; anchors.margins: 8; fillMode: VideoOutput.PreserveAspectFit; visible: mediaPlayer.hasVideo }
                                ColumnLayout {
                                    anchors.centerIn: parent; width: parent.width - 60; visible: !bridge.mediaUrl
                                    Label { text: "Откройте запись, подкаст или видео"; color: "#f0f1ef"; font.pixelSize: 18; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
                                    Label { text: "После обработки появятся синхронизированные реплики. Файл остаётся в исходной папке."; color: "#9699a2"; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
                                    Button { text: "Выбрать файл"; Layout.alignment: Qt.AlignHCenter; onClicked: bridge.importFile() }
                                }
                                DropArea { anchors.fill: parent; onDropped: if (drop.urls.length) bridge.transcribePath(drop.urls[0].toString()) }
                            }
                            RowLayout {
                                Layout.fillWidth: true; visible: bridge.mediaUrl.length > 0
                                Button { text: mediaPlayer.playbackState === MediaPlayer.PlayingState ? "Пауза" : "Воспроизвести"; onClicked: mediaPlayer.playbackState === MediaPlayer.PlayingState ? mediaPlayer.pause() : mediaPlayer.play() }
                                Slider { Layout.fillWidth: true; from: 0; to: Math.max(1, mediaPlayer.duration); value: mediaPlayer.position; onMoved: mediaPlayer.position = value }
                                Label { text: root.timestamp(mediaPlayer.position) + " / " + root.timestamp(mediaPlayer.duration); color: "#a4a7af"; font.family: "Consolas"; font.pixelSize: 11 }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Button { text: "Открыть файл"; enabled: !bridge.busy; onClicked: bridge.importFile() }
                                Button { text: "Отменить"; visible: bridge.busy; onClicked: bridge.cancel() }
                                Item { Layout.fillWidth: true }
                            }
                        }
                        TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; player: mediaPlayer; editable: true }
                    }
                    MediaPlayer { id: mediaPlayer; source: bridge.mediaUrl; videoOutput: mediaVideo; audioOutput: AudioOutput { id: mediaAudio } }
                }

                Item {
                    ColumnLayout {
                        anchors.fill: parent; spacing: 12
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 185; radius: 20
                            color: "#17181c"; border.color: "#2c2e35"
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 18; spacing: 8
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: "Ключевые слова"; color: "#e8e9e9"; font.pixelSize: 12; Layout.preferredWidth: 120 }
                                    TextField { Layout.fillWidth: true; placeholderText: "Например: выборы, ставка, Whisper"; text: bridge.settings.keywords; enabled: !bridge.busy; onEditingFinished: bridge.setSetting("keywords", text) }
                                }
                                TextArea { Layout.fillWidth: true; Layout.fillHeight: true; placeholderText: "Название | https://прямая-ссылка-на-эфир\nДо четырёх HTTP(S)-потоков, один на строку"; text: bridge.settings.channels; enabled: !bridge.busy; wrapMode: TextEdit.Wrap; onActiveFocusChanged: if (!activeFocus) bridge.setSetting("channels", text) }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Button { text: root.startLabel(); enabled: !bridge.busy || bridge.recording; onClicked: bridge.toggleRecording() }
                                    Button { visible: bridge.busy; text: "Остановить"; onClicked: bridge.toggleRecording() }
                                    Item { Layout.fillWidth: true }
                                    Label { text: "Совпадений: " + bridge.hits.length; color: "#9b9ea6" }
                                }
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true; Layout.fillHeight: true; radius: 18; color: "#17181c"; border.color: "#2c2e35"
                            Label { visible: bridge.hits.length === 0; anchors.centerIn: parent; text: "Совпадения по словам появятся здесь"; color: "#777981" }
                            ListView {
                                anchors.fill: parent; anchors.margins: 10; clip: true; spacing: 7; model: bridge.hits
                                delegate: Rectangle {
                                    required property var modelData
                                    width: ListView.view.width; implicitHeight: eventText.implicitHeight + 28; radius: 12; color: "#1e2026"
                                    ColumnLayout {
                                        anchors.fill: parent; anchors.margins: 12; spacing: 4
                                        Label { text: modelData.source + " · " + modelData.matches; color: "#b8bdc7"; font.pixelSize: 11 }
                                        Label { id: eventText; text: modelData.text; color: "#eceeec"; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    }
                                    TapHandler { onTapped: bridge.openSession(modelData.session_id) }
                                }
                                ScrollBar.vertical: ScrollBar { }
                            }
                        }
                    }
                }

                Item {
                    ColumnLayout {
                        anchors.fill: parent; spacing: 12
                        TextField { Layout.fillWidth: true; placeholderText: "Поиск по названию и тексту"; onTextChanged: bridge.refreshHistory(text) }
                        Label { text: bridge.history.length ? "Выберите сессию, чтобы открыть текст или медиа." : "История пока пуста."; color: "#93969f"; font.pixelSize: 12 }
                        ListView {
                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 8; model: bridge.history
                            delegate: Button {
                                id: historyButton
                                required property var modelData
                                width: ListView.view.width; implicitHeight: 70; onClicked: bridge.openSession(modelData.id)
                                contentItem: ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 13; spacing: 2
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Label { text: modelData.title; color: "#e9eae9"; font.pixelSize: 14; font.weight: Font.DemiBold }
                                        Item { Layout.fillWidth: true }
                                        Label { text: modelData.mode + " · " + modelData.segment_count + " фраз"; color: "#a2a5ad"; font.pixelSize: 11 }
                                    }
                                    Label { text: modelData.text || "Нет распознанного текста"; color: "#777b84"; elide: Text.ElideRight; Layout.fillWidth: true; maximumLineCount: 1 }
                                }
                                background: Rectangle { radius: 14; color: historyButton.hovered ? "#22242a" : "#191a1e"; border.color: "#2b2d34" }
                            }
                            ScrollBar.vertical: ScrollBar { }
                        }
                    }
                }

                Item {
                    Flickable {
                        anchors.fill: parent; contentWidth: width; contentHeight: settingsColumn.implicitHeight + 20; clip: true
                        ColumnLayout {
                            id: settingsColumn; width: parent.width; spacing: 14
                            Label { text: "Распознавание"; color: "#f0f1ef"; font.pixelSize: 18; font.weight: Font.DemiBold }
                            GridLayout {
                                columns: 2; columnSpacing: 16; rowSpacing: 10
                                Repeater {
                                    model: [
                                        {key:"profile", title:"Профиль", values:["fast","balanced","quality"]},
                                        {key:"model", title:"Модель", values:["tiny","base","small","medium","large-v3","turbo"]},
                                        {key:"device", title:"Устройство", values:["auto","cpu","cuda"]},
                                        {key:"language", title:"Язык", values:["auto","ru","en","de","es","fr","zh"]},
                                        {key:"task", title:"Задача", values:["transcribe","translate"]},
                                        {key:"backend", title:"Обработка", values:["local","remote"]}
                                    ]
                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Label { text: modelData.title; color: "#a9acb4"; Layout.preferredWidth: 105 }
                                        ComboBox { Layout.fillWidth: true; model: modelData.values; currentIndex: modelData.values.indexOf(bridge.settings[modelData.key]); enabled: !bridge.busy; onActivated: bridge.setSetting(modelData.key, currentText) }
                                    }
                                }
                            }
                            Label { text: "Сервер"; color: "#f0f1ef"; font.pixelSize: 18; font.weight: Font.DemiBold; Layout.topMargin: 16 }
                            TextField { Layout.fillWidth: true; placeholderText: "http://127.0.0.1:8765"; text: bridge.settings.server_url; enabled: !bridge.busy; onEditingFinished: bridge.setSetting("server_url", text) }
                            Label { text: "Локальная обработка хранит аудио на устройстве. В удалённом режиме файл или аудиофрагмент отправляется по указанному адресу."; color: "#92959e"; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: "Источники"; color: "#f0f1ef"; font.pixelSize: 18; font.weight: Font.DemiBold; Layout.topMargin: 16 }
                            RowLayout {
                                RadioButton { text: "Микрофон"; checked: bridge.settings.source === "microphone"; enabled: !bridge.busy; onToggled: if (checked) bridge.setSetting("source", "microphone") }
                                RadioButton { text: "Системный звук"; checked: bridge.settings.source === "system"; enabled: !bridge.busy; onToggled: if (checked) bridge.setSetting("source", "system") }
                            }
                            Label { text: "Режим " + (bridge.settings.source === "system" ? "системного звука" : "микрофона") + " зависит от доступности устройства и драйверов Windows."; color: "#92959e"; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Button { text: "Копировать текст"; enabled: bridge.segments.length > 0; onClicked: bridge.copyText() }
                Repeater { model: ["txt", "srt", "vtt", "json"]; delegate: Button { required property string modelData; text: modelData.toUpperCase(); enabled: bridge.segments.length > 0; onClicked: bridge.exportFile(modelData) } }
                Item { Layout.fillWidth: true }
                Label { text: bridge.segments.length ? bridge.segments.length + " сегм." : ""; color: "#777981"; font.pixelSize: 11 }
            }
        }
    }

    Window {
        id: island
        width: 530; height: 138; visible: false; color: "transparent"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        x: Screen.width / 2 - width / 2; y: 36
        Rectangle {
            anchors.fill: parent; radius: 30; color: "#f113151a"; border.color: "#4b4e56"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 18; spacing: 7
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: ".аудио"; color: "#eef0ed"; font.bold: true; font.pixelSize: 13 }
                    Item { Layout.fillWidth: true }
                    Label { text: bridge.recording ? "● СЛУШАЮ" : bridge.status; color: bridge.recording ? "#eef0ed" : "#aeb1b9"; font.pixelSize: 10 }
                }
                Label { text: bridge.caption; color: "#f5f6f5"; font.pixelSize: 19; maximumLineCount: 2; wrapMode: Text.Wrap; elide: Text.ElideRight; Layout.fillWidth: true; Layout.fillHeight: true }
                ProgressBar { Layout.fillWidth: true; from: 0; to: 0.25; value: bridge.level; visible: bridge.recording }
            }
            TapHandler { onDoubleTapped: island.visible = false }
        }
    }

    Connections { target: bridge; function onIslandRequested() { island.visible = !island.visible } }
}
