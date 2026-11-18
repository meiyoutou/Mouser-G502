"""Build public screenshot components without another Python/Qt runtime."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import zipfile
import hashlib


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def copy_tree(source, destination):
    for path in sorted(source.rglob("*")):
        if (not path.is_file() or path.suffix in {".pyc", ".pyo", ".pyi"}
                or path.name.startswith("opencv_videoio_ffmpeg")
                or set(path.relative_to(source).parts) & {"__pycache__", "tests", "test", "data", "include"}):
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def package(output, text):
    output.mkdir(parents=True, exist_ok=False)
    assets = {}
    root = output / "scroll"
    root.mkdir()
    site = Path(sys.executable).parent.parent / "Lib/site-packages"
    for name in ("cv2", "numpy", "numpy.libs"):
        copy_tree(site / name, root / name)
        assert (root / name).is_dir(), name
    for package in ("opencv-python-headless", "numpy"):
        dist = importlib.metadata.distribution(package)
        for item in dist.files:
            if ".dist-info" in str(item) and "license" in str(item).lower() and not str(item).endswith(".py"):
                target = root / "licenses" / package / str(item)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dist.locate_file(item), target)
    manifest = {"protocol": 1, "kind": "scroll",
                "files": {p.relative_to(root).as_posix(): digest(p)
                          for p in sorted(root.rglob("*")) if p.is_file()}}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    for kind, source in (("scroll", root), ("text", text)):
        name = f"Mouser-screenshot-{kind}-v1-cp313-win64.zip"
        archive = output / name
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(source.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    bundle.write(path, path.relative_to(source).as_posix())
        with zipfile.ZipFile(archive) as bundle:
            expanded = sum(item.file_size for item in bundle.infolist())
        assets[kind] = {
            "id": f"{kind}-v1-cp313-win64", "python_abi": "cp313", "name": name,
            "url": "https://github.com/meiyoutou/Mouser-G502/releases/download/screenshot-components-v1-win64/" + name,
            "available_online": False,
            "size": archive.stat().st_size, "expanded_size": expanded,
            "sha256": digest(archive), "manifest_sha256": digest(source / "manifest.json"),
        }
    data = {"protocol": 1, "assets": assets}
    (output / "catalog.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--text-component", type=Path, required=True)
    args = parser.parse_args()
    package(args.output.resolve(), args.text_component.resolve())
