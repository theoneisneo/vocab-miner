"""Timed lyrics/subtitles from audio with Whisper (faster-whisper, local GPU if there is one).

Two uses:
  - lyrics text without timing (<stem>.txt next to the audio's name): Whisper only supplies the timing;
    every line keeps the given text and gets the time of the words that match it.
  - no text at all: Whisper's own transcription becomes the lines. It can mishear (especially singing),
    so the file is marked as a transcription in its header.

Output is .lrc (easy to fix by hand, read by the subtitle source). A line followed by a long pause gets an
empty time stamp so the line does not stay on screen through instrumental parts.
"""
from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path

GAP = 2.0                   # seconds of silence after a line before it is closed with an empty stamp
MARK_ALIGNED = "[re:vocab-miner: lyrics timed with Whisper]"
MARK_TRANSCRIBED = "[re:vocab-miner: Whisper transcription, may contain mistakes]"


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Line:
    text: str
    start: float
    end: float


# ---------- Whisper ----------

def _cuda_dll_dirs() -> None:
    """On Windows, CUDA libraries installed from PyPI (nvidia-cublas-cu12, nvidia-cudnn-cu12) are not on PATH."""
    if os.name != "nt":
        return
    try:
        import nvidia
    except ImportError:
        return
    for base in nvidia.__path__:
        for bin_dir in Path(base).glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def load_model(name: str = "large-v3", device: str = "auto"):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ImportError("faster-whisper is not installed: uv sync --extra whisper") from e
    _cuda_dll_dirs()
    if device in ("auto", "cuda"):
        try:
            return WhisperModel(name, device="cuda", compute_type="float16")
        except (RuntimeError, ValueError):
            if device == "cuda":
                raise
    return WhisperModel(name, device="cpu", compute_type="int8")


def transcribe(model, audio: Path, lang: str) -> tuple[list[Word], list[Line]]:
    """Word timings and Whisper's own lines. No VAD: music is not speech and VAD drops sung parts."""
    segments, _ = model.transcribe(str(audio), language=lang, word_timestamps=True, vad_filter=False,
                                   condition_on_previous_text=False)
    words: list[Word] = []
    lines: list[Line] = []
    for s in segments:
        text = s.text.strip()
        if text:
            lines.append(Line(text, s.start, s.end))
        words += [Word(w.word.strip(), w.start, w.end) for w in s.words or [] if w.word.strip()]
    return words, lines


# ---------- aligning given lyrics to Whisper's words ----------

def _norm(w: str) -> str:
    return re.sub(r"[^\w]", "", w.lower())


def _tokens(text: str) -> list[str]:
    return [t for t in (_norm(w) for w in re.split(r"[\s\-‐-―]+", text)) if t]


def align(lyrics: list[str], words: list[Word]) -> list[Line]:
    """Give each lyric line the time of its words that Whisper heard; lines with no match are spread evenly
    between their timed neighbours."""
    lines = [ln.strip() for ln in lyrics if ln.strip()]
    flat = [(i, t) for i, ln in enumerate(lines) for t in _tokens(ln)]
    heard = [_norm(w.text) for w in words]
    match: dict[int, int] = {}
    sm = difflib.SequenceMatcher(None, [t for _, t in flat], heard, autojunk=False)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            match[a + k] = b + k
    spans: list[tuple[float, float] | None] = []
    for i in range(len(lines)):
        hits = [match[k] for k, (li, _) in enumerate(flat) if li == i and k in match]
        spans.append((words[hits[0]].start, words[hits[-1]].end) if hits else None)
    _fill_gaps(spans, lines, total=words[-1].end if words else 0.0)
    return [Line(t, s[0], s[1]) for t, s in zip(lines, spans, strict=True)]


def _fill_gaps(spans: list, lines: list[str], total: float) -> None:
    i = 0
    while i < len(spans):
        if spans[i] is not None:
            i += 1
            continue
        j = i
        while j < len(spans) and spans[j] is None:
            j += 1
        lo = spans[i - 1][1] if i > 0 else 0.0
        hi = spans[j][0] if j < len(spans) else max(total, lo)
        weights = [max(len(_tokens(lines[k])), 1) for k in range(i, j)]
        step = (hi - lo) / sum(weights) if hi > lo else 0.0
        t = lo
        for k, w in zip(range(i, j), weights, strict=True):
            spans[k] = (t, t + w * step)
            t += w * step
        i = j
    for k in range(1, len(spans)):          # keep the order even if Whisper matched a repeated line early
        if spans[k][0] < spans[k - 1][0]:
            spans[k] = (spans[k - 1][0], max(spans[k][1], spans[k - 1][0]))


# ---------- output ----------

def _stamp(t: float) -> str:
    m, s = divmod(max(t, 0.0), 60)
    return f"[{int(m):02d}:{s:05.2f}]"


def to_lrc(lines: list[Line], title: str = "", transcribed: bool = False) -> str:
    out = [f"[ti:{title}]"] if title else []
    out.append(MARK_TRANSCRIBED if transcribed else MARK_ALIGNED)
    for k, ln in enumerate(lines):
        out.append(f"{_stamp(ln.start)}{ln.text}")
        nxt = lines[k + 1].start if k + 1 < len(lines) else None
        if nxt is None or nxt - ln.end > GAP:
            out.append(_stamp(ln.end))
    return "\n".join(out) + "\n"


def read_lyrics(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
