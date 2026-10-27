"""Create Papa's lip-sync mouth shapes and acting poses ONCE (≈ 23 Gemini image edits, ~₹70).

    GEMINI_API_KEY=... python tools/make_papa_v2.py

Starts from assets/papa/base.png (your character) and writes
    assets/papa/v2/<pose>/{rest,aa,ee,oo,mbp,blink}.png   (same canvas size for every image)
    assets/papa/v2/poses.json
    assets/papa/v2/preview.png
Poses: default (arms crossed), explain (open hands), thumbs (thumbs up), think (hand on chin).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.images import gemini_image                      # noqa: E402
from tools.make_papa import align, chroma_key                  # noqa: E402

SRC = ROOT / "assets" / "papa" / "base.png"
OUT = ROOT / "assets" / "papa" / "v2"
GREEN = (0, 255, 0)
MODELS = ["gemini-3.1-flash-lite-image", "gemini-nano-banana-2.1", "gemini-2.5-flash-image"]

KEEP = ("Edit this image. Keep EVERYTHING else identical — same character, same face, same "
        "clothes, same art style, same size and position in the frame, same lighting, and the "
        "same flat pure green (#00FF00) background. No text.")

POSES = {
    "explain": "Change ONLY his arms and hands: he now holds both hands open in front of his "
               "chest, palms up, like he is explaining something. Body, head and face stay put; "
               "mouth closed in a friendly smile; hands fully inside the frame.",
    "thumbs": "Change ONLY his arms and hands: he now gives a big thumbs up with his right hand "
              "near his shoulder, other arm relaxed. Body, head and face stay put; cheerful "
              "closed-mouth smile; hand fully inside the frame.",
    "think": "Change ONLY his arms, hand and eyes: he now rests one hand on his chin, thinking, "
             "eyes looking slightly up. Body and head stay put; mouth closed; hand fully inside "
             "the frame.",
}

MOUTHS = {
    "aa": "Change ONLY his mouth: open wide as if saying 'aa', jaw dropped, top teeth and "
          "tongue slightly visible under the moustache.",
    "ee": "Change ONLY his mouth: wide stretched smile as if saying 'ee', teeth together and "
          "visible, mouth slightly open.",
    "oo": "Change ONLY his mouth: small rounded open lips as if saying 'oo'.",
    "mbp": "Change ONLY his mouth: lips pressed firmly together, as if saying 'm'.",
    "blink": "Change ONLY his eyes: both eyes fully closed (mid-blink). Mouth unchanged.",
}


def edit(img: Image.Image, instruction: str) -> Image.Image:
    last = None
    for model in MODELS:
        for attempt in range(2):
            try:
                return gemini_image(f"{KEEP} {instruction}", model, aspect="9:16",
                                    input_images=[img]).convert("RGB")
            except Exception as e:                      # try again / next model
                last = e
                print(f"    retry ({model}): {str(e)[:120]}")
                time.sleep(5)
    raise RuntimeError(f"edit failed: {last}")


def head_box(img: Image.Image) -> tuple[int, int, int, int]:
    """Rough box around the head (top 34% of the character) for mouth/eye transplants."""
    a = np.asarray(chroma_key(img).getchannel("A")) > 40
    ys, xs = np.nonzero(a)
    top, bottom = ys.min(), ys.max()
    h = bottom - top
    band = a[top:top + int(h * 0.34)]
    bys, bxs = np.nonzero(band)
    return int(bxs.min()), int(top), int(bxs.max()), int(top + h * 0.34)


def face_patch(base: Image.Image, variant: Image.Image) -> Image.Image:
    """Take only the changed pixels inside the head box from `variant`, rest from `base`."""
    variant = align(variant, base)
    a = np.asarray(base, dtype=np.int16)
    b = np.asarray(variant, dtype=np.int16)
    diff = np.abs(a - b).sum(axis=2)
    x0, y0, x1, y1 = head_box(base)
    m = np.zeros_like(diff, dtype=np.uint8)
    m[y0:y1, x0:x1] = (diff[y0:y1, x0:x1] > 45) * 255
    mask = Image.fromarray(m).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(5))
    return Image.composite(variant, base, mask)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    papa = Image.open(SRC).convert("RGBA")
    W, H = 768, 1365
    k = min(W * 0.86 / papa.width, H * 0.92 / papa.height)
    papa = papa.resize((int(papa.width * k), int(papa.height * k)), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), GREEN + (255,))
    canvas.alpha_composite(papa, ((W - papa.width) // 2, H - papa.height))
    default = canvas.convert("RGB")

    poses = {"default": default}
    for name, instr in POSES.items():
        print(f"pose: {name}")
        v = edit(default, instr).resize((W, H), Image.LANCZOS)
        poses[name] = align(v, default)

    frames: dict[str, dict[str, Image.Image]] = {}
    for pname, pimg in poses.items():
        frames[pname] = {"rest": pimg}
        for mname, instr in MOUTHS.items():
            print(f"  {pname}/{mname}")
            frames[pname][mname] = face_patch(pimg, edit(pimg, instr).resize((W, H), Image.LANCZOS))

    # cut out the green, crop every image to the same union box so poses line up
    cut = {p: {m: chroma_key(im) for m, im in d.items()} for p, d in frames.items()}
    boxes = [im.getchannel("A").point(lambda v: 255 if v > 30 else 0).getbbox()
             for d in cut.values() for im in d.values()]
    boxes = [b for b in boxes if b]
    union = (min(b[0] for b in boxes), min(b[1] for b in boxes),
             max(b[2] for b in boxes), max(b[3] for b in boxes))
    for p, d in cut.items():
        (OUT / p).mkdir(exist_ok=True)
        for m, im in d.items():
            im.crop(union).save(OUT / p / f"{m}.png")
    (OUT / "poses.json").write_text(json.dumps({"poses": list(cut), "mouths": ["rest", *MOUTHS]}))

    # preview sheet
    names = ["rest", "aa", "ee", "oo", "mbp", "blink"]
    tw = 220
    sample = Image.open(OUT / "default" / "rest.png")
    th = int(sample.height * tw / sample.width)
    sheet = Image.new("RGB", (tw * len(names), th * len(cut)), (30, 36, 60))
    for r, p in enumerate(cut):
        for c, m in enumerate(names):
            im = Image.open(OUT / p / f"{m}.png").resize((tw, th))
            sheet.paste(im, (c * tw, r * th), im)
    sheet.save(OUT / "preview.png")
    print("✅ saved to", OUT)


if __name__ == "__main__":
    main()
