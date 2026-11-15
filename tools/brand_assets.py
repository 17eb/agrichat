# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==11.3.0"]
# ///
"""Derive the web logo assets from brand/agrichat-logo.png.

Run: uv run tools/brand_assets.py

Outputs in web/static/img/:
- logo.png: full lockup (speech bubble, sprout, carrot, lettering), trimmed.
- logo-icon.png: mark without the lettering, carrot recentred; for small sizes.
- favicon.ico, favicon-32.png: browser tab icons.
- apple-touch-icon.png: 180 px home-screen icon on an opaque background.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "brand" / "agrichat-logo.png"
OUT = ROOT / "web" / "static" / "img"

BUBBLE = (157, 207, 107, 255)
# Regions measured on the 2000 x 2000 source.
LETTERING = (640, 1110, 1360, 1250)
CARROT = (740, 525, 1230, 1110)
CARROT_SHIFT = 130  # moves the carrot to the bubble's vertical centre
TOUCH_BG = (246, 249, 243, 255)  # --surface, light scheme


def is_carrot(pixel: tuple[int, int, int, int]) -> bool:
    r, g, b, a = pixel
    if a < 200:
        return False
    if abs(r - BUBBLE[0]) + abs(g - BUBBLE[1]) + abs(b - BUBBLE[2]) < 40:
        return False
    sprout = r < 190 and g > 190 and b < 90
    return not sprout


def icon_mark(source: Image.Image) -> Image.Image:
    mark = source.copy()
    draw = ImageDraw.Draw(mark)
    draw.rectangle(LETTERING, fill=BUBBLE)

    region = mark.crop(CARROT)
    carrot = Image.new("RGBA", region.size, (0, 0, 0, 0))
    src, dst = region.load(), carrot.load()
    for y in range(region.height):
        for x in range(region.width):
            if is_carrot(src[x, y]):
                dst[x, y] = src[x, y]
                src[x, y] = BUBBLE
    mark.paste(region, CARROT[:2])
    mark.alpha_composite(carrot, (CARROT[0], CARROT[1] + CARROT_SHIFT))
    return mark


def trimmed(image: Image.Image, pad: int) -> Image.Image:
    box = image.getchannel("A").getbbox()
    crop = image.crop(box)
    side = max(crop.size) + 2 * pad
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return canvas


def resized(image: Image.Image, side: int) -> Image.Image:
    return image.resize((side, side), Image.Resampling.LANCZOS)


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    OUT.mkdir(parents=True, exist_ok=True)

    lockup = source.crop(source.getchannel("A").getbbox())
    height = 320
    width = round(lockup.width * height / lockup.height)
    lockup.resize((width, height), Image.Resampling.LANCZOS).save(OUT / "logo.png", optimize=True)

    mark = trimmed(icon_mark(source), pad=24)
    resized(mark, 192).save(OUT / "logo-icon.png", optimize=True)
    resized(mark, 32).save(OUT / "favicon-32.png", optimize=True)
    resized(mark, 256).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    touch = Image.new("RGBA", (180, 180), TOUCH_BG)
    touch.alpha_composite(resized(mark, 148), (16, 16))
    touch.convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)


if __name__ == "__main__":
    main()
