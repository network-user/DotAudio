import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    property string phase: "ready"
    property bool hoveredIsland: false
    property bool clickThrough: false
    color: Theme.islandFill
    border.width: 1
    border.color: Theme.border
    clip: true

    signal requestTheater()
    signal requestApp(string page)
    signal dragStarted()
    signal dragReleased()

    readonly property bool livePage: bridge.page === "live"
    readonly property var currentSegment: bridge.segments.length ? bridge.segments[bridge.segments.length - 1] : null
    readonly property var captionWords: currentSegment && currentSegment.words ? currentSegment.words : []
    readonly property string captionKey: currentSegment ? String(currentSegment.id) : ""
    readonly property int recSize: phase === "ready" ? 28 : 32

    signal requestModePick()
    signal closeModes()

    MouseArea {
        id: dragArea
        anchors.fill: parent
        hoverEnabled: !root.clickThrough
        z: 0
        onEntered: root.hoveredIsland = true
        onExited: root.hoveredIsland = false
        onPressed: root.dragStarted()
        onReleased: root.dragReleased()
        onDoubleClicked: {
            if (root.livePage)
                root.requestTheater()
            else
                root.requestApp(bridge.page)
        }
    }

    RowLayout {
        visible: root.phase === "ready" || root.phase === "listen" || root.phase === "quiet" || root.phase === "process"
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.topMargin: 8
        anchors.bottomMargin: 8
        spacing: 10
        z: 1

        RecordControl {
            Layout.preferredWidth: root.recSize
            Layout.preferredHeight: root.recSize
        }

        Icon {
            visible: root.phase === "ready"
            name: root.livePage ? "live" : "dictation"
            ink: Theme.text
            width: 16
            height: 16
            TapHandler {
                enabled: !bridge.recording && !bridge.busy
                onTapped: root.requestModePick()
            }
        }
        Label {
            visible: root.phase === "ready"
            text: root.livePage ? "Live" : "Диктовка"
            color: Theme.text
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.family: Theme.fontFamily
            Layout.fillWidth: false
            TapHandler {
                enabled: !bridge.recording && !bridge.busy
                onTapped: root.requestModePick()
            }
        }

        Label {
            visible: root.livePage && (root.phase === "ready" || root.phase === "listen" || root.phase === "quiet")
            text: bridge.liveSourceLabel
            color: Theme.muted
            font.pixelSize: 11
            font.family: Theme.fontFamily
            TapHandler {
                enabled: !bridge.recording && !bridge.busy
                onTapped: bridge.cycleLiveSource()
            }
        }

        Label {
            visible: root.phase === "process"
            text: "Распознаю"
            color: Theme.muted
            font.pixelSize: 12
            font.weight: Font.DemiBold
            font.family: Theme.fontFamily
        }

        Waveform {
            visible: root.phase === "listen" || root.phase === "quiet"
            Layout.fillWidth: true
            Layout.preferredHeight: 12
            bars: 14
            barH: 12
        }

        Item { visible: root.phase === "ready" || root.phase === "process"; Layout.fillWidth: true }

        Label {
            visible: bridge.recording || bridge.busy
            text: bridge.elapsed
            color: Theme.muted
            font.family: Theme.monoFamily
            font.pixelSize: 11
        }

        IconButton {
            visible: root.hoveredIsland && !root.clickThrough && root.phase === "ready"
            iconName: "expand"
            implicitWidth: 28
            implicitHeight: 28
            onClicked: root.livePage ? root.requestTheater() : root.requestApp(bridge.page)
            ToolTip.visible: hovered
            ToolTip.text: root.livePage ? "Субтитры" : "Окно"
            opacity: visible ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 80 } }
        }
    }

    RowLayout {
        visible: root.phase === "caption" || root.phase === "result"
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10
        z: 1

        RecordControl {
            Layout.preferredWidth: 32
            Layout.preferredHeight: 32
            Layout.alignment: Qt.AlignTop
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 4
            Label {
                visible: root.phase === "result"
                text: "В буфере"
                color: Theme.muted
                font.pixelSize: 11
                font.family: Theme.fontFamily
            }
            CaptionText {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: bridge.caption
                words: root.captionWords
                segmentKey: root.captionKey
                pixelSize: 15
                maxLines: 2
            }
            Waveform {
                Layout.fillWidth: true
                Layout.preferredHeight: 10
                bars: 12
                barH: 10
            }
        }

        Label {
            visible: bridge.recording || bridge.busy
            Layout.alignment: Qt.AlignTop
            text: bridge.elapsed
            color: Theme.muted
            font.family: Theme.monoFamily
            font.pixelSize: 11
        }
    }

    RowLayout {
        visible: root.phase === "error"
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10
        z: 1
        Icon { name: "warning"; ink: Theme.text; width: 18; height: 18 }
        Text {
            Layout.fillWidth: true
            text: bridge.notice
            color: Theme.text
            font.pixelSize: 12
            font.family: Theme.fontFamily
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
        IconButton { iconName: "close"; onClicked: bridge.clearNotice() }
    }

    RowLayout {
        visible: root.phase === "modePick"
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8
        z: 2
        PillButton {
            Layout.fillWidth: true
            text: "Live"
            primary: root.livePage
            onClicked: {
                bridge.selectPage("live")
                root.closeModes()
            }
        }
        PillButton {
            Layout.fillWidth: true
            text: "Диктовка"
            primary: !root.livePage
            onClicked: {
                bridge.selectPage("dictation")
                root.closeModes()
            }
        }
        IconButton {
            iconName: "close"
            onClicked: root.closeModes()
        }
    }

    component RecordControl: Button {
        id: rec
        implicitWidth: 32
        implicitHeight: 32
        padding: 0
        hoverEnabled: true
        enabled: !bridge.busy || bridge.recording
        onClicked: bridge.toggleRecording()
        background: Item {
            Rectangle {
                anchors.centerIn: parent
                width: rec.width
                height: rec.height
                radius: rec.width / 2
                color: "transparent"
                border.width: 1
                border.color: Theme.recRing
                visible: bridge.recording
                SequentialAnimation on scale {
                    running: bridge.recording
                    loops: Animation.Infinite
                    NumberAnimation { from: 1; to: 1.18; duration: 800 }
                    NumberAnimation { from: 1.18; to: 1; duration: 800 }
                }
                SequentialAnimation on opacity {
                    running: bridge.recording
                    loops: Animation.Infinite
                    NumberAnimation { from: 0.5; to: 0; duration: 800 }
                    NumberAnimation { from: 0; to: 0.5; duration: 800 }
                }
            }
            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: rec.down ? Theme.fill : rec.hovered ? "#1affffff" : Theme.surface2
                border.width: 1
                border.color: Theme.borderHi
            }
        }
        contentItem: Item {
            Icon {
                visible: bridge.busy && !bridge.recording
                anchors.centerIn: parent
                name: "spinner"
                width: 14
                height: 14
            }
            Rectangle {
                visible: !bridge.busy || bridge.recording
                anchors.centerIn: parent
                width: bridge.recording ? 12 : 10
                height: bridge.recording ? 12 : 10
                radius: bridge.recording ? 3 : 5
                color: Theme.ink
                Behavior on width { NumberAnimation { duration: 180 } }
                Behavior on height { NumberAnimation { duration: 180 } }
                Behavior on radius { NumberAnimation { duration: 180 } }
            }
        }
    }
}
