"""Cinematic style: full-screen AI scene backgrounds with slow zoom/pan,
Gyaan Papa talking in the bottom-left corner,
big white serif Hinglish captions, pop-up number cards."""
from __future__ import annotations

import math
import random
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import papa3d
from .character import Papa
from .render import (FONTS, TimedScene, animate_number, caption_groups, ease_out, font, hex2rgb,
                     speech_levels, triangle, with_alpha)

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_serif_cache: dict = {}


def serif(size: int) -> ImageFont.FreeTypeFont:
    if size not in _serif_cache:
        f = ImageFont.truetype(str(FONTS / "Lora-Variable.ttf"), size,
                               layout_engine=ImageFont.Layout.RAQM)
        f.set_variation_by_name("Bold")
        _serif_cache[size] = f
    return _serif_cache[size]


def word_font(text: str, size: int):
    """Lora for Roman Hinglish; Poppins for Devanagari or the ₹ sign."""
    if DEVANAGARI.search(text) or "₹" in text:
        return font("Bold", int(size * 0.92))
    return serif(size)


class CinematicRenderer:
    PAPA_MAX_W, PAPA_MAX_H = 640, 1060

    def __init__(self, cfg: dict, source: str, backgrounds: list[Path],
                 talking: Path | None = None, hook: str | None = None,
                 clips: dict | None = None, goal: str | None = None):
        self.cfg, self.st = cfg, cfg["style"]
        self.goal = goal or "follows"
        self.clips = clips or {}                       # scene index → Veo clip (moving background)
        self._vb: dict = {}
        self.hook = (hook or "").strip()
        self.W, self.H, self.fps = self.st["width"], self.st["height"], self.st["fps"]
        self.source = source
        self.bgs = [self._prep_bg(p) for p in backgrounds]
        rnd = random.Random(42)
        self.moves = [(rnd.choice([1, -1]), rnd.uniform(-1, 1), rnd.uniform(-1, 1))
                      for _ in backgrounds]
        self.clip = None
        if talking is not None:                        # Hedra: Papa really talks
            from .hedra import TalkingClip
            self.clip = TalkingClip(talking, width=746)
        if papa3d.available():
            self.papa = papa3d.Papa3D(self.PAPA_MAX_W, self.PAPA_MAX_H)
            self.papa_kind = "3d"
        else:
            self.papa = Papa()
            self.papa_kind = "2d"
        self.shade = self._make_shade()
        self.brand = self._make_brand()
        self._cap_cache: dict = {}
        self._stat_cache: dict = {}

    # static pieces ---------------------------------------------------------
    def _prep_bg(self, path: Path) -> Image.Image:
        im = Image.open(path).convert("RGB")
        k = 1.16
        return im.resize((int(self.W * k), int(self.H * k)), Image.LANCZOS)

    def _make_shade(self) -> Image.Image:
        g = Image.new("L", (1, self.H), 0)
        for y in range(self.H):
            top = max(0, 1 - y / 330) * 150
            bot = max(0, (y - 1050) / (self.H - 1050)) * 175
            g.putpixel((0, y), int(min(255, top + bot)))
        shade = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        shade.putalpha(g.resize((self.W, self.H)))
        return shade

    def _make_brand(self) -> Image.Image:
        img = Image.new("RGBA", (self.W, 170), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        acc = hex2rgb(self.st["accent"])
        name = self.cfg["channel"]["name"]
        f = font("Bold", 38)
        w = int(f.getlength(name)) + 56
        d.rounded_rectangle([40, 52, 40 + w, 112], radius=30, fill=acc)
        d.text((40 + w // 2, 82), name, font=f, fill=hex2rgb(self.st["bg_top"]), anchor="mm")
        d.text((44, 136), f"Source: {self.source}  •  Educational only, not advice",
               font=font("Medium", 24), fill=(255, 255, 255, 200))
        return img

    # background with slow zoom / pan ("Ken Burns") + punch-in on each cut ---
    def background(self, i: int, t_in: float, dur: float, freeze: bool = False) -> Image.Image:
        if i in self.clips:
            from .veo import VideoBg
            vb = self._vb.get(i)
            if vb is None:
                for old in self._vb.values():
                    old.close()
                vb = self._vb[i] = VideoBg(self.clips[i], self.W, self.H, self.fps)
            fr = vb.last if (freeze and vb.last is not None) else vb.next()
            if fr is not None:
                zoom = 1.0 + 0.05 * (1 - ease_out(t_in / 0.35))      # same punch-in at the cut
                if zoom > 1.001:
                    cw, ch = self.W / zoom, self.H / zoom
                    box = ((self.W - cw) / 2, (self.H - ch) / 2, (self.W + cw) / 2, (self.H + ch) / 2)
                    fr = fr.resize((self.W, self.H), Image.BILINEAR, box=box)
                return fr.convert("RGBA")
            self.clips.pop(i, None)                    # clip unreadable → still picture
        big = self.bgs[i]
        direction, px, py = self.moves[i]
        p = min(t_in / max(dur, 0.1), 1.0)
        zoom = 1.0 + 0.10 * (p if direction > 0 else 1 - p)
        zoom += 0.06 * (1 - ease_out(t_in / 0.35))          # punch-in at the cut
        zoom = min(zoom, 1.159)
        cw, ch = self.W / zoom * 1.0, self.H / zoom * 1.0
        bw, bh = big.size
        cx = bw / 2 + px * (bw - cw) / 2 * p
        cy = bh / 2 + py * (bh - ch) / 2 * p
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        box = (max(0, box[0]), max(0, box[1]), min(bw, box[2]), min(bh, box[3]))
        return big.resize((self.W, self.H), Image.BILINEAR, box=box).convert("RGBA")

    # captions ---------------------------------------------------------------
    def caption(self, words: list, active: int) -> Image.Image:
        key = (id(words), active)
        if key in self._cap_cache:
            return self._cap_cache[key]
        size = 96
        gap = 26
        widths = [word_font(w.text, size).getlength(w.text) for w in words]
        lines, cur, cur_w = [], [], 0.0
        for i, ww in enumerate(widths):
            if cur and cur_w + gap + ww > 940:
                lines.append(cur)
                cur, cur_w = [], 0.0
            cur.append(i)
            cur_w += (gap if len(cur) > 1 else 0) + ww
        if cur:
            lines.append(cur)
        img = Image.new("RGBA", (self.W, 300), (0, 0, 0, 0))
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d, sd = ImageDraw.Draw(img), ImageDraw.Draw(shadow)
        acc = hex2rgb(self.st["accent"])
        for li, idxs in enumerate(lines[:2]):
            total = sum(widths[i] for i in idxs) + gap * (len(idxs) - 1)
            x = (self.W - total) / 2
            y = 30 + li * 128
            for i in idxs:
                txt = words[i].text
                f = word_font(txt, size)
                sd.text((x + 4, y + 6), txt, font=f, fill=(0, 0, 0, 255), stroke_width=8,
                        stroke_fill=(0, 0, 0, 255))
                d.text((x, y), txt, font=f, fill=acc if i == active else (255, 255, 255),
                       stroke_width=3, stroke_fill=(20, 20, 20))
                x += widths[i] + gap
        shadow = shadow.filter(ImageFilter.GaussianBlur(9))
        shadow.putalpha(shadow.getchannel("A").point(lambda v: int(v * 0.75)))
        out = Image.alpha_composite(shadow, img)
        self._cap_cache[key] = out
        return out

    # stat pop-up card -------------------------------------------------------
    def stat_card(self, sc: TimedScene, t_in: float) -> Image.Image | None:
        stat = sc.data.get("stat") or {}
        if not stat.get("value"):
            return None
        done = t_in >= 1.0
        key = sc.index
        if done and key in self._stat_cache:
            return self._stat_cache[key]
        direction = stat.get("direction", "neutral")
        col = hex2rgb({"up": self.st["up"], "down": self.st["down"]}.get(direction, self.st["accent"]))
        value = animate_number(stat["value"], ease_out(t_in / 0.9))
        fv = font("Bold", 92)
        while fv.getlength(value) > 600 and fv.size > 50:
            fv = font("Bold", fv.size - 6)
        label = stat.get("label", "")
        fl = font("Medium", 40)
        arrow = 64 if direction in ("up", "down") else 0
        w = int(max(fv.getlength(value) + arrow, fl.getlength(label)) + 80)
        img = Image.new("RGBA", (w + 16, 250), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([10, 14, w + 10, 234], radius=34, fill=(0, 0, 0, 110))
        d.rounded_rectangle([0, 0, w, 220], radius=34, fill=(255, 255, 255, 240))
        d.rounded_rectangle([0, 0, 18, 220], radius=9, fill=col)
        if arrow:
            triangle(d, 40, 82, 22, direction == "up", col)
        d.text((40 + arrow, 30), value, font=fv, fill=col)
        d.text((44, 148), label, font=fl, fill=(40, 44, 60))
        if done:
            self._stat_cache[key] = img
        return img

    # big hook headline on the first scene (also what the Reel cover shows) -----
    def hook_card(self) -> Image.Image | None:
        if not self.hook:
            return None
        if "hook" in self._stat_cache:
            return self._stat_cache["hook"]
        acc = hex2rgb(self.st["accent"])
        words = self.hook.split()
        size = 104
        while True:
            gap = int(size * 0.28)
            lines, cur = [], []
            for w in words:
                trial = " ".join(cur + [w])
                if cur and word_font(trial, size).getlength(trial) > 940:
                    lines.append(cur)
                    cur = [w]
                else:
                    cur.append(w)
            if cur:
                lines.append(cur)
            if len(lines) <= 2 or size <= 64:
                break
            size -= 8
        lines = lines[:2]
        line_h = int(size * 1.25)
        img = Image.new("RGBA", (self.W, line_h * len(lines) + 60), (0, 0, 0, 0))
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d, sd = ImageDraw.Draw(img), ImageDraw.Draw(shadow)
        for li, ws in enumerate(lines):
            widths = [word_font(w, size).getlength(w) for w in ws]
            x = (self.W - (sum(widths) + gap * (len(ws) - 1))) / 2
            y = 20 + li * line_h
            for w, ww in zip(ws, widths):
                f = word_font(w, size)
                hot = any(c.isdigit() for c in w) or "₹" in w or w.endswith("?") or w.endswith("!")
                sd.text((x + 4, y + 6), w, font=f, fill=(0, 0, 0, 255), stroke_width=10,
                        stroke_fill=(0, 0, 0, 255))
                d.text((x, y), w, font=f, fill=acc if hot else (255, 255, 255),
                       stroke_width=4, stroke_fill=(20, 20, 20))
                x += ww + gap
        shadow = shadow.filter(ImageFilter.GaussianBlur(10))
        shadow.putalpha(shadow.getchannel("A").point(lambda v: int(v * 0.8)))
        out = Image.alpha_composite(shadow, img)
        self._stat_cache["hook"] = out
        return out

    def outro_card(self) -> Image.Image:
        if "outro" not in self._stat_cache:
            img = Image.new("RGBA", (self.W, 520), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            acc = hex2rgb(self.st["accent"])
            f1 = serif(92)
            lines = {"comments": ["Comment karo,", "Papa jawab denge!"],
                     "saves": ["Save karo,", "kaam aayega!"],
                     "shares": ["Dost ko bhejo,", "uska bhala hoga!"]}.get(
                self.goal, ["Follow karo,", "Papa roz samjhayenge!"])
            for i, line in enumerate(lines):
                d.text((self.W // 2 + 4, 80 + i * 120 + 6), line, font=f1, fill=(0, 0, 0, 200),
                       anchor="mm")
                d.text((self.W // 2, 80 + i * 120), line, font=f1,
                       fill=(255, 255, 255) if i == 0 else acc, anchor="mm", stroke_width=3,
                       stroke_fill=(20, 20, 20))
            d.rounded_rectangle([290, 330, 790, 430], radius=50, fill=acc)
            d.text((540, 380), self.cfg["channel"]["handle"], font=font("Bold", 46),
                   fill=hex2rgb(self.st["bg_top"]), anchor="mm")
            self._stat_cache["outro"] = img
        return self._stat_cache["outro"]

    # papa ---------------------------------------------------------------------
    def papa_frame(self, t: float, level: float, expr: str) -> Image.Image:
        if self.clip is not None:
            f = self.clip.frame(t)
            if f is not None:
                return f
        if self.papa_kind == "3d":
            return self.papa.frame(t, level)
        im = self.papa.frame(t, expr, level)
        k = min(self.PAPA_MAX_W / im.width, 1000 / im.height)
        return im.resize((int(im.width * k), int(im.height * k)), Image.BILINEAR)

    # main loop ------------------------------------------------------------------
    def render(self, scenes: list[TimedScene], total: float, audio: Path, out: Path,
               outro_from: float, voice_wav: Path | None = None):
        n_frames = int(math.ceil(total * self.fps))
        groups = caption_groups(scenes, max_words=6)
        levels = speech_levels(voice_wav, n_frames, self.fps, scenes)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{self.W}x{self.H}", "-r", str(self.fps), "-i", "-", "-i", str(audio),
               "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
               "-af", "apad", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        acc = hex2rgb(self.st["accent"])
        for fi in range(n_frames):
            t = fi / self.fps
            in_outro = t >= outro_from
            sc = next((s for s in scenes if s.start <= t < s.end), scenes[-1])
            t_in = t - sc.start
            frame = self.background(sc.index, t_in if not in_outro else sc.end - sc.start,
                                    sc.end - sc.start, freeze=in_outro)
            frame.alpha_composite(self.shade)
            frame.alpha_composite(self.brand, (0, 0))

            # Papa, bottom-left, slides in at the start
            level = 0.0 if in_outro else levels[fi]
            papa = self.papa_frame(t, level, sc.data.get("expression", "happy"))
            entry = ease_out(t / 0.5)
            px = int((-107 if self.clip is not None else -30) - 500 * (1 - entry))
            py = self.H - papa.height + 60
            frame.alpha_composite(papa, (px, py))

            if not in_outro:
                hook = self.hook_card() if sc.index == 0 else None
                if hook is not None:                   # fully visible from frame 0 → good cover
                    fade = min(1.0, max(0.0, (sc.end - t) / 0.25))
                    frame.alpha_composite(with_alpha(hook, fade) if fade < 1 else hook, (0, 190))
                card = self.stat_card(sc, t_in)
                if card is not None and t_in > 0.15:
                    k = ease_out((t_in - 0.15) / 0.3)
                    x = int(self.W - card.width - 50 + 400 * (1 - k))
                    y = 190 + hook.height + 20 if hook is not None else 330
                    frame.alpha_composite(with_alpha(card, k), (x, y))
                g = next((g for g in groups if g[0] <= t < g[1]), None)
                if g:
                    active = max((i for i, w in enumerate(g[2]) if w.start <= t), default=0)
                    cap = self.caption(g[2], active)
                    pop = ease_out((t - g[0]) / 0.12)
                    if pop < 0.999:
                        s = 0.88 + 0.12 * pop
                        cap = cap.resize((int(cap.width * s), int(cap.height * s)), Image.BILINEAR)
                    frame.alpha_composite(cap, ((self.W - cap.width) // 2,
                                                800 + (300 - cap.height) // 2))
            else:
                k = ease_out((t - outro_from) / 0.35)
                frame.alpha_composite(with_alpha(self.outro_card(), k), (0, 520))

            d = ImageDraw.Draw(frame)
            d.rectangle([0, 0, int(self.W * t / total), 9], fill=acc)
            proc.stdin.write(frame.convert("RGB").tobytes())
        for vb in self._vb.values():
            vb.close()
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg encoding failed")
