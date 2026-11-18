"""Optional, checksum-pinned Tesseract component. Never imported for inference in UI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MAX_RESULT = 8 * 1024 * 1024


class TextSelectionError(ValueError):
    pass


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def catalog():
    root = Path(getattr(sys, "_MEIPASS", ROOT))
    return json.loads((root / "core/text_selection_assets.json").read_text(encoding="utf-8"))


def checked_runtime(root=None):
    asset = catalog()
    if root is None:
        from core.screenshot_components import checked_directory
        installed = checked_directory("text")
        if installed is not None:
            return installed
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT
        root = base / asset["directory"]
    root = Path(root)
    try:
        manifest_path = root / "manifest.json"
        if digest(manifest_path) != asset["manifest_sha256"]:
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, expected in manifest["files"].items():
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                    or not name or (root / name).is_symlink()
                    or not (root / name).resolve().is_relative_to(root.resolve())
                    or digest(root / name) != expected):
                return None
        return root
    except (OSError, ValueError, KeyError, TypeError):
        return None


def recognize(image, *, runtime=None, cancelled=None):
    from core.screenshot_components import using
    with using("text"):
        return _recognize(image, runtime=runtime, cancelled=cancelled)


def _recognize(image, *, runtime=None, cancelled=None):
    runtime = checked_runtime(runtime)
    if runtime is None:
        raise TextSelectionError("text_select_missing")
    if image.width() * image.height() > 32_000_000 or image.isNull():
        raise TextSelectionError("text_select_large")
    with tempfile.TemporaryDirectory(prefix="mouser-text-select-") as directory:
        directory = Path(directory)
        source, result = directory / "input.png", directory / "result.json"
        if not image.save(str(source), "PNG"):
            raise TextSelectionError("text_select_failed")
        args = [str(source), str(result), str(runtime.resolve())]
        command = ([sys.executable, "--text-selection-worker", *args]
                   if getattr(sys, "frozen", False)
                   else [sys.executable, "-m", "core.text_selection_worker", *args])
        environment = dict(os.environ, OMP_THREAD_LIMIT="2", OMP_NUM_THREADS="2",
                           PYTHONDONTWRITEBYTECODE="1")
        start = time.monotonic()
        process = subprocess.Popen(command, cwd=ROOT if not getattr(sys, "frozen", False) else None,
            env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            while process.poll() is None:
                if cancelled is not None and cancelled.is_set():
                    raise TextSelectionError("text_select_cancelled")
                if time.monotonic() - start > 60:
                    raise TextSelectionError("text_select_timeout")
                try:
                    process.wait(timeout=.08)
                except subprocess.TimeoutExpired:
                    pass
            if (process.returncode != 0 or not result.is_file()
                    or result.stat().st_size > MAX_RESULT):
                raise TextSelectionError("text_select_failed")
            data = json.loads(result.read_text(encoding="utf-8"))
            if (data.get("protocol") != 1 or data.get("ok") is not True
                    or data.get("size") != [image.width(), image.height()]
                    or not isinstance(data.get("glyphs"), list) or len(data["glyphs"]) > 100_000):
                raise TextSelectionError("text_select_failed")
            for glyph in data["glyphs"]:
                box = glyph["box"]
                if (not isinstance(glyph["text"], str) or not glyph["text"]
                        or glyph["prefix"] not in ("", " ", "\n")
                        or len(box) != 4 or any(type(v) is not int for v in box)
                        or not (0 <= box[0] < box[2] <= image.width()
                                and 0 <= box[1] < box[3] <= image.height())):
                    raise TextSelectionError("text_select_failed")
            data["elapsed_seconds"] = round(time.monotonic() - start, 3)
            return data
        except TextSelectionError:
            raise
        except (ValueError, KeyError, TypeError) as error:
            raise TextSelectionError("text_select_failed") from error
        finally:
            if process.poll() is None:
                # Only this job's private child, never the main app.
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
