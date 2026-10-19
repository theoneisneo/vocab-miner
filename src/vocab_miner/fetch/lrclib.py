"""Timed lyrics for a video list from LRCLIB (lrclib.net), a free, community-maintained lyrics database with a
public API meant for exactly this kind of use.

For each video: search by cleaned title + artist, keep results in the wanted language (the same title often
exists in several languages, and romanized Japanese is not English), prefer time-synced lyrics whose track
length matches the video (so the timing fits it), and save
    <out>/<video id>.lrc   time-synced, ready to use
    <out>/<video id>.txt   plain text: `vm transcribe --lyrics` adds the timing
Requests are spaced out and sent with an identifying User-Agent, as LRCLIB asks.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..albums import clean_title

API = "https://lrclib.net/api"
UA = "vocab-miner (language learning from your own material; https://github.com/theoneisneo/vocab-miner)"
PAUSE = 3.0
MAX_DIFF = 4.0          # seconds: synced lyrics only line up when the track length matches the video
ROMAJI = {"ni", "wo", "ga", "wa", "mo", "kara", "te", "ne", "kono", "sono", "naka", "nai", "desu", "shite",
          "mou", "boku", "kimi", "bokura", "dake", "made", "yori", "koto", "sae"}
SCRIPTS = {"ja": "぀-ヿ㐀-鿿", "zh": "㐀-鿿", "ko": "가-힯ᄀ-ᇿ"}


def artist_from_channel(channel: str) -> str:
    """"YOASOBI - Topic" -> "YOASOBI"; channel names often carry such suffixes."""
    return re.sub(r"\s*(-\s*topic|official(\s+channel)?|vevo|channel)\s*$", "", channel or "", flags=re.IGNORECASE).strip()


def norm(s: str) -> str:
    return re.sub(r"\W+", "", s.casefold())


def in_lang(text: str, lang: str) -> bool:
    """Is most of the text in `lang`? Script-based for ja/zh/ko; for Latin-script languages, Latin letters but
    not romanized Japanese."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    base = lang.split("-")[0]
    if base in SCRIPTS:
        return sum(bool(re.match(f"[{SCRIPTS[base]}]", c)) for c in letters) / len(letters) >= 0.5
    words = re.findall(r"[a-z]+", text.lower())
    if words and sum(w in ROMAJI for w in words) / len(words) > 0.03:
        return False
    return sum(c.isascii() for c in letters) / len(letters) >= 0.9


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for wait in (15, 45, None):     # the service is sometimes briefly unavailable
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", None)
            if wait is None or (code is not None and code < 500 and code != 429):
                raise
            time.sleep(wait)


def search(track: str, artist: str, duration: float | None, get: Callable = _get, pause: float = PAUSE) -> list[dict]:
    """Field search; when the server fails on it (it does for some titles), the exact lookup and a free-text
    search instead."""
    try:
        return get(f"{API}/search?" + urllib.parse.urlencode({"track_name": track, "artist_name": artist}))
    except urllib.error.HTTPError as e:
        if e.code < 500:
            raise
    results: list[dict] = []
    if duration:
        try:
            results.append(get(f"{API}/get?" + urllib.parse.urlencode(
                {"track_name": track, "artist_name": artist, "duration": round(duration)})))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    if pause:
        time.sleep(pause)
    return results + get(f"{API}/search?" + urllib.parse.urlencode({"q": f"{artist} {track}"}))


def pick(results: list[dict], track: str, artist: str, duration: float | None, lang: str) -> dict | None:
    """Best result: right track and artist, in `lang`; time-synced with a matching length first."""
    cands = []
    for r in results:
        lyrics = r.get("syncedLyrics") or r.get("plainLyrics") or ""
        if r.get("instrumental") or not lyrics or not in_lang(lyrics, lang):
            continue
        if artist and norm(artist) not in norm(r.get("artistName") or ""):
            continue
        if norm(r.get("trackName") or "") != norm(track):
            continue
        diff = abs((r.get("duration") or 0) - duration) if duration else 0.0
        synced = bool(r.get("syncedLyrics")) and diff <= MAX_DIFF
        cands.append((not synced, diff, -len(lyrics), r))
    if not cands:
        return None
    cands.sort(key=lambda c: c[:3])
    return {**cands[0][3], "_synced": not cands[0][0], "_diff": cands[0][1]}


@dataclass
class LyricsResult:
    id: str
    title: str
    status: str         # synced | plain | missing | error
    detail: str = ""


def fetch_lyrics(rows: list[dict], out: Path, lang: str, artist: str | None = None, get: Callable = _get,
                 pause: float = PAUSE, progress: Callable[[int, int, LyricsResult], None] | None = None
                 ) -> list[LyricsResult]:
    """rows: video list rows (id, title, channel, duration). Videos that already have a file in `out` are skipped."""
    out.mkdir(parents=True, exist_ok=True)
    results: list[LyricsResult] = []
    asked = 0
    for n, row in enumerate(rows, 1):
        vid, title = row["id"], clean_title(row.get("title") or "")
        if any((out / f"{vid}{s}").exists() for s in (".lrc", ".vtt", ".srt", ".txt")):
            continue
        if asked and pause:
            time.sleep(pause)
        asked += 1
        who = artist or artist_from_channel(row.get("channel") or "")
        dur = float(row["duration"]) if row.get("duration") else None
        try:
            best = pick(search(title, who, dur, get, pause), title, who, dur, lang)
        except (urllib.error.URLError, TimeoutError) as e:
            res = LyricsResult(vid, title, "error", str(e))
        else:
            if best is None:
                res = LyricsResult(vid, title, "missing")
            elif best["_synced"]:
                (out / f"{vid}.lrc").write_text(
                    f"[ti:{title}]\n[ar:{who}]\n[re:LRCLIB {best.get('id', '')}]\n"
                    + best["syncedLyrics"].strip() + "\n", encoding="utf-8")
                res = LyricsResult(vid, title, "synced", f"length differs {best['_diff']:.1f}s")
            else:
                (out / f"{vid}.txt").write_text(best["plainLyrics"].strip() + "\n", encoding="utf-8")
                res = LyricsResult(vid, title, "plain", "no timing: run vm transcribe --lyrics")
        results.append(res)
        if progress:
            progress(n, len(rows), res)
    return results
