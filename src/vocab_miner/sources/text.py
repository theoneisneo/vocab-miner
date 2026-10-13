"""Plain text files (.txt): one file or a directory of files, one doc per file."""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from ..model import Utterance
from ..textclean import clean
from . import iter_files, read_text

# split after sentence-final punctuation (and any closing quotes/brackets that follow it)
SENTENCE_END = re.compile(r"(?<=[。！？!?…])[」』）)\"'”’]*")


def split_sentences(text: str) -> list[str]:
    out, start = [], 0
    for m in SENTENCE_END.finditer(text):
        out.append(text[start:m.end()])
        start = m.end()
    out.append(text[start:])
    return [s.strip() for s in out if s.strip()]


class TextSource:
    """Options:
    split = "line"       each non-empty line is an utterance (default; good for lyrics and line-based scripts)
            "paragraph"  blank-line separated blocks; line breaks inside a block are treated as layout
            "sentence"   paragraphs further split at 。！？!? (good for prose)
    """

    def __init__(self, source_id: str, path: str | Path, lang: str,
                 split: Literal["line", "paragraph", "sentence"] = "line", control_codes: bool = True):
        if split not in ("line", "paragraph", "sentence"):
            raise ValueError(f"split must be line/paragraph/sentence, got {split!r}")
        self.source_id = source_id
        self.path = Path(path)
        self.lang = lang
        self.split = split
        self.control_codes = control_codes

    def _chunks(self, text: str) -> list[str]:
        if self.split == "line":
            return text.split("\n")
        paragraphs = re.split(r"\n\s*\n", text)
        if self.split == "paragraph":
            return paragraphs
        return [s for p in paragraphs for s in split_sentences(clean(p, control_codes=self.control_codes))]

    def utterances(self) -> Iterator[Utterance]:
        for doc_id, file in iter_files(self.path, (".txt",)):
            seq = 0
            for chunk in self._chunks(read_text(file)):
                text = clean(chunk, control_codes=self.control_codes)
                if not text:
                    continue
                seq += 1
                yield Utterance(id=f"{self.source_id}:{doc_id}:{seq}", source_id=self.source_id,
                                doc_id=doc_id, seq=seq, lang=self.lang, text=text)
