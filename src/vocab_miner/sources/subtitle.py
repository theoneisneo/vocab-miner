"""Timed text: .lrc (lyrics), .srt and .vtt (subtitles). One doc per file.

Media: if an audio/video file with the same stem sits next to the subtitle file (song.lrc + song.mp3),
each utterance gets a MediaRef(kind="file") with its start/end. Otherwise a YouTube id can be given per doc
with the `youtube` option: { "<doc_id>" = "<video id>" }.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..model import MediaRef, Utterance
from ..textclean import clean
from . import iter_files, read_text

MEDIA_SUFFIXES = (".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".mp4", ".mkv", ".webm")


@dataclass
class Cue:
    start: float | None
    end: float | None
    text: str


# ---------- LRC ----------

LRC_TIME = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]")
LRC_META = re.compile(r"^\[([a-zA-Z]+):(.*)\]\s*$")
LRC_WORD_TIME = re.compile(r"<\d+:\d{1,2}(?:[.:]\d{1,3})?>")    # enhanced LRC per-word stamps


def _secs(m: str, s: str, frac: str | None) -> float:
    return int(m) * 60 + int(s) + (int(frac) / 10 ** len(frac) if frac else 0.0)


def parse_lrc(text: str) -> list[Cue]:
    offset = 0.0
    timed: list[tuple[float, str]] = []
    for line in text.split("\n"):
        line = line.strip()
        meta = LRC_META.match(line)
        if meta and not LRC_TIME.match(line):
            if meta.group(1).lower() == "offset":
                try:
                    offset = int(meta.group(2).strip()) / 1000   # positive offset = lyrics come earlier
                except ValueError:
                    pass
            continue
        stamps = []
        while (m := LRC_TIME.match(line)):
            stamps.append(_secs(*m.groups()))
            line = line[m.end():]
        if not stamps:
            continue
        body = LRC_WORD_TIME.sub("", line)
        timed.extend((t, body) for t in stamps)    # one line may repeat at several times (chorus)
    timed.sort(key=lambda x: x[0])
    cues = []
    for i, (t, body) in enumerate(timed):
        end = timed[i + 1][0] - offset if i + 1 < len(timed) else None
        cues.append(Cue(max(t - offset, 0.0), end, body))
    return cues


# ---------- SRT / VTT ----------

TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
CUE_TIMING = re.compile(rf"^\s*{TS}\s*-->\s*{TS}")


def _ts(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(text: str) -> list[Cue]:
    """Also handles WebVTT: the header, NOTE/STYLE/REGION blocks and cue settings are skipped."""
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        idx = next((i for i, ln in enumerate(lines) if CUE_TIMING.match(ln)), None)
        if idx is None:
            continue                                # header, NOTE, STYLE, ...
        g = CUE_TIMING.match(lines[idx]).groups()
        cues.append(Cue(_ts(*g[:4]), _ts(*g[4:]), "\n".join(lines[idx + 1:])))
    return cues


parse_vtt = parse_srt

PARSERS = {".lrc": parse_lrc, ".srt": parse_srt, ".vtt": parse_vtt}


class SubtitleSource:
    suffixes: tuple[str, ...] = tuple(PARSERS)

    def __init__(self, source_id: str, path: str | Path, lang: str,
                 youtube: dict[str, str] | None = None, control_codes: bool = True):
        self.source_id = source_id
        self.path = Path(path)
        self.lang = lang
        self.youtube = youtube or {}
        self.control_codes = control_codes

    @staticmethod
    def find_media(file: Path) -> Path | None:
        for suf in MEDIA_SUFFIXES:
            for cand in (file.with_suffix(suf), file.with_suffix(suf.upper())):
                if cand.is_file():
                    return cand
        return None

    def _media(self, doc_id: str, file: Path, cue: Cue) -> MediaRef | None:
        if (audio := self.find_media(file)) is not None:
            return MediaRef(kind="file", uri=str(audio), start=cue.start, end=cue.end)
        if doc_id in self.youtube:
            return MediaRef(kind="youtube", uri=self.youtube[doc_id], start=cue.start, end=cue.end)
        return None

    def utterances(self) -> Iterator[Utterance]:
        for doc_id, file in iter_files(self.path, self.suffixes):
            cues = PARSERS[file.suffix.lower()](read_text(file))
            seq = 0
            for cue in cues:
                text = clean(cue.text, control_codes=self.control_codes)
                if not text:
                    continue
                seq += 1
                yield Utterance(id=f"{self.source_id}:{doc_id}:{seq}", source_id=self.source_id,
                                doc_id=doc_id, seq=seq, lang=self.lang, text=text,
                                media=self._media(doc_id, file, cue))


class LrcSource(SubtitleSource):
    suffixes = (".lrc",)


class SrtSource(SubtitleSource):
    suffixes = (".srt",)


class VttSource(SubtitleSource):
    suffixes = (".vtt",)
