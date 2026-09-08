import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Live-сцена. Главное здесь - читаемый текст, поэтому окно устроено как
// страница разговора: тонкая полоса состояния сверху, поток речи в середине
// и одна кнопка внизу.
//
// Раньше тот же текст показывали три виджета сразу (лента огрызков, строка
// «предыдущая фраза» и всплывающая панель истории), а в полосе состояния
// стояло больше десяти кнопок подряд. Теперь поток один - `LiveTranscript`,
// а второстепенные действия убраны под кнопку «ещё».
Rectangle {
    id: root

    property bool embedded: false

    color: Theme.surface
    radius: Theme.radiusXl
    border.width: 1
    border.color: Theme.border
    clip: true

    signal requestIsland()
    signal requestApp()
    // Пользователь тянет окно / растягивает за угол (нативные окно-действия).
    signal requestWindowMove()
    signal requestWindowEdgeResize()
    // Замок фиксирует положение и размер окна Live и делает клики сквозными.
    readonly property bool locked: Boolean(bridge.settings.live_locked)
    readonly property bool overlayOn: Boolean(bridge.settings.caption_overlay)
    readonly property bool showTimes: Boolean(bridge.settings.live_show_times)
    readonly property string stageHint: bridge.liveActive
        ? bridge.liveStatusText
        : "Нажмите «Слушать» - речь появится здесь"
    // Это измеренное отставание последнего принятого фрагмента, а не обещание
    // скорости модели. После первой фразы оно помогает сразу увидеть, успевает
    // ли выбранный профиль за текущим источником.
    readonly property string latencyLabel: {
        var ms = Math.max(0, Number(bridge.liveLatencyMs))
        if (!bridge.liveActive || ms < 1)
            return ""
        return ms < 1000 ? "≈ " + Math.round(ms) + " мс"
                         : "≈ " + (Math.round(ms / 100) / 10) + " с"
    }
    readonly property string sourceCheckText: String(bridge.deviceTest.message || "")

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.padCard
        spacing: Theme.gapMd

        // Полоса состояния: слева что происходит, справа чем управляют.
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            spacing: Theme.gapSm

            StatusDot { active: bridge.recording }

            Label {
                Layout.fillWidth: true
                text: bridge.liveActive ? bridge.liveStatusText
                      : bridge.busy ? "Завершаем" : "Live не запущен"
                color: bridge.recording ? Theme.text : Theme.muted
                font.pixelSize: Theme.fsSmall
                font.weight: Font.DemiBold
                font.family: Theme.fontFamily
                elide: Text.ElideRight
                Behavior on color { ColorAnimation { duration: Theme.slowMs } }
            }

            Label {
                opacity: bridge.recording || bridge.busy ? 1 : 0
                text: bridge.elapsed
                color: Theme.muted
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fsSmall
                Behavior on opacity { NumberAnimation { duration: Theme.baseMs } }
            }

            Label {
                visible: root.latencyLabel.length > 0
                text: root.latencyLabel
                color: Theme.faint
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fsSmall
                ToolTip.visible: latencyHover.hovered
                ToolTip.text: "Отставание последнего текста от аудио"
                HoverHandler { id: latencyHover }
            }

            PillButton {
                compact: true
                text: bridge.liveSourceLabel
                enabled: !bridge.recording && !bridge.busy
                onClicked: bridge.cycleLiveSource()
                ToolTip.visible: hovered
                ToolTip.text: "Микрофон, звук компьютера или оба сразу"
            }

            PillButton {
                compact: true
                text: bridge.liveSensitivityLabel
                enabled: !bridge.recording && !bridge.busy
                onClicked: bridge.toggleLiveSensitivity()
                ToolTip.visible: hovered
                ToolTip.text: "«Речь» показывает только речь, «Всё» - любой звук, включая песни"
            }

            IconButton {
                iconName: "overlay"
                ink: root.overlayOn ? Theme.text : Theme.muted
                onClicked: bridge.setSetting("caption_overlay", !root.overlayOn)
                ToolTip.visible: hovered
                ToolTip.text: root.overlayOn ? "Скрыть субтитры зала" : "Показать субтитры зала"
            }

            IconButton {
                id: moreButton
                iconName: "more"
                ink: extras.opened ? Theme.text : Theme.muted
                onClicked: extras.opened ? extras.close() : extras.open()
                ToolTip.visible: hovered && !extras.opened
                ToolTip.text: "Остальные действия"
            }

            // Ребро-захват: тянуть маленькое поле - перемещать окно.
            Item {
                Layout.preferredWidth: 16
                Layout.preferredHeight: 22
                visible: !root.embedded && !root.locked
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.SizeAllCursor
                    onPressed: root.requestWindowMove()
                }
                Icon { name: "move"; ink: Theme.muted; width: 15; height: 15; anchors.centerIn: parent }
            }

            // Ребро-захват: растянуть окно за угол (native resize).
            Item {
                Layout.preferredWidth: 12
                Layout.preferredHeight: 22
                visible: !root.embedded && !root.locked
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.SizeFDiagCursor
                    onPressed: root.requestWindowEdgeResize()
                }
                Icon { name: "sizer"; ink: Theme.muted; width: 12; height: 22; anchors.centerIn: parent }
            }

            IconButton {
                visible: !root.embedded
                iconName: "expand"
                onClicked: root.requestApp()
                ToolTip.visible: hovered
                ToolTip.text: "Открыть окно приложения"
            }

            IconButton {
                visible: !root.embedded
                iconName: "collapse"
                onClicked: root.requestIsland()
                ToolTip.visible: hovered
                ToolTip.text: "Свернуть в остров"
            }
        }

        // Перед стартом результат проверки остаётся рядом с кнопкой запуска:
        // не нужно уходить в настройки, чтобы понять, слышит ли Live источник.
        Label {
            Layout.fillWidth: true
            visible: !bridge.liveActive && root.sourceCheckText.length > 0
            text: root.sourceCheckText
            color: bridge.deviceTest.phase === "error" || bridge.deviceTest.phase === "silent"
                ? Theme.rec : Theme.muted
            font.pixelSize: Theme.fsSmall
            font.family: Theme.fontFamily
            wrapMode: Text.Wrap
        }

        // Поток речи: сказанное выше, текущая фраза внизу.
        LiveTranscript {
            id: transcript
            objectName: "liveTranscript"
            Layout.fillWidth: true
            Layout.fillHeight: true
            segments: bridge.segments
            confirmed: bridge.confirmedCaption
            pending: bridge.partialCaption
            placeholder: root.stageHint
            pixelSize: root.embedded ? Theme.fsStageSm : Theme.fsStage
            liveLines: 3
            showTimes: root.showTimes
            reduceMotion: Boolean(bridge.settings.reduce_motion)
            onCopyRequested: text => bridge.copyPhrase(text)
        }

        // Управление. Уровень стоит прямо над кнопкой: видно, слышит ли
        // приложение источник, до того как нажали «Слушать».
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.gapSm

            Waveform {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredHeight: 20
                bars: 32
                barH: 20
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gapSm

                Item { Layout.fillWidth: true }

                PillButton {
                    text: bridge.recording ? "Стоп" : bridge.busy ? "Останавливаем" : "Слушать"
                    primary: true
                    enabled: !bridge.busy || bridge.recording
                    onClicked: bridge.toggleRecording()
                }

                PillButton {
                    visible: bridge.busy
                    compact: true
                    text: bridge.recording ? "Отменить" : "Остановить сейчас"
                    onClicked: bridge.forceStop()
                    ToolTip.visible: hovered
                    ToolTip.text: "Остановить без сохранения незавершённой фразы"
                }

                Item { Layout.fillWidth: true }
            }
        }
    }

    // Второстепенные действия. В полосе состояния остаются только те, что
    // трогают во время речи; остальное живёт здесь и не отнимает ширину.
    Popup {
        id: extras
        parent: moreButton
        x: -width + moreButton.width
        y: moreButton.height + Theme.gapXs
        padding: Theme.gapSm
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: Theme.surface2
            radius: Theme.radiusMd
            border.width: 1
            border.color: Theme.borderHi
        }

        contentItem: ColumnLayout {
            spacing: Theme.gapXs

            Label {
                Layout.fillWidth: true
                text: "Движок: " + bridge.liveModelText
                color: Theme.muted
                font.pixelSize: Theme.fsSmall
                font.family: Theme.fontFamily
                bottomPadding: Theme.gapXs
            }

            PillButton {
                Layout.fillWidth: true
                compact: true
                text: bridge.deviceTest.phase === "starting" || bridge.deviceTest.phase === "listening"
                    ? "Проверяем источник…" : "Проверить источник"
                enabled: !bridge.recording && !bridge.busy
                    && bridge.deviceTest.phase !== "starting" && bridge.deviceTest.phase !== "listening"
                onClicked: bridge.testLiveSource()
            }

            PillButton {
                Layout.fillWidth: true
                compact: true
                text: "Скопировать расшифровку"
                enabled: bridge.text.length > 0
                onClicked: { bridge.copyText(); extras.close() }
            }

            PillButton {
                Layout.fillWidth: true
                compact: true
                text: root.showTimes ? "Скрыть таймкоды" : "Показать таймкоды"
                onClicked: bridge.setSetting("live_show_times", !root.showTimes)
            }

            PillButton {
                Layout.fillWidth: true
                compact: true
                visible: !root.embedded
                text: root.locked ? "Снять фиксацию окна" : "Зафиксировать окно"
                onClicked: bridge.setSetting("live_locked", !root.locked)
            }
        }
    }
}
