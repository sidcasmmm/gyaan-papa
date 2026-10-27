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

STYLE = ("Photorealistic cinematic photo, vertical 9:16, Indian setting, warm natural lighting, "
         "shallow depth of field, rich detail. No text, no letters, no logos, no watermarks, "
         "no real or famous people — only ordinary unnamed people.")


# ── Gemini (also used by tools/make_papa.py) ────────────────────────────
def gemini_image(prompt: str, model: str, aspect: str = "9:16",
                 input_images: list[Image.Image] | None = None, retries: int = 3) -> Image.Image:
    key = os.environ["GEMINI_API_KEY"]
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
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key}, json=body, timeout=180)
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


# ── Pixabay (free) ──────────────────────────────────────────────────────
def pixabay_image(query: str) -> Image.Image:
    r = requests.get("https://pixabay.com/api/",
                     params={"key": os.environ.get("PIXABAY_API_KEY") or os.environ["PEXELS_API_KEY"],
                             "q": query[:100],
                             "image_type": "photo", "orientation": "vertical",
                             "safesearch": "true", "per_page": 10}, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits and " " in query:                       # too specific → try fewer words
        return pixabay_image(" ".join(query.split()[:2]))
    if not hits:
        raise RuntimeError(f"no Pixabay photo for '{query}'")
    hit = random.choice(hits[:5])
    url = hit.get("fullHDURL") or hit.get("largeImageURL")
    return Image.open(io.BytesIO(requests.get(url, timeout=60).content)).convert("RGBA")


# ── fallback ────────────────────────────────────────────────────────────
def placeholder(label: str, seed: int, W: int = 1080, H: int = 1920) -> Image.Image:
    rnd = random.Random(seed)
    base = [(28, 38, 70), (52, 34, 24), (20, 50, 46), (48, 28, 56), (30, 30, 36)][seed % 5]
    img = Image.new("RGBA", (W, H), base + (255,))
    d = ImageDraw.Draw(img)
    for _ in range(14):                       # soft "bokeh" lights
        x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.randint(80, 260)
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=(255, 210 - rnd.randint(0, 80), 140, rnd.randint(25, 60)))
    img = img.filter(ImageFilter.GaussianBlur(40))
    d = ImageDraw.Draw(img)
    d.text((W // 2, 520), f"[ AI scene: {label[:40]} ]", fill=(255, 255, 255, 120), anchor="mm")
    return img


def fit_cover(img: Image.Image, W: int, H: int) -> Image.Image:
    k = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * k + 0.5), int(img.height * k + 0.5)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def scene_images(scenes: list[dict], cfg: dict, workdir: Path, offline: bool = False) -> list[Path]:
    icfg = cfg.get("images", {})
    provider = icfg.get("provider", "gemini")
    W, H = cfg["style"]["width"], cfg["style"]["height"]
    out = []
    for i, sc in enumerate(scenes):
        path = workdir / f"bg{i}.jpg"
        prompt = sc.get("image_prompt") or sc.get("onscreen") or "Indian stock market office"
        img = None
        if not offline:
            try:
                if provider == "pixabay":
                    img = pixabay_image(sc.get("image_query") or prompt)
                elif provider == "pexels":
                    img = pexels_image(sc.get("image_query") or prompt)
                else:
                    img = gemini_image(f"{prompt}. {STYLE}", icfg.get("gemini_model",
                                                                     "gemini-2.5-flash-image"))
                print(f"  ✓ image {i + 1}/{len(scenes)}")
            except Exception as e:
                print(f"  ✗ image {i + 1}: {e}")
        if img is None:
            img = placeholder(prompt, i, W, H)
        fit_cover(img, W, H).convert("RGB").save(path, quality=92)
        out.append(path)
    return out
