"""Learning-order rankers."""
from __future__ import annotations

from collections.abc import Sequence

from .model import VocabEntry


class FrequencyRanker:
    """Words found in the most docs first (songs, scenes), then by total count.

    by = "doc_freq" (default) or "count". Known words keep their place; exporters show their status.
    """

    def __init__(self, by: str = "doc_freq"):
        if by not in ("doc_freq", "count"):
            raise ValueError(f"by must be doc_freq or count, got {by!r}")
        self.by = by

    def rank(self, entries: Sequence[VocabEntry], known: set[str]) -> list[VocabEntry]:
        if self.by == "doc_freq":
            key = (lambda e: (-e.doc_freq, -e.count, e.key))
        else:
            key = (lambda e: (-e.count, -e.doc_freq, e.key))
        out = sorted(entries, key=key)
        for i, e in enumerate(out, 1):
            e.rank = i
        return out
