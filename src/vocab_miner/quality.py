"""Quality report for a folder of timed lyrics/subtitles: what to trust, what to look at, what is broken.

Each file gets a grade:
    ok       usable as is (synced lyrics, uploader subtitles, lyrics timed with Whisper)
    check    worth a look (Whisper transcription, lyrics end well before the video does, Whisper sign-offs...)
    problem  probably wrong (another language, longer than the video, almost no lines)
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from .fetch.lrclib import in_lang
from .sources.subtitle import PARSERS, lrc_meta, read_video_list
from .transcribe import MADE_UP

GRADES = ("ok", "check", "problem")


@dataclass
class Report:
    id: str
    title: str
    origin: str
    grade: str = "ok"
    notes: list[str] = field(default_factory=list)

    def flag(self, grade: str, note: str) -> None:
        if GRADES.index(grade) > GRADES.index(self.grade):
            self.grade = grade
        self.notes.append(note)


def origin_of(path: Path, meta: dict[str, str]) -> str:
    re_ = meta.get("re", "").lower()
    if "transcription" in re_:
        return "Whisper transcription"
    if "timed with whisper" in re_:
        return "lyrics timed with Whisper"
    if "lrclib" in re_:
        return "LRCLIB"
    if path.suffix.lower() in (".vtt", ".srt"):
        return "subtitles"
    return "lyrics file"


def check_file(path: Path, lang: str, duration: float | None = None, title: str = "") -> Report:
    text = path.read_text(encoding="utf-8-sig")
    meta = lrc_meta(text) if path.suffix.lower() == ".lrc" else {}
    cues = [c for c in PARSERS[path.suffix.lower()](text) if c.text.strip()]
    rep = Report(path.stem, title or meta.get("ti", ""), origin_of(path, meta))
    if rep.origin == "Whisper transcription":
        rep.flag("check", "AI transcription: may contain mistakes")
    if len(cues) < 5:
        rep.flag("problem", f"only {len(cues)} lines")
    if cues and not in_lang(" ".join(c.text for c in cues), lang):
        rep.flag("problem", f"mostly not in {lang} (another version of the song?)")
    made_up = sum(bool(MADE_UP.match(c.text.strip())) for c in cues)
    if made_up:
        rep.flag("check", f"{made_up} line(s) look like Whisper sign-offs (e.g. 'Thanks for watching')")
    starts = [c.start for c in cues if c.start is not None]
    if any(b < a for a, b in pairwise(starts)):
        rep.flag("check", "time stamps go backwards")
    if duration and starts:
        last = max((c.end or c.start) for c in cues if c.start is not None)
        if starts[-1] > duration + 5:
            rep.flag("problem", f"lines continue after the video ends ({starts[-1]:.0f}s > {duration:.0f}s): "
                                "lyrics for a longer version?")
        elif last < 0.6 * duration:
            rep.flag("check", f"lyrics end at {last:.0f}s of {duration:.0f}s: missing part, or a long outro")
    return rep


def check_folder(folder: Path, lang: str, video_lists: list[Path] = ()) -> list[Report]:
    """Every timed file named by a video id (or any name) in `folder`; durations and titles from video lists."""
    info: dict[str, dict] = {}
    for vl in video_lists:
        if vl.is_file():
            rows = csv.DictReader(vl.read_text(encoding="utf-8").splitlines(), delimiter="\t")
            for r in rows:
                info.setdefault(r["id"], r)
    titles = {k: v for vl in video_lists if vl.is_file() for k, v in read_video_list(vl).items()}
    reports = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in PARSERS or "." in f.stem:       # song.zh-Hant.lrc is a translation
            continue
        row = info.get(f.stem, {})
        dur = float(row["duration"]) if row.get("duration") else None
        reports.append(check_file(f, lang, dur, titles.get(f.stem, "")))
    return reports


def write_report(path: Path, reports: list[Report]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["grade", "id", "title", "origin", "notes"])
        order = {g: i for i, g in enumerate(reversed(GRADES))}
        for r in sorted(reports, key=lambda r: (order[r.grade], r.title)):
            w.writerow([r.grade, r.id, r.title, r.origin, "; ".join(r.notes)])
