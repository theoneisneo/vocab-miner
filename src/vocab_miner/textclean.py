"""Text cleanup shared by sources: control codes, layout line breaks, whitespace."""
from __future__ import annotations

import html
import re

# <tag ...>, </tag>, {0}, {name}, [tag] -- markup and placeholders commonly found in game/subtitle text
TAG = re.compile(r"</?[A-Za-z][^<>]*>|\{[^{}]*\}|\[[^\[\]]*\]")
WS = re.compile(r"[ \t　]+")
CJK = r"、-ヿ㐀-鿿豈-﫿＀-￯"
CJK_GAP = re.compile(rf"(?<=[{CJK}]) (?=[{CJK}])")


def strip_control_codes(text: str) -> str:
    return TAG.sub("", text)


def join_layout_breaks(text: str) -> str:
    """Line breaks inside one utterance are usually layout, not sentence boundaries.

    Joined with a space, which is then dropped between CJK characters.
    """
    text = re.sub(r"\s*(?:\r\n|\r|\n|\\r\\n|\\n)\s*", " ", text)
    return CJK_GAP.sub("", text)


def normalize_space(text: str) -> str:
    return WS.sub(" ", text).strip()


def clean(text: str, *, control_codes: bool = True) -> str:
    text = html.unescape(text)          # &amp; &#39; ... from web-sourced subtitles and lyrics
    if control_codes:
        text = strip_control_codes(text)
    return normalize_space(join_layout_breaks(text))
