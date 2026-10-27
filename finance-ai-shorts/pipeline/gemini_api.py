"""One place that sends requests to Gemini.

Order:
  1. Vertex AI (Google Cloud) with VERTEX_API_KEY  → paid from the Google Cloud free credit
  2. AI Studio with GEMINI_API_KEY                  → backup (prepaid AI Studio credit)
If Vertex doesn't know a model or refuses the key, the same request goes to AI Studio,
so a Reel never fails just because of the Vertex setup.
"""
from __future__ import annotations

import os

import requests

_said = set()


def available() -> bool:
    return bool(os.environ.get("VERTEX_API_KEY") or os.environ.get("GEMINI_API_KEY"))


# AI Studio shortcut names that Vertex AI doesn't know → real model names to try on Vertex
VERTEX_ALIASES = {
    "gemini-flash-latest": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                            "gemini-3-flash", "gemini-2.5-flash"],
    "gemini-flash-lite-latest": ["gemini-3.5-flash-lite", "gemini-2.5-flash-lite"],
}
_vertex_ok: dict[str, str] = {}      # alias → the Vertex name that worked
_vertex_bad: set[str] = set()        # Vertex names that returned 404


def _vertex_names(model: str) -> list[str]:
    if model in _vertex_ok:
        return [_vertex_ok[model]]
    names = VERTEX_ALIASES.get(model, [model])
    return [n for n in names if n not in _vertex_bad]


def _routes(model: str):
    vkey = os.environ.get("VERTEX_API_KEY")
    project = os.environ.get("GCP_PROJECT_ID", "").strip()
    if vkey:
        for name in _vertex_names(model):
            if project:
                yield ("Vertex AI", f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/"
                                    f"global/publishers/google/models/{name}:generateContent", vkey, name)
            yield ("Vertex AI", f"https://aiplatform.googleapis.com/v1/publishers/google/models/"
                                f"{name}:generateContent", vkey, name)
    gkey = os.environ.get("GEMINI_API_KEY")
    if gkey:
        yield ("AI Studio", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
               gkey, model)


def post(model: str, body: dict, timeout: int = 90) -> requests.Response:
    """Send one generateContent request; returns the first successful response,
    otherwise the last error response (callers handle status codes as before)."""
    last = None
    for route, url, key, name in _routes(model):
        if route == "Vertex AI" and name in _vertex_bad:
            continue
        try:
            r = requests.post(url, params={"key": key}, json=body, timeout=timeout)
        except requests.RequestException:
            if route == "AI Studio":
                raise
            continue
        if r.status_code < 400:
            if route == "Vertex AI":
                _vertex_ok[model] = name
            if (route, model) not in _said:
                _said.add((route, model))
                shown = model if name == model else f"{model} → {name}"
                print(f"  ({shown} via {route})")
            return r
        last = r
        if route == "Vertex AI":
            if r.status_code == 404:
                _vertex_bad.add(name)            # this name doesn't exist on Vertex
            if (name, r.status_code) not in _said:
                _said.add((name, r.status_code))
                print(f"  Vertex AI {r.status_code} for {name}: {r.text[:160]!r} — trying next")
    if last is None:
        raise RuntimeError("No Gemini key set (VERTEX_API_KEY or GEMINI_API_KEY)")
    return last
