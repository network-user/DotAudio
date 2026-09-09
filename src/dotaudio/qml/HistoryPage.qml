import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Страница истории: поиск по сессиям, переименование и повторное открытие.
Item {
    id: root

    property string editingId: ""

    function modeLabel(mode) {
        var map = {
            dictation: "Диктовка",
            live: "Live",
            media: "Медиа",
            monitor: "Эфир",
            transcript: "Транскрибация"
        }
        return map[mode] || mode
    }

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
                    text: "Сессии появятся здесь после первой диктовки, Live, транскрибации или разбора файла."
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
                    height: root.editingId === modelData.id ? 96 : 74
                    radius: Theme.radiusMd
                    color: historyHover.containsMouse ? Theme.fill : Theme.surface
                    border.width: 1
                    border.color: historyHover.containsMouse ? Theme.borderHi : Theme.border
                    scale: historyOpen.pressed && root.editingId !== modelData.id ? 0.99 : 1
                    Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                    Behavior on border.color { ColorAnimation { duration: Theme.fastMs } }
                    Behavior on scale { NumberAnimation { duration: Theme.fastMs } }
                    Behavior on height { NumberAnimation { duration: Theme.fastMs } }

                    HoverHandler { id: historyHover }

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: Theme.gapXs

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.gapSm
                            Icon { name: "history"; width: 16; height: 16; ink: Theme.muted }
                            Item {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                implicitHeight: 44
                                ColumnLayout {
                                    anchors.fill: parent
                                    spacing: 3
                                    visible: root.editingId !== historyCard.modelData.id
                                    Text {
                                        text: historyCard.modelData.title
                                        color: Theme.text
                                        font.pixelSize: Theme.fsBody
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: root.modeLabel(historyCard.modelData.mode)
                                              + " · " + historyCard.modelData.segment_count + " фрагм."
                                        color: Theme.muted
                                        font.pixelSize: Theme.fsSmall
                                    }
                                }
                                TextField {
                                    id: titleEdit
                                    anchors.fill: parent
                                    visible: root.editingId === historyCard.modelData.id
                                    text: historyCard.modelData.title
                                    color: Theme.text
                                    font.pixelSize: Theme.fsBody
                                    selectByMouse: true
                                    selectionColor: Theme.fillPress
                                    selectedTextColor: Theme.text
                                    onVisibleChanged: if (visible) { forceActiveFocus(); selectAll() }
                                    Keys.onReturnPressed: saveTitle()
                                    Keys.onEnterPressed: saveTitle()
                                    Keys.onEscapePressed: root.editingId = ""
                                    background: Rectangle {
                                        radius: Theme.radiusSm
                                        color: Theme.fill
                                        border.width: 1
                                        border.color: Theme.borderHi
                                    }
                                    function saveTitle() {
                                        var value = text.trim()
                                        if (!value.length)
                                            return
                                        bridge.renameSession(historyCard.modelData.id, value)
                                        root.editingId = ""
                                    }
                                }
                                MouseArea {
                                    id: historyOpen
                                    anchors.fill: parent
                                    enabled: root.editingId !== historyCard.modelData.id
                                    onClicked: bridge.openSession(historyCard.modelData.id)
                                }
                            }
                            IconButton {
                                iconName: root.editingId === historyCard.modelData.id ? "check" : "edit"
                                onClicked: {
                                    if (root.editingId === historyCard.modelData.id)
                                        titleEdit.saveTitle()
                                    else
                                        root.editingId = historyCard.modelData.id
                                }
                                ToolTip.visible: hovered
                                ToolTip.text: root.editingId === historyCard.modelData.id
                                              ? "Сохранить название"
                                              : "Переименовать"
                            }
                            Icon {
                                visible: root.editingId !== historyCard.modelData.id
                                name: "expand"
                                width: 14
                                height: 14
                                ink: Theme.muted
                                rotation: -90
                            }
                        }
                    }
                }
            }
        }
    }
}
