"""Gyaan Papa — an original cartoon desi uncle drawn entirely in code.

Parts are drawn at 2x and downscaled for smooth edges, then cached:
  body  (static)                      — Nehru jacket, kurta collar, pocket square
  head  (expression × mouth × blink)  — face, salt-pepper hair, round specs, big moustache
Per frame we only pick a cached head and rotate / bob it a little.
"""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter

S = 2                      # supersampling
HEAD_W, HEAD_H = 560, 640
BODY_W, BODY_H = 720, 600

SKIN = (201, 139, 94)
SKIN_DARK = (176, 115, 74)
SKIN_LIGHT = (219, 160, 116)
HAIR = (168, 172, 180)
HAIR_DARK = (110, 114, 122)
STACHE = (58, 56, 60)
FRAME = (34, 30, 30)
JACKET = (242, 169, 59)
JACKET_DARK = (205, 133, 35)
KURTA = (248, 244, 236)
MOUTH = (92, 30, 36)
TONGUE = (226, 108, 112)
BLUSH = (232, 120, 110, 70)

EXPRESSIONS = ("happy", "excited", "shocked", "thinking", "serious")


def _s(box):
    return [v * S for v in box]


def _down(img: Image.Image, w: int, h: int) -> Image.Image:
    return img.resize((w, h), Image.LANCZOS)


# ── body ───────────────────────────────────────────────────────────────
def draw_body() -> Image.Image:
    img = Image.new("RGBA", (BODY_W * S, BODY_H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = BODY_W // 2
    # neck
    d.rounded_rectangle(_s([cx - 70, 0, cx + 70, 120]), radius=30 * S, fill=SKIN_DARK)
    # kurta (white) under jacket
    d.rounded_rectangle(_s([40, 70, BODY_W - 40, BODY_H + 200]), radius=230 * S, fill=KURTA)
    # jacket halves (Nehru style, open slightly in middle)
    d.rounded_rectangle(_s([40, 80, cx - 14, BODY_H + 200]), radius=200 * S, fill=JACKET)
    d.rounded_rectangle(_s([cx + 14, 80, BODY_W - 40, BODY_H + 200]), radius=200 * S, fill=JACKET)
    d.rectangle(_s([cx - 120, 80, cx - 14, BODY_H + 200]), fill=JACKET)
    d.rectangle(_s([cx + 14, 80, cx + 120, BODY_H + 200]), fill=JACKET)
    # kurta strip visible in the middle
    d.rectangle(_s([cx - 14, 90, cx + 14, BODY_H]), fill=KURTA)
    # mandarin collar
    d.rounded_rectangle(_s([cx - 95, 70, cx + 95, 120]), radius=18 * S, fill=JACKET_DARK)
    d.rounded_rectangle(_s([cx - 80, 62, cx + 80, 104]), radius=16 * S, fill=KURTA)
    # buttons
    for y in (190, 290, 390, 490):
        d.ellipse(_s([cx + 26, y - 13, cx + 52, y + 13]), fill=(120, 72, 20))
        d.ellipse(_s([cx + 32, y - 7, cx + 40, y + 1]), fill=(170, 112, 50))
    # pocket + pocket square
    d.rounded_rectangle(_s([cx + 140, 250, cx + 280, 262]), radius=5 * S, fill=JACKET_DARK)
    d.polygon(_s([cx + 160, 252, cx + 190, 200, cx + 215, 238, cx + 245, 196, cx + 262, 252]),
              fill=(230, 70, 110))
    # ₹ pin on the left
    d.ellipse(_s([cx - 230, 230, cx - 170, 290]), fill=(250, 214, 100), outline=(150, 100, 20), width=4 * S)
    d.line(_s([cx - 212, 246, cx - 186, 246]), fill=(120, 72, 20), width=4 * S)
    d.line(_s([cx - 212, 258, cx - 186, 258]), fill=(120, 72, 20), width=4 * S)
    d.line(_s([cx - 210, 246, cx - 190, 275]), fill=(120, 72, 20), width=4 * S)
    # jacket seam shading
    d.arc(_s([60, 160, 340, 900]), 180, 260, fill=JACKET_DARK, width=8 * S)
    d.arc(_s([BODY_W - 340, 160, BODY_W - 60, 900]), 280, 360, fill=JACKET_DARK, width=8 * S)
    # soft neck shadow under the chin
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse(_s([cx - 90, -30, cx + 90, 50]), fill=(90, 50, 30, 120))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(10 * S)))
    return _down(img, BODY_W, BODY_H)


