"""Build independent, pinned model ZIPs; never include personal settings."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.speech_models import CATALOG, create_pack


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--model", choices=["all", *CATALOG], default="all")
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for pack_id in CATALOG if args.model == "all" else [args.model]:
        archive = args.destination / f"Mouser-model-{pack_id}-v1.zip"
        create_pack(pack_id, ROOT / "speech_models", archive)
        print(f"MODEL_PACK_READY={archive.name}; bytes={archive.stat().st_size}")


if __name__ == "__main__":
    main()
