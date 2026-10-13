"""Anki deck (.apkg) export. Install with `uv sync --extra anki` (genanki).

One note per vocabulary entry; new cards come in learning order (rank). Notes have stable GUIDs derived from
the entry, so re-importing an updated deck updates existing notes and keeps your review history.
"""
from __future__ import annotations

import hashlib
import html
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from ..model import Token, Utterance, VocabEntry
from ..render import anki_furigana
from .csv import media_link

# v2 adds FrontHint (romaji on the front while kana are new). Toggling it only changes field content,
# so re-importing updates notes in place.
MODEL_NAME = "vocab-miner word v2"

FIELDS = ["Key", "Word", "Reading", "Romaji", "POS", "Meaning", "English", "Warning",
          "Example", "ExampleRomaji", "ExampleMeaning", "Link", "Source", "Rank", "FrontHint"]

FRONT = """
<div class="word">{{Word}}</div>
{{#Reading}}<div class="reading">{{Reading}}</div>{{/Reading}}
{{#FrontHint}}<div class="front-hint">{{FrontHint}}</div>{{/FrontHint}}
"""

BACK = """
{{FrontSide}}
<hr id="answer">
{{^FrontHint}}<div class="romaji">{{Romaji}}</div>{{/FrontHint}}
<div class="meaning">{{Meaning}}</div>
{{#Warning}}<div class="warning">⚠ {{Warning}}</div>{{/Warning}}
<div class="pos">{{POS}}</div>
{{#English}}<div class="english">{{English}}</div>{{/English}}
{{#Example}}
<div class="example">{{furigana:Example}}</div>
<div class="example-romaji">{{ExampleRomaji}}</div>
<div class="example-meaning">{{ExampleMeaning}}</div>
{{/Example}}
{{#Link}}<div class="link">{{Link}}</div>{{/Link}}
<div class="source">{{Source}}</div>
"""

CSS = """
.card { font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic", sans-serif; font-size: 20px;
        text-align: center; color: #1f1f1f; background: #fafafa; line-height: 1.5; }
.nightMode.card, .night_mode .card { color: #e8e8e8; background: #1e1e1e; }
.word { font-size: 2.4em; margin-top: .4em; }
.reading { font-size: 1.1em; color: #666; }
.romaji { font-size: .95em; color: #888; letter-spacing: .03em; }
.front-hint { font-size: 1.2em; color: #2563eb; letter-spacing: .04em; margin-top: .2em; }
.nightMode .front-hint, .night_mode .front-hint { color: #93c5fd; }
.meaning { font-size: 1.3em; margin: .4em 0; }
.warning { color: #b45309; margin: .3em 0; }
.pos, .source { font-size: .75em; color: #888; }
.english { font-size: .8em; color: #777; margin-bottom: .6em; }
.example { font-size: 1.15em; margin-top: .8em; }
.example b { color: #2563eb; }
.example ruby rt { font-size: .55em; color: #888; }
.example-romaji { font-size: .75em; color: #888; }
.example-meaning { font-size: .9em; }
.link { margin-top: .6em; font-size: .85em; }
.nightMode .example b, .night_mode .example b { color: #93c5fd; }
"""


def _stable_id(name: str) -> int:
    """Anki model/deck ids: stable 31-bit-ish positive ints derived from a name."""
    return int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16) + (1 << 30)


class AnkiExporter:
    """Options: deck (deck name), limit (only the first N new words), include_known (default False),
    romaji_front (romaji on the front of the card, default False)."""

    def __init__(self, deck: str = "vocab-miner", limit: int | None = None, include_known: bool = False,
                 romaji_front: bool = False,
                 romanize_tokens: Callable[[Sequence[Token]], str] | None = None):
        self.deck = deck
        self.limit = limit
        self.include_known = include_known
        self.romanize_tokens = romanize_tokens
        self.romaji_front = romaji_front        # show romaji on the front (for learners who cannot read kana yet)

    def _model(self):
        import genanki

        return genanki.Model(
            _stable_id(MODEL_NAME), MODEL_NAME,
            fields=[{"name": f} for f in FIELDS],
            templates=[{"name": "Word → meaning", "qfmt": FRONT, "afmt": BACK}],
            css=CSS, sort_field_index=FIELDS.index("Rank"),
        )

    def fields(self, e: VocabEntry, utterances: Mapping[str, Utterance],
               tokens: Mapping[str, list[Token]]) -> list[str]:
        ex = utterances.get(e.examples[0]) if e.examples else None
        example = ex_romaji = ex_meaning = link = ""
        if ex is not None:
            toks = tokens.get(ex.id, [])
            hl = {i for i, t in enumerate(toks) if t.key == e.key}
            example = anki_furigana(ex.text, toks, hl) if toks else html.escape(ex.text)
            ex_romaji = html.escape(self.romanize_tokens(toks)) if self.romanize_tokens and toks else ""
            ex_meaning = html.escape(ex.translations.get("zh-Hant", "") or next(iter(ex.translations.values()), ""))
            url = media_link(ex.media)
            if url.startswith("http"):
                link = f'<a href="{html.escape(url)}">▶ 聽這一句</a>'
        show_reading = e.reading and e.reading != e.lemma
        return [
            e.key.replace("\t", "|"), html.escape(e.lemma), html.escape(e.reading or "") if show_reading else "",
            html.escape(e.romaji or ""), html.escape(e.pos_label or e.pos),
            html.escape(e.gloss.get("zh-Hant", "")), html.escape(e.gloss.get("en", "")),
            html.escape(e.false_friend or ""), example, ex_romaji, ex_meaning, link,
            html.escape("、".join(e.docs[:5])), str(e.rank),
            html.escape(e.romaji or "") if self.romaji_front else "",
        ]

    def export(self, entries: Sequence[VocabEntry], utterances: Mapping[str, Utterance], out: Path,
               tokens: Mapping[str, list[Token]] | None = None) -> int:
        import genanki

        tokens = tokens or {}
        chosen = [e for e in entries if self.include_known or e.status != "known"]
        if self.limit:
            chosen = chosen[: self.limit]
        model = self._model()
        deck = genanki.Deck(_stable_id(f"deck:{self.deck}"), self.deck)
        for e in chosen:
            deck.add_note(genanki.Note(model=model, fields=self.fields(e, utterances, tokens),
                                       guid=genanki.guid_for("vocab-miner", e.lang, e.key), due=e.rank))
        out.parent.mkdir(parents=True, exist_ok=True)
        genanki.Package(deck).write_to_file(str(out))
        return len(chosen)