# ── head ───────────────────────────────────────────────────────────────
def _brows(d, expr):
    # (inner_y, outer_y) offsets — lower inner = angry/serious, higher = surprised
    y = 210
    shapes = {
        "happy": ((-6, 0), (-6, 0)),
        "excited": ((-22, -14), (-22, -14)),
        "shocked": ((-34, -22), (-34, -22)),
        "thinking": ((-2, 6), (-30, -36)),
        "serious": ((10, -8), (10, -8)),
    }[expr]
    for side, (inner, outer) in zip((-1, 1), shapes):
        cx = 280 + side * 75
        x_in, x_out = cx - side * 50, cx + side * 50
        d.line(_s([x_in, y + inner, cx, y + min(inner, outer) - 8, x_out, y + outer]),
               fill=HAIR_DARK, width=20 * S, joint="curve")
        for x, yy in ((x_in, y + inner), (x_out, y + outer)):
            d.ellipse(_s([x - 10, yy - 10, x + 10, yy + 10]), fill=HAIR_DARK)


def _eyes(d, expr, blink):
    look = {"thinking": (10, -8)}.get(expr, (0, 0))
    big = expr in ("shocked", "excited")
    for side in (-1, 1):
        cx, cy = 280 + side * 75, 300
        if blink:
            d.arc(_s([cx - 30, cy - 18, cx + 30, cy + 18]), 10, 170, fill=STACHE, width=7 * S)
            continue
        rx, ry = (34, 34) if big else (31, 28)
        d.ellipse(_s([cx - rx, cy - ry, cx + rx, cy + ry]), fill=(255, 255, 255))
        pr = 13 if expr == "shocked" else 16
        px, py = cx + look[0], cy + look[1] + 2
        d.ellipse(_s([px - pr, py - pr, px + pr, py + pr]), fill=(40, 28, 24))
        d.ellipse(_s([px - pr + 6, py - pr + 4, px - pr + 13, py - pr + 11]), fill=(255, 255, 255))
        if expr == "happy":   # happy cheeks push lower lid up
            d.chord(_s([cx - 40, cy + 8, cx + 40, cy + 50]), 180, 360, fill=SKIN)


def _glasses(d):
    for side in (-1, 1):
        cx, cy = 280 + side * 75, 300
        d.ellipse(_s([cx - 62, cy - 58, cx + 62, cy + 58]), outline=FRAME, width=10 * S)
        d.arc(_s([cx - 44, cy - 42, cx + 10, cy + 10]), 200, 250, fill=(255, 255, 255, 170), width=6 * S)
    d.arc(_s([248, 278, 312, 318]), 200, 340, fill=FRAME, width=9 * S)
    d.line(_s([93, 290, 70, 300]), fill=FRAME, width=9 * S)
    d.line(_s([467, 290, 490, 300]), fill=FRAME, width=9 * S)


def _mouth(d, expr, level):
    """level 0 = closed … 3 = wide open."""
    cx, top = 280, 462
    if expr == "shocked" and level == 0:
        level = 1
    if level == 0:
        if expr == "serious":
            d.line(_s([cx - 34, top + 8, cx + 34, top + 8]), fill=MOUTH, width=8 * S)
        else:
            d.arc(_s([cx - 44, top - 26, cx + 44, top + 22]), 20, 160, fill=MOUTH, width=8 * S)
        return
    if expr == "shocked":
        r = 16 + level * 7
        d.ellipse(_s([cx - r, top - 4, cx + r, top - 4 + r * 2.2]), fill=MOUTH)
        return
    w = 44 + level * 4
    h = 14 + level * 15
    d.chord(_s([cx - w, top - h * 0.6, cx + w, top + h]), 0, 180, fill=MOUTH)
    d.ellipse(_s([cx - w * 0.45, top + h * 0.35, cx + w * 0.45, top + h * 0.95]), fill=TONGUE)
    d.chord(_s([cx - w * 0.8, top - 10, cx + w * 0.8, top + 14]), 0, 180, fill=(250, 250, 248))  # teeth


def _moustache(d, expr):
    lift = {"happy": -6, "excited": -10, "shocked": 4, "thinking": 0, "serious": 6}[expr]
    for side in (-1, 1):
        pts = []
        for i in range(13):
            t = i / 12
            x = 280 + side * (8 + 118 * t)
            y = 420 + 34 * math.sin(math.pi * t) * 0.55 + (lift * t) - 8 * t * t
            pts.append((x, y))
        for (x, y) in pts:
            r = 26 - 10 * abs((x - 280) / 126)
            d.ellipse(_s([x - r, y - r * 0.85, x + r, y + r * 0.85]), fill=STACHE)
        # curled tip: small dots spiralling up and back inward
        ex, ey = pts[-1]
        ccx, ccy = ex + side * 4, ey - 18
        for k in range(9):
            a = math.pi / 2 - k * (math.pi * 1.25 / 8)      # from bottom, sweeping outward & up
            x = ccx + side * 18 * math.cos(a)
            y = ccy + 18 * math.sin(a)
            r = 11 - k * 0.8
            d.ellipse(_s([x - r, y - r, x + r, y + r]), fill=STACHE)
    # highlight strands
    for side in (-1, 1):
        d.arc(_s([280 + side * 20 - 40 + side * 30, 400, 280 + side * 20 + 40 + side * 30, 440]),
              200 if side < 0 else 280, 260 if side < 0 else 340, fill=(110, 108, 114), width=4 * S)


