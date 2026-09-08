import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Страница моделей: сводка железа, карточки моделей и словарь.
Item {
    // Одна прокрутка на страницу. Раньше список моделей скроллился
    // внутри страницы и последняя карточка обрезалась половиной.
    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: modelsColumn.implicitHeight
        clip: true
        ScrollBar.vertical: ScrollBar {}
        ColumnLayout {
            id: modelsColumn
            width: parent.width
            spacing: 10

            // Сводка устройства и рекомендация. Числа здесь
            // фактические: потоки CPU, ОЗУ и то, что видит
            // CTranslate2. Проба доезжает фоном, поэтому пока
            // она не готова, поля честно показывают прочерк.
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: hwBody.implicitHeight + 2 * Theme.padCard
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: hwBody
                    anchors.fill: parent
                    anchors.margins: Theme.padCard
                    spacing: Theme.gapSm
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        Label { text: "Ваше устройство"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        Label {
                            text: bridge.hardware.compute_label && bridge.hardware.compute_label.length ? bridge.hardware.compute_label : "Определяем…"
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                            font.family: Theme.monoFamily
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapLg
                        HwStat { label: "Потоки CPU"; value: bridge.hardware.threads > 0 ? String(bridge.hardware.threads) : "-" }
                        HwStat { label: "ОЗУ"; value: bridge.hardware.ram_gb ? bridge.hardware.ram_gb + " ГБ" : "-" }
                        HwStat {
                            label: "GPU"
                            value: bridge.hardware.gpuLabel && String(bridge.hardware.gpuLabel).length ? String(bridge.hardware.gpuLabel) : "—"
                        }
                        HwStat { label: "CUDA"; value: bridge.hardware.cuda_devices > 0 ? "есть" : "нет" }
                        HwStat { label: "Рекомендуем"; value: bridge.recommendedModel }
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: {
                            var h = bridge.hardware
                            return h.computeHint && h.computeHint.length
                        }
                        text: bridge.hardware.computeHint || ""
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        visible: bridge.showGpuHint || bridge.gpuSetup.busy || String(bridge.hardware.computeAdvice) === "needs_runtime"
                        PillButton {
                            text: bridge.gpuSetup.busy
                                   ? ("Настройка… " + Math.round(bridge.gpuSetup.percent || 0) + "%")
                                   : (bridge.hardware.computeAction === "use_gpu" ? "Включить GPU" : "Настроить GPU")
                            enabled: !bridge.gpuSetup.busy && !bridge.modelPreparing && !bridge.recording
                            onClicked: bridge.setupGpu()
                        }
                        PillButton {
                            text: "Инструкция"
                            visible: String(bridge.hardware.computeAdvice) === "needs_runtime" && !bridge.gpuSetup.busy
                            onClicked: bridge.openCudaHelp()
                        }
                        PillButton {
                            text: "Команда pip"
                            visible: String(bridge.hardware.computeAdvice) === "needs_runtime" && !bridge.gpuSetup.busy
                            onClicked: bridge.copyCudaInstallCommand()
                        }
                        PillButton {
                            text: "Скрыть"
                            visible: !bridge.gpuSetup.busy && bridge.showGpuHint
                            onClicked: bridge.dismissGpuHint()
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: bridge.gpuSetup.error && bridge.gpuSetup.error.length
                        text: bridge.gpuSetup.error || ""
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "Подходит и не подходит оцениваются по факту: память сравнивается с реальным ОЗУ, скорость - рекомендация по числу потоков, не замер. Замер появится после первого распознавания."
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                }
            }

        Repeater {
            model: ["tiny", "base", "small", "medium", "large-v3", "turbo"]
            delegate: Rectangle {
                id: modelCard
                required property string modelData
                required property int index
                readonly property var disk: {
                    var lib = bridge.modelLibrary
                    for (var i = 0; i < lib.length; i++) {
                        if (lib[i].model === modelCard.modelData)
                            return lib[i]
                    }
                    return { "ready": false, "bytes": 0 }
                }
                readonly property var spec: bridge.modelCatalog[modelCard.modelData] || null
                readonly property var fit: {
                    // Чтение hardware держит привязку живой: сводка
                    // доезжает фоном, и оценка пересчитывается сама.
                    var hw = bridge.hardware
                    return bridge.modelFit(modelCard.modelData)
                }
                readonly property bool selected: bridge.settings.model === modelData
                readonly property bool preparing: bridge.modelPreparing && bridge.modelState.model === modelData
                readonly property bool cached: Boolean(disk.ready)
                // Снимок загрузки относится к этой карточке, пока
                // идёт скачивание файлов модели.
                readonly property var dl: bridge.modelDownload
                readonly property bool downloading: preparing
                    && dl.model === modelData && dl.phase === "download"
                Layout.fillWidth: true
                implicitHeight: cardBody.implicitHeight + 2 * 16
                radius: Theme.radiusLg
                color: selected ? Theme.fill : Theme.surface
                border.width: 1
                border.color: selected ? Theme.borderHi : Theme.border
                Behavior on color { ColorAnimation { duration: Theme.baseMs } }
                Behavior on border.color { ColorAnimation { duration: Theme.baseMs } }

                ColumnLayout {
                    id: cardBody
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: Theme.gapSm

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        Icon { name: "models"; width: 18; height: 18; ink: modelCard.selected ? Theme.text : Theme.muted }
                        Label { text: modelCard.modelData; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                        // Бейджи состояния: выбрана / в кеше / рекомендована.
                        // Состояние не передаётся одним цветом.
                        Rectangle {
                            visible: modelCard.selected
                            radius: 8
                            implicitHeight: 16
                            implicitWidth: badgeSel.implicitWidth + 12
                            color: Theme.text
                            Label { id: badgeSel; anchors.centerIn: parent; text: "выбрана"; color: Theme.bg; font.pixelSize: Theme.fsMicro; font.weight: Font.DemiBold }
                        }
                        Rectangle {
                            visible: modelCard.cached && !modelCard.selected
                            radius: 8
                            implicitHeight: 16
                            implicitWidth: badgeCache.implicitWidth + 12
                            color: Theme.fill
                            border.width: 1
                            border.color: Theme.border
                            Label {
                                id: badgeCache
                                anchors.centerIn: parent
                                text: modelCard.disk.bytes > 0 ? "в кеше · " + Math.round(modelCard.disk.bytes / 1048576) + " МБ" : "в кеше"
                                color: Theme.muted
                                font.pixelSize: Theme.fsMicro
                            }
                        }
                        Rectangle {
                            visible: !modelCard.selected && bridge.recommendedModel === modelCard.modelData
                            radius: 8
                            implicitHeight: 16
                            implicitWidth: badgeRec.implicitWidth + 12
                            color: "transparent"
                            border.width: 1
                            border.color: Theme.borderHi
                            Label { id: badgeRec; anchors.centerIn: parent; text: "для этого ПК"; color: Theme.muted; font.pixelSize: Theme.fsMicro }
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            visible: modelCard.spec !== null
                            text: modelCard.spec ? modelCard.spec.params + " параметров" : ""
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                            font.family: Theme.monoFamily
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        // Справочная шкала нагрузки: пять сегментов по
                        // числу параметров из каталога. Это ориентир
                        // архитектуры, не замер скорости машины.
                        Item {
                            Layout.preferredWidth: 84
                            Layout.preferredHeight: 5
                            Layout.alignment: Qt.AlignVCenter
                            Repeater {
                                model: 5
                                Rectangle {
                                    required property int index
                                    x: index * 17
                                    width: 14
                                    radius: 2
                                    anchors.top: parent.top
                                    anchors.bottom: parent.bottom
                                    color: modelCard.spec && index < modelCard.spec.load
                                           ? (modelCard.selected ? Theme.text : Theme.muted)
                                           : Theme.hairline
                                    Behavior on color { ColorAnimation { duration: Theme.baseMs } }
                                }
                            }
                        }
                        Label {
                            visible: modelCard.spec !== null
                            text: modelCard.spec ? "скачать ~" + modelCard.spec.download_mb + " МБ · память ~" + modelCard.spec.ram_gb + " ГБ" : ""
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: modelCard.fit.note
                            color: modelCard.fit.state === "tight" || modelCard.fit.state === "slow" ? Theme.muted : Theme.faint
                            font.pixelSize: Theme.fsSmall
                            font.italic: modelCard.fit.state === "tight" || modelCard.fit.state === "slow"
                        }
                    }

                    // Прогресс подготовки. Во время скачивания
                    // проценты, объём и скорость берутся из факта
                    // полученных байтов; после - модель грузится в
                    // память без процента, там честный свип.
                    ColumnLayout {
                        visible: modelCard.preparing
                        Layout.fillWidth: true
                        spacing: 5

                        Item {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 4
                            clip: true
                            Rectangle {
                                anchors.fill: parent
                                radius: 2
                                color: Theme.hairline
                            }
                            Rectangle {
                                visible: modelCard.downloading
                                width: parent.width * Math.min(1, (modelCard.dl.percent || 0) / 100)
                                height: parent.height
                                radius: 2
                                color: Theme.text
                                Behavior on width {
                                    NumberAnimation {
                                        duration: Theme.fastMs
                                        easing.type: Easing.OutQuad
                                    }
                                }
                            }
                            Rectangle {
                                id: sweep
                                visible: !modelCard.downloading
                                width: parent.width * 0.3
                                height: parent.height
                                radius: 2
                                color: Theme.text
                                SequentialAnimation on x {
                                    loops: Animation.Infinite
                                    running: modelCard.preparing && !modelCard.downloading
                                    NumberAnimation { from: -sweep.width; to: modelCard.width; duration: 1100; easing.type: Easing.InOutQuad }
                                }
                            }
                        }

                        Label {
                            visible: modelCard.downloading
                            text: Math.round(modelCard.dl.percent || 0) + "%"
                                  + " · " + Math.round(modelCard.dl.received_mb || 0)
                                  + " из " + Math.round(modelCard.dl.total_mb || 0) + " МБ"
                                  + " · " + (modelCard.dl.speed_mb_s || 0) + " МБ/с"
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                            font.family: Theme.monoFamily
                        }
                        Label {
                            visible: !modelCard.downloading && bridge.modelState.message.length > 0
                            text: bridge.modelState.message
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        PillButton {
                            text: modelCard.selected ? "Выбрана" : "Выбрать"
                            enabled: !modelCard.selected && !bridge.busy
                            onClicked: bridge.setSetting("model", modelCard.modelData)
                        }
                        PillButton {
                            visible: modelCard.preparing
                            text: "Отмена"
                            onClicked: bridge.cancelModelPrepare()
                        }
                        PillButton {
                            visible: !modelCard.preparing && !modelCard.cached
                            text: "Загрузить"
                            primary: true
                            enabled: !bridge.busy && !bridge.modelPreparing
                            onClicked: { bridge.setSetting("model", modelCard.modelData); bridge.prepareSelectedModel() }
                        }
                        Label {
                            visible: modelCard.cached && !modelCard.preparing
                            text: "Готова к работе"
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                        }
                        Item { Layout.fillWidth: true }
                    }
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: rulesBox.implicitHeight + 2 * Theme.padCard
            radius: Theme.radiusLg
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            ColumnLayout {
                id: rulesBox
                anchors.fill: parent
                anchors.margins: Theme.padCard
                spacing: Theme.gapSm
                Label { text: "Словарь и snippets"; color: Theme.text; font.pixelSize: Theme.fsTitle; font.weight: Font.DemiBold }
                Text { Layout.fillWidth: true; text: "Термины помогают Whisper, а замены применяются только к финальному тексту диктовки. Всё остаётся на этом устройстве."; color: Theme.muted; font.pixelSize: Theme.fsSmall; wrapMode: Text.Wrap }
                RowLayout {
                    id: termRow
                    Layout.fillWidth: true
                    // Enter в любом поле добавляет запись: до этого
                    // словарь пополнялся только мышью.
                    function addTerm() {
                        if (!termInput.text.length)
                            return
                        bridge.addDictionaryEntry(termInput.text, mistakeInput.text)
                        termInput.clear()
                        mistakeInput.clear()
                        termInput.forceActiveFocus()
                    }
                    TextField { id: termInput; Layout.fillWidth: true; placeholderText: "Термин"; color: Theme.text; placeholderTextColor: Theme.muted; onAccepted: termRow.addTerm(); background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                    TextField { id: mistakeInput; Layout.preferredWidth: 180; placeholderText: "Вариант ошибки"; color: Theme.text; placeholderTextColor: Theme.muted; onAccepted: termRow.addTerm(); background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                    PillButton { text: "+"; onClicked: termRow.addTerm(); ToolTip.visible: hovered; ToolTip.text: "Добавить термин" }
                }
                // Список терминов: раньше он был обрезан
                // семьюдесятью пикселями и уже с четвёртой
                // записью словарь нельзя было просмотреть.
                ListView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(160, contentHeight)
                    model: bridge.dictionary
                    clip: true
                    spacing: 2
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: RowLayout {
                        required property var modelData
                        required property int index
                        width: ListView.view.width
                        Text {
                            Layout.fillWidth: true
                            text: modelData.term + (modelData.misheard ? " ← " + modelData.misheard : "")
                            color: Theme.muted
                            elide: Text.ElideRight
                            font.pixelSize: Theme.fsSmall
                        }
                        IconButton {
                            iconName: "close"
                            glyph: 12
                            implicitWidth: 22
                            implicitHeight: 22
                            onClicked: bridge.removeDictionaryEntry(index)
                            ToolTip.visible: hovered
                            ToolTip.text: "Убрать термин"
                        }
                    }
                }
                RowLayout {
                    id: snippetRow
                    Layout.fillWidth: true
                    function addSnippet() {
                        if (!snippetInput.text.length)
                            return
                        bridge.addSnippet(snippetInput.text, expansionInput.text)
                        snippetInput.clear()
                        expansionInput.clear()
                        snippetInput.forceActiveFocus()
                    }
                    TextField { id: snippetInput; Layout.preferredWidth: 180; placeholderText: "Фраза"; color: Theme.text; placeholderTextColor: Theme.muted; onAccepted: snippetRow.addSnippet(); background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                    TextField { id: expansionInput; Layout.fillWidth: true; placeholderText: "Вставляемый текст"; color: Theme.text; placeholderTextColor: Theme.muted; onAccepted: snippetRow.addSnippet(); background: Rectangle { radius: Theme.radiusSm; color: Theme.fill } }
                    PillButton { text: "+"; onClicked: snippetRow.addSnippet(); ToolTip.visible: hovered; ToolTip.text: "Добавить замену" }
                }
                // Добавленные замены раньше исчезали из виду:
                // их некуда было посмотреть и нечем убрать.
                ListView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(120, contentHeight)
                    model: bridge.snippets
                    clip: true
                    spacing: 2
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: RowLayout {
                        required property var modelData
                        required property int index
                        width: ListView.view.width
                        Text {
                            Layout.fillWidth: true
                            text: modelData.trigger + " → " + modelData.expansion
                            color: Theme.muted
                            elide: Text.ElideRight
                            font.pixelSize: Theme.fsSmall
                        }
                        IconButton {
                            iconName: "close"
                            glyph: 12
                            implicitWidth: 22
                            implicitHeight: 22
                            onClicked: bridge.removeSnippet(index)
                            ToolTip.visible: hovered
                            ToolTip.text: "Убрать замену"
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: bridge.snippets.length === 0
                    text: "Замен пока нет. Например: «пдп» → «Подпишитесь на канал»."
                    color: Theme.faint
                    font.pixelSize: Theme.fsSmall
                    wrapMode: Text.Wrap
                }
            }
        }
        }
    }
}
