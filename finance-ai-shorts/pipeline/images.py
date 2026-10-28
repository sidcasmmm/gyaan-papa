"""Background images for each scene.

provider "gemini" — AI-generated photo-realistic scenes (≈ $0.04 per image)
provider "pixabay" — free stock photos (needs a free PIXABAY_API_KEY)
provider "pexels"  — free stock photos (needs a PEXELS_API_KEY)
Falls back to a plain gradient card if both fail, so a run never dies on images.
"""
from __future__ import annotations

import base64
import io
import os
import random
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

STYLE = ("Vertical 9:16 cinematic illustration for a Hindi science and history explainer. Bold, "
         "clear and wondrous — like a premium documentary poster: dramatic lighting, rich colours, "
         "depth, a single focal point that instantly shows the idea (sky, moon, leaf, ancient street, "
         "printing press, human heart as a simple diagram-like scene). Keep the bottom-left third "
         "simpler (a character is placed there). No text, no letters, no numbers, no logos, no "
         "watermarks, no real or famous people, no gory injury, no lab procedure — only ordinary "
         "unnamed people or objects.")
STYLE_PHOTO = ("Vertical 9:16 photo-realistic still of the idea itself: sky, space, nature, an ancient "
               "place, or a simple everyday object. Warm natural light, one clear subject. Keep the "
               "bottom-left third simpler (a character is placed there). No text, no letters, no numbers, "
               "no logos, no watermarks, no real or famous people.")
GEMINI_IMAGE_MODELS = ["gemini-3.1-flash-lite-image", "gemini-nano-banana-2.1", "gemini-2.5-flash-image"]


# ── Gemini (also used by tools/make_papa.py) ────────────────────────────
def gemini_image(prompt: str, model: str, aspect: str = "9:16",
                 input_images: list[Image.Image] | None = None, retries: int = 3) -> Image.Image:
    from . import gemini_api
    parts = []
    for im in input_images or []:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "PNG")
        parts.append({"inline_data": {"mime_type": "image/png",
                                      "data": base64.b64encode(buf.getvalue()).decode()}})
    parts.append({"text": prompt})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "imageConfig": {"aspectRatio": aspect}}}
    last = None
    for attempt in range(retries):
        r = gemini_api.post(model, body, timeout=180)
        if r.status_code == 400 and "imageConfig" in r.text:      # older models: no aspect option
            body["generationConfig"].pop("imageConfig", None)
            continue
        if r.status_code >= 400:
            last = f"{r.status_code}: {r.text[:300]}"
            time.sleep(4 * (attempt + 1))
            continue
        for cand in r.json().get("candidates", []):
            for p in cand.get("content", {}).get("parts", []):
                data = p.get("inline_data") or p.get("inlineData")
                if data:
                    return Image.open(io.BytesIO(base64.b64decode(data["data"]))).convert("RGBA")
        last = "no image in response (prompt may have been blocked)"
        time.sleep(3)
    raise RuntimeError(f"Gemini image failed: {last}")


# ── Pexels (free) ───────────────────────────────────────────────────────
def pexels_image(query: str) -> Image.Image:
    r = requests.get("https://api.pexels.com/v1/search",
                     headers={"Authorization": os.environ["PEXELS_API_KEY"]},
                     params={"query": query, "orientation": "portrait", "per_page": 8}, timeout=30)
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        raise RuntimeError(f"no Pexels photo for '{query}'")
    url = random.choice(photos[:5])["src"]["large2x"]
    return Image.open(io.BytesIO(requests.get(url, timeout=60).content)).convert("RGBA")


STOCK_FALLBACKS = ["blue sky", "night stars", "green leaf", "ancient stone city",
                   "rainbow clouds", "full moon"]


# ── Pixabay (free) ──────────────────────────────────────────────────────
def pixabay_image(query: str) -> Image.Image:
    r = requests.get("https://pixabay.com/api/",
                     params={"key": os.environ.get("PIXABAY_API_KEY") or os.environ["PEXELS_API_KEY"],
                             "q": query[:100],
                             "image_type": "photo", "orientation": "vertical",
                             "safesearch": "true", "per_page": 10}, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits and len(query.split()) > 2:            # too specific → try fewer words
        return pixabay_image(" ".join(query.split()[:2]))
    if not hits and query not in STOCK_FALLBACKS:       # still nothing → a broad science photo
        return pixabay_image(random.choice(STOCK_FALLBACKS))
    if not hits:
        raise RuntimeError(f"no Pixabay photo for '{query}'")
    hit = random.choice(hits[:5])
    url = hit.get("fullHDURL") or hit.get("largeImageURL")
    return Image.open(io.BytesIO(requests.get(url, timeout=60).content)).convert("RGBA")


# ── fallback ────────────────────────────────────────────────────────────
def placeholder(_label: str, seed: int, W: int = 1080, H: int = 1920) -> Image.Image:
    rnd = random.Random(seed)
    base = [(28, 38, 70), (52, 34, 24), (20, 50, 46), (48, 28, 56), (30, 30, 36)][seed % 5]
    img = Image.new("RGBA", (W, H), base + (255,))
    d = ImageDraw.Draw(img)
    for _ in range(14):                       # soft "bokeh" lights
        x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.randint(80, 260)
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=(255, 210 - rnd.randint(0, 80), 140, rnd.randint(25, 60)))
    return img.filter(ImageFilter.GaussianBlur(40))


