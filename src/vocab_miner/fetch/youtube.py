"""YouTube as a starting point: playlist -> video list, video list -> subtitle files.

The sing-along page plays YouTube videos, so a playlist is a natural way to collect material:
list the videos, then download the subtitle tracks the uploaders provide (never the video itself).
Videos without subtitles can be transcribed later (Whisper).

Subtitles are saved as <out>/<video id>.vtt so the file name is the video id; the subtitle source can then
link every line to its place in the video.
"""
from __future__ import annotations

import csv
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

LIST_HEADER = ["index", "id", "title", "channel", "duration", "url"]
VIDEO_ID = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})|^([\w-]{11})$")
PAUSE = 3.0     # seconds between videos


def video_id(s: str) -> str | None:
    m = VIDEO_ID.search(s.strip())
    return (m.group(1) or m.group(2)) if m else None


def watch_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


def _yt_dlp():
    try:
        import yt_dlp
    except ImportError as e:
        raise ImportError("yt-dlp is missing: run uv sync") from e
    return yt_dlp


# ---------- playlist -> list ----------

def playlist_entries(url: str, ydl_factory: Callable | None = None) -> tuple[str, list[dict]]:
    """(playlist title, [{id, title, channel, duration}]) without downloading anything."""
    factory = ydl_factory or _yt_dlp().YoutubeDL
    with factory({"extract_flat": "in_playlist", "quiet": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = [{"id": e["id"], "title": e.get("title") or "",
                "channel": e.get("channel") or e.get("uploader") or "", "duration": e.get("duration") or ""}
               for e in info.get("entries") or [] if e and e.get("id")]
    return info.get("title") or "", entries


def write_list(path: Path, entries: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(LIST_HEADER)
        for i, e in enumerate(entries, 1):
            w.writerow([i, e["id"], e["title"], e["channel"], e["duration"], watch_url(e["id"])])


def read_targets(items: Iterable[str]) -> list[tuple[str, str]]:
    """(video id, title) from list files written by write_list, text files of urls, or urls / ids."""
    targets: list[tuple[str, str]] = []
    for item in items:
        p = Path(item)
        if p.is_file():
            lines = p.read_text(encoding="utf-8").splitlines()
            if lines and lines[0].split("\t")[:2] == LIST_HEADER[:2]:
                targets += [(r["id"], r.get("title") or "") for r in csv.DictReader(lines, delimiter="\t")]
            else:
                targets += [(vid, "") for line in lines if (vid := video_id(line))]
        elif (vid := video_id(item)):
            targets.append((vid, ""))
        else:
            raise ValueError(f"not a file, YouTube url or video id: {item}")
    seen: set[str] = set()
    return [t for t in targets if not (t[0] in seen or seen.add(t[0]))]


# ---------- list -> subtitles ----------

def pick_lang(tracks: dict, wanted: str) -> str | None:
    """Exact language code first, then a regional variant (en -> en-US), never the "-orig" duplicates."""
    if wanted in tracks:
        return wanted
    return next((k for k in tracks if k.split("-")[0] == wanted and not k.endswith("-orig")), None)


@dataclass
class SubResult:
    id: str
    title: str
    status: str     # cached | subtitles | auto | none | auto-available | error
    detail: str = ""


def download_subtitles(targets: list[tuple[str, str]], out: Path, lang: str = "en", auto: bool = False,
                       pause: float = PAUSE, ydl_factory: Callable | None = None,
                       progress: Callable[[int, int, SubResult], None] | None = None) -> list[SubResult]:
    """Download one subtitle track per video as <out>/<id>.vtt. Uploader-made subtitles are preferred;
    auto-generated captions only with auto=True (they are often wrong for songs)."""
    factory = ydl_factory or _yt_dlp().YoutubeDL
    out.mkdir(parents=True, exist_ok=True)
    results: list[SubResult] = []
    fetched = 0
    with factory({"quiet": True, "no_warnings": True, "skip_download": True}) as probe:
        for n, (vid, title) in enumerate(targets, 1):
            dest = out / f"{vid}.vtt"
            if dest.exists():
                res = SubResult(vid, title, "cached", dest.name)
            else:
                if fetched and pause:
                    time.sleep(pause)
                fetched += 1
                res = _one(factory, probe, vid, title, dest, lang, auto)
            results.append(res)
            if progress:
                progress(n, len(targets), res)
    return results


def _one(factory, probe, vid: str, title: str, dest: Path, lang: str, auto: bool) -> SubResult:
    try:
        info = probe.extract_info(watch_url(vid), download=False)
    except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds; keep going with the other videos
        return SubResult(vid, title, "error", str(e).splitlines()[0])
    title = title or info.get("title") or ""
    manual = pick_lang(info.get("subtitles") or {}, lang)
    generated = pick_lang(info.get("automatic_captions") or {}, lang)
    if manual:
        track, status, opts = manual, "subtitles", {"writesubtitles": True}
    elif generated and auto:
        track, status, opts = generated, "auto", {"writeautomaticsub": True}
    else:
        return SubResult(vid, title, "auto-available" if generated else "none")
    stem = dest.with_suffix("")
    with factory({"quiet": True, "no_warnings": True, "skip_download": True, "subtitleslangs": [track],
                  "subtitlesformat": "vtt", "outtmpl": str(stem) + ".%(ext)s", **opts}) as ydl:
        ydl.download([watch_url(vid)])
    got = sorted(dest.parent.glob(f"{vid}.*.vtt"))     # yt-dlp names it <id>.<lang>.vtt
    if not got:
        return SubResult(vid, title, "error", "download produced no file")
    got[0].replace(dest)
    return SubResult(vid, title, status, f"{dest.name} ({track})")


def write_report(path: Path, results: Iterable[SubResult]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["id", "title", "status", "detail"])
        w.writerows([r.id, r.title, r.status, r.detail] for r in results)


# ---------- audio (for transcription) ----------

def download_audio(vid: str, out: Path, ydl_factory: Callable | None = None) -> Path:
    """Audio track only, as <out>/<id>.<ext>; reused if already there."""
    out.mkdir(parents=True, exist_ok=True)
    have = [p for p in out.glob(f"{vid}.*") if p.suffix not in (".part", ".ytdl")]
    if have:
        return have[0]
    factory = ydl_factory or _yt_dlp().YoutubeDL
    # YouTube sometimes answers 403 for a moment: try again, then fall back to the HLS stream (audio + video)
    formats = ["bestaudio[ext=m4a]/bestaudio", "bestaudio[ext=m4a]/bestaudio", "best[protocol^=m3u8]"]
    error: Exception | None = None
    for k, fmt in enumerate(formats):
        if k:
            time.sleep(PAUSE)
        try:
            with factory({"quiet": True, "no_warnings": True, "noprogress": True, "format": fmt,
                          "outtmpl": str(out / f"{vid}.%(ext)s")}) as ydl:
                ydl.download([watch_url(vid)])
        except Exception as e:  # noqa: BLE001 - yt-dlp's DownloadError; retried below
            error = e
            continue
        have = [p for p in out.glob(f"{vid}.*") if p.suffix not in (".part", ".ytdl")]
        if have:
            return have[0]
    raise RuntimeError(f"no audio downloaded for {vid}: {error}")


# ---------- a file of playlists (language | album | url) ----------

LIST_ID = re.compile(r"[?&]list=([\w-]+)")


@dataclass
class Playlist:
    lang: str
    album: str          # section name in the app; "" = only a source of songs
    url: str

    @property
    def list_id(self) -> str:
        m = LIST_ID.search(self.url)
        return m.group(1) if m else ""


def read_playlists(path: Path) -> list[Playlist]:
    """Lines "language | album | url"; "#" starts a comment, album "-" means not an album."""
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.split("#", 1)[0].strip() if line.lstrip().startswith("#") else line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3 or not LIST_ID.search(parts[2]):
            raise ValueError(f"{path}:{n}: expected 'language | album | playlist url', got {line!r}")
        out.append(Playlist(parts[0], "" if parts[1] == "-" else parts[1], parts[2]))
    return out


def list_file(folder: Path, playlist: Playlist) -> Path:
    return folder / f"{playlist.list_id}.tsv"


def read_list(path: Path) -> list[dict]:
    """Rows of a list file written by write_list."""
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines(), delimiter="\t"))
