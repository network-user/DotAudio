import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

// Выпадающий список в теме приложения. Базовый ComboBox приносил системную
// рамку и стрелку, из-за чего строки устройств выглядели чужими среди
// остальных элементов.
ComboBox {
    id: control

    implicitHeight: 34
    hoverEnabled: true
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fsLabel

    contentItem: Text {
        leftPadding: 13
        rightPadding: 32
        text: control.displayText
        color: control.enabled ? Theme.text : Theme.muted
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Icon {
        x: control.width - width - 11
        y: (control.height - height) / 2
        width: 14
        height: 14
        name: "expand"
        ink: !control.enabled ? Theme.faint
             : control.hovered || control.popup.visible ? Theme.text : Theme.muted
        rotation: control.popup.visible ? 180 : 0
        Behavior on rotation {
            NumberAnimation {
                duration: Theme.baseMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
    }

    background: Rectangle {
        radius: Theme.radiusMd
        color: control.down ? Theme.fillPress : control.hovered ? Theme.fillHi : Theme.fill
        border.width: 1
        border.color: control.popup.visible || control.activeFocus ? Theme.borderHi : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.fastMs } }
        Behavior on border.color { ColorAnimation { duration: Theme.fastMs } }
    }

    delegate: ItemDelegate {
        id: option
        required property var model
        required property int index

        width: ListView.view ? ListView.view.width : control.width
        implicitHeight: 32
        highlighted: control.highlightedIndex === option.index

        contentItem: Text {
            leftPadding: 8
            text: control.textRole ? option.model[control.textRole] : option.model
            color: control.currentIndex === option.index ? Theme.text : Theme.muted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsLabel
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: Theme.radiusSm
            color: option.highlighted ? Theme.fillHi : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.instantMs } }
        }
    }

    popup: Popup {
        y: control.height + 6
        width: control.width
        implicitHeight: Math.min(260, list.contentHeight + 12)
        padding: 6

        contentItem: ListView {
            id: list
            clip: true
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }

        background: Rectangle {
            radius: Theme.radiusMd
            color: Theme.surface3
            border.width: 1
            border.color: Theme.borderHi
        }

        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.contentMs }
            NumberAnimation {
                property: "scale"
                from: 0.97
                to: 1
                duration: Theme.baseMs
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easeOut
            }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.fastMs }
        }
    }
}
