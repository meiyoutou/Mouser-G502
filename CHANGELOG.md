# Changelog

## v3.7.60 — Windows screenshot tools, long-image text selection and view navigation

- Add the existing optional Text selection action to finished-image editors,
  including completed long screenshots. Recognize flattened, redacted pixels
  only on request, in the existing isolated worker; keep the same small component.
- Drag recognized text and use Ctrl+C/Ctrl+A without changing the image.
  Keep glyph coordinates across zoom/scroll; cancel stale jobs after image edits
  or closure. Image finish/save/pin never includes text-selection highlights.
- Use Ctrl+wheel to zoom around the pointer and plain wheel to scroll, over
  either the image or viewport padding. Add matching zoom buttons, plus a
  pinned-window fit button and corner resize grip, with localized tooltips.
- Keep original export resolution. Zoom changes geometry without re-rendering
  the document. Preserve capture completion, mouse detection and personal data.
- Publish committed Windows x64 source and a runtime-only portable package.
  Include the small text-selection component and required licenses, but no
  preview images, local test notes, ASR models or personal data.
- Point update checks/manifests at this fork and publish the checksum-pinned
  optional speech runtime v2 for on-demand installation.

## v3.7.59 (local test build) — Restore completed long-image editing

- Route completed long screenshots through the existing edit/output entry,
  respecting the capture's "Edit after screenshot" preference. When enabled,
  the scrolling checkmark opens the editor instead of immediately copying or
  saving; the editor's checkmark performs the original output action.
- Retain annotation, explicit pinning and full-resolution edited pixels.
  Keep direct output when editing is disabled, without changing user settings.
- Preserve the v3.7.58 finish-race fix and compute-helper cleanup. Extend
  source and frozen-app checks for editor-before-output, edited copy/save/pin
  and disabled-editor delivery. Separate local test delivery; no public upload.

## v3.7.56 (local test build) — Compute and settings lifecycle

- Run live scrolling image registration in a lazy, session-owned child. Keep
  the original montage, verification, pause/undo and snapshot algorithm; only
  native matching/motion computation crosses bounded binary pipes in RAM.
  Close the helper on finish/cancel; handle timeouts, crashes and late results.
- Initialize the windowed child's inherited pipe handles without opening a
  terminal. Its early entry never loads Qt, config, logging, HID or an app GUI.
- Do not create the QML settings engine on tray-only startup. Release a safely
  hidden settings window after 60 seconds; recreate it on tray/second-instance
  activation and restore its page/geometry. Retain unsaved vocabulary/dialogs.
- Stop the hidden UI's 500 ms inventory snapshot refresh, not device discovery,
  reconnect, mapping, voice or screenshot services. Refresh immediately on show.
- Keep personal data, installed components, the running app and prior builds.
  Separate local test delivery only; no automatic switch or public upload.

## v3.7.55 (local test build) — Resource limits and leaner Windows bundle

- Initialize scrolling-capture NumPy/OpenBLAS with one BLAS thread, and OpenCV
  with two compute threads. Restore the process environment after import and
  synchronize speech-helper environment snapshots; keep ASR settings unchanged.
- Exclude unused OpenCV FFmpeg video decoding, Pillow AVIF and non-Material
  Controls styles. Keep Basic fallback, QtOpenGL, native dependencies/licenses.
- Default to INFO logs; the existing Debug mode switch enables DEBUG. Bound
  new main logs to 1 MiB × 4 files and speech event logs to 256 KiB × 3 files.
  Leave pre-existing historical logs, personal data and older packages intact.
- Keep stitching, image buffers, text selection and speech models unchanged.
  Separate local test package only; no automatic replacement or GitHub upload.

## v3.7.54 (local test build) — Text selection naming and legacy removal

- Use one localized Text selection menu entry and an original text-row/I-beam
  line icon, distinct from the ordinary pointer and annotation T.
- Remove the legacy RapidOCR / PP-OCRv6 controller, installer, editable result
  dialog, asset catalog and packaging spec/script. Remove the unusable legacy
  action from finished-image editors as well.
- Retain the approved Tesseract-based frozen-image drag-to-copy layer in
  region/full captures. Rename its component folder to `文字选择组件`; recognition
  remains opt-in, local and isolated. It still uses OCR internally and can err.
- Keep personal data, installed components and older builds untouched. This
  is a local test build, not a public release or live-program replacement.

