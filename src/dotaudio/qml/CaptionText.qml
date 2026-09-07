import QtQuick
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: root
    property string text: ""
    property var words: []
    property int maxLines: 2
    property int pixelSize: 15
    property int weight: Font.DemiBold
    property color ink: Theme.text
    property int align: Text.AlignLeft
    property string segmentKey: ""
    property bool fadeOnChange: true
    readonly property bool hashed: words && words.length > 0
    readonly property real lineBox: Math.ceil(pixelSize * 1.25 * maxLines)
    implicitHeight: hashed ? Math.min(wordFlow.implicitHeight, lineBox) : plain.implicitHeight
    clip: true
    opacity: 1

    onSegmentKeyChanged: {
        if (!root.fadeOnChange)
            return
        root.opacity = 0
        fadeIn.restart()
    }

    NumberAnimation on opacity {
        id: fadeIn
        from: 0
        to: 1
        duration: Theme.contentMs
        easing.type: Easing.OutCubic
    }

    Text {
        id: plain
        visible: !root.hashed
        width: parent.width
        text: root.text
        color: root.ink
        font.pixelSize: root.pixelSize
        font.weight: root.weight
        font.family: Theme.fontFamily
        wrapMode: Text.Wrap
        maximumLineCount: root.maxLines
        elide: Text.ElideRight
        lineHeight: 1.25
        lineHeightMode: Text.ProportionalHeight
        horizontalAlignment: root.align
    }

    Flow {
        id: wordFlow
        visible: root.hashed
        width: parent.width
        height: Math.min(implicitHeight, root.lineBox)
        spacing: 6
        clip: true
        Repeater {
            model: root.words
            delegate: Text {
                id: wordLabel
                required property var modelData
                required property int index
                text: modelData.text !== undefined ? modelData.text : ""
                color: root.ink
                font.pixelSize: root.pixelSize
                font.weight: root.weight
                font.family: Theme.fontFamily
                opacity: 0
                SequentialAnimation on opacity {
                    running: true
                    PauseAnimation { duration: wordLabel.index * 18 }
                    NumberAnimation { from: 0; to: 1; duration: Theme.contentMs; easing.type: Easing.OutCubic }
                }
            }
        }
    }
}
