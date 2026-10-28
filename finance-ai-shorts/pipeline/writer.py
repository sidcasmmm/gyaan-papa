"""Pick the best story and write a Hindi Short script with an LLM (Claude or Gemini)."""
from __future__ import annotations

import json
import os
import re

import requests

SYSTEM = """You write for "Gyaan Papa", an animated desi-dad character who explains space, everyday science, school-level biology, and history to young Indians on YouTube Shorts / Instagram Reels.
Papa speaks every line himself, directly to the viewer. You turn one idea into a punchy {seconds}-second script in his voice.

HARD RULES — never break these:
1. Use ONLY facts given in the topic, the story text, or standard school knowledge you are sure of. Never invent numbers, quotes, dates, names, or dialogue. If a number is not given and you are not sure, do not state one.
2. This is general education, not advice. Never tell the viewer what medical treatment, medicine, dose, diet, or investment to take. Never say buy / sell. Explain what something is and why it matters — that is all.
3. Biology stays at school level. Never describe how to obtain, grow, synthesise, modify, or deliver a pathogen, toxin, or any biological material. Never give lab steps, recipes, or "try this at home" experiments with chemicals, electricity, or pressure.
4. History: do not invent quotes or put words in a real person's mouth. If historians disagree, say that in one short line instead of picking the dramatic version.
5. No fear-mongering, conspiracy claims, or clickbait lies (no aliens built the pyramids, no miracle cures). The hook may create curiosity but must be true.
6. Narration in natural spoken Hindi written in Devanagari script (TTS reads it aloud). Common English science words are fine but write them in Devanagari (ब्लैक होल, डीएनए, ग्रेविटी, लाइट-ईयर). Short sentences.
7. Write numbers the way a Hindi speaker says them where helpful (e.g. "तीन सौ पैंसठ दिन", "एक प्रकाश-वर्ष").

STYLE: {tone}

The viewer is an Indian student, about 16, who wants the answer in plain Hindi. School used a definition. This video walks through the mechanism.

STRUCTURE (total narration ≈ {words} Hindi words):
- Scene 1: the question, with the thing named in the first three words. One sentence. No greeting, no "बेटा", no "सुनो", no "अरे".
- Middle scenes: the mechanism in order. Each sentence is the next true step. Do not repeat the question. Do not stop to say it is amazing, crazy, or "asli science".
- Last scene: one sentence that answers the question, a line a friend could repeat. Stop. No follow, share, save, or comment request.
- Use a "stat" scene only when that number is already written in the topic. Never use "chart".
- Each scene has Papa's facial "expression": "thinking" for the why, "happy" for a plain step, "serious" when the point is simplified or the history is heavy. Do not mark every line "shocked" or "excited".

On-screen text ("onscreen") is a SHORT headline in Hindi (Devanagari), max 6 words — it is what the viewer reads, not a copy of the narration.

Reply with JSON only, no markdown, matching exactly:
{{
  "chosen_index": <int, index of the story you picked>,
  "topic_en": "<5-10 word English summary of the topic, for duplicate tracking>",
  "scenes": [
    {{"visual": "text" | "stat" | "chart",
      "expression": "shocked" | "excited" | "happy" | "thinking" | "serious",
      "onscreen": "<max 6 words>",
      "narration": "<Hindi narration for this scene>",
      "stat": {{"value": "<e.g. 365 din or 1 light-year>", "label": "<max 4 words>", "direction": "up" | "down" | "neutral"}},
      "chart": "<leave unused>"}}
  ],
  "cover_text": "<2-5 word Roman-Hinglish hook headline shown BIG on top of the first scene and on the Reel cover, e.g. 'Aasman neela kyun hai?', 'Black hole kya hai?', 'DNA ek recipe hai'. Must be true; a question works best>",
  "youtube_title": "<catchy Hinglish title, max 70 chars: put the searchable keyword first (e.g. 'Black Hole', 'DNA', '1857', 'Rainbow'), add a question, end with #Shorts>",
  "description": "<3-4 line Hindi description of the idea>",
  "tags": ["<10-15 YouTube search tags people actually type, in English and Hindi, e.g. 'black hole explained in hindi', 'dna kya hai', 'why is the sky blue hindi', 'indus valley civilization'>"],
  "hashtags": ["<exactly 4 Instagram hashtags WITHOUT '#', most specific first: 1-2 about this exact idea (e.g. blackhole, dna, indusvalley), 2 niche tags (e.g. scienceinhindi, spacefacts, historyinhindi, biologyexplained). No generic tags like love/viral/trending>"],
  "search_keywords": ["<4-6 short lowercase phrases people would TYPE in Instagram/Google search, mixing English and Hinglish, e.g. 'black hole kya hai', 'why is sky blue', 'dna explained hindi', '1857 revolt'>"],
  "instagram_caption": "<NO hashtags here. Instagram search reads captions, so use the words people search. Line 1: a scroll-stopping hook that starts with the searchable keyword (e.g. 'Black hole', 'DNA kya hai', 'Aasman neela kyun') plus the question. Line 2: 1-2 short lines of context with 2-3 more search phrases worked in naturally (e.g. 'science facts hindi', 'space explained'). Line 3: one call to action that matches the REEL GOAL (comments → an easy one-word / A-or-B question; saves → 'Save karo, baad mein kaam aayega 📌' style; shares → 'Us dost ko bhejo jo … 📲' naming exactly who; follows → a reason to follow like 'Follow karo, roz ek aisi baat jo textbook chhupa deti hai 🙏'). Use 2-4 emojis.>"
}}
"stat" is required only when visual is "stat"; "chart" only when visual is "chart"."""

