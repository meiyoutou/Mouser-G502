# Changelog

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

