"""Pinned, on-demand downloads. The main application needs no ASR libraries."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from functools import lru_cache

from core.speech_models import bundle_roots, model_directory, install_pack, _safe_name, _check_parent

PROTOCOL = 1
RELEASE_TAG = "speech-components-v1-win64"
RELEASE_URL = "https://github.com/meiyoutou/Mouser-G502/releases/download/" + RELEASE_TAG
MAX_EXPANDED_BYTES = 800 * 1024 * 1024
_INSTALL_LOCK = threading.Lock()


class ComponentError(ValueError):
    def __init__(self, code, detail=""):
        self.code = code
        super().__init__(detail or code)


@lru_cache(maxsize=1)
def assets_catalog():
    # Trust only the catalog shipped in the application, not downloaded metadata.
    path = Path(__file__).with_name("speech_component_assets.json")
    if not path.is_file():
        path = next((root / "core/speech_component_assets.json" for root in bundle_roots()
                     if (root / "core/speech_component_assets.json").is_file()), path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("protocol") != PROTOCOL:
            raise ValueError()
        return data["assets"]
    except (OSError, ValueError, KeyError) as error:
        raise ComponentError("catalog", "Speech component catalog is unavailable") from error


def runtime_directory():
    return model_directory().parent / "speech_runtime" / "v1-win64"


def runtime_executable():
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        return None
    root = runtime_directory()
    executable = root / "MouserSpeech.exe"
    try:
        marker = json.loads((root / "mouser-runtime.json").read_text(encoding="utf-8"))
        asset = assets_catalog()["runtime"]
        if marker != {"protocol": PROTOCOL, "archive_sha256": asset["sha256"]}:
            return None
        if executable.is_file() and (root / "_internal").is_dir():
            info = executable.stat()
            if not _binary_matches(str(executable), info.st_size, info.st_mtime_ns, asset["exe_sha256"]):
                return None
            return executable
    except (OSError, ValueError, KeyError):
        pass
    return None


@lru_cache(maxsize=8)
def _binary_matches(path, size, mtime, expected):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest() == expected


def verify_executable(path):
    with Path(path).open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != assets_catalog()["runtime"]["exe_sha256"]:
        raise ComponentError("checksum", "Speech executable validation failed; reinstall the component")


def cancelled(event):
    if event is not None and event.is_set():
        raise ComponentError("cancelled")


class _HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ComponentError("url", "Non-HTTPS download redirect rejected")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def download(asset, destination, *, cancel_event=None, progress=None, opener=None):
    """Bounded streaming download, 3 tries, exact size/hash, HTTPS redirects only."""
    url = asset.get("url") or (RELEASE_URL + "/" + asset["name"])
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ComponentError("url", "Speech downloads require HTTPS")
    expected = int(asset["size"])
    if not 0 < expected <= 1024 * 1024 * 1024 or len(asset["sha256"]) != 64:
        raise ComponentError("catalog", "Invalid pinned speech asset")
    destination = Path(destination)
    open_url = opener or urllib.request.build_opener(_HTTPSRedirects()).open
    deadline = time.monotonic() + 900
    for attempt in range(3):
        cancelled(cancel_event)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mouser-Optional-Speech/1", "Accept-Encoding": "identity"})
            with open_url(request, timeout=20) as source, destination.open("wb") as output:
                if urllib.parse.urlsplit(source.geturl()).scheme != "https":
                    raise ComponentError("url", "Non-HTTPS response rejected")
                length = source.headers.get("Content-Length")
                if length is not None and int(length) != expected:
                    raise ComponentError("size", "Speech download size did not match the catalog")
                size, digest = 0, hashlib.sha256()
                # HTTPResponse.read(n) can wait for n bytes while a slow peer
                # keeps sending tiny fragments. read1 returns available data,
                # so progress, cancellation and the overall deadline stay live.
                read_chunk = getattr(source, "read1", source.read)
                while True:
                    cancelled(cancel_event)
                    if time.monotonic() > deadline:
                        raise ComponentError("network", "Speech download timed out")
                    chunk = read_chunk(256 * 1024)
                    if not chunk:
                        break
                    cancelled(cancel_event)
                    if time.monotonic() > deadline:
                        raise ComponentError("network", "Speech download timed out")
                    size += len(chunk)
                    if size > expected:
                        raise ComponentError("size", "Speech download exceeded its pinned size")
                    output.write(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(size, expected)
                if size != expected or digest.hexdigest() != asset["sha256"]:
                    raise ComponentError("checksum", "Speech download checksum failed")
            cancelled(cancel_event)
            return destination
        except (OSError, urllib.error.URLError, ComponentError) as error:
            destination.unlink(missing_ok=True)
            cancelled(cancel_event)
            if isinstance(error, ComponentError) and error.code not in {"network", "checksum"}:
                raise
            if attempt == 2 or time.monotonic() > deadline:
                if isinstance(error, ComponentError):
                    raise
                raise ComponentError("network", "Download failed; check the network and retry") from error
            if cancel_event is not None:
                cancel_event.wait(attempt + 1)
            else:
                time.sleep(attempt + 1)
    raise ComponentError("network")


def install_runtime(archive, asset, *, destination=None, cancel_event=None):
    root = Path(destination) if destination else runtime_directory()
    root.parent.mkdir(parents=True, exist_ok=True)
    _check_parent(root, root.parent)
    with Path(archive).open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != asset["sha256"]:
            raise ComponentError("checksum", "Speech runtime checksum mismatch")
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        names = [item.filename for item in entries]
        if len(names) != len(set(names)) or len(names) > 5000:
            raise ComponentError("archive", "Invalid speech runtime archive")
        for entry in entries:
            _safe_name(entry.filename)
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                raise ComponentError("archive", "Unsupported runtime archive member")
            if not (entry.filename in {"MouserSpeech.exe", "NOTICE.md"} or entry.filename.startswith("_internal/")):
                raise ComponentError("archive", "Unexpected speech runtime file")
        if "MouserSpeech.exe" not in names or not any(name.startswith("_internal/") for name in names):
            raise ComponentError("archive", "Incomplete speech runtime archive")
        total = sum(entry.file_size for entry in entries)
        if total != asset["expanded_size"] or total > MAX_EXPANDED_BYTES:
            raise ComponentError("size", "Invalid expanded runtime size")
        if shutil.disk_usage(root.parent).free < total + 64 * 1024 * 1024:
            raise ComponentError("disk", "Not enough free space for the speech runtime")
        with tempfile.TemporaryDirectory(prefix=".speech-runtime-", dir=root.parent) as temporary:
            stage = Path(temporary) / "new"
            stage.mkdir()
            for entry in entries:
                cancelled(cancel_event)
                target = stage / entry.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(entry) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        cancelled(cancel_event)
                        output.write(chunk)
            with (stage / "MouserSpeech.exe").open("rb") as executable:
                if hashlib.file_digest(executable, "sha256").hexdigest() != asset["exe_sha256"]:
                    raise ComponentError("checksum", "Speech executable checksum mismatch")
            (stage / "mouser-runtime.json").write_text(json.dumps({"protocol": PROTOCOL,
                "archive_sha256": asset["sha256"]}), encoding="utf-8")
            cancelled(cancel_event)
            backup = Path(temporary) / "previous"
            if root.exists():
                os.replace(root, backup)
            try:
                os.replace(stage, root)
            except Exception:
                if backup.exists():
                    os.replace(backup, root)
                raise
    return root / "MouserSpeech.exe"


def install_selection(pack_id, with_preview, *, cancel_event=None, progress=None, phase=None, assets=None, opener=None):
    from core.speech_models import CATALOG, catalog_status
    if pack_id not in CATALOG:
        raise ComponentError("catalog", "Unknown speech model")
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ComponentError("platform", "Automatic speech installation currently requires Windows x64")
    if not _INSTALL_LOCK.acquire(blocking=False):
        raise ComponentError("busy", "Another speech installation is active")
    try:
        assets = assets if assets is not None else assets_catalog()
        model_ids = [pack_id] + (["zipformer"] if with_preview and pack_id != "zipformer" else [])
        installed = {item["id"]: item["installed"] and item["vad_installed"] for item in catalog_status()}
        pending = (["runtime"] if runtime_executable() is None else []) + [item for item in model_ids if not installed[item]]
        root = model_directory().parent
        root.mkdir(parents=True, exist_ok=True)
        required = sum(assets[item]["size"] + assets[item]["expanded_size"] for item in pending) + 128 * 1024 * 1024
        if shutil.disk_usage(root).free < required:
            raise ComponentError("disk", "Not enough free space for download and installation")
        for index, item in enumerate(pending):
            cancelled(cancel_event)
            asset = assets[item]
            if phase:
                phase("download", item)
            with tempfile.TemporaryDirectory(prefix=".speech-download-", dir=root) as directory:
                archive = download(asset, Path(directory) / asset["name"], cancel_event=cancel_event,
                    opener=opener, progress=lambda done, total: progress(int((index + .8 * done / total) * 100 / len(pending))) if progress else None)
                if phase:
                    phase("install", item)
                cancelled(cancel_event)
                if item == "runtime":
                    install_runtime(archive, asset, cancel_event=cancel_event)
                else:
                    install_pack(archive, cancel_event=cancel_event)
                if progress:
                    progress(int((index + 1) * 100 / len(pending)))
        if progress:
            progress(100)
        return pack_id
    finally:
        _INSTALL_LOCK.release()
