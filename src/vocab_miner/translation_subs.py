"""Line translations from the uploader's subtitle tracks in other languages (e.g. Chinese subtitles on a music video).

For each song with timed lyrics and each wanted language, the uploader's track in that language is downloaded
and every translated cue is attached to the lyrics line it overlaps most (cues of one line are joined), which
handles subtitles that split or merge lines differently. The result is written as <id>.<lang>.lrc next to the
lyrics, the layout SubtitleSource reads with translations = { "<lang>" = "file" }. Existing files are never
overwritten, so they can be edited by hand.

Simplified Chinese tracks are converted when Traditional is wanted (and back), with OpenCC (Taiwan phrasing).

When the lyrics' timing came from speech recognition (Whisper, automatic captions) and is squeezed (many lines a fraction of a second apart, a sign the
alignment failed) and the subtitles have exactly one cue per line, the lyrics are re-timed from the subtitles
(the original is kept as <file>.bak).
"""
from __future__ import annotations

import csv
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from .fetch import youtube
from .sources import read_text
from .sources.subtitle import PARSERS, Cue, lrc_meta

# tracks to try for a wanted language, best first; a track in the other script is converted
PREFERENCES = {
    "zh-Hant": ["zh-Hant", "zh-TW", "zh-HK", "zh", "zh-Hans", "zh-CN", "zh-SG"],
    "zh-Hans": ["zh-Hans", "zh-CN", "zh-SG", "zh", "zh-Hant", "zh-TW", "zh-HK"],
}
TRADITIONAL = {"zh-Hant", "zh-TW", "zh-HK"}
OVERLAP_GAP = 4.0       # seconds: a cue between lines goes to the nearest line start this close
SQUEEZED_GAP = 0.5      # seconds between line starts that counts as squeezed
SQUEEZED_RUN = 5        # this many squeezed gaps in a file mean the timing failed
CHECKED = "translation_subs.tsv"


def pick_track(tracks: Sequence[str], lang: str) -> str | None:
    for t in PREFERENCES.get(lang, [lang]):
        if t in tracks:
            return t
    return next((t for t in tracks if t.split("-")[0] == lang.split("-")[0] and not t.endswith("-orig")), None)


def converter(track: str, lang: str) -> Callable[[str], str]:
    """Text as-is, or converted between Simplified and Traditional Chinese. A plain "zh" track is usually
    Simplified; converting Traditional text to Traditional leaves it as it is."""
    if not lang.startswith("zh") or track == lang:
        return lambda s: s
    to_trad = lang in TRADITIONAL
    if to_trad == (track in TRADITIONAL):
        return lambda s: s
    try:
        from opencc import OpenCC
    except ImportError:
        return lambda s: s
    cc = OpenCC("s2twp" if to_trad else "tw2sp")
    return cc.convert


def squeezed(starts: Sequence[float]) -> int:
    """How many consecutive line starts are less than SQUEEZED_GAP apart."""
    return sum(0 <= b - a < SQUEEZED_GAP for a, b in pairwise(starts))


def sung(cues: Sequence[Cue]) -> list[Cue]:
    return [c for c in cues if c.start is not None and c.text.strip()]


def align(lines: Sequence[Cue], subs: Sequence[Cue], convert: Callable[[str], str] = lambda s: s
          ) -> list[tuple[float, str]]:
    """[(line start, translation)] for the lines that got a translation. `lines` may include empty end
    markers, which end the line before them."""
    timed = [c for c in lines if c.start is not None]
    spans = []
    for i, c in enumerate(timed):
        nxt = timed[i + 1].start if i + 1 < len(timed) else c.start + 8
        end = c.end if c.end and c.end > c.start else nxt
        spans.append((c.start, min(end, nxt) if nxt > c.start else end))
    texts: list[list[str]] = [[] for _ in timed]
    for z in subs:
        if z.start is None or not z.text.strip():
            continue
        zs, ze = z.start, z.end or z.start + 2
        best, best_ov = None, 0.0
        for i, (s, e) in enumerate(spans):
            if timed[i].text.strip() and (ov := min(ze, e) - max(zs, s)) > best_ov:
                best, best_ov = i, ov
        if best is None:
            near = [(abs(zs - s), i) for i, (s, _) in enumerate(spans)
                    if timed[i].text.strip() and abs(zs - s) < OVERLAP_GAP]
            best = min(near)[1] if near else None
        if best is not None:
            texts[best].append(convert(" ".join(z.text.split())))
    return [(c.start, " ".join(dict.fromkeys(t))) for c, t in zip(timed, texts) if t]


