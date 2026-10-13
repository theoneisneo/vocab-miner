"""CSV vocabulary list (UTF-8 with BOM so Excel opens it correctly)."""
from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..model import MediaRef, Utterance, VocabEntry

COLUMNS = ["rank", "lemma", "reading", "romaji", "pos", "gloss_zh", "gloss_en", "count", "doc_freq", "coverage",
           "forms", "docs", "false_friend", "jlpt", "status", "example", "example_zh", "example_link"]


def media_link(m: MediaRef | None) -> str:
    if m is None:
        return ""
    if m.kind == "youtube":
        return f"https://www.youtube.com/watch?v={m.uri}" + (f"&t={int(m.start)}s" if m.start is not None else "")
    return m.uri + (f"#t={m.start:.2f}" if m.start is not None else "")


class CsvExporter:
    def __init__(self, gloss_zh: str = "zh-Hant", gloss_en: str = "en", sep: str = "、"):
        self.gloss_zh, self.gloss_en, self.sep = gloss_zh, gloss_en, sep

    def row(self, e: VocabEntry, utterances: Mapping[str, Utterance]) -> dict[str, object]:
        ex = utterances.get(e.examples[0]) if e.examples else None
        return {
            "rank": e.rank, "lemma": e.lemma, "reading": e.reading or "", "romaji": e.romaji or "",
            "pos": e.pos_label or e.pos, "gloss_zh": e.gloss.get(self.gloss_zh, ""),
            "gloss_en": e.gloss.get(self.gloss_en, ""), "count": e.count, "doc_freq": e.doc_freq,
            "coverage": f"{e.coverage:.1%}", "forms": self.sep.join(e.forms), "docs": self.sep.join(e.docs),
            "false_friend": f"⚠ {e.false_friend}" if e.false_friend else "", "jlpt": e.jlpt or "",
            "status": e.status, "example": ex.text if ex else "",
            "example_zh": ex.translations.get(self.gloss_zh, "") if ex else "",
            "example_link": media_link(ex.media) if ex else "",
        }

    def export(self, entries: Sequence[VocabEntry], utterances: Mapping[str, Utterance], out: Path) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for e in entries:
                w.writerow(self.row(e, utterances))
