"""Prepare the optional text-selection component without a second Python runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def package(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError("Destination must be new")
    destination.mkdir(parents=True)
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyi"}:
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    manifest = {"engine": "Tesseract 5.5.3 / tesserocr 2.11.0 / tessdata_fast",
                "files": {p.relative_to(destination).as_posix(): digest(p)
                          for p in sorted(destination.rglob("*")) if p.is_file()}}
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    archive = destination.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
        for path in destination.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(destination))
    print(json.dumps({"directory": "文字选择组件", "manifest_sha256": digest(destination / "manifest.json"),
                      "expanded_bytes": sum(p.stat().st_size for p in destination.rglob("*") if p.is_file()),
                      "zip_bytes": archive.stat().st_size}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    package(args.source, args.destination)
