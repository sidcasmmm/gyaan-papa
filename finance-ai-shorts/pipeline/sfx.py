"""Original sound effects, synthesised from scratch (no copyright worries):
whoosh on every scene change, ding when a number pops up, cha-ching on money lines."""
from __future__ import annotations

import re
import wave
from pathlib import Path

import numpy as np

SR = 48000
MONEY = re.compile(r"₹|रुपये|रुपए|करोड़|लाख|पैसा|पैसे|crore|lakh|paisa|paise|rupee", re.I)


def _env(n, attack=0.005, decay=6.0):
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-t * decay)


def whoosh(dur=0.42):
    n = int(SR * dur)
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 1, n)
    # sweep a simple band-pass by mixing differently-smoothed noise
    out = np.zeros(n)
    t = np.arange(n) / n
    for k, w in ((3, 1.0), (9, 0.6), (25, 0.3)):
        sm = np.convolve(noise, np.ones(k) / k, "same")
        out += w * sm * np.sin(np.pi * t) ** (1 + k / 10)
    out *= np.sin(np.pi * t) ** 1.5
    return 0.55 * out / (np.abs(out).max() + 1e-9)


def ding(freq=1568.0, dur=0.7):
    n = int(SR * dur)
    t = np.arange(n) / SR
    tone = (np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * freq * 2.76 * t)
            + 0.2 * np.sin(2 * np.pi * freq * 5.4 * t))
    return 0.45 * tone * _env(n, decay=5.5) / 1.6


def cash():
    """'cha-ching': quick metallic click, then two bright bell hits."""
    click_n = int(SR * 0.06)
    rng = np.random.default_rng(7)
    click = rng.normal(0, 1, click_n) * _env(click_n, decay=60) * 0.5
    out = np.zeros(int(SR * 0.9))
    out[:click_n] += click
    for start, f in ((0.08, 2093.0), (0.18, 2637.0)):
        b = ding(f, 0.7)
        s = int(SR * start)
        out[s:s + len(b)] += b[:len(out) - s] * 0.8
    return out


def events_for(timed_scenes) -> list[tuple[float, str]]:
    ev = []
    for sc in timed_scenes:
        if sc.index > 0:
            ev.append((max(0.0, sc.start - 0.12), "whoosh"))
        text = sc.data.get("narration", "") + " " + sc.data.get("caption", "")
        if (sc.data.get("stat") or {}).get("value"):
            ev.append((sc.start + 0.3, "ding"))
        elif MONEY.search(text):
            ev.append((sc.start + 0.25, "cash"))
    return ev


def mix(in_wav: Path, events: list[tuple[float, str]], out_wav: Path, volume: float = 0.5) -> Path:
    with wave.open(str(in_wav)) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    if ch > 1:
        data = data.reshape(-1, ch).mean(1)
    if sr != SR:
        idx = np.arange(0, len(data), sr / SR)
        data = np.interp(idx, np.arange(len(data)), data)
    sounds = {"whoosh": whoosh(), "ding": ding(), "cash": cash()}
    for t, name in events:
        s = int(t * SR)
        snd = sounds[name] * volume
        e = min(len(data), s + len(snd))
        if s < len(data):
            data[s:e] += snd[:e - s]
    data = np.clip(data, -1, 1)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((data * 32767).astype(np.int16).tobytes())
    return out_wav
