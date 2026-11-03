# Changelog

## v3.7.34 — One-app on-demand speech (Windows x64)

- Publish the Windows application as the stable download; keep the earlier
  release available for rollback. Recognition and compatibility still depend
  on the user's hardware, microphone and target application.

- Keep one lightweight application: the Voice page downloads the pinned speech
  runtime and selected model only after an explicit Download and enable click.
- Show model recommendations and the actual missing download size; optionally
  include Zipformer preview with SenseVoice/Whisper, without downloading all models.
- HTTPS, bounded streaming/retry/cancellation, exact checksums, safe staged
  extraction/rollback and temporary-download cleanup. Mouse shortcuts are preserved.
- Move recording and ASR to a hidden, independent process. Pause-to-submit,
  target/caret preview, clipboard restoration and input-focus guards stay in the UI.
- Exit the speech process after 30 seconds idle to release native model memory;
  downloaded files remain installed and the next recording restarts it as needed.
- Fix Windows blocked control-pipe/native initialization and frozen GBK/UTF-8
  protocol mismatches; keep read-only accessibility anchors in the main package.
- Automatic component installation is currently Windows x64 only. Speech/model
  component releases are separate from the main application's stable update channel.

## v3.7.33 (local test build) — Optional voice deployment

- Windows Lite excludes speech dependencies and models; Voice ships runtime only by default.
- Independent, checksum-pinned SenseVoice, Zipformer and Whisper small model packs include Silero VAD; external models survive replacing the program folder.
- Localized model recommendations, installed state, uncompressed size and optional preview requirements appear in Voice settings.
- Explicit offline model installation validates all assets before committing; rollback preserves prior assets on failure. No user data is included.
- Missing optional models are normal: no microphone opens and no silent download/model substitution occurs. Auto never routes other languages to the Mandarin-only model.

## v3.7.32 (local test build)

### Added

- Continuous microphone capture, Silero VAD phrase segmentation, ordered
  background phrase recognition, and automatic phrase insertion on pauses.
  Stop flushes the remaining phrase instead of being required for every input.
- SenseVoice Small int8 candidate for Chinese final recognition, with the
  existing Zipformer model retained for fast preview and as a selectable mode.
- A localized voice settings page: actual/selected model, speech language,
  microphone, pause timing, preview, vocabulary, opt-in literal correction
  rules, test input and retained text when automatic delivery is unsafe.
- Non-activating, click-through preview near the input caret/control, with
  physical-to-logical display mapping and screen-edge placement fallback.

### Fixed

- Remove implicit medium-to-small and volume-threshold rewriting. Explicit
  models do not silently change or trigger a first-run download.
- Separate audio capture from final ASR so recognition does not stop listening.
  Bound queues and report overflows rather than silently lose input audio.
- Validate focus before every insertion, prevent replay into another input,
  serialize clipboard delivery, and restore clipboard content when unchanged.
- Do not write recordings, recognized text or custom terms into speech logs.

### Changed

- Keep hand-gesture debugging and device diagnostics, but collapse them by
  default under Advanced / Troubleshooting; add a copy-diagnostics action.
- This is a local evaluation build, not a public release. Accuracy and
  compatibility require user testing; no guaranteed recognition improvement.

## v3.7.31 (local test build)

### Changed

- Merge the Logitech management selector into the mouse-page header. The title
  shows the actual managed mouse, including the automatic selection mode;
  remove the separate management card and move manual layout overrides into
  the collapsed Advanced popup.
- Keep rescan beside the device selector and wrap status badges on narrow
  windows. Preserve per-device layout overrides and all shortcut mappings.
- Localize receiver, Bluetooth and USB connection labels in both the device
  menu and connection badge; changes follow the selected interface language.

## v3.7.30 (local test build)

### Added

- Windows read-only Logitech inventory: enumerate all receiver slots and direct
  USB/Bluetooth candidates, distinguish mice from paired keyboards, and show
  offline or feature-limited devices separately from the receiver itself.