## v3.7.51 (local test build) — Ordinary arrow pointer, not a crop tool

- Correct the visible default Select tool to use a mouse-pointer icon and
  ArrowCursor, not a dashed selection box or crosshair. Initial region
  capture still frames the screenshot; once framed, pointer clicks/drags
  neither replace nor move the crop, including outside its bounds.
- Make the result editor's default pointer neutral too, preventing a drag from
  silently cropping the image on Copy/Save/Finish. Keep document crop APIs
  separate for legacy programmatic checks.
- Retain clicked hand move mode, boundary handles, fixed source pixels, explicit
  free-moving pins and existing output routes. Do not pass clicks through to
  underlying apps or pretend frozen pixels are interactive/selectable text.
- Add pointer, first-frame, full-screen and output regression/frozen checks.
  Preserve personal settings and old builds; local only, no GitHub upload.

## v3.7.50 (local test build) — Default Select and persistent hand move mode

- Add a visible checked Select (default) button. Clicking the hand selects an
  exclusive move mode; release the button, then drag anywhere inside the crop
  to move it. Further drags work without pressing the hand again.
- Select locks interior dragging again; outside dragging can reselect. Edge
  handles still resize in either mode. Frozen pixels and annotations stay
  anchored. Correct QRectF/QRect conversion so moving never grows the crop.
- Keep independent pins freely movable, with no automatic pin or OCR.
  Localize hints, preserve existing shortcuts, settings and old builds.
- Verify default/mutually exclusive modes, released-button interior dragging,
  repeated and cross-monitor moves, bounds, cursor, resize and copy output.
  Local testing only; no GitHub publication or live-program replacement.

## v3.7.49 (local test build) — Frozen selection hand grip, separate free-moving pins

- Correct the interaction from 3.7.48: display a hand drag grip immediately in
  the selection toolbar after the user releases the region selection. No need
  to click Finish or create a pin first. Hand dragging adjusts only the crop
  within frozen screen bounds; underlying screenshot pixels stay anchored.
- Keep ordinary inside-selection dragging from moving the fixed selection.
  Edge handles still resize it, drawing tools still annotate, and the explicit
  hand moves the bounds, including across negative-coordinate monitors.
- Remove automatic pin creation after ordinary or scrolling copy/save.
  Pin is once again a separate explicit action, not the screenshot preview.
- Restore free dragging from the image and background of explicit pin windows;
  pins are not confined to their small hand grip. Keep full-resolution copying
  and optional long-image scroll/zoom in those independent pins.
- Add generated-pixel tests for immediate hand visibility, actual hand mouse
  events, immutable frozen pixels, bounded crop movement, no automatic pins,
  localization and separate freely movable image pins. No automatic OCR,
  personal setting migration or GitHub publication.

## v3.7.48 (local test build) — Fixed screenshot results with an explicit hand grip

- Keep completed region/full-screen/scrolling screenshots on screen by default,
  after the original copy/save succeeds. Keep cancellation, failure, original
  shortcut mappings and the explicit Pin action unchanged. No automatic OCR.
- Reuse the pinned-result window with a compact hand drag handle, Copy and
  Close controls outside the image. Keep the window topmost without activating
  another app or stealing its keyboard focus; Copy is an explicit mouse action.
- Fit long-image width into a bounded scrollable window rather than shrinking
  the entire long image into a thin unreadable thumbnail. Wheel scrolls;
  Ctrl+wheel zooms. Copy always uses the unscaled original, never the toolbar
  or viewport crop. Closing the window does not change the clipboard.
- Localize hints/accessibility names in English, Simplified and Traditional
  Chinese, including live language changes. No runtime/model download is
  needed. Existing optional OCR remains a separate explicit action.
- Add generated-pixel completion, hand-drag, scroll, full-resolution copy,
  localization, cancellation/failure and frozen-program checks. Local only;
  retain user settings, existing installs and rollback builds.

## v3.7.47 (local test build) — Refresh verified overlap instead of freezing old tails

- Replay all eight stored frames from the user-initiated private Codex
  diagnostic: seven successful appends reproduce the recorded 1000-row
  displacement. The original complete run produced a 930x5991 result, but only
  the capped eight frames are available for replay; do not claim a full rerun.
