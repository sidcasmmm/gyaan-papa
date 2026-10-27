"""Make Papa really talk with Hedra (Character-3): his face, head and body move with the voice.

Flow (Hedra API v3, paid from your prepaid API wallet at hedra.com/develop/billing):
  1. upload Papa's picture (on a green screen) and the voice   → POST /v3/files
  2. ask the price first, skip Hedra if over your limit          → POST /v3/models/{m}/estimate
  3. start the job                                               → POST /v3/models/{m}
  4. wait for it                                                 → GET  /v3/jobs/{job_id}
  5. download the talking video; render.py keys out the green.
If anything fails, the video is still made with the free animation.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image

API = "https://api.hedra.com/v3"
GREEN = (0, 255, 0)

PROMPT = ("A friendly young Indian man talks energetically and warmly straight to the camera, "
          "explaining an idea. Natural lip-sync, lively facial expressions, "
          "eyebrows and head move with the words, small natural shoulder movement. Camera is "
          "static. The background stays a flat solid pure green screen the whole time.")


def _headers() -> dict:
    return {"Authorization": f"Key {os.environ['HEDRA_API_KEY']}"}


def _check(r: requests.Response, step: str) -> dict:
    if r.status_code >= 400:
        raise RuntimeError(f"Hedra {step} failed ({r.status_code}): {r.text[:400]}")
    return r.json()


def start_image(base_png: Path, out: Path) -> Path:
    """Papa centred on a 9:16 green screen — big enough that his face is clear."""
    papa = Image.open(base_png).convert("RGBA")
    W, H = 1080, 1920
    k = min(W * 0.92 / papa.width, H * 0.80 / papa.height)
    papa = papa.resize((int(papa.width * k), int(papa.height * k)), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), GREEN + (255,))
    canvas.alpha_composite(papa, ((W - papa.width) // 2, H - papa.height))
    canvas.convert("RGB").save(out, quality=95)
    return out


def upload(path: Path) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{API}/files", headers=_headers(), files={"file": (path.name, f)},
                          timeout=180)
    return _check(r, f"upload {path.name}")["url"]


def make_talking_papa(base_png: Path, voice_audio: Path, workdir: Path, cfg: dict) -> Path:
    acfg = cfg.get("animation", {})
    model = acfg.get("hedra_model", "hedra-character-3")
    img = start_image(base_png, workdir / "papa_green.jpg")
    print("  uploading Papa + voice to Hedra")
    payload = {"input": {
        "prompt": PROMPT,
        "aspect_ratio": "9:16",
        "resolution": acfg.get("resolution", "540p"),
        "start_image": {"source": "url", "url": upload(img)},
        "audio": {"source": "url", "url": upload(voice_audio)},
    }}

    est = _check(requests.post(f"{API}/models/{model}/estimate", headers=_headers(),
                               json=payload, timeout=60), "estimate")
    cost = float(est.get("cost", 0))
    limit = float(acfg.get("max_cost_usd_per_video", 1.5))
    print(f"  Hedra price for this video: ${cost:.2f} (limit ${limit:.2f})")
    if cost > limit:
        raise RuntimeError(f"Hedra would cost ${cost:.2f}, above your limit ${limit:.2f}")

    digest = hashlib.sha1(voice_audio.read_bytes()).hexdigest()[:16]
    payload["idempotency_key"] = f"papa-{digest}"          # a retried run never pays twice
    job = _check(requests.post(f"{API}/models/{model}", headers=_headers(), json=payload,
                               timeout=60), "start")
    job_id = job["job_id"]
    print(f"  Hedra job {job_id} started")

    deadline = time.time() + 25 * 60
    while time.time() < deadline:
        time.sleep(8)
        j = _check(requests.get(f"{API}/jobs/{job_id}", headers=_headers(), timeout=30), "status")
        if j["status"] == "COMPLETED":
            outs = [o for o in j.get("outputs", []) if o.get("url")]
            if not outs:
                raise RuntimeError("Hedra finished but returned no video")
            out = workdir / "papa_talking.mp4"
            with requests.get(outs[0]["url"], stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(out, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            print(f"  ✓ Hedra video ready (charged ${j.get('cost', cost)})")
            return out
        if j["status"] == "FAILED":
            raise RuntimeError(f"Hedra job failed: {j.get('error')}")
    raise RuntimeError("Hedra took longer than 25 minutes")


class TalkingClip:
    """Streams the Hedra video frame by frame (scaled), keying out the green screen."""

    def __init__(self, path: Path, width: int):
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height,r_frame_rate", "-of", "csv=p=0", str(path)],
                               capture_output=True, text=True, check=True).stdout.strip().split(",")
        w, h = int(probe[0]), int(probe[1])
        num, den = probe[2].split("/")
        self.fps = float(num) / float(den or 1)
        self.W = width
        self.H = int(h * width / w) // 2 * 2
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", f"scale={self.W}:{self.H}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.idx = -1
        self.current: Image.Image | None = None

    def frame(self, t: float) -> Image.Image:
        want = int(t * self.fps)
        size = self.W * self.H * 3
        while self.idx < want:
            raw = self.proc.stdout.read(size)
            if len(raw) < size:          # clip ended → hold the last frame
                break
            self.idx += 1
            self.current = key_green(Image.frombytes("RGB", (self.W, self.H), raw))
        return self.current

    def close(self):
        self.proc.kill()


def key_green(img: Image.Image) -> Image.Image:
    import numpy as np
    from PIL import ImageFilter
    a = np.asarray(img, dtype=np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    greenness = g - np.maximum(r, b)
    alpha = np.clip(1 - (greenness - 30) / 50, 0, 1)
    g2 = np.where(greenness > 0, np.maximum(r, b) + np.clip(greenness, 0, 12), g)   # despill
    rgba = np.dstack([r, g2, b, alpha * 255]).astype(np.uint8)
    out = Image.fromarray(rgba, "RGBA")
    out.putalpha(out.getchannel("A").filter(ImageFilter.MinFilter(3)))
    return out