- A localized management-target selector and rescan button. Remember a verified
  mouse identity without modifying existing shortcut/profile mappings. A missing
  explicit target never silently falls back to another mouse.

### Fixed

- Match HID++ replies, errors, battery/button notifications and wake events to
  the selected receiver slot and request. Reset feature state between slots.
- Use the receiver's short output channel for pairing-register reads and read
  both report collections with one owner per channel. Preserve the radio serial
  across awake/asleep inventories; it is not the firmware unit ID.
- Revalidate identity before feature configuration; stop using a slot whose
  identity changes. Inventory scans do not modify pairing or onboard memory.

### Scope

- Manage one mouse at a time. Ordinary Windows mouse-hook shortcuts remain
  global, as before. Identification does not imply that every device supports
  HID++ gestures, DPI changes or battery reporting.
- Bluetooth, Bolt, multiple mice and slot reassignment need hardware acceptance
  beyond the simulated regression tests. This build is not a public release yet.

## v3.7.29

This release adds a local sherpa-onnx streaming speech engine.

### Added

- Add an automatic local streaming engine using the bundled
  `sherpa-onnx-streaming-zipformer-zh-14M` model when available.
- Show partial recognition text in the always-on-top status bubble while
  recording, then paste the final recognized text after stopping.
- Keep faster-whisper as the fallback engine when the local streaming model is
  not available.

## v3.7.28

This release makes unexpected voice typing errors display as localized user
messages while keeping technical details in the speech log.

### Fixed

- Show a localized voice typing failure message instead of displaying raw
  lower-level exception text in the always-on-top status bubble.

## v3.7.27

This release fixes voice recognition with PyAV builds that reject
`metadata_errors`.

### Fixed

- Read Mouser-recorded wav audio directly before passing it to faster-whisper,
  avoiding the PyAV file decoding path that could fail with
  `open() got an unexpected keyword argument 'metadata_errors'`.

## v3.7.26

This release improves voice typing diagnosis and low-volume recording behavior.

### Fixed

- Write voice typing status, recognition, paste, and error details to
  `%APPDATA%\\Mouser\\speech_to_text.log` so shortcut failures can be
  diagnosed from a real log instead of an empty process console.
- When the user manually stops dictation, send the recorded audio to the local
  recognizer even if the live volume threshold was not crossed, which avoids
  false "no speech detected" failures on quiet microphones.

## v3.7.25

This release makes voice typing usable without a large first-run model download.

### Fixed

- Prefer a bundled local small speech model when available, including for users
  whose v3.7.23 config still contains the old medium default.
- Separate recording, stopping, and recognizing states so repeated triggers
  during recognition show a wait message instead of repeatedly saying stop.
- Stop early with a clear no-speech message instead of sending silent audio to
  the recognizer.

## v3.7.24

This release improves the new local voice typing action after real shortcut testing.

### Fixed

- Prevent duplicate shortcut/button events from immediately stopping dictation
  right after it starts.
- Show voice typing status in a small always-on-top overlay so recording,
  recognition, and paste feedback are visible while another app is focused.

## v3.7.23

This release adds a local offline voice typing action.

### Added

- Added a new **Voice Typing** action that can be assigned to a mouse button or
  Actions Ring sector.
- Voice typing records from the local microphone, transcribes with a local
  faster-whisper model, copies the recognized text, and pastes it into the
  current input field by default.
- Added Simplified Chinese and Traditional Chinese labels/status messages for
  the action, Actions Ring display, and common speech errors.
- Added default speech-to-text configuration and PyInstaller collection rules
  for optional local speech runtime dependencies.

## v3.7.20

This release keeps the Windows DLL search path handles alive for the lifetime
of the app, fixing a remaining packaged startup failure while importing
`PySide6.QtWidgets` on some PCs.

### Fixed

- Persist the handles returned by `os.add_dll_directory()` so Windows continues
  to search the bundled PySide6 and shiboken6 folders during Qt imports.

## v3.7.19

This release fixes a packaged Windows startup failure that could show
`DLL load failed while importing QtWidgets`.

### Fixed

