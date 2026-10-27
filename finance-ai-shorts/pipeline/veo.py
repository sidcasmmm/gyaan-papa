"""Short moving video backgrounds with Google Veo (Vertex AI, paid from the Google Cloud credit).

animate(image, prompt, out, seconds) turns a scene picture into a few seconds of gentle
cinematic motion. Every failure raises, and the caller keeps the still picture instead.

    python -m pipeline.veo --probe        # find a Veo model that works with VERTEX_API_KEY
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

MODELS = ["veo-3.1-fast-generate-001", "veo-3.1-fast-generate-preview", "veo-3.0-fast-generate-001",
          "veo-3.1-generate-001", "veo-3.0-generate-001", "veo-2.0-generate-001"]
LOCATIONS = ["us-central1", "global"]
MOTION = ("Subtle cinematic motion only: slow camera push-in, gentle parallax, soft moving light, "
          "drifting particles. Keep the scene, composition, colours and art style exactly as in the "
          "image. No text, no letters, no new people, no talking, no scene cuts.")

_working: tuple[str, str] | None = None          # (model, location) that worked this run


def _key() -> str:
    k = os.environ.get("VERTEX_API_KEY")
    if not k:
        raise RuntimeError("VERTEX_API_KEY not set")
    return k


def _base(model: str, loc: str) -> str:
    project = os.environ.get("GCP_PROJECT_ID", "").strip()
    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
    if project:
        return f"https://{host}/v1/projects/{project}/locations/{loc}/publishers/google/models/{model}"
    return f"https://{host}/v1/publishers/google/models/{model}"


def _start(model: str, loc: str, prompt: str, image_png: bytes | None, seconds: int) -> str:
    inst = {"prompt": prompt}
    if image_png:
        inst["image"] = {"bytesBase64Encoded": base64.b64encode(image_png).decode(),
                         "mimeType": "image/png"}
    params = {"aspectRatio": "9:16", "sampleCount": 1, "durationSeconds": seconds,
              "personGeneration": "allow_adult"}
    if not model.startswith("veo-2"):
        params.update({"generateAudio": False, "resolution": "720p"})
    r = requests.post(f"{_base(model, loc)}:predictLongRunning", params={"key": _key()},
                      json={"instances": [inst], "parameters": params}, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"{model}@{loc} start {r.status_code}: {r.text[:300]}")
    return r.json()["name"]


def _wait(model: str, loc: str, op: str, timeout_s: int = 420) -> bytes:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(8)
        r = requests.post(f"{_base(model, loc)}:fetchPredictOperation", params={"key": _key()},
                          json={"operationName": op}, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"{model} poll {r.status_code}: {r.text[:300]}")
        d = r.json()
        if not d.get("done"):
            continue
        if "error" in d:
            raise RuntimeError(f"{model} failed: {json.dumps(d['error'])[:300]}")
        resp = d.get("response", {})
        vids = resp.get("videos") or resp.get("generatedSamples") or []
        for v in vids:
            data = v.get("bytesBase64Encoded") or (v.get("video") or {}).get("bytesBase64Encoded")
            if data:
                return base64.b64decode(data)
        reason = resp.get("raiMediaFilteredReasons") or resp
        raise RuntimeError(f"{model}: no video returned ({str(reason)[:300]})")
    raise RuntimeError(f"{model}: timed out after {timeout_s}s")


def animate(image_path: Path | None, prompt: str, out: Path, seconds: int = 4) -> Path:
    """Make `out` (mp4). Tries the model that already worked first, then the list."""
    global _working
    png = None
    if image_path is not None:
        from PIL import Image
        im = Image.open(image_path).convert("RGB")
        im.thumbnail((720, 1280))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        png = buf.getvalue()
    combos = ([_working] if _working else []) + [(m, l) for m in MODELS for l in LOCATIONS
                                                   if (m, l) != _working]
    errors = []
    for model, loc in combos:
        secs = seconds if not model.startswith("veo-2") else max(5, seconds)
        if not model.startswith("veo-2"):
            secs = min((4, 6, 8), key=lambda s: abs(s - seconds))
        try:
            op = _start(model, loc, f"{prompt}. {MOTION}", png, secs)
        except RuntimeError as e:
            errors.append(str(e))
            continue                                     # model/location not available → next
        data = _wait(model, loc, op)                     # a real failure here → caller keeps the picture
        out.write_bytes(data)
        _working = (model, loc)
        from . import usage
        usage.add("veo_seconds", secs)
        return out
    raise RuntimeError("no Veo model available: " + " | ".join(e[:220] for e in errors))


def pingpong(src: Path, out: Path, length: float) -> Path:
    """Forward + backward loop of the clip, at least `length` seconds long (smooth, no jump)."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter_complex",
                    "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0,setpts=PTS-STARTPTS[v]",
                    "-map", "[v]", "-an", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(out.with_suffix(".pp.mp4"))], check=True)
    loops = max(0, int(length // max(_dur(out.with_suffix(".pp.mp4")), 0.5)))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", str(loops), "-i",
                    str(out.with_suffix(".pp.mp4")), "-t", f"{length + 0.3:.2f}", "-an",
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


def _dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "csv=p=0", str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


class VideoBg:
    """Streams frames of a clip (already ≥ scene length) at the video's size and fps."""

    def __init__(self, path: Path, W: int, H: int, fps: int):
        self.W, self.H = W, H
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf",
             f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps={fps}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.last = None

    def next(self):
        from PIL import Image
        n = self.W * self.H * 3
        buf = self.proc.stdout.read(n) if self.proc else b""
        if len(buf) == n:
            self.last = Image.frombytes("RGB", (self.W, self.H), buf)
        elif self.proc:
            self.close()
        return self.last

    def close(self):
        if self.proc:
            self.proc.stdout.close()
            self.proc.kill()
            self.proc = None


def is_full_3d(vcfg: dict, now=None) -> bool:
    """True when this Reel should have EVERY scene moving: forced with FULL_3D=true, or the
    run falls inside full_3d_windows_ist before full_3d_until."""
    from datetime import datetime, timedelta, timezone
    env = os.environ.get("FULL_3D", "").strip().lower()
    if env in ("true", "false"):
        return env == "true"
    ist = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=5, minutes=30)))
    until = str(vcfg.get("full_3d_until", "")).strip()
    if not until or ist.date().isoformat() > until:
        return False
    mins = ist.hour * 60 + ist.minute
    for a, b in vcfg.get("full_3d_windows_ist") or []:
        if int(a[:2]) * 60 + int(a[3:]) <= mins <= int(b[:2]) * 60 + int(b[3:]):
            return True
    return False


