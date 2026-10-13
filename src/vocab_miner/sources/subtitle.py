"""Timed text: .lrc (lyrics), .srt and .vtt (subtitles). One doc per file.

Media: if an audio/video file with the same stem sits next to the subtitle file (song.lrc + song.mp3),
each utterance gets a MediaRef(kind="file") with its start/end. Otherwise a YouTube id can be given per doc
with the `youtube` option: { "<doc_id>" = "<video id>" }.

Translations: bilingual material is supported with the `translations` option (see SubtitleSource).
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
    """Options:
    youtube       {doc_id: video id} when there is no local audio next to the file
    translations  {lang: layout} for bilingual material, layout one of
                  "last-line"  the last line of each cue is the translation (bilingual .srt/.vtt)
                  "same-time"  a cue with the same start time right after the original (bilingual .lrc)
                  "file"       a separate file song.<lang>.lrc / .srt / .vtt next to song.lrc, matched by time
    """

    suffixes: tuple[str, ...] = tuple(PARSERS)

    def __init__(self, source_id: str, path: str | Path, lang: str,
                 youtube: dict[str, str] | None = None, translations: dict[str, str] | None = None,
                 control_codes: bool = True):
        self.source_id = source_id
        self.path = Path(path)
        self.lang = lang
        self.youtube = youtube or {}
        self.translations = translations or {}
        bad = {m for m in self.translations.values() if m not in LAYOUTS}
        if bad:
            raise ValueError(f"translation layout must be one of {sorted(LAYOUTS)}, got {sorted(bad)}")
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

    def _clean(self, text: str) -> str:
        return clean(text, control_codes=self.control_codes)

    def _cues(self, file: Path) -> list[Cue]:
        return PARSERS[file.suffix.lower()](read_text(file))

    def _with_translations(self, file: Path, cues: list[Cue]) -> list[tuple[Cue, dict[str, str]]]:
        """Pair each original cue with its translations according to the configured layouts."""
        inline = [lang for lang, m in self.translations.items() if m == "last-line"]
        same_time = [lang for lang, m in self.translations.items() if m == "same-time"]
        out: list[tuple[Cue, dict[str, str]]] = []
        i = 0
        while i < len(cues):
            cue, tr = cues[i], {}
            if inline:
                lines = [ln for ln in cue.text.split("\n") if ln.strip()]
                if len(lines) > len(inline):
                    for lang, line in zip(reversed(inline), reversed(lines[-len(inline):]), strict=True):
                        tr[lang] = self._clean(line)
                    cue = Cue(cue.start, cue.end, "\n".join(lines[:-len(inline)]))
            i += 1
            for lang in same_time:                   # following cues at the same time are translations
                if i < len(cues) and cues[i].start == cue.start and cue.start is not None:
                    tr[lang] = self._clean(cues[i].text)
                    i += 1
            if same_time and i < len(cues) and cues[i].start is not None and cues[i].start > (cue.start or 0):
                cue = Cue(cue.start, cues[i].start, cue.text)   # end at the next original line, not its translation
            out.append((cue, tr))
        for lang, layout in self.translations.items():
            if layout == "file" and (side := self._sidecar(file, lang)) is not None:
                _attach_by_time(out, [c for c in self._cues(side) if self._clean(c.text)], lang, self._clean)
        return out

    @staticmethod
    def _sidecar(file: Path, lang: str) -> Path | None:
        for suf in (file.suffix, *PARSERS):
            cand = file.with_name(f"{file.stem}.{lang}{suf}")
            if cand.is_file():
                return cand
        return None

    def utterances(self) -> Iterator[Utterance]:
        for doc_id, file in iter_files(self.path, self.suffixes):
            if SIDECAR.search(file.stem):
                continue                             # song.zh-Hant.lrc is a translation, not a doc of its own
            seq = 0
            for cue, tr in self._with_translations(file, self._cues(file)):
                text = self._clean(cue.text)
                if not text:
                    continue
                seq += 1
                yield Utterance(id=f"{self.source_id}:{doc_id}:{seq}", source_id=self.source_id,
                                doc_id=doc_id, seq=seq, lang=self.lang, text=text,
                                translations={k: v for k, v in tr.items() if v},
                                media=self._media(doc_id, file, cue))


LAYOUTS = {"last-line", "same-time", "file"}
# "song.zh-Hant" / "song.en": a stem ending in a BCP-47-like tag marks a translation file
SIDECAR = re.compile(r"\.[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def _attach_by_time(pairs: list[tuple[Cue, dict[str, str]]], side: list[Cue], lang: str, clean_fn) -> None:
    """Match translation cues to original cues by start time (within 0.3 s), or by position if counts agree."""
    originals = [p for p in pairs if clean_fn(p[0].text)]
    by_time = {round(c.start, 1): c for c in side if c.start is not None}
    matched = 0
    for cue, tr in originals:
        if cue.start is None:
            continue
        keys = (round(cue.start + off, 1) for off in (0, -.1, .1, -.2, .2, -.3, .3))
        hit = next((by_time[k] for k in keys if k in by_time), None)
        if hit is not None:
            tr[lang] = clean_fn(hit.text)
            matched += 1
    if matched == 0 and len(side) == len(originals):
        for (_, tr), c in zip(originals, side, strict=True):
            tr[lang] = clean_fn(c.text)


class LrcSource(SubtitleSource):
    suffixes = (".lrc",)


class SrtSource(SubtitleSource):
    suffixes = (".srt",)


class VttSource(SubtitleSource):
    suffixes = (".vtt",)
