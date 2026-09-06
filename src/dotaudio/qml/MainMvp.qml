import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtMultimedia

ApplicationWindow {
    id: root
    property bool compactMode: true
    property bool restorePosition: false
    property var nav: [
        { key: "live", icon: "◉", title: "Live-субтитры", hint: "главный режим" },
        { key: "dictation", icon: "✦", title: "Диктовка", hint: "голос в буфер" },
        { key: "media", icon: "▣", title: "Караоке", hint: "аудио и видео" },
        { key: "models", icon: "⌁", title: "Модели", hint: "скачать заранее" },
        { key: "history", icon: "◷", title: "История", hint: "локальные сессии" },
        { key: "settings", icon: "⚙", title: "Настройки", hint: "звук и остров" }
    ]
    property int pageIndex: ["live", "dictation", "media", "models", "history", "settings"].indexOf(bridge.page)
    width: compactMode ? 580 : 1280
    height: compactMode ? 164 : 820
    minimumWidth: compactMode ? 500 : 960
    minimumHeight: compactMode ? 144 : 650
    visible: true
    title: "DotAudio"
    color: compactMode ? "transparent" : "#0b0d10"
    flags: compactMode ? (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint) : Qt.Window
    opacity: compactMode ? Number(bridge.settings.island_opacity) : 1
    font.family: "Segoe UI"
    font.pointSize: 10

    function openWorkspace(page) {
        if (page) bridge.selectPage(page)
        bridge.applyIslandClickThrough(false)
        compactMode = false
    }
    function closeWorkspace() {
        compactMode = true
        bridge.applyIslandClickThrough(Boolean(bridge.settings.island_click_through))
    }
    function levelColor() {
        if (bridge.recording) return "#ff5f7b"
        if (bridge.busy || bridge.modelPreparing) return "#f4b860"
        return "#73e2b7"
    }
    function shortCaption() {
        if (bridge.caption.length) return bridge.caption
        if (bridge.recording) return "Слушаю речь и жду первую завершённую фразу"
        if (bridge.modelPreparing) return bridge.modelState.message
        return "Нажмите запись - текст появится после первой фразы"
    }
    function timestamp(milliseconds) {
        var total = Math.max(0, Math.floor(milliseconds / 1000))
        var h = Math.floor(total / 3600)
        var m = Math.floor((total % 3600) / 60)
        var s = total % 60
        return (h > 0 ? (h < 10 ? "0" : "") + h + ":" : "")
             + (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
    }

    Component.onCompleted: {
        if (Number(bridge.settings.island_x) >= 0) {
            x = Number(bridge.settings.island_x)
            y = Number(bridge.settings.island_y)
        }
        bridge.applyIslandClickThrough(Boolean(bridge.settings.island_click_through))
    }
    onClosing: function(close) { if (bridge.busy) { close.accepted = false; bridge.cancel() } }
    Shortcut { sequence: "Escape"; enabled: bridge.busy; onActivated: bridge.cancel() }
    Connections {
        target: bridge
        function onIslandRequested() { root.compactMode = true; bridge.applyIslandClickThrough(Boolean(bridge.settings.island_click_through)) }
    }

    Rectangle {
        id: island
        visible: root.compactMode
        anchors.fill: parent
        radius: 32
        color: "#15171bcc"
        border.width: 1
        border.color: bridge.recording ? "#ff6c85" : bridge.busy ? "#f4b860" : "#3a424e"
        layer.enabled: true

        Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.color: "#ffffff14"; border.width: 1 }
        MouseArea {
            id: islandDrag
            anchors { left: parent.left; right: parent.right; top: parent.top; bottom: parent.bottom }
            anchors.rightMargin: 168
            z: 1
            drag.target: root
            drag.minimumX: 0; drag.minimumY: 0
            onReleased: bridge.saveIslandPosition(root.x, root.y)
        }
        RowLayout {
            z: 2
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14
            Button {
                id: recordButton
                Layout.preferredWidth: 58; Layout.preferredHeight: 58
                text: bridge.recording ? "■" : "●"
                onClicked: bridge.toggleRecording()
                contentItem: Text { text: recordButton.text; color: "#111318"; font.pixelSize: bridge.recording ? 16 : 26; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 29; color: root.levelColor(); Behavior on color { ColorAnimation { duration: 180 } } }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 5
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: bridge.recording ? "LIVE · запись" : bridge.busy ? "WHISPER · обработка" : "DOTAUDIO · готов"; color: root.levelColor(); font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.3 }
                    Item { Layout.fillWidth: true }
                    Label { text: bridge.elapsed; color: "#aeb6c4"; font.family: "Consolas"; font.pixelSize: 11; visible: bridge.recording || bridge.busy }
                }
                Text {
                    Layout.fillWidth: true; text: root.shortCaption(); color: "#f2f5f7"; font.pixelSize: 15; font.weight: Font.DemiBold
                    elide: Text.ElideRight; maximumLineCount: 1
                }
                Row {
                    Layout.fillWidth: true; spacing: 3; height: 22
                    Repeater {
                        model: 42
                        delegate: Rectangle {
                            required property int index
                            width: 4; radius: 2; anchors.verticalCenter: parent.verticalCenter
                            property real pulse: 0.18 + Math.abs(Math.sin(index * 1.73)) * 0.82
                            height: 3 + (bridge.recording ? (8 + bridge.level * 25 * pulse) : bridge.busy ? 8 * pulse : 3)
                            color: bridge.recording ? "#ff7890" : bridge.busy ? "#f4b860" : "#52606d"
                            Behavior on height { NumberAnimation { duration: 90 } }
                            SequentialAnimation on opacity { running: bridge.recording; loops: Animation.Infinite; NumberAnimation { to: 0.45; duration: 370 + index * 14 } NumberAnimation { to: 1; duration: 370 + index * 14 } }
                        }
                    }
                }
            }
            Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 58; color: "#ffffff16" }
            Button {
                Layout.preferredWidth: 42; Layout.preferredHeight: 42; text: "⌁"
                onClicked: root.openWorkspace("models")
                contentItem: Text { text: "⌁"; color: "#dce3ed"; font.pixelSize: 22; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 15; color: parent.hovered ? "#2a3039" : "#20242b" }
            }
            Button {
                Layout.preferredWidth: 42; Layout.preferredHeight: 42; text: "↗"
                onClicked: root.openWorkspace("live")
                contentItem: Text { text: "↗"; color: "#dce3ed"; font.pixelSize: 21; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 15; color: parent.hovered ? "#2a3039" : "#20242b" }
            }
        }
    }

    RowLayout {
        visible: !root.compactMode
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.preferredWidth: 244; Layout.fillHeight: true; color: "#111319"; border.color: "#252a33"; border.width: 1
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 18; spacing: 8
                RowLayout {
                    Layout.fillWidth: true; spacing: 10
                    Rectangle { width: 42; height: 42; radius: 15; color: "#f1f5f9"; Label { anchors.centerIn: parent; text: ".a"; color: "#101217"; font.pixelSize: 16; font.bold: true } }
                    ColumnLayout { spacing: 0; Label { text: ".аудио"; color: "#f4f6f8"; font.pixelSize: 22; font.bold: true } Label { text: "DOTCORE / WHISPER"; color: "#7d8999"; font.pixelSize: 9; font.letterSpacing: 1.4 } }
                }
                Label { text: "РУССКАЯ РЕЧЬ · LIVE FIRST"; color: "#6f7f92"; font.pixelSize: 9; font.letterSpacing: 1.1; Layout.topMargin: 18; Layout.bottomMargin: 6 }
                Repeater {
                    model: root.nav
                    delegate: Button {
                        required property var modelData
                        Layout.fillWidth: true; Layout.preferredHeight: 52; text: modelData.title
                        onClicked: bridge.selectPage(modelData.key)
                        contentItem: RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 10; spacing: 10
                            Label { text: modelData.icon; color: bridge.page === modelData.key ? "#12151a" : "#91a0b2"; font.pixelSize: 18; Layout.preferredWidth: 22; horizontalAlignment: Text.AlignHCenter }
                            ColumnLayout { Layout.fillWidth: true; spacing: 0; Label { text: modelData.title; color: bridge.page === modelData.key ? "#12151a" : "#ecf0f5"; font.pixelSize: 13; font.bold: true } Label { text: modelData.hint; color: bridge.page === modelData.key ? "#4a5664" : "#758193"; font.pixelSize: 10 } }
                        }
                        background: Rectangle { radius: 14; color: bridge.page === modelData.key ? "#eaf1f4" : parent.hovered ? "#1b2028" : "transparent" }
                    }
                }
                Item { Layout.fillHeight: true }
                Rectangle {
                    Layout.fillWidth: true; Layout.preferredHeight: 86; radius: 16; color: "#181d25"; border.color: "#28313d"
                    ColumnLayout { anchors.fill: parent; anchors.margins: 12; spacing: 4; Label { text: bridge.hotkeysAvailable ? "Глобальные клавиши включены" : "Глобальная клавиша занята"; color: "#dce5ee"; font.pixelSize: 11; font.bold: true } Label { text: "Ctrl + Alt + Space - запись\nCtrl + Alt + O - остров"; color: "#8290a0"; font.pixelSize: 10 } }
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 28; spacing: 16
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout { spacing: 2; Label { text: ({live:"Live-субтитры", dictation:"Диктовка", media:"Караоке-студия", models:"Модели Whisper", history:"История", settings:"Настройки"})[bridge.page]; color: "#f3f5f8"; font.pixelSize: 28; font.bold: true } Label { text: bridge.status; color: "#8d9aaa"; font.pixelSize: 12 } }
                Item { Layout.fillWidth: true }
                Button { text: "Журнал"; onClicked: logDrawer.open(); contentItem: Text { text: "Журнал"; color: "#d6dfe9"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } background: Rectangle { radius: 14; color: parent.hovered ? "#28303b" : "#1c222b" } }
                Button { text: "Свернуть"; onClicked: root.closeWorkspace(); contentItem: Text { text: "Свернуть"; color: "#101318"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } background: Rectangle { radius: 14; color: "#e6eef0" } }
            }
            Rectangle { visible: bridge.notice.length > 0; Layout.fillWidth: true; implicitHeight: notice.implicitHeight + 22; radius: 14; color: "#2b2523"; border.color: "#5e4638"; Label { id: notice; anchors.fill: parent; anchors.margins: 11; text: bridge.notice; color: "#f6ded1"; wrapMode: Text.Wrap; font.pixelSize: 12 } TapHandler { onTapped: bridge.clearNotice() } }
            StackLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; currentIndex: root.pageIndex < 0 ? 0 : root.pageIndex
                // Live
                Item {
                    ColumnLayout { anchors.fill: parent; spacing: 14
                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 270; radius: 24; color: "#14181f"; border.color: bridge.recording ? "#7e4052" : "#273240"; border.width: 1
                            ColumnLayout { anchors.fill: parent; anchors.margins: 26; spacing: 10
                                RowLayout { Layout.fillWidth: true; Label { text: bridge.recording ? "Эфир в работе" : "Готов к прямым субтитрам"; color: "#f5f7fa"; font.pixelSize: 23; font.bold: true } Item { Layout.fillWidth: true } Rectangle { width: 12; height: 12; radius: 6; color: root.levelColor(); SequentialAnimation on opacity { running: bridge.recording; loops: Animation.Infinite; NumberAnimation { to: 0.25; duration: 600 } NumberAnimation { to: 1; duration: 600 } } } }
                                Text { Layout.fillWidth: true; text: bridge.caption.length ? bridge.caption : "Начните запись. После первой законченной фразы текст появится здесь, а не в пустом поле."; color: bridge.caption.length ? "#ffffff" : "#94a1b1"; font.pixelSize: bridge.caption.length ? 30 : 17; font.weight: bridge.caption.length ? Font.DemiBold : Font.Normal; wrapMode: Text.Wrap; maximumLineCount: 3; Behavior on opacity { NumberAnimation { duration: 220 } } }
                                Text { visible: bridge.settings.task === "translate"; text: "Перевод в English выполняет Whisper Translate"; color: "#8cd8c2"; font.pixelSize: 11; font.letterSpacing: 0.4 }
                                Item { Layout.fillHeight: true }
                                RowLayout { Layout.fillWidth: true; Button { id: liveStart; text: bridge.recording ? "Завершить и сохранить" : "Начать live"; enabled: !bridge.busy || bridge.recording; onClicked: bridge.toggleRecording(); contentItem: Text { text: liveStart.text; color: "#101318"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter } background: Rectangle { radius: 17; color: root.levelColor() } } Button { visible: bridge.busy; text: "Отмена"; onClicked: bridge.cancel() } Item { Layout.fillWidth: true } Label { text: bridge.elapsed; color: "#d6dce5"; font.family: "Consolas"; font.pixelSize: 18 } }
                                Row { Layout.fillWidth: true; height: 28; spacing: 4; Repeater { model: 64; delegate: Rectangle { required property int index; width: 5; radius: 3; anchors.verticalCenter: parent.verticalCenter; property real texture: 0.25 + Math.abs(Math.sin(index * 2.17)) * 0.75; height: 3 + bridge.level * 25 * texture; color: bridge.recording ? "#ff607e" : "#33404e"; Behavior on height { NumberAnimation { duration: 85 } } } } }
                            }
                        }
                        TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; editable: false; showEmptyHint: false }
                    }
                }
                // Dictation
                Item {
                    ColumnLayout { anchors.fill: parent; spacing: 14
                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 230; radius: 24; color: "#151a21"; border.color: "#293544"
                            ColumnLayout { anchors.fill: parent; anchors.margins: 24; spacing: 10; Label { text: bridge.recording ? "Говорите спокойно" : "Голос в текст и буфер обмена"; color: "#f4f7fa"; font.pixelSize: 24; font.bold: true } Label { text: "Результат останется в истории. Запуск по Ctrl + Alt + Space бережно вставит текст в предыдущее окно, если оно сохранило фокус."; color: "#99a6b6"; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true } Item { Layout.fillHeight: true } RowLayout { Layout.fillWidth: true; Button { text: bridge.recording ? "Завершить" : "Записать"; onClicked: bridge.toggleRecording() } Button { text: "Копировать текст"; enabled: bridge.text.length > 0; onClicked: bridge.copyText() } Item { Layout.fillWidth: true } Switch { text: "Автовставка"; checked: bridge.settings.auto_paste; onToggled: bridge.setSetting("auto_paste", checked) } } }
                        }
                        TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; editable: true; showEmptyHint: true }
                    }
                }
                // Karaoke media
                Item {
                    RowLayout { anchors.fill: parent; spacing: 14
                        ColumnLayout { Layout.preferredWidth: parent.width * 0.53; Layout.fillHeight: true; spacing: 12
                            Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; radius: 24; color: "#10141a"; border.color: "#293543"
                                VideoOutput { id: mediaVideo; anchors.fill: parent; anchors.margins: 8; fillMode: VideoOutput.PreserveAspectFit; visible: mediaPlayer.hasVideo }
                                ColumnLayout { anchors.centerIn: parent; width: parent.width - 70; visible: !bridge.mediaUrl; Label { text: "Аудио в караоке-субтитры"; color: "#f3f6f9"; font.pixelSize: 23; font.bold: true; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true } Label { text: "Откройте аудио или видео. Word timestamps сохранятся вместе с расшифровкой и сформируют анимированный ASS-трек."; color: "#94a2b1"; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true } Button { text: "Выбрать медиа"; Layout.alignment: Qt.AlignHCenter; onClicked: bridge.importFile() } }
                                Rectangle { visible: bridge.mediaUrl.length > 0; anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 24 } height: 94; radius: 18; color: "#101216e8"; border.color: "#ffffff20"; ColumnLayout { anchors.fill: parent; anchors.margins: 12; RowLayout { Layout.fillWidth: true; Text { text: bridge.caption.length ? bridge.caption : "Караоке появится после распознавания"; color: "#ffffff"; font.pixelSize: 19; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true } } Slider { Layout.fillWidth: true; from: 0; to: Math.max(1, mediaPlayer.duration); value: mediaPlayer.position; onMoved: mediaPlayer.position = value } } }
                            }
                            RowLayout { Layout.fillWidth: true; Button { text: "Открыть файл"; enabled: !bridge.busy; onClicked: bridge.importFile() } Button { text: mediaPlayer.playbackState === MediaPlayer.PlayingState ? "Пауза" : "Воспроизвести"; visible: bridge.mediaUrl.length > 0; onClicked: mediaPlayer.playbackState === MediaPlayer.PlayingState ? mediaPlayer.pause() : mediaPlayer.play() } Button { text: "Обложка"; visible: bridge.mediaUrl.length > 0; onClicked: bridge.chooseCover() } Button { text: "Экспорт ASS"; enabled: bridge.segments.length > 0; onClicked: bridge.exportKaraokeFile() } Button { text: bridge.rendering ? "Рендер…" : "MP4"; enabled: bridge.segments.length > 0 && !bridge.rendering; onClicked: bridge.exportKaraokeVideo() } Item { Layout.fillWidth: true } Label { text: root.timestamp(mediaPlayer.position); color: "#98a6b6"; font.family: "Consolas" } }
                        }
                        TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; player: mediaPlayer; editable: true; showEmptyHint: true }
                    }
                    MediaPlayer { id: mediaPlayer; source: bridge.mediaUrl; videoOutput: mediaVideo; audioOutput: AudioOutput {} }
                }
                // Models
                Item {
                    Flickable { anchors.fill: parent; contentWidth: width; contentHeight: modelsColumn.implicitHeight; clip: true
                        ColumnLayout { id: modelsColumn; width: parent.width; spacing: 14
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 112; radius: 20; color: "#15211f"; border.color: "#285048"; RowLayout { anchors.fill: parent; anchors.margins: 18; Rectangle { width: 44; height: 44; radius: 15; color: "#73e2b7"; Label { anchors.centerIn: parent; text: bridge.modelPreparing ? "…" : "✓"; color: "#102019"; font.pixelSize: 22; font.bold: true } } ColumnLayout { Layout.fillWidth: true; Label { text: bridge.modelState.message; color: "#eaf8f2"; font.pixelSize: 15; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true } Label { text: "Подготовка идёт в фоне. Скачивание требуется только один раз для локальной модели."; color: "#8fc3b1"; font.pixelSize: 11 } } BusyIndicator { running: bridge.modelPreparing; visible: running } } }
                            Repeater { model: [ {id:"tiny", title:"tiny", hint:"самый быстрый, демонстрация"}, {id:"base", title:"base", hint:"рекомендуется для live"}, {id:"small", title:"small", hint:"точнее русская речь"}, {id:"medium", title:"medium", hint:"мощный ПК или GPU"}, {id:"large-v3", title:"large-v3", hint:"максимум качества"}, {id:"turbo", title:"turbo", hint:"быстрый крупный вариант"} ]; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 78; radius: 18; color: bridge.settings.model === modelData.id ? "#202b32" : "#151a21"; border.color: bridge.settings.model === modelData.id ? "#71c9b2" : "#2a333f"; RowLayout { anchors.fill: parent; anchors.margins: 15; ColumnLayout { Layout.fillWidth: true; Label { text: modelData.title; color: "#f2f6f8"; font.pixelSize: 16; font.bold: true } Label { text: modelData.hint; color: "#94a3b2"; font.pixelSize: 11 } } Button { text: bridge.settings.model === modelData.id ? "Выбрана" : "Выбрать"; enabled: !bridge.busy; onClicked: bridge.setSetting("model", modelData.id) } Button { text: bridge.modelPreparing && bridge.modelState.model === modelData.id ? "Готовим…" : "Скачать"; enabled: !bridge.busy && !bridge.modelPreparing; onClicked: { bridge.setSetting("model", modelData.id); bridge.prepareSelectedModel() } } } } }
                        }
                    }
                }
                // History
                Item {
                    ColumnLayout { anchors.fill: parent; spacing: 12; TextField { Layout.fillWidth: true; placeholderText: "Поиск по истории"; color: "#edf2f6"; onTextChanged: bridge.refreshHistory(text); background: Rectangle { radius: 14; color: "#181e26"; border.color: "#2c3846" } } ListView { Layout.fillWidth: true; Layout.fillHeight: true; model: bridge.history; spacing: 7; clip: true; ScrollBar.vertical: ScrollBar {} delegate: Rectangle { required property var modelData; width: ListView.view.width; height: 74; radius: 16; color: "#161b22"; border.color: "#293340"; MouseArea { anchors.fill: parent; onClicked: bridge.openSession(modelData.id) } Column { anchors.fill: parent; anchors.margins: 12; spacing: 3; Text { text: modelData.title; color: "#edf2f6"; font.pixelSize: 14; font.bold: true } Text { text: modelData.mode + " · " + modelData.segment_count + " сегм. · " + modelData.text; color: "#93a1b1"; font.pixelSize: 11; elide: Text.ElideRight; width: parent.width } } } } }
                }
                // Settings
                Item {
                    Flickable { anchors.fill: parent; contentWidth: width; contentHeight: settingsColumn.implicitHeight; clip: true
                        ColumnLayout { id: settingsColumn; width: parent.width; spacing: 14
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 154; radius: 20; color: "#151b22"; border.color: "#2b3744"; ColumnLayout { anchors.fill: parent; anchors.margins: 17; Label { text: "Речь и перевод"; color: "#f0f4f7"; font.pixelSize: 16; font.bold: true } RowLayout { Layout.fillWidth: true; Label { text: "Язык распознавания"; color: "#a9b5c1"; Layout.preferredWidth: 175 } ComboBox { Layout.preferredWidth: 240; model: [{id:"ru",name:"Русский"},{id:"auto",name:"Автоопределение"},{id:"en",name:"English"}]; textRole:"name"; currentIndex: bridge.settings.language === "ru" ? 0 : bridge.settings.language === "auto" ? 1 : 2; onActivated: bridge.setSetting("language", model[currentIndex].id) } Item { Layout.fillWidth: true } } RowLayout { Layout.fillWidth: true; Label { text: "Вывод субтитров"; color: "#a9b5c1"; Layout.preferredWidth: 175 } ComboBox { Layout.preferredWidth: 240; model: [{id:"transcribe",name:"Исходный язык"},{id:"translate",name:"English через Whisper"}]; textRole:"name"; currentIndex: bridge.settings.task === "translate" ? 1 : 0; onActivated: bridge.setSetting("task", model[currentIndex].id) } Label { text: "Whisper Translate переводит на английский"; color: "#718091"; font.pixelSize: 10 } } } }
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 236; radius: 20; color: "#151b22"; border.color: "#2b3744"; ColumnLayout { anchors.fill: parent; anchors.margins: 17; spacing: 8; RowLayout { Layout.fillWidth: true; Label { text: "Микрофон и наушники"; color: "#f0f4f7"; font.pixelSize: 16; font.bold: true } Item { Layout.fillWidth: true } Button { text: "Обновить"; onClicked: { bridge.refreshDevices(); bridge.refreshOutputs() } } } RowLayout { Layout.fillWidth: true; Label { text: "Вход"; color: "#a9b5c1"; Layout.preferredWidth: 68 } ComboBox { Layout.fillWidth: true; model: [{id:"",name:"Системный микрофон"}].concat(bridge.devices); textRole:"name"; currentIndex: { for (var i=0; i<model.length; ++i) if (String(model[i].id) === String(bridge.settings.input_device)) return i; return 0 } onActivated: bridge.setSetting("input_device", String(model[currentIndex].id)) } Button { text: "Тест 3 сек"; onClicked: bridge.testMicrophone() } } RowLayout { Layout.fillWidth: true; Label { text: "Выход"; color: "#a9b5c1"; Layout.preferredWidth: 68 } ComboBox { Layout.fillWidth: true; model: [{id:"",name:"Системный вывод"}].concat(bridge.outputs); textRole:"name"; currentIndex: { for (var i=0; i<model.length; ++i) if (String(model[i].id) === String(bridge.settings.output_device)) return i; return 0 } onActivated: bridge.setSetting("output_device", String(model[currentIndex].id)) } Button { text: "Тон"; onClicked: bridge.testOutputDevice() } } ProgressBar { Layout.fillWidth: true; from: 0; to: 0.35; value: bridge.deviceTest.level; visible: bridge.deviceTest.phase === "listening" } Label { text: bridge.deviceTest.message || "Тест не записывает и не сохраняет аудио."; color: bridge.deviceTest.phase === "error" ? "#ff9da9" : "#8393a4"; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true } } }
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 205; radius: 20; color: "#151b22"; border.color: "#2b3744"; ColumnLayout { anchors.fill: parent; anchors.margins: 17; spacing: 7; Label { text: "Мини-островок"; color: "#f0f4f7"; font.pixelSize: 16; font.bold: true } RowLayout { Layout.fillWidth: true; Label { text: "Прозрачность"; color: "#a9b5c1"; Layout.preferredWidth: 130 } Slider { Layout.fillWidth: true; from: 0.35; to: 1; value: Number(bridge.settings.island_opacity); onMoved: bridge.setSetting("island_opacity", value) } Label { text: Math.round(Number(bridge.settings.island_opacity)*100) + "%"; color: "#dce4ec"; Layout.preferredWidth: 40 } } Switch { text: "Пропускать клики сквозь остров"; checked: Boolean(bridge.settings.island_click_through); onToggled: bridge.setIslandClickThrough(checked) } Switch { text: "Запоминать позицию острова"; checked: Boolean(bridge.settings.island_snap); onToggled: bridge.setSetting("island_snap", checked) } Label { text: "При пропуске кликов верните рабочее окно горячей клавишей Ctrl + Alt + O."; color: "#718192"; font.pixelSize: 10 } } }
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 104; radius: 20; color: "#151b22"; border.color: "#2b3744"; RowLayout { anchors.fill: parent; anchors.margins: 17; ColumnLayout { Layout.fillWidth: true; Label { text: "Профиль качества"; color: "#f0f4f7"; font.pixelSize: 16; font.bold: true } Label { text: "Fast уменьшает задержку, quality увеличивает точность и нагрузку."; color: "#8392a2"; font.pixelSize: 11 } } ComboBox { model: [{id:"fast",name:"Fast"},{id:"balanced",name:"Balanced"},{id:"quality",name:"Quality"}]; textRole:"name"; currentIndex: bridge.settings.profile === "fast" ? 0 : bridge.settings.profile === "quality" ? 2 : 1; onActivated: bridge.setSetting("profile", model[currentIndex].id) } } }
                        }
                    }
                }
            }
        }
    }
    Drawer { id: logDrawer; parent: root.contentItem; width: Math.min(440, root.width * .86); height: parent.height; edge: Qt.Right; modal: true; background: Rectangle { color: "#12171e"; border.color: "#2c3947" } ColumnLayout { anchors.fill: parent; anchors.margins: 18; Label { text: "Журнал работы"; color: "#f2f5f8"; font.pixelSize: 20; font.bold: true } Label { text: "Статусы, модель и сохранение сегментов"; color: "#8493a2"; font.pixelSize: 11 } ListView { Layout.fillWidth: true; Layout.fillHeight: true; model: bridge.logs; spacing: 8; clip: true; delegate: Rectangle { required property var modelData; width: ListView.view.width; implicitHeight: logText.implicitHeight + 18; radius: 12; color: modelData.tone === "error" ? "#352126" : modelData.tone === "success" ? "#1c302b" : modelData.tone === "warning" ? "#352f20" : "#1a212a"; Text { id: logText; anchors.fill: parent; anchors.margins: 9; text: modelData.time + "  " + modelData.message; color: "#dce5ed"; font.pixelSize: 11; wrapMode: Text.Wrap } } } } }
}
