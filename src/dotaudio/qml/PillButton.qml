import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

Button {
    id: control

    property bool primary: false
    property bool compact: false

    implicitHeight: compact ? 28 : 32
    leftPadding: compact ? 11 : 14
    rightPadding: compact ? 11 : 14
    hoverEnabled: true
    // Нажатие проседает, наведение чуть приподнимает: отклик виден до
    // того, как отработает само действие.
    scale: control.down ? 0.96 : control.hovered && control.enabled ? 1.02 : 1
    opacity: control.enabled ? 1 : 0.5

    Behavior on scale {
        NumberAnimation {
            duration: Theme.fastMs
            easing.type: Easing.Bezier
            easing.bezierCurve: Theme.easeSpring
        }
    }
    Behavior on opacity {
        NumberAnimation { duration: Theme.baseMs }
    }

    contentItem: Text {
        text: control.text
        color: control.primary ? Theme.bg : Theme.text
        font.pixelSize: control.compact ? Theme.fsSmall : 12
        font.weight: Font.DemiBold
        font.family: Theme.fontFamily
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        Behavior on color { ColorAnimation { duration: Theme.baseMs } }
    }

    background: Item {
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: height / 2
            color: "transparent"
            border.width: 1
            border.color: Theme.borderHi
            opacity: control.activeFocus ? 0.9 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.fastMs } }
        }
        Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: control.primary
                   ? (control.down ? "#d6d6d2" : control.hovered ? "#ffffff" : Theme.text)
                   : (control.down ? Theme.fillPress : control.hovered ? Theme.fill : "transparent")
            border.width: control.primary ? 0 : 1
            border.color: control.hovered ? Theme.borderHi : Theme.border
            Behavior on color { ColorAnimation { duration: Theme.fastMs } }
            Behavior on border.color { ColorAnimation { duration: Theme.fastMs } }
        }
    }
}
