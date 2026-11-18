"""Conservative Windows package exclusions, shared by the spec and tests."""


def unused_runtime_file(name: str) -> bool:
    path = name.replace("\\", "/").lower()
    base = path.rsplit("/", 1)[-1]
    if path.startswith("cv2/") and base.startswith("opencv_videoio_ffmpeg") and base.endswith(".dll"):
        return True
    if path.startswith("pil/") and (base.startswith("_avif.") or base == "avifimageplugin.py"):
        return True
    prefix = "pyside6/qml/qtquick/controls/"
    if path.startswith(prefix):
        relative = path[len(prefix):]
        # Keep root plugin/qmldir, Material + its explicit Basic fallback only.
        if "/" in relative and relative.split("/", 1)[0] not in {"basic", "material", "impl"}:
            return True
    return False
