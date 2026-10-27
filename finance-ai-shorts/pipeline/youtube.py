"""Upload a Short to YouTube with the official YouTube Data API v3."""
from __future__ import annotations

import os
import time
from pathlib import Path


def _credentials():
    from google.oauth2.credentials import Credentials
    return Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )


def upload(video: Path, title: str, description: str, tags: list[str], cfg: dict,
           public: bool, thumbnail: Path | None = None) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    yt = build("youtube", "v3", credentials=_credentials(), cache_discovery=False)
    status = {
        "privacyStatus": "public" if public else "private",
        "selfDeclaredMadeForKids": cfg["youtube"].get("made_for_kids", False),
    }
    if cfg.get("disclose_ai", True):
        status["containsSyntheticMedia"] = True
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags[:30],
            "categoryId": cfg["youtube"]["category_id"],
            "defaultLanguage": "hi",
            "defaultAudioLanguage": "hi",
        },
        "status": status,
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024,
                            resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response, retries = None, 0
    while response is None:
        try:
            _, response = req.next_chunk()
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retries < 5:
                retries += 1
                time.sleep(2 ** retries)
                continue
            raise
    vid = response["id"]
    if thumbnail and thumbnail.exists():
        try:  # custom thumbnails need a verified channel; ignore if not allowed
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail))).execute()
        except HttpError as e:
            print(f"  (thumbnail skipped: {e.resp.status})")
    return f"https://youtube.com/shorts/{vid}"