def fit_cover(img: Image.Image, W: int, H: int) -> Image.Image:
    k = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * k + 0.5), int(img.height * k + 0.5)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def _gemini_any(prompt: str, preferred: str | None) -> Image.Image:
    models = ([preferred] if preferred else []) + [m for m in GEMINI_IMAGE_MODELS if m != preferred]
    last = None
    for m in models:
        try:
            return gemini_image(prompt, m, retries=2)
        except Exception as e:
            last = e
            if "billing" in str(e).lower() or "quota" in str(e).lower() or "429" in str(e):
                break                                # no point trying other models
    raise RuntimeError(f"Gemini images unavailable: {last}")


def scene_images(scenes: list[dict], cfg: dict, workdir: Path, offline: bool = False,
                 photo: bool = False) -> list[Path]:
    """One background per scene. AI images match what Papa is saying; if AI images fail
    (e.g. billing not enabled) it falls back to free stock photos, then a plain card."""
    icfg = cfg.get("images", {})
    provider = icfg.get("provider", "gemini")
    W, H = cfg["style"]["width"], cfg["style"]["height"]
    have_stock = bool(os.environ.get("PIXABAY_API_KEY") or os.environ.get("PEXELS_API_KEY"))
    ai_ok = provider == "gemini" and bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("VERTEX_API_KEY"))

    # monthly spending limit for AI pictures
    import json
    from datetime import datetime
    usage_file = Path(__file__).resolve().parent.parent / "state" / "usage.json"
    month = datetime.utcnow().strftime("%Y-%m")
    try:
        usage = json.loads(usage_file.read_text())
    except Exception:
        usage = {}
    used = usage.get(month, {}).get("ai_images", 0)
    price = float(icfg.get("price_inr_per_image", 3.0))
    limit = float(icfg.get("monthly_limit_inr", 2000))
    if ai_ok and used * price >= limit:
        print(f"  AI picture limit reached this month (₹{used * price:.0f} of ₹{limit:.0f}) — using stock photos")
        ai_ok = False
    made = 0
    out = []
    for i, sc in enumerate(scenes):
        path = workdir / f"bg{i}.jpg"
        prompt = sc.get("image_prompt") or sc.get("onscreen") or "Indian stock market"
        query = sc.get("image_query") or prompt
        img = None
        if not offline:
            if ai_ok:
                try:
                    img = _gemini_any(f"{prompt}. {STYLE_PHOTO if photo else STYLE}", icfg.get("gemini_model"))
                    made += 1
                    print(f"  ✓ AI image {i + 1}/{len(scenes)}")
                    if (used + made) * price >= limit:
                        ai_ok = False                # stop at the monthly limit
                except Exception as e:
                    print(f"  ✗ AI image {i + 1}: {str(e)[:160]} — using stock photos instead")
                    ai_ok = False                    # don't keep retrying a broken setup
            if img is None and have_stock:
                try:
                    img = (pexels_image(query) if provider == "pexels" and os.environ.get("PEXELS_API_KEY")
                           and not os.environ.get("PIXABAY_API_KEY") else pixabay_image(query))
                    print(f"  ✓ stock photo {i + 1}/{len(scenes)}")
                except Exception as e:
                    print(f"  ✗ stock photo {i + 1}: {str(e)[:120]}")
        if img is None:
            img = placeholder(prompt, i, W, H)
        fit_cover(img, W, H).convert("RGB").save(path, quality=92)
        out.append(path)
    from . import usage as run_usage
    run_usage.add("ai_images", made)
    if made:
        usage.setdefault(month, {})["ai_images"] = used + made
        usage_file.parent.mkdir(parents=True, exist_ok=True)
        usage_file.write_text(json.dumps(usage, indent=1))
        print(f"  AI pictures this month: {used + made} (≈ ₹{(used + made) * price:.0f} of ₹{limit:.0f} limit)")
    return out
