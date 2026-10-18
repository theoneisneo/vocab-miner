"""Core data model. The Utterance JSONL format is the public contract between sources and the pipeline."""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

# Utterances with this tag are left out of frequency/coverage statistics but may still be used as examples
# (e.g. an alternate recording of a song that is already in the corpus).
NO_STATS_TAG = "no-stats"


@dataclass(frozen=True)
class MediaRef:
    kind: Literal["youtube", "file"]
    uri: str                      # YouTube video id, or local file path
    start: float | None = None    # seconds
    end: float | None = None


@dataclass
class Utterance:
    id: str                       # "<source_id>:<local_id>", globally unique
    source_id: str                # e.g. "songs/artist-x"
    doc_id: str                   # unit inside the source: one song, one scene
    seq: int                      # order inside the doc
    lang: str                     # BCP-47
    text: str                     # original text, control codes removed
    translations: dict[str, str] = field(default_factory=dict)
    reading_hint: str | None = None
    speaker: str | None = None
    media: MediaRef | None = None
    tags: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> Utterance:
        media = d.get("media")
        return cls(**{**d, "media": MediaRef(**media) if media else None})


@dataclass(frozen=True)
class Token:
    surface: str
    lemma: str                    # dictionary lemma; with lemma_reading it identifies a vocabulary entry
    reading: str | None           # reading of the surface form (ja: hiragana), for ruby/furigana
    pos: str                      # Universal POS (NOUN, VERB, ADP, ...)
    pos_native: str               # language-specific POS, e.g. UniDic "名詞-普通名詞-一般"
    start: int
    end: int
    is_proper: bool = False
    base: str | None = None       # base form as written in the text (ja: する rather than 為る); display form
    lemma_reading: str | None = None

    @property
    def key(self) -> str:
        """Identity of the vocabulary entry this token belongs to."""
        return f"{self.lemma}	{self.lemma_reading or ''}"


@dataclass
class VocabEntry:
    lemma: str                     # display form (most common written base form)
    lang: str
    pos: str                       # UPOS
    key: str = ""                  # Token.key of the grouped tokens
    pos_label: str | None = None   # learner-facing POS name, language specific
    reading: str | None = None
    romaji: str | None = None
    gloss: dict[str, str] = field(default_factory=dict)   # {"zh-Hant": ..., "en": ...}
    count: int = 0
    doc_freq: int = 0
    coverage: float = 0.0          # cumulative token coverage up to this entry
    forms: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    false_friend: str | None = None
    jlpt: str | None = None
    status: Literal["new", "learning", "known"] = "new"
    examples: list[str] = field(default_factory=list)      # Utterance ids
    origin: str | None = None      # source word of a loanword (ja: アイドル <- idol), when the dictionary knows it
    rank: int = 0


def write_jsonl(path: Path, utterances: Iterable[Utterance]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for u in utterances:
            f.write(u.to_json() + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> Iterator[Utterance]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield Utterance.from_dict(json.loads(line))
