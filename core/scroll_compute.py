"""Stateless screenshot registration RPC. No Qt, settings, hooks or disk pixels."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

MAX_PIXELS = 32_000_000
MAX_HEADER = 4096


def _worker_streams():
    if sys.stdin is not None and sys.stdout is not None:
        # Use independent unbuffered descriptors. A failed BufferedWriter
        # flush otherwise leaves bytes for Python's final sys.stdout flush,
        # turning an already-handled parent disconnect into exit code 120.
        return (os.fdopen(os.dup(sys.stdin.fileno()), "rb", buffering=0),
                os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0))
    # PyInstaller's Windows windowed bootloader sets sys.std* to None even
    # when Popen passed pipes. Bind only the child's inherited OS handles;
    # never allocate/attach a visible console.
    if sys.platform != "win32":
        raise OSError("worker pipes unavailable")
    import ctypes
    import msvcrt
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [w.DWORD]
    kernel.GetStdHandle.restype = w.HANDLE
    streams = []
    for identifier, mode, flags in ((-10, "rb", os.O_RDONLY), (-11, "wb", os.O_WRONLY)):
        handle = kernel.GetStdHandle(identifier & 0xFFFFFFFF)
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise OSError("worker pipes unavailable")
        fd = msvcrt.open_osfhandle(int(handle), flags | os.O_BINARY)
        streams.append(os.fdopen(fd, mode, buffering=0))
    return tuple(streams)


class StitchError(ValueError):
    """Translated reason codes, never captured content."""


def _read_exact(stream, size):
    result = bytearray()
    while len(result) < size:
        chunk = stream.read(min(size - len(result), 1024 * 1024))
        if not chunk:
            raise EOFError("scroll pipe closed")
        result.extend(chunk)
    return result


def _write_all(stream, data):
    view = memoryview(data)
    while view:
        written = stream.write(view)
        if not written:
            raise EOFError("scroll pipe closed")
        view = view[written:]


class ScrollComputeClient:
    """One lazy child per long-capture session; shared by immutable snapshots."""
    TIMEOUT = 45

    def __init__(self):
        self.process = None
        self._closed = False
        self._lock = threading.Lock()
        self._component_use = None

    def _start(self):
        if self._closed:
            raise StitchError("scroll_capture_error")
        if self.process is None or self.process.poll() is not None:
            from core.screenshot_components import using
            if self._component_use is None:
                self._component_use = using("scroll")
                self._component_use.__enter__()
            command = ([sys.executable, "--scroll-compute-worker"]
                       if getattr(sys, "frozen", False)
                       else [sys.executable, "-u", "-m", "core.scroll_compute"])
            from core.compute_limits import child_environment
            try:
                self.process = subprocess.Popen(
                    command, cwd=str(Path(__file__).resolve().parents[1]),
                    env=dict(child_environment(), PYTHONIOENCODING="utf-8",
                             PYINSTALLER_RESET_ENVIRONMENT="1", PYTHONDONTWRITEBYTECODE="1"),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    bufsize=0, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except BaseException:
                self._component_use.__exit__(None, None, None)
                self._component_use = None
                raise
            if self._closed:  # Cancellation may have raced the Popen call.
                self.close()
                raise StitchError("scroll_capture_error")
        return self.process

    def query(self, method, previous, current):
        if previous.size != current.size:
            raise StitchError("scroll_size")
        width, height = previous.size
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            raise StitchError("scroll_limit")
        with self._lock:
            process = self._start()
            deadline = threading.Timer(self.TIMEOUT, lambda: self._terminate(process))
            deadline.daemon = True
            deadline.start()
            try:
                _write_all(process.stdin, (json.dumps({"method": method, "width": width,
                    "height": height}) + "\n").encode("ascii"))
                for image in (previous, current):
                    _write_all(process.stdin, image.convert("RGB").tobytes())
                reply = process.stdout.readline(MAX_HEADER + 1)
                if not reply.endswith(b"\n") or len(reply) > MAX_HEADER:
                    raise ValueError("invalid scroll response")
                data = json.loads(reply)
                if data.get("error"):
                    raise StitchError(data["error"] if data["error"] in
                        {"scroll_unchanged", "scroll_overlap", "scroll_size", "scroll_limit"}
                        else "scroll_capture_error")
                return data["result"]
            except StitchError:
                raise
            except (OSError, EOFError, ValueError, KeyError) as error:
                self._terminate(process)
                raise StitchError("scroll_capture_error") from error
            finally:
                deadline.cancel()

    @staticmethod
    def _terminate(process):
        try:
            if process.poll() is None:
                process.terminate()
        except OSError:
            pass

    def close(self):
        self._closed = True
        process = self.process
        if process is None:
            return
        self._terminate(process)  # Only our disposable compute child, never the main app.
        use, self._component_use = self._component_use, None
        def reap():
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            finally:
                for stream in (process.stdin, process.stdout):
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
                if use is not None:
                    use.__exit__(None, None, None)
        threading.Thread(target=reap, name="ScrollComputeCleanup", daemon=True).start()


def serve():
    """Process selected pixels in RAM; EOF closes the session without persistence."""
    from PIL import Image
    from ui.screenshot_registration import RegistrationStitcher
    try:
        source, target = _worker_streams()
    except OSError:
        return 2
    while True:
        line = source.readline(MAX_HEADER + 1)
        if not line:
            return 0
        if len(line) > MAX_HEADER or not line.endswith(b"\n"):
            return 2
        try:
            request = json.loads(line)
            width, height = request["width"], request["height"]
            if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0
                    or width * height > MAX_PIXELS or request["method"] not in {"motion", "register"}):
                return 2
            size = width * height * 3
            previous = Image.frombytes("RGB", (width, height), bytes(_read_exact(source, size)))
            current = Image.frombytes("RGB", (width, height), bytes(_read_exact(source, size)))
            # Only methods below use native libraries. No full montage/history
            # is copied to or kept in the helper.
            from core.compute_limits import registration_libraries
            stitcher = RegistrationStitcher.__new__(RegistrationStitcher)
            stitcher._compute = None
            stitcher.cv, stitcher.np = registration_libraries()
            result = (stitcher._motion_rect(previous, current) if request["method"] == "motion"
                      else stitcher._register(previous, current))
            response = {"result": result}
            del stitcher, previous, current
        except EOFError:
            return 0
        except StitchError as error:
            response = {"error": str(error)}
        except Exception:
            response = {"error": "scroll_capture_error"}
        try:
            _write_all(target, (json.dumps(response) + "\n").encode("ascii"))
            target.flush()
        except (OSError, ValueError):
            # Parent closed/exited during computation: never leave a windowed
            # PyInstaller error dialog or orphan helper waiting for dismissal.
            return 0


if __name__ == "__main__":
    # Import the canonical module so its StitchError identity also matches
    # RegistrationStitcher when this file was executed using python -m.
    from core.scroll_compute import serve as run
    raise SystemExit(run())
