import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: page
    objectName: "speechSettingsPage"
    readonly property var theme: Theme.palette(uiState.darkMode)
    property var s: lm.strings
    readonly property var cfg: backend.speechSettings
    readonly property var runtime: backend.speechRuntime
    readonly property var engineOptions: [
        {label: s["speech.engine_auto"], value: "auto"},
        {label: s["speech.engine_sensevoice"], value: "sense_voice"},
        {label: s["speech.engine_zipformer"], value: "sherpa_onnx_streaming"},
        {label: s["speech.engine_whisper"], value: "faster_whisper"}
    ]
    readonly property var languageOptions: [
        {label: s["speech.chinese"], value: "zh"},
        {label: "English", value: "en"},
        {label: s["speech.language_auto"], value: "auto"},
        {label: s["speech.follow_ui"], value: "follow_ui"},
        {label: s["speech.cantonese"], value: "yue"},
        {label: "日本語", value: "ja"}, {label: "한국어", value: "ko"}
    ]
    function selected(options, value) {
        for (var i = 0; i < options.length; i++)
            if (options[i].value === value) return i
        return 0
    }
    Component.onCompleted: backend.refreshSpeechMicrophones()
    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: page.width - 64
            x: 32
            spacing: 18
            Item { Layout.preferredHeight: 8 }
            Label {
                text: s["speech.title"]
                color: theme.textPrimary
                font.pixelSize: 26
                font.bold: true
            }
            Label {
                text: s["speech.description"]
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: theme.textSecondary
            }
            Label {
                visible: !runtime.enabled
                text: s["speech.lite_help"]
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: theme.textPrimary
                font.bold: true
            }
            Label { text: s["speech.optional_title"]; color: theme.textPrimary; font.bold: true; font.pixelSize: 19 }
            Label { text: s["speech.optional_help"]; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.textSecondary }
            Label { text: s["speech.memory_help"]; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.textSecondary }
            Label { visible: !backend.speechDownloadSupported; text: s["speech.error_platform"]; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: "#e59564" }
            Repeater {
                model: backend.speechModels
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: modelColumn.implicitHeight + 28
                    color: theme.bgCard
                    radius: 10
                    ColumnLayout {
                        id: modelColumn
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                        Label { text: modelData.name + " · " + (modelData.installed ? s["speech.installed"] : s["speech.not_installed"]); color: theme.textPrimary; font.bold: true; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        Label { text: modelData.note; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: modelData.size; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            Button {
                                objectName: "speechDownloadButton_" + modelData.id
                                readonly property bool complete: runtime.enabled && modelData.installed && modelData.vad_installed && (!cfg.preview_enabled || modelData.id === "zipformer" || runtime.preview)
                                text: complete ? s["speech.use_model"] : s["speech.download_enable"]
                                enabled: !backend.speechModelInstalling && !backend.speechBusy && (complete || backend.speechDownloadSupported)
                                onClicked: {
                                    if (complete) backend.useSpeechModel(modelData.id)
                                    else backend.downloadSpeechModel(modelData.id, cfg.preview_enabled)
                                }
                            }
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Button { text: s["speech.install_pack"]; enabled: !backend.speechModelInstalling && !backend.speechBusy; onClicked: backend.installSpeechModelPack() }
                Button { text: s["speech.open_models"]; onClicked: backend.openSpeechModelDirectory() }
                Button { text: s["speech.refresh"]; onClicked: backend.refreshSpeechMicrophones() }
            }
            ProgressBar { visible: backend.speechModelInstalling; Layout.fillWidth: true; from: 0; to: 100; value: backend.speechModelInstallProgress }
            RowLayout {
                Layout.fillWidth: true
                Label { text: backend.speechInstallMessage; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                Button { visible: backend.speechModelInstalling; text: s["speech.cancel_download"]; onClicked: backend.cancelSpeechDownload() }
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: runtimeColumn.implicitHeight + 32
                color: theme.bgCard
                radius: 12
                ColumnLayout {
                    id: runtimeColumn
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
                    Label { text: s["speech.actual_model"] + "  " + (runtime.model || s["speech.no_model"]); color: theme.textPrimary; font.bold: true; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    Label { visible: backend.speechActiveModel.length > 0; text: s["speech.active_model"] + "  " + backend.speechActiveModel; color: theme.accent }
                    Label {
                        text: runtime.ready ? s["speech.model_ready"] : s["speech.model_missing"]
                        color: runtime.ready ? theme.accent : "#e59564"
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                    Label { text: s["speech.local_only"]; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    Label { text: s["speech.auto_help"]; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    Label { visible: runtime.ready && cfg.preview_enabled && !runtime.preview; text: s["speech.preview_missing"]; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 18
                rowSpacing: 12
                Label { text: s["speech.engine"]; color: theme.textPrimary }
                ComboBox {
                    objectName: "speechEngineCombo"
                    Layout.fillWidth: true
                    model: page.engineOptions
                    textRole: "label"
                    currentIndex: page.selected(page.engineOptions, cfg.engine)
                    onActivated: backend.setSpeechSetting("engine", page.engineOptions[index].value)
                }
                Label { text: s["speech.language"]; color: theme.textPrimary }
                ComboBox {
                    Layout.fillWidth: true
                    model: page.languageOptions
                    textRole: "label"
                    currentIndex: page.selected(page.languageOptions, cfg.language)
                    onActivated: backend.setSpeechSetting("language", page.languageOptions[index].value)
                }
                Label { text: s["speech.microphone"]; color: theme.textPrimary }
                RowLayout {
                    Layout.fillWidth: true
                    ComboBox {
                        Layout.fillWidth: true
                        model: backend.speechMicrophones
                        textRole: "name"
                        currentIndex: {
                            var options = backend.speechMicrophones
                            for (var i = 0; i < options.length; i++)
                                if (options[i].key === cfg.microphone) return i
                            return -1
                        }
                        onActivated: backend.setSpeechSetting("microphone", backend.speechMicrophones[index].key)
                    }
                    Button { text: s["speech.refresh"]; onClicked: backend.refreshSpeechMicrophones() }
                }
                Label { text: s["speech.pause_duration"]; color: theme.textPrimary }
                SpinBox {
                    from: 4; to: 30; stepSize: 1
                    value: Math.round(cfg.silence_stop_seconds * 10)
                    textFromValue: function(value, locale) { return (value / 10).toFixed(1) + " s" }
                    onValueModified: backend.setSpeechSetting("silence_stop_seconds", value / 10)
                }
                Label { text: s["speech.audio_level"]; color: theme.textPrimary }
                ProgressBar {
                    Layout.fillWidth: true
                    value: backend.speechAudioLevel
                    from: 0; to: 1
                }
                Label { text: s["speech.preview"]; color: theme.textPrimary }
                Switch { checked: cfg.preview_enabled; onToggled: backend.setSpeechSetting("preview_enabled", checked) }
                Label { text: s["speech.auto_input"]; color: theme.textPrimary }
                Switch { checked: cfg.auto_paste; onToggled: backend.setSpeechSetting("auto_paste", checked) }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: cfg.engine === "faster_whisper"
                Label { text: s["speech.whisper_model"]; color: theme.textPrimary }
                ComboBox {
                    model: ["small", "medium", "large-v3-turbo"]
                    currentIndex: model.indexOf(cfg.model)
                    onActivated: backend.setSpeechSetting("model", currentText)
                }
                Button { text: s["speech.choose_model"]; onClicked: backend.chooseSpeechModelFolder() }
            }
            Label {
                visible: cfg.engine === "faster_whisper" && cfg.model_path.length > 0
                text: cfg.model_path
                Layout.fillWidth: true
                wrapMode: Text.WrapAnywhere
                color: theme.textSecondary
            }
            Label { text: s["speech.custom_words"]; color: theme.textPrimary; font.bold: true }
            Label { text: s["speech.words_help"]; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            TextArea {
                id: words
                Layout.fillWidth: true
                Layout.preferredHeight: 90
                text: cfg.custom_words
                wrapMode: TextEdit.Wrap
                selectByMouse: true
                placeholderText: s["speech.words_placeholder"]
            }
            Label { text: s["speech.corrections"]; color: theme.textPrimary; font.bold: true }
            Label { text: s["speech.corrections_help"]; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            TextArea {
                id: corrections
                Layout.fillWidth: true
                Layout.preferredHeight: 90
                text: cfg.corrections
                wrapMode: TextEdit.Wrap
                selectByMouse: true
                placeholderText: s["speech.corrections_placeholder"]
            }
            RowLayout {
                Switch {
                    text: s["speech.enable_corrections"]
                    checked: cfg.corrections_enabled
                    onToggled: backend.setSpeechSetting("corrections_enabled", checked)
                }
                Button {
                    text: s["speech.save_words"]
                    onClicked: {
                        backend.setSpeechVocabulary(words.text, corrections.text)
                    }
                }
            }
            Label { text: s["speech.test_title"]; color: theme.textPrimary; font.bold: true }
            Label { text: s["speech.test_help"]; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            TextArea {
                id: speechTestInput
                objectName: "speechTestInput"
                Layout.fillWidth: true
                Layout.preferredHeight: 100
                wrapMode: TextEdit.Wrap
                selectByMouse: true
                placeholderText: s["speech.test_placeholder"]
            }
            RowLayout {
                Button {
                    text: s["speech.test_record"]
                    enabled: backend.speechBusy || (runtime.ready && !backend.speechModelInstalling)
                    onClicked: { speechTestInput.forceActiveFocus(); backend.requestSpeechTest() }
                }
                Label { text: s["speech.settings_next_session"]; color: theme.textSecondary; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            }
            Label { visible: backend.speechPendingText.length > 0; text: s["speech.pending_title"]; color: theme.textPrimary; font.bold: true }
            TextArea {
                visible: backend.speechPendingText.length > 0
                Layout.fillWidth: true
                Layout.preferredHeight: 100
                text: backend.speechPendingText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
            }
            Button { visible: backend.speechPendingText.length > 0; text: s["speech.copy_pending"]; onClicked: backend.copySpeechPendingText() }
            Item { Layout.preferredHeight: 24 }
        }
    }
}