- Fix a confirmed output defect: append-only bottom strips froze the fixed
  "jump to bottom" button into successive seams. Place each new join within
  the already-verified overlap and replace the old lower overlap with actual
  pixels from the latest frame. Recorded-sample button occurrences drop from
  seven to one without changing the registered offsets or content bounds.
- Retain the final visible overlay once; do not invent pixels hidden in the
  final frame. Insufficient/ambiguous overlap is still refused. This is not a
  general-purpose watermark remover or a guarantee for all fixed overlays.
- Add generated-pixel regression and frozen-executable checks. Keep private
  frames and replay images outside source, build resources and public ZIPs.
  Keep the thumbnail-only preview and direct long-image delivery unchanged.
- Local test only; do not replace the running app, modify personal bindings or
  publish to GitHub automatically.

## v3.7.46 (local diagnostic test) — Accessibility candidates and private tracing

- Retain image-based fixed-panel refinement even when UI Automation supplies a
  narrowed rectangle. A chat webview can contain both a scrolling transcript
  and a fixed header/composer. Previously that path disabled refinement.
- Add a regression for the 1322x1010 coarse-container case and log subsequent
  image refinement even when accessibility narrowed the original selection.
- Add an explicit standalone `--diagnose-scroll` entry before logging, config,
  HID and single-instance handling. It may run beside the existing app.
  Consent and manual region selection are required; the user scrolls.
- Save at most eight full selected frames (before UIA cropping), bounded on a
  private asynchronous writer, plus local metadata/result. No clipboard write,
  input injection or upload. Normal screenshot capture records no frames.
- Actual Codex frame-pair verification is still pending user-driven capture.
  This is a local diagnostic build, not a confirmed real-scene fix or release.

## v3.7.45 (local test build) — Verified registration and continuous preview

- Replace the live session's exact-row matcher with lazy headless OpenCV
  registration: independent multi-column templates/ORB propose translations;
  appearance, detail, ambiguity and color checks authorize appending pixels.
  Keep the legacy matcher only for compatibility and regression comparisons.
- Infer moving-body bounds separately from candidate scoring; keep a reliable
  anchor on failure and allow revisiting already captured content without
  appending it twice. Continue refusing insufficient or ambiguous overlaps.
- Show an always-visible bounded thumbnail, computed on the matching worker.
  Keep only Cancel and Finish controls; preview never pauses capture or opens
  another window. Finish directly copies/saves via the original screenshot
  action; ordinary screenshots retain their editing surface.
- Preserve single-flight worker isolation, capture exclusion, final flush and
  size/pixel limits. Failed final joins may recover without a hidden Resume
  control; explicitly finishing again keeps the visible accepted content.
- Add portrait/landscape, font-scale/antialiasing, recovery, reverse/revisit,
  bounded-preview, direct-delivery and frozen-entry checks. Tests cannot prove
  compatibility with every third-party window.
- Bundle the screenshot-only OpenCV/NumPy runtime and license notices, not
  speech/OCR engines or models. ScrollSnap MIT design notice is retained.
  Local test only; no personal configuration or GitHub publication changes.

## v3.7.44 (local test build) — Pixel-motion fallback without accessibility

- Fix the confirmed unsupported-provider case: a 1689x1135 selection remained
  uncropped and all subsequent frames were rejected. Retain advisory UIA but
  add a dependency-free pixel-motion fallback over selected images only.
- Infer one unambiguous moving rectangle from internal native-RGB anchors.
  Verify actual aligned pixels and require almost all motion inside it;
  never crop away changing digits to manufacture a match.
- Avoid weak average-gray alignment while the content region is unknown.
  Once inferred, match the interior and replace the old bottom margin instead
  of repeating fixed white padding at every join. Undo remains pixel-reversible.
- Treat unchanged content with a blinking excluded panel as idle, not failure.
  Add no-UIA, white-panel/caret, ten successive scrolls, wrong/repeated views,
  undo/new-branch and frozen-binary checks.
- Native owned-fixture test deliberately disables UIA and verifies ten actual
  screen captures/appends, total 1070 pixels, against the known source pixels.
  This does not constitute a test of the user's Codex window.
- No new optional imaging/model runtime. Single-monitor downward capture and
  conservative rejection remain. Local only; user data and GitHub unchanged.

## v3.7.43 (local test build) — Detect scrolling content inside fixed panels