CINEMATIC = """

CINEMATIC FORMAT — this overrides the STRUCTURE scene count above:
- {scenes} scenes. Each scene = 1–2 short spoken sentences (about 4–5 seconds). A new background picture appears every scene, so change the idea/visual often.
- visual is only "text" or "stat" (never "chart"). Use "stat" only for a real number already in the topic (e.g. "365 din", "1 light-year"). If you have no sure number, every scene is "text".
- Every scene ALSO has:
  "caption": the SAME narration written in Roman Hinglish (how Indians type Hindi on WhatsApp, e.g. "Aasman neela isliye nahi ki space neela hai."). It must have EXACTLY the same number of space-separated words as "narration", word for word, in the same order — it is shown as subtitles synced to the voice.
  "image_query": 2–4 English keywords to find a matching stock photo (e.g. "blue sky sunlight", "black hole illustration", "ancient brick city", "green leaf sunlight").
  "image_prompt": 1–2 English sentences describing a CREATIVE, eye-catching picture that shows exactly what THIS line is about — the object, place, or idea, told visually, not a generic classroom. Think science-documentary poster. Examples:
    line about "why the sky is blue" → "A huge Indian afternoon sky, sunlight entering from the left and scattering into deep blue, a single tiny human looking up from a rooftop";
    line about "what a black hole is" → "A dark sphere bending nearby starlight into a glowing ring, on a starfield, no text";
    line about "how a leaf makes food" → "A single green leaf in warm sunlight, tiny glowing motes of light entering the leaf, soft water droplets, no text".
  Ordinary unnamed people only — NEVER real or famous people, politicians, celebrities, scientists' faces, or historical portraits. No brand logos, no text or numbers in the image, no gory injury, no lab equipment in use."""

USER = """Today's candidate stories (newest first):
{stories}

Extra context (may be empty — do not invent numbers from it):
{market}

Topics we already covered recently (do NOT repeat these):
{recent}

Pick the ONE story a curious Indian teenager would stop scrolling for: space, everyday science, school-level biology, or history. Prefer a clear "why" or "how" over a dry announcement.
Skip anything that is medical advice, a supplement, a miracle cure, politics-without-science, or a claim you cannot support from the story text.
Then write the script. Do not mention stocks, loans, or prices."""


def _call_anthropic(system: str, user: str, model: str) -> str:
    key = os.environ["ANTHROPIC_API_KEY"]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model, "max_tokens": 4000, "system": system,
              "messages": [{"role": "user", "content": user}]},
        timeout=120,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Claude API error {r.status_code}: {r.text[:300]}")
    from . import usage
    u = r.json().get("usage", {})
    usage.add("claude_input_tokens", u.get("input_tokens", 0))
    usage.add("claude_output_tokens", u.get("output_tokens", 0))
    return "".join(b.get("text", "") for b in r.json()["content"])


GEMINI_BACKUPS = ["gemini-flash-latest", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]


