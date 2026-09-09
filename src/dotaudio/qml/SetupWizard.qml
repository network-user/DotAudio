import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Мастер первого запуска: опрос устройства, брифинг и прогресс загрузок.
Item {
    id: root

    readonly property bool reduceMotion: Boolean(bridge.settings.reduce_motion)

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        opacity: setup.visible ? 1 : 0
        Behavior on opacity {
            enabled: !root.reduceMotion
            NumberAnimation { duration: Theme.baseMs; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easeOut }
        }
        // Блокируем клики в приложение под мастером.
        MouseArea { anchors.fill: parent; enabled: setup.visible }
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(720, parent.width - 48)
        height: Math.min(640, parent.height - 40)
        radius: Theme.radiusXl
        color: Theme.surface
        border.width: 1
        border.color: Theme.borderHi
        opacity: setup.visible ? 1 : 0
        scale: setup.visible ? 1 : 0.96
        Behavior on opacity {
            enabled: !root.reduceMotion
            NumberAnimation { duration: Theme.slowMs; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easeOut }
        }
        Behavior on scale {
            enabled: !root.reduceMotion
            NumberAnimation { duration: Theme.slowMs; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easeSpring }
        }
        MouseArea { anchors.fill: parent }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: Theme.gapMd

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gapSm
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Label {
                        text: {
                            if (setup.phase === "scan") return "Знакомство с устройством"
                            if (setup.phase === "brief") return "Краткий план"
                            if (setup.phase === "run") return "Готовим DotAudio"
                            if (setup.phase === "done") return "Готово"
                            return "Настройка"
                        }
                        color: Theme.text
                        font.pixelSize: Theme.fsHead
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: {
                            if (setup.phase === "scan")
                                return "Определяем процессор, память и доступные ускорители"
                            if (setup.phase === "brief")
                                return "Можно поправить план, затем всё скачается в фоне"
                            if (setup.phase === "run")
                                return setup.message || "Загрузка и подготовка…"
                            if (setup.phase === "done")
                                return setup.error ? setup.message : "Можно пользоваться приложением"
                            return ""
                        }
                        color: Theme.muted
                        font.pixelSize: Theme.fsLabel
                        wrapMode: Text.Wrap
                    }
                }
                Icon {
                    visible: setup.phase === "scan" || (setup.phase === "run" && setup.busy)
                    name: "spinner"
                    width: 22
                    height: 22
                }
            }

            // ---- SCAN ----
            Item {
                visible: setup.phase === "scan"
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.centerIn: parent
                    width: parent.width * 0.82
                    spacing: Theme.gapLg

                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        width: 72
                        height: 72
                        radius: 36
                        color: Theme.fill
                        border.width: 1
                        border.color: Theme.border
                        Icon {
                            anchors.centerIn: parent
                            name: "settings"
                            width: 28
                            height: 28
                        }
                        // Мягкое дыхание кольца во время опроса.
                        SequentialAnimation on opacity {
                            running: setup.phase === "scan" && !root.reduceMotion
                            loops: Animation.Infinite
                            NumberAnimation { from: 0.55; to: 1; duration: 900; easing.type: Easing.InOutSine }
                            NumberAnimation { from: 1; to: 0.55; duration: 900; easing.type: Easing.InOutSine }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: setup.message
                        color: Theme.text
                        font.pixelSize: Theme.fsTitle
                    }
                    // Индетерминированная полоса.
                    Rectangle {
                        Layout.fillWidth: true
                        height: 6
                        radius: 3
                        color: Theme.fill
                        clip: true
                        Rectangle {
                            id: scanBar
                            width: parent.width * 0.35
                            height: parent.height
                            radius: 3
                            color: Theme.text
                            SequentialAnimation on x {
                                running: setup.phase === "scan" && !root.reduceMotion
                                loops: Animation.Infinite
                                NumberAnimation {
                                    from: -scanBar.width
                                    to: card.width
                                    duration: 1400
                                    easing.type: Easing.InOutCubic
                                }
                            }
                        }
                    }
                }
            }

            // ---- BRIEF ----
            Flickable {
                visible: setup.phase === "brief"
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: briefCol.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                ColumnLayout {
                    id: briefCol
                    width: parent.width
                    spacing: Theme.gapMd

                    // Сводка железа.
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: hwGrid.implicitHeight + 28
                        radius: Theme.radiusMd
                        color: Theme.surface2
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            id: hwGrid
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.margins: 14
                            spacing: Theme.gapLg
                            ColumnLayout {
                                spacing: 1
                                Label { text: "Процессор"; color: Theme.faint; font.pixelSize: Theme.fsMicro }
                                Label {
                                    text: (setup.hardware.threads || 0) + " потоков"
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
                                    text: setup.hardware.ram_gb ? (setup.hardware.ram_gb + " ГБ") : "—"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsBody
                                    font.family: Theme.monoFamily
                                    font.weight: Font.DemiBold
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                Label { text: "Ускорение"; color: Theme.faint; font.pixelSize: Theme.fsMicro }
                                Label {
                                    Layout.fillWidth: true
                                    text: setup.briefing.gpuLabel || setup.hardware.compute_label || "CPU"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsBody
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }

                    Label {
                        text: "Найдено"
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        Repeater {
                            model: setup.briefing.technologies || []
                            delegate: Rectangle {
                                required property var modelData
                                width: techLabel.implicitWidth + 20
                                height: 30
                                radius: 15
                                color: modelData.state === "needed" ? Theme.fillHi : Theme.fill
                                border.width: 1
                                border.color: Theme.border
                                Label {
                                    id: techLabel
                                    anchors.centerIn: parent
                                    text: modelData.title + " · " + modelData.detail
                                    color: Theme.text
                                    font.pixelSize: Theme.fsSmall
                                }
                            }
                        }
                    }

                    Label {
                        text: "Что подготовим"
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                    }

                    // Whisper
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: whisperRow.implicitHeight + 24
                        radius: Theme.radiusMd
                        color: Theme.surface2
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            id: whisperRow
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: Theme.gapMd
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Label {
                                    text: setup.briefing.whisperLabel || "Whisper"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: setup.briefing.whisperReady
                                          ? "Уже в кеше · прогреем при старте"
                                          : ("Скачивание · ~" + (setup.briefing.whisperMb || 0) + " МБ · " + (setup.briefing.deviceLabel || ""))
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                            }
                            ToggleSwitch {
                                checked: Boolean(setup.briefing.downloadWhisper) || Boolean(setup.briefing.whisperReady)
                                enabled: !Boolean(setup.briefing.whisperReady)
                                onToggled: setup.updateBriefing({ downloadWhisper: checked })
                            }
                        }
                    }

                    // GPU
                    Rectangle {
                        visible: Boolean(setup.briefing.useGpu) || String(setup.hardware.computeAdvice) === "needs_runtime" || String(setup.hardware.computeAdvice) === "ready"
                        Layout.fillWidth: true
                        implicitHeight: gpuRow.implicitHeight + 24
                        radius: Theme.radiusMd
                        color: Theme.surface2
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            id: gpuRow
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: Theme.gapMd
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Label {
                                    text: setup.briefing.cudaNeeded ? "CUDA runtime" : "Видеокарта"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: setup.briefing.cudaNeeded
                                          ? ("Поставим пакеты NVIDIA · ~" + (setup.briefing.cudaMb || 0) + " МБ")
                                          : (setup.briefing.computeHint || "Использовать GPU для Whisper")
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                            }
                            ToggleSwitch {
                                checked: Boolean(setup.briefing.useGpu)
                                onToggled: setup.updateBriefing({ useGpu: checked })
                            }
                        }
                    }

                    // LLM
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: llmRow.implicitHeight + 24
                        radius: Theme.radiusMd
                        color: Theme.surface2
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            id: llmRow
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: Theme.gapMd
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Label {
                                    text: setup.briefing.llmLabel || "Ассистент"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: setup.briefing.llmReady
                                          ? "Файл уже на диске"
                                          : ("Локальная модель · ~" + (setup.briefing.llmMb || 0) + " МБ")
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                            }
                            ToggleSwitch {
                                checked: Boolean(setup.briefing.downloadLlm) || Boolean(setup.briefing.llmReady)
                                enabled: !Boolean(setup.briefing.llmReady)
                                onToggled: setup.updateBriefing({ downloadLlm: checked })
                            }
                        }
                    }

                    // NVIDIA NeMo
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: nemoRow.implicitHeight + 24
                        radius: Theme.radiusMd
                        color: Theme.surface2
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            id: nemoRow
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: Theme.gapMd
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Label {
                                    text: "NVIDIA NeMo · голоса"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: setup.briefing.nemoReady
                                          ? "Рантайм готов · сверим модель Sortformer"
                                          : ("Рантайм + Sortformer · ~" + (setup.briefing.nemoMb || 0) + " МБ · для транскрибации")
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                            }
                            ToggleSwitch {
                                checked: Boolean(setup.briefing.downloadNemo) || Boolean(setup.briefing.nemoReady)
                                enabled: !Boolean(setup.briefing.nemoReady)
                                onToggled: setup.updateBriefing({ downloadNemo: checked })
                            }
                        }
                    }

                    Label {
                        visible: !Boolean(setup.briefing.ffmpegReady)
                        Layout.fillWidth: true
                        text: "FFmpeg не найден в PATH. Караоке-экспорт и разбор эфиров попросят поставить его отдельно."
                        color: Theme.faint
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }

                    Label {
                        visible: Number(setup.briefing.totalMb) > 0
                        Layout.fillWidth: true
                        text: "Оценка загрузки · ~" + Math.round(Number(setup.briefing.totalMb)) + " МБ"
                        color: Theme.faint
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.monoFamily
                    }
                }
            }

            // ---- RUN / DONE ----
            ColumnLayout {
                visible: setup.phase === "run" || setup.phase === "done"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.gapMd

                // Общий процент.
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            text: Math.round(setup.overallPercent) + "%"
                            color: Theme.text
                            font.pixelSize: Theme.fsHero
                            font.weight: Font.DemiBold
                            font.family: Theme.monoFamily
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: setup.message
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                            elide: Text.ElideRight
                            Layout.maximumWidth: card.width * 0.45
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 8
                        radius: 4
                        color: Theme.fill
                        Rectangle {
                            width: parent.width * Math.max(0, Math.min(1, setup.overallPercent / 100))
                            height: parent.height
                            radius: 4
                            color: Theme.text
                            Behavior on width {
                                enabled: !root.reduceMotion
                                NumberAnimation { duration: Theme.baseMs }
                            }
                        }
                    }
                }

                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: Theme.gapSm
                    model: setup.steps
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width
                        implicitHeight: stepCol.implicitHeight + 20
                        radius: Theme.radiusMd
                        color: Theme.surface2
                        border.width: 1
                        border.color: modelData.status === "active" ? Theme.borderHi : Theme.hairline

                        ColumnLayout {
                            id: stepCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.margins: 12
                            spacing: 6
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.gapSm
                                Icon {
                                    name: modelData.status === "done" ? "check"
                                          : (modelData.status === "error" ? "warning"
                                          : (modelData.status === "active" ? "spinner" : "models"))
                                    width: 16
                                    height: 16
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    color: Theme.text
                                    font.pixelSize: Theme.fsBody
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    visible: modelData.status === "active" || modelData.status === "done"
                                    text: Math.round(Number(modelData.percent || 0)) + "%"
                                    color: Theme.faint
                                    font.pixelSize: Theme.fsSmall
                                    font.family: Theme.monoFamily
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: modelData.message || modelData.detail || ""
                                color: Theme.muted
                                font.pixelSize: Theme.fsSmall
                                wrapMode: Text.Wrap
                            }
                            Rectangle {
                                visible: modelData.status === "active" || Number(modelData.percent) > 0
                                Layout.fillWidth: true
                                height: 4
                                radius: 2
                                color: Theme.fill
                                Rectangle {
                                    width: parent.width * Math.max(0, Math.min(1, Number(modelData.percent || 0) / 100))
                                    height: parent.height
                                    radius: 2
                                    color: Theme.text
                                    Behavior on width {
                                        enabled: !root.reduceMotion
                                        NumberAnimation { duration: Theme.fastMs }
                                    }
                                }
                            }
                        }
                    }
                }

                Label {
                    visible: setup.phase === "done" && setup.error.length > 0
                    Layout.fillWidth: true
                    text: setup.error
                    color: Theme.muted
                    font.pixelSize: Theme.fsSmall
                    wrapMode: Text.Wrap
                }
            }

            // ---- FOOTER ----
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gapSm

                PillButton {
                    visible: setup.phase === "brief"
                    text: "Позже"
                    onClicked: setup.skip()
                }
                PillButton {
                    visible: setup.phase === "run" && setup.busy
                    text: "Отмена"
                    onClicked: setup.cancel()
                }
                Item { Layout.fillWidth: true }
                PillButton {
                    visible: setup.phase === "brief"
                    text: "Настроить автоматически"
                    primary: true
                    onClicked: setup.confirm()
                }
                PillButton {
                    visible: setup.phase === "done"
                    text: "Начать работу"
                    primary: true
                    onClicked: setup.finish()
                }
            }
        }
    }
}
