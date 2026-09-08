import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Каталог локальных моделей и ускорение. Показывает измеренное железо, что
// уже лежит на диске и чем именно считать: сборкой llama.cpp или Ollama.
Item {
    id: root

    signal closeRequested()

    // Клик мимо листа закрывает его, но не проваливается на страницу под ним.
    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        MouseArea { anchors.fill: parent; onClicked: root.closeRequested() }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(760, parent.width - 40)
        height: Math.min(600, parent.height - 30)
        radius: Theme.radiusXl
        color: Theme.surface
        border.width: 1
        border.color: Theme.borderHi
        MouseArea { anchors.fill: parent }

        // Лист приезжает снизу: видно, что он лежит поверх страницы.
        NumberAnimation on y {
            running: root.visible
            from: root.height
            to: Math.round((root.height - parent.height) / 2)
            duration: Theme.slowMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: Theme.gapMd

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gapSm
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Label {
                        text: "Локальные модели"
                        color: Theme.text
                        font.pixelSize: Theme.fsHead
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: "Работают на этом компьютере. Ничего не отправляется наружу."
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                    }
                }
                IconButton { iconName: "close"; onClicked: root.closeRequested() }
            }

            // Сводка устройства: то, что измерено, без обещаний скорости.
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: hardwareRow.implicitHeight + 24
                radius: Theme.radiusMd
                color: Theme.surface2
                border.width: 1
                border.color: Theme.hairline
                RowLayout {
                    id: hardwareRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    spacing: Theme.gapLg

                    ColumnLayout {
                        spacing: 1
                        Label { text: "Процессор"; color: Theme.faint; font.pixelSize: Theme.fsMicro }
                        Label {
                            text: (assistant.hardware.threads || 0) + " потоков"
                            color: Theme.text
                            font.pixelSize: Theme.fsBody
                            font.family: Theme.monoFamily
                            font.weight: Font.DemiBold
                        }
                    }
                    ColumnLayout {
                        spacing: 1
                        Label { text: "Память"; color: Theme.faint; font.pixelSize: Theme.fsMicro }
                        Label {
                            text: assistant.hardware.ram_gb
                                  ? assistant.hardware.ram_gb + " ГБ" : "неизвестно"
                            color: Theme.text
                            font.pixelSize: Theme.fsBody
                            font.family: Theme.monoFamily
                            font.weight: Font.DemiBold
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Label { text: "Видеокарта"; color: Theme.faint; font.pixelSize: Theme.fsMicro }
                        Label {
                            Layout.fillWidth: true
                            text: assistant.hardware.gpuLabel || "не найдена"
                            color: Theme.text
                            font.pixelSize: Theme.fsBody
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                    }
                    IconButton {
                        iconName: "undo"
                        onClicked: assistant.refreshHardware()
                        ToolTip.visible: hovered
                        ToolTip.text: "Опросить устройство заново"
                    }
                }
            }

            // Чем считать. Строка честно говорит, умеет ли установленная
            // сборка выгружать слои на карту, и как это изменить.
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: accelBox.implicitHeight + 24
                radius: Theme.radiusMd
                color: Theme.fill
                border.width: 1
                border.color: Theme.hairline
                ColumnLayout {
                    id: accelBox
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 12
                    spacing: Theme.gapXs

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        StatusDot { active: assistant.hardware.llamaGpuOffload === true }
                        Label {
                            Layout.fillWidth: true
                            text: assistant.runtimes.length
                                  ? assistant.runtimes.map(function (item) {
                                        return item.label + ": " + item.detail
                                    }).join("   ·   ")
                                  : "Проверяю рантаймы…"
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                            wrapMode: Text.Wrap
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        Label {
                            text: "Считать через"
                            color: Theme.faint
                            font.pixelSize: Theme.fsMicro
                        }
                        Dropdown {
                            Layout.preferredWidth: 190
                            model: [
                                { key: "auto", label: "Автоматически" },
                                { key: "llama_cpp", label: "Встроенный llama.cpp" },
                                { key: "ollama", label: "Ollama" }
                            ]
                            textRole: "label"
                            currentIndex: ["auto", "llama_cpp", "ollama"].indexOf(assistant.runtimePreference)
                            onActivated: function (index) {
                                assistant.setRuntime(["auto", "llama_cpp", "ollama"][index])
                            }
                        }
                        Item { Layout.fillWidth: true }
                        PillButton {
                            compact: true
                            visible: assistant.accelerators.length > 0
                                     && assistant.accelerators[0].available
                                     && assistant.hardware.llamaGpuOffload !== true
                            enabled: !assistant.install.active
                            text: assistant.install.active
                                  ? "Устанавливаю…"
                                  : "Ускорение: " + (assistant.accelerators.length
                                                     ? assistant.accelerators[0].label : "")
                            onClicked: assistant.installAccelerator(assistant.accelerators[0].id)
                            ToolTip.visible: hovered
                            ToolTip.text: assistant.accelerators.length
                                          ? assistant.accelerators[0].command : ""
                        }
                        PillButton {
                            compact: true
                            visible: assistant.modelReady
                            text: "Выгрузить из памяти"
                            onClicked: assistant.unloadModel()
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: assistant.install.log.length > 0
                        text: assistant.install.log
                        color: Theme.faint
                        font.pixelSize: Theme.fsMicro
                        font.family: Theme.monoFamily
                        wrapMode: Text.Wrap
                        maximumLineCount: 4
                        elide: Text.ElideRight
                    }
                }
            }

            ListView {
                id: cards
                objectName: "modelCards"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: Theme.gapSm
                model: assistant.catalog
                ScrollBar.vertical: ScrollBar { }
                delegate: Rectangle {
                    required property var modelData
                    readonly property bool current: assistant.modelId === modelData.id
                    readonly property bool downloading: assistant.download.active
                                                        && assistant.download.model === modelData.id
                    width: cards.width
                    implicitHeight: cardBody.implicitHeight + 24
                    radius: Theme.radiusMd
                    color: current ? Theme.surface3 : Theme.surface2
                    border.width: 1
                    border.color: current ? Theme.borderHi : Theme.hairline
                    Behavior on color { ColorAnimation { duration: Theme.fastMs } }

                    ColumnLayout {
                        id: cardBody
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 12
                        spacing: Theme.gapXs

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            Label {
                                text: modelData.label
                                color: Theme.text
                                font.pixelSize: Theme.fsTitle
                                font.weight: Font.DemiBold
                            }
                            Rectangle {
                                implicitWidth: tierLabel.implicitWidth + 14
                                implicitHeight: 20
                                radius: 10
                                color: Theme.fill
                                border.width: 1
                                border.color: Theme.hairline
                                Label {
                                    id: tierLabel
                                    anchors.centerIn: parent
                                    text: modelData.tierLabel
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsMicro
                                }
                            }
                            Label {
                                visible: modelData.id === assistant.recommendedModel
                                text: "подходит вашему устройству"
                                color: Theme.text
                                font.pixelSize: Theme.fsMicro
                                font.weight: Font.DemiBold
                            }
                            Item { Layout.fillWidth: true }
                            Label {
                                text: modelData.sizeGb + " ГБ"
                                color: Theme.muted
                                font.pixelSize: Theme.fsSmall
                                font.family: Theme.monoFamily
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: modelData.detail
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                            wrapMode: Text.Wrap
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            StatusDot { active: modelData.state === "ok" }
                            Label {
                                Layout.fillWidth: true
                                text: modelData.note
                                     + "   ·   " + modelData.params
                                     + "   ·   контекст " + modelData.context
                                     + (modelData.gpuLayers > 0
                                        ? "   ·   на видеокарту слоёв: " + modelData.gpuLayers : "")
                                color: Theme.faint
                                font.pixelSize: Theme.fsMicro
                                wrapMode: Text.Wrap
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.topMargin: Theme.gapXs
                            spacing: Theme.gapSm
                            PillButton {
                                compact: true
                                visible: modelData.ready
                                enabled: !current
                                text: current ? "Выбрана" : "Выбрать"
                                primary: !current
                                onClicked: assistant.selectModel(modelData.id)
                            }
                            PillButton {
                                compact: true
                                visible: !modelData.onDisk && !modelData.inOllama && !downloading
                                enabled: !assistant.download.active
                                text: "Скачать " + modelData.sizeGb + " ГБ"
                                onClicked: {
                                    assistant.selectModel(modelData.id)
                                    assistant.downloadModel(modelData.id)
                                }
                            }
                            PillButton {
                                compact: true
                                visible: downloading
                                text: "Остановить "
                                      + Math.round((assistant.download.ratio || 0) * 100) + "%"
                                onClicked: assistant.cancelDownload()
                            }
                            Label {
                                visible: modelData.inOllama && !modelData.onDisk
                                text: "уже есть в Ollama"
                                color: Theme.muted
                                font.pixelSize: Theme.fsMicro
                            }
                            Item { Layout.fillWidth: true }
                            PillButton {
                                compact: true
                                visible: modelData.onDisk
                                text: confirmDelete.running ? "Точно удалить?" : "Удалить файл"
                                onClicked: {
                                    if (confirmDelete.running) {
                                        confirmDelete.stop()
                                        assistant.deleteModel(modelData.id)
                                    } else {
                                        confirmDelete.restart()
                                    }
                                }
                                // Удаление гигабайтов - в два нажатия: случайный
                                // клик не должен стирать скачанное.
                                Timer { id: confirmDelete; interval: 2600 }
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            visible: downloading
                            implicitHeight: 4
                            radius: 2
                            color: Theme.fill
                            Rectangle {
                                width: parent.width
                                       * Math.max(0, Math.min(1, assistant.download.ratio || 0))
                                height: parent.height
                                radius: 2
                                color: Theme.text
                                Behavior on width { NumberAnimation { duration: Theme.fastMs } }
                            }
                        }
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                text: "Модели скачиваются с Hugging Face один раз и дальше работают без интернета. "
                    + "Файлы лежат в папке данных программы."
                color: Theme.faint
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.Wrap
            }
        }
    }
}
