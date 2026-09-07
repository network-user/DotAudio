import QtQuick
import QtQuick.Window
import "Theme.js" as Theme

// Окно субтитров для зала. Высота фиксируется по выбранному размеру
// текста, поэтому окно не дёргается на каждой фразе: движется только сам
// текст внутри.
Window {
    id: overlay

    property bool active: Boolean(bridge.liveActive) && Boolean(bridge.settings.caption_overlay)
    property bool locked: Boolean(bridge.settings.caption_locked)
    property bool dragging: false
    property real entry: 0

    readonly property bool wanted: overlay.active && !overlay.autoHidden

    width: Math.min(960, Math.floor(hostScreen.width * 0.7))
    height: stageHeight + 58
    color: "transparent"
    visible: overlay.wanted || overlay.opacity > 0.02
    opacity: overlay.wanted ? 1 : 0
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
           | (overlay.locked ? Qt.WindowDoesNotAcceptFocus : 0)

    Behavior on opacity {
        NumberAnimation {
            duration: Theme.slowMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeOut
        }
    }

    readonly property var hostScreen: {
        var screens = Qt.application.screens
        var idx = Number(bridge.settings.caption_screen)
        if (idx >= 0 && idx < screens.length)
            return screens[idx]
        return Screen
    }
    readonly property bool autoHidden: Boolean(bridge.settings.caption_autohide)
        && bridge.displayCaption.length === 0
        && bridge.livePhase !== "starting"
        && bridge.livePhase !== "backlog"
        && bridge.livePhase !== "no_text"
        && bridge.livePhase !== "speech"
        && bridge.livePhase !== "decoding"
        && bridge.livePhase !== "stopping"

    readonly property string previousText: {
        var items = bridge.segments
        if (bridge.partialCaption.length > 0 && items.length)
            return String(items[items.length - 1].text)
        if (items.length >= 2)
            return String(items[items.length - 2].text)
        return ""
    }
    readonly property int captionSize: bridge.settings.caption_size === "lg" ? 44
                                     : bridge.settings.caption_size === "sm" ? 24 : 34
    readonly property int stageHeight: Math.round(captionSize * 1.26 * 2
                                                  + captionSize * 0.46 * 1.3
                                                  + captionSize * 0.34)
    readonly property bool highContrast: String(bridge.settings.caption_contrast) === "high"

    function placeOnScreen() {
        if (overlay.dragging)
            return
        var screen = overlay.hostScreen
        var pos = String(bridge.settings.caption_position)
        if (pos === "floating" && Number(bridge.settings.caption_x) >= 0) {
            overlay.x = Number(bridge.settings.caption_x)
            overlay.y = Number(bridge.settings.caption_y)
            return
        }
        overlay.x = screen.virtualX + Math.round((screen.width - overlay.width) / 2)
        if (pos === "top")
            overlay.y = screen.virtualY + Math.round(screen.height * 0.08)
        else
            overlay.y = screen.virtualY + screen.height - overlay.height - Math.round(screen.height * 0.12)
    }

    onVisibleChanged: {
        if (visible) {
            overlay.placeOnScreen()
            overlay.raise()
            bridge.applyClickThrough(overlay.winId(), overlay.locked)
        }
    }
    onWantedChanged: {
        if (overlay.wanted) {
            overlay.entry = Math.round(overlay.height * 0.12)
            slideIn.restart()
        }
    }
    onWidthChanged: overlay.placeOnScreen()
    onHeightChanged: overlay.placeOnScreen()
    onLockedChanged: {
        if (overlay.visible)
            bridge.applyClickThrough(overlay.winId(), overlay.locked)
    }

    NumberAnimation {
        id: slideIn
        target: overlay
        property: "entry"
        to: 0
        duration: Theme.promoteMs
        easing.type: Easing.Bezier
        easing.bezierCurve: Theme.easeOut
    }

    Connections {
        target: bridge
        function onChanged() { overlay.placeOnScreen() }
    }

    Rectangle {
        id: card
        anchors.fill: parent
        radius: Theme.radiusLg
        color: overlay.highContrast ? Theme.overlayFillHigh : Theme.overlayFill
        border.width: 1
        border.color: Theme.border
        transform: Translate { y: overlay.entry }

        MouseArea {
            id: dragArea
            anchors.fill: parent
            enabled: !overlay.locked
            cursorShape: overlay.locked ? Qt.ArrowCursor : Qt.SizeAllCursor
            property real grabX: 0
            property real grabY: 0
            onPressed: function (mouse) {
                overlay.dragging = true
                grabX = mouse.x
                grabY = mouse.y
            }
            onPositionChanged: function (mouse) {
                if (!pressed)
                    return
                overlay.x += mouse.x - grabX
                overlay.y += mouse.y - grabY
            }
            onReleased: {
                overlay.dragging = false
                bridge.setSetting("caption_position", "floating")
                bridge.setSetting("caption_x", Math.round(overlay.x))
                bridge.setSetting("caption_y", Math.round(overlay.y))
            }
        }

        // Служебная строка уходит, когда на экране есть текст: в зале
        // читают фразу, а не индикаторы.
        Row {
            id: chrome
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.topMargin: 14
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            height: 16
            spacing: 8
            opacity: bridge.displayCaption.length > 0 ? 0 : 1
            visible: opacity > 0.02
            Behavior on opacity { NumberAnimation { duration: Theme.slowMs } }

            StatusDot {
                anchors.verticalCenter: parent.verticalCenter
                active: bridge.recording
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: bridge.liveActive ? bridge.liveStatusText : "LIVE"
                color: overlay.highContrast ? "#ffffff" : Theme.muted
                font.pixelSize: Theme.fsMicro
                font.family: Theme.monoFamily
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: bridge.recording ? bridge.elapsed : ""
                color: overlay.highContrast ? "#ffffff" : Theme.muted
                font.pixelSize: Theme.fsMicro
                font.family: Theme.monoFamily
            }
        }

        CaptionStage {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            anchors.bottomMargin: 20
            height: overlay.stageHeight
            previous: overlay.previousText
            confirmed: bridge.confirmedCaption
            pending: bridge.partialCaption
            placeholder: bridge.liveActive ? bridge.liveStatusText : ""
            pixelSize: overlay.captionSize
            maxLines: 2
            align: Text.AlignHCenter
            ink: overlay.highContrast ? "#ffffff" : Theme.text
            mutedInk: overlay.highContrast ? "#d8d8d4" : Theme.muted
        }
    }
}
