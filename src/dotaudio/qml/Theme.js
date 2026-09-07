.pragma library

// Поверхности и чернила. Монохром DotCore: акцент даёт форма и белая
// прозрачность, а не цвет. Единственный цветной сигнал - запись.
var bg = "#0a0b0d"
var surface = "#14161a"
var surface2 = "#1b1d21"
var surface3 = "#21242a"
var text = "#f3f3f1"
var muted = "#a6a7ab"
var faint = "#74757a"
var border = "#22ffffff"
var borderHi = "#33ffffff"
var hairline = "#16ffffff"
var fill = "#14ffffff"
var fillHi = "#20ffffff"
var fillPress = "#2effffff"
var specular = "#26ffffff"
var scrim = "#99000000"
var ink = "#f3f3f1"
var islandFill = "#f214161a"
var overlayFill = "#f20a0b0d"
var overlayFillHigh = "#ff0a0b0d"
var recRing = "#66ffffff"
var rec = "#ff5f57"
var recSoft = "#33ff5f57"

var fontFamily = "Segoe UI"
var monoFamily = "Consolas"

// Размеры текста. Живой субтитр крупнее всего остального: в Live читают
// одну фразу, а не интерфейс вокруг неё.
var fsMicro = 10
var fsSmall = 11
var fsBody = 13
var fsTitle = 16
var fsHead = 26
var fsStage = 34

var radiusSm = 10
var radiusMd = 14
var radiusLg = 20
var radiusXl = 26

// Длительности. Короткие для отклика на курсор, средние для смены
// содержимого, длинная только для морфа острова. Это проектные значения
// интерфейса, а не измеренная задержка распознавания.
var instantMs = 90
var fastMs = 140
var baseMs = 210
var slowMs = 320
var morphMs = 380
var wordMs = 260
var reflowMs = 300
var promoteMs = 420
var contentMs = 170
var wordStaggerMs = 26
var wordStaggerCapMs = 190

// Кривые. easeOut - мягкое торможение без отката, для появления текста.
// easeSpring - лёгкий перелёт для морфа острова и нажатий.
var easeOut = [0.16, 1.0, 0.3, 1.0, 1, 1]
var easeInOut = [0.65, 0.0, 0.35, 1.0, 1, 1]
var easeSpring = [0.34, 1.32, 0.64, 1.0, 1, 1]
var easeExit = [0.4, 0.0, 1.0, 1.0, 1, 1]

// Прозрачность живого хвоста фразы: подтверждённые слова видны полностью,
// ещё уточняемые - приглушены. Состояние передаётся не только цветом:
// хвост дополнительно тоньше по начертанию.
var pendingAlpha = 0.52
var historyAlpha = 0.44

// Уровень входа. Усиление и корень нужны только чтобы тихая речь была
// видна на 12-20 px; само значение остаётся измеренным RMS из capture.
var levelGain = 28
var levelCurve = 0.7

function levelShape(level) {
    var raw = Math.max(0, Math.min(1, Number(level) * levelGain))
    return Math.pow(raw, levelCurve)
}
