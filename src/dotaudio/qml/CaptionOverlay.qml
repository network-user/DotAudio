import QtQuick
import QtQuick.Window
import "Theme.js" as Theme

Window {
    id: overlay
    // The preference alone must not leave an empty always-on-top window open.
    // Live owns the overlay lifetime; the setting only opts it in.
    property bool active: Boolean(bridge.liveActive) && Boolean(bridge.settings.caption_overlay)
    width: Math.min(960, Math.floor(Screen.width * 0.7))
    height: {
        var base = bridge.settings.caption_size === "lg" ? 168 : bridge.settings.caption_size === "sm" ? 116 : 140
        return overlay.previousCaption ? base + 28 : base
    }
    color: "transparent"
    visible: overlay.active
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
    x: Math.round((Screen.width - width) / 2)
    y: Math.round(Screen.height - height - Screen.height * 0.12)

    readonly property var currentSegment: bridge.segments.length ? bridge.segments[bridge.segments.length - 1] : null
    readonly property var previousCaption: {
        if (bridge.partialCaption.length > 0 && bridge.segments.length)
            return bridge.segments[bridge.segments.length - 1]
        if (bridge.segments.length >= 2)
            return bridge.segments[bridge.segments.length - 2]
        return null
    }
    // Timestamped words describe finalized segments only. A partial hypothesis
    // must remain plain text, otherwise Flow hides the changing tail.
    readonly property bool usesSegmentWords: bridge.partialCaption.length === 0
                                            && currentSegment !== null
                                            && String(currentSegment.text) === String(bridge.displayCaption)
    readonly property var captionWords: usesSegmentWords && currentSegment.words ? currentSegment.words : []
    // Keep the last finalized key while the next hypothesis changes. This
    // prevents CaptionText from restarting its transition for every partial.
    readonly property string captionKey: currentSegment ? String(currentSegment.id) : ""
    readonly property int captionSize: bridge.settings.caption_size === "lg" ? 44 : bridge.settings.caption_size === "sm" ? 24 : 34
    readonly property bool highContrast: String(bridge.settings.caption_contrast) === "high"

    onVisibleChanged: {
        if (visible) {
            overlay.raise()
            bridge.applyClickThrough(overlay.winId(), true)
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: 16
        color: overlay.highContrast ? Theme.overlayFillHigh : Theme.overlayFill
        border.width: 1
        border.color: Theme.border

        Column {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 6

            Text {
                width: parent.width
                visible: overlay.previousCaption !== null
                text: overlay.previousCaption ? overlay.previousCaption.text : ""
                color: overlay.highContrast ? "#c8c8c4" : Theme.muted
                font.pixelSize: Math.max(16, overlay.captionSize - 12)
                font.family: Theme.fontFamily
                elide: Text.ElideRight
                maximumLineCount: 1
                wrapMode: Text.NoWrap
                horizontalAlignment: Text.AlignHCenter
            }

            CaptionText {
                width: parent.width
                height: parent.height - (overlay.previousCaption ? 28 : 0)
                text: bridge.displayCaption.length > 0 ? bridge.displayCaption
                                                        : bridge.livePhase === "starting" ? "Готовим модель…"
                                                        : bridge.livePhase === "backlog" ? "Догоняем звук"
                                                        : bridge.livePhase === "stopping" ? "Завершаем"
                                                        : "Слушаю"
                words: overlay.captionWords
                segmentKey: overlay.captionKey
                pixelSize: overlay.captionSize
                maxLines: overlay.previousCaption ? 2 : 2
                align: Text.AlignHCenter
                ink: overlay.highContrast ? "#ffffff" : Theme.text
                fadeOnChange: overlay.usesSegmentWords
            }
        }
    }
}