def make_clips(scenes: list, timed: list, bgs: list[Path], cfg: dict, work: Path) -> dict[int, Path]:
    """Animate the opening scene + the longest other scenes. Returns {scene index: clip path}.
    Never raises: any problem → that scene keeps its still picture."""
    vcfg = cfg.get("veo", {})
    sample = os.environ.get("SAVE_SAMPLE", "").lower() == "true"
    if not (vcfg.get("enabled") or sample) or not os.environ.get("VERTEX_API_KEY"):
        return {}
    from datetime import date, datetime, timezone
    until = str(vcfg.get("until", "")).strip()
    if until and date.today().isoformat() > until:
        print(f"  Veo switched off after {until} (Google Cloud credit period over)")
        return {}
    usage_file = Path(__file__).resolve().parent.parent / "state" / "usage.json"
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        all_usage = json.loads(usage_file.read_text())
    except Exception:
        all_usage = {}
    used_s = all_usage.get(month, {}).get("veo_seconds", 0)
    total_s = sum(v.get("veo_seconds", 0) for v in all_usage.values() if isinstance(v, dict))
    price = float(vcfg.get("price_inr_per_second", 10))
    limit = float((vcfg.get("monthly_limit_overrides") or {}).get(month, vcfg.get("monthly_limit_inr", 6500)))
    total_limit = float(vcfg.get("total_limit_inr", 0) or 0)
    seconds = int(vcfg.get("seconds", 4))
    full = is_full_3d(vcfg)
    n = len(timed) if full else int(vcfg.get("clips_per_reel", 2))
    left = int((limit - used_s * price) // (seconds * price))
    if total_limit:
        left = min(left, int((total_limit - total_s * price) // (seconds * price)))
    if left <= 0:
        print(f"  Veo limit reached (month ≈ ₹{used_s * price:.0f} of ₹{limit:.0f}, "
              f"total ≈ ₹{total_s * price:.0f} of ₹{total_limit:.0f}) — still pictures")
        return {}
    n = min(n, left, len(timed))
    print(f"  Veo: {'FULLY 3D — ' if full else ''}{n} moving scene(s) planned")
    others = sorted(range(1, len(timed)), key=lambda i: timed[i].end - timed[i].start, reverse=True)
    order = [0] + others                               # opening first, then longest scenes
    pick, spare = order[:n], order[n:n + 2]            # spares replace scenes Google refuses
    from concurrent.futures import ThreadPoolExecutor

    def one(i):
        sc = scenes[i]
        prompt = sc.get("image_prompt") or sc.get("onscreen") or "cinematic science scene, no text"
        raw = work / f"veo{i}_raw.mp4"
        animate(bgs[i], prompt, raw, seconds)
        return i, pingpong(raw, work / f"veo{i}.mp4", timed[i].end - timed[i].start)

    clips = {}
    with ThreadPoolExecutor(max_workers=3 if full else 2) as ex:
        batch = pick
        while batch:
            futs = {ex.submit(one, i): i for i in batch}
            failed = 0
            for f, i in futs.items():
                try:
                    _, path = f.result()
                    clips[i] = path
                    print(f"  ✓ Veo video for scene {i + 1}")
                except Exception as e:
                    failed += 1
                    print(f"  ✗ Veo skipped scene {i + 1}: {str(e)[:220]}")
            batch, spare = spare[:failed], spare[failed:]   # try other scenes instead
    if clips:
        print(f"  Veo this month: ≈ ₹{(used_s + len(clips) * seconds) * price:.0f} of ₹{limit:.0f}"
              f" · total ≈ ₹{(total_s + len(clips) * seconds) * price:.0f} of ₹{total_limit:.0f}")
    return clips


def probe():
    """Try every model/location with a tiny text-only request and save one sample clip."""
    root = Path(__file__).resolve().parent.parent
    out = root / "state" / "veo_sample.mp4"
    log = []
    try:
        animate(None, "A glowing Indian rupee coin slowly spinning above a dark trading desk, "
                      "cinematic 3D cartoon style", out, seconds=4)
        log.append(f"OK model={_working} size={out.stat().st_size} dur={_dur(out):.1f}s")
    except Exception as e:
        log.append(f"FAILED: {e}")
    text = "\n".join(log)
    print(text)
    (root / "state" / "veo_probe.log").write_text(text + "\n")


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
