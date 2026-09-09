import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import "Theme.js" as Theme

// Страница караоке: плеер, пословный редактор и экспорт.
Item {
    id: page

    // Время воспроизведения в мм:сс для полосы транспорта.
    function clock(milliseconds) {
        var total = Math.max(0, Math.round(Number(milliseconds) / 1000))
        var minutes = Math.floor(total / 60)
        var seconds = total % 60
        return (minutes < 10 ? "0" : "") + minutes + ":" + (seconds < 10 ? "0" : "") + seconds
    }

    RowLayout {
        anchors.fill: parent
        spacing: Theme.gapLg
        ColumnLayout {
            // Доля ширины задаётся растяжением, а не через
            // parent.width: прежняя привязка зацикливалась и
            // выдавливала редактор за край окна.
            Layout.fillWidth: true
            Layout.horizontalStretchFactor: 53
            Layout.fillHeight: true
            spacing: Theme.gapMd
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.radiusXl
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                clip: true
                VideoOutput { id: mediaVideo; anchors.fill: parent; anchors.margins: 10; visible: mediaPlayer.hasVideo; fillMode: VideoOutput.PreserveAspectFit }
                Image { anchors.fill: parent; anchors.margins: 10; visible: !mediaPlayer.hasVideo && bridge.coverUrl.length > 0; source: bridge.coverUrl; fillMode: Image.PreserveAspectCrop }
                KaraokePreview { visible: bridge.mediaUrl.length > 0; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: Theme.padCard; height: 126; player: mediaPlayer; segments: bridge.segments }
                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 64, 330)
                    visible: !bridge.mediaUrl
                    spacing: 10
                    Icon { Layout.alignment: Qt.AlignHCenter; name: "media"; width: 28; height: 28 }
                    Label { Layout.fillWidth: true; text: "Аудио в караоке"; horizontalAlignment: Text.AlignHCenter; color: Theme.text; font.pixelSize: Theme.fsLead; font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "Откройте аудио или видео, получите текст по словам и доведите таймкоды."; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.fsBody }
                    PillButton { Layout.alignment: Qt.AlignHCenter; text: "Выбрать медиа"; primary: true; onClicked: bridge.importFile() }
                }
            }
            // Транспорт воспроизведения. Без него по записи
            // можно было двигаться только кликом по таймкоду
            // в списке фраз, а паузы не было вовсе.
            RowLayout {
                Layout.fillWidth: true
                visible: bridge.mediaUrl.length > 0
                spacing: Theme.gapSm

                IconButton {
                    readonly property bool running:
                        mediaPlayer.playbackState === MediaPlayer.PlayingState
                    iconName: running ? "stop" : "live"
                    onClicked: running ? mediaPlayer.pause() : mediaPlayer.play()
                    ToolTip.visible: hovered
                    ToolTip.text: running ? "Пауза" : "Воспроизвести"
                }

                Label {
                    text: page.clock(mediaPlayer.position)
                    color: Theme.muted
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.fsSmall
                }

                Slider {
                    id: seek
                    Layout.fillWidth: true
                    from: 0
                    to: Math.max(1, mediaPlayer.duration)
                    // Пока тянут ручку, позиция плеера не
                    // перетирает то, что показывает слайдер.
                    value: pressed ? value : mediaPlayer.position
                    onMoved: mediaPlayer.position = value
                    background: Rectangle {
                        x: seek.leftPadding
                        y: seek.topPadding + seek.availableHeight / 2 - height / 2
                        width: seek.availableWidth
                        height: 3
                        radius: 2
                        color: Theme.fill
                        Rectangle {
                            width: seek.visualPosition * parent.width
                            height: parent.height
                            radius: 2
                            color: Theme.text
                        }
                    }
                    handle: Rectangle {
                        x: seek.leftPadding + seek.visualPosition * (seek.availableWidth - width)
                        y: seek.topPadding + seek.availableHeight / 2 - height / 2
                        width: 12
                        height: 12
                        radius: 6
                        color: Theme.text
                    }
                }

                Label {
                    text: page.clock(mediaPlayer.duration)
                    color: Theme.faint
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.fsSmall
                }
            }

            RowLayout {
                Layout.fillWidth: true
                PillButton { text: "Открыть"; onClicked: bridge.importFile() }
                PillButton { text: "Обложка"; enabled: bridge.mediaUrl.length > 0; onClicked: bridge.chooseCover() }
                IconButton { iconName: "undo"; enabled: bridge.canUndoEdit; onClicked: bridge.undoEdit(); ToolTip.visible: hovered; ToolTip.text: "Отменить правку" }
                IconButton { iconName: "redo"; enabled: bridge.canRedoEdit; onClicked: bridge.redoEdit(); ToolTip.visible: hovered; ToolTip.text: "Повторить правку" }
                Item { Layout.fillWidth: true }
                PillButton { text: "слова→тишина"; enabled: bridge.segments.length > 0; onClicked: bridge.realignKaraoke(); ToolTip.visible: hovered; ToolTip.text: "Притянуть границы слов к тишине аудио (без повторного распознавания)" }
                // Обычная расшифровка, а не только караоке:
                // экспорт был реализован в ядре, но на этой
                // странице его нечем было вызвать.
                PillButton { text: "TXT"; enabled: bridge.segments.length > 0; onClicked: bridge.exportFile("txt") }
                PillButton { text: "SRT"; enabled: bridge.segments.length > 0; onClicked: bridge.exportFile("srt"); ToolTip.visible: hovered; ToolTip.text: "Субтитры с таймкодами (также VTT и JSON - в диктовке)" }
                PillButton { text: "ASS"; enabled: bridge.segments.length > 0; onClicked: bridge.exportKaraokeFile() }
                PillButton { text: bridge.rendering ? "Рендер…" : "MP4"; primary: true; enabled: bridge.segments.length > 0 && !bridge.rendering; onClicked: bridge.exportKaraokeVideo() }
            }
        }
        KaraokeEditor { Layout.fillWidth: true; Layout.horizontalStretchFactor: 47; Layout.fillHeight: true; player: mediaPlayer; segments: bridge.segments; editable: true }
    }
    MediaPlayer { id: mediaPlayer; source: bridge.mediaUrl; videoOutput: mediaVideo; audioOutput: AudioOutput {} }

    function applyPendingSeek() {
        if (bridge.pendingSeekMs < 0 || mediaPlayer.duration <= 0)
            return
        mediaPlayer.position = bridge.pendingSeekMs
        bridge.clearPendingSeek()
    }

    Connections {
        target: bridge
        function onChanged() { page.applyPendingSeek() }
    }

    Connections {
        target: mediaPlayer
        function onDurationChanged() { page.applyPendingSeek() }
    }
}
