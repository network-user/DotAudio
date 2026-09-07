import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

Button {
    id: control
    property bool primary: false
    implicitHeight: 32
    leftPadding: 14
    rightPadding: 14
    hoverEnabled: true
    contentItem: Text {
        text: control.text
        color: control.primary ? Theme.bg : (control.enabled ? Theme.text : Theme.muted)
        font.pixelSize: 12
        font.weight: Font.DemiBold
        font.family: Theme.fontFamily
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 16
        color: control.primary
               ? (control.down ? "#d8d8d4" : control.hovered ? "#ffffff" : Theme.text)
               : (control.down ? "#26ffffff" : control.hovered ? "#14ffffff" : "transparent")
        border.width: control.primary ? 0 : 1
        border.color: control.activeFocus ? Theme.borderHi : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.contentMs } }
    }
}
