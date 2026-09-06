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
    property color accent: bridge.recording ? "#ff375f" : bridge.busy || bridge.modelPreparing ? "#ff9f0a" : "#0a84ff"
    property real recordingPhase: 0
    width: compact ? 604 : 1220
    height: compact ? 132 : 790
    minimumWidth: compact ? 520 : 1000
    minimumHeight: compact ? 120 : 660
    visible: true
    color: compact ? "transparent" : "#000000"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    opacity: compact ? Math.max(0.9, Number(bridge.settings.island_opacity)) : 1
    font.family: "Segoe UI Variable Display"

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
        function onIslandRequested() {
            root.compact = true
            root.show()
            root.raise()
            root.requestActivate()
        }
    }
    Shortcut { sequence: "Escape"; enabled: bridge.busy; onActivated: bridge.cancel() }
    Timer {
        interval: 70
        running: bridge.recording
        repeat: true
        onTriggered: root.recordingPhase += 0.32
    }

    component IconButton: Button {
        id: control
        property color ink: "#f5f5f7"
        implicitWidth: 38
        implicitHeight: 38
        hoverEnabled: true
        contentItem: Text { text: control.text; color: control.enabled ? control.ink : "#6e6e73"; font.family: "Segoe UI Symbol"; font.pixelSize: 17; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: width / 2; color: control.down ? "#30ffffff" : control.hovered ? "#1fffffff" : "#10ffffff"; Behavior on color { ColorAnimation { duration: 130 } } }
    }
    component ActionButton: Button {
        id: control
        property bool primary: false
        property color tint: root.accent
        implicitHeight: 38
        leftPadding: 15
        rightPadding: 15
        hoverEnabled: true
        contentItem: Text { text: control.text; color: control.primary ? "#ffffff" : control.enabled ? "#f5f5f7" : "#6e6e73"; font.pixelSize: 12; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: 19; color: control.primary ? (control.down ? Qt.darker(control.tint, 1.2) : control.hovered ? Qt.lighter(control.tint, 1.08) : control.tint) : control.down ? "#26ffffff" : control.hovered ? "#19ffffff" : "#0effffff"; border.width: control.primary ? 0 : 1; border.color: "#16ffffff"; Behavior on color { ColorAnimation { duration: 130 } } }
    }
    component Waveform: Item {
        id: wave
        property int bars: 48
        property real inputLevel: Math.min(1, Math.max(0, bridge.level * 28))
        implicitHeight: 28
        Row {
            anchors.centerIn: parent
            spacing: 3
            Repeater {
                model: wave.bars
                delegate: Rectangle {
                    required property int index
                    property real shape: 0.18 + Math.abs(Math.sin(index * 1.71)) * 0.82
                    width: 3
                    height: bridge.recording ? 3 + wave.inputLevel * 34 * shape : 3
                    radius: 2
                    color: bridge.recording ? root.accent : "#22ffffff"
                    anchors.verticalCenter: parent.verticalCenter
                    Behavior on height { NumberAnimation { duration: 90 } }
                    Behavior on color { ColorAnimation { duration: 180 } }
                }
            }
        }
    }

    Rectangle {
        visible: root.compact
        anchors.fill: parent
        radius: 32
        color: "#1d1d1f"
        border.width: 1
        border.color: bridge.recording ? "#88ff375f" : "#1effffff"
        Rectangle { anchors.fill: parent; anchors.margins: 1; radius: 31; color: "transparent"; border.width: 1; border.color: "#0bffffff" }
        MouseArea { anchors.fill: parent; z: 0; onPressed: root.startSystemMove(); onReleased: bridge.saveIslandPosition(root.x, root.y) }
        RowLayout {
            z: 1
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 12
            Button {
                id: islandRecord
                Layout.preferredWidth: 54
                Layout.preferredHeight: 54
                hoverEnabled: true
                onClicked: bridge.toggleRecording()
                contentItem: Item { Rectangle { anchors.centerIn: parent; width: bridge.recording ? 17 : 18; height: bridge.recording ? 17 : 18; radius: bridge.recording ? 5 : 9; color: "#ffffff"; Behavior on width { NumberAnimation { duration: 140 } } Behavior on height { NumberAnimation { duration: 140 } } } }
                background: Item {
                    Rectangle {
                        anchors.centerIn: parent
                        width: 54
                        height: 54
                        radius: 27
                        color: "transparent"
                        border.width: 1
                        border.color: "#66ff375f"
                        visible: bridge.recording
                        SequentialAnimation on scale {
                            running: bridge.recording
                            loops: Animation.Infinite
                            NumberAnimation { from: 1; to: 1.45; duration: 820 }
                            NumberAnimation { from: 1.45; to: 1; duration: 820 }
                        }
                        SequentialAnimation on opacity {
                            running: bridge.recording
                            loops: Animation.Infinite
                            NumberAnimation { from: 0.65; to: 0; duration: 820 }
                            NumberAnimation { from: 0; to: 0.65; duration: 820 }
                        }
                    }
                    Rectangle { anchors.centerIn: parent; width: 54; height: 54; radius: 27; color: bridge.recording ? "#ff375f" : islandRecord.hovered ? "#4c4c4f" : "#363638"; Behavior on color { ColorAnimation { duration: 150 } } }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 7
                    Rectangle { Layout.preferredWidth: 6; Layout.preferredHeight: 6; radius: 3; color: root.accent; SequentialAnimation on opacity { running: bridge.recording; loops: Animation.Infinite; NumberAnimation { to: 0.35; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
                    Label { text: bridge.recording ? "LIVE · ВХОД " + Math.round(Math.min(1, bridge.level * 28) * 100) + "%" : bridge.busy ? "ОБРАБАТЫВАЮ РЕЧЬ" : "DOTAUDIO ГОТОВ"; color: bridge.recording && bridge.level > 0.003 ? "#30d158" : "#aeaeb2"; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 0.75 }
                    Item { Layout.fillWidth: true }
                    Label { visible: bridge.recording || bridge.busy; text: bridge.elapsed; color: "#aeaeb2"; font.family: "Cascadia Mono"; font.pixelSize: 11 }
                }
                Text { Layout.fillWidth: true; text: bridge.caption.length ? bridge.caption : bridge.recording ? "Говорите, я собираю фразу…" : "Нажмите круглую кнопку для начала"; color: "#f5f5f7"; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideRight }
                Waveform { Layout.fillWidth: true; Layout.preferredHeight: 18; bars: 46 }
            }
            Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 44; color: "#18ffffff" }
            IconButton { text: "⌁"; onClicked: root.expand("models"); ToolTip.visible: hovered; ToolTip.text: "Модели Whisper" }
            IconButton { text: "⌃"; ink: "#ffffff"; onClicked: root.expand("live"); ToolTip.visible: hovered; ToolTip.text: "Открыть полное окно" }
        }
    }

    Rectangle {
        visible: !root.compact
        anchors.fill: parent
        color: "#0c0c0e"
        RowLayout {
            anchors.fill: parent
            spacing: 0
            Rectangle {
                Layout.preferredWidth: 242
                Layout.fillHeight: true
                color: "#151517"
                border.width: 1
                border.color: "#0dffffff"
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 7
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.bottomMargin: 19
                        spacing: 10
                        Rectangle { Layout.preferredWidth: 38; Layout.preferredHeight: 38; radius: 13; color: "#f5f5f7"; Text { anchors.centerIn: parent; text: ".а"; color: "#1d1d1f"; font.pixelSize: 15; font.weight: Font.Bold } }
                        ColumnLayout { spacing: 0; Label { text: ".аудио"; color: "#f5f5f7"; font.pixelSize: 20; font.weight: Font.DemiBold } Label { text: "ЛОКАЛЬНАЯ РЕЧЬ"; color: "#8e8e93"; font.pixelSize: 9; font.weight: Font.DemiBold; font.letterSpacing: 1.1 } }
                    }
                    Repeater {
                        model: [ { key: "live", icon: "◉", title: "Live", detail: "Субтитры" }, { key: "dictation", icon: "○", title: "Диктовка", detail: "Голос в текст" }, { key: "media", icon: "▸", title: "Караоке", detail: "Аудио и видео" }, { key: "models", icon: "⌁", title: "Модели", detail: "Whisper" }, { key: "history", icon: "◷", title: "История", detail: "Сессии" }, { key: "settings", icon: "⚙", title: "Среда", detail: "Устройства" } ]
                        delegate: Button {
                            id: nav
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 54
                            hoverEnabled: true
                            onClicked: bridge.selectPage(modelData.key)
                            contentItem: RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 10
                                spacing: 10
                                Text { text: nav.modelData.icon; color: bridge.page === nav.modelData.key ? "#ffffff" : "#aeaeb2"; font.family: "Segoe UI Symbol"; font.pixelSize: 17; Layout.preferredWidth: 20 }
                                ColumnLayout { Layout.fillWidth: true; spacing: 0; Label { text: nav.modelData.title; color: bridge.page === nav.modelData.key ? "#ffffff" : "#d1d1d6"; font.pixelSize: 13; font.weight: Font.DemiBold } Label { text: nav.modelData.detail; color: bridge.page === nav.modelData.key ? "#c7c7cc" : "#6e6e73"; font.pixelSize: 10 } }
                                Rectangle { visible: bridge.page === nav.modelData.key; Layout.preferredWidth: 5; Layout.preferredHeight: 5; radius: 3; color: root.accent }
                            }
                            background: Rectangle { radius: 15; color: bridge.page === nav.modelData.key ? "#18ffffff" : nav.hovered ? "#0bffffff" : "transparent"; Behavior on color { ColorAnimation { duration: 140 } } }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 88
                        radius: 17
                        color: "#09ffffff"
                        border.width: 1
                        border.color: "#0bffffff"
                        ColumnLayout { anchors.fill: parent; anchors.margins: 12; spacing: 3; Label { text: bridge.hotkeysAvailable ? "Горячие клавиши готовы" : "Горячие клавиши недоступны"; color: "#d1d1d6"; font.pixelSize: 11; font.weight: Font.DemiBold } Label { text: "Ctrl + Alt + Space - диктовка"; color: "#8e8e93"; font.pixelSize: 10 } Label { text: "Ctrl + Alt + O - остров"; color: "#8e8e93"; font.pixelSize: 10 } }
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 28
                spacing: 20
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    ColumnLayout {
                        spacing: 2
                        Label { text: ({live: "Живые субтитры", dictation: "Диктовка", media: "Караоке-студия", models: "Модели Whisper", history: "История", settings: "Настройки"})[bridge.page]; color: "#f5f5f7"; font.pixelSize: 30; font.weight: Font.DemiBold }
                        Label { text: bridge.status; color: "#98989d"; font.pixelSize: 13 }
                    }
                    Item { Layout.fillWidth: true }
                    Rectangle { visible: bridge.busy || bridge.recording; Layout.preferredHeight: 30; Layout.preferredWidth: 90; radius: 15; color: bridge.recording ? "#22ff375f" : "#22ff9f0a"; Row { anchors.centerIn: parent; spacing: 6; Rectangle { width: 6; height: 6; radius: 3; color: root.accent } Text { text: bridge.elapsed; color: root.accent; font.family: "Cascadia Mono"; font.pixelSize: 11; font.weight: Font.DemiBold } } }
                    IconButton { text: "≡"; onClicked: root.logsOpen = !root.logsOpen; ToolTip.visible: hovered; ToolTip.text: "Журнал" }
                    ActionButton { text: "Скрыть"; onClicked: root.hide(); ToolTip.visible: hovered; ToolTip.text: "Вернуть: Ctrl + Alt + O" }
                    IconButton { text: "×"; ink: "#ff6961"; onClicked: Qt.quit(); ToolTip.visible: hovered; ToolTip.text: "Закрыть программу" }
                    IconButton { text: "⌄"; onClicked: root.collapse(); ToolTip.visible: hovered; ToolTip.text: "Свернуть в остров" }
                }
                Rectangle {
                    visible: bridge.notice.length > 0
                    Layout.fillWidth: true
                    Layout.preferredHeight: noticeText.implicitHeight + 24
                    radius: 14
                    color: "#18ff9f0a"
                    border.width: 1
                    border.color: "#35ff9f0a"
                    RowLayout { anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 8; spacing: 9; Text { text: "!"; color: "#ff9f0a"; font.pixelSize: 15; font.weight: Font.Bold } Text { id: noticeText; Layout.fillWidth: true; text: bridge.notice; color: "#f5d6a7"; font.pixelSize: 12; wrapMode: Text.Wrap } IconButton { text: "×"; ink: "#f5d6a7"; onClicked: bridge.clearNotice() } }
                }
                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: Math.max(0, root.pageKeys.indexOf(bridge.page))
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 16
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 290
                                radius: 28
                                color: "#1c1c1e"
                                border.width: 1
                                border.color: bridge.recording ? "#66ff375f" : "#12ffffff"
                                Rectangle { width: parent.width * 0.46; height: parent.height * 0.9; x: parent.width * 0.52; y: 18; radius: width / 2; color: bridge.recording ? "#12ff375f" : "#0c0a84ff" }
                                Item {
                                    visible: bridge.recording
                                    anchors.right: parent.right
                                    anchors.rightMargin: 30
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 90
                                    height: 90
                                    z: 1
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: 54
                                        height: 54
                                        radius: 27
                                        color: "#ff375f"
                                        Text { anchors.centerIn: parent; text: "●"; color: "#ffffff"; font.pixelSize: 19 }
                                    }
                                    Repeater {
                                        model: 2
                                        delegate: Rectangle {
                                            required property int index
                                            anchors.centerIn: parent
                                            width: 54
                                            height: 54
                                            radius: 27
                                            color: "transparent"
                                            border.width: 1
                                            border.color: "#66ff375f"
                                            SequentialAnimation on scale {
                                                running: bridge.recording
                                                loops: Animation.Infinite
                                                PauseAnimation { duration: index * 580 }
                                                NumberAnimation { from: 1; to: 1.66; duration: 1160 }
                                                PauseAnimation { duration: (1 - index) * 580 }
                                            }
                                            SequentialAnimation on opacity {
                                                running: bridge.recording
                                                loops: Animation.Infinite
                                                PauseAnimation { duration: index * 580 }
                                                NumberAnimation { from: 0.65; to: 0; duration: 1160 }
                                                PauseAnimation { duration: (1 - index) * 580 }
                                            }
                                        }
                                    }
                                }
                                ColumnLayout {
                                    z: 2
                                    anchors.fill: parent
                                    anchors.margins: 26
                                    spacing: 8
                                    RowLayout { Layout.fillWidth: true; Label { text: bridge.recording ? "●  " + bridge.inputState.toUpperCase() + " · " + bridge.elapsed : "LIVE-СУБТИТРЫ"; color: bridge.inputState === "Сигнал есть" ? "#30d158" : root.accent; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.7 } Item { Layout.fillWidth: true } Label { text: bridge.recording ? "ВХОД " + Math.round(Math.min(1, bridge.level * 28) * 100) + "%" : (bridge.settings.source === "system" ? "ЗВУК СИСТЕМЫ" : "МИКРОФОН") + " · " + (bridge.settings.language === "ru" ? "РУССКИЙ" : String(bridge.settings.language).toUpperCase()); color: bridge.recording && bridge.level > 0.003 ? "#30d158" : "#8e8e93"; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 0.8 } }
                                    Text { Layout.fillWidth: true; Layout.fillHeight: true; text: bridge.caption.length ? bridge.caption : bridge.recording ? "Слушаю. Первая завершённая фраза появится здесь." : "Запустите Live, чтобы увидеть субтитры."; color: bridge.caption.length ? "#f5f5f7" : "#98989d"; font.pixelSize: bridge.caption.length ? 31 : 20; font.weight: bridge.caption.length ? Font.DemiBold : Font.Normal; wrapMode: Text.Wrap; verticalAlignment: Text.AlignVCenter; Behavior on font.pixelSize { NumberAnimation { duration: 180 } } }
                                    RowLayout { Layout.fillWidth: true; Waveform { Layout.fillWidth: true; bars: 58; Layout.preferredHeight: 34 } ActionButton { text: bridge.recording ? "Завершить Live" : "Начать Live"; primary: true; tint: bridge.recording ? "#ff375f" : "#0a84ff"; enabled: !bridge.busy || bridge.recording; onClicked: bridge.toggleRecording() } ActionButton { visible: bridge.busy; text: "Отмена"; onClicked: bridge.cancel() } }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 24
                                color: "#151517"
                                border.width: 1
                                border.color: "#0cffffff"
                                ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 10; RowLayout { Layout.fillWidth: true; Label { text: "Лента расшифровки"; color: "#f5f5f7"; font.pixelSize: 15; font.weight: Font.DemiBold } Item { Layout.fillWidth: true } Label { text: bridge.segments.length + " фрагм."; color: "#8e8e93"; font.pixelSize: 11 } } TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; editable: false; showEmptyHint: false } }
                            }
                        }
                    }
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 16
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 250
                                radius: 28
                                color: "#1c1c1e"
                                border.width: 1
                                border.color: bridge.recording ? "#66ff375f" : "#12ffffff"
                                ColumnLayout { anchors.fill: parent; anchors.margins: 26; spacing: 10; Label { text: "БЫСТРЫЙ ВВОД"; color: "#0a84ff"; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 0.7 } Label { text: bridge.recording ? "Говорите естественно" : "Скажите мысль, я отдам текст в буфер"; color: "#f5f5f7"; font.pixelSize: 26; font.weight: Font.DemiBold } Text { Layout.fillWidth: true; text: "После остановки расшифровка сохранится в истории и попадёт в буфер обмена. Горячая клавиша: Ctrl + Alt + Space."; color: "#98989d"; font.pixelSize: 14; wrapMode: Text.Wrap } Item { Layout.fillHeight: true } RowLayout { Layout.fillWidth: true; ActionButton { text: bridge.recording ? "Остановить запись" : "Начать диктовку"; primary: true; tint: bridge.recording ? "#ff375f" : "#0a84ff"; onClicked: bridge.toggleRecording() } ActionButton { text: "Копировать текст"; enabled: bridge.text.length > 0; onClicked: bridge.copyText() } Item { Layout.fillWidth: true } Waveform { Layout.preferredWidth: 190; bars: 30 } } }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; radius: 24; color: "#151517"; border.width: 1; border.color: "#0cffffff"; TranscriptEditor { anchors.fill: parent; anchors.margins: 20; editable: true } }
                        }
                    }
                    Item {
                        RowLayout {
                            anchors.fill: parent
                            spacing: 16
                            ColumnLayout {
                                Layout.preferredWidth: parent.width * 0.53
                                Layout.fillHeight: true
                                spacing: 12
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    radius: 28
                                    color: "#1c1c1e"
                                    border.width: 1
                                    border.color: "#12ffffff"
                                    clip: true
                                    VideoOutput { id: mediaVideo; anchors.fill: parent; anchors.margins: 10; visible: mediaPlayer.hasVideo; fillMode: VideoOutput.PreserveAspectFit }
                                    Image { anchors.fill: parent; anchors.margins: 10; visible: !mediaPlayer.hasVideo && bridge.coverUrl.length > 0; source: bridge.coverUrl; fillMode: Image.PreserveAspectCrop }
                                    KaraokePreview { visible: bridge.mediaUrl.length > 0; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 18; height: 126; player: mediaPlayer; segments: bridge.segments }
                                    ColumnLayout { anchors.centerIn: parent; width: Math.min(parent.width - 64, 330); visible: !bridge.mediaUrl; spacing: 10; Rectangle { Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: 52; Layout.preferredHeight: 52; radius: 26; color: "#0a84ff"; Text { anchors.centerIn: parent; text: "▸"; color: "white"; font.pixelSize: 24 } } Label { Layout.fillWidth: true; text: "Аудио в караоке"; horizontalAlignment: Text.AlignHCenter; color: "#f5f5f7"; font.pixelSize: 21; font.weight: Font.DemiBold } Text { Layout.fillWidth: true; text: "Откройте аудио или видео, получите текст по словам и доведите таймкоды до чистого результата."; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; color: "#98989d"; font.pixelSize: 13 } ActionButton { Layout.alignment: Qt.AlignHCenter; text: "Выбрать медиа"; primary: true; tint: "#0a84ff"; onClicked: bridge.importFile() } }
                                }
                                RowLayout { Layout.fillWidth: true; ActionButton { text: "Открыть"; onClicked: bridge.importFile() } ActionButton { text: "Обложка"; enabled: bridge.mediaUrl.length > 0; onClicked: bridge.chooseCover() } Item { Layout.fillWidth: true } ActionButton { text: "ASS"; enabled: bridge.segments.length > 0; onClicked: bridge.exportKaraokeFile() } ActionButton { text: bridge.rendering ? "Рендер…" : "MP4"; primary: true; tint: "#0a84ff"; enabled: bridge.segments.length > 0 && !bridge.rendering; onClicked: bridge.exportKaraokeVideo() } }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; radius: 24; color: "#151517"; border.width: 1; border.color: "#0cffffff"; TranscriptEditor { anchors.fill: parent; anchors.margins: 20; player: mediaPlayer; editable: true } }
                        }
                        MediaPlayer { id: mediaPlayer; source: bridge.mediaUrl; videoOutput: mediaVideo; audioOutput: AudioOutput {} }
                    }
                    Item {
                        ListView {
                            anchors.fill: parent
                            spacing: 10
                            clip: true
                            model: ["tiny", "base", "small", "medium", "large-v3", "turbo"]
                            delegate: Rectangle {
                                id: modelCard
                                required property string modelData
                                width: ListView.view.width
                                height: 86
                                radius: 21
                                color: bridge.settings.model === modelData ? "#1c0a84ff" : "#1c1c1e"
                                border.width: 1
                                border.color: bridge.settings.model === modelData ? "#880a84ff" : "#10ffffff"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 14
                                    Rectangle { Layout.preferredWidth: 44; Layout.preferredHeight: 44; radius: 14; color: bridge.settings.model === modelCard.modelData ? "#0a84ff" : "#10ffffff"; Text { anchors.centerIn: parent; text: "W"; color: "#ffffff"; font.pixelSize: 16; font.weight: Font.Bold } }
                                    ColumnLayout { Layout.fillWidth: true; spacing: 2; Label { text: modelCard.modelData; color: "#f5f5f7"; font.pixelSize: 16; font.weight: Font.DemiBold } Label { text: bridge.settings.model === modelCard.modelData ? bridge.modelState.message : "Выберите для работы или подготовьте заранее"; color: "#98989d"; font.pixelSize: 11 } }
                                    ActionButton { text: "Выбрать"; enabled: !bridge.busy; onClicked: bridge.setSetting("model", modelCard.modelData) }
                                    ActionButton { text: bridge.modelPreparing && bridge.modelState.model === modelCard.modelData ? "Готовим" : "Загрузить"; primary: true; tint: "#0a84ff"; enabled: !bridge.busy && !bridge.modelPreparing; onClicked: { bridge.setSetting("model", modelCard.modelData); bridge.prepareSelectedModel() } }
                                }
                            }
                        }
                    }
                    Item {
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 14
                            TextField { Layout.fillWidth: true; placeholderText: "Поиск по названию или тексту"; color: "#f5f5f7"; placeholderTextColor: "#6e6e73"; leftPadding: 16; rightPadding: 16; onTextChanged: bridge.refreshHistory(text); background: Rectangle { radius: 14; color: "#1c1c1e"; border.width: 1; border.color: "#10ffffff" } }
                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                model: bridge.history
                                spacing: 8
                                clip: true
                                delegate: Rectangle {
                                    id: historyCard
                                    required property var modelData
                                    width: ListView.view.width
                                    height: 78
                                    radius: 18
                                    color: historyMouse.containsMouse ? "#12ffffff" : "#1c1c1e"
                                    border.width: 1
                                    border.color: "#0cffffff"
                                    MouseArea { id: historyMouse; anchors.fill: parent; hoverEnabled: true; onClicked: bridge.openSession(historyCard.modelData.id) }
                                    RowLayout { anchors.fill: parent; anchors.margins: 15; Rectangle { Layout.preferredWidth: 34; Layout.preferredHeight: 34; radius: 11; color: "#10ffffff"; Text { anchors.centerIn: parent; text: "◷"; color: "#d1d1d6"; font.pixelSize: 15 } } ColumnLayout { Layout.fillWidth: true; spacing: 3; Text { text: historyCard.modelData.title; color: "#f5f5f7"; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true } Text { text: historyCard.modelData.mode + " · " + historyCard.modelData.segment_count + " фрагм."; color: "#8e8e93"; font.pixelSize: 11 } } Text { text: "›"; color: "#8e8e93"; font.pixelSize: 24 } }
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
                                    Layout.preferredHeight: 128
                                    radius: 22
                                    color: "#1c1c1e"
                                    border.width: 1
                                    border.color: "#10ffffff"
                                    ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 8; Label { text: "Язык и вывод"; color: "#f5f5f7"; font.pixelSize: 16; font.weight: Font.DemiBold } RowLayout { Layout.fillWidth: true; Text { Layout.fillWidth: true; text: "Распознавание ориентировано на русский язык."; color: "#98989d"; font.pixelSize: 12 } ActionButton { text: "Русский"; primary: bridge.settings.language === "ru" && bridge.settings.task === "transcribe"; tint: "#0a84ff"; onClicked: { bridge.setSetting("language", "ru"); bridge.setSetting("task", "transcribe") } } ActionButton { text: "English subtitles"; primary: bridge.settings.task === "translate"; tint: "#0a84ff"; onClicked: bridge.setSetting("task", "translate") } } }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 270
                                    radius: 22
                                    color: "#1c1c1e"
                                    border.width: 1
                                    border.color: "#10ffffff"
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 18
                                        spacing: 10
                                        Label { text: "Источник Live и устройства"; color: "#f5f5f7"; font.pixelSize: 16; font.weight: Font.DemiBold }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: "Источник Live"; color: "#98989d"; font.pixelSize: 12; Layout.fillWidth: true }
                                            ActionButton { text: "Микрофон"; primary: bridge.settings.source === "microphone"; tint: "#0a84ff"; onClicked: bridge.setSetting("source", "microphone") }
                                            ActionButton { text: "Звук системы"; primary: bridge.settings.source === "system"; tint: "#0a84ff"; onClicked: bridge.setSetting("source", "system") }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ComboBox {
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
                                                contentItem: Text { leftPadding: 12; text: inputChooser.displayText; color: "#f5f5f7"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; font.pixelSize: 12 }
                                                background: Rectangle { radius: 12; color: "#0dffffff"; border.width: 1; border.color: "#14ffffff" }
                                            }
                                            ActionButton { text: "Обновить"; onClicked: bridge.refreshDevices() }
                                            ActionButton { text: "Проверить Live"; primary: true; tint: "#0a84ff"; onClicked: bridge.testLiveSource() }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            ComboBox {
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
                                                contentItem: Text { leftPadding: 12; text: outputChooser.displayText; color: "#f5f5f7"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; font.pixelSize: 12 }
                                                background: Rectangle { radius: 12; color: "#0dffffff"; border.width: 1; border.color: "#14ffffff" }
                                            }
                                            ActionButton { text: "Обновить"; onClicked: bridge.refreshOutputs() }
                                            ActionButton { text: "Тон"; onClicked: bridge.testOutputDevice(); ToolTip.visible: hovered; ToolTip.text: "Проверить, что выход воспроизводит звук" }
                                            ActionButton { text: "Loopback"; primary: bridge.settings.source === "system"; tint: "#0a84ff"; onClicked: bridge.testSystemLoopback(); ToolTip.visible: hovered; ToolTip.text: "Проверить, что этот выход попадает в Live" }
                                        }
                                        ProgressBar {
                                            Layout.fillWidth: true
                                            from: 0
                                            to: 1
                                            value: bridge.deviceTest.level
                                            background: Rectangle { implicitHeight: 5; radius: 3; color: "#12ffffff" }
                                            contentItem: Item { implicitHeight: 5; Rectangle { width: parent.width * Math.min(1, bridge.deviceTest.level * 3); height: parent.height; radius: 3; color: "#30d158"; Behavior on width { NumberAnimation { duration: 100 } } } }
                                        }
                                        Label { text: bridge.deviceTest.message || "Проверка не сохраняет запись."; color: "#8e8e93"; font.pixelSize: 11 }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 174
                                    radius: 22
                                    color: "#1c1c1e"
                                    border.width: 1
                                    border.color: "#10ffffff"
                                    ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 8; Label { text: "Мини-остров"; color: "#f5f5f7"; font.pixelSize: 16; font.weight: Font.DemiBold } RowLayout { Layout.fillWidth: true; Label { text: "Непрозрачность"; color: "#98989d"; font.pixelSize: 12; Layout.preferredWidth: 118 } Slider { Layout.fillWidth: true; from: 0.86; to: 1; value: Number(bridge.settings.island_opacity); onMoved: bridge.setSetting("island_opacity", value) } } RowLayout { Layout.fillWidth: true; Switch { text: "Пропускать клики"; checked: Boolean(bridge.settings.island_click_through); onToggled: bridge.setIslandClickThrough(checked) } Item { Layout.fillWidth: true } Switch { text: "Запоминать позицию"; checked: Boolean(bridge.settings.island_snap); onToggled: bridge.setSetting("island_snap", checked) } } }
                                }
                            }
                        }
                    }
                }
            }
        }
        Rectangle {
            visible: root.logsOpen
            width: 360
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            color: "#1c1c1e"
            border.width: 1
            border.color: "#18ffffff"
            z: 10
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 14
                RowLayout { Layout.fillWidth: true; Label { text: "Журнал работы"; color: "#f5f5f7"; font.pixelSize: 19; font.weight: Font.DemiBold } Item { Layout.fillWidth: true } IconButton { text: "×"; onClicked: root.logsOpen = false } }
                Label { text: "События приложения и распознавания"; color: "#8e8e93"; font.pixelSize: 11 }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: bridge.logs
                    spacing: 8
                    clip: true
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width
                        implicitHeight: eventText.implicitHeight + 22
                        radius: 14
                        color: "#08ffffff"
                        Text { id: eventText; anchors.fill: parent; anchors.margins: 11; text: modelData.time + "  " + modelData.message; color: "#d1d1d6"; font.pixelSize: 11; wrapMode: Text.Wrap }
                    }
                }
            }
        }
    }
}
