"""Animate the 3D Papa cut-outs (assets/papa/*.png) for free — no per-second AI cost.

Lip-sync = switching between mouth images by voice loudness; plus blinks, a gentle
head-and-body sway, breathing and a little bounce on loud words."""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PAPA_DIR = ROOT / "assets" / "papa"
NEEDED = ["base", "talk1", "talk2", "talk3", "blink"]


def available() -> bool:
    return all((PAPA_DIR / f"{n}.png").exists() for n in NEEDED)


class Papa3D:
    def __init__(self, max_w: int, max_h: int, folder: Path = PAPA_DIR, seed: int = 5):
        self.frames = {}
        for n in NEEDED:
            im = Image.open(folder / f"{n}.png").convert("RGBA")
            k = min(max_w / im.width, max_h / im.height)
            self.frames[n] = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
        self.W, self.H = self.frames["base"].size
        rnd = random.Random(seed)
        self.blinks, t = [], 1.0
        while t < 900:
            self.blinks.append(t)
            t += rnd.uniform(2.5, 5.0)
        self._mouth_hold = (0.0, "base")

    def frame(self, t: float, level: float) -> Image.Image:
        blinking = any(b <= t < b + 0.12 for b in self.blinks)
        if level < 0.12:
            key = "base"
        elif level < 0.4:
            key = "talk1"
        elif level < 0.72:
            key = "talk2"
        else:
            key = "talk3"
        # hold each mouth shape ≥ 2 frames so it doesn't flicker
        held_t, held_k = self._mouth_hold
        if t - held_t < 0.066 and key != "base":
            key = held_k
        else:
            self._mouth_hold = (t, key)
        if blinking and key == "base":
            key = "blink"
        img = self.frames[key]
        angle = 1.6 * math.sin(t * 1.7) + 1.2 * level * math.sin(t * 9)
        img = img.rotate(angle, resample=Image.BICUBIC, center=(self.W / 2, self.H), expand=False)
        breathe = 1 + 0.008 * math.sin(t * 2.3) + 0.012 * level
        if abs(breathe - 1) > 0.002:
            nw, nh = int(self.W * breathe), int(self.H * breathe)
            img = img.resize((nw, nh), Image.BILINEAR)
        return img