def draw_head(expr: str, mouth: int, blink: bool) -> Image.Image:
    img = Image.new("RGBA", (HEAD_W * S, HEAD_H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # side hair puffs (behind face)
    for cx in (100, 460):
        d.ellipse(_s([cx - 72, 170, cx + 72, 330]), fill=HAIR)
        d.ellipse(_s([cx - 50, 150, cx + 40, 250]), fill=HAIR)
    # ears
    for cx in (78, 482):
        d.ellipse(_s([cx - 36, 268, cx + 36, 392]), fill=SKIN_DARK)
        d.ellipse(_s([cx - 18, 292, cx + 18, 368]), fill=SKIN)
    # face
    d.ellipse(_s([88, 92, 472, 584]), fill=SKIN)
    d.ellipse(_s([130, 110, 380, 300]), fill=SKIN_LIGHT)          # forehead shine
    d.ellipse(_s([88, 92, 472, 584]), outline=SKIN_DARK, width=4 * S)
    # receding hair on top
    d.chord(_s([110, 70, 450, 250]), 190, 350, fill=HAIR)
    d.chord(_s([180, 108, 380, 190]), 180, 360, fill=SKIN_LIGHT)   # bald patch
    for x in (220, 270, 320):
        d.arc(_s([x - 40, 96, x + 40, 170]), 200, 330, fill=HAIR_DARK, width=5 * S)
    # blush
    bl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bl)
    for cx in (165, 395):
        bd.ellipse(_s([cx - 46, 372, cx + 46, 420]), fill=BLUSH)
    img = Image.alpha_composite(img, bl.filter(ImageFilter.GaussianBlur(8 * S)))
    d = ImageDraw.Draw(img)
    # nose
    d.ellipse(_s([246, 330, 314, 410]), fill=SKIN_DARK)
    d.ellipse(_s([254, 332, 306, 398]), fill=SKIN)
    _eyes(d, expr, blink)
    _brows(d, expr)
    _glasses(d)
    _mouth(d, expr, mouth)
    _moustache(d, expr)
    # chin dimple
    d.arc(_s([260, 540, 300, 560]), 20, 160, fill=SKIN_DARK, width=4 * S)
    return _down(img, HEAD_W, HEAD_H)


# ── animator ───────────────────────────────────────────────────────────
class Papa:
    """Builds full character frames (head on body) for any moment in time."""

    W, H = BODY_W, 520 + BODY_H

    def __init__(self, seed: int = 11):
        self.body = draw_body()
        self.heads: dict = {}
        rnd = random.Random(seed)
        self.blinks, t = [], 1.2
        while t < 600:
            self.blinks.append(t)
            t += rnd.uniform(2.4, 4.6)

    def head(self, expr, mouth, blink):
        key = (expr, mouth, blink)
        if key not in self.heads:
            self.heads[key] = draw_head(expr, mouth, blink)
        return self.heads[key]

    def is_blinking(self, t):
        return any(b <= t < b + 0.13 for b in self.blinks)

    def frame(self, t: float, expr: str, level: float, entry: float = 1.0) -> Image.Image:
        """level = speech loudness 0..1. entry = 0→1 slide-in progress."""
        mouth = 0 if level < 0.12 else 1 if level < 0.38 else 2 if level < 0.68 else 3
        head = self.head(expr if expr in EXPRESSIONS else "happy", mouth, self.is_blinking(t))
        angle = 2.4 * math.sin(t * 1.9) + (3.0 * math.sin(t * 7.5) * level)
        if expr == "thinking":
            angle += 6
        nod = -10 * level + 3 * math.sin(t * 3.8)
        canvas = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        breathe = 4 * math.sin(t * 2.4)
        canvas.alpha_composite(self.body, (0, int(480 + breathe)))
        rh = head.rotate(angle, resample=Image.BICUBIC, expand=False, center=(HEAD_W / 2, HEAD_H - 80))
        canvas.alpha_composite(rh, ((self.W - HEAD_W) // 2, int(nod + breathe * 0.6)))
        return canvas
