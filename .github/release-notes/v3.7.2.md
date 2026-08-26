# Mouser v3.7.2

**A Windows crash fix.** If Mouser vanished mid-use — on a right click, on a scroll, seemingly at random — this release is for you. Two users chasing what looked like two unrelated bugs turned out to be hitting the same line of code.

## 💥 The crash

Mouser read a field on every mouse event as if it were a memory address. It isn't — `dwExtraInfo` is an opaque tag the event's sender attaches, and it's usually zero. Whenever something on the system set it to anything else, Mouser dereferenced that number as a pointer and the process died instantly: no error dialog, no traceback, nothing in the log.

The line only ran with **debug mode enabled**, which is why it looked so arbitrary. @lazyzyf hit it on every right click (#252); @327607501 hit it on every scroll and narrowed it down by testing with debug mode off (#253). Same bug, different events.

Two related fixes went in alongside it:

- **Debug logging no longer floods.** A hi-res wheel emits ~15 events per detent, and each one wrote a debug line — a Qt signal plus a UI list rebuild every time. Wheel bursts are now coalesced to one line per 250 ms with a count of what was skipped.
- **Shell popups no longer freeze the app** (#252). The foreground-app detector resolved every unfamiliar `explorer.exe` window by enumerating *every* top-level window and opening each owning process. Windows 11 taskbar previews, Alt-Tab and context menus took that path three times a second for as long as they were open, starving the mouse hook until input stopped responding. Transient shell windows are now skipped outright, and anything else is resolved at most once.

## ↔️ Horizontal scroll direction (Windows)

Wheel tilt fired the wrong binding on Windows. A positive `WM_MOUSEHWHEEL` delta means the wheel was tilted **right**, but Mouser classified it as left — the opposite of its own macOS and Linux behaviour. Tilt left ran your "scroll right" action and vice versa.

Reported by **@327607501** on the M590 (whose wheel tilt is the main control bound to these events) and independently diagnosed and hardware-verified by **@unijiang** (#254). The direction is now decided in one shared helper that all three platforms call, with tests pinning the sign so the platforms can't drift apart again.

> [!IMPORTANT]
> **If you already mapped wheel tilt on Windows, swap your two assignments once after updating.** Anyone who set these up before this release worked around the old reversed behaviour, and that workaround is now the bug.

macOS and Linux are unaffected — they were already correct.

## ⌨️ Custom shortcut recorder

The shortcut dialog now has two explicit modes instead of trying to be both at once:

- **Record keys** (default) — press the shortcut you want. Held modifiers preview as `Ctrl + …` until a real key lands.
- **Type instead** — a plain text field, so shifted characters like `+` can be typed without the Shift press being recorded as the shortcut.

**The Windows key is now recordable.** Pressing it used to open the Start menu and steal focus before a second key could be pressed, making `Win + A` impossible to record. While recording, Mouser swallows just that key and folds it into the combo itself. The guard is released the moment the dialog closes, the mode switches, or the app loses focus.

Also: the dialog's key list said `f1–f12` while `f1–f24` have been supported for some time.

## 🙏 Thanks

To **@lazyzyf** and **@327607501** for reports precise enough to find a crash that leaves no trace — the log excerpt in #252 and the debug-mode A/B test in #253 were what cracked it. To **@unijiang** for the independent diagnosis and hardware verification of the scroll direction, on top of the M585/M590 support in v3.7.1. And to **@yj-Ban** for confirming the v3.7.1 Linux hi-res scroll fix on Mint (#244).

**Full changelog:** https://github.com/TomBadash/Mouser/compare/v3.7.1...v3.7.2
