"""Re-post already-made Reels as Instagram Trial Reels (shown to non-followers first).

    python tools/trial_repost.py videos/            # folder with one sub-folder per old run

Each video short_YYYYMMDD_HHMM.mp4 is matched to the post in state/history.json made
right after it, and re-uses that post's exact Instagram caption (read back from Instagram).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import instagram  # noqa: E402

cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
if not cfg.get("uploads_enabled", False):
    sys.exit("Uploads are off (uploads_enabled: false). Nothing was sent to Instagram or Facebook.")
hist_path = ROOT / "state" / "history.json"
state = json.loads(hist_path.read_text())
graph = f"https://graph.facebook.com/{cfg['instagram']['graph_version']}"
auth = {"Authorization": f"OAuth {os.environ['IG_ACCESS_TOKEN']}"}


def shortcode(url: str) -> str:
    m = re.search(r"/(?:reel|p)/([^/?]+)", url or "")
    return m.group(1) if m else ""


def ig_captions() -> dict:
    """shortcode -> caption for the account's recent posts."""
    out, url = {}, f"{graph}/{os.environ['IG_USER_ID']}/media"
    params = {"fields": "caption,permalink", "limit": 50}
    for _ in range(3):
        r = requests.get(url, params=params, headers=auth, timeout=30)
        r.raise_for_status()
        for m in r.json().get("data", []):
            out[shortcode(m.get("permalink", ""))] = m.get("caption", "")
        url, params = r.json().get("paging", {}).get("next"), None
        if not url:
            break
    return out


def find_post(video: Path) -> dict | None:
    m = re.search(r"short_(\d{8}_\d{4})", video.name)
    if not m:
        return None
    made = datetime.strptime(m.group(1), "%Y%m%d_%H%M")
    best = None
    for p in state["posted"]:
        if not p.get("instagram"):
            continue
        at = datetime.fromisoformat(p["at"]).replace(tzinfo=None)
        gap = (at - made).total_seconds()
        if 0 <= gap <= 3 * 3600 and (best is None or gap < best[0]):
            best = (gap, p)
    return best[1] if best else None


def main(folder: str):
    videos = sorted(v for v in Path(folder).rglob("short_*.mp4") if not v.stem.endswith("_ig"))
    if not videos:
        sys.exit("No videos found")
    captions = ig_captions()
    failed = 0
    for i, video in enumerate(videos):
        post = find_post(video)
        if not post:
            print(f"❌ {video.name}: no matching Instagram post in history"); failed += 1; continue
        if post.get("instagram_trial", "").startswith("http"):
            print(f"↷ {video.name}: already has a Trial Reel ({post['instagram_trial']})"); continue
        caption = captions.get(shortcode(post["instagram"]))
        if not caption:
            print(f"❌ {video.name}: couldn't read the caption of {post['instagram']}"); failed += 1; continue
        if i:
            time.sleep(30)
        print(f"▶ {post['title']}  ({post['instagram']})")
        try:
            post["instagram_trial"] = instagram.publish_trial_reel(video, caption, cfg)
            print(f"  ✓ Trial Reel: {post['instagram_trial']}")
        except Exception as e:
            print(f"  ❌ Trial Reel failed: {e}"); failed += 1
        hist_path.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "videos")
