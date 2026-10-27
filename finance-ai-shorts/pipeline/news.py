"""Fetch the latest finance headlines from RSS feeds (no extra libraries needed)."""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (FinanceShortsBot; +https://github.com)"}


@dataclass
class Story:
    title: str
    summary: str
    link: str
    source: str
    published: datetime
    key: str = field(default="")

    def __post_init__(self):
        self.key = normalize(self.title)


def normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    words = [w for w in text.split() if len(w) > 2]
    return " ".join(sorted(set(words))[:12])


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(raw: str | None) -> datetime:
    if raw:
        try:
            d = parsedate_to_datetime(raw)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _source_name(url: str, item_source: str | None) -> str:
    if item_source:
        return item_source
    host = urlparse(url).netloc.replace("www.", "")
    return {
        "economictimes.indiatimes.com": "Economic Times",
        "livemint.com": "Mint",
        "business-standard.com": "Business Standard",
        "moneycontrol.com": "Moneycontrol",
    }.get(host, host)


def fetch_feed(url: str) -> list[Story]:
    resp = requests.get(url, headers=UA, timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    stories = []
    for it in items:
        def g(tag):
            el = it.find(tag)
            if el is None:
                el = it.find("{http://www.w3.org/2005/Atom}" + tag)
            return el.text if el is not None else None

        link = g("link") or ""
        if not link:
            el = it.find("{http://www.w3.org/2005/Atom}link")
            link = el.get("href", "") if el is not None else ""
        title = _clean(g("title"))
        src_el = it.find("source")
        source = _source_name(url, src_el.text if src_el is not None else None)
        # Google News appends " - Source" to titles
        if "news.google.com" in url and " - " in title:
            title, _, source = title.rpartition(" - ")
        if not title:
            continue
        stories.append(Story(
            title=title,
            summary=_clean(g("description") or g("summary"))[:600],
            link=link.strip(),
            source=source,
            published=_parse_date(g("pubDate") or g("published") or g("updated")),
        ))
    return stories


def latest_stories(feeds: list[str], max_age_hours: float, seen_keys: set[str],
                   blocklist: list[str], limit: int = 25) -> list[Story]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    pool: dict[str, Story] = {}
    for url in feeds:
        try:
            for s in fetch_feed(url):
                if s.published < cutoff or s.key in seen_keys or not s.key:
                    continue
                if any(b.lower() in s.title.lower() for b in blocklist):
                    continue
                pool.setdefault(s.key, s)
            print(f"  ✓ {url[:70]}")
        except Exception as e:  # one broken feed should never stop the run
            print(f"  ✗ {url[:70]} ({e.__class__.__name__})")
        time.sleep(0.3)
    stories = sorted(pool.values(), key=lambda s: s.published, reverse=True)
    return stories[:limit]
