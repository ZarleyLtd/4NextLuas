"""Build Alexa store icons from 4NextLuasIcon.jpg.

Small: 108x108 PNG, 16px padding. Large: 512x512 PNG, 75px padding.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "4NextLuasIcon.jpg"
OUT_DIR = ROOT / "skill-package" / "assets" / "images"
DOCS_DIR = ROOT / "docs" / "icons"


def _l1(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def crop_icon(im: Image.Image, threshold: int = 62) -> Image.Image:
    rgb = im.convert("RGB")
    w, h = rgb.size
    bg = rgb.getpixel((0, 0))
    pix = rgb.load()
    minx, miny, maxx, maxy = w, h, 0, 0
    for y in range(h):
        for x in range(w):
            if _l1(pix[x, y], bg) > threshold:
                if x < minx:
                    minx = x
                if y < miny:
                    miny = y
                if x > maxx:
                    maxx = x
                if y > maxy:
                    maxy = y
    side = max(maxx - minx + 1, maxy - miny + 1)
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    left = int(round(cx - side / 2))
    top = int(round(cy - side / 2))
    left = max(0, min(left, w - side))
    top = max(0, min(top, h - side))
    return rgb.crop((left, top, left + side, top + side)).convert("RGBA")


def fit_on_canvas(icon: Image.Image, size: int, padding: int) -> Image.Image:
    inner = size - 2 * padding
    fitted = icon.resize((inner, inner), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(fitted, (padding, padding), fitted)
    return canvas


def main() -> None:
    src = Image.open(SRC)
    icon = crop_icon(src)
    specs = {
        "en-GB_smallIcon.png": (108, 16),
        "en-GB_largeIcon.png": (512, 75),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for name, (size, pad) in specs.items():
        out = fit_on_canvas(icon, size, pad)
        for dest in (OUT_DIR / name, DOCS_DIR / name):
            out.save(dest, "PNG", optimize=True)
            print(f"wrote {dest} {out.size} {out.mode}")


if __name__ == "__main__":
    main()
