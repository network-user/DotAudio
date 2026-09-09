import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

// Страница «Ассистент»: слева отдельно записи и чаты, справа разговор.
// Расшифровка здесь только читается - правки остаются на своих страницах.
Item {
    id: root

    property bool catalogOpen: false
    property bool confirmDeleteOpen: false

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

    component SegmentPill: Rectangle {
        id: pill
        property string key
        property string label
        property bool active: assistant.listMode === key
        implicitHeight: 28
        implicitWidth: pillLabel.implicitWidth + 20
        radius: Theme.radiusSm
        color: active ? Theme.fillHi : (pillMouse.containsMouse ? Theme.fill : "transparent")
        border.width: 1
        border.color: active ? Theme.borderHi : Theme.hairline
        Behavior on color { ColorAnimation { duration: Theme.fastMs } }
        MouseArea {
            id: pillMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: assistant.setListMode(pill.key)
        }
        Label {
            id: pillLabel
            anchors.centerIn: parent
            text: pill.label
            color: Theme.text
            font.pixelSize: Theme.fsSmall
            font.weight: Font.DemiBold
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: Theme.gapLg

        // ---- левая колонка: записи / чаты и модель ----
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
                        SegmentPill { key: "records"; label: "Записи" }
                        SegmentPill { key: "chats"; label: "Чаты" }
                        Item { Layout.fillWidth: true }
                        IconButton {
                            visible: assistant.listMode === "chats"
                            iconName: "plus"
                            onClicked: assistant.createChat()
                            ToolTip.visible: hovered
                            ToolTip.text: "Новый чат"
                        }
                        IconButton {
                            iconName: "undo"
                            onClicked: assistant.refreshRecords(search.text)
                            ToolTip.visible: hovered
                            ToolTip.text: "Обновить списки"
                        }
                    }

                    Field {
                        id: search
                        Layout.fillWidth: true
                        placeholderText: assistant.listMode === "chats"
                                         ? "Поиск по чатам и записям"
                                         : "Поиск по названию и тексту"
                        onTextChanged: searchDelay.restart()
                        Timer {
                            id: searchDelay
                            interval: Theme.slowMs
                            onTriggered: assistant.refreshRecords(search.text)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: assistant.listMode === "records" && assistant.untitledCount > 0
                        spacing: Theme.gapSm
                        Label {
                            Layout.fillWidth: true
                            text: "Без имени: " + assistant.untitledCount
                            color: Theme.muted
                            font.pixelSize: Theme.fsMicro
                        }
                        PillButton {
                            compact: true
                            text: assistant.naming ? "Называю…" : "Назвать"
                            enabled: !assistant.busy && assistant.modelReady
                            onClicked: assistant.nameUntitledRecords()
                            ToolTip.visible: hovered
                            ToolTip.text: "Локальная модель придумает заголовки для типовых «Микрофон» и т.п."
                        }
                    }

                    Label {
                        visible: assistant.listMode === "records" && assistant.records.length === 0
                        Layout.fillWidth: true
                        text: "Записей с расшифровкой пока нет."
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }

                    Label {
                        visible: assistant.listMode === "chats" && assistant.chats.length <= 1
                                 && !(assistant.chats.length === 1 && assistant.chats[0].chatCount > 0)
                        Layout.fillWidth: true
                        text: "Пока только свободный разговор. Выберите запись слева во вкладке «Записи»."
                        color: Theme.muted
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                    }

                    ListView {
                        id: sideList
                        objectName: "recordList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: Theme.gapXs
                        model: assistant.listMode === "chats" ? assistant.chats : assistant.records
                        ScrollBar.vertical: ScrollBar { }
                        delegate: Item {
                            id: rowItem
                            required property var modelData
                            width: sideList.width
                            height: card.implicitHeight

                            Rectangle {
                                id: card
                                width: parent.width
                                implicitHeight: cardCol.implicitHeight + 18
                                radius: Theme.radiusMd
                                color: assistant.recordId === String(modelData.id || "")
                                       ? Theme.fillHi
                                       : (rowHover.containsMouse ? Theme.fill : "transparent")
                                border.width: 1
                                border.color: assistant.recordId === String(modelData.id || "")
                                              ? Theme.borderHi : Theme.hairline
                                Behavior on color { ColorAnimation { duration: Theme.fastMs } }

                                MouseArea {
                                    id: rowHover
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: assistant.selectRecord(String(modelData.id || ""))
                                }

                                Column {
                                    id: cardCol
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 10
                                    anchors.rightMargin: (
                                        assistant.listMode === "chats"
                                        && Number(modelData.chatCount || 0) > 0
                                    ) ? 36 : 10
                                    spacing: 3

                                    Row {
                                        width: parent.width
                                        spacing: 6
                                        Label {
                                            width: parent.width - (needsMark.visible ? needsMark.width + 6 : 0)
                                            text: modelData.displayTitle || modelData.title || "Запись"
                                            color: Theme.text
                                            font.pixelSize: Theme.fsLabel
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                            maximumLineCount: 2
                                            wrapMode: Text.Wrap
                                        }
                                        Rectangle {
                                            id: needsMark
                                            visible: !!modelData.needsTitle
                                            width: markLabel.implicitWidth + 8
                                            height: 16
                                            radius: 8
                                            color: Theme.fill
                                            border.width: 1
                                            border.color: Theme.hairline
                                            anchors.verticalCenter: parent.verticalCenter
                                            Label {
                                                id: markLabel
                                                anchors.centerIn: parent
                                                text: "имя"
                                                color: Theme.faint
                                                font.pixelSize: Theme.fsMicro
                                            }
                                        }
                                    }
                                    Label {
                                        width: parent.width
                                        text: modelData.subtitle || ""
                                        color: Theme.muted
                                        font.pixelSize: Theme.fsMicro
                                        elide: Text.ElideRight
                                    }
                                }

                                    IconButton {
                                    visible: assistant.listMode === "chats"
                                             && Number(modelData.chatCount || 0) > 0
                                    anchors.right: parent.right
                                    anchors.rightMargin: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    iconName: "trash"
                                    onClicked: assistant.deleteChatId(String(modelData.id || ""))
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Удалить этот чат"
                                }
                            }
                        }
                    }
                }
            }

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
                    text: assistant.record.title || assistant.recordTitle
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
                            titleEditor.text = assistant.record.title || assistant.recordTitle
                            titleEditor.visible = true
                            titleEditor.forceActiveFocus()
                            titleEditor.selectAll()
                        }
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: titleEditor.visible ? "Сохранить название" : "Переименовать запись"
                }
                IconButton {
                    visible: assistant.recordDeletable
                    iconName: "pin"
                    enabled: !assistant.busy
                    opacity: assistant.recordPinned ? 1 : 0.7
                    onClicked: assistant.togglePinRecord()
                    ToolTip.visible: hovered
                    ToolTip.text: assistant.recordPinned ? "Открепить" : "Закрепить сверху"
                }
                PillButton {
                    compact: true
                    text: "Новый чат"
                    enabled: !assistant.busy
                    onClicked: assistant.createChat()
                    ToolTip.visible: hovered
                    ToolTip.text: "Отдельный разговор без расшифровки"
                }
                PillButton {
                    compact: true
                    visible: assistant.recordId !== ""
                    text: assistant.naming ? "…" : "Назвать"
                    enabled: !assistant.busy && assistant.modelReady
                    onClicked: assistant.nameRecord()
                    ToolTip.visible: hovered
                    ToolTip.text: "Придумать заголовок по расшифровке"
                }
                PillButton {
                    compact: true
                    visible: assistant.recordId !== "" && Number(assistant.record.segments || 0) > 0
                    text: "Карта"
                    enabled: !assistant.busy
                    onClicked: assistant.rebuildIndex()
                    ToolTip.visible: hovered
                    ToolTip.text: "Пересчитать описания частей записи"
                }
                PillButton {
                    compact: true
                    text: "Удалить чат"
                    enabled: !assistant.busy && assistant.messages.length > 0
                    onClicked: assistant.deleteChat()
                    ToolTip.visible: hovered
                    ToolTip.text: "Стереть переписку. Расшифровка останется"
                }
                PillButton {
                    compact: true
                    visible: assistant.recordDeletable
                    text: "Удалить запись"
                    enabled: !assistant.busy
                    onClicked: root.confirmDeleteOpen = true
                    ToolTip.visible: hovered
                    ToolTip.text: "Удалить расшифровку и чат навсегда"
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

                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(430, parent.width - 60)
                    visible: assistant.messages.length === 0
                    spacing: Theme.gapSm
                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: assistant.modelReady
                              ? (assistant.recordId === "" ? "Свободный разговор" : "Спросите о записи")
                              : "Модель ещё не скачана"
                        color: Theme.text
                        font.pixelSize: Theme.fsLead
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        text: assistant.modelReady
                              ? (assistant.recordId === ""
                                 ? "Можно просто поговорить или прикрепить .txt. Чтобы разобрать расшифровку, откройте вкладку «Записи»."
                                 : "Модель работает на этом компьютере: ни расшифровка, ни вопросы никуда не отправляются.")
                              : "Откройте «Модели», выберите подходящую этому устройству и скачайте её."
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
                        function onStreamChanged() {
                            if (assistant.busy)
                                chat.positionViewAtEnd()
                        }
                    }
                    delegate: Item {
                        id: bubbleRow
                        required property var modelData
                        required property int index
                        readonly property bool mine: modelData.role === "user"
                        readonly property var fileMeta: (modelData.meta && modelData.meta.attachment)
                                                       ? modelData.meta.attachment : null
                        // Ширина пузыря фиксирована долей списка: иначе
                        // TextEdit и ColumnLayout крутят друг друга по размеру
                        // и строки наезжают.
                        readonly property real bubbleWidth: Math.min(chat.width * 0.82, 560)
                        width: chat.width
                        height: Math.max(bubble.height, copyBtn.visible ? copyBtn.height : 0)

                        Rectangle {
                            id: bubble
                            width: bubbleRow.bubbleWidth
                            height: col.height + 22
                            anchors.right: bubbleRow.mine ? parent.right : undefined
                            anchors.left: bubbleRow.mine ? undefined : parent.left
                            radius: Theme.radiusMd
                            color: bubbleRow.mine ? Theme.fillHi : Theme.surface2
                            border.width: 1
                            border.color: bubbleRow.mine ? Theme.border : Theme.hairline

                            Column {
                                id: col
                                x: 11
                                y: 11
                                width: parent.width - 22
                                spacing: Theme.gapXs

                                Rectangle {
                                    visible: bubbleRow.fileMeta !== null
                                    width: parent.width
                                    height: attachRow.height + 10
                                    radius: Theme.radiusSm
                                    color: Theme.fill
                                    border.width: 1
                                    border.color: Theme.hairline
                                    Row {
                                        id: attachRow
                                        x: 6
                                        y: 5
                                        width: parent.width - 12
                                        spacing: 6
                                        Icon { name: "attach"; width: 12; height: 12; ink: Theme.muted }
                                        Label {
                                            width: parent.width - 18
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
                                    width: parent.width
                                    readOnly: true
                                    selectByMouse: true
                                    selectionColor: Theme.fillPress
                                    selectedTextColor: Theme.text
                                    wrapMode: TextEdit.Wrap
                                    textFormat: TextEdit.PlainText
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
                            id: copyBtn
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
        if (!value.length)
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

    // Подтверждение удаления записи: нельзя вернуть расшифровку.
    Rectangle {
        anchors.fill: parent
        visible: root.confirmDeleteOpen
        z: 20
        color: Theme.scrim
        MouseArea { anchors.fill: parent; onClicked: root.confirmDeleteOpen = false }

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(420, parent.width - 40)
            implicitHeight: confirmCol.implicitHeight + 36
            radius: Theme.radiusXl
            color: Theme.surface
            border.width: 1
            border.color: Theme.borderHi
            MouseArea { anchors.fill: parent }

            ColumnLayout {
                id: confirmCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 18
                spacing: Theme.gapMd

                Label {
                    Layout.fillWidth: true
                    text: "Удалить запись?"
                    color: Theme.text
                    font.pixelSize: Theme.fsSection
                    font.weight: Font.DemiBold
                }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: Number(assistant.record.segments || 0) > 0
                          ? ("«" + assistant.recordTitle + "» будет удалена вместе с расшифровкой, чатом и выжимками. Это нельзя отменить.")
                          : ("Чат «" + assistant.recordTitle + "» будет удалён навсегда. Это нельзя отменить.")
                    color: Theme.muted
                    font.pixelSize: Theme.fsBody
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gapSm
                    Item { Layout.fillWidth: true }
                    PillButton {
                        text: "Отмена"
                        onClicked: root.confirmDeleteOpen = false
                    }
                    PillButton {
                        primary: true
                        text: "Удалить навсегда"
                        enabled: !assistant.busy && assistant.recordDeletable
                        onClicked: {
                            root.confirmDeleteOpen = false
                            assistant.deleteRecord()
                        }
                    }
                }
            }
        }
    }

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
