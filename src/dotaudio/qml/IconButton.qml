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
    // У кнопки нет подписи, поэтому имя для доступности берётся из
    // подсказки: иначе экранный диктор читает пустую кнопку.
    Accessible.role: Accessible.Button
    Accessible.name: control.ToolTip.text.length ? control.ToolTip.text : control.iconName
    scale: control.down ? 0.92 : control.hovered && control.enabled ? 1.06 : 1
    opacity: control.enabled ? 1 : 0.45

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

    background: Rectangle {
        radius: width / 2
        color: control.down ? Theme.fillPress : control.hovered ? Theme.fillHi : "transparent"
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.borderHi
        Behavior on color { ColorAnimation { duration: Theme.fastMs } }
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
