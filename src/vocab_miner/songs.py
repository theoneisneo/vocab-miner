"""One command from playlists to timed lyrics: `vm songs playlists.txt --lang en -o data/raw/english`.

    1. video lists of the playlists in that language (cached, as vm yt-playlists)
    2. the uploader's subtitle track, when there is one (as vm yt-subs)
    3. LRCLIB: time-synced lyrics, or plain lyrics (as vm yt-lyrics)
    4. Whisper: timing for plain lyrics, or a transcription when nothing else was found (as vm transcribe)
    5. quality report (as vm quality): <out>/quality.tsv

Songs that already have a file in the output folder are skipped, also when the file belongs to another upload of
the same song (a music video and a music-only track of one song count once). Non-songs in playlists (prologues,
interludes, crossfade previews, trailers) are left out, and so is anything listed in <out>/skip.txt (one video id
or title per line, e.g. a version in another language that sits in a playlist). <out>/videos.tsv lists every song
with a clean title; use it as the subtitle source's `video_list` so each line links to its video.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import quality
from .albums import clean_title, title_key
from .fetch import lrclib, youtube

NOT_A_SONG = re.compile(r"\b(prologue|epilogue|interlude|cross\s*fade|crossfade|trailer|teaser|making|"
                        r"behind the scenes|preview)\b", re.IGNORECASE)
TIMED = (".lrc", ".vtt", ".srt")


@dataclass
class SongsResult:
    songs: int = 0
    already: int = 0
    subtitles: int = 0
    synced: int = 0
    plain: int = 0
    timed: int = 0
    transcribed: int = 0
    missing: list[str] = field(default_factory=list)
    reports: list[quality.Report] = field(default_factory=list)


def read_skip(path: Path) -> set[str]:
    """skip.txt: videos to leave out (e.g. another-language version inside a playlist), one video id or title
    per line; "#" starts a comment."""
    if not path.is_file():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out |= {line, title_key(line)}
    return out


def has_file(out: Path, vid: str, suffixes=(*TIMED, ".txt")) -> bool:
    return any((out / f"{vid}{s}").exists() for s in suffixes)


def collect(playlists: list[youtube.Playlist], lang: str, list_dir: Path, log: Callable[[str], None]) -> list[dict]:
    """Song rows of every playlist in `lang`, in order, one per song (by title)."""
    rows, seen = [], set()
    for pl in playlists:
        if pl.lang.split("-")[0] != lang.split("-")[0]:
            continue
        path = youtube.list_file(list_dir, pl)
        if not path.is_file():
            title, entries = youtube.playlist_entries(pl.url)
            youtube.write_list(path, entries)
            log(f"{pl.album or '-'}: {len(entries)} videos ({title})")
        for r in youtube.read_list(path):
            key = title_key(r["title"])
            if NOT_A_SONG.search(r["title"]) or not key or key in seen:
                continue
            seen.add(key)
            rows.append({"id": r["id"], "title": clean_title(r["title"]), "channel": r.get("channel", ""),
                         "duration": r.get("duration", "")})
    return rows


def run(playlists_file: Path, lang: str, out: Path, list_dir: Path, whisper: bool = True, separate: bool = False,
        model: str = "large-v3", log: Callable[[str], None] = print) -> SongsResult:
    res = SongsResult()
    out.mkdir(parents=True, exist_ok=True)
    rows = collect(youtube.read_playlists(playlists_file), lang, list_dir, log)
    skip = read_skip(out / "skip.txt")
    rows = [r for r in rows if r["id"] not in skip and title_key(r["title"]) not in skip]
    # a song is done when any upload of it has a file here (earlier runs may have used another video)
    known: dict[str, str] = {}
    for vl in [out / "videos.tsv", *list_dir.glob("*.tsv")]:
        if vl.is_file():
            for r in youtube.read_list(vl):
                if has_file(out, r.get("id", "")):
                    known.setdefault(title_key(r.get("title", "")), r["id"])
    for r in rows:                                  # keep the upload that already has the lyrics
        if (vid := known.get(title_key(r["title"]))) and not has_file(out, r["id"]):
            r["id"] = vid
    youtube.write_list(out / "videos.tsv", rows)
    res.songs = len(rows)
    todo = [r for r in rows if not has_file(out, r["id"])]
    res.already = res.songs - len(todo)
    log(f"{res.songs} songs, {res.already} already have lyrics, {len(todo)} to look for")

    if todo:
        log("uploader subtitles…")
        subs = youtube.download_subtitles([(r["id"], r["title"]) for r in todo], out, lang=lang)
        res.subtitles = sum(s.status == "subtitles" for s in subs)
        todo = [r for r in todo if not has_file(out, r["id"])]
    if todo:
        log("LRCLIB…")
        found = lrclib.fetch_lyrics(todo, out, lang)
        res.synced = sum(f.status == "synced" for f in found)
        res.plain = sum(f.status == "plain" for f in found)
    need = [r for r in rows if not has_file(out, r["id"], TIMED)]
    if need and whisper:
        from . import transcribe as tr
        try:
            w = tr.load_model(model)
        except ImportError as e:
            log(f"Whisper skipped ({e}); {len(need)} songs have no timed lyrics")
            w = None
        for n, r in enumerate(need, 1) if w else ():
            try:
                audio = youtube.download_audio(r["id"], list_dir / "audio")
                if separate:
                    audio = tr.separate_vocals(audio, Path(".cache") / "vocals")
            except Exception as e:  # noqa: BLE001 - one unavailable video should not stop the rest
                log(f"[{n}/{len(need)}] {r['title']}: no audio ({str(e).splitlines()[0]})")
                continue
            words, heard = tr.transcribe(w, audio, lang)
            text = out / f"{r['id']}.txt"
            if text.is_file():
                lines, transcribed = tr.align(tr.read_lyrics(text), words), False
            else:
                lines, transcribed = tr.drop_made_up(heard), True
            (out / f"{r['id']}.lrc").write_text(tr.to_lrc(lines, r["title"], transcribed), encoding="utf-8")
            res.transcribed += transcribed
            res.timed += not transcribed
            log(f"[{n}/{len(need)}] {r['title']}: {'transcribed' if transcribed else 'lyrics timed'}")
    res.missing = [r["title"] for r in rows if not has_file(out, r["id"], TIMED)]
    res.reports = quality.check_folder(out, lang, [out / "videos.tsv"])
    quality.write_report(out / "quality.tsv", res.reports)
    return res
