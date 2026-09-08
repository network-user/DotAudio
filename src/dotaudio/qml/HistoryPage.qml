import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Страница истории: поиск по сессиям и повторное открытие.
Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gapMd
        TextField {
            Layout.fillWidth: true
            placeholderText: "Поиск по названию или тексту"
            color: Theme.text
            placeholderTextColor: Theme.muted
            leftPadding: 16
            rightPadding: 16
            onTextChanged: bridge.refreshHistory(text)
            background: Rectangle { radius: 14; color: Theme.surface; border.width: 1; border.color: Theme.border }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(parent.width - 60, 360)
                visible: bridge.history.length === 0
                spacing: Theme.gapSm
                Icon {
                    Layout.alignment: Qt.AlignHCenter
                    name: "history"
                    ink: Theme.faint
                    width: 30
                    height: 30
                }
                Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: "Пока нет сессий"
                    color: Theme.text
                    font.pixelSize: Theme.fsLead
                    font.weight: Font.DemiBold
                }
                Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: "Сессии появятся здесь после первой диктовки, Live или разбора файла."
                    color: Theme.muted
                    font.pixelSize: Theme.fsBody
                }
            }

            ListView {
                anchors.fill: parent
                model: bridge.history
                spacing: Theme.gapSm
                clip: true
                add: Transition {
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.baseMs }
                    NumberAnimation {
                        property: "y"
                        from: 12
                        duration: Theme.slowMs
                        easing.type: Easing.Bezier
                        easing.bezierCurve: Theme.easeOut
                    }
                }
                delegate: Rectangle {
                    id: historyCard
                    required property var modelData
                    width: ListView.view.width
                    height: 74
                    radius: Theme.radiusMd
                    color: historyMouse.containsMouse ? Theme.fill : Theme.surface
                    border.width: 1
                    border.color: historyMouse.containsMouse ? Theme.borderHi : Theme.border
                    scale: historyMouse.pressed ? 0.99 : 1
                    Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                    Behavior on border.color { ColorAnimation { duration: Theme.fastMs } }
                    Behavior on scale { NumberAnimation { duration: Theme.fastMs } }
                    MouseArea { id: historyMouse; anchors.fill: parent; hoverEnabled: true; onClicked: bridge.openSession(historyCard.modelData.id) }
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        Icon { name: "history"; width: 16; height: 16; ink: Theme.muted }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3
                            Text { text: historyCard.modelData.title; color: Theme.text; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                            Text { text: historyCard.modelData.mode + " · " + historyCard.modelData.segment_count + " фрагм."; color: Theme.muted; font.pixelSize: Theme.fsSmall }
                        }
                        Icon { name: "expand"; width: 14; height: 14; ink: Theme.muted; rotation: -90 }
                    }
                }
            }
        }
    }
}
