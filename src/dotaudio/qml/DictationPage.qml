import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Страница диктовки: запись, готовый текст и список фраз.
// SplitView: шапка и лента фраз тянутся ручкой при низком окне.
Item {
    SplitView {
        anchors.fill: parent
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

        Rectangle {
            SplitView.preferredHeight: 248
            SplitView.minimumHeight: 160
            SplitView.maximumHeight: Math.max(180, parent.height - 120)
            radius: Theme.radiusXl
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            clip: true

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
                                  ? "Удерживайте " + bridge.settings.dictate_hotkey + ", чтобы диктовать. Остров покажет запись; после отпускания текст уточнится и попадёт в буфер. Вставка последнего: " + bridge.settings.paste_last_hotkey + "."
                                  : "Горячая клавиша " + bridge.settings.dictate_hotkey + " поднимает остров. После остановки запись уточняется, текст копируется и при автовставке уходит в активное поле. Вставка последнего: " + bridge.settings.paste_last_hotkey + "."
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
                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    Dropdown {
                        id: micChooser
                        width: Math.min(280, Math.max(160, parent.width * 0.35))
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
                    PillButton {
                        text: bridge.speechModeLabel
                        enabled: !bridge.recording && !bridge.busy
                        onClicked: bridge.cycleSpeechMode()
                        ToolTip.visible: hovered
                        ToolTip.text: bridge.speechModeHint
                    }
                    PillButton { text: bridge.recording ? "Стоп" : bridge.busy ? "Остановить" : "Диктовать"; primary: true; onClicked: bridge.toggleRecording() }
                    PillButton { text: "Копировать"; enabled: bridge.text.length > 0; onClicked: bridge.copyText() }
                    PillButton { text: "Вставить последний"; enabled: bridge.lastTranscript.length > 0 && !bridge.recording; onClicked: bridge.pasteLastTranscript() }
                    Waveform { bars: 18; barH: 18 }
                }
            }
        }

        TranscriptEditor {
            SplitView.fillHeight: true
            SplitView.minimumHeight: 120
            editable: true
        }
    }
}
