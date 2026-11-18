"""Pinned optional screenshot engines; no screenshots, settings or input sent."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import sys
import tempfile
import threading
import zipfile

from core.speech_components import ComponentError, cancelled, download

KINDS = ("scroll", "text")
_LOCK = threading.RLock()
_ACTIVE = {kind: 0 for kind in KINDS}
_MUTATING = set()
_DLL_HANDLES = []


def catalog():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    data = json.loads((root / "core/screenshot_component_assets.json").read_text(encoding="utf-8"))
    if data["protocol"] != 1 or set(data["assets"]) != set(KINDS):
        raise ComponentError("catalog")
    return data["assets"]


def data_directory():
    override = os.environ.get("MOUSER_SCREENSHOT_COMPONENT_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "Mouser/screenshot_components"


def directory(kind):
    if kind not in KINDS:
        raise ComponentError("catalog")
    identifier = catalog()[kind]["id"]
    _safe_name(identifier)
    if "/" in identifier:
        raise ComponentError("catalog")
    return data_directory() / identifier


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or path.as_posix() != name
            or "\\" in name or ":" in name or "\x00" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ComponentError("archive")
    return path


def _no_links(root):
    # A user-writable installation must never redirect replacement/removal.
    for path in (root, *root.parents):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ComponentError("path")


def _files(root):
    """Inspect reparse attributes once per entry, not every ancestor per file."""
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if (stat.S_ISLNK(info.st_mode)
                        or getattr(info, "st_file_attributes", 0) & 0x400):
                    raise ComponentError("path")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    yield Path(entry.path)
                else:
                    raise ComponentError("path")


def _manifest(root, asset):
    _no_links(root)
    manifest_path = root / "manifest.json"
    if manifest_path.stat().st_size > 2 * 1024 * 1024 or manifest_path.is_symlink():
        raise ComponentError("checksum")
    if digest(manifest_path) != asset["manifest_sha256"]:
        raise ComponentError("checksum")
    files = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    if not isinstance(files, dict) or not files or len(files) > 5000:
        raise ComponentError("archive")
    actual = set()
    for path in _files(root):
        actual.add(path.relative_to(root).as_posix())
    if actual != {"manifest.json", *files}:
        raise ComponentError("checksum")
    for name, expected in files.items():
        _safe_name(name)
        path = root / name
        if digest(path) != expected:
            raise ComponentError("checksum")
    return files


def checked_directory(kind, root=None):
    try:
        root = Path(root) if root is not None else directory(kind)
        _manifest(root, catalog()[kind])
        return root
    except (OSError, ValueError, KeyError, TypeError):
        return None


@contextmanager
def using(kind):
    with _LOCK:
        if kind in _MUTATING:
            raise ComponentError("busy")
        _ACTIVE[kind] += 1
    try:
        yield
    finally:
        with _LOCK:
            _ACTIVE[kind] -= 1


@contextmanager
def _mutation(kind):
    with _LOCK:
        if _ACTIVE[kind] or kind in _MUTATING:
            raise ComponentError("busy")
        _MUTATING.add(kind)
    try:
        yield
    finally:
        with _LOCK:
            _MUTATING.discard(kind)


def local_directories():
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return [root / name for root in (base, base.parent)
            for name in ("可选截图组件", "Screenshot-components")]


def find_local(kind, roots=None):
    asset = catalog()[kind]
    for root in local_directories() if roots is None else roots:
        path = Path(root) / asset["name"]
        if path.is_file():
            return path  # Verification happens before any extraction.
    return None


def legacy_text_directory():
    from core.text_selection import checked_runtime
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    for folder in (base / "文字选择组件", base.parent / "文字选择组件"):
        if folder.is_dir() and checked_runtime(folder) is not None:
            return folder
    return None


def _promote(stage, root, temporary):
    _no_links(root)
    previous = temporary / "previous"
    if root.exists():
        os.replace(root, previous)
    try:
        os.replace(stage, root)
    except BaseException:
        if previous.exists():
            os.replace(previous, root)
        raise


def _supported(asset):
    abi = f"cp{sys.version_info.major}{sys.version_info.minor}"
    if (sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}
            or asset["python_abi"] != abi):
        raise ComponentError("platform")


def install(kind, archive=None, *, cancel_event=None, progress=None, phase=None, roots=None):
    """Local-first, exact checksums, bounded staging and atomic replacement."""
    asset = catalog()[kind]
    _supported(asset)
    with _mutation(kind):
        root = directory(kind)
        _no_links(root)
        root.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(root.parent).free < asset["expanded_size"] + asset["size"] + 32 * 1024 * 1024:
            raise ComponentError("disk")
        with tempfile.TemporaryDirectory(prefix=".install-", dir=root.parent) as temp:
            temp = Path(temp)
            source = Path(archive) if archive is not None else find_local(kind, roots)
            legacy = legacy_text_directory() if kind == "text" and source is None else None
            if legacy is not None:
                # Only an explicitly requested installation copies an adjacent
                # old component. Never move/delete its files or scan old builds.
                if phase:
                    phase("install")
                _manifest(legacy, asset)
                stage = temp / "new"
                stage.mkdir()
                for path in legacy.rglob("*"):
                    cancelled(cancel_event)
                    if path.is_file():
                        target = stage / path.relative_to(legacy)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, target)
                _manifest(stage, asset)
                cancelled(cancel_event)
                _promote(stage, root, temp)
                return root
            if source is None:
                if not asset.get("available_online", False):
                    raise ComponentError("not_published")
                if phase:
                    phase("download")
                source = download(asset, temp / asset["name"], cancel_event=cancel_event,
                                  progress=progress)
            if phase:
                phase("verify")
            cancelled(cancel_event)
            if source.stat().st_size != asset["size"] or digest(source) != asset["sha256"]:
                raise ComponentError("checksum")
            with zipfile.ZipFile(source) as bundle:
                entries = bundle.infolist()
                names = [entry.filename for entry in entries]
                if (len(entries) > 5000 or len({name.casefold() for name in names}) != len(names)
                        or sum(entry.file_size for entry in entries) != asset["expanded_size"]
                        or asset["expanded_size"] > 400 * 1024 * 1024):
                    raise ComponentError("archive")
                for entry in entries:
                    _safe_name(entry.filename)
                    if (entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16)
                            or entry.flag_bits & 1):
                        raise ComponentError("archive")
                if bundle.getinfo("manifest.json").file_size > 2 * 1024 * 1024:
                    raise ComponentError("archive")
                manifest = bundle.read("manifest.json")
                if hashlib.sha256(manifest).hexdigest() != asset["manifest_sha256"]:
                    raise ComponentError("checksum")
                expected = json.loads(manifest)["files"]
                if set(names) != {"manifest.json", *expected}:
                    raise ComponentError("archive")
                stage = temp / "new"
                stage.mkdir()
                if phase:
                    phase("install")
                for entry in entries:
                    cancelled(cancel_event)
                    target = stage / entry.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    hasher = hashlib.sha256()
                    with bundle.open(entry) as src, target.open("wb") as dst:
                        while chunk := src.read(1024 * 1024):
                            cancelled(cancel_event)
                            dst.write(chunk)
                            hasher.update(chunk)
                    if entry.filename != "manifest.json" and hasher.hexdigest() != expected[entry.filename]:
                        raise ComponentError("checksum")
            cancelled(cancel_event)
            _promote(stage, root, temp)
        return root


def uninstall(kind):
    with _mutation(kind):
        root = directory(kind)
        _no_links(root)
        if root.exists():
            # Validate every descendant before a recursive removal.
            list(_files(root))
            if root.parent.resolve() != data_directory().resolve():
                raise ComponentError("path")
            shutil.rmtree(root)


def activate_scroll():
    """Only call inside the disposable compute child, never the main UI."""
    root = checked_directory("scroll")
    if root is None:
        if getattr(sys, "frozen", False):
            raise ComponentError("scroll_component_missing")
        return None  # Source development uses the project's virtualenv.
    sys.path.insert(0, str(root))
    for name in ("numpy.libs", "cv2"):
        if hasattr(os, "add_dll_directory"):
            _DLL_HANDLES.append(os.add_dll_directory(str(root / name)))
    sys.dont_write_bytecode = True
    return root