def stamp(t: float) -> str:
    return f"[{int(t // 60):02d}:{t % 60:05.2f}]"


def to_lrc(pairs: Sequence[tuple[float, str]], note: str) -> str:
    return "\n".join([f"[re:{note}]", *(f"{stamp(s)}{t}" for s, t in pairs)]) + "\n"


def retime(lyrics: Path, subs: Sequence[Cue]) -> bool:
    """Re-time Whisper-timed lyrics whose timing is squeezed from subtitles with one cue per line."""
    text = read_text(lyrics)
    note = lrc_meta(text).get("re", "").lower()
    if lyrics.suffix.lower() != ".lrc" or not ("whisper" in note or "automatic captions" in note):
        return False
    lines, subs = sung(PARSERS[".lrc"](text)), sung(subs)
    if len(lines) != len(subs) or squeezed([c.start for c in lines]) < SQUEEZED_RUN:
        return False
    head = [ln for ln in text.split("\n") if ln.startswith(("[ti:", "[ar:", "[re:"))]
    body = [f"{stamp(z.start)}{c.text}" for c, z in zip(lines, subs)] + [stamp(subs[-1].end or subs[-1].start + 4)]
    backup = lyrics.with_name(lyrics.name + ".bak")
    if not backup.exists():
        shutil.copyfile(lyrics, backup)
    lyrics.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    return True


@dataclass
class TrResult:
    id: str
    lang: str
    status: str         # written | none | have | error
    detail: str = ""


def read_checked(path: Path) -> set[tuple[str, str]]:
    if not path.is_file():
        return set()
    return {(r["id"], r["lang"]) for r in csv.DictReader(read_text(path).splitlines(), delimiter="\t")}


def fetch(rows: Sequence[dict], out: Path, langs: Sequence[str], lyrics_of: Callable[[str], Path | None],
          pause: float = youtube.PAUSE, ydl_factory: Callable | None = None,
          log: Callable[[str], None] = print) -> list[TrResult]:
    """<out>/<id>.<lang>.lrc for every song row that has lyrics and no translation file yet. Videos found to
    have no such track are remembered in <out>/translation_subs.tsv and not asked again."""
    checked_path = out / CHECKED
    checked = read_checked(checked_path)
    todo = [(r, lang) for r in rows for lang in langs
            if (r["id"], lang) not in checked and lyrics_of(r["id"]) is not None
            and not any((out / f"{r['id']}.{lang}{s}").exists() for s in PARSERS)]
    results: list[TrResult] = []
    if not todo:
        return results
    factory = ydl_factory or youtube._yt_dlp().YoutubeDL
    (out / ".subs").mkdir(parents=True, exist_ok=True)
    infos: dict[str, dict] = {}
    with factory({"quiet": True, "no_warnings": True, "skip_download": True}) as probe:
        for n, (r, lang) in enumerate(todo):
            vid = r["id"]
            try:
                if vid not in infos:
                    if n and pause:
                        time.sleep(pause)
                    infos[vid] = probe.extract_info(youtube.watch_url(vid), download=False) or {}
                track = pick_track(list((infos[vid].get("subtitles") or {}).keys()), lang)
                if track is None:
                    results.append(TrResult(vid, lang, "none"))
                    continue
                dest = out / ".subs" / f"{vid}.{lang}.vtt"
                if not dest.exists() and not youtube.download_track(factory, vid, track, dest):
                    results.append(TrResult(vid, lang, "error", "download produced no file"))
                    continue
                subs = PARSERS[".vtt"](read_text(dest))
                lyrics = lyrics_of(vid)
                if retime(lyrics, subs):
                    log(f"  {r.get('title', vid)}: timing re-done from the {track} subtitles")
                pairs = align(PARSERS[lyrics.suffix.lower()](read_text(lyrics)), subs, converter(track, lang))
                (out / f"{vid}.{lang}.lrc").write_text(to_lrc(pairs, f"uploader subtitles ({track})"),
                                                       encoding="utf-8")
                results.append(TrResult(vid, lang, "written", track))
            except Exception as e:  # noqa: BLE001 - one failing video should not stop the rest
                results.append(TrResult(vid, lang, "error", str(e).splitlines()[0]))
    new = [res for res in results if res.status in ("none", "written")]
    if new:
        first = not checked_path.exists()
        with checked_path.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            if first:
                w.writerow(["id", "lang", "status", "track"])
            w.writerows([res.id, res.lang, res.status, res.detail] for res in new)
    return results
