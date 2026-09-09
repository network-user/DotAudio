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

    // Незаконченное предложение уже стоит в живой строке, в «предыдущих» оно
    // не считается. Пока речь идёт, предыдущая строка - последнее законченное
    // предложение; когда живая строка пуста, его показывает сама строка, а
    // предыдущей становится то, что было перед ним.
    readonly property bool liveEmpty: bridge.displayCaption.length === 0
    readonly property int closedCount: bridge.liveOpenPhrase
        ? Math.max(0, bridge.segments.length - 1) : bridge.segments.length
    readonly property string previousText: {
        var items = bridge.segments
        var count = overlay.closedCount
        if (!overlay.liveEmpty)
            return count > 0 ? String(items[count - 1].text) : ""
        if (bridge.settledCaption.length > 0 && count >= 2)
            return String(items[count - 2].text)
        return ""
    }
    readonly property int captionSize: bridge.settings.caption_size === "lg" ? 44
                                     : bridge.settings.caption_size === "sm" ? 24 : 34
    // Место под текст сцена считает сама: формула высоты живёт в одном месте.
    readonly property int stageHeight: stage.implicitHeight
    readonly property bool highContrast: String(bridge.settings.caption_contrast) === "high"

    function bounded(value, lower, upper) {
        return Math.max(lower, Math.min(upper, value))
    }

    function placeOnScreen() {
        if (overlay.dragging)
            return
        var screen = overlay.hostScreen
        var pos = String(bridge.settings.caption_position)
        if (pos === "floating" && Number(bridge.settings.caption_x) >= 0) {
            // Монитор мог отключиться, сменить DPI или получить другую
            // виртуальную координату. Оставляем хотя бы узкий край окна в
            // пределах выбранного экрана, чтобы субтитры не «пропали» вне
            // видимой области и их можно было вернуть мышью.
            var visibleEdge = 24
            overlay.x = overlay.bounded(
                Number(bridge.settings.caption_x),
                screen.virtualX - overlay.width + visibleEdge,
                screen.virtualX + screen.width - visibleEdge
            )
            overlay.y = overlay.bounded(
                Number(bridge.settings.caption_y),
                screen.virtualY - overlay.height + visibleEdge,
                screen.virtualY + screen.height - visibleEdge
            )
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

    // Положение зависит только от выбранных настроек субтитров и от экрана.
    // Раньше окно пересчитывало место на каждое общее уведомление контроллера,
    // то есть и на каждую секунду записи.
    readonly property string placement: [
        bridge.settings.caption_position,
        bridge.settings.caption_screen,
        bridge.settings.caption_x,
        bridge.settings.caption_y,
    ].join("|")
    onPlacementChanged: overlay.placeOnScreen()

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
            property real pressSX: 0
            property real pressSY: 0
            property bool dragArmed: false
            onPressed: function (mouse) {
                pressSX = mouse.screenX
                pressSY = mouse.screenY
                dragArmed = true
            }
            onPositionChanged: function (mouse) {
                if (!pressed || !dragArmed || overlay.locked)
                    return
                var dx = mouse.screenX - pressSX
                var dy = mouse.screenY - pressSY
                if (dx * dx + dy * dy < 16)
                    return
                dragArmed = false
                overlay.dragging = true
                overlay.startSystemMove()
            }
            onReleased: dragArmed = false
        }

        Timer {
            interval: 32
            running: overlay.dragging
            repeat: true
            onTriggered: {
                if (bridge.primaryButtonDown())
                    return
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
            id: stage
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            anchors.bottomMargin: 20
            height: implicitHeight
            previous: overlay.previousText
            confirmed: overlay.liveEmpty ? bridge.settledCaption : bridge.confirmedCaption
            pending: bridge.partialCaption
            placeholder: bridge.liveActive ? bridge.liveStatusText : ""
            pixelSize: overlay.captionSize
            maxLines: 2
            align: Text.AlignLeft
            ink: overlay.highContrast ? "#ffffff" : Theme.text
            mutedInk: overlay.highContrast ? "#d8d8d4" : Theme.muted
        }
    }
}
