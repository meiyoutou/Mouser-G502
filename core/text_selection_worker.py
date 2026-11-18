"""One-shot Tesseract recognition; no Qt, settings, clipboard, HID or networking."""
import json
import math
import os
from pathlib import Path
import sys


def peak_memory():
    if sys.platform != "win32":
        return {}
    import ctypes
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel.GetCurrentProcess.restype = w.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
    if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return {"peak_working_set_bytes": counters.PeakWorkingSetSize,
                "peak_commit_bytes": counters.PeakPagefileUsage}
    return {}


def cjk(char):
    return "\u2e80" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"


def recognize(source, runtime):
    from core.text_selection import checked_runtime
    runtime = checked_runtime(runtime)
    if runtime is None:
        raise ValueError("unverified text selection component")
    # Native extension is optional and intentionally absent from the UI bundle.
    sys.path.insert(0, str(runtime))
    handles = []
    if hasattr(os, "add_dll_directory"):
        handles.append(os.add_dll_directory(str(runtime / "tesserocr")))
    import importlib
    tess = importlib.import_module("tesserocr")
    from PIL import Image, ImageOps
    with Image.open(source) as source_image:
        width, height = source_image.size
        if width * height > 32_000_000:
            raise ValueError("large input")
        image = ImageOps.grayscale(source_image)
    scale = min(2., 3200 / width, 6000 / height, math.sqrt(6_000_000 / (width * height)))
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    if size != image.size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    sx, sy = image.width / width, image.height / height
    glyphs = []
    # Tesseract's Windows narrow-path model loader cannot reliably open UTF-8
    # Chinese installation paths. Python changes this PRIVATE child's cwd via
    # the wide-character Win32 API; the native loader then only sees ASCII ".".
    # No model copy, short-path dependency or global/system setting is needed.
    os.chdir(runtime / "tessdata")
    with tess.PyTessBaseAPI(path=".", lang="chi_sim+eng",
                           oem=tess.OEM.LSTM_ONLY, psm=tess.PSM.AUTO) as engine:
        engine.SetVariable("user_defined_dpi", "150")
        engine.SetImage(image)
        engine.Recognize()
        iterator = engine.GetIterator()
        if iterator:
            while True:
                try:
                    text = iterator.GetUTF8Text(tess.RIL.SYMBOL)
                    box = iterator.BoundingBox(tess.RIL.SYMBOL)
                except RuntimeError:
                    # Tesseract also traverses empty/non-text layout blocks.
                    # These are normal on screenshots, not failed jobs.
                    text, box = None, None
                if text and box and text.strip() and iterator.Confidence(tess.RIL.SYMBOL) >= 20:
                    prefix = ""
                    if glyphs:
                        if iterator.IsAtBeginningOf(tess.RIL.TEXTLINE):
                            prefix = "\n"
                        elif iterator.IsAtBeginningOf(tess.RIL.WORD):
                            previous = glyphs[-1]["text"][-1]
                            if not (cjk(previous) or cjk(text[0])) and text[0].isalnum():
                                prefix = " "
                    x1, y1, x2, y2 = box
                    mapped = [max(0, math.floor(x1/sx)), max(0, math.floor(y1/sy)),
                              min(width, math.ceil(x2/sx)), min(height, math.ceil(y2/sy))]
                    if mapped[2] > mapped[0] and mapped[3] > mapped[1]:
                        glyphs.append({"text": text, "prefix": prefix, "box": mapped})
                if len(glyphs) >= 100_000 or not iterator.Next(tess.RIL.SYMBOL):
                    break
    return {"ok": True, "protocol": 1, "size": [width, height], "glyphs": glyphs,
            "text": "".join(g["prefix"] + g["text"] for g in glyphs).lstrip(),
            "engine": "Tesseract 5 / tessdata_fast chi_sim+eng", "network_used": False,
            **peak_memory()}


def main(args=None):
    args = list(sys.argv[1:] if args is None else args)
    if len(args) != 3:
        return 2
    try:
        data = recognize(args[0], args[2])
    except Exception as error:
        # This private result file is not logged. Import/loader diagnostics
        # contain no recognized text and help diagnose optional native DLLs.
        data = {"ok": False, "protocol": 1, "error": "text_select_failed",
                "error_type": type(error).__name__,
                "loader_detail": str(error)[:500] if isinstance(error, (ImportError, OSError)) else ""}
    Path(args[1]).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return 0 if data["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
