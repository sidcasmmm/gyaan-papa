"""Create the 3D Gyaan Papa character ONCE (≈ 5 AI images, about ₹20–40 total).

    GEMINI_API_KEY=... python tools/make_papa.py            # or run the "Create Papa" GitHub workflow
    python tools/make_papa.py --extra "wearing a red pagdi"   # tweak the look

Writes assets/papa/{base,talk1,talk2,talk3,blink}.png (transparent cut-outs that line up
pixel-perfectly) plus assets/papa/preview.png so you can check him. Not happy? Run again.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "assets" / "papa"

CHARACTER = (
    "A 3D animated cartoon character in a modern Pixar/Disney style render: 'Gyaan Papa', "
    "a cheerful Indian man in his late 50s. Warm brown skin, salt-and-pepper side hair with a "
    "receding hairline, a big thick black-and-grey handlebar moustache with curled ends, round "
    "black-rimmed glasses, friendly expressive eyes, slight smile. He wears a mustard-yellow Nehru "
    "jacket with brown buttons over a white kurta, a small pink pocket square, and holds a small "
    "glass of chai in one hand at chest height. Waist-up portrait, facing the camera, slightly "
    "turned three-quarters, whole head and both shoulders fully inside the frame with empty space "
    "around him. Soft studio lighting, high detail, smooth subsurface skin. "
    "Background: completely flat solid pure green (#00FF00) chroma-key screen, no shadows, "
    "no floor, nothing else in the image. No text."
)

EDITS = {
    "talk1": "mouth slightly open, as if in the middle of saying a word",
    "talk2": "mouth clearly open, speaking an 'aa' sound, teeth visible",
    "talk3": "mouth wide open, laughing while talking",
    "blink": "both eyes fully closed (mid-blink), mouth closed",
}
EDIT_TEMPLATE = ("Edit this image. Keep EVERYTHING identical — same character, same pose, same "
                 "framing, same size, same position, same lighting, same green background. "
                 "The ONLY change: {change}.")


# ── image processing ───────────────────────────────────────────────────
def align(variant: Image.Image, base: Image.Image, search: int = 24) -> Image.Image:
    """Find the small shift that best lines up `variant` with `base`."""
    variant = variant.convert("RGB").resize(base.size, Image.LANCZOS)
    k = 4
    small = (base.width // k, base.height // k)
    a = np.asarray(base.convert("L").resize(small), dtype=np.float32)
    b = np.asarray(variant.convert("L").resize(small), dtype=np.float32)
    best, best_err = (0, 0), float("inf")
    s = search // k
    for dy in range(-s, s + 1):
        for dx in range(-s, s + 1):
            shifted = np.roll(np.roll(b, dy, 0), dx, 1)
            err = np.mean(np.abs(a[s:-s, s:-s] - shifted[s:-s, s:-s]))
            if err < best_err:
                best, best_err = (dx, dy), err
    dx, dy = best[0] * k, best[1] * k
    return Image.fromarray(np.roll(np.roll(np.asarray(variant), dy, 0), dx, 1))


def changed_region_mask(base: Image.Image, variant: Image.Image) -> Image.Image:
    """Feathered mask around the face area that changed (mouth or eyes)."""
    a = np.asarray(base.convert("RGB"), dtype=np.int16)
    b = np.asarray(variant.convert("RGB"), dtype=np.int16)
    diff = np.abs(a - b).sum(axis=2)
    h, w = diff.shape
    diff[int(h * 0.62):, :] = 0                    # ignore body / hands: only the head changes
    m = Image.fromarray(np.uint8(np.clip(diff * 2, 0, 255))).filter(ImageFilter.GaussianBlur(6))
    arr = np.asarray(m) > 40
    ys, xs = np.nonzero(arr)
    mask = Image.new("L", base.size, 0)
    if len(xs) < 50:
        return mask
    # keep the dense core (drop scattered noise) and pad it
    x0, x1 = np.percentile(xs, [3, 97]).astype(int)
    y0, y1 = np.percentile(ys, [3, 97]).astype(int)
    pad = int(0.04 * w)
    from PIL import ImageDraw
    ImageDraw.Draw(mask).ellipse([x0 - pad, y0 - pad, x1 + pad, y1 + pad], fill=255)
    return mask.filter(ImageFilter.GaussianBlur(pad // 2 + 2))


def chroma_key(img: Image.Image) -> Image.Image:
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    greenness = g - np.maximum(r, b)
    alpha = np.clip(1 - (greenness - 25) / 55, 0, 1)
    # despill: pull green down on edge pixels
    spill = np.clip(greenness, 0, None) * (alpha < 1)
    g2 = g - spill * 0.85
    rgba = np.dstack([r, np.minimum(g, np.maximum(g2, np.maximum(r, b))), b, alpha * 255])
    out = Image.fromarray(np.uint8(np.clip(rgba, 0, 255)), "RGBA")
    a_ch = out.getchannel("A").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1))
    out.putalpha(a_ch)
    return out


def build(base_rgb: Image.Image, variants_rgb: dict[str, Image.Image]) -> dict[str, Image.Image]:
    """Align variants, transplant only the changed face region, cut out the green."""
    frames = {"base": base_rgb.convert("RGB")}
    for name, v in variants_rgb.items():
        v = align(v, frames["base"])
        mask = changed_region_mask(frames["base"], v)
        frames[name] = Image.composite(v, frames["base"], mask)
    cut = {k: chroma_key(v) for k, v in frames.items()}
    bbox = cut["base"].getchannel("A").point(lambda p: 255 if p > 30 else 0).getbbox()
    if bbox:
        cut = {k: v.crop(bbox) for k, v in cut.items()}
    return cut


def preview(frames: dict[str, Image.Image], path: Path):
    order = ["base", "talk1", "talk2", "talk3", "blink"]
    h = 520
    tiles = [frames[k].resize((int(frames[k].width * h / frames[k].height), h)) for k in order]
    sheet = Image.new("RGB", (sum(t.width for t in tiles) + 20 * 6, h + 40), (24, 30, 52))
    x = 20
    for t in tiles:
        sheet.paste(t, (x, 20), t)
        x += t.width + 20
    sheet.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", default="", help="extra description, e.g. 'wearing a turban'")
    ap.add_argument("--model", default="gemini-2.5-flash-image")
    args = ap.parse_args()
    from pipeline.images import gemini_image

    OUT.mkdir(parents=True, exist_ok=True)
    print("Generating Papa…")
    base = gemini_image(CHARACTER + (" " + args.extra if args.extra else ""), args.model, aspect="3:4")
    base.convert("RGB").save(OUT / "raw_base.png")
    variants = {}
    for name, change in EDITS.items():
        print(f"  variant: {name}")
        variants[name] = gemini_image(EDIT_TEMPLATE.format(change=change), args.model,
                                      aspect="3:4", input_images=[base])
    frames = build(base, variants)
    for k, v in frames.items():
        v.save(OUT / f"{k}.png")
    preview(frames, OUT / "preview.png")
    print(f"✅ Saved to {OUT.relative_to(ROOT)} — open preview.png to check him.")


if __name__ == "__main__":
    main()
