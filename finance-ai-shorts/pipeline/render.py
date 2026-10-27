"""Render a 1080x1920 vertical Short: animated background, live ticker, scene cards,
stat count-ups, self-drawing charts and word-by-word Hindi captions."""
from __future__ import annotations

import math
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from .character import Papa

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"


# ── helpers ────────────────────────────────────────────────────────────
def hex2rgb(h: str, a: int | None = None):
    h = h.lstrip("#")
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return rgb + (a,) if a is not None else rgb


def ease_out(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


_font_cache: dict = {}


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(FONTS / f"Poppins-{weight}.ttf"), size,
                                              layout_engine=ImageFont.Layout.RAQM)
    return _font_cache[key]


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int, max_lines: int = 4) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if f.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def fit_font(text: str, weight: str, start: int, min_size: int, max_w: int, max_lines: int):
    size = start
    while size > min_size:
        f = font(weight, size)
        lines = wrap(text, f, max_w, 99)
        if len(lines) <= max_lines:
            return f, lines
        size -= 4
    f = font(weight, min_size)
    return f, wrap(text, f, max_w, max_lines)


def with_alpha(img: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return img
    a = img.getchannel("A").point(lambda v: int(v * alpha))
    out = img.copy()
    out.putalpha(a)
    return out


# ── timeline model ─────────────────────────────────────────────────────
@dataclass
class TimedScene:
    data: dict
    start: float
    end: float
    words: list           # voice.Word with absolute times
    index: int
    total: int


class Renderer:
    def __init__(self, cfg: dict, quotes: list, source: str):
        if not features.check("raqm"):
            raise RuntimeError("Pillow was built without libraqm — Hindi text would render "
                               "incorrectly. Install libraqm (apt install libraqm0).")
        self.cfg = cfg
        st = cfg["style"]
        self.W, self.H, self.fps = st["width"], st["height"], st["fps"]
        self.st = st
        self.quotes = {q.label: q for q in quotes}
        self.quote_list = quotes
        self.source = source
        self.bg = self._make_background()
        self.ticker = self._make_ticker()
        self.header = self._make_header()
        self.footer = self._make_footer()
        self.nametag = self._make_nametag()
        self.papa = Papa()
        self._card_cache: dict = {}
        self._cap_cache: dict = {}

    # static layers -------------------------------------------------------
    def _make_background(self) -> Image.Image:
        W, H = self.W, self.H + 400                       # taller: scrolls slowly
        top, bot = hex2rgb(self.st["bg_top"]), hex2rgb(self.st["bg_bottom"])
        grad = Image.new("RGB", (1, H))
        for y in range(H):
            t = y / H
            grad.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
        bg = grad.resize((W, H)).convert("RGBA")
        d = ImageDraw.Draw(bg)
        grid = (255, 255, 255, 7)
        for x in range(0, W, 120):
            d.line([(x, 0), (x, H)], fill=grid, width=1)
        for y in range(0, H, 120):
            d.line([(0, y), (W, y)], fill=grid, width=1)
        # soft glows
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([-300, 200, 700, 1200], fill=hex2rgb(self.st["accent"], 38))
        gd.ellipse([500, 1300, 1500, 2300], fill=(80, 110, 255, 45))
        glow = glow.filter(ImageFilter.GaussianBlur(160))
        # faint rising candlesticks at the bottom for a "markets" feel
        cd = ImageDraw.Draw(glow)
        import random
        rnd = random.Random(7)
        level = H - 380
        for x in range(30, W, 46):
            level += rnd.randint(-38, 30)
            level = min(max(level, H - 640), H - 140)
            h = rnd.randint(30, 110)
            up = rnd.random() > 0.42
            col = hex2rgb(self.st["up"] if up else self.st["down"], 34)
            cd.line([(x + 12, level - h // 2 - 25), (x + 12, level + h // 2 + 25)], fill=col, width=3)
            cd.rectangle([x, level - h // 2, x + 24, level + h // 2], fill=col)
        return Image.alpha_composite(bg, glow)

    def _make_ticker(self) -> Image.Image | None:
        if not self.quote_list:
            return None
        f_lab, f_val = font("Medium", 34), font("Bold", 34)
        parts = []
        for q in self.quote_list:
            col = self.st["up"] if q.change_pct >= 0 else self.st["down"]
            parts.append((q.label, f"{q.price:,.2f}", f"{abs(q.change_pct):.2f}%", col,
                          q.change_pct >= 0))
        seg_w = sum(f_lab.getlength(a) + f_val.getlength(b) + f_val.getlength(c) + 170
                    for a, b, c, _, _ in parts)
        strip = Image.new("RGBA", (int(seg_w) * 2 + 10, 70), (0, 0, 0, 0))
        d = ImageDraw.Draw(strip)
        x = 0
        for _ in range(2):
            for lab, val, chg, col, up in parts:
                d.text((x, 14), lab, font=f_lab, fill=hex2rgb(self.st["muted"]))
                x += f_lab.getlength(lab) + 18
                d.text((x, 14), val, font=f_val, fill=hex2rgb(self.st["text"]))
                x += f_val.getlength(val) + 16
                triangle(d, x, 36, 11, up, hex2rgb(col))
                x += 30
                d.text((x, 14), chg, font=f_val, fill=hex2rgb(col))
                x += f_val.getlength(chg) + 36
                d.ellipse([x, 31, x + 8, 39], fill=hex2rgb(self.st["accent"], 160))
                x += 72
        self.ticker_seg = int(seg_w)
        return strip

    def _make_header(self) -> Image.Image:
        img = Image.new("RGBA", (self.W, 160), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        acc = hex2rgb(self.st["accent"])
        d.ellipse([60, 46, 148, 134], fill=acc)
        dark = hex2rgb(self.st["bg_top"])
        for side in (-1, 1):                                   # mini moustache logo
            for i in range(7):
                x = 104 + side * (3 + i * 5.5)
                y = 96 + 4 * math.sin(math.pi * i / 6) - i * 0.6
                r = 9 - i * 0.7
                d.ellipse([x - r, y - r * 0.8, x + r, y + r * 0.8], fill=dark)
            d.ellipse([104 + side * 38 - 5, 82, 104 + side * 38 + 5, 92], fill=dark)
        d.text((170, 58), self.cfg["channel"]["name"], font=font("Bold", 46),
               fill=hex2rgb(self.st["text"]))
        d.text((172, 112), self.cfg["channel"].get("tagline", "दुनिया समझो, आसान भाषा में"),
               font=font("Medium", 26), fill=hex2rgb(self.st["muted"]))
        return img

    def _make_footer(self) -> Image.Image:
        img = Image.new("RGBA", (self.W, 48), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((self.W // 2, 24), f"स्रोत: {self.source}  •  सिर्फ़ जानकारी, निवेश सलाह नहीं",
               font=font("Medium", 25), fill=hex2rgb(self.st["muted"]), anchor="mm")
        return img

    def _make_nametag(self) -> Image.Image:
        f = font("Bold", 38)
        txt = self.cfg["channel"].get("character_name", "ज्ञान पापा")
        w = int(f.getlength(txt)) + 60
        img = Image.new("RGBA", (w + 20, 100), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([6, 14, w + 6, 90], radius=20, fill=(0, 0, 0, 110))
        d.rounded_rectangle([0, 6, w, 82], radius=20, fill=hex2rgb(self.st["accent"]))
        d.text((w // 2, 44), txt, font=f, fill=hex2rgb(self.st["bg_top"]), anchor="mm")
        return img.rotate(-7, resample=Image.BICUBIC, expand=True)

    # scene cards ---------------------------------------------------------
    def _chip(self, d: ImageDraw.ImageDraw, x: int, y: int, text: str, bg, fg=(255, 255, 255)):
        f = font("Bold", 30)
        w = f.getlength(text)
        d.rounded_rectangle([x, y, x + w + 44, y + 56], radius=28, fill=bg)
        d.text((x + 22, y + 28), text, font=f, fill=fg, anchor="lm")
        return w + 44

    def _card_base(self, sc: TimedScene, h: int):
        img = Image.new("RGBA", (960, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, 959, h - 1], radius=40, fill=(16, 22, 44, 170),
                            outline=(255, 255, 255, 40), width=2)
        if sc.index == 0:
            w = self._chip(d, 40, 40, "    आज की बड़ी खबर", hex2rgb(self.st["down"]))
            d.ellipse([64, 59, 82, 77], fill=(255, 255, 255))
        elif sc.index == sc.total - 1:
            self._chip(d, 40, 40, "समझिए", hex2rgb(self.st["accent"]), hex2rgb(self.st["bg_top"]))
        else:
            self._chip(d, 40, 40, f"{sc.index + 1:02d} / {sc.total:02d}", (255, 255, 255, 30))
        return img, d

    def _headline(self, d, text, y, max_lines=3, size=92, min_size=60):
        f, lines = fit_font(text, "Bold", size, min_size, 880, max_lines)
        lh = int(f.size * 1.32)
        for i, line in enumerate(lines):
            d.text((40, y + i * lh), line, font=f, fill=hex2rgb(self.st["text"]))
        return y + len(lines) * lh

    def _text_card(self, sc: TimedScene) -> Image.Image:
        img, d = self._card_base(sc, 640)
        bottom = self._headline(d, sc.data["onscreen"], 124, max_lines=3, size=92)
        d.rounded_rectangle([40, bottom + 24, 200, bottom + 36], radius=6,
                            fill=hex2rgb(self.st["accent"]))
        return img.crop((0, 0, 960, min(640, bottom + 90)))

    def _stat_card(self, sc: TimedScene, progress: float) -> Image.Image:
        stat = sc.data["stat"]
        img, d = self._card_base(sc, 560)
        y = self._headline(d, sc.data["onscreen"], 118, max_lines=1, size=66, min_size=46)
        direction = stat.get("direction", "neutral")
        col = hex2rgb({"up": self.st["up"], "down": self.st["down"]}.get(direction, self.st["accent"]))
        value = animate_number(stat["value"], ease_out(progress))
        fv, vlines = fit_font(value, "Bold", 140, 80, 760 if direction != "neutral" else 880, 1)
        vy = y + 24
        if direction in ("up", "down"):
            ax, ay, s = 40, vy + fv.size * 0.62, 46
            pts = ([(ax, ay + s), (ax + s, ay - s), (ax + 2 * s, ay + s)] if direction == "up"
                   else [(ax, ay - s), (ax + s, ay + s), (ax + 2 * s, ay - s)])
            d.polygon(pts, fill=col)
            d.text((150, vy), vlines[0], font=fv, fill=col)
        else:
            d.text((40, vy), vlines[0], font=fv, fill=col)
        d.text((40, vy + int(fv.size * 1.35)), stat.get("label", ""), font=font("Medium", 46),
               fill=hex2rgb(self.st["muted"]))
        return img

    def _chart_card(self, sc: TimedScene, progress: float) -> Image.Image:
        q = self.quotes[sc.data["chart"]]
        img, d = self._card_base(sc, 570)
        y = self._headline(d, sc.data["onscreen"], 112, max_lines=1, size=58, min_size=44)
        up = q.change_pct >= 0
        col = hex2rgb(self.st["up"] if up else self.st["down"])
        d.text((40, y + 4), q.label, font=font("Medium", 32), fill=hex2rgb(self.st["muted"]))
        d.text((40, y + 42), f"{q.price:,.2f}", font=font("Bold", 64), fill=hex2rgb(self.st["text"]))
        chg = f"{abs(q.change_pct):.2f}%"
        fb = font("Bold", 48)
        d.text((920, y + 52), chg, font=fb, fill=col, anchor="ra")
        triangle(d, 920 - fb.getlength(chg) - 52, y + 84, 18, up, col)
        # chart area
        cx0, cy0, cx1, cy1 = 40, y + 140, 920, 530
        pts = downsample(q.series, 120)
        lo, hi = min(pts), max(pts)
        span = (hi - lo) or 1
        coords = [(cx0 + (cx1 - cx0) * i / (len(pts) - 1),
                   cy1 - 20 - (cy1 - cy0 - 40) * (v - lo) / span) for i, v in enumerate(pts)]
        n = max(2, int(len(coords) * ease_out(progress)))
        shown = coords[:n]
        for gy in range(4):
            yy = cy0 + (cy1 - cy0) * gy / 3
            d.line([(cx0, yy), (cx1, yy)], fill=(255, 255, 255, 18), width=1)
        fill = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(fill).polygon(shown + [(shown[-1][0], cy1), (shown[0][0], cy1)],
                                     fill=col + (60,))
        img.alpha_composite(fill)
        d.line(shown, fill=col, width=7, joint="curve")
        x, y2 = shown[-1]
        d.ellipse([x - 13, y2 - 13, x + 13, y2 + 13], fill=col + (90,))
        d.ellipse([x - 7, y2 - 7, x + 7, y2 + 7], fill=(255, 255, 255))
        d.text((cx1, cy1 + 2), q.series_label, font=font("Regular", 26),
               fill=hex2rgb(self.st["muted"]), anchor="ra")
        return img

    def card(self, sc: TimedScene, t_in: float) -> Image.Image:
        visual = sc.data["visual"]
        anim = visual in ("stat", "chart") and t_in < 1.4
        key = (sc.index, "final")
        if not anim and key in self._card_cache:
            return self._card_cache[key]
        progress = min(t_in / 1.3, 1.0)
        if visual == "stat":
            img = self._stat_card(sc, progress)
        elif visual == "chart":
            img = self._chart_card(sc, progress)
        else:
            img = self._text_card(sc)
        if not anim:
            self._card_cache[key] = img
        return img

    # captions ------------------------------------------------------------
    def caption(self, words: list, active: int) -> Image.Image:
        key = (id(words), active)
        if key in self._cap_cache:
            return self._cap_cache[key]
        f = font("Bold", 70)
        space = f.getlength(" ") + 22
        lines, cur, cur_w = [], [], 0
        for i, w in enumerate(words):
            ww = f.getlength(w.text)
            if cur and cur_w + space + ww > 900:
                lines.append(cur)
                cur, cur_w = [], 0
            cur.append(i)
            cur_w += (space if cur_w else 0) + ww
        if cur:
            lines.append(cur)
        img = Image.new("RGBA", (self.W, 260), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        acc = hex2rgb(self.st["accent"])
        for li, idxs in enumerate(lines[:2]):
            total = sum(f.getlength(words[i].text) for i in idxs) + space * (len(idxs) - 1)
            x = (self.W - total) / 2
            y = 20 + li * 110
            for i in idxs:
                txt = words[i].text
                wlen = f.getlength(txt)
                if i == active:
                    d.rounded_rectangle([x - 14, y - 6, x + wlen + 14, y + 98], radius=18, fill=acc)
                    d.text((x, y), txt, font=f, fill=hex2rgb(self.st["bg_top"]))
                else:
                    d.text((x, y), txt, font=f, fill=(255, 255, 255), stroke_width=6,
                           stroke_fill=(0, 0, 0, 230))
                x += wlen + space
        self._cap_cache[key] = img
        return img

    # main loop -----------------------------------------------------------
    CARD_TOP, CARD_MAX_H, CAP_Y, PAPA_Y = 300, 575, 885, 1105

    def _fit_card(self, card: Image.Image) -> Image.Image:
        if card.height <= self.CARD_MAX_H:
            return card
        k = self.CARD_MAX_H / card.height
        return card.resize((int(card.width * k), self.CARD_MAX_H), Image.LANCZOS)

    def render(self, scenes: list[TimedScene], total: float, audio: Path, out: Path,
               outro_from: float, voice_wav: Path | None = None):
        n_frames = int(math.ceil(total * self.fps))
        groups = caption_groups(scenes)
        levels = speech_levels(voice_wav, n_frames, self.fps, scenes)
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{self.W}x{self.H}",
               "-r", str(self.fps), "-i", "-", "-i", str(audio),
               "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
               "-af", "apad", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        acc = hex2rgb(self.st["accent"])
        for fi in range(n_frames):
            t = fi / self.fps
            off = int((t * 9) % 400)
            frame = self.bg.crop((0, off, self.W, off + self.H))
            frame.alpha_composite(self.header, (0, 0))
            if self.ticker is not None:
                tx = int((t * 110) % self.ticker_seg)
                band = Image.new("RGBA", (self.W, 70), (0, 0, 0, 90))
                band.alpha_composite(self.ticker.crop((tx, 0, tx + self.W, 70)))
                frame.alpha_composite(band, (0, 170))
            frame.alpha_composite(self.footer, (0, 244))

            in_outro = t >= outro_from
            sc = next((s for s in scenes if s.start <= t < s.end), scenes[-1])
            expr = "happy" if in_outro else sc.data.get("expression", "happy")

            # Papa (drawn before captions so captions stay on top)
            entry = ease_out(t / 0.6)
            papa = self.papa.frame(t, expr, 0.0 if in_outro else levels[fi])
            px = (self.W - papa.width) // 2
            frame.alpha_composite(papa, (px, int(self.PAPA_Y + 820 * (1 - entry))))
            if t > 0.5:
                frame.alpha_composite(self.nametag, (20, self.PAPA_Y + 330))

            # info card (speech bubble)
            if not in_outro:
                t_in = t - sc.start
                card = self._fit_card(self.card(sc, t_in))
                k = ease_out(t_in / 0.35)
                side = -1 if sc.index % 2 else 1
                x = int((self.W - card.width) / 2 + side * 160 * (1 - k))
                frame.alpha_composite(with_alpha(card, k), (x, self.CARD_TOP))
                g = next((g for g in groups if g[0] <= t < g[1]), None)
                if g:
                    active = max((i for i, w in enumerate(g[2]) if w.start <= t), default=0)
                    frame.alpha_composite(self.caption(g[2], active), (0, self.CAP_Y))
            else:
                frame.alpha_composite(self.outro(t - outro_from), (60, self.CARD_TOP))

            # punch-in zoom at the start of each scene (and the hook)
            since = (t - outro_from) if in_outro else (t - sc.start)
            if since < 0.22 and t > 0.05:
                z = 1 + 0.045 * (1 - since / 0.22)
                zw, zh = int(self.W * z), int(self.H * z)
                frame = frame.resize((zw, zh), Image.BILINEAR).crop(
                    ((zw - self.W) // 2, (zh - self.H) // 2,
                     (zw - self.W) // 2 + self.W, (zh - self.H) // 2 + self.H))
            d = ImageDraw.Draw(frame)
            d.rectangle([0, 0, int(self.W * t / total), 10], fill=acc)
            proc.stdin.write(frame.convert("RGB").tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg encoding failed")

    def outro(self, t: float) -> Image.Image:
        if "outro" not in self._card_cache:
            img = Image.new("RGBA", (960, 560), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([0, 0, 959, 559], radius=44, fill=(16, 22, 44, 200),
                                outline=hex2rgb(self.st["accent"], 160), width=3)
            d.text((480, 110), "बेटा, दुनिया समझो", font=font("Bold", 70),
                   fill=hex2rgb(self.st["text"]), anchor="mm")
            d.text((480, 200), "रोज़ एक बात!", font=font("Bold", 70),
                   fill=hex2rgb(self.st["accent"]), anchor="mm")
            d.rounded_rectangle([190, 290, 770, 410], radius=60, fill=hex2rgb(self.st["accent"]))
            d.text((480, 350), "फॉलो करो", font=font("Bold", 58),
                   fill=hex2rgb(self.st["bg_top"]), anchor="mm")
            d.text((480, 480), self.cfg["channel"]["handle"], font=font("Medium", 44),
                   fill=hex2rgb(self.st["muted"]), anchor="mm")
            self._card_cache["outro"] = img
        k = ease_out(t / 0.35)
        return with_alpha(self._card_cache["outro"], k)


# ── utilities ──────────────────────────────────────────────────────────
def triangle(d: ImageDraw.ImageDraw, x: float, cy: float, s: float, up: bool, fill):
    pts = ([(x, cy + s), (x + s, cy - s), (x + 2 * s, cy + s)] if up
           else [(x, cy - s), (x + s, cy + s), (x + 2 * s, cy - s)])
    d.polygon(pts, fill=fill)


def speech_levels(wav_path: Path | None, n_frames: int, fps: int, scenes) -> list[float]:
    """0..1 mouth-opening per video frame, from voice loudness (or word timings)."""
    levels = np.zeros(n_frames)
    if wav_path and Path(wav_path).exists():
        with wave.open(str(wav_path)) as w:
            sr = w.getframerate()
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
        hop = sr / fps
        for i in range(n_frames):
            seg = data[int(i * hop):int((i + 1) * hop)]
            levels[i] = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    if levels.max() < 1e-3:                       # silent (offline preview) → fake from words
        for sc in scenes:
            for w in sc.words:
                for i in range(int(w.start * fps), min(n_frames, int(w.end * fps) + 1)):
                    levels[i] = 0.35 + 0.6 * abs(math.sin(i * 1.3))
        return levels.tolist()
    ref = np.percentile(levels[levels > 0], 92) or 1.0
    levels = np.clip(levels / ref, 0, 1)
    out, cur = [], 0.0
    for v in levels:                              # fast open, slower close
        cur = v if v > cur else cur * 0.55 + v * 0.45
        out.append(float(cur))
    return out


def downsample(series: list[float], n: int) -> list[float]:
    if len(series) <= n:
        return series
    step = len(series) / n
    return [series[int(i * step)] for i in range(n)] + [series[-1]]


def animate_number(value: str, p: float) -> str:
    """Count up the first number inside a string like '₹2.1 लाख करोड़' or '7.5%'."""
    m = re.search(r"\d[\d,]*\.?\d*", value)
    if not m or p >= 0.999:
        return value
    raw = m.group(0)
    num = float(raw.replace(",", ""))
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    cur = num * p
    txt = f"{cur:,.{decimals}f}" if "," in raw else f"{cur:.{decimals}f}"
    return value[:m.start()] + txt + value[m.end():]


def caption_groups(scenes: list[TimedScene], max_words: int = 4):
    """Split narration into short on-screen phrases: (start, end, words)."""
    groups = []
    for sc in scenes:
        cur = []
        for w in sc.words:
            cur.append(w)
            if len(cur) >= max_words or w.text[-1:] in ",.?!।":
                groups.append(cur)
                cur = []
        if cur:
            if len(cur) == 1 and groups and len(groups[-1]) < 6 and groups[-1][0] in sc.words:
                groups[-1].extend(cur)
            else:
                groups.append(cur)
    out = []
    for i, g in enumerate(groups):
        start = g[0].start
        end = groups[i + 1][0].start if i + 1 < len(groups) else g[-1].end + 0.3
        end = min(end, g[-1].end + 0.6)
        out.append((start, end, g))
    return out


def build_audio(parts: list[Path], gaps: list[float], tail: float, music: Path | None,
                music_volume: float, workdir: Path) -> Path:
    """Join scene clips with small pauses, add optional background music."""
    wavs = []
    for i, p in enumerate(parts):
        w = workdir / f"part{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p),
                        "-ar", "48000", "-ac", "1", str(w)], check=True)
        wavs.append(w)
    joined = workdir / "voice.wav"
    with wave.open(str(joined), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(48000)
        for w, gap in zip(wavs, gaps):
            with wave.open(str(w)) as src:
                out.writeframes(src.readframes(src.getnframes()))
            out.writeframes(b"\x00\x00" * int(48000 * gap))
        out.writeframes(b"\x00\x00" * int(48000 * tail))
    if not music:
        return joined
    mixed = workdir / "mix.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined),
                    "-stream_loop", "-1", "-i", str(music), "-filter_complex",
                    f"[1:a]volume={music_volume}[m];[0:a][m]amix=inputs=2:duration=first:"
                    f"dropout_transition=0:normalize=0[a]", "-map", "[a]", "-ar", "48000", str(mixed)],
                   check=True)
    return mixed
