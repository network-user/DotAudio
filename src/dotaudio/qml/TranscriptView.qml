import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// РћС‚РґРµР»СЊРЅС‹Р№ СЂРµР¶РёРј В«РўСЂР°РЅСЃРєСЂРёР±Р°С†РёСЏВ»: С„Р°Р№Р» -> СЂР°СЃС€РёС„СЂРѕРІРєР° СЃ С‚Р°Р№РјРєРѕРґР°РјРё Рё
// РіРѕРІРѕСЂСЏС‰РёРјРё. Р’РµСЃСЊ РѕР±РјРµРЅ РёРґС‘С‚ С‡РµСЂРµР· РјРѕСЃС‚ bridge.*; СЂР°СЃРїРѕР·РЅР°РІР°РЅРёРµ РІСЃРµРіРґР°
// Р»РѕРєР°Р»СЊРЅРѕ (bridge.runTranscript РЅРёРєРѕРіРґР° РЅРµ РІС‹Р±РёСЂР°РµС‚ СЃРµСЂРІРµСЂ).
Rectangle {
    id: view
    color: "transparent"

    property string phase: String(bridge.transcribeState.phase || "idle")
    property string file: String(bridge.transcribeState.file || "")
    property bool busyPhase: phase === "working"
    property var segs: bridge.transcribeSegments
    property var speakers: bridge.transcribeState.speakers || []

    function timecode(seconds) {
        var total = Math.max(0, Math.round(Number(seconds) * 1000))
        var hours = Math.floor(total / 3600000)
        total -= hours * 3600000
        var minutes = Math.floor(total / 60000)
        total -= minutes * 60000
        var rest = (total / 1000).toFixed(1)
        if (rest.length < 4) rest = "0" + rest
        return (hours > 0 ? (hours < 10 ? "0" : "") + hours + ":" : "")
               + (minutes < 10 ? "0" : "") + minutes + ":" + rest
    }

    Connections {
        target: bridge
        function onTranscribeChanged() { }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gapMd

        // РџР°РЅРµР»СЊ РІС‹Р±РѕСЂР° Рё Р·Р°РїСѓСЃРєР°.
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: topRow.implicitHeight + 2 * Theme.padCard
            radius: Theme.radiusLg
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            ColumnLayout {
                id: topRow
                anchors.fill: parent
                anchors.margins: Theme.padCard
                spacing: Theme.gapSm
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Label {
                            text: view.file.length ? view.file : "Р Р°СЃС€РёС„СЂРѕРІРєР° Р°СѓРґРёРѕ РёР»Рё РІРёРґРµРѕ"
                            color: Theme.text
                            font.pixelSize: Theme.fsTitle
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Label {
                            text: view.file.length
                                  ? "РћР±СЂР°Р±РѕС‚РєР° Р»РѕРєР°Р»СЊРЅРѕ. РђСѓРґРёРѕ РЅРµ РїРѕРєРёРґР°РµС‚ СЌС‚РѕС‚ РєРѕРјРїСЊСЋС‚РµСЂ."
                                  : "РћС‚РєСЂРѕР№С‚Рµ Р·Р°РїРёСЃСЊ, РїРѕР»СѓС‡РёС‚Рµ СЃР»РѕРІР° СЃ С‚Р°Р№РјРєРѕРґР°РјРё Рё РјРµС‚РєРё РіРѕРІРѕСЂСЏС‰РёС…."
                            color: Theme.muted
                            font.pixelSize: Theme.fsSmall
                            wrapMode: Text.Wrap
                        }
                    }
                    PillButton { text: "РћС‚РєСЂС‹С‚СЊ"; enabled: !view.busyPhase; onClicked: bridge.pickTranscriptFile() }
                    PillButton { text: view.busyPhase ? "РЎС‚РѕРї" : "РўСЂР°РЅСЃРєСЂРёР±РёСЂРѕРІР°С‚СЊ"; primary: !view.busyPhase; enabled: view.file.length > 0; onClicked: view.busyPhase ? bridge.stopTranscript() : bridge.runTranscript() }
                    PillButton { text: "РћС‡РёСЃС‚РёС‚СЊ"; enabled: (view.file.length > 0 || view.segs.length > 0) && !view.busyPhase; onClicked: bridge.clearTranscript() }
                    PillButton { text: "РЎРѕС…СЂР°РЅРёС‚СЊвЂ¦"; enabled: view.segs.length > 0 && !view.busyPhase; onClicked: bridge.transcriptExport() }
                }
                Label {
                    visible: view.busyPhase
                    Layout.fillWidth: true
                    text: "Р Р°СЃРїРѕР·РЅР°С‘Рј РЅР° РїСЂРѕС†РµСЃСЃРѕСЂРµвЂ¦ РїРѕСЃР»Рµ СЃР»РѕРІ СЃС‚Р°РІРёРј С‚Р°Р№РјРєРѕРґС‹ Рё РѕРїСЂРµРґРµР»СЏРµРј РіРѕР»РѕСЃР°. Р­С‚Рѕ Р·Р°РЅРёРјР°РµС‚ РІСЂРµРјСЏ РЅР° РґР»РёРЅРЅРѕР№ Р·Р°РїРёСЃРё."
                    color: Theme.faint
                    font.pixelSize: Theme.fsSmall
                    wrapMode: Text.Wrap
                }
            }
        }

        // Р›РµРіРµРЅРґР° РіРѕРІРѕСЂСЏС‰РёС… (РїРµСЂРµРёРјРµРЅРѕРІР°РЅРёРµ: РєР»РёРє Рё РїСЂР°РІРєР°).
        Rectangle {
            Layout.fillWidth: true
            visible: view.speakers.length > 0
            implicitHeight: speakerRow.implicitHeight + 2 * Theme.padCard
            radius: Theme.radiusLg
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            Flow {
                id: speakerRow
                anchors.fill: parent
                anchors.margins: Theme.padCard
                spacing: Theme.gapSm
                Repeater {
                    model: view.speakers
                    delegate: Rectangle {
                        id: chip
                        required property var modelData
                        function commit() {
                            var label = nameField.text.trim()
                            if (label.length) bridge.renameTranscriptSpeaker(Number(modelData.key), label)
                        }
                        width: Math.min(210, Math.max(120, nameField.implicitWidth + labelTail.width + 34))
                                        implicitHeight: 34
                                        radius: Theme.radiusLg
                                        color: Theme.fill
                                        border.width: 1
                                        border.color: Theme.hairline
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 10
                                            spacing: 8
                                            Label { text: String(modelData.key) + "."; color: Theme.muted; font.family: Theme.monoFamily; font.pixelSize: Theme.fsSmall }
                                            TextField {
                                                id: nameField
                                                Layout.fillWidth: true
                                                text: String(modelData.label || "")
                                                color: Theme.text
                                                font.pixelSize: Theme.fsSmall
                                                onActiveFocusChanged: if (!activeFocus) chip.commit()
                                                onEditingFinished: chip.commit()
                                                background: Item {}
                                            }
                                            Label { id: labelTail; text: "В· РіРѕСЃС‚СЊ"; color: Theme.faint; font.pixelSize: Theme.fsSmall }
                                        }
                                }
                }
            }
        }

        // РЎРїРёСЃРѕРє С„СЂР°Р· СЃ РіРѕРІРѕСЂСЏС‰РёРј Рё С‚Р°Р№РјРєРѕРґРѕРј.
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ColumnLayout {
                anchors.centerIn: parent
                visible: view.segs.length === 0 && !view.file.length
                width: Math.min(parent.width - 80, 360)
                spacing: Theme.gapSm
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Р“РѕС‚РѕРІРѕ Рє С‚СЂР°РЅСЃРєСЂРёР±Р°С†РёРё"
                    color: Theme.text
                    font.pixelSize: Theme.fsLead
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: "Р­С‚РѕС‚ СЂР°Р·РґРµР» РЅРµ РєР°СЃР°РµС‚СЃСЏ РєР°СЂР°РѕРєРµ: РІС‹Р±РёСЂР°РµС‚СЃСЏ Р·Р°РїРёСЃСЊ, Р° РїСЂРё Р¶РµР»Р°РЅРёРё РѕРїСЂРµРґРµР»СЏРµС‚СЃСЏ, РєС‚Рѕ РёР· РіРѕРІРѕСЂСЏС‰РёС… С‡С‚Рѕ РїСЂРѕРёР·РЅС‘СЃ."
                    color: Theme.muted
                    font.pixelSize: Theme.fsBody
                }
            }
            ColumnLayout {
                anchors.centerIn: parent
                visible: view.segs.length === 0 && view.file.length && !view.busyPhase
                spacing: Theme.gapSm
                Label {
                    text: "Р¤Р°Р№Р» РІС‹Р±СЂР°РЅ"
                    color: Theme.text
                    font.pixelSize: Theme.fsLead
                    font.weight: Font.DemiBold
                }
                Label {
                    color: Theme.muted
                    font.pixelSize: Theme.fsBody
                    text: "РћРїСЂРµРґРµР»РµРЅРёРµ РіРѕР»РѕСЃРѕРІ Р·Р°СЂР°Р±РѕС‚Р°РµС‚ РїРѕСЃР»Рµ СЂР°СЃРїРѕР·РЅР°РІР°РЅРёСЏ."
                }
            }
            ListView {
                id: segList
                anchors.fill: parent
                model: view.segs
                spacing: Theme.gapSm
                clip: true
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    id: segCard
                    required property var modelData
                    readonly property string label: modelData.speaker || ""
                    width: ListView.view.width
                    implicitHeight: segBody.implicitHeight + 24
                    radius: Theme.radiusMd
                    color: Theme.surface2
                    border.width: 1
                    border.color: Theme.border
                    RowLayout {
                        id: segBody
                        anchors.fill: parent
                        anchors.margins: 11
                        spacing: 10
                        Rectangle {
                            Layout.preferredWidth: 4
                            Layout.fillHeight: true
                            radius: 2
                            color: segCard.label ? Theme.text : Theme.hairline
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.gapSm
                                Label {
                                    text: view.timecode(modelData.start) + " вЂ“ " + view.timecode(modelData.end)
                                    color: Theme.muted
                                    font.family: Theme.monoFamily
                                    font.pixelSize: Theme.fsSmall
                                }
                                Item { Layout.fillWidth: true }
                                Label {
                                    visible: segCard.label.length > 0
                                    text: segCard.label
                                    color: Theme.text
                                    font.pixelSize: Theme.fsSmall
                                    font.weight: Font.DemiBold
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: modelData.text || "-"
                                color: Theme.text
                                font.pixelSize: Theme.fsBody
                                wrapMode: Text.Wrap
                                textFormat: Text.PlainText
                            }
                        }
                    }
                }
            }
        }
    }
}
