import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Мастер первого запуска: опрос устройства, брифинг и прогресс загрузок.
Item {
    id: root

    // Контекст setup иногда null на кадр (async Loader, recreate HWND, teardown).
    // Без охраны биндинги сыплют TypeError в консоль во время нормальной работы.
    readonly property bool setupAlive: setup !== null && setup !== undefined
    readonly property bool setupVisible: setupAlive && Boolean(setup.visible)
    readonly property bool setupBusy: setupAlive && Boolean(setup.busy)
    readonly property string setupPhase: setupAlive ? String(setup.phase || "") : ""
    readonly property string setupMessage: setupAlive ? String(setup.message || "") : ""
    readonly property string setupError: setupAlive ? String(setup.error || "") : ""
    readonly property real setupPercent: setupAlive ? Number(setup.overallPercent || 0) : 0
    readonly property var setupHw: (setupAlive && setup.hardware) ? setup.hardware : ({})
    readonly property var setupBrief: (setupAlive && setup.briefing) ? setup.briefing : ({})
    readonly property var setupSteps: (setupAlive && setup.steps) ? setup.steps : []
    readonly property bool reduceMotion: (bridge && bridge.settings)
                                         ? Boolean(bridge.settings.reduce_motion) : false

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        opacity: root.setupVisible ? 1 : 0
        Behavior on opacity {
            enabled: !root.reduceMotion
            NumberAnimation { duration: Theme.baseMs; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easeOut }
        }
        // Блокируем клики в приложение под мастером.
        MouseArea { anchors.fill: parent; enabled: root.setupVisible }
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
        opacity: root.setupVisible ? 1 : 0
        scale: root.setupVisible ? 1 : 0.96
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
                            if (root.setupPhase === "scan") return "Знакомство с устройством"
                            if (root.setupPhase === "brief") return "Краткий план"
                            if (root.setupPhase === "run") return "Готовим DotAudio"
                            if (root.setupPhase === "done") return "Готово"
                            return "Настройка"
                        }
                        color: Theme.text
                        font.pixelSize: Theme.fsHead
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: {
                            if (root.setupPhase === "scan")
                                return "Определяем процессор, память и доступные ускорители"
                            if (root.setupPhase === "brief")
                                return "Можно поправить план, затем всё скачается в фоне"
                            if (root.setupPhase === "run")
                                return root.setupMessage || "Загрузка и подготовка…"
                            if (root.setupPhase === "done")
                                return root.setupError ? root.setupMessage : "Можно пользоваться приложением"
                            return ""
                        }
                        color: Theme.muted
                        font.pixelSize: Theme.fsLabel
                        wrapMode: Text.Wrap
                    }
                }
                Icon {
                    visible: root.setupPhase === "scan" || (root.setupPhase === "run" && root.setupBusy)
                    name: "spinner"
                    width: 22
                    height: 22
                }
            }

            // ---- SCAN ----
            Item {
                visible: root.setupPhase === "scan"
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
                            running: root.setupPhase === "scan" && !root.reduceMotion
                            loops: Animation.Infinite
                            NumberAnimation { from: 0.55; to: 1; duration: 900; easing.type: Easing.InOutSine }
                            NumberAnimation { from: 1; to: 0.55; duration: 900; easing.type: Easing.InOutSine }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: root.setupMessage
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
                                running: root.setupPhase === "scan" && !root.reduceMotion
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
                visible: root.setupPhase === "brief"
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
                                    text: (root.setupHw.threads || 0) + " потоков"
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
                                    text: root.setupHw.ram_gb ? (root.setupHw.ram_gb + " ГБ") : "—"
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
                                    text: root.setupBrief.gpuLabel || root.setupHw.compute_label || "CPU"
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
                            model: root.setupBrief.technologies || []
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
                                    text: root.setupBrief.whisperLabel || "Whisper"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: root.setupBrief.whisperReady
                                          ? "Уже в кеше · прогреем при старте"
                                          : ("Скачивание · ~" + (root.setupBrief.whisperMb || 0) + " МБ · " + (root.setupBrief.deviceLabel || ""))
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                            }
                            ToggleSwitch {
                                checked: Boolean(root.setupBrief.downloadWhisper) || Boolean(root.setupBrief.whisperReady)
                                enabled: !Boolean(root.setupBrief.whisperReady)
                                onToggled: if (setup) setup.updateBriefing({ downloadWhisper: checked })
                            }
                        }
                    }

                    // GPU
                    Rectangle {
                        visible: Boolean(root.setupBrief.useGpu) || String(root.setupHw.computeAdvice) === "needs_runtime" || String(root.setupHw.computeAdvice) === "ready"
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
                                    text: root.setupBrief.cudaNeeded ? "CUDA runtime" : "Видеокарта"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: root.setupBrief.cudaNeeded
                                          ? ("Поставим пакеты NVIDIA · ~" + (root.setupBrief.cudaMb || 0) + " МБ")
                                          : (root.setupBrief.computeHint || "Использовать GPU для Whisper")
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                            }
                            ToggleSwitch {
                                checked: Boolean(root.setupBrief.useGpu)
                                onToggled: if (setup) setup.updateBriefing({ useGpu: checked })
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
                                    text: root.setupBrief.llmLabel || "Ассистент"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: root.setupBrief.llmReady
                                          ? "Файл уже на диске"
                                          : ("Локальная модель · ~" + (root.setupBrief.llmMb || 0) + " МБ")
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                            }
                            ToggleSwitch {
                                checked: Boolean(root.setupBrief.downloadLlm) || Boolean(root.setupBrief.llmReady)
                                enabled: !Boolean(root.setupBrief.llmReady)
                                onToggled: if (setup) setup.updateBriefing({ downloadLlm: checked })
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
                                    text: root.setupBrief.nemoReady
                                          ? "Рантайм готов · сверим модель Sortformer"
                                          : ("Рантайм + Sortformer · ~" + (root.setupBrief.nemoMb || 0) + " МБ · для транскрибации")
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                            }
                            ToggleSwitch {
                                checked: Boolean(root.setupBrief.downloadNemo) || Boolean(root.setupBrief.nemoReady)
                                enabled: !Boolean(root.setupBrief.nemoReady)
                                onToggled: if (setup) setup.updateBriefing({ downloadNemo: checked })
                            }
                        }
                    }

                    Label {
                        visible: !Boolean(root.setupBrief.ffmpegReady) && !Boolean(root.setupBrief.downloadFfmpeg)
                        Layout.fillWidth: true
                        text: "FFmpeg отключён: караоке-экспорт и разбор эфиров будут недоступны, пока не поставите его."
                        color: Theme.faint
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }

                    // FFmpeg
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: ffmpegRow.implicitHeight + 24
                        radius: Theme.radiusMd
                        color: Theme.surface2
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            id: ffmpegRow
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: Theme.gapMd
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Label {
                                    text: "FFmpeg"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsTitle
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: root.setupBrief.ffmpegReady
                                          ? "Найден в PATH или в папке tools"
                                          : ("Портативная сборка · ~" + (root.setupBrief.ffmpegMb || 0) + " МБ · караоке и эфиры")
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.Wrap
                                }
                            }
                            ToggleSwitch {
                                checked: Boolean(root.setupBrief.downloadFfmpeg) || Boolean(root.setupBrief.ffmpegReady)
                                enabled: !Boolean(root.setupBrief.ffmpegReady)
                                onToggled: if (setup) setup.updateBriefing({ downloadFfmpeg: checked })
                            }
                        }
                    }

                    Label {
                        visible: Number(root.setupBrief.totalMb) > 0
                        Layout.fillWidth: true
                        text: "Оценка загрузки · ~" + Math.round(Number(root.setupBrief.totalMb)) + " МБ"
                        color: Theme.faint
                        font.pixelSize: Theme.fsSmall
                        font.family: Theme.monoFamily
                    }
                }
            }

            // ---- RUN / DONE ----
            ColumnLayout {
                visible: root.setupPhase === "run" || root.setupPhase === "done"
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
                            text: Math.round(root.setupPercent) + "%"
                            color: Theme.text
                            font.pixelSize: Theme.fsHero
                            font.weight: Font.DemiBold
                            font.family: Theme.monoFamily
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            text: root.setupMessage
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
                            width: parent.width * Math.max(0, Math.min(1, root.setupPercent / 100))
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
                    model: root.setupSteps
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
                    visible: root.setupPhase === "done" && root.setupError.length > 0
                    Layout.fillWidth: true
                    text: root.setupError
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
                    visible: root.setupPhase === "brief"
                    text: "Позже"
                    onClicked: if (setup) setup.skip()
                }
                PillButton {
                    visible: root.setupPhase === "run" && root.setupBusy
                    text: "Отмена"
                    onClicked: if (setup) setup.cancel()
                }
                Item { Layout.fillWidth: true }
                PillButton {
                    visible: root.setupPhase === "brief"
                    text: "Настроить автоматически"
                    primary: true
                    onClicked: if (setup) setup.confirm()
                }
                PillButton {
                    visible: root.setupPhase === "done"
                    text: "Начать работу"
                    primary: true
                    onClicked: if (setup) setup.finish()
                }
            }
        }
    }
}
