"""Plugin interfaces. Implementations are loaded from config as "module.path:ClassName"."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from .model import Token, Utterance, VocabEntry


@runtime_checkable
class Source(Protocol):
    """Turns some material into utterances. Fill only what the material actually has."""
    source_id: str

    def utterances(self) -> Iterable[Utterance]: ...


@runtime_checkable
class LineMerger(Protocol):
    """Optional for a Source: join lines merged in the web app in its own files (`vm apply-edits`). Each group is
    the start times of consecutive lines of one doc; returns how many groups were merged."""

    def merge_lines(self, doc_id: str, groups: Sequence[Sequence[float]]) -> int: ...


@runtime_checkable
class Tokenizer(Protocol):
    lang: str

    def tokenize(self, text: str) -> list[Token]: ...


@runtime_checkable
class Romanizer(Protocol):
    """Reading -> learner-friendly Latin spelling (e.g. Hepburn without macrons for ja)."""
    lang: str

    def romanize(self, reading: str) -> str: ...


@runtime_checkable
class Dictionary(Protocol):
    """lemma (+reading, pos) -> glosses per target language."""
    lang: str

    def lookup(self, lemma: str, reading: str | None = None, pos: str | None = None,
               base: str | None = None) -> Mapping[str, str]: ...


@runtime_checkable
class Ranker(Protocol):
    def rank(self, entries: Sequence[VocabEntry], known: set[str]) -> list[VocabEntry]: ...


@runtime_checkable
class ExampleSelector(Protocol):
    """Pick example utterance ids for each entry at build time (see docs/architecture.md §2)."""

    def select(self, entry: VocabEntry, candidates: Sequence[Utterance], known: set[str], k: int) -> list[str]: ...


@runtime_checkable
class Exporter(Protocol):
    def export(self, entries: Sequence[VocabEntry], utterances: Mapping[str, Utterance], out: Path) -> None: ...