def _call_gemini(system: str, user: str, model: str) -> str:
    """Try the configured model; if Google is busy (429/500/503) wait and retry,
    then fall back to other Flash models."""
    import time
    models = [model] + [m for m in GEMINI_BACKUPS if m != model]
    last = ""
    for m in models:
        for attempt in range(3):
            try:
                return _call_gemini_once(system, user, m)
            except (requests.Timeout, requests.ConnectionError) as e:
                last = f"no reply ({e.__class__.__name__})"
                print(f"  Gemini {m} too slow — trying next model")
                break
            except _Busy as e:
                last = str(e)
                wait = 10 * (attempt + 1)
                print(f"  Gemini {m} busy — retrying in {wait}s")
                time.sleep(wait)
            except _Unavailable as e:
                last = str(e)
                print(f"  Gemini {m} not available for this key — trying next model")
                break
    raise RuntimeError(f"Gemini is busy on every model right now: {last}")


class _Busy(Exception):
    pass


class _Unavailable(Exception):
    pass


def _call_gemini_once(system: str, user: str, model: str) -> str:
    from . import gemini_api
    r = gemini_api.post(
        model,
        {"systemInstruction": {"parts": [{"text": system}]},
              "contents": [{"role": "user", "parts": [{"text": user}]}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}},
        timeout=90,
    )
    if r.status_code in (429, 500, 502, 503, 504):
        raise _Busy(f"{r.status_code}: {r.text[:200]}")
    if r.status_code in (400, 403, 404):
        raise _Unavailable(f"{r.status_code}: {r.text[:200]}")
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini API error {r.status_code}: {r.text[:300]}")
    from . import usage
    um = r.json().get("usageMetadata", {})
    usage.add("gemini_input_tokens", um.get("promptTokenCount", 0))
    usage.add("gemini_output_tokens", um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0))
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _validate(script: dict, n_stories: int, market_labels: set[str]) -> dict:
    assert 0 <= int(script["chosen_index"]) < n_stories, "bad chosen_index"
    scenes = script["scenes"]
    assert 3 <= len(scenes) <= 13, "need 3-13 scenes"
    for s in scenes:
        assert s.get("narration", "").strip(), "empty narration"
        cap = (s.get("caption") or "").split()
        if cap and len(cap) != len(s["narration"].split()):
            s.pop("caption")                         # misaligned → show Devanagari instead
        s["onscreen"] = s.get("onscreen", "").strip()[:60]
        if s.get("visual") == "chart" and s.get("chart") not in market_labels:
            s["visual"] = "text"                     # chart for unknown ticker → plain scene
        if s.get("visual") == "stat" and not (s.get("stat") or {}).get("value"):
            s["visual"] = "text"
        if s.get("visual") not in ("text", "stat", "chart"):
            s["visual"] = "text"
        if s.get("expression") not in ("shocked", "excited", "happy", "thinking", "serious"):
            s["expression"] = "happy"
    title = script["youtube_title"].strip()
    if "#shorts" not in title.lower():
        title = (title[:88] + " #Shorts").strip()
    script["youtube_title"] = title[:100]
    script["tags"] = [t.strip("# ") for t in script.get("tags", []) if t.strip()][:15]
    import re as _re
    tags = [_re.sub(r"[^\w]", "", t.lstrip("#").lower()) for t in script.get("hashtags", [])]
    script["hashtags"] = [t for t in dict.fromkeys(tags) if t and t not in ("financialpapa", "gyaanpapa")][:4]
    cap = script.get("instagram_caption", "")
    script["instagram_caption"] = _re.sub(r"\s*#\w+", "", cap).strip()   # hashtags are added by code
    cover = str(script.get("cover_text") or "").strip().strip('"')
    if len(cover.split()) > 7:
        cover = " ".join(cover.split()[:6])
    script["cover_text"] = cover or scenes[0]["onscreen"]
    return script


