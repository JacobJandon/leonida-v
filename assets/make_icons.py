"""Cut the chosen logo (02 / Sunset Emblem) out of `logo-concepts.png` and write every icon size Leonida uses.

Run from the repo root:  python assets/make_icons.py   (needs Pillow; dev-only, not a runtime dependency)

Outputs
  assets/leonida-logo.png        1024 px, transparent background (README, releases)
  assets/leonida-banner.png      README header: logo + wordmark on the dark brand background
  leonida/gui/assets/leonida.png 256 px window icon (bundled with the app)
  leonida/gui/assets/leonida.ico 16-256 px Windows icon (exe, shortcuts)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "logo-concepts.png"
# Emblem 02 sits in the top-right quarter of the 2730x1536 concept sheet (measured on the sheet).
CROP = (1758, 92, 2338, 672)
BG_LEVEL = 22        # the sheet's background is ~ (13, 13, 18): everything this dark becomes transparent
SOFT = 70            # brightness range over which the glow fades in


def cut_emblem() -> Image.Image:
    sheet = Image.open(SRC).convert("RGB")
    sw, sh = sheet.size
    sx, sy = sw / 2730, sh / 1536  # in case the sheet is re-exported at another size
    box = tuple(round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate(CROP))
    rgb = sheet.crop(box)
    out = Image.new("RGBA", rgb.size)
    px_in, px_out = rgb.load(), out.load()
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = px_in[x, y]
            m = max(r, g, b)
            a = max(0.0, min(1.0, (m - BG_LEVEL) / SOFT))
            if a <= 0:
                px_out[x, y] = (0, 0, 0, 0)
                continue
            # remove the dark background from semi-transparent glow pixels (un-premultiply against it)
            bg = 13
            px_out[x, y] = tuple(max(0, min(255, round((c - bg * (1 - a)) / a))) for c in (r, g, b)) + (round(a * 255),)
    # The emblem's dark inner stripes are as dark as a glow edge: make everything inside the outline opaque.
    solid = rgb.convert("L").point(lambda v: 255 if v > 45 else 0)
    solid = solid.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))  # close small gaps
    holes = solid.copy()
    ImageDraw.floodfill(holes, (0, 0), 128)  # outside = 128; anything still 0 is an enclosed hole
    filled = holes.point(lambda v: 0 if v == 128 else 255).filter(ImageFilter.MinFilter(3))
    fp, op = filled.load(), out.load()
    for y in range(rgb.height):
        for x in range(rgb.width):
            if fp[x, y]:
                op[x, y] = px_in[x, y] + (255,)
    bbox = out.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    out = out.crop(bbox)
    side = max(out.size)
    square = Image.new("RGBA", (side, side))
    square.paste(out, ((side - out.width) // 2, (side - out.height) // 2))
    return square


def banner(logo: Image.Image) -> Image.Image:
    w, h = 1700, 480
    img = Image.new("RGBA", (w, h), (13, 13, 18, 255))
    glow = Image.new("RGBA", (w, h))
    ImageDraw.Draw(glow).ellipse((60, 20, 500, 460), fill=(255, 80, 140, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))
    img.alpha_composite(logo.resize((400, 400), Image.LANCZOS), (80, 40))
    draw = ImageDraw.Draw(img)
    try:
        title = ImageFont.truetype("bahnschrift.ttf", 150)
        sub = ImageFont.truetype("bahnschrift.ttf", 44)
    except OSError:
        title = sub = ImageFont.load_default()
    # sunset gradient wordmark
    text = "LEONIDA V"
    tw = draw.textbbox((0, 0), text, font=title)
    mask = Image.new("L", (w, h))
    ImageDraw.Draw(mask).text((540, 120), text, font=title, fill=255)
    grad = Image.new("RGBA", (w, h))
    gd = ImageDraw.Draw(grad)
    x0, x1 = 540, 540 + tw[2]
    for x in range(x0, x1 + 1):
        t = (x - x0) / max(1, x1 - x0)
        col = (round(255 - 120 * t), round(170 - 120 * t), round(80 + 175 * t), 255)  # gold -> pink -> violet
        gd.line([(x, 0), (x, h)], fill=col)
    img.paste(grad, (0, 0), mask)
    draw.text((546, 300), "GTA VI-style GTA V Enhanced, one safe step at a time", font=sub, fill=(205, 195, 230, 255))
    return img


def main() -> None:
    logo = cut_emblem()
    big = logo.resize((1024, 1024), Image.LANCZOS)
    big.save(ROOT / "assets" / "leonida-logo.png", optimize=True)
    banner(big).convert("RGB").save(ROOT / "assets" / "leonida-banner.png", optimize=True)
    gui = ROOT / "leonida" / "gui" / "assets"
    gui.mkdir(parents=True, exist_ok=True)
    big.resize((256, 256), Image.LANCZOS).save(gui / "leonida.png", optimize=True)
    big.save(gui / "leonida.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", ", ".join(str(p.relative_to(ROOT)) for p in (
        ROOT / "assets" / "leonida-logo.png", ROOT / "assets" / "leonida-banner.png", gui / "leonida.png", gui / "leonida.ico")))


if __name__ == "__main__":
    main()
