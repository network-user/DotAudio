import QtQuick
import "Theme.js" as Theme

// Точка состояния: спокойная в покое, с расходящимся кольцом во время
// записи. Кольцо - только подсветка активности; состояние всегда
// подписано текстом рядом, чтобы не передавать смысл одним цветом.
Item {
    id: dot

    property bool active: false
    property color tint: active ? Theme.rec : Theme.muted
    property real core: 7

    implicitWidth: core
    implicitHeight: core

    Rectangle {
        id: halo
        anchors.centerIn: parent
        width: dot.core
        height: dot.core
        radius: width / 2
        color: "transparent"
        border.width: 1
        border.color: dot.tint
        visible: dot.active
        opacity: 0

        SequentialAnimation {
            running: dot.active
            loops: Animation.Infinite
            ParallelAnimation {
                NumberAnimation {
                    target: halo
                    property: "scale"
                    from: 1
                    to: 2.6
                    duration: 1400
                    easing.type: Easing.OutCubic
                }
                SequentialAnimation {
                    NumberAnimation { target: halo; property: "opacity"; from: 0; to: 0.5; duration: 220 }
                    NumberAnimation { target: halo; property: "opacity"; to: 0; duration: 1180; easing.type: Easing.OutCubic }
                }
            }
        }
    }

    Rectangle {
        id: pip
        anchors.centerIn: parent
        width: dot.core
        height: dot.core
        radius: width / 2
        color: dot.tint

        Behavior on color { ColorAnimation { duration: Theme.baseMs } }

        SequentialAnimation {
            running: dot.active
            loops: Animation.Infinite
            onRunningChanged: if (!running) pip.opacity = 1
            NumberAnimation { target: pip; property: "opacity"; to: 0.45; duration: 700; easing.type: Easing.InOutSine }
            NumberAnimation { target: pip; property: "opacity"; to: 1.0; duration: 700; easing.type: Easing.InOutSine }
        }
    }
}
