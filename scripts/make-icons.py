# make-icons.py — draw the cactus saguaro icon and write every PNG size.
#
# Responsibilities:
# - Draw a saguaro on the page's dark background at 1024px (assets/icon-1024.png).
# - Downscale it into src/cactus/www_static/ (192, 512, maskable 512, apple 180).
# - Run once, commit the PNGs: `uv run --with pillow python scripts/make-icons.py`.

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BG = (20, 22, 26)  # #14161a, the page background
GREEN = (106, 224, 168)  # #6ae0a8, the live badge green
S = 1024


def draw(scale: float) -> Image.Image:
    """Saguaro scaled about the centre; scale < 1 leaves a maskable safe zone."""
    img = Image.new("RGB", (S, S), BG)
    d = ImageDraw.Draw(img)

    def p(v: float) -> int:
        return round(S / 2 + (v - S / 2) * scale)

    def rr(x0, y0, x1, y1, r):
        d.rounded_rectangle((p(x0), p(y0), p(x1), p(y1)), radius=round(r * scale), fill=GREEN)

    rr(432, 180, 592, 860, 80)  # trunk
    rr(250, 400, 432, 470, 35)  # left arm, horizontal
    rr(215, 270, 285, 470, 35)  # left arm, up
    rr(592, 500, 774, 570, 35)  # right arm, horizontal
    rr(739, 360, 809, 570, 35)  # right arm, up
    rr(300, 840, 724, 890, 25)  # ground
    return img


def main() -> None:
    (ROOT / "assets").mkdir(exist_ok=True)
    static = ROOT / "src" / "cactus" / "www_static"
    static.mkdir(parents=True, exist_ok=True)
    full = draw(1.0)
    full.save(ROOT / "assets" / "icon-1024.png")
    for name, size, img in (
        ("icon-192.png", 192, full),
        ("icon-512.png", 512, full),
        ("icon-maskable-512.png", 512, draw(0.7)),
        ("apple-touch-icon.png", 180, full),
    ):
        img.resize((size, size), Image.LANCZOS).save(static / name)


if __name__ == "__main__":
    main()
