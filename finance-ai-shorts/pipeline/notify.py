"""Optional: send yourself the finished video + links on Telegram (free).
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable; otherwise this does nothing."""
from __future__ import annotations

import os
from pathlib import Path

import requests


def telegram(text: str, video: Path | None = None):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    base = f"https://api.telegram.org/bot{token}"
    try:
        if video and video.exists() and video.stat().st_size < 48 * 1024 * 1024:
            with open(video, "rb") as f:
                requests.post(f"{base}/sendVideo", data={"chat_id": chat, "caption": text[:1000]},
                              files={"video": f}, timeout=120)
        else:
            requests.post(f"{base}/sendMessage", data={"chat_id": chat, "text": text[:4000]},
                          timeout=30)
    except Exception as e:
        print(f"  (telegram failed: {e})")
