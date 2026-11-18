"""Text-selection measurements on public synthetic samples only."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QImage
from core import text_selection


def sample(size):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    lines = []
    for row, pixels in enumerate((16, 24, 32)):
        text = f"截图冻结后拖选文字，不会点击原窗口。Test copy 123 ABC {pixels}"
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", pixels)
        draw.text((40, 35+row*90), text, fill="#172333", font=font)
        lines.append(text)
    return image, "\n".join(lines)


def run(runtime, output):
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for label, size in (("normal", (1200, 420)), ("4k", (3840, 2160))):
        image, reference = sample(size)
        path = output / (label + ".png")
        image.save(path)
        data = text_selection.recognize(QImage(str(path)), runtime=runtime)
        # A substring check is not a full accuracy benchmark.
        reports.append({key: value for key, value in data.items() if key != "glyphs"})
        reports[-1].update(sample=label, glyph_count=len(data["glyphs"]), reference=reference)
    (output / "benchmark.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.runtime, args.output)
