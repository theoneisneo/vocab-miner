"""When each piece of a line is sung, for the web app's word-by-word highlight (experimental).

Input: word timings heard by speech recognition for a song, [[text, start, end], ...] (Whisper's words, as
`vm songs` / `vm transcribe` keep them in <lyrics folder>/.words/<video id>.words.json). Each line of the song is
compared character by character with the words heard during it; a piece of the line (a seg entry) gets the start
time of its first character that was heard. Pieces not heard get no time: the app spreads the line's time over
them by their length.
"""
from __future__ import annotations

import difflib
import json
from collections.abc import Sequence
from pathlib import Path

from .transcribe import _tokens

WINDOW = 0.8        # seconds around a line in which its words are looked for


def read_words(path: Path) -> list[tuple[str, float, float]]:
    return [(t, float(s), float(e)) for t, s, e in json.loads(path.read_text(encoding="utf-8"))]


def write_words(path: Path, words: Sequence) -> None:
    """Whisper's words ([Word] or (text, start, end)) as [[text, start, end], ...]."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [[w.text, round(w.start, 2), round(w.end, 2)] if hasattr(w, "text") else [w[0], round(w[1], 2), round(w[2], 2)]
            for w in words]
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def add_piece_times(lines: list[dict], words: Sequence[tuple[str, float, float]]) -> int:
    """Append each matched piece's start time to its seg entry (seg[k][4]); returns the pieces timed."""
    timed = 0
    for i, line in enumerate(lines):
        start = line.get("start")
        if start is None:
            continue
        end = line.get("end")
        if end is None:
            end = next((ln["start"] for ln in lines[i + 1:] if ln.get("start") is not None), start + 8)
        heard = [(t, wi) for wi, (text, s, _) in enumerate(words) if start - WINDOW <= s <= end + WINDOW
                 for t in _tokens(text)]
        chars = [(k, t) for k, piece in enumerate(line["seg"]) for t in _tokens(piece[0])]
        if not heard or not chars:
            continue
        sm = difflib.SequenceMatcher(None, [t for _, t in chars], [t for t, _ in heard], autojunk=False)
        first: dict[int, float] = {}
        for a, b, size in sm.get_matching_blocks():
            for n in range(size):
                k = chars[a + n][0]
                first.setdefault(k, words[heard[b + n][1]][1])
        last = -1.0
        for k, piece in enumerate(line["seg"]):
            t = first.get(k)
            if t is not None and t >= last:               # keep the order; an out-of-order match is dropped
                while len(piece) < 4:
                    piece.append(None)
                piece[4:] = [round(t, 2)]
                last = t
                timed += 1
    return timed