- After selection closes, resolve the scrolling viewport using read-only UIA
  geometry, including Qt viewport/adjacent-scrollbar layouts without a
  ScrollPattern. Intersect with the selection, never enlarge it or read text.
  Unsupported, stale or timed-out providers retain the original selection.
- Crop the frozen seed and live frames to the same physical rectangle.
  Show a localized hint when capture is narrowed to the detected content.
- Match independent native-pixel stripes to tolerate a narrow scrollbar or
  small blinking caret; verify full-overlap pixels without relaxing existing
  error thresholds. Ambiguous repeated patterns are still rejected.
- Probe off the GUI thread with a bounded wait and one background provider
  job. Add synthetic geometry, provider failure, fixed-panel, pixel matching,
  controller and frozen-program checks.
- Single-monitor, downward capture remains. Not arbitrary pixel-based
  fixed-header removal; unsupported apps still require selecting content only.
  Local test only; existing configuration, active app and GitHub unchanged.

## v3.7.42 (local test build) — Scroll manually, stitch automatically

- Start live region sampling automatically when scrolling capture opens.
  The user scrolls the original target; no Append viewport clicks or synthetic
  scrolling input are required. Unchanged/rejected frames are deduplicated.
- Run overlap analysis on a single background job with snapshot isolation.
  Finish flushes the latest viewport; cancellation/pause discard late results.
- Focusless, capture-excluded controls provide Pause/Resume, Undo, Preview,
  Cancel and a checkmark. Preview/Undo pause capture; Resume is explicit.
  If Windows cannot exclude overlapping controls, pause rather than capture them.
- Keep conservative alignment, single-monitor downward-only capture and
  pixel/height memory limits. Increase the fragment cap to 500 for small
  automatic updates; unresolved final views require explicit partial completion.
- Add automatic timer, lifecycle, localization and frozen-program checks.
  Local test only; personal configuration, the active app and GitHub unchanged.

## v3.7.41 (local test build) — Native-pixel scrolling overlap fix

- Match native RGB row fingerprints in linear row time and verify actual
  pixels before falling back to the existing conservative approximate matcher.
  White text pages with exact overlap are no longer rejected solely because
  their blurred gray sampling scores are ambiguous.
- Check multiple real alignments and continue refusing periodic/ambiguous,
  unchanged, insufficient-overlap or incompatible frames without modifying
  the existing stitched image. Exact alignment supports small scroll steps.
- Add text-page, multi-append/undo, repeated-pattern, collision-verification,
  fallback and frozen checks. Diagnostics log reason codes and dimensions,
  never captured text or pixel data.
- Scrolling remains manual, single-monitor, downward capture. No automatic
  scrolling/append, fixed-header removal or cross-monitor support is added.
- Local test package only; user data, current program, startup and GitHub
  remain unchanged.

## v3.7.40 (local test build) — Consistent screenshot icons and fewer controls

- Remove Number and Full image from both screenshot toolbars/menus.
- Remove the redundant selection/crop button; basic region selection and edge
  resizing remain. Right-click or click the active tool again to leave drawing.
  Automatic window snapping remains unchanged.
- Rebuild icons on one vector grid with consistent strokes, native high-DPI
  rasters, fixed 34px buttons and no offset-inducing menu indicators.
- Reuse frozen monitor images when switching tools, avoiding an unnecessary
  full-desktop render/copy. Draft previews are still cleared when cancelled.
- Local test only; existing user data, running app, startup and GitHub unchanged.

## v3.7.39 (local test build) — Screenshot toolbar priorities

- Finish is an icon-only check mark; localized tooltip and accessibility label
  retain the copy/save destination and Enter shortcut.
- Manual scrolling capture and pin are primary buttons. The finished-image
  editor omits live scrolling, which cannot apply to an already captured image.
- Text moves into More; inline input, edits and undo behavior are unchanged.
- Number stamps, full-image crop reset and help remain in More.
- Existing configuration, running app, startup and public release are unchanged.

## v3.7.38 (local test build) — Compact screenshot interaction

- Region/full screenshots share a frozen per-monitor selection and annotation
  surface, with a single compact floating toolbar; no separate editor transition.
- Original line icons, context-only colors/width/font options, grouped shapes,
  localized destination-specific finish button and a More menu.
- Inline editable text; Ctrl+Enter commits and Esc discards the current text
  without cancelling the screenshot. Existing text can be reopened and edited.
