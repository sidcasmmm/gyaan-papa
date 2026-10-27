"""Find space, science, and history ideas people are talking about right now.

Off by default (config trending.enabled). Instagram has no public trending feed, so
Gemini searches the web for a recent, sourced explainer topic. The curated list in
config.yaml is the normal path, because guessed science facts go wrong.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

PROMPT = """Today is {today} (India).

Use Google Search to find space, everyday science, school-level biology, or history topics
that people are discussing RIGHT NOW (the last 7 days, i.e. {month_year}). Put "{month_year}"
in your search queries and ignore any page older than 14 days.
Focus on questions Indian students and curious viewers ask: a mission, a "why does this happen",
a history anniversary, a clear misconception. Skip markets, medical advice, supplements, and politics.

Pick {n} topics that would make a great short Hinglish "Papa Explains" Reel.
Do NOT pick any of these recently covered topics:
{recent}

Rules: only real, verified facts from your search (with the date of the fact).
Every topic must be backed by a source published on or after {cutoff}; give that date.
No medical advice, no doses, no lab instructions, no invented quotes.

Reply with ONLY this JSON:
{{"topics": [
  {{"topic": "short Hinglish topic line for the Reel (like: 'Chandrayaan ne south pole ke paas kya kiya')",
    "why_trending": "one line: where/why it is trending this week",
    "source_date": "YYYY-MM-DD of the newest source that shows it is trending",
    "key_facts": ["fact with number and date", "..."]}}
]}}"""


def _ask(cfg: dict, prompt: str) -> str:
    from . import gemini_api, usage
    model = cfg.get("trending", {}).get("model") or cfg["writer"].get("gemini_model", "gemini-flash-latest")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.7}}
    r = gemini_api.post(model, body, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:200]}")
    data = r.json()
    um = data.get("usageMetadata", {})
    usage.add("gemini_input_tokens", um.get("promptTokenCount", 0))
    usage.add("gemini_output_tokens", um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0))
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _parse(text: str) -> list[dict]:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    topics = json.loads(text[start:end + 1]).get("topics", [])
    return [t for t in topics if isinstance(t, dict) and str(t.get("topic", "")).strip()]


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9₹]+", s.lower()) if len(w) > 3}


def _too_close(topic: str, recent: list[str]) -> bool:
    """True if this topic mostly repeats something we posted recently."""
    a = _words(topic)
    if not a:
        return False
    return any(len(a & _words(r)) / len(a) >= 0.6 for r in recent if r)


def _fresh(t: dict, max_days: int) -> bool:
    """Reject topics with no recent source date, or whose facts only mention past years."""
    now = datetime.now(IST)
    try:
        d = datetime.strptime(str(t.get("source_date", ""))[:10], "%Y-%m-%d").replace(tzinfo=IST)
    except ValueError:
        return False
    if not (now - timedelta(days=max_days) <= d <= now + timedelta(days=1)):
        return False
    text = " ".join([t["topic"], str(t.get("why_trending", ""))] + [str(f) for f in t.get("key_facts") or []])
    years = {int(y) for y in re.findall(r"\b(20[0-9]{2})\b", text)}
    return not years or max(years) >= now.year


def pick_topic(cfg: dict, recent_topics: list[str]) -> str | None:
    """Return a topic line (with key facts) for a trending-concept Reel, or None."""
    n = int(cfg.get("trending", {}).get("candidates", 5))
    recent = [t for t in recent_topics if t][-25:]
    now = datetime.now(IST)
    max_days = int(cfg.get("trending", {}).get("max_age_days", 14))
    prompt = PROMPT.format(today=now.strftime("%d %B %Y"), n=n, month_year=now.strftime("%B %Y"),
                           cutoff=(now - timedelta(days=max_days)).strftime("%d %B %Y"),
                           recent="\n".join(f"- {t}" for t in recent) or "(none yet)")
    for attempt in range(2):
        try:
            topics = _parse(_ask(cfg, prompt))
        except Exception as e:
            print(f"  trending lookup attempt {attempt + 1} failed: {e}")
            continue
        for t in topics:
            print(f"  trending: {t['topic']} [{t.get('source_date', '?')}] — {t.get('why_trending', '')}")
        for t in topics:
            if not _fresh(t, max_days):
                print(f"  ✗ too old / undated: {t['topic']}")
                continue
            if _too_close(t["topic"], recent):
                continue
            facts = "; ".join(str(f) for f in (t.get("key_facts") or [])[:5])
            line = t["topic"].strip()
            if t.get("why_trending"):
                line += f" (trending: {t['why_trending'].strip()})"
            if facts:
                line += f". Key facts: {facts}"
            return line
    return None
