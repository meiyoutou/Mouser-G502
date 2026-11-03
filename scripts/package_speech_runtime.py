"""Build the public optional runtime archive and output its pinned metadata."""
import argparse
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def package(source, archive):
    source, archive = Path(source), Path(archive)
    files = sorted(path for path in source.rglob("*") if path.is_file())
    if not (source / "MouserSpeech.exe").is_file():
        raise ValueError("Missing standalone speech executable")
    forbidden = {"config.json", "speech_to_text.log", ".env", "settings.json", "metadata.json"}
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in files:
            name = file.relative_to(source).as_posix()
            if file.is_symlink() or file.name in forbidden or file.suffix in {".log", ".err"}:
                raise ValueError("Unexpected private/runtime file: " + name)
            if not (name == "MouserSpeech.exe" or name.startswith("_internal/")):
                raise ValueError("Unexpected root runtime file: " + name)
            z.write(file, name)
        z.writestr("NOTICE.md", (ROOT / "scripts/speech_runtime_notice.md").read_text(encoding="utf-8")
                   + "\n\n## Mouser license\n\n" + (ROOT / "LICENSE").read_text(encoding="utf-8"))
        for license_file in sorted((ROOT / "scripts/licenses").glob("*LICENSE")):
            z.write(license_file, "_internal/third_party_licenses/" + license_file.name)
        for package in ("numpy", "sounddevice", "sherpa-onnx", "soxr", "faster-whisper", "huggingface-hub", "av"):
            info = distribution(package)
            for entry in info.files or []:
                if not any(word in Path(str(entry)).name.lower() for word in ("license", "copying")):
                    continue
                if Path(str(entry)).suffix in {".pyc", ".py", ".pyd", ".dll"}:
                    continue
                file = Path(info.locate_file(entry))
                if file.is_file():
                    name = "_internal/third_party_licenses/" + package + "/" + str(entry).replace("\\", "/")
                    if ".." in name.split("/") or name in z.namelist():
                        raise ValueError("Unexpected license path")
                    z.write(file, name)
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            raise ValueError("Runtime ZIP CRC failed")
        expanded = sum(entry.file_size for entry in z.infolist())
    with archive.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    with (source / "MouserSpeech.exe").open("rb") as file:
        executable_digest = hashlib.file_digest(file, "sha256").hexdigest()
    return {"name": archive.name, "size": archive.stat().st_size, "sha256": digest,
            "expanded_size": expanded, "exe_sha256": executable_digest}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("archive")
    args = parser.parse_args()
    print(json.dumps(package(args.source, args.archive), indent=2))
