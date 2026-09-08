import QtQuick
import "Theme.js" as Theme

// Полоса уровня входа. Каждый столбик - измеренный RMS одного блока
// захвата (100 мс), самый правый самый свежий. Форма не выдумывается:
// усиление и корень только растягивают тихую речь до читаемой высоты.
//
// Рисуется одним холстом. Прежняя версия держала столбик-прямоугольник на
// каждый блок и пересобирала массив значений десять раз в секунду: каждое
// обновление пересчитывало привязки всех делегатов и запускало десятки
// одновременных анимаций высоты. При включённой записи это шло постоянно и
// в острове, и в окне Live одновременно.
Item {
    id: wave

    property int bars: 14
    property real barH: 12
    property real barW: 3
    property real gap: 3
    property bool live: Boolean(bridge.recording)

    implicitHeight: barH
    implicitWidth: bars * barW + Math.max(0, bars - 1) * gap

    // Кольцевой буфер: новое значение вытесняет самое старое, массив не
    // пересоздаётся и не участвует в привязках.
    property var samples: new Array(64).fill(0)
    property int head: 0

    function reset() {
        for (var i = 0; i < wave.samples.length; i++)
            wave.samples[i] = 0
        wave.head = 0
        canvas.requestPaint()
    }

    function push(value) {
        wave.samples[wave.head % wave.samples.length] = value
        wave.head = wave.head + 1
        canvas.requestPaint()
    }

    onBarsChanged: reset()
    onLiveChanged: if (!wave.live) reset()
    Component.onCompleted: reset()

    Connections {
        target: bridge
        function onLevelChanged() {
            if (wave.live)
                wave.push(Theme.levelShape(bridge.level))
        }
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        renderStrategy: Canvas.Immediate

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var count = Math.max(1, wave.bars)
            var total = count * wave.barW + (count - 1) * wave.gap
            var left = (width - total) / 2
            var middle = height / 2
            var ring = wave.samples.length
            ctx.fillStyle = wave.live ? Theme.ink : Theme.border
            for (var i = 0; i < count; i++) {
                // Самый правый столбик - последний измеренный блок.
                var age = count - 1 - i
                var value = wave.samples[(wave.head - 1 - age + ring * 2) % ring] || 0
                var bar = Math.max(2, 2 + value * (wave.barH - 2))
                var x = left + i * (wave.barW + wave.gap)
                // Свежие блоки заметнее давних: видно направление времени.
                ctx.globalAlpha = wave.live ? 0.35 + 0.65 * ((i + 1) / count) : 1
                ctx.beginPath()
                ctx.roundedRect(x, middle - bar / 2, wave.barW, bar, wave.barW / 2, wave.barW / 2)
                ctx.fill()
            }
            ctx.globalAlpha = 1
        }
    }
}
