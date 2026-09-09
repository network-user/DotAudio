import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Страница диктовки: запись, готовый текст и список фраз.
Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 14
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 248
            radius: Theme.radiusXl
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: Theme.gapSm
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
                        spacing: Theme.gapSm
                        visible: opacity > 0.01
                        opacity: bridge.caption.length ? 0 : 1
                        Behavior on opacity { NumberAnimation { duration: Theme.contentMs } }
                        Label {
                            Layout.fillWidth: true
                            text: bridge.recording ? "Говорите естественно" : "Скажите мысль, текст попадёт в буфер"
                            color: Theme.text
                            font.pixelSize: Theme.fsHero
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
                        pixelSize: Theme.fsHero
                        maxLines: 3
                        align: Text.AlignLeft
                        opacity: bridge.caption.length ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    Dropdown {
                        id: micChooser
                        Layout.fillWidth: true
                        Layout.maximumWidth: 280
                        enabled: !bridge.recording && !bridge.busy
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
                            var device = micChooser.model[index]
                            bridge.setSetting("input_device", String(device.id))
                        }
                    }
                    PillButton {
                        text: {
                            var phase = String(bridge.deviceTest.phase || "")
                            if (phase === "listening" || phase === "starting") return "Слушаю…"
                            if (phase === "playing") return "Играю…"
                            return "Проверить"
                        }
                        enabled: !bridge.recording && !bridge.busy
                                 && bridge.deviceTest.phase !== "listening"
                                 && bridge.deviceTest.phase !== "starting"
                                 && bridge.deviceTest.phase !== "playing"
                        onClicked: bridge.testMicrophone()
                        ToolTip.visible: hovered
                        ToolTip.text: "Как в Discord: говорите, затем услышите себя"
                    }
                    PillButton { text: bridge.recording ? "Стоп" : bridge.busy ? "Остановить" : "Диктовать"; primary: true; onClicked: bridge.toggleRecording() }
                    PillButton { text: "Копировать"; enabled: bridge.text.length > 0; onClicked: bridge.copyText() }
                    PillButton { text: "Вставить последний"; enabled: bridge.lastTranscript.length > 0 && !bridge.recording; onClicked: bridge.pasteLastTranscript() }
                    Item { Layout.fillWidth: true }
                    Waveform { Layout.preferredWidth: 140; bars: 18; barH: 18 }
                }
            }
        }
        TranscriptEditor { Layout.fillWidth: true; Layout.fillHeight: true; editable: true }
    }
}
