import QtQuick
import "Theme.js" as Theme

// Полоса уровня входа. Каждый столбик - измеренный RMS одного блока
// захвата (100 мс), самый правый самый свежий. Форма не выдумывается:
// усиление и корень только растягивают тихую речь до читаемой высоты.
Item {
    id: wave

    property int bars: 14
    property real barH: 12
    property real barW: 3
    property real gap: 3
    property bool live: Boolean(bridge.recording)
    property var samples: []

    implicitHeight: barH
    implicitWidth: bars * barW + Math.max(0, bars - 1) * gap
    clip: true

    Component.onCompleted: wave.reset()
    onBarsChanged: wave.reset()
    onLiveChanged: if (!wave.live) wave.reset()

    function reset() {
        var zeros = []
        for (var i = 0; i < wave.bars; i++)
            zeros.push(0)
        wave.samples = zeros
    }

    function push(value) {
        var next = wave.samples.slice(Math.max(0, wave.samples.length - wave.bars + 1))
        while (next.length < wave.bars - 1)
            next.unshift(0)
        next.push(value)
        wave.samples = next
    }

    Connections {
        target: bridge
        function onLevelChanged() {
            if (wave.live)
                wave.push(Theme.levelShape(bridge.level))
        }
    }

    Row {
        anchors.centerIn: parent
        spacing: wave.gap

        Repeater {
            model: wave.bars

            delegate: Rectangle {
                required property int index
                readonly property real sample: wave.samples.length > index ? wave.samples[index] : 0
                readonly property real freshness: (index + 1) / wave.bars

                width: wave.barW
                radius: wave.barW / 2
                height: Math.max(2, 2 + sample * (wave.barH - 2))
                color: wave.live ? Theme.ink : Theme.border
                opacity: wave.live ? 0.35 + 0.65 * freshness : 1
                anchors.verticalCenter: parent.verticalCenter

                Behavior on height {
                    NumberAnimation { duration: 110; easing.type: Easing.OutQuad }
                }
                Behavior on opacity {
                    NumberAnimation { duration: Theme.baseMs }
                }
            }
        }
    }
}
