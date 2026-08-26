#!/usr/bin/env python3
"""Verify Mouser update metadata for the selected platform."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.update_installer import platform_key, verify_update_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--platform-key", default=platform_key())
    args = parser.parse_args()

    data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    manifest = verify_update_manifest(data, platform_key=args.platform_key)
    print(
        f"verified {manifest.version} build {manifest.build_number} "
        f"for {args.platform_key}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
