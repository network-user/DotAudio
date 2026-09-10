import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Тело карточки «Анализ»: статус, кнопки, список проверок, путь к журналу.
// Не полная страница - вставляется как Item внутри карточки.
Item {
    id: panel

    property var doctor: ({})
    property bool running: false
    property bool showTitle: true
    // Контекст первого запуска - передаётся из SettingsPage для «Починить».
    property var setup: null

    implicitHeight: panelCol.implicitHeight

    ColumnLayout {
        id: panelCol
        width: parent.width
        spacing: Theme.gapSm

        Label {
            visible: panel.showTitle
            text: "Анализ"
            color: Theme.text
            font.pixelSize: Theme.fsTitle
            font.weight: Font.DemiBold
        }

        Text {
            Layout.fillWidth: true
            visible: String(panel.doctor.message || "").length > 0
            text: String(panel.doctor.message || "")
            color: Theme.muted
            font.pixelSize: Theme.fsLabel
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gapSm

            PillButton {
                text: "Анализ"
                enabled: !panel.running && String(panel.doctor.phase || "") !== "running"
                onClicked: bridge.runTranscriptDoctor()
            }

            PillButton {
                text: String(panel.doctor.fixLabel || "Починить")
                visible: Boolean(panel.doctor.canFix)
                onClicked: {
                    var fixes = panel.doctor.fixes || []
                    if (fixes.indexOf("setup") >= 0 && panel.setup)
                        panel.setup.beginForced()
                    bridge.fixTranscriptDoctor()
                }
            }

            PillButton {
                text: "Копировать отчёт"
                onClicked: bridge.copyDoctorReport()
            }

            PillButton {
                text: "Журнал"
                onClicked: bridge.openLogFile()
            }

            Item { Layout.fillWidth: true }
        }

        Repeater {
            model: panel.doctor.checks || []
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.gapSm

                StatusDot {
                    active: Boolean(modelData.ok)
                    tint: Boolean(modelData.ok) ? Theme.text : Theme.rec
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Label {
                        Layout.fillWidth: true
                        text: String(modelData.label || "")
                        color: Theme.text
                        font.pixelSize: Theme.fsLabel
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        visible: String(modelData.detail || "").length > 0
                        text: String(modelData.detail || "")
                        color: Boolean(modelData.ok) ? Theme.muted : Theme.rec
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            visible: String(bridge.logFilePath || "").length > 0
            text: String(bridge.logFilePath || "")
            color: Theme.faint
            font.pixelSize: Theme.fsMicro
            font.family: Theme.monoFamily
            elide: Text.ElideMiddle
        }
    }
}
