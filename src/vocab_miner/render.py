"""Turn a tokenized sentence into ruby segments (text with readings over the kanji), for cards and web pages."""
from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass

from .model import Token

KANA = r"ぁ-ゖァ-ヺー"
KANA_RUN = re.compile(rf"[{KANA}]+|[^{KANA}]+")
NEEDS_RUBY = re.compile(r"[㐀-鿿豈-﫿々〆ヶ]")   # kanji, 々, 〆, ヶ


def _hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


@dataclass(frozen=True)
class Segment:
    text: str
    ruby: str | None = None        # reading to show above text, only where it adds something
    token: int | None = None       # index of the token this piece belongs to (None for gaps)


def split_okurigana(surface: str, reading: str) -> list[tuple[str, str | None]]:
    """食べ/たべ -> [(食, た), (べ, None)];  お茶/おちゃ -> [(お, None), (茶, ちゃ)].

    Kana inside the surface must appear in the reading; if the pieces cannot be matched the whole surface
    gets the whole reading.
    """
    runs = KANA_RUN.findall(surface)
    pattern = "".join(f"({re.escape(_hira(r))})" if re.fullmatch(f"[{KANA}]+", r) else "(.+?)" for r in runs)
    m = re.fullmatch(pattern, _hira(reading))
    if not m:
        return [(surface, reading)]
    out = []
    for run, rd in zip(runs, m.groups(), strict=True):
        out.append((run, rd if NEEDS_RUBY.search(run) else None))
    return out


def segments(text: str, tokens: Sequence[Token]) -> list[Segment]:
    """Cover the whole text: token pieces (with ruby over kanji) and the gaps between tokens."""
    out: list[Segment] = []
    pos = 0
    for i, t in enumerate(tokens):
        if t.start < pos or text[t.start:t.end] != t.surface:
            continue                                     # defensive: skip tokens that do not line up
        if t.start > pos:
            out.append(Segment(text[pos:t.start]))
        if t.reading and NEEDS_RUBY.search(t.surface):
            out += [Segment(piece, ruby, i) for piece, ruby in split_okurigana(t.surface, t.reading)]
        else:
            out.append(Segment(t.surface, None, i))
        pos = t.end
    if pos < len(text):
        out.append(Segment(text[pos:]))
    return out


def _render(text: str, tokens: Sequence[Token], highlight: set[int], ruby_fmt) -> str:
    out, bold = [], False
    for s in segments(text, tokens):
        hl = s.token is not None and s.token in highlight
        if hl != bold:
            out.append("<b>" if hl else "</b>")
            bold = hl
        piece = html.escape(s.text)
        out.append(ruby_fmt(piece, html.escape(s.ruby)) if s.ruby else piece)
    if bold:
        out.append("</b>")
    return "".join(out)


def anki_furigana(text: str, tokens: Sequence[Token], highlight: set[int] = frozenset()) -> str:
    """Anki's {{furigana:Field}} syntax ("漢字[かんじ]", a space before each ruby base); highlighted tokens in <b>."""
    return _render(text, tokens, highlight, lambda base, rt: f" {base}[{rt}]").strip()


def html_ruby(text: str, tokens: Sequence[Token], highlight: set[int] = frozenset()) -> str:
    return _render(text, tokens, highlight, lambda base, rt: f"<ruby>{base}<rt>{rt}</rt></ruby>")
