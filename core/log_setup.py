"""
log_setup.py — Redirect all print() output to a rotating log file.

Call setup_logging() once, early in main_qml.py, before Qt and core imports.
"""
import io
import logging
import logging.handlers
import os
import sys
import threading

LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 3  # current + 3 backups: approximately 4 MiB, not 30 MiB
SPEECH_LOG_MAX_BYTES = 256 * 1024
SPEECH_LOG_BACKUPS = 2  # current + 2 backups: approximately 768 KiB
_speech_lock = threading.Lock()


def set_debug_logging(enabled: bool) -> None:
    """Follow the existing debug switch, without reconfiguring an embedding host."""
    root = logging.getLogger()
    if any(getattr(handler, "_mouser_owned", False) for handler in root.handlers):
        explicit_debug = os.environ.get("MOUSER_LOG_LEVEL", "").upper() == "DEBUG"
        root.setLevel(logging.DEBUG if enabled or explicit_debug else logging.INFO)


def log_speech_event(message: str) -> None:
    """Bound the existing event-only log; do not duplicate it into the root log."""
    root = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Mouser")
    path = os.path.abspath(os.path.join(root, "speech_to_text.log"))
    with _speech_lock:
        logger = logging.getLogger("mouser.speech.events")
        logger.propagate = False
        logger.setLevel(logging.INFO)
        if not logger.handlers or logger.handlers[0].baseFilename != path:
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
                handler.close()
            os.makedirs(root, mode=0o700, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=SPEECH_LOG_MAX_BYTES, backupCount=SPEECH_LOG_BACKUPS,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
            logger.addHandler(handler)
        logger.info(message)


def _get_log_dir() -> str:
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Logs", "Mouser")
    elif sys.platform == "linux":
        xdg_state = os.environ.get(
            "XDG_STATE_HOME",
            os.path.join(os.path.expanduser("~"), ".local", "state"),
        )
        return os.path.join(xdg_state, "Mouser", "logs")
    else:  # Windows
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "Mouser", "logs")


class _StreamToLogger:
    """Forward writes to a Logger. Thread-safe via threading.local buffer."""

    def __init__(self, logger: logging.Logger, level: int = logging.INFO):
        self._logger = logger
        self._level = level
        self._local = threading.local()

    def write(self, msg: str) -> int:
        if not hasattr(self._local, "buf"):
            self._local.buf = ""
        self._local.buf += msg
        while "\n" in self._local.buf:
            line, self._local.buf = self._local.buf.split("\n", 1)
            if line:
                self._logger.log(self._level, line)
        return len(msg)

    def flush(self) -> None:
        if hasattr(self._local, "buf") and self._local.buf:
            self._logger.log(self._level, self._local.buf)
            self._local.buf = ""

    def fileno(self):
        raise io.UnsupportedOperation("fileno")

    @property
    def encoding(self):
        return "utf-8"

    @property
    def errors(self):
        return "replace"

    def isatty(self):
        return False


def setup_logging() -> str:
    """
    Configure rotating file log and redirect stdout to it.
    Returns the log file path. Idempotent (safe to call multiple times).

    Only sys.stdout is redirected (all app output uses print()). sys.stderr
    is left untouched to avoid a recursion: logging handler errors call
    handleError() which writes to sys.stderr — redirecting it through the
    logger would create an infinite loop.
    """
    root = logging.getLogger()
    if root.handlers:
        return ""  # already configured

    log_dir = _get_log_dir()
    fmt = logging.Formatter(fmt="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    log_path = ""
    try:
        os.makedirs(log_dir, mode=0o700, exist_ok=True)
        log_path = os.path.join(log_dir, "mouser.log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
            delay=False,                # create file immediately on startup
        )
        file_handler._mouser_owned = True
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:
        log_path = ""
        # Fall back to console-only — app must not crash due to logging failure
        print(f"[Logging] Cannot create log dir {log_dir}: {exc}", file=sys.__stderr__)

    # Terminal output: only when NOT running as a frozen bundle.
    # getattr(sys, "frozen", False) is set by PyInstaller (same pattern used
    # in main_qml.py for ROOT path resolution). When frozen with console=False,
    # sys.stdout is /dev/null, so we skip the StreamHandler.
    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler(sys.__stdout__)
        console_handler._mouser_owned = True
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    root.setLevel(logging.INFO)
    set_debug_logging(False)

    # Redirect stdout — must come AFTER StreamHandler setup above.
    # StreamHandler uses sys.__stdout__ (original), not sys.stdout, so
    # redirecting sys.stdout here does not create a circular loop.
    sys.stdout = _StreamToLogger(root, logging.INFO)

    return log_path
