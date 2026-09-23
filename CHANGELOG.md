# Changelog

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
