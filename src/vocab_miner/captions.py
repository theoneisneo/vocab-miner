"""Timing for lyrics text from YouTube's automatic captions, when Whisper is not installed or not used.

YouTube's speech recognition writes a caption track for many videos, with a time for each word. Its words are
often wrong for singing, but only their times are used: the lyrics text is aligned to them the same way as to
Whisper's words (transcribe.align), and every line keeps the given text. Many music videos have no such track
(no speech recognition, or a wrong language detected), and the result is only kept when enough lines matched.

Only the original-language recognition is used (the "<lang>-orig" track, or "<lang>" when the video's own
language is <lang>); machine-translated tracks have no word times.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from .fetch import youtube
from .sources import read_text
from .sources.subtitle import CUE_TIMING, _ts
from .transcribe import Line, Word, align_with_coverage

MARK = "[re:vocab-miner: lyrics timed with YouTube's automatic captions]"
MIN_COVERAGE = 0.5          # share of lines that must match something recognised
# caption word times come late (two songs measured against good timing: lines started 0.4 s and ~0.9 s late)
LEAD = 0.4
WORD_TIME = re.compile(r"<(\d+:\d{2}:\d{2}\.\d{3})>")
TAG = re.compile(r"</?c[^>]*>")


def caption_words(vtt: str) -> list[Word]:
    """Words with times from an automatic-caption .vtt. Each cue repeats the line before it and adds a new last
    line, where <hh:mm:ss.mmm> marks when each following word starts; 10 ms cues only repeat text."""
    words: list[Word] = []
    cues: list[tuple[float, float, list[str]]] = []
    for line in vtt.split("\n"):                   # a cue's text may start with a blank line: split on timings
        if m := CUE_TIMING.match(line):
            g = m.groups()
            cues.append((_ts(*g[:4]), _ts(*g[4:]), []))
        elif cues:
            cues[-1][2].append(line)
    for start, end, lines in cues:
        body = [ln for ln in lines if ln.strip()]
        if end - start < 0.05 or not body:
            continue
        new = TAG.sub("", body[-1])
        parts = WORD_TIME.split(new)               # text, time, text, time, text ...
        times = [start] + [_ts(*re.match(r"(\d+):(\d{2}):(\d{2})\.(\d{3})", t).groups()) for t in parts[1::2]]
        texts = parts[0::2]
        for k, (t, text) in enumerate(zip(times, texts)):
            if text.strip():
                nxt = times[k + 1] if k + 1 < len(times) else end
                words.append(Word(text.strip(), t, max(nxt, t)))
    return words


def pick_track(info: dict, lang: str) -> str | None:
    auto = info.get("automatic_captions") or {}
    if f"{lang}-orig" in auto:
        return f"{lang}-orig"
    if lang in auto and (info.get("language") or "").split("-")[0] == lang.split("-")[0]:
        return lang
    return None


def time_lyrics(vid: str, lyrics: list[str], lang: str, cache: Path, ydl_factory: Callable | None = None
                ) -> tuple[list[Line] | None, str]:
    """(timed lines, note) for one video; lines is None when there is no usable caption track."""
    dest = cache / f"{vid}.vtt"
    if not dest.exists():
        factory = ydl_factory or youtube._yt_dlp().YoutubeDL
        with factory({"quiet": True, "no_warnings": True, "skip_download": True}) as probe:
            info = probe.extract_info(youtube.watch_url(vid), download=False) or {}
        track = pick_track(info, lang)
        if track is None:
            return None, "no automatic captions in this language"
        cache.mkdir(parents=True, exist_ok=True)
        if not youtube.download_track(factory, vid, track, dest, writeautomaticsub=True):
            return None, "caption download produced no file"
    words = caption_words(read_text(dest))
    if not words:
        return None, "the captions have no word times"
    lines, coverage = align_with_coverage(lyrics, words)
    if coverage < MIN_COVERAGE:
        return None, f"only {coverage:.0%} of the lines match the captions"
    lines = [Line(ln.text, max(ln.start - LEAD, 0.0), max(ln.end - LEAD, 0.0)) for ln in lines]
    return lines, f"{coverage:.0%} of the lines matched"
