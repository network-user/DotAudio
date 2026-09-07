import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

Button {
    id: control
    property string iconName: "close"
    property color ink: Theme.ink
    property int glyph: 16
    implicitWidth: 28
    implicitHeight: 28
    hoverEnabled: true
    background: Rectangle {
        radius: width / 2
        color: control.down ? "#28ffffff" : control.hovered ? "#16ffffff" : "transparent"
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.borderHi
        Behavior on color { ColorAnimation { duration: Theme.contentMs } }
    }
    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            name: control.iconName
            ink: control.enabled ? control.ink : Theme.muted
            width: control.glyph
            height: control.glyph
        }
    }
}