- OCR installation is prompted only when OCR is requested, never automatically.
  OCR/clipboard/save/pin consume the same flattened selected pixels.
- Manual scroll capture has a smaller control window with an optional preview.
  Scrolling is still manual, single-monitor and conservative overlap matching.
- Existing mappings, direct-output mode, user data, startup reference and stable
  public release are unchanged. This is a local test build, not a QQ asset copy.

## v3.7.37 (local test build) — Screenshot phase two

- Snapshot visible top-level window bounds in z-order, excluding Mouser,
  minimized/cloaked windows and the desktop/taskbar. Hover/click or Enter snaps;
  drag retains free selection. A toggles snapping, M the frozen-pixel magnifier.
- Editor magnifier reads exactly the flattened preview, including crop/redaction.
- Optional independent RapidOCR 3.10.0 / PP-OCRv6 small CPU Chinese/English
  component: explicit local ZIP installation, pinned size/hash, safe staged
  extraction and rollback. Not included or loaded in the main app. Component
  has not been published online. Explicit model paths prevent silent downloads.
- OCR uses only the flattened current image; editable results require explicit
  copying and never auto-paste or upload. Hidden worker exits per job and
  cancellation/timeout stops only that worker.
- S in region selection starts manual downward scrolling capture. User scrolls,
  then appends one viewport. Controls hide before capture; matching rejects
  unchanged/ambiguous/non-overlapping frames. Exact vertical pixel matching,
  undo, monitor-change check, 50-frame/20,000px/32MP caps. Finish reuses the editor.
- Scrolling currently supports a single monitor and content-only regions.
  Fixed bars, repeated/dynamic content and horizontal movement may be rejected.
  It is not automatic scrolling or recording. Existing mappings/configuration
  and direct copy/save mode are unchanged. Local test only; no GitHub upload.

## v3.7.36 (local test build) — Windows screenshot editor

- Region and virtual-desktop full-screen actions share a pixel-coordinate
  editor: crop/resize selection, shapes, arrows, pen, plain text, numbering,
  mosaic and solid conceal, stroke/color/font/block controls, undo/redo,
  copy, PNG save/save-as and movable/zoomable focusless pinned screenshots.
- Preview and delivery use the same frozen captured pixels. Render full
  annotations before cropping so mosaic pixels remain identical after crop.
  Multi-screen selection uses per-screen frozen background panes, retaining
  the existing logical-to-physical monitor mapping.
- Region selection supports moving/resizing before Enter/double-click opens
  editing. Editor Enter delivers to the original clipboard/file destination.
  Esc cancels without output. Close/error releases the editor busy state.
- Edit-after-capture is on by default in Windows; General settings can restore
  immediate output without changing shortcut bindings. English, Simplified
  Chinese and Traditional Chinese labels follow the interface language.
- Flattened exports contain no original image layer. Mosaic is not a secure
  redaction guarantee; solid conceal is provided for sensitive information.
- OCR, automatic window snapping, scrolling capture and recording remain
  outside this first phase. Other platform capture paths are unchanged.
- Carry forward local 3.7.35 speech/sensitivity changes. This package is not
  uploaded and does not change the public stable release.

## v3.7.35 (local test build) — Local-first speech installation and actual sensitivity

- Check adjacent `可选语音组件` / `Speech-components` ZIPs by exact size and
  SHA-256 before downloading missing assets. Reject corrupt local packages;
  retain installed models and personal shortcuts. Show installation errors on
  the Voice page and record network reason codes without proxy credentials.
- Package speech runtime v2 separately so the worker uses the new VAD limits.
  This local test runtime is not published; keep its ZIP beside the application.
  Existing v1 model ZIPs remain compatible and need no model replacement.
- Gesture distance now starts at 1 px with matching low-distance tracking and
  return gates; retain existing >=8 px recognition and 90 ms repeat guards.
- Ring hold duration starts at 1 ms. Horizontal shortcut trigger amount starts
  at 1% (0.01 logical step), with non-volume repeat intervals from 1 ms. Retain
  volume's separate 60 ms guard and physical device/timer precision limits.
- Speech VAD probability starts at 1% and pause detection at 0.1 seconds
  (setting 1). Values reach the detector, not only the UI. Very low values may
  cause noise detection, early phrase splitting or accidental mouse actions.
- Do not reset existing settings. Speech changes apply on the next recording.

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
