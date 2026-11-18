"""Lazy screenshot compute limits; never export them to the speech helper."""
from __future__ import annotations

import importlib
import os
import sys
import threading

OPENBLAS_THREADS = 1
OPENCV_THREADS = 2
_lock = threading.RLock()
_libraries = None
_original_environment = None


def child_environment():
    """Snapshot without a concurrent screenshot import's temporary overrides."""
    with _lock:
        environment = dict(os.environ)
        if _original_environment is not None:
            for name, value in _original_environment.items():
                if value is None:
                    environment.pop(name, None)
                else:
                    environment[name] = value
        return environment


def registration_libraries():
    """Cap BLAS before its first import and configure OpenCV just once.

    NumPy reads OPENBLAS_NUM_THREADS during native initialization. Setting it
    after the import cannot avoid the initial thread/commit allocation. Restore
    the process environment even on import failure; no system/user env is edited.
    The shared lock also prevents a simultaneously launched ASR helper from
    inheriting these screenshot-only limits.
    """
    global _libraries, _original_environment
    with _lock:
        if _libraries is not None:
            return _libraries
        names = ("OPENBLAS_NUM_THREADS", "OPENBLAS_DEFAULT_NUM_THREADS")
        previous = {name: os.environ.get(name) for name in names}
        _original_environment = previous
        try:
            if getattr(sys, "frozen", False):
                from core.screenshot_components import activate_scroll
                activate_scroll()
            for name in names:
                os.environ[name] = str(OPENBLAS_THREADS)
            # cv2 imports NumPy too, so BOTH imports must be inside this scope.
            np = importlib.import_module("numpy")
            cv = importlib.import_module("cv2")
            cv.setNumThreads(OPENCV_THREADS)
            _libraries = cv, np
            return _libraries
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            _original_environment = None
