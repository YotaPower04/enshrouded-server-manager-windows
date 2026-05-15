"""Generate flat/modern .ico files for the Enshrouded Server Manager.

Produces:
  install.ico  - blue rounded square, white download-into-tray glyph
  manager.ico  - red rounded square, white capital E (server stopped)
  running.ico  - green rounded square, white capital E (server running)
"""
from pathlib import Path
from PIL import Image, ImageDraw

SIZES = [256, 128, 64, 48, 32, 16]
FG = (255, 255, 255, 255)

# Anti-aliased shapes look bad at 16/32 if drawn at native size. Draw everything
# at 256 then resize down with LANCZOS — Windows picks the best fit at runtime.
BASE = 256


def _draw_E(draw: ImageDraw.ImageDraw, size: int):
    m = size * 0.28
    top, bot = m, size - m
    left = m
    right = size - m * 0.85
    stroke = max(2, int(size * 0.11))
    half = stroke / 2
    mid_y = (top + bot) / 2
    # vertical bar
    draw.rectangle((left, top, left + stroke, bot), fill=FG)
    # top horizontal
    draw.rectangle((left, top, right, top + stroke), fill=FG)
    # middle horizontal (slightly shorter, gives the classic E look)
    draw.rectangle(
        (left, mid_y - half, right - (right - left) * 0.18, mid_y + half),
        fill=FG,
    )
    # bottom horizontal
    draw.rectangle((left, bot - stroke, right, bot), fill=FG)


def _draw_install(draw: ImageDraw.ImageDraw, size: int):
    cx = size / 2
    shaft_w = max(2, int(size * 0.14))
    shaft_top = size * 0.22
    shaft_bot = size * 0.55
    # arrow shaft
    draw.rectangle(
        (cx - shaft_w / 2, shaft_top, cx + shaft_w / 2, shaft_bot),
        fill=FG,
    )
    # arrowhead
    head_w = size * 0.40
    head_h = size * 0.18
    draw.polygon(
        [
            (cx - head_w / 2, shaft_bot),
            (cx + head_w / 2, shaft_bot),
            (cx, shaft_bot + head_h),
        ],
        fill=FG,
    )
    # tray / landing surface
    tray_y = size * 0.80
    tray_thick = max(2, int(size * 0.09))
    tray_w = size * 0.58
    draw.rectangle(
        (cx - tray_w / 2, tray_y, cx + tray_w / 2, tray_y + tray_thick),
        fill=FG,
    )


def _render(bg_rgb: tuple[int, int, int], glyph) -> Image.Image:
    img = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(BASE * 0.20)
    draw.rounded_rectangle(
        (0, 0, BASE - 1, BASE - 1),
        radius=radius,
        fill=(*bg_rgb, 255),
    )
    glyph(draw, BASE)
    return img


def write_ico(bg_rgb: tuple[int, int, int], glyph, out_path: Path):
    base_img = _render(bg_rgb, glyph)
    frames = []
    for s in SIZES:
        if s == BASE:
            frames.append(base_img)
        else:
            frames.append(base_img.resize((s, s), Image.Resampling.LANCZOS))
    # Pillow's ICO writer wants sizes via the .save() call.
    frames[0].save(
        out_path,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
    )
    print(f"wrote {out_path.name} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "assets"
    out.mkdir(exist_ok=True)
    write_ico((0x25, 0x63, 0xeb), _draw_install, out / "install.ico")
    write_ico((0xc0, 0x39, 0x2b), _draw_E,        out / "manager.ico")
    write_ico((0x27, 0xae, 0x60), _draw_E,        out / "running.ico")