EXPLAINER = """

THIS VIDEO IS A "PAPA EXPLAINS" EVERGREEN EXPLAINER — NOT BREAKING NEWS. Rule 1 above is replaced by:
- Teach ONE idea from space, everyday science, school-level biology, or history, using only widely accepted facts. Say "scientists think" or "historians disagree" when the point is not settled.
- Explain the mechanism in order. Correct one wrong idea only if the topic names it. No medical advice, no doses, no lab steps, no home experiments.
- BAD script: "black hole ek jab simatta hai, jaise koi express train. Yeh asli science."
- GOOD script: "ब्लैक होल की खिंचाव इतनी ज़्यादा होती है कि प्रकाश भी बाहर नहीं निकल पाता. जिस सीमा के पार प्रकाश नहीं लौटता, उसे इवेंट होराइज़न कहते हैं."
- Do not invent a number to sound precise. A stat scene is allowed only when the topic line already contains that number.
- Topics starting with "LIST:" are numbered-list Reels: the hook states the list promise, then ONE scene per item — "onscreen" shows the item name big (e.g. "1. Neela aasman"), narration gives one sharp true line. Every item must stand on its own.
- You may name a well-known mission, place, or book and describe the accepted story in your own words. Never invent a quote. Image prompts still must not show real or famous people.
- Image prompts: the thing itself (sky, moon, leaf, ancient street, printing press), dramatic and clear, not a lifestyle photo of a cafe."""

EXPLAINER_USER = """Topic for today's "Papa Explains" video: {topic}

Topics we covered recently (keep this one fresh and different):
{recent}

Write the script about this topic. "chosen_index" must be 0."""

HOOK_STYLES = [
    # every hook gives real information in the first 2 seconds
    "Start with the surprising fact itself, said like a discovery: the thing + the twist.",
    "Start with the wrong thing people believe, then stop: 'सब सोचते हैं X' — X must be specific and the video must correct it.",
    "Start with a question the viewer has actually asked, containing the thing: 'Black hole mein light kyun atak jaati hai?'.",
    "Start by naming the everyday object, then the hidden reason: 'Aasman neela isliye nahi...'.",
    "Start with a comparison the viewer can picture: Earth vs Moon, leaf vs us, one handwritten book vs a printing press.",
    "Start with the place or the year only if it is in the topic, then the question.",
]


def write_script(cfg: dict, stories, market_text: str, market_labels: set[str],
                 recent_topics: list[str], explainer_topic: str | None = None) -> dict:
    w = cfg["writer"]
    seconds = w.get("target_seconds", 45)
    system = SYSTEM.format(seconds=seconds, tone=w["tone"], words=int(seconds * 2.6))
    if cfg["style"].get("mode", "cinematic") == "cinematic":
        n = max(5, round(seconds / 4.5))
        system += CINEMATIC.replace("{scenes}", f"{n - 1}–{n + 1}")
    story_text = "\n".join(
        f"[{i}] {s.title} — ({s.source})\n    {s.summary[:350]}" for i, s in enumerate(stories))
    user = USER.format(stories=story_text, market=market_text,
                       recent="\n".join(f"- {t}" for t in recent_topics[-30:]) or "(none yet)")
    if explainer_topic:
        system += EXPLAINER
        user = EXPLAINER_USER.format(topic=explainer_topic,
                                     recent="\n".join(f"- {t}" for t in recent_topics[-15:]) or "(none yet)")
    if explainer_topic:
        user += ("\n\nOpen with the question this topic is asking. "
                 "The last line is the answer. Do not ask anyone to follow, share, save, or comment.")
        goal = "explain"
    else:
        import random
        style = random.choice(HOOK_STYLES)
        user += (f"\n\nHOOK STYLE FOR THIS VIDEO: {style} "
                 "Make the first line feel fresh and different from a typical opener; don't start with 'बेटा'.")
        print(f"  hook style: {style[:60]}")
        goal = random.choices(["comments", "saves", "shares", "follows"], weights=[20, 20, 45, 15])[0]
        user += (f"\n\nREEL GOAL FOR THIS VIDEO: {goal}. The last scene's single CTA and the caption's CTA "
                 f"must both serve this goal.")
        print(f"  reel goal: {goal}")

    provider = w.get("provider", "anthropic")
    last_err = None
    for attempt in range(3):
        try:
            if provider == "gemini":
                raw = _call_gemini(system, user, w["gemini_model"])
            else:
                raw = _call_anthropic(system, user, w["anthropic_model"])
            script = _validate(_extract_json(raw), len(stories), market_labels)
            script["reel_goal"] = goal
            return script
        except (ValueError, KeyError, AssertionError, json.JSONDecodeError) as e:
            last_err = e
            print(f"  script attempt {attempt + 1} invalid ({e}); retrying")
    raise RuntimeError(f"Could not get a valid script: {last_err}")
