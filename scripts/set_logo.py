#!/usr/bin/env python3
"""Install the Atreides crest image used by the web UI.

The page prefers `src/api/static/logo.png` and falls back to an inline SVG crest
when it is absent, so the UI never depends on an asset being present — but the
real mark should be used whenever we have it.

    python scripts/set_logo.py ~/Downloads/atreides_logo.png

Any format Pillow can read is accepted and converted to PNG. The image is
squared (centred, transparent padding) and capped at 512px, because the crest is
rendered at 84 CSS pixels and shipping a 1.2 MB original in a repository would be
careless.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "api" / "static"
TARGET = STATIC / "logo.png"
MAX_EDGE = 512


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path, help="path to the logo image")
    parser.add_argument("--raw", action="store_true",
                        help="copy verbatim without squaring or resizing")
    args = parser.parse_args()

    source = args.image.expanduser()
    if not source.is_file():
        print(f"not found: {source}", file=sys.stderr)
        return 2

    STATIC.mkdir(parents=True, exist_ok=True)

    if args.raw:
        shutil.copyfile(source, TARGET)
        print(f"copied verbatim → {TARGET}  ({TARGET.stat().st_size / 1024:.0f} KB)")
        return 0

    try:
        from PIL import Image
    except ImportError:
        # Pillow is already a dependency for the OCR path, but a verbatim copy is
        # a perfectly good outcome if it is somehow missing.
        shutil.copyfile(source, TARGET)
        print(f"Pillow unavailable — copied verbatim → {TARGET}")
        return 0

    with Image.open(source) as image:
        image = image.convert("RGBA")
        width, height = image.size

        # Square it on a transparent canvas so the circular crest is not cropped.
        edge = max(width, height)
        square = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
        square.paste(image, ((edge - width) // 2, (edge - height) // 2))

        if edge > MAX_EDGE:
            square = square.resize((MAX_EDGE, MAX_EDGE), Image.LANCZOS)

        square.save(TARGET, "PNG", optimize=True)

    print(f"installed → {TARGET}")
    print(f"  source {width}x{height} → {square.size[0]}x{square.size[1]}, "
          f"{TARGET.stat().st_size / 1024:.0f} KB")
    print("  reload the UI; it picks up logo.png automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
