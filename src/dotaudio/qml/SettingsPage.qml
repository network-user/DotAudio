import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Страница настроек: устройства, Live, субтитры зала, горячие клавиши.
Item {
    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: settingsColumn.implicitHeight
        clip: true
        ColumnLayout {
            id: settingsColumn
            width: parent.width
            spacing: Theme.gapMd
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: setupBox.implicitHeight + 2 * Theme.padCard
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: setupBox
                    anchors.fill: parent
                    anchors.margins: Theme.padCard
                    spacing: Theme.gapSm
                    Label {
                        text: "Автонастройка"
                        color: Theme.text
                        font.pixelSize: Theme.fsTitle
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Опрос устройства, выбор моделей и фоновая загрузка рекомендованных файлов."
                        color: Theme.muted
                        font.pixelSize: Theme.fsLabel
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        PillButton {
                            text: setup.visible ? "Идёт настройка…" : "Запустить снова"
                            primary: !setup.visible
                            enabled: !setup.busy && !bridge.recording && !bridge.busy
                            onClicked: setup.reopen()
                        }
                        Label {
                            text: Boolean(bridge.settings.setup_completed) ? "Уже проходили" : "Ещё не завершена"
                            color: Theme.faint
                            font.pixelSize: Theme.fsSmall
                        }
                        Item { Layout.fillWidth: true }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: computeBox.implicitHeight + 2 * Theme.padCard
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: computeBox
                    anchors.fill: parent
                    anchors.margins: Theme.padCard
                    spacing: Theme.gapSm
                    Label { text: "Вычисления Whisper"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                    Text {
                        Layout.fillWidth: true
                        text: {
                            var label = bridge.hardware.compute_label || "Определяем…"
                            var tip = bridge.hardware.computeHint || ""
                            return "Сейчас: " + label + (tip.length ? ". " + tip : "")
                        }
                        color: Theme.muted
                        font.pixelSize: Theme.fsLabel
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        PillButton {
                            text: "Авто"
                            primary: String(bridge.settings.device) === "auto"
                            enabled: !bridge.gpuSetup.busy && !bridge.recording
                            onClicked: bridge.selectComputeDevice("auto")
                            ToolTip.visible: hovered
                            ToolTip.text: "CUDA если доступна, иначе CPU"
                        }
                        PillButton {
                            text: "Процессор"
                            primary: String(bridge.settings.device) === "cpu"
                            enabled: !bridge.gpuSetup.busy && !bridge.recording
                            onClicked: bridge.selectComputeDevice("cpu")
                        }
                        PillButton {
                            text: "Видеокарта"
                            primary: String(bridge.settings.device) === "cuda"
                            enabled: !bridge.gpuSetup.busy && !bridge.recording
                            onClicked: bridge.selectComputeDevice("cuda")
                            ToolTip.visible: hovered
                            ToolTip.text: Boolean(bridge.hardware.cudaReady)
                                          ? "Использовать CUDA"
                                          : "Скачает CUDA runtime и подготовит модель"
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: bridge.hardware.gpuLabel || ""
                            color: Theme.faint
                            font.pixelSize: Theme.fsSmall
                            font.family: Theme.monoFamily
                        }
                    }
                    Rectangle {
                        visible: bridge.gpuSetup.busy || (Number(bridge.gpuSetup.percent) > 0 && String(bridge.gpuSetup.phase) !== "idle")
                        Layout.fillWidth: true
                        height: 6
                        radius: 3
                        color: Theme.fill
                        Rectangle {
                            width: parent.width * Math.max(0, Math.min(1, Number(bridge.gpuSetup.percent) / 100))
                            height: parent.height
                            radius: 3
                            color: Theme.text
                            Behavior on width { NumberAnimation { duration: Theme.baseMs } }
                        }
                    }
                    Label {
                        visible: bridge.gpuSetup.busy || String(bridge.gpuSetup.error || "").length > 0
                        Layout.fillWidth: true
                        text: {
                            if (bridge.gpuSetup.busy)
                                return Math.round(Number(bridge.gpuSetup.percent || 0)) + "% · " + String(bridge.gpuSetup.message || "")
                            return String(bridge.gpuSetup.error || bridge.gpuSetup.message || "")
                        }
                        color: Theme.faint
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.monoFamily
                        wrapMode: Text.Wrap
                    }
                    ColumnLayout {
                        visible: String(bridge.hardware.computeAdvice) === "needs_runtime" && !bridge.gpuSetup.busy
                        Layout.fillWidth: true
                        spacing: 2
                        Repeater {
                            model: bridge.hardware.manualSteps || []
                            delegate: Label {
                                required property var modelData
                                Layout.fillWidth: true
                                text: "· " + modelData
                                color: Theme.faint
                                font.pixelSize: Theme.fsSmall
                                wrapMode: Text.Wrap
                            }
                        }
                        RowLayout {
                            spacing: Theme.gapSm
                            PillButton { text: "Настроить GPU"; primary: true; onClicked: bridge.setupGpu() }
                            PillButton { text: "Инструкция"; onClicked: bridge.openCudaHelp() }
                            PillButton { text: "Команда pip"; onClicked: bridge.copyCudaInstallCommand() }
                        }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: dictEngineBox.implicitHeight + 2 * Theme.padCard
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: dictEngineBox
                    anchors.fill: parent
                    anchors.margins: Theme.padCard
                    spacing: Theme.gapSm
                    Label { text: "Движок распознавания Live"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "Vosk - лёгкая потоковая Kaldi-модель для слабого CPU. Whisper - точнее, но заметно тяжелее. Диктовка и медиа всегда на Whisper."; color: Theme.muted; font.pixelSize: Theme.fsLabel; wrapMode: Text.Wrap }
                    RowLayout {
                        Layout.fillWidth: true
                        PillButton { text: "Vosk"; primary: String(bridge.settings.live_engine) === "vosk"; onClicked: bridge.setSetting("live_engine", "vosk") }
                        PillButton { text: "Whisper"; primary: String(bridge.settings.live_engine) !== "vosk"; onClicked: bridge.setSetting("live_engine", "whisper") }
                        Item { Layout.fillWidth: true }
                        Label { text: bridge.liveModelText; color: Theme.faint; font.pixelSize: Theme.fsSmall }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: String(bridge.settings.live_engine) === "vosk"
                        Label { text: "Модель vosk"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.fillWidth: true }
                        PillButton { text: "Малая (~44 МБ)"; primary: String(bridge.settings.vosk_size) === "small"; onClicked: bridge.setSetting("vosk_size", "small"); ToolTip.visible: hovered; ToolTip.text: "vosk-model-small-ru-0.22 · для слабого CPU" }
                        PillButton { text: "Большая (~1,8 ГБ)"; primary: String(bridge.settings.vosk_size) !== "small"; onClicked: bridge.setSetting("vosk_size", "big"); ToolTip.visible: hovered; ToolTip.text: "vosk-model-ru-0.42 · точнее, тяжелее" }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: languageBox.implicitHeight + 2 * Theme.padCard
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: languageBox
                    anchors.fill: parent
                    anchors.margins: Theme.padCard
                    spacing: Theme.gapSm
                    Label { text: "Язык и вывод"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { Layout.fillWidth: true; text: "Распознавание ориентировано на русский язык."; color: Theme.muted; font.pixelSize: Theme.fsLabel; wrapMode: Text.Wrap }
                        PillButton { text: "Русский"; primary: bridge.settings.language === "ru" && bridge.settings.task === "transcribe"; onClicked: { bridge.setSetting("language", "ru"); bridge.setSetting("task", "transcribe") } }
                        PillButton { text: "English subtitles"; primary: bridge.settings.task === "translate"; onClicked: bridge.setSetting("task", "translate") }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: deviceBox.implicitHeight + 2 * Theme.padCard
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: deviceBox
                    anchors.fill: parent
                    anchors.margins: Theme.padCard
                    spacing: 10
                    Label { text: "Микрофон и устройства"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                    Text {
                        Layout.fillWidth: true
                        text: "Диктовка всегда идёт с микрофона ниже. Live отдельно: микрофон, звук компьютера или Авто. Проверка микрофона записывает пару секунд и проигрывает сказанное в наушники - как в Discord."
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                    Label { text: "Микрофон диктовки"; color: Theme.text; font.pixelSize: Theme.fsLabel; font.weight: Font.DemiBold }
                    Text {
                        Layout.fillWidth: true
                        text: "Если микрофона наушников нет в списке - Windows отдаёт только их вывод, без входа. Включите микрофон гарнитуры в Параметры → Система → Звук → Ввод (или в приложении производителя), затем «Обновить». Пока его нет, выберите UNA или другой рабочий вход."
                        color: Theme.faint
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Dropdown {
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
                        }
                        PillButton { text: "Обновить"; onClicked: bridge.refreshDevices() }
                        PillButton {
                            text: bridge.deviceTest.phase === "listening" || bridge.deviceTest.phase === "starting" || bridge.deviceTest.phase === "playing"
                                  ? "Слушаю…"
                                  : "Проверить"
                            primary: true
                            enabled: !bridge.recording && !bridge.busy && bridge.deviceTest.phase !== "listening" && bridge.deviceTest.phase !== "starting" && bridge.deviceTest.phase !== "playing"
                            onClicked: bridge.testMicrophone()
                            ToolTip.visible: hovered
                            ToolTip.text: "Говорите 2–3 с, затем услышите себя в наушниках"
                        }
                    }
                    Label { text: "Источник Live"; color: Theme.text; font.pixelSize: Theme.fsLabel; font.weight: Font.DemiBold }
                    RowLayout {
                        Layout.fillWidth: true
                        PillButton { text: "Микрофон"; primary: String(bridge.settings.live_source) === "microphone"; onClicked: bridge.setSetting("live_source", "microphone") }
                        PillButton { text: "Звук системы"; primary: String(bridge.settings.live_source) === "system"; onClicked: bridge.setSetting("live_source", "system") }
                        PillButton { text: "Авто"; primary: String(bridge.settings.live_source) === "mixed"; onClicked: bridge.setSetting("live_source", "mixed"); ToolTip.visible: hovered; ToolTip.text: "Микрофон и звук компьютера одновременно" }
                        Item { Layout.fillWidth: true }
                        PillButton { text: "Проверить Live"; onClicked: bridge.testLiveSource(); enabled: !bridge.recording && !bridge.busy }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: String(bridge.settings.live_source) === "system" || String(bridge.settings.live_source) === "mixed"
                        Dropdown {
                            id: loopbackChooser
                            Layout.fillWidth: true
                            model: [{ name: "Системный вывод Windows", id: "" }].concat(bridge.loopbacks)
                            textRole: "name"
                            currentIndex: {
                                var selected = String(bridge.settings.loopback_device)
                                for (var i = 0; i < model.length; i++) {
                                    if (String(model[i].id) === selected) return i
                                }
                                return 0
                            }
                            onActivated: function(index) {
                                var device = loopbackChooser.model[index]
                                bridge.setSetting("loopback_device", String(device.id))
                            }
                        }
                        PillButton { text: "Обновить"; onClicked: bridge.refreshLoopbacks() }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Dropdown {
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
                        }
                        PillButton { text: "Обновить"; onClicked: bridge.refreshOutputs() }
                        PillButton { text: "Тон"; onClicked: bridge.testOutputDevice() }
                        PillButton { text: "Loopback"; primary: String(bridge.settings.live_source) === "system" || String(bridge.settings.live_source) === "mixed"; onClicked: bridge.testSystemLoopback() }
                    }
                    // Уровень проверки устройства. Шкала та же,
                    // что у осциллограммы, поэтому «тихо» здесь
                    // и «тихо» на острове выглядят одинаково.
                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 6
                        Rectangle {
                            anchors.fill: parent
                            radius: 3
                            color: Theme.hairline
                        }
                        Rectangle {
                            height: parent.height
                            radius: 3
                            width: parent.width * Theme.levelShape(bridge.deviceTest.level)
                            color: Theme.text
                            Behavior on width { NumberAnimation { duration: 110; easing.type: Easing.OutQuad } }
                        }
                    }
                    Label {
                        text: {
                            var phase = String(bridge.deviceTest.phase || "")
                            if (phase === "listening" || phase === "starting")
                                return bridge.deviceTest.message || "Говорите сейчас - полоска должна двигаться."
                            if (phase === "playing")
                                return bridge.deviceTest.message || "Слушаем запись…"
                            return bridge.deviceTest.message || "Проверка не сохраняет запись на диск."
                        }
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: islandBox.implicitHeight + 2 * Theme.padCard
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: islandBox
                    anchors.fill: parent
                    anchors.margins: Theme.padCard
                    spacing: Theme.gapSm
                    Label { text: "Диктовка и остров"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                    Text {
                        Layout.fillWidth: true
                        text: bridge.hotkeysAvailable
                              ? "Глобальные клавиши работают, даже когда окно свёрнуто."
                              : "Глобальные клавиши недоступны на этой системе. Запускайте запись кнопкой."
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Диктовка"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.preferredWidth: 90 }
                        Repeater {
                            model: ["Ctrl+Alt+Space", "Ctrl+Shift+Space", "Ctrl+Win+Space"]
                            PillButton {
                                required property string modelData
                                text: modelData
                                primary: bridge.settings.dictate_hotkey === modelData
                                onClicked: bridge.setHotkeys(modelData, bridge.settings.island_hotkey)
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Остров"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.preferredWidth: 90 }
                        Repeater {
                            model: ["Ctrl+Alt+O", "Ctrl+Shift+O", "Ctrl+Win+O"]
                            PillButton {
                                required property string modelData
                                text: modelData
                                primary: bridge.settings.island_hotkey === modelData
                                onClicked: bridge.setHotkeys(bridge.settings.dictate_hotkey, modelData)
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Вставка"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.preferredWidth: 90 }
                        Repeater {
                            model: ["Shift+Alt+Z", "Ctrl+Alt+V", "Ctrl+Shift+V"]
                            PillButton {
                                required property string modelData
                                text: modelData
                                primary: bridge.settings.paste_last_hotkey === modelData
                                onClicked: bridge.setPasteHotkey(modelData)
                            }
                        }
                    }
                    ToggleSwitch {
                        text: "Удерживать клавишу, чтобы диктовать"
                        checked: Boolean(bridge.settings.dictate_hold)
                        onToggled: bridge.setSetting("dictate_hold", checked)
                    }
                    // Автовставка была включена всегда и не
                    // имела выключателя, хотя вставляет текст
                    // в чужое окно.
                    ToggleSwitch {
                        text: "Вставлять текст в активное окно"
                        checked: Boolean(bridge.settings.auto_paste)
                        onToggled: bridge.setSetting("auto_paste", checked)
                    }
                    Label {
                        text: Boolean(bridge.settings.auto_paste)
                            ? "После диктовки текст копируется и вставляется в то окно, где вы работали. Enter не нажимается."
                            : "Текст только копируется в буфер обмена; вставить можно самому или клавишей " + bridge.settings.paste_last_hotkey + "."
                        color: Theme.faint
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        text: "По умолчанию повтор " + bridge.settings.dictate_hotkey + " начинает и останавливает запись. Вставка последнего текста: " + bridge.settings.paste_last_hotkey + "."
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Непрозрачность"; color: Theme.muted; font.pixelSize: Theme.fsLabel; Layout.preferredWidth: 118 }
                        Slider {
                            id: opacitySlider
                            Layout.fillWidth: true
                            from: 0.86
                            to: 1
                            value: Number(bridge.settings.island_opacity)
                            onMoved: bridge.setSetting("island_opacity", value)
                            background: Rectangle {
                                x: opacitySlider.leftPadding
                                y: (opacitySlider.height - height) / 2
                                width: opacitySlider.availableWidth
                                height: 4
                                radius: 2
                                color: Theme.fill
                                Rectangle {
                                    width: opacitySlider.position * parent.width
                                    height: parent.height
                                    radius: 2
                                    color: Theme.text
                                }
                            }
                            handle: Rectangle {
                                x: opacitySlider.leftPadding + opacitySlider.visualPosition * (opacitySlider.availableWidth - width)
                                y: (opacitySlider.height - height) / 2
                                width: 18
                                height: 18
                                radius: 9
                                color: opacitySlider.pressed ? "#d6d6d2" : Theme.text
                                border.width: 1
                                border.color: Theme.borderHi
                                scale: opacitySlider.pressed ? 1.1 : 1
                                Behavior on scale {
                                    NumberAnimation {
                                        duration: Theme.fastMs
                                        easing.type: Easing.Bezier
                                        easing.bezierCurve: Theme.easeSpring
                                    }
                                }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ToggleSwitch { text: "Пропускать клики"; checked: Boolean(bridge.settings.island_click_through); onToggled: bridge.setIslandClickThrough(checked) }
                        Item { Layout.fillWidth: true }
                        ToggleSwitch { text: "Запоминать позицию"; checked: Boolean(bridge.settings.island_snap); onToggled: bridge.setSetting("island_snap", checked) }
                    }
                    Label {
                        visible: Boolean(bridge.settings.island_click_through)
                        text: "Клики проходят сквозь остров. Запись: Ctrl+Alt+Space"
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: overlayBox.implicitHeight + 2 * Theme.padCard
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: overlayBox
                    anchors.fill: parent
                    anchors.margins: Theme.padCard
                    spacing: Theme.gapSm
                    Label { text: "Субтитры на экране"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "Отдельное окно для зала: крупный текст, без кнопок, клики проходят сквозь."; color: Theme.muted; font.pixelSize: Theme.fsLabel; wrapMode: Text.Wrap }
                    RowLayout {
                        Layout.fillWidth: true
                        ToggleSwitch { text: "Показать на экране"; checked: Boolean(bridge.settings.caption_overlay); onToggled: bridge.setSetting("caption_overlay", checked) }
                        Item { Layout.fillWidth: true }
                        PillButton { text: "Меньше"; primary: bridge.settings.caption_size === "sm"; onClicked: bridge.setSetting("caption_size", "sm") }
                        PillButton { text: "Средние"; primary: bridge.settings.caption_size === "md"; onClicked: bridge.setSetting("caption_size", "md") }
                        PillButton { text: "Крупные"; primary: bridge.settings.caption_size === "lg"; onClicked: bridge.setSetting("caption_size", "lg") }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        PillButton { text: "Обычный контраст"; primary: String(bridge.settings.caption_contrast) !== "high"; onClicked: bridge.setSetting("caption_contrast", "normal") }
                        PillButton { text: "Высокий контраст"; primary: String(bridge.settings.caption_contrast) === "high"; onClicked: bridge.setSetting("caption_contrast", "high") }
                        Item { Layout.fillWidth: true }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        PillButton { text: "Сверху"; primary: String(bridge.settings.caption_position) === "top"; onClicked: bridge.setSetting("caption_position", "top") }
                        PillButton { text: "Снизу"; primary: String(bridge.settings.caption_position) !== "top" && String(bridge.settings.caption_position) !== "floating"; onClicked: bridge.setSetting("caption_position", "bottom") }
                        PillButton { text: "Плавающие"; primary: String(bridge.settings.caption_position) === "floating"; onClicked: bridge.setSetting("caption_position", "floating") }
                        Item { Layout.fillWidth: true }
                        PillButton {
                            compact: true
                            visible: String(bridge.settings.caption_position) === "floating"
                            text: "Вернуть вниз"
                            onClicked: bridge.resetCaptionPosition()
                            ToolTip.visible: hovered
                            ToolTip.text: "Сбросить сохранённое положение плавающих субтитров"
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ToggleSwitch { text: "Скрывать в паузе"; checked: Boolean(bridge.settings.caption_autohide); onToggled: bridge.setSetting("caption_autohide", checked) }
                        Item { Layout.fillWidth: true }
                        ToggleSwitch { text: "Закрепить (клики сквозь)"; checked: Boolean(bridge.settings.caption_locked); onToggled: bridge.setSetting("caption_locked", checked) }
                    }
                    ToggleSwitch {
                        text: "Без анимации слов"
                        checked: Boolean(bridge.settings.reduce_motion)
                        onToggled: bridge.setSetting("reduce_motion", checked)
                    }
                    Label {
                        text: Boolean(bridge.settings.caption_locked)
                              ? "Субтитры не перехватывают мышь. Снимите закрепление, чтобы перетащить окно зала."
                              : "Перетащите окно субтитров. Положение сохранится как плавающее."
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Repeater {
                            model: Qt.application.screens
                            PillButton {
                                required property int index
                                text: index === 0 ? "Экран 1" : "Экран " + (index + 1)
                                primary: Number(bridge.settings.caption_screen) === index || (Number(bridge.settings.caption_screen) < 0 && index === 0)
                                onClicked: bridge.setSetting("caption_screen", index)
                            }
                        }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: liveBox.implicitHeight + 2 * Theme.padCard
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: liveBox
                    anchors.fill: parent
                    anchors.margins: Theme.padCard
                    spacing: Theme.gapSm
                    Label { text: "Live-окно и текст"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "При Live остров превращается в одно окно. Размер - пресетами или руками за угол, замок фиксирует положение и размер."; color: Theme.muted; wrapMode: Text.Wrap; font.pixelSize: Theme.fsSmall }
                    RowLayout {
                        Layout.fillWidth: true
                        ToggleSwitch { text: "Авто-окно при старте Live"; checked: Boolean(bridge.settings.live_auto_window); onToggled: bridge.setSetting("live_auto_window", checked) }
                        Item { Layout.fillWidth: true }
                        ToggleSwitch { text: "Замок"; checked: Boolean(bridge.settings.live_locked); onToggled: bridge.setSetting("live_locked", checked) }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Размер пресет"; color: Theme.muted; font.pixelSize: Theme.fsLabel }
                        PillButton { text: "Малый"; primary: String(bridge.settings.live_size) === "small"; onClicked: bridge.setSetting("live_size", "small") }
                        PillButton { text: "Средний"; primary: String(bridge.settings.live_size) === "standard"; onClicked: bridge.setSetting("live_size", "standard") }
                        PillButton { text: "Широкий"; primary: String(bridge.settings.live_size) === "wide"; onClicked: bridge.setSetting("live_size", "wide") }
                        PillButton { text: "Высокий"; primary: String(bridge.settings.live_size) === "tall"; onClicked: bridge.setSetting("live_size", "tall") }
                        Item { Layout.fillWidth: true }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ToggleSwitch { text: "Таймкод у каждой фразы"; checked: Boolean(bridge.settings.live_show_times); onToggled: bridge.setSetting("live_show_times", checked) }
                        Item { Layout.fillWidth: true }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ToggleSwitch {
                            text: "Экономный режим финалов (greedy)"
                            checked: Boolean(bridge.settings.live_greedy_finals)
                            onToggled: bridge.setSetting("live_greedy_finals", checked)
                        }
                        Text {
                            Layout.alignment: Qt.AlignVCenter
                            text: "для слабых машин: финалы лучом 1"
                            color: Theme.faint
                            font.pixelSize: Theme.fsMicro
                        }
                        Item { Layout.fillWidth: true }
                    }
                    Label {
                        text: "Комбинация выхода: закрывает программу целиком из консоли и по горячей клавише."
                        color: Theme.faint
                        font.pixelSize: Theme.fsMicro
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        TextField {
                            id: quitInput
                            Layout.fillWidth: true
                            text: String(bridge.settings.quit_hotkey || "Ctrl+Alt+X")
                            placeholderText: "Ctrl+Alt+A"
                            selectByMouse: true
                            color: Theme.text
                            placeholderTextColor: Theme.faint
                            font.family: Theme.fontFamily
                            inputMethodHints: Qt.ImhNoPredictiveText
                            background: Rectangle { radius: 10; color: Theme.fill; border.width: 1; border.color: Theme.hairline }
                        }
                        PillButton {
                            compact: true
                            text: "Применить"
                            primary: true
                            onClicked: {
                                bridge.setQuitHotkey(quitInput.text)
                                // После валидации показываем каноничный вид.
                                quitInput.text = String(bridge.settings.quit_hotkey)
                            }
                        }
                    }
                    Row {
                        Layout.fillWidth: true
                        spacing: 6
                        Repeater {
                            model: ["Ctrl+Alt+X", "Ctrl+Alt+C", "Ctrl+Alt+Q"]
                            PillButton {
                                required property string modelData
                                text: modelData
                                primary: String(bridge.settings.quit_hotkey) === modelData
                                onClicked: { bridge.setSetting("quit_hotkey", modelData); quitInput.text = modelData }
                            }
                        }
                    }
                }
            }
        }
    }
}
