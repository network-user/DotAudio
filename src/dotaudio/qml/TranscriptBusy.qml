import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Карточка занятости транскрибации: этап ASR или разметки голосов,
// декоративные столбики и полоса прогресса (или shimmer без числа).
//
// Столбики - индикатор работы пайплайна, не RMS микрофона. Высоты
// синтетические, чтобы не путать с Waveform на записи.
Rectangle {
    id: root

    property bool active: false
    property string stage: ""
    property real progress: -1
    property string fileName: ""
    property string message: ""

    // Фаза декоративной волны; крутится только при active.
    property real pulse: 0
    property real shimmerPos: -0.4

    readonly property string displayMessage: {
        if (String(root.message).length > 0)
            return root.message
        if (root.stage === "voices")
            return "Определяем, кто говорит…"
        return "Распознаём речь и расставляем таймкоды…"
    }

    readonly property string stageLabel: {
        if (root.stage === "voices")
            return "Голоса"
        if (root.stage === "asr")
            return "Речь"
        return "Распознавание"
    }

    readonly property string shortName: {
        var path = String(root.fileName || "")
        if (!path.length)
            return ""
        var slash = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"))
        return slash >= 0 ? path.slice(slash + 1) : path
    }

    readonly property bool determinate: root.progress >= 0

    visible: root.active
    implicitHeight: root.active ? (body.implicitHeight + Theme.padCard) : 0
    radius: Theme.radiusMd
    color: Theme.surface
    border.width: 1
    border.color: Theme.border
    clip: true

    onActiveChanged: {
        if (!root.active) {
            root.pulse = 0
            root.shimmerPos = -0.4
            bars.requestPaint()
        }
    }

    Timer {
        id: pulseTimer
        interval: 48
        repeat: true
        running: root.active
        onTriggered: {
            root.pulse = (root.pulse + 0.14) % (Math.PI * 2)
            bars.requestPaint()
        }
    }

    SequentialAnimation {
        id: shimmerAnim
        running: root.active && !root.determinate
        loops: Animation.Infinite
        NumberAnimation {
            target: root
            property: "shimmerPos"
            from: -0.4
            to: 1.05
            duration: 1400
            easing.type: Easing.InOutSine
        }
        PauseAnimation { duration: Theme.slowMs }
    }

    RowLayout {
        id: body
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Theme.padCard - 2
        anchors.rightMargin: Theme.padCard - 2
        spacing: Theme.gapMd

        // Декоративные столбики: индикатор работы, не RMS микрофона.
        Canvas {
            id: bars
            Layout.preferredWidth: 56
            Layout.preferredHeight: 28
            Layout.alignment: Qt.AlignVCenter
            renderStrategy: Canvas.Immediate

            property int count: 7
            property real barW: 3
            property real gap: 3

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var count = Math.max(1, bars.count)
                var total = count * bars.barW + (count - 1) * bars.gap
                var left = (width - total) / 2
                var middle = height / 2
                var active = root.active
                ctx.fillStyle = Theme.ink
                for (var i = 0; i < count; i++) {
                    var wave = 0.35 + 0.65 * Math.abs(Math.sin(root.pulse + i * 0.55))
                    var bar = active ? Math.max(3, 3 + wave * (height - 6)) : 3
                    var x = left + i * (bars.barW + bars.gap)
                    ctx.globalAlpha = active ? (0.28 + 0.72 * ((i + 1) / count)) : 0.35
                    ctx.beginPath()
                    ctx.roundedRect(x, middle - bar / 2, bars.barW, bar, bars.barW / 2, bars.barW / 2)
                    ctx.fill()
                }
                ctx.globalAlpha = 1
            }

            Component.onCompleted: requestPaint()
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.gapXs

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gapSm

                Label {
                    text: root.stageLabel
                    color: Theme.text
                    font.pixelSize: Theme.fsLabel
                    font.weight: Font.DemiBold
                }

                Label {
                    visible: root.determinate
                    text: Math.round(Math.max(0, Math.min(1, root.progress)) * 100) + "%"
                    color: Theme.faint
                    font.pixelSize: Theme.fsSmall
                    font.family: Theme.monoFamily
                }

                Item { Layout.fillWidth: true }
            }

            Label {
                Layout.fillWidth: true
                text: root.displayMessage
                color: Theme.muted
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.Wrap
            }

            Label {
                Layout.fillWidth: true
                visible: root.shortName.length > 0
                text: root.shortName
                color: Theme.faint
                font.pixelSize: Theme.fsMicro
                elide: Text.ElideMiddle
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 2
                height: 4
                radius: 2
                color: Theme.fill
                clip: true

                Rectangle {
                    visible: root.determinate
                    width: parent.width * Math.max(0, Math.min(1, root.progress))
                    height: parent.height
                    radius: 2
                    color: Theme.ink
                    Behavior on width {
                        NumberAnimation { duration: Theme.fastMs }
                    }
                }

                Rectangle {
                    visible: !root.determinate
                    x: parent.width * root.shimmerPos
                    width: Math.max(24, parent.width * 0.32)
                    height: parent.height
                    radius: 2
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "#00ffffff" }
                        GradientStop { position: 0.45; color: Theme.fillHi }
                        GradientStop { position: 0.55; color: Theme.ink }
                        GradientStop { position: 1.0; color: "#00ffffff" }
                    }
                }
            }
        }
    }
}
