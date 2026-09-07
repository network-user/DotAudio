import QtQuick
import QtQuick.Window
import "Theme.js" as Theme

Window {
    id: overlay
    property bool active: Boolean(bridge.settings.caption_overlay)
    width: Math.min(960, Math.floor(Screen.width * 0.7))
    height: bridge.settings.caption_size === "lg" ? 160 : bridge.settings.caption_size === "sm" ? 108 : 128
    color: "transparent"
    visible: overlay.active
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
    x: Math.round((Screen.width - width) / 2)
    y: Math.round(Screen.height - height - Screen.height * 0.12)

    readonly property var currentSegment: bridge.segments.length ? bridge.segments[bridge.segments.length - 1] : null
    readonly property var captionWords: currentSegment && currentSegment.words ? currentSegment.words : []
    readonly property string captionKey: currentSegment ? String(currentSegment.id) : ""
    readonly property int captionSize: bridge.settings.caption_size === "lg" ? 52 : bridge.settings.caption_size === "sm" ? 28 : 40
    readonly property bool highContrast: String(bridge.settings.caption_contrast) === "high"

    onVisibleChanged: {
        if (visible)
            overlay.raise()
    }

    Rectangle {
        anchors.fill: parent
        radius: 16
        color: overlay.highContrast ? Theme.overlayFillHigh : Theme.overlayFill
        border.width: 1
        border.color: Theme.border

        CaptionText {
            anchors.fill: parent
            anchors.margins: 22
            text: bridge.caption
            words: overlay.captionWords
            segmentKey: overlay.captionKey
            pixelSize: overlay.captionSize
            maxLines: 2
            align: Text.AlignHCenter
            ink: overlay.highContrast ? "#ffffff" : Theme.text
            fadeOnChange: true
        }
    }
}
