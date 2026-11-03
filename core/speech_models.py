"""Pinned external model packs; automatic component download is separate."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import zipfile

SENSE_VOICE_MODEL = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
STREAMING_MODEL = "sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23"
PACK_MANIFEST = "mouser-model-pack.json"
PACK_FORMAT = "mouser-speech-model-pack"

# Pin the model assets shipped by this project, not a checksum supplied by an
# arbitrary imported ZIP. New official models require a deliberate catalog update.
ASSETS = {
    "silero_vad.onnx": (643854, "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"),
    f"{SENSE_VOICE_MODEL}/model.int8.onnx": (239233841, "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51"),
    f"{SENSE_VOICE_MODEL}/tokens.txt": (315894, "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc"),
    f"{STREAMING_MODEL}/encoder-epoch-99-avg-1.int8.onnx": (21621684, "1c556ea57cec304e55ec4b72e52c1cc098bb01476ed7d90f3de939fe126487b1"),
    f"{STREAMING_MODEL}/decoder-epoch-99-avg-1.int8.onnx": (1888682, "22f123bb8cba9b38974b3df18a3f45e7081f4985ebb2e075d9f21f618c468bbf"),
    f"{STREAMING_MODEL}/joiner-epoch-99-avg-1.int8.onnx": (1795562, "a7cf9d82757bdcf786059454495a9ca95e4bd7347f72473fc08d794475c36169"),
    f"{STREAMING_MODEL}/tokens.txt": (48697, "8b294db9045d6e5f94647f4c1eec1af4da143a75053c399611444b378ff966ac"),
    "faster-whisper-small/config.json": (2370, "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"),
    "faster-whisper-small/model.bin": (483546902, "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"),
    "faster-whisper-small/tokenizer.json": (2203239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
    "faster-whisper-small/vocabulary.txt": (459861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
}
CATALOG = {
    "sensevoice": {"name": "SenseVoice Small (int8)", "folder": SENSE_VOICE_MODEL,
                   "engine": "sense_voice", "note": "speech.recommend_sensevoice"},
    "zipformer": {"name": "Zipformer 14M (int8)", "folder": STREAMING_MODEL,
                  "engine": "sherpa_onnx_streaming", "note": "speech.recommend_zipformer"},
    "whisper-small": {"name": "Whisper small", "folder": "faster-whisper-small",
                      "engine": "faster_whisper", "note": "speech.recommend_whisper"},
}


class ModelPackError(ValueError):
    pass


def bundle_roots():
    roots = []
    if getattr(sys, "frozen", False):
        if getattr(sys, "_MEIPASS", ""):
            roots.append(Path(sys._MEIPASS))
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parent.parent)
    return list(dict.fromkeys(roots))


def model_directory():
    if os.environ.get("MOUSER_SPEECH_MODEL_DIR"):
        return Path(os.environ["MOUSER_SPEECH_MODEL_DIR"]).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "Mouser" / "speech_models"


def model_roots():
    return list(dict.fromkeys([model_directory(), *(root / "speech_models" for root in bundle_roots())]))


def find_model(name, explicit="", required=()):
    candidates = [Path(explicit)] if explicit else [root / name for root in model_roots()]
    for path in candidates:
        if path.exists() and all((path / item).is_file() for item in required):
            return path
    return None


def runtime_enabled():
    from core.speech_components import runtime_executable
    if runtime_executable() is not None:
        return True
    # Legacy full packages have no marker and remain compatible.
    for root in bundle_roots() if getattr(sys, "frozen", False) else []:
        marker = root / "speech-runtime.json"
        if marker.is_file():
            try:
                return json.loads(marker.read_text(encoding="utf-8")).get("enabled") is True
            except (OSError, ValueError):
                return False
    try:
        return all(importlib.util.find_spec(name) is not None for name in ("numpy", "sounddevice", "sherpa_onnx", "soxr"))
    except (ImportError, ValueError):
        return False


def pack_paths(pack_id):
    if pack_id not in CATALOG:
        raise ModelPackError("Unknown model pack")
    folder = CATALOG[pack_id]["folder"] + "/"
    return ["silero_vad.onnx", *(name for name in ASSETS if name.startswith(folder))]


def catalog_status():
    result = []
    for pack_id, item in CATALOG.items():
        paths = pack_paths(pack_id)
        required = [name.split("/", 1)[1] for name in paths if "/" in name]
        result.append({**item, "id": pack_id, "bytes": sum(ASSETS[name][0] for name in paths),
                       "installed": find_model(item["folder"], required=required) is not None,
                       "vad_installed": find_model("silero_vad.onnx") is not None})
    return result


def _safe_name(name):
    if not isinstance(name, str) or "\\" in name or ":" in name or "\x00" in name:
        raise ModelPackError("Unsafe model archive path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {".", ".."} for part in name.split("/")) or str(path) != name:
        raise ModelPackError("Unsafe model archive path")
    return name


def _check_parent(path, root):
    root = root.resolve()
    if not path.resolve().is_relative_to(root):
        raise ModelPackError("Model destination escapes its directory")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ModelPackError("Symlink model destinations are not supported")


def install_pack(archive, destination=None, progress=None, cancel_event=None):
    """Validate the entire pinned ZIP before changing existing installed assets.

    Commit each pack directory atomically; roll back it and shared VAD on error.
    Staging/rollback folders are newly created inside this model directory only.
    """
    root = Path(destination) if destination is not None else model_directory()
    if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise ModelPackError("Symlink model destinations are not supported")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) > 24 or len({entry.filename for entry in entries}) != len(entries):
            raise ModelPackError("Duplicate or excessive model archive entries")
        for entry in entries:
            _safe_name(entry.filename)
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                raise ModelPackError("Unsupported model archive entry")
        if PACK_MANIFEST not in z.namelist() or z.getinfo(PACK_MANIFEST).file_size > 32768:
            raise ModelPackError("This is not a Mouser model pack ZIP")
        try:
            manifest = json.loads(z.read(PACK_MANIFEST))
            pack_id = manifest["id"]
            if manifest.get("format") != PACK_FORMAT or manifest.get("version") != 1:
                raise ValueError()
            paths = pack_paths(pack_id)
            advertised = manifest["files"]
            if not isinstance(advertised, dict) or set(advertised) != set(paths):
                raise ValueError()
        except (KeyError, TypeError, ValueError) as error:
            raise ModelPackError("Invalid model pack manifest") from error
        expected = set(paths) | {PACK_MANIFEST, "NOTICE.md"}
        if set(z.namelist()) != expected or z.getinfo("NOTICE.md").file_size > 65536:
            raise ModelPackError("Unexpected or missing files in model pack")
        for name in paths:
            size, digest = ASSETS[name]
            if z.getinfo(name).file_size != size or advertised[name] != {"size": size, "sha256": digest}:
                raise ModelPackError("Model pack does not match this application's catalog")
        total = sum(ASSETS[name][0] for name in paths)
        if shutil.disk_usage(root).free < total + 64 * 1024 * 1024:
            raise ModelPackError("Not enough free space for model installation")
        with tempfile.TemporaryDirectory(prefix=".model-install-", dir=root) as temporary:
            stage = Path(temporary)
            done = 0
            for name in paths:
                if cancel_event is not None and cancel_event.is_set():
                    raise ModelPackError("cancelled")
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with z.open(name) as source, target.open("wb") as output:
                    while data := source.read(1024 * 1024):
                        if cancel_event is not None and cancel_event.is_set():
                            raise ModelPackError("cancelled")
                        output.write(data)
                        digest.update(data)
                        done += len(data)
                        if progress:
                            progress(min(99, int(done * 100 / total)))
                if target.stat().st_size != ASSETS[name][0] or digest.hexdigest() != ASSETS[name][1]:
                    raise ModelPackError("Model checksum validation failed")
            folder = CATALOG[pack_id]["folder"]
            (stage / folder / "NOTICE.md").write_bytes(z.read("NOTICE.md"))
            committed, backups = [], []
            if cancel_event is not None and cancel_event.is_set():
                raise ModelPackError("cancelled")
            try:
                for name in (folder, "silero_vad.onnx"):
                    target = root / name
                    _check_parent(target, root)
                    if target.exists():
                        backup = stage / ("previous-" + name)
                        os.replace(target, backup)
                        backups.append((backup, target))
                    os.replace(stage / name, target)
                    committed.append(target)
            except Exception:
                for target in reversed(committed):
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink(missing_ok=True)
                for backup, target in reversed(backups):
                    os.replace(backup, target)
                raise
    if progress:
        progress(100)
    return pack_id


def create_pack(pack_id, source, archive):
    """Build helper: ship only catalogued model assets, VAD and license notice."""
    source = Path(source)
    paths = pack_paths(pack_id)
    manifest = {"format": PACK_FORMAT, "version": 1, "id": pack_id,
                "files": {name: {"size": ASSETS[name][0], "sha256": ASSETS[name][1]} for name in paths}}
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr(PACK_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        z.write(source / "NOTICE.md", "NOTICE.md")
        for name in paths:
            file = source / name
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if file.stat().st_size != ASSETS[name][0] or digest != ASSETS[name][1]:
                raise ModelPackError("Source model checksum mismatch: " + name)
            z.write(file, name)
    return Path(archive)