- Added the bundled PySide6 and shiboken6 folders to the Windows DLL search path
  before importing Qt, so extracted portable packages can find QtWidgets and its
  runtime dependencies more reliably on other PCs.
- Declared `PySide6.QtWidgets` explicitly in the Windows PyInstaller build.

## v3.7.18

This release fixes another Windows multi-monitor region screenshot overlay issue.

### Fixed

- Split the region-selection shade into one overlay per display so opening the
  screenshot selector no longer leaves a stale highlighted patch on one monitor.
- Kept cross-monitor dragging on one shared global selection while painting each
  monitor preview in that monitor's own coordinate space.

## v3.7.17

This release fixes the Windows region screenshot preview on multi-monitor setups.

### Fixed

- Kept the visible region-selection preview aligned with the selected capture
  region on dual-monitor and multi-monitor layouts.

## v3.7.16

This release makes personal settings migration clearer for new users.

### Changed

- Renamed the settings backup actions to **Export personal settings** and
  **Import personal settings** so they are not confused with the app download.
- Added in-app guidance for old-computer export and new-computer import.
- Added a localized warning when someone tries to import the GitHub app zip
  instead of a Mouser personal settings backup zip.
- Updated README migration steps for the separate `Mouser-settings-*.zip`
  personal settings package.

## v3.7.15

This release fixes a packaged Windows startup failure in v3.7.14.

### Fixed

- Fixed a QML expression parsing error in the Mouse & Profiles page connection
  status text. The v3.7.14 Windows package could log FATAL: Failed to load QML
  and exit before showing the window; v3.7.15 starts normally again.
- Reduced background HID battery reads while the Mouser window is hidden or the
  system is idle, which avoids unnecessary wireless wake-ups for MX/G502-style
  Logitech receivers.

### Notes

- The v3.7.14 settings backup/import/export feature is unchanged.
- Public source and release packages still do not include personal config, logs,
  screenshots, or G502 onboard-memory backups.

## v3.7.14

This release adds user settings backup and migration support for the G502 fork.

### Added

- Settings page controls to export, import, and open the Mouser settings folder.
- Export/import for shortcut mappings, profiles, actions ring slots, and personal settings.
- Automatic rolling backups before config saves, stored locally under the user settings folder.
- Corrupted config recovery: Mouser preserves the broken file, then restores from the latest valid backup when possible.
- English, Simplified Chinese, and Traditional Chinese labels for the new backup UI and status prompts.

### Notes

- Exported settings bundles contain `config.json` and `metadata.json` only.
- Public source and release packages do not include personal config, logs, screenshots, or G502 onboard-memory backups.

## v3.7.12-g502-screenshot-fix

This release fixes a Windows screenshot timing issue in the G502 fork.

### Fixed

- Screenshot actions now wait briefly before capturing the desktop so the
  Actions Ring overlay has time to disappear. This prevents the ring / task-view
  chooser UI from being included in screenshots started from the ring.
- Repeated screenshot requests during that short wait are ignored with the
  existing "finish current screenshot selection first" status message.

## v3.7.11-g502-f13f16-cn-i18n-sync

This is an unofficial fork build based on [TomBadash/Mouser](https://github.com/TomBadash/Mouser).

### Added

- Logitech G502 HERO / G502-series detection and layout support.
- G502 onboard unlock flow that backs up the current onboard profile before writing.
- G502 special-button routing through F13-F16:
  - DPI Shift -> F13
  - DPI Down -> F14
  - DPI Up -> F15
  - Profile Cycle -> F16
- Windows low-level F13-F16 interception while a supported G502 is connected.
- Chinese and Traditional Chinese labels for the action ring overlay.
- Localized status/toast messages that follow the language selected in settings.

### Changed

- G502 special buttons are exposed as configurable physical buttons in Mouser after onboard unlock.
- Windows package is built as a GUI executable so it does not open a terminal window on launch.

### Notes

- This is not an official Logitech, G HUB, or upstream Mouser release.
- Personal config, G502 backups, and logs are not included in the public source repository.
