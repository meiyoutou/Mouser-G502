"""Compare existing frozen self-checks with Windows process counters; synthetic only."""
import argparse
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import time


class Counters(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
            "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


def run(old, new, output):
    output.mkdir(parents=True, exist_ok=True)
    kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
    samples = []
    for cycle in range(2):
        for label, executable in (("old", old), ("new", new)):
            report_path = output / f"{label}-{cycle+1}.json"
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_FONTDIR=r"C:\Windows\Fonts",
                QSG_RHI_BACKEND="software", QT_QUICK_BACKEND="software",
                APPDATA=str(output / "isolated/roaming"), LOCALAPPDATA=str(output / "isolated/local"),
                MOUSER_SPEECH_MODEL_DIR=str(output / "isolated/speech_models"))
            start = time.monotonic()
            process = subprocess.Popen([str(executable), "--check-screenshot-compact", str(report_path)],
                env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            handle = kernel.OpenProcess(0x410, False, process.pid)
            assert handle
            peak_working = peak_private = observations = 0
            try:
                while process.poll() is None:
                    counters = Counters()
                    counters.cb = ctypes.sizeof(counters)
                    if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                        peak_working = max(peak_working, counters.PeakWorkingSetSize)
                        peak_private = max(peak_private, counters.PrivateUsage)
                        observations += 1
                    if time.monotonic() - start > 100:
                        raise TimeoutError("Synthetic self-check exceeded 100 seconds")
                    time.sleep(.025)
            finally:
                kernel.CloseHandle(handle)
            assert process.returncode == 0
            check = json.loads(report_path.read_text(encoding="utf-8"))
            assert check["ok"] and check["frozen"]
            samples.append({"label": label, "version": check["version"], "cycle": cycle+1,
                "peak_working_mib": round(peak_working / 2**20, 2),
                "sampled_peak_private_mib": round(peak_private / 2**20, 2),
                "observations": observations, "elapsed_seconds": round(time.monotonic() - start, 3)})
    sizes = {}
    for label, executable in (("old", old), ("new", new)):
        files = [executable, *(p for p in (executable.parent / "_internal").rglob("*") if p.is_file())]
        sizes[label] = {"runtime_bytes": sum(file.stat().st_size for file in files), "file_count": len(files)}
    report = {"ok": True, "same_check": "--check-screenshot-compact", "synthetic_only": True,
              "settings_and_startup_untouched": True, "samples": samples, "sizes": sizes,
              "sampled_private_not_physical_ram": True}
    (output / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.old.resolve(), args.new.resolve(), args.output.resolve())
