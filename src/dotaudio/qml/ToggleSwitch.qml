import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

// Переключатель в общей теме. Стандартный Switch брал системную палитру
// и на тёмной поверхности его подпись читалась хуже фона.
Switch {
    id: control

    implicitHeight: 28
    spacing: 10
    hoverEnabled: true

    indicator: Rectangle {
        implicitWidth: 40
        implicitHeight: 22
        x: 0
        y: (control.height - height) / 2
        radius: height / 2
        color: control.checked ? Theme.text : Theme.fill
        border.width: 1
        border.color: control.checked ? Theme.text : control.hovered ? Theme.borderHi : Theme.border

        Behavior on color { ColorAnimation { duration: Theme.baseMs } }
        Behavior on border.color { ColorAnimation { duration: Theme.baseMs } }

        Rectangle {
            width: 16
            height: 16
            radius: 8
            y: 3
            x: control.checked ? parent.width - width - 3 : 3
            color: control.checked ? Theme.bg : Theme.muted
            Behavior on x {
                NumberAnimation {
                    duration: Theme.baseMs
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easeSpring
                }
            }
            Behavior on color { ColorAnimation { duration: Theme.baseMs } }
        }
    }

    contentItem: Text {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        color: control.enabled ? Theme.text : Theme.muted
        font.pixelSize: 12
        font.family: Theme.fontFamily
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.Wrap
    }
}
