"""Publish a Reel with the Instagram Graph API (resumable upload of a local file —
no need to host the video anywhere)."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import requests


def instagram_safe_copy(video: Path) -> Path:
    """Re-encode to Instagram's recommended Reels spec: H.264 High@4.1, 30 fps,
    closed GOP, yuv420p, stereo AAC 44.1 kHz, moov atom at the start."""
    out = video.with_name(video.stem + "_ig.mp4")
    if out.exists() and out.stat().st_mtime >= video.stat().st_mtime:
        return out                                        # already made (e.g. for the Trial Reel copy)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
                    "-c:v", "libx264", "-profile:v", "high", "-level", "4.1",
                    "-pix_fmt", "yuv420p", "-r", "30", "-g", "60", "-keyint_min", "60",
                    "-sc_threshold", "0", "-b:v", "6M", "-maxrate", "8M", "-bufsize", "12M",
                    "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
                    "-movflags", "+faststart", str(out)], check=True)
    return out


def _attempt(video: Path, caption: str, cfg: dict, ai_label: bool,
             trial_strategy: str | None = None) -> str:
    token = os.environ["IG_ACCESS_TOKEN"]
    ig_user = os.environ["IG_USER_ID"]
    ver = cfg["instagram"]["graph_version"]
    graph = f"https://graph.facebook.com/{ver}"
    auth = {"Authorization": f"OAuth {token}"}

    # 1) create an upload container
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
              "access_token": token}
    if trial_strategy:                                    # Trial Reel: shown to non-followers first
        params["trial_params"] = json.dumps({"graduation_strategy": trial_strategy})
    else:
        params["share_to_feed"] = str(cfg["instagram"].get("share_to_feed", True)).lower()
    cover_ms = cfg["instagram"].get("cover_offset_ms")
    if cover_ms is not None:                              # cover = frame with the hook title + Papa
        params["thumb_offset"] = str(int(cover_ms))
    if ai_label:
        params["is_ai_generated"] = "true"
    r = requests.post(f"{graph}/{ig_user}/media", data=params, timeout=60)
    if r.status_code >= 400 and "is_ai_generated" in params:
        params.pop("is_ai_generated")                     # older API versions reject it
        r = requests.post(f"{graph}/{ig_user}/media", data=params, timeout=60)
    _check(r, "create container")
    container = r.json()["id"]
    upload_uri = r.json().get("uri") or f"https://rupload.facebook.com/ig-api-upload/{ver}/{container}"

    # 2) upload the bytes (sent in one piece with an exact length)
    data = video.read_bytes()
    r = requests.post(upload_uri, data=data, timeout=600, headers={
        **auth, "offset": "0", "file_size": str(len(data)),
        "Content-Type": "application/octet-stream", "Content-Length": str(len(data))})
    _check(r, "upload video")

    # 3) wait for Instagram to process it
    for _ in range(60):
        r = requests.get(f"{graph}/{container}", params={"fields": "status_code,status"},
                         headers=auth, timeout=30)
        _check(r, "check status")
        code = r.json().get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing failed: {r.json()}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram processing timed out")

    # 4) publish
    r = requests.post(f"{graph}/{ig_user}/media_publish", headers=auth,
                      data={"creation_id": container}, timeout=60)
    _check(r, "publish")
    media_id = r.json()["id"]
    r = requests.get(f"{graph}/{media_id}", params={"fields": "permalink"}, headers=auth, timeout=30)
    return r.json().get("permalink", f"instagram media {media_id}")


def publish_reel(video: Path, caption: str, cfg: dict, trial_strategy: str | None = None) -> str:
    safe = instagram_safe_copy(video)
    print(f"  Instagram copy: {safe.stat().st_size / 1e6:.1f} MB")
    try:
        return _attempt(safe, caption, cfg, ai_label=cfg.get("disclose_ai", True),
                        trial_strategy=trial_strategy)
    except RuntimeError as e:
        if "ProcessingFailedError" not in str(e) and "processing failed" not in str(e):
            raise
        print(f"  Instagram rejected the upload ({e}); retrying once with a fresh container")
        time.sleep(15)
        return _attempt(safe, caption, cfg, ai_label=False, trial_strategy=trial_strategy)


def publish_trial_reel(video: Path, caption: str, cfg: dict) -> str:
    """Post the same video again as an Instagram Trial Reel (non-followers only).
    MANUAL = stays a trial until you graduate it in the app; SS_PERFORMANCE = Instagram
    shares it to followers automatically if it performs well."""
    strategy = str(cfg["instagram"].get("trial_reel_graduation", "MANUAL")).upper()
    return publish_reel(video, caption, cfg, trial_strategy=strategy)


def _check(r: requests.Response, step: str):
    if r.status_code >= 400:
        raise RuntimeError(f"Instagram {step} failed ({r.status_code}): {r.text[:400]}")
