"""Tracks what each run uses on paid services, prints it, and keeps monthly totals
in state/usage.json (the workflow commits that file after every run)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "state" / "usage.json"
RUN: dict = {"gemini_input_tokens": 0, "gemini_output_tokens": 0, "claude_input_tokens": 0,
             "claude_output_tokens": 0, "elevenlabs_characters": 0, "ai_images": 0}


def add(key: str, n: int):
    RUN[key] = RUN.get(key, 0) + int(n or 0)


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def save_and_report(cfg: dict) -> list[str]:
    try:
        data = json.loads(FILE.read_text())
    except Exception:
        data = {}
    m = data.setdefault(_month(), {})
    for k, v in RUN.items():
        if k != "ai_images":                    # images are counted by images.py
            m[k] = m.get(k, 0) + v
    m["videos"] = m.get("videos", 0) + 1
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, indent=1))

    price_img = float(cfg.get("images", {}).get("price_inr_per_image", 3.0))
    el_quota = 30000
    lines = [
        "**This video used:**",
        f"- Gemini script: {RUN['gemini_input_tokens']:,} tokens in / {RUN['gemini_output_tokens']:,} out",
        f"- AI pictures: {RUN['ai_images']} (≈ ₹{RUN['ai_images'] * price_img:.0f})",
        f"- ElevenLabs voice: {RUN['elevenlabs_characters']:,} characters",
        f"**This month so far ({m['videos']} videos):** "
        f"{m.get('ai_images', 0)} AI pictures ≈ ₹{m.get('ai_images', 0) * price_img:.0f} · "
        f"ElevenLabs {m.get('elevenlabs_characters', 0):,} / {el_quota:,} characters · "
        f"Gemini script {m.get('gemini_input_tokens', 0) + m.get('gemini_output_tokens', 0):,} tokens",
    ]
    if RUN.get("veo_seconds"):
        vp = float(cfg.get("veo", {}).get("price_inr_per_second", 10))
        lines.insert(3, f"- Veo video: {RUN['veo_seconds']} s (≈ ₹{RUN['veo_seconds'] * vp:.0f}); "
                        f"this month {m.get('veo_seconds', 0)} s ≈ ₹{m.get('veo_seconds', 0) * vp:.0f}")
    if RUN["claude_input_tokens"]:
        lines.insert(2, f"- Claude script: {RUN['claude_input_tokens']:,} in / {RUN['claude_output_tokens']:,} out")
    return lines
