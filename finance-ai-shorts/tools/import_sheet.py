"""Turn the shared character sheet into Papa's animation frames.

    python tools/import_sheet.py path/to/character_sheet.png

Cuts the big arms-crossed pose (waist-up) out of the grey background, upscales it,
and paints talking-mouth and blink frames so he can lip-sync in the video.
Writes assets/papa/{base,talk1,talk2,talk3,blink}.png + preview.png.

The coordinates below match the 1024×1536 sheet (big pose on the left).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "papa"

CROP = (20, 0, 360, 610)            # waist-up part of the big pose, in sheet pixels
SCALE = 3                           # upscale before drawing so details stay smooth
MOUTH = (186, 201, 56)              # centre x, centre y, width (sheet pixels)
EYES = [(133, 134, 168, 158), (197, 127, 231, 154)]   # boxes around each eye
LID_SAMPLE = [(150, 131), (214, 124)]                 # skin just above each eye


def cutout(sheet: Image.Image) -> Image.Image:
    rgb = sheet.convert("RGB").crop(CROP)
    a = np.asarray(rgb, dtype=np.float32) / 255
    mx, mn = a.max(2), a.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    bgish = (sat < 0.17) & (mx > 0.55)
    mask = Image.fromarray(np.uint8(bgish) * 255, "L").copy()   # copy: floodfill needs its own buffer
    w, h = mask.size
    # background = grey area connected to the left/top/right edges
    for x in range(0, w, 4):
        for y in (0,):
            if mask.getpixel((x, y)) == 255:
                ImageDraw.floodfill(mask, (x, y), 128)
    for y in range(0, h, 4):
        for x in (0, w - 1):
            if mask.getpixel((x, y)) == 255:
                ImageDraw.floodfill(mask, (x, y), 128)
    bg = np.asarray(mask) == 128
    alpha = Image.fromarray(np.uint8(~bg) * 255, "L")
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    big = rgb.resize((w * SCALE, h * SCALE), Image.LANCZOS)
    big.putalpha(alpha.resize(big.size, Image.LANCZOS))
    # fade the bottom edge so the cut at the waist looks clean
    fade = Image.new("L", big.size, 255)
    fd = ImageDraw.Draw(fade)
    for i in range(80):
        fd.line([(0, big.height - 1 - i), (big.width, big.height - 1 - i)], fill=int(255 * i / 80))
    big.putalpha(Image.fromarray(np.minimum(np.asarray(big.getchannel("A")), np.asarray(fade))))
    return big


def _p(x, y):
    return ((x - CROP[0]) * SCALE, (y - CROP[1]) * SCALE)


def moustache_mask(base: Image.Image) -> Image.Image:
    """Dark moustache pixels, so the mouth is drawn *behind* the moustache."""
    cx, cy, mw = MOUTH
    a = np.asarray(base.convert("RGB"), dtype=np.int16)
    lum = a.mean(2)
    m = np.zeros(lum.shape, bool)
    x0, y0 = _p(cx - mw, cy - 22)
    x1, y1 = _p(cx + mw, cy + 1)
    m[int(y0):int(y1), int(x0):int(x1)] = lum[int(y0):int(y1), int(x0):int(x1)] < 85
    return Image.fromarray(np.uint8(m) * 255).filter(ImageFilter.MaxFilter(3)).filter(
        ImageFilter.GaussianBlur(1.2))


def talk(base: Image.Image, level: int) -> Image.Image:
    cx, cy, mw = MOUTH
    X, Y = _p(cx, cy)
    w = mw * SCALE * (0.46 + 0.05 * level)
    h = mw * SCALE * (0.10 + 0.10 * level)
    ss = 3
    layer = Image.new("RGBA", (base.width * ss, base.height * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def S(*v):
        return [x * ss for x in v]
    top = Y - 10
    # soft lower-lip shading, then the mouth opening, teeth and tongue
    d.ellipse(S(X - w / 2 - 8, top - h * 0.1, X + w / 2 + 8, top + h + 10), fill=(196, 104, 74, 150))
    d.ellipse(S(X - w / 2, top - h * 0.15, X + w / 2, top + h), fill=(92, 34, 32, 255))
    d.ellipse(S(X - w * 0.36, top - h * 0.05, X + w * 0.36, top + h * 0.95), fill=(70, 22, 24, 255))
    d.chord(S(X - w * 0.40, top - h * 0.30, X + w * 0.40, top + h * 0.30), 0, 180,
            fill=(238, 232, 226, 255))
    if level >= 2:
        d.ellipse(S(X - w * 0.26, top + h * 0.58, X + w * 0.26, top + h * 1.0), fill=(190, 88, 92, 255))
    layer = layer.resize(base.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.6))
    out = base.copy()
    out.alpha_composite(layer)
    return Image.composite(base, out, moustache_mask(base))   # moustache stays on top


def blink(base: Image.Image, sheet: Image.Image) -> Image.Image:
    """Close the eyes: cover each eye with a soft skin-tone eyelid + a lash line."""
    a = np.asarray(base.convert("RGB"), dtype=np.float32)
    out = base.copy()
    for (x0, y0, x1, y1) in EYES:
        a0, b0 = [int(v) for v in _p(x0 - 4, y0 - 4)]
        a1, b1 = [int(v) for v in _p(x1 + 4, y1 + 4)]

        def skin(r0, r1):
            band = a[r0:r1, a0:a1].reshape(-1, 3)
            band = band[band.mean(1) > 120]
            return np.median(band, 0) if len(band) else np.array([220, 150, 110])
        below = skin(b1 + 4, b1 + 26)
        above = skin(max(0, b0 - 8), b0 + 4)
        w, h = a1 - a0, b1 - b0
        grad = np.zeros((h, w, 3), np.float32)
        for y in range(h):
            t = y / max(h - 1, 1)
            grad[y] = above * (1 - t) * 0.85 + below * (0.15 + 0.85 * t)
        grad *= 0.97                                   # lids are a touch darker than cheeks
        lid = Image.fromarray(np.uint8(np.clip(grad, 0, 255)), "RGB").convert("RGBA")
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).ellipse([3, 3, w - 3, h - 3], fill=255)
        lid.putalpha(mask.filter(ImageFilter.GaussianBlur(6)))
        ld = ImageDraw.Draw(lid)
        mid = h * 0.62
        ld.arc([w * 0.12, mid - h * 0.30, w * 0.88, mid + h * 0.10], 25, 155,
               fill=(32, 18, 14, 255), width=5)
        out.alpha_composite(lid, (a0, b0))
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python tools/import_sheet.py character_sheet.png")
    sheet = Image.open(sys.argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    base = cutout(sheet)
    frames = {"base": base, "talk1": talk(base, 1), "talk2": talk(base, 2),
              "talk3": talk(base, 3), "blink": blink(base, sheet)}
    for k, v in frames.items():
        v.save(OUT / f"{k}.png")
    from tools.make_papa import preview
    preview(frames, OUT / "preview.png")
    print(f"✅ Saved Papa frames to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
