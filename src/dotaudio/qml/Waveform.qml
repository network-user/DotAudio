import QtQuick
import "Theme.js" as Theme

Item {
    id: wave
    property int bars: 14
    property real barH: 12
    property real targetLevel: Math.min(1, Math.max(0, Number(bridge.level) * Theme.levelGain))
    property real inputLevel: targetLevel
    implicitHeight: barH
    clip: true

    Behavior on inputLevel { NumberAnimation { duration: 110; easing.type: Easing.OutQuad } }

    Row {
        anchors.centerIn: parent
        spacing: 3
        Repeater {
            model: wave.bars
            delegate: Rectangle {
                required property int index
                property real shape: 0.18 + Math.abs(Math.sin(index * 1.71)) * 0.82
                width: 3
                height: bridge.recording ? 3 + wave.inputLevel * wave.barH * shape : 3
                radius: 1.5
                color: bridge.recording ? Theme.ink : Theme.border
                anchors.verticalCenter: parent.verticalCenter
                Behavior on height { NumberAnimation { duration: 90 } }
            }
        }
    }
}
