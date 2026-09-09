import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Страница «Ассистент»: слева выбор записи и модель, справа разговор.
// Расшифровка здесь только читается - правки остаются на своих страницах.
Item {
    id: root

    property bool catalogOpen: false

    // Однострочное поле на токенах темы: системное поле приносит светлую
    // палитру на тёмный фон.
    component Field: TextField {
        color: Theme.text
        placeholderTextColor: Theme.faint
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fsLabel
        selectByMouse: true
        selectionColor: Theme.fillPress
        selectedTextColor: Theme.text
        leftPadding: 12
        rightPadding: 12
        implicitHeight: 34
        background: Rectangle {
            radius: Theme.radiusSm
            color: Theme.fill
            border.width: 1
            border.color: parent.activeFocus ? Theme.borderHi : Theme.hairline
            Behavior on border.color { ColorAnimation { duration: Theme.fastMs } }
        }
    }

    component Card: Rectangle {
        radius: Theme.radiusLg
        color: Theme.surface
        border.width: 1
        border.color: Theme.border
    }

    function stamp(seconds) {
        var total = Math.max(0, Math.round(Number(seconds) || 0))
        var minutes = Math.floor(total / 60)
        var rest = total % 60
        return (minutes < 10 ? "0" : "") + minutes + ":" + (rest < 10 ? "0" : "") + rest
    }

    RowLayout {
        anchors.fill: parent
        spacing: Theme.gapLg

        // ---- левая колонка: записи и модель ----
        ColumnLayout {
            Layout.preferredWidth: 300
            Layout.maximumWidth: 320
            Layout.fillHeight: true
            spacing: Theme.gapMd

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: Theme.gapSm

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        Label {
                            text: "Запись"
                            color: Theme.text
                            font.pixelSize: Theme.fsTitle
                            font.weight: Font.DemiBold
                        }
                        Item { Layout.fillWidth: true }
                        IconButton {
                            iconName: "undo"
                            onClicked: assistant.refreshRecords(search.text)
                            ToolTip.visible: hovered
                            ToolTip.text: "Обновить список"
                        }
                    }
                    Field {
                        id: search
                        Layout.fillWidth: true
                        placeholderText: "Поиск по названию и тексту"
                        onTextChanged: searchDelay.restart()
                        Timer {
                            id: searchDelay
                            interval: Theme.slowMs
                            onTriggered: assistant.refreshRecords(search.text)
                        }
                    }

                    // Общий чат стоит первым: он не привязан к записи и всегда доступен.
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 44
                        radius: Theme.radiusMd
                        color: assistant.recordId === "" ? Theme.fillHi
                             : generalHover.containsMouse ? Theme.fill : "transparent"
                        border.width: 1
                        border.color: assistant.recordId === "" ? Theme.borderHi : Theme.hairline
                        Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                        MouseArea {
                            id: generalHover
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: assistant.selectRecord("")
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: Theme.gapSm
                            Icon { name: "dictation"; width: 15; height: 15; ink: Theme.muted }
                            ColumnLayout {
                                spacing: 0
                                Label {
                                    text: "Свободный разговор"
                                    color: Theme.text
                                    font.pixelSize: Theme.fsLabel
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    text: "Без записи, обычный чат"
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsMicro
                                }
                            }
                        }
                    }

                    Label {
                        visible: assistant.records.length === 0
                        Layout.fillWidth: true
                        Layout.topMargin: Theme.gapSm
                        text: "Записей с расшифровкой пока нет. Сделайте запись в Live или в диктовке."
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }

                    ListView {
                        id: recordList
                        objectName: "recordList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 6
                        model: assistant.records
                        ScrollBar.vertical: ScrollBar { }
                        delegate: Rectangle {
                            required property var modelData
                            readonly property bool selected: assistant.recordId === modelData.id
                            width: recordList.width
                            implicitHeight: 56
                            radius: Theme.radiusMd
                            color: selected ? Theme.fillHi
                                 : recordHover.containsMouse ? Theme.fill : "transparent"
                            border.width: 1
                            border.color: selected ? Theme.borderHi : Theme.hairline
                            Behavior on color { ColorAnimation { duration: Theme.fastMs } }
                            MouseArea {
                                id: recordHover
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: assistant.selectRecord(modelData.id)
                            }
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 1
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    color: Theme.text
                                    font.pixelSize: Theme.fsLabel
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.preview
                                    color: Theme.muted
                                    font.pixelSize: Theme.fsMicro
                                    elide: Text.ElideRight
                                }
                                Label {
                                    text: modelData.segments + " фраз"
                                    color: Theme.faint
                                    font.pixelSize: Theme.fsMicro
                                    font.family: Theme.monoFamily
                                }
                            }
                        }
                    }
                }
            }

            // Активная модель и путь к каталогу.
            Card {
                Layout.fillWidth: true
                Layout.preferredHeight: modelBox.implicitHeight + 26
                ColumnLayout {
                    id: modelBox
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: Theme.gapXs
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        StatusDot { active: assistant.modelReady }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Label {
                                text: assistant.modelLabel || "Модель не выбрана"
                                color: Theme.text
                                font.pixelSize: Theme.fsLabel
                                font.weight: Font.DemiBold
                            }
                            Label {
                                text: assistant.modelReady
                                      ? assistant.activeRuntime
                                      : "Не скачана"
                                color: Theme.muted
                                font.pixelSize: Theme.fsMicro
                            }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: assistant.hardware.gpuLabel || ""
                        color: Theme.faint
                        font.pixelSize: Theme.fsMicro
                        elide: Text.ElideRight
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: Theme.gapXs
                        spacing: Theme.gapSm
                        PillButton {
                            compact: true
                            text: "Модели"
                            onClicked: {
                                assistant.refreshCatalog()
                                root.catalogOpen = true
                            }
                        }
                        PillButton {
                            compact: true
                            visible: !assistant.modelReady && !assistant.download.active
                            text: "Скачать"
                            primary: true
                            onClicked: assistant.downloadModel(assistant.modelId)
                        }
                        Item { Layout.fillWidth: true }
                    }
                    // Прогресс загрузки виден и когда каталог закрыт: файл идёт
                    // минутами, и об этом должно быть видно с рабочей страницы.
                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: assistant.download.active
                        spacing: 2
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: "Скачиваю " + (assistant.download.label || "")
                                color: Theme.muted
                                font.pixelSize: Theme.fsMicro
                                elide: Text.ElideRight
                            }
                            Label {
                                text: Math.round((assistant.download.ratio || 0) * 100) + "%"
                                color: Theme.text
                                font.pixelSize: Theme.fsMicro
                                font.family: Theme.monoFamily
                            }
                            IconButton {
                                iconName: "close"
                                onClicked: assistant.cancelDownload()
                                ToolTip.visible: hovered
                                ToolTip.text: "Остановить загрузку"
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 4
                            radius: 2
                            color: Theme.fill
                            Rectangle {
                                width: parent.width * Math.max(0, Math.min(1, assistant.download.ratio || 0))
                                height: parent.height
                                radius: 2
                                color: Theme.text
                                Behavior on width { NumberAnimation { duration: Theme.fastMs } }
                            }
                        }
                    }
                }
            }
        }

        // ---- правая часть: разговор ----
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.gapMd

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gapSm
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    visible: !titleEditor.visible
                    Label {
                        text: assistant.recordTitle
                        color: Theme.text
                        font.pixelSize: Theme.fsSection
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Label {
                        text: assistant.status
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                    }
                }
                TextField {
                    id: titleEditor
                    Layout.fillWidth: true
                    visible: false
                    text: assistant.recordTitle
                    color: Theme.text
                    font.pixelSize: Theme.fsBody
                    selectByMouse: true
                    selectionColor: Theme.fillPress
                    selectedTextColor: Theme.text
                    Keys.onReturnPressed: root.saveRecordTitle()
                    Keys.onEnterPressed: root.saveRecordTitle()
                    Keys.onEscapePressed: visible = false
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.fill
                        border.width: 1
                        border.color: Theme.borderHi
                    }
                }
                IconButton {
                    visible: assistant.recordId !== ""
                    iconName: titleEditor.visible ? "check" : "edit"
                    enabled: !assistant.busy
                    onClicked: {
                        if (titleEditor.visible)
                            root.saveRecordTitle()
                        else {
                            titleEditor.text = assistant.recordTitle
                            titleEditor.visible = true
                            titleEditor.forceActiveFocus()
                            titleEditor.selectAll()
                        }
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: titleEditor.visible ? "Сохранить название" : "Переименовать запись"
                }
                PillButton {
                    compact: true
                    visible: assistant.recordId !== ""
                    text: "Собрать карту заново"
                    enabled: !assistant.busy
                    onClicked: assistant.rebuildIndex()
                    ToolTip.visible: hovered
                    ToolTip.text: "Пересчитать описания частей записи"
                }
                PillButton {
                    compact: true
                    text: "Очистить"
                    enabled: !assistant.busy && assistant.messages.length > 0
                    onClicked: assistant.clearChat()
                    ToolTip.visible: hovered
                    ToolTip.text: "Стереть переписку. Расшифровка останется"
                }
            }

            Rectangle {
                visible: assistant.notice.length > 0
                Layout.fillWidth: true
                Layout.preferredHeight: noticeText.implicitHeight + 20
                radius: Theme.radiusMd
                color: Theme.fill
                border.width: 1
                border.color: Theme.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 6
                    spacing: Theme.gapSm
                    Icon { name: "warning"; width: 15; height: 15 }
                    Text {
                        id: noticeText
                        Layout.fillWidth: true
                        text: assistant.notice
                        color: Theme.text
                        font.pixelSize: Theme.fsLabel
                        font.family: Theme.fontFamily
                        wrapMode: Text.Wrap
                    }
                    IconButton { iconName: "close"; onClicked: assistant.clearNotice() }
                }
            }

            // Готовые действия работают по записи, поэтому в общем чате их нет.
            Flow {
                objectName: "assistantActions"
                Layout.fillWidth: true
                visible: assistant.recordId !== ""
                spacing: Theme.gapSm
                Repeater {
                    model: assistant.actions
                    delegate: PillButton {
                        required property var modelData
                        compact: true
                        text: modelData.label
                        enabled: !assistant.busy && assistant.modelReady
                        onClicked: assistant.runAction(modelData.id)
                    }
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                // Пустое состояние объясняет, что делать: без модели чат
                // молчал бы без причины.
                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(430, parent.width - 60)
                    visible: assistant.messages.length === 0
                    spacing: Theme.gapSm
                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: assistant.modelReady ? "Спросите о записи" : "Модель ещё не скачана"
                        color: Theme.text
                        font.pixelSize: Theme.fsLead
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        text: assistant.modelReady
                              ? "Модель работает на этом компьютере: ни расшифровка, ни вопросы никуда не отправляются."
                              : "Откройте «Модели», выберите подходящую этому устройству и скачайте её. После этого чат работает без интернета."
                        color: Theme.muted
                        font.pixelSize: Theme.fsBody
                    }
                    PillButton {
                        Layout.alignment: Qt.AlignHCenter
                        visible: !assistant.modelReady
                        primary: true
                        text: "Открыть модели"
                        onClicked: {
                            assistant.refreshCatalog()
                            root.catalogOpen = true
                        }
                    }
                }

                ListView {
                    id: chat
                    objectName: "assistantChat"
                    anchors.fill: parent
                    anchors.margins: 14
                    clip: true
                    spacing: Theme.gapMd
                    model: assistant.messages
                    visible: assistant.messages.length > 0
                    ScrollBar.vertical: ScrollBar { }
                    Connections {
                        target: assistant
                        function onMessagesChanged() { chat.positionViewAtEnd() }
                    }
                    delegate: Item {
                        id: bubbleRow
                        required property var modelData
                        required property int index
                        readonly property bool mine: modelData.role === "user"
                        readonly property var fileMeta: (modelData.meta && modelData.meta.attachment)
                                                       ? modelData.meta.attachment : null
                        width: chat.width
                        implicitHeight: bubble.implicitHeight

                        Rectangle {
                            id: bubble
                            width: Math.min(parent.width * 0.86, Math.max(120, bodyCol.implicitWidth + 28))
                            implicitHeight: bodyCol.implicitHeight + 22
                            anchors.right: bubbleRow.mine ? parent.right : undefined
                            anchors.left: bubbleRow.mine ? undefined : parent.left
                            radius: Theme.radiusMd
                            color: bubbleRow.mine ? Theme.fillHi : Theme.surface2
                            border.width: 1
                            border.color: bubbleRow.mine ? Theme.border : Theme.hairline

                            ColumnLayout {
                                id: bodyCol
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 11
                                spacing: Theme.gapXs

                                Rectangle {
                                    visible: bubbleRow.fileMeta !== null
                                    Layout.fillWidth: true
                                    implicitHeight: attachLabel.implicitHeight + 12
                                    radius: Theme.radiusSm
                                    color: Theme.fill
                                    border.width: 1
                                    border.color: Theme.hairline
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 6
                                        spacing: 6
                                        Icon { name: "attach"; width: 12; height: 12; ink: Theme.muted }
                                        Label {
                                            id: attachLabel
                                            Layout.fillWidth: true
                                            text: bubbleRow.fileMeta
                                                  ? (bubbleRow.fileMeta.name + " · "
                                                     + bubbleRow.fileMeta.chars + " симв.")
                                                  : ""
                                            color: Theme.muted
                                            font.pixelSize: Theme.fsMicro
                                            elide: Text.ElideMiddle
                                        }
                                    }
                                }

                                TextEdit {
                                    id: body
                                    Layout.fillWidth: true
                                    readOnly: true
                                    selectByMouse: true
                                    selectionColor: Theme.fillPress
                                    selectedTextColor: Theme.text
                                    wrapMode: TextEdit.Wrap
                                    text: {
                                        if (modelData.pending)
                                            return assistant.pendingReply.length
                                                   ? assistant.pendingReply
                                                   : (assistant.stage.length ? assistant.status : "…")
                                        if (modelData.content && modelData.content.length)
                                            return modelData.content
                                        return assistant.stage.length ? assistant.status : "…"
                                    }
                                    color: (modelData.pending
                                            ? assistant.pendingReply.length
                                            : (modelData.content && modelData.content.length))
                                           ? Theme.text : Theme.muted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fsBody
                                }
                            }
                        }
                        IconButton {
                            visible: !bubbleRow.mine && !assistant.busy
                                     && modelData.content && modelData.content.length > 0
                            anchors.left: bubble.right
                            anchors.leftMargin: 4
                            anchors.bottom: bubble.bottom
                            iconName: "copy"
                            onClicked: assistant.copyMessage(index)
                            ToolTip.visible: hovered
                            ToolTip.text: "Скопировать"
                        }
                    }
                }
            }

            // Ввод. Enter отправляет, Shift+Enter переносит строку: вопрос по
            // записи бывает длиннее одной строки.
            Card {
                Layout.fillWidth: true
                Layout.preferredHeight: inputColumn.implicitHeight + 20
                ColumnLayout {
                    id: inputColumn
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: Theme.gapXs

                    Rectangle {
                        visible: assistant.attachment.name !== undefined
                                 && String(assistant.attachment.name || "").length > 0
                        Layout.fillWidth: true
                        implicitHeight: pendingAttach.implicitHeight + 10
                        radius: Theme.radiusSm
                        color: Theme.fill
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            id: pendingAttach
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 4
                            spacing: 6
                            Icon { name: "attach"; width: 13; height: 13; ink: Theme.muted }
                            Label {
                                Layout.fillWidth: true
                                text: (assistant.attachment.name || "")
                                      + " · " + (assistant.attachment.chars || 0) + " симв."
                                      + (assistant.attachment.truncated ? " (обрезан)" : "")
                                color: Theme.muted
                                font.pixelSize: Theme.fsMicro
                                elide: Text.ElideMiddle
                            }
                            IconButton {
                                iconName: "close"
                                onClicked: assistant.clearAttachment()
                                ToolTip.visible: hovered
                                ToolTip.text: "Убрать файл"
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.gapSm
                        IconButton {
                            Layout.alignment: Qt.AlignBottom
                            iconName: "attach"
                            enabled: !assistant.busy
                            onClicked: assistant.attachTextFile()
                            ToolTip.visible: hovered
                            ToolTip.text: "Прикрепить .txt"
                        }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(100, Math.max(36, input.implicitHeight))
                            TextArea {
                                id: input
                                objectName: "assistantInput"
                                placeholderText: assistant.recordId === ""
                                                 ? "Спросите что угодно или прикрепите .txt"
                                                 : "Спросите о записи: о чём говорили, что решили, когда прозвучало…"
                                placeholderTextColor: Theme.faint
                                color: Theme.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fsBody
                                wrapMode: TextEdit.Wrap
                                selectByMouse: true
                                selectionColor: Theme.fillPress
                                selectedTextColor: Theme.text
                                background: null
                                enabled: !assistant.busy
                                Keys.onReturnPressed: function (event) {
                                    if (event.modifiers & Qt.ShiftModifier) {
                                        event.accepted = false
                                        return
                                    }
                                    event.accepted = true
                                    root.send()
                                }
                            }
                        }
                        PillButton {
                            Layout.alignment: Qt.AlignBottom
                            visible: !assistant.busy
                            primary: true
                            text: "Спросить"
                            enabled: assistant.modelReady && (
                                input.text.trim().length > 0
                                || (assistant.attachment.name
                                    && String(assistant.attachment.name).length > 0)
                            )
                            onClicked: root.send()
                        }
                        PillButton {
                            Layout.alignment: Qt.AlignBottom
                            visible: assistant.busy
                            text: "Стоп"
                            onClicked: assistant.stop()
                        }
                    }
                }
            }
        }
    }

    function saveRecordTitle() {
        var value = titleEditor.text.trim()
        titleEditor.visible = false
        if (!value.length || value === assistant.recordTitle)
            return
        assistant.renameRecord(value)
    }

    function send() {
        var text = input.text.trim()
        var hasFile = assistant.attachment.name
                      && String(assistant.attachment.name).length > 0
        if (!text.length && !hasFile)
            return
        assistant.ask(text)
        input.clear()
    }

    // Каталог моделей поверх страницы: создаётся при первом открытии,
    // чтобы не держать лист и его привязки в памяти зря.
    Loader {
        id: catalogLoader
        objectName: "assistantModels"
        anchors.fill: parent
        active: root.catalogOpen
        visible: root.catalogOpen
        source: "AssistantModels.qml"
        onLoaded: {
            if (item)
                item.closeRequested.connect(function () { root.catalogOpen = false })
        }
    }
}
