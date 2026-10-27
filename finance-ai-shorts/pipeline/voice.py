"""Hindi voiceover with word-level timings (free Microsoft Edge neural voices)."""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

TICKS = 10_000_000  # edge-tts offsets are in 100-nanosecond units


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class SceneAudio:
    path: Path
    duration: float
    words: list[Word]


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _spread_words(text: str, duration: float, lead: float = 0.05) -> list[Word]:
    """Fallback timings: share the duration across words by length."""
    tokens = text.split()
    total = sum(len(t) + 2 for t in tokens) or 1
    t, words = lead, []
    usable = max(duration - lead - 0.15, 0.5)
    for tok in tokens:
        d = usable * (len(tok) + 2) / total
        words.append(Word(tok, t, t + d))
        t += d
    return words


def _align(text: str, boundaries: list[Word]) -> list[Word]:
    """Edge returns boundaries without punctuation; map them back onto the
    original tokens so captions keep commas, ? and । marks."""
    tokens = text.split()
    if not boundaries:
        return []
    if len(boundaries) == len(tokens):
        return [Word(tok, b.start, b.end) for tok, b in zip(tokens, boundaries)]
    # Counts differ (numbers / symbols split differently): map each token onto the
    # boundary that covers the same relative character position.
    b_lens = [max(len(b.text), 1) for b in boundaries]
    b_total = sum(b_lens)
    t_lens = [max(len(t.strip(".,!?।:;\"'()“”‘’-–—")), 1) for t in tokens]
    t_total = sum(t_lens)
    out, t_pos = [], 0
    for tok, tl in zip(tokens, t_lens):
        lo = (t_pos / t_total) * b_total
        hi = ((t_pos + tl) / t_total) * b_total
        t_pos += tl
        acc, start, end = 0, None, None
        for b, bl in zip(boundaries, b_lens):
            b_lo, b_hi = acc, acc + bl
            acc += bl
            if b_hi <= lo or b_lo >= hi:
                continue
            # interpolate inside the boundary so split tokens get separate times
            s = b.start + (b.end - b.start) * max(0, (lo - b_lo) / bl)
            e = b.start + (b.end - b.start) * min(1, (hi - b_lo) / bl)
            start = s if start is None else start
            end = e
        if start is None:
            start = end = out[-1].end if out else 0.0
        out.append(Word(tok, start, max(end, start + 0.05)))
    return out


async def _synth(text: str, voice: str, rate: str, pitch: str, out: Path) -> list[Word]:
    import edge_tts
    try:
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    except TypeError:  # older edge-tts versions always send word boundaries
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    words = []
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / TICKS
                words.append(Word(chunk["text"], s, s + chunk["duration"] / TICKS))
    return words


def synthesize(text: str, voice_cfg: dict, out: Path) -> SceneAudio:
    for attempt in range(3):
        try:
            boundaries = asyncio.run(_synth(text, voice_cfg["name"], voice_cfg["rate"],
                                            voice_cfg["pitch"], out))
            break
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  voice retry ({e.__class__.__name__})")
    dur = probe_duration(out)
    words = _align(text, boundaries) or _spread_words(text, dur)
    return SceneAudio(out, dur, words)


def synthesize_elevenlabs(text: str, voice_cfg: dict, out: Path) -> SceneAudio:
    """More expressive paid voice (ElevenLabs). Needs ELEVENLABS_API_KEY and a voice_id."""
    import base64
    import os
    import requests

    vid = voice_cfg["elevenlabs_voice_id"]
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"},
        json={"text": text, "model_id": voice_cfg.get("elevenlabs_model", "eleven_multilingual_v2"),
              **({"language_code": "hi"} if "multilingual_v2" not in
                 voice_cfg.get("elevenlabs_model", "eleven_multilingual_v2") else {}),
              "voice_settings": {"stability": voice_cfg.get("elevenlabs_stability", 0.4),
                                 "similarity_boost": 0.8,
                                 "style": voice_cfg.get("elevenlabs_style", 0.35),
                                 "speed": voice_cfg.get("elevenlabs_speed", 1.0),
                                 "use_speaker_boost": True}},
        timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text[:300]}")
    data = r.json()
    out.write_bytes(base64.b64decode(data["audio_base64"]))
    from . import usage
    usage.add("elevenlabs_characters", len(text))
    al = data.get("alignment") or data.get("normalized_alignment") or {}
    if isinstance(al.get("characters"), list) and al["characters"] and isinstance(al["characters"][0], dict):
        chars = [(c["character"], c["start_time_seconds"], c["end_time_seconds"]) for c in al["characters"]]
    else:
        chars = list(zip(al.get("characters", []), al.get("character_start_times_seconds", []),
                         al.get("character_end_times_seconds", [])))
    boundaries, cur, start, end = [], "", None, 0.0
    for ch, s, e in chars + [(" ", 0, 0)]:
        if ch.isspace():
            if cur:
                boundaries.append(Word(cur, start, end))
            cur, start = "", None
        else:
            cur += ch
            start = s if start is None else start
            end = e
    dur = probe_duration(out)
    return SceneAudio(out, dur, _align(text, boundaries) or _spread_words(text, dur))


def speak(text: str, voice_cfg: dict, out: Path) -> SceneAudio:
    if voice_cfg.get("provider") == "elevenlabs" and voice_cfg.get("elevenlabs_voice_id"):
        try:
            return synthesize_elevenlabs(text, voice_cfg, out)
        except Exception as e:                       # credits used up etc. → free voice
            print(f"  ElevenLabs failed ({e}); using free voice")
    return synthesize(text, voice_cfg, out)


def synthesize_offline(text: str, out: Path, words_per_sec: float = 2.7) -> SceneAudio:
    """Preview voice without internet: ffmpeg's built-in robotic English voice (flite)
    if available, else silence. Real runs use the natural Hindi voice."""
    import os
    if os.environ.get("PREVIEW_ROBOT_VOICE") != "1":      # robotic English voice only on request
        dur = max(1.5, len(text.split()) / words_per_sec + 0.4)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=24000:cl=mono", "-t", f"{dur:.2f}", "-q:a", "9", str(out)],
                       check=True)
        return SceneAudio(out, dur, _spread_words(text, dur))
    safe = text.replace("\\", " ").replace("'", "").replace(":", " ").replace(",", " ,")
    wav = out.with_suffix(".wav")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"flite=text='{safe}':voice=kal16", "-af", "atempo=1.12,volume=2.2",
                        "-ar", "24000", str(wav)], capture_output=True)
    if r.returncode == 0 and wav.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-q:a", "3",
                        str(out)], check=True)
        dur = probe_duration(out)
        return SceneAudio(out, dur, _spread_words(text, dur, lead=0.1))
    dur = max(1.5, len(text.split()) / words_per_sec + 0.4)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", f"{dur:.2f}", "-q:a", "9", str(out)],
                   check=True)
    return SceneAudio(out, dur, _spread_words(text, dur))
