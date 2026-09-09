import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Мини-статистика в сводке железа: подпись над значением.
ColumnLayout {
    property string label: ""
    property string value: ""
    spacing: 1
    Label { text: label; color: Theme.faint; font.pixelSize: Theme.fsMicro }
    Label {
        text: value
        color: Theme.text
        font.pixelSize: Theme.fsBody
        font.weight: Font.DemiBold
        font.family: Theme.monoFamily
    }
}
