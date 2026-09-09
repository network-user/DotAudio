import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Дорожки говорящих в духе DAW: каждая роль - полоса с сегментами.
Item {
    id: root
    property var speakers: []
    property var segments: []
    property real duration: 1
    property int focusKey: 0
    property var mutedKeys: ({})
    property var soloKeys: ({})

    signal focusRequested(int key)
    signal seekRequested(real start, real end, int index)
    signal muteToggled(int key)
    signal soloToggled(int key)

    readonly property real total: Math.max(0.001, Number(root.duration))

    function isMuted(key) {
        var k = String(key)
        if (root.soloActive())
            return !Boolean(root.soloKeys[k])
        return Boolean(root.mutedKeys[k])
    }

    function soloActive() {
        for (var k in root.soloKeys) {
            if (root.soloKeys[k])
                return true
        }
        return false
    }

    implicitHeight: Math.max(48, trackCol.implicitHeight)

    ColumnLayout {
        id: trackCol
        anchors.fill: parent
        spacing: 4

        Repeater {
            model: root.speakers
            delegate: RowLayout {
                id: track
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.gapSm
                readonly property int key: Number(modelData.key)
                readonly property bool focused: root.focusKey === track.key
                readonly property bool muted: root.isMuted(track.key)

                PillButton {
                    text: String(modelData.label || ("Голос " + track.key))
                    compact: true
                    Layout.preferredWidth: 110
                    onClicked: root.focusRequested(track.focused ? 0 : track.key)
                    ToolTip.visible: hovered
                    ToolTip.text: "Фильтр списка по этому голосу"
                }
                PillButton {
                    text: track.muted && !root.soloActive() ? "M" : "M"
                    compact: true
                    Layout.preferredWidth: 28
                    opacity: Boolean(root.mutedKeys[String(track.key)]) ? 1 : 0.45
                    onClicked: root.muteToggled(track.key)
                    ToolTip.visible: hovered
                    ToolTip.text: "Mute дорожки"
                }
                PillButton {
                    text: "S"
                    compact: true
                    Layout.preferredWidth: 28
                    opacity: Boolean(root.soloKeys[String(track.key)]) ? 1 : 0.45
                    onClicked: root.soloToggled(track.key)
                    ToolTip.visible: hovered
                    ToolTip.text: "Solo дорожки"
                }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 22
                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusSm
                        color: Theme.surface2
                        border.width: 1
                        border.color: track.focused ? Theme.borderHi : Theme.hairline
                    }
                    Repeater {
                        model: root.segments
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            visible: Number(modelData.role) === track.key
                            x: 2 + (parent.width - 4) * Math.min(1, Number(modelData.start) / root.total)
                            width: Math.max(2, (parent.width - 4)
                                   * Math.min(1, (Number(modelData.end) - Number(modelData.start)) / root.total))
                            y: 3
                            height: parent.height - 6
                            radius: 3
                            color: Theme.speakerInk(track.key)
                            opacity: track.muted ? 0.18 : 0.9
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.seekRequested(
                                    Number(parent.modelData.start),
                                    Number(parent.modelData.end),
                                    parent.index
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
