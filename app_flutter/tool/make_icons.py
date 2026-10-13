"""Render the SentinelAI brand mark into the app icons (Windows .ico, web favicon and PWA icons).

The mark is the same drawing as SentinelMark in lib/core/brand.dart: three rounded bars, the middle one
(accent) shifted right. Icons put it on a dark rounded tile so it reads on light and dark taskbars.

usage (from app_flutter/):  python tool/make_icons.py      (needs Pillow)
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
TILE = (14, 22, 36)          # dark tile, a step above the app background #070B12
EDGE = (40, 54, 78)          # hairline around the tile
INK = (232, 238, 248)        # AppColors.text (dark palette)
ACCENT = (75, 155, 255)      # AppColors.blue (dark palette)
SS = 4                       # supersampling factor


def mark(draw: ImageDraw.ImageDraw, x: float, y: float, s: float) -> None:
    """SentinelMark at (x, y) with side s."""
    bar = s * 0.2
    gap = (s - 3 * bar) / 2
    for top, left, width, colour in ((0, 0, 0.78, INK), (bar + gap, 0.22, 0.78, ACCENT), (2 * (bar + gap), 0, 0.6, INK)):
        x0, y0 = x + left * s, y + top
        draw.rounded_rectangle((x0, y0, x0 + width * s, y0 + bar), radius=bar / 2, fill=colour)


def render(size: int, *, full_bleed: bool = False, mark_share: float = 0.56) -> Image.Image:
    """Square icon. full_bleed: tile fills the canvas (maskable icons); otherwise a rounded tile."""
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if full_bleed:
        d.rectangle((0, 0, n, n), fill=TILE)
    else:
        pad = n * 0.04
        radius = n * 0.22
        d.rounded_rectangle((pad, pad, n - pad, n - pad), radius=radius, fill=TILE,
                            outline=EDGE, width=max(1, round(n * 0.012)))
    s = n * mark_share
    mark(d, (n - s) / 2, (n - s) / 2, s)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    web = ROOT / "web"
    render(32, mark_share=0.62).save(web / "favicon.png")
    render(192).save(web / "icons" / "Icon-192.png")
    render(512).save(web / "icons" / "Icon-512.png")
    # Maskable icons are cropped to a circle by some launchers: keep the mark inside the 80% safe zone.
    render(192, full_bleed=True, mark_share=0.46).save(web / "icons" / "Icon-maskable-192.png")
    render(512, full_bleed=True, mark_share=0.46).save(web / "icons" / "Icon-maskable-512.png")
    # Windows: one .ico with every size the shell asks for; small sizes get a slightly larger mark.
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [render(s, mark_share=0.64 if s <= 24 else 0.58 if s <= 48 else 0.56) for s in sizes]
    ico = ROOT / "windows" / "runner" / "resources" / "app_icon.ico"
    frames[-1].save(ico, format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    print("icons written")


if __name__ == "__main__":
    main()
