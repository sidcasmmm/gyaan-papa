"""Finance AI Shorts — one run = pick news → write Hindi script → voice → video → upload.

    python main.py              full run (uses API keys from environment variables)
    python main.py --dry-run    make the video but don't upload anything
    python main.py --offline    sample script + silent audio, no internet (preview the design)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from pipeline import images, market, news, notify, papa3d, render, sfx, voice, writer

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
SCENE_GAP, OUTRO = 0.08, 1.2   # short outro: a long silent end card makes people swipe away

DISCLAIMER = ("⚠️ यह वीडियो सिर्फ़ सामान्य जानकारी के लिए है — मेडिकल, कानूनी या निवेश सलाह नहीं। "
              "विज्ञान और इतिहास आसान भाषा में है; कोई बात पक्की लगे तो किताब या शिक्षक से जाँच लें।\n"
              "Script AI की मदद से लिखी गई है और आवाज़ AI-generated है।")


def load_state() -> dict:
    p = ROOT / "state" / "history.json"
    return json.loads(p.read_text()) if p.exists() else {"posted": []}


def save_state(state: dict):
    p = ROOT / "state" / "history.json"
    state["posted"] = state["posted"][-300:]
    p.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def summary(md: str):
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(md + "\n")


def sample_inputs():
    """Fake data for --offline previews."""
    import random
    rnd = random.Random(3)
    def walk(start, n=75, drift=0.0006):
        v, out = start, []
        for _ in range(n):
            v *= 1 + rnd.gauss(drift, 0.0018)
            out.append(v)
        return out
    s1, s2 = walk(24650), walk(81200)
    quotes = [market.Quote("NIFTY 50", "^NSEI", s1[-1], (s1[-1] / s1[0] - 1) * 100, s1, "Today"),
              market.Quote("SENSEX", "^BSESN", s2[-1], (s2[-1] / s2[0] - 1) * 100, s2, "Today"),
              market.Quote("USD/INR", "INR=X", 84.12, -0.08, walk(84.2, drift=-0.0001), "Today"),
              market.Quote("GOLD", "GC=F", 2654.3, 0.61, walk(2630), "Today")]
    story = news.Story("SAMPLE: Why the sky looks blue", "Sample story for preview.",
                       "https://example.com", "Sample", datetime.now(timezone.utc))
    script = {
        "chosen_index": 0, "topic_en": "why the sky looks blue",
        "scenes": [
            {"visual": "text", "expression": "shocked", "onscreen": "आसमान नीला क्यों",
             "narration": "आसमान नीला इसलिए नहीं कि अंतरिक्ष नीला है।",
             "caption": "Aasman neela isliye nahi ki antariksh neela hai.",
             "image_prompt": "A huge afternoon sky over an Indian rooftop, sunlight scattering into deep blue"},
            {"visual": "text", "expression": "thinking", "onscreen": "रोशनी बिखरती है",
             "narration": "सूरज की सफेद रोशनी हवा में छोटे कणों से टकरा कर बिखरती है।",
             "caption": "Suraj ki safed roshni hawa mein chhote kanon se takra kar bikharti hai.",
             "image_prompt": "Sunlight entering the atmosphere and scattering into blue rays, no text"},
            {"visual": "text", "expression": "excited", "onscreen": "नीली रोशनी ज़्यादा",
             "narration": "नीली रोशनी सबसे ज़्यादा इधर उधर बिखरती है, इसलिए आसमान नीला दिखता है।",
             "caption": "Neeli roshni sabse zyada idhar udhar bikharti hai, isliye aasman neela dikhta hai.",
             "image_prompt": "Deep blue sky with a tiny person looking up from a terrace"},
            {"visual": "text", "expression": "happy", "onscreen": "शाम को लाल",
             "narration": "शाम को रोशनी को लंबा रास्ता तय करना पड़ता है, इसलिए सूरज लाल दिखता है।",
             "caption": "Shaam ko roshni ko lamba rasta tay karna padta hai, isliye suraj laal dikhta hai.",
             "image_prompt": "An Indian sunset, the sun low and red, long light path through the sky"},
            {"visual": "text", "expression": "serious", "onscreen": "एक लाइन में",
             "narration": "याद रखो, नीला आसमान बिखरी हुई रोशनी है, रंग की दीवार नहीं।",
             "caption": "Yaad rakho, neela aasman bikhari hui roshni hai, rang ki deewar nahi.",
             "image_prompt": "Clear blue sky with soft clouds, simple and bright, no text"},
        ],
        "youtube_title": "आसमान नीला क्यों है? पापा समझाएंगे #Shorts",
        "description": "Sample preview video.",
        "tags": ["sample"],
        "instagram_caption": "Aasman neela kyun hai?",
        "cover_text": "Aasman neela kyun hai?",
    }
    return quotes, [story], script


def pick_explainer(cfg: dict, state: dict, args, force: bool = False) -> str | None:
    """Return a 'Papa Explains' topic for this run, or None for a news video."""
    ex = cfg.get("explainers", {})
    topics = ex.get("topics", [])
    if args.offline or args.sample:
        return None
    custom = (os.environ.get("CUSTOM_TOPIC") or "").strip()
    if custom:                                         # topic given by hand for this run
        return custom
    ctype = os.environ.get("CONTENT_TYPE", "auto") or "auto"
    # trending mode is off by default; the curated topic list is the normal path
    if ctype == "trending" or (cfg.get("trending", {}).get("enabled") and ctype == "auto"):
        from pipeline import trends
        print("① Finding a trending science or history topic")
        recent = ([p.get("topic", "") for p in state["posted"]]
                  + ([os.environ["AVOID_TOPIC"]] if os.environ.get("AVOID_TOPIC") else []))
        picked = trends.pick_topic(cfg, recent)
        if picked:
            return picked
        print("  no trending topic found — using the evergreen topic list this time")
        force = True
    if not ex.get("enabled") or not topics:
        return None
    if not force:
        if ctype == "news":
            return None
        if ctype != "explainer" and ex.get("slot", "mix") == "mix":
            # dynamic mix: never 2 explainers in a row, never more than 2 news in a row,
            # otherwise pick randomly (mostly news)
            import random
            kinds = ["explainer" if p.get("key", "").startswith("explainer:") else "news"
                     for p in state["posted"]]
            if kinds and kinds[-1] == "explainer":
                return None
            if kinds[-2:] == ["news", "news"]:
                pass                                   # time for an explainer
            elif random.random() >= float(ex.get("explainer_share", 0.35)):
                return None
        elif ctype != "explainer":                     # auto: by time of day
            slot = ex.get("slot", "evening")
            hour = datetime.now(IST).hour
            is_evening = hour >= 15
            if slot == "evening" and not is_evening:
                return None
            if slot == "morning" and is_evening:
                return None
            if slot == "none":
                return None
    done = {p["key"] for p in state["posted"] if p.get("key", "").startswith("explainer:")}
    fresh = [t for t in topics if "explainer:" + t.lower() not in done]
    if not fresh:                                      # all covered → start the list again
        fresh = topics
        state["posted"] = [p for p in state["posted"] if not p.get("key", "").startswith("explainer:")]
    return fresh[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="make the video, don't upload")
    ap.add_argument("--offline", action="store_true", help="sample data, no internet")
    ap.add_argument("--sample", action="store_true", help="sample script, REAL voice (no API keys needed)")
    ap.add_argument("--voice-name", help="try a different voice, e.g. en-IN-PrabhatNeural")
    ap.add_argument("--talking-clip", help="(testing) use an existing Hedra video instead of calling Hedra")
    ap.add_argument("--read", choices=["devanagari", "roman"], help="which script the voice reads")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))

    # GitHub sometimes starts scheduled runs hours late — don't post at odd hours
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and cfg.get("skip_late_runs", False):
        now = datetime.now(IST)
        mins = now.hour * 60 + now.minute
        windows = cfg.get("schedule_windows_ist", [["07:30", "09:30"], ["19:00", "21:00"]])
        ok = any(int(a[:2]) * 60 + int(a[3:]) <= mins <= int(b[:2]) * 60 + int(b[3:]) for a, b in windows)
        if not ok:
            summary(f"Skipped: GitHub started this scheduled run late ({now:%H:%M} IST), "
                    "outside the posting windows. Nothing was posted.")
            return
    if args.voice_name:
        cfg["voice"]["name"] = args.voice_name
        cfg["voice"]["provider"] = "edge"
    if args.read:
        cfg["voice"]["read"] = args.read
    if args.sample:
        args.dry_run = True
    state = load_state()

    # If a Reel already went out recently (e.g. started by hand because GitHub's timer was late),
    # a late scheduled run does nothing instead of posting a second Reel.
    automatic = (os.environ.get("GITHUB_EVENT_NAME") == "schedule"
                 or os.environ.get("AUTO_TIMER", "").lower() == "true")
    if automatic and state["posted"]:
        # a posting "day" runs 5 AM → 5 AM IST, so late-night Reels count for the evening before
        from datetime import timedelta

        def _day(ts):
            return (ts - timedelta(hours=5)).strftime("%Y-%m-%d")
        today = _day(datetime.now(IST))
        n_today = 0
        for p in state["posted"]:
            try:
                n_today += _day(datetime.fromisoformat(p["at"])) == today
            except Exception:
                pass
        if n_today >= int(cfg.get("max_posts_per_day", 4)):
            summary(f"Skipped: already {n_today} Reels today (limit {cfg.get('max_posts_per_day', 4)}).")
            return
        try:
            last = datetime.fromisoformat(state["posted"][-1]["at"])
            gap_h = (datetime.now(IST) - last).total_seconds() / 3600
            if gap_h < float(cfg.get("min_hours_between_posts", 4)):
                summary(f"Skipped: a Reel was already posted {gap_h:.1f} h ago "
                        f"({state['posted'][-1].get('topic', '')}). Nothing new posted.")
                return
        except Exception:
            pass
    stamp = datetime.now(IST).strftime("%Y%m%d_%H%M")
    work = ROOT / "out" / stamp
    work.mkdir(parents=True, exist_ok=True)

    # 1–3: data + script ---------------------------------------------------
    explainer = pick_explainer(cfg, state, args)
    if args.offline or args.sample:
        quotes, stories, script = sample_inputs()
    elif explainer:
        print(f"① Papa Explains: {explainer}")
        quotes = []
        stories = [news.Story(explainer, "", "", "Gyaan Papa", datetime.now(IST))]
        stories[0].key = "explainer:" + explainer.lower()
        print("③ Writing script")
        script = writer.write_script(cfg, stories, "", set(),
                                     [p.get("topic", "") for p in state["posted"]],
                                     explainer_topic=explainer)
    else:
        print("① Market data")
        quotes = market.get_quotes(cfg["market"]["tickers"])
        print("② News")
        seen = {p["key"] for p in state["posted"]} | {p["key"] for p in state.get("previewed", [])[-20:]}
        stories = news.latest_stories(cfg["news"]["feeds"], cfg["news"]["max_age_hours"], seen,
                                      cfg["news"].get("blocklist", []))
        if not stories:
            explainer = pick_explainer(cfg, state, args, force=True)
            if not explainer:
                summary("No new stories found — nothing to post this run.")
                return
            print(f"  no fresh news — making a Papa Explains video instead: {explainer}")
            quotes = []
            stories = [news.Story(explainer, "", "", "Gyaan Papa", datetime.now(IST))]
            stories[0].key = "explainer:" + explainer.lower()
        print(f"  {len(stories)} candidate stories")
        print("③ Writing script")
        script = writer.write_script(cfg, stories, market.as_prompt_text(quotes),
                                     {q.label for q in quotes},
                                     [p.get("topic", "") for p in state["posted"] + state.get("previewed", [])]
                                     + ([os.environ["AVOID_TOPIC"]] if os.environ.get("AVOID_TOPIC") else []),
                                     explainer_topic=explainer)
    story = stories[int(script["chosen_index"])]
    (work / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2))
    print(f"  Story: {story.title}")

    cinematic = cfg["style"].get("mode", "cinematic") == "cinematic"

    # 4: voice ---------------------------------------------------------------
    print("④ Voiceover")
    timed, t = [], 0.0
    parts, gaps = [], []
    n = len(script["scenes"])
    for i, sc in enumerate(script["scenes"]):
        mp3 = work / f"scene{i}.mp3"
        roman = cfg["voice"].get("read") == "roman" and sc.get("caption")
        tts_text = sc["caption"] if roman else sc["narration"]
        a = (voice.synthesize_offline(sc.get("caption") or sc["narration"], mp3) if args.offline
             else voice.speak(tts_text, cfg["voice"], mp3))
        shown = (sc.get("caption") or "").split()
        if cinematic and len(shown) == len(a.words):          # show Roman Hinglish subtitles
            words = [voice.Word(c, w.start + t, w.end + t) for c, w in zip(shown, a.words)]
        else:
            words = [voice.Word(w.text, w.start + t, w.end + t) for w in a.words]
        timed.append(render.TimedScene(sc, t, t + a.duration + SCENE_GAP, words, i, n))
        parts.append(a.path)
        gaps.append(SCENE_GAP)
        t += a.duration + SCENE_GAP
    outro_from, total = t, t + OUTRO
    music_vol = cfg["style"].get("background_music_volume", 0)
    music = (next(iter(sorted((ROOT / "assets" / "music").glob("*.mp3"))), None)
             if music_vol > 0 else None)
    audio = render.build_audio(parts, gaps, OUTRO, music, music_vol, work)
    if cfg.get("sound_effects", True):
        audio = sfx.mix(audio, sfx.events_for(timed), work / "final_audio.wav",
                        cfg.get("sound_effects_volume", 0.5))
    print(f"  {total:.1f}s total")

    # 5: video ---------------------------------------------------------------
    print("⑤ Rendering video")
    video = work / f"short_{stamp}.mp4"
    if cinematic:
        from pipeline.render_cinematic import CinematicRenderer
        print("  generating scene images")
        bgs = images.scene_images(script["scenes"], cfg, work, offline=args.offline,
                                   photo=False)
        clips = {}
        if not args.offline and not args.sample:
            from pipeline import veo
            clips = veo.make_clips(script["scenes"], timed, bgs, cfg, work)
        talking = Path(args.talking_clip) if args.talking_clip else None
        if talking is None and (cfg.get("animation", {}).get("provider") == "hedra" and not args.offline
                and os.environ.get("HEDRA_API_KEY") and papa3d.available()):
            print("  animating Papa with Hedra")
            try:
                from pipeline import hedra
                speech = work / "voice_for_hedra.wav"          # voice only, no outro silence
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(work / "voice.wav"),
                                "-t", f"{outro_from:.2f}", str(speech)], check=True)
                talking = hedra.make_talking_papa(papa3d.PAPA_DIR / "base.png", speech, work, cfg)
            except Exception as e:
                print(f"  ✗ Hedra skipped ({e}) — using free animation")
        CinematicRenderer(cfg, story.source, bgs, talking, hook=script.get("cover_text"),
                          clips=clips, goal=script.get("reel_goal")).render(
            timed, total, audio, video, outro_from, voice_wav=work / "voice.wav")
    else:
        render.Renderer(cfg, quotes, story.source).render(timed, total, audio, video, outro_from,
                                                          voice_wav=work / "voice.wav")
    print(f"  ✓ {video.relative_to(ROOT)} ({video.stat().st_size / 1e6:.1f} MB)")

    # 6: upload --------------------------------------------------------------
    tags = list(dict.fromkeys(script.get("tags", []) + cfg["youtube"]["default_tags"]))
    # Instagram allows max 5 hashtags: brand tag + 4 topic tags chosen by the AI
    topic_tags = script.get("hashtags") or ["scienceinhindi", "spacefacts", "historyinhindi", "biologyexplained"]
    ig_hashtags = " ".join("#" + t for t in (["gyaanpapa"] + topic_tags)[:5])
    yt_first = [t.replace(" ", "") for t in tags if " " not in t][:2]
    hashtags = " ".join("#" + t for t in dict.fromkeys(["Shorts"] + topic_tags[:2] + yt_first + ["GyaanPapa"]))
    photo_credit = {"pixabay": "\nPhotos: Pixabay", "pexels": "\nPhotos: Pexels"}.get(
        cfg.get("images", {}).get("provider", ""), "")
    src_line = (f"स्रोत / Source: {story.source} — {story.link}" if story.link
                else "Papa Explains — general information only")
    description = (f"{script['description']}\n\n{src_line}{photo_credit}"
                   f"\n\n{DISCLAIMER}\n\n{hashtags}")
    kw = [k.strip() for k in (script.get("search_keywords") or []) if str(k).strip()][:6]
    kw_line = f"({', '.join(kw)})\n\n" if kw else ""        # searchable keywords, like top finance pages
    ig_caption = (f"{script['instagram_caption']}\n\n{ig_hashtags}\n\n{kw_line}"
                  + (f"स्रोत: {story.source}\n" if story.link else "") + DISCLAIMER)
    results, errors = {}, []
    public = cfg.get("publish_mode", "review") == "auto"
    if not cfg.get("uploads_enabled", False):
        print("⑥ Uploads are off (uploads_enabled: false). Nothing sent to YouTube, Instagram, or Facebook.")
        args.dry_run = True

    if args.dry_run and not args.offline and not args.sample:
        state.setdefault("previewed", []).append({"key": story.key, "topic": script.get("topic_en", story.title),
                                                  "at": datetime.now(IST).isoformat(timespec="minutes")})
        state["previewed"] = state["previewed"][-20:]
        save_state(state)                         # so the next real run picks a different story
    if args.offline or args.dry_run:
        print("⑥ Dry run — skipping uploads")
    else:
        print(f"⑥ Uploading ({'PUBLIC' if public else 'review mode: private'})")
        if cfg["platforms"].get("youtube") and not os.environ.get("YT_REFRESH_TOKEN"):
            print("  YouTube not connected yet (no YT_REFRESH_TOKEN secret) — skipping")
        elif cfg["platforms"].get("youtube"):
            try:
                from pipeline import youtube
                results["youtube"] = youtube.upload(video, script["youtube_title"], description,
                                                    tags, cfg, public)
                print(f"  ✓ YouTube: {results['youtube']}")
            except Exception as e:
                errors.append(f"YouTube: {e}")
                traceback.print_exc()
        ig_now = public or cfg.get("instagram", {}).get("post_in_review_mode", False)
        if cfg["platforms"].get("instagram") and ig_now and not os.environ.get("IG_ACCESS_TOKEN"):
            print("  Instagram not connected yet (no IG_ACCESS_TOKEN secret) — skipping")
        elif cfg["platforms"].get("instagram") and ig_now:
            try:
                from pipeline import instagram
                results["instagram"] = instagram.publish_reel(video, ig_caption, cfg)
                print(f"  ✓ Instagram: {results['instagram']}")
            except Exception as e:
                errors.append(f"Instagram: {e}")
                traceback.print_exc()
            if cfg["instagram"].get("also_post_trial_reel") and "instagram" in results:
                try:                                      # extra copy for non-followers; never fails the run
                    time.sleep(30)
                    results["instagram_trial"] = instagram.publish_trial_reel(video, ig_caption, cfg)
                    print(f"  ✓ Instagram Trial Reel: {results['instagram_trial']}")
                except Exception as e:
                    results["instagram_trial"] = f"⚠️ not posted: {str(e)[:200]}"
                    traceback.print_exc()

        if results or not errors:
            state["posted"].append({"key": story.key, "topic": script.get("topic_en", story.title),
                                    "title": script["youtube_title"], "source_url": story.link,
                                    "at": datetime.now(IST).isoformat(timespec="minutes"),
                                    **results})
            save_state(state)

    md = [f"### {script['youtube_title']}", f"- Story: {story.title} ({story.source})",
          f"- Length: {total:.0f}s", f"- Mode: {cfg.get('publish_mode')}"]
    md += [f"- {k}: {v}" for k, v in results.items()]
    md += [f"- ❌ {e}" for e in errors]
    from pipeline import usage
    md += [""] + usage.save_and_report(cfg)
    summary("\n".join(md))
    notify.telegram("\n".join(md) + ("\n\nReview mode: check YouTube Studio and make it public."
                                     if not public and not args.dry_run else ""), video)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
