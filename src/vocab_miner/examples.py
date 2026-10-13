"""Example sentence selection at build time (docs/architecture.md §2)."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence

from .model import Utterance, VocabEntry


class DefaultExampleSelector:
    """Score candidates: has audio > has translation > comfortable length; spread over different docs.

    Utterances carrying any of exclude_tags (e.g. "spoiler") are never chosen.
    """

    def __init__(self, exclude_tags: Sequence[str] = ("spoiler",), ideal_len: tuple[int, int] = (6, 30)):
        self.exclude_tags = set(exclude_tags)
        self.ideal_len = ideal_len

    def score(self, u: Utterance) -> float:
        lo, hi = self.ideal_len
        n = len(u.text)
        length = 1.0 if lo <= n <= hi else max(0.0, 1.0 - (lo - n if n < lo else n - hi) / hi)
        has_media = u.media is not None and (u.media.kind == "file" or u.media.start is not None)
        return 3.0 * has_media + 2.0 * bool(u.translations) + length

    def select(self, entry: VocabEntry, candidates: Sequence[Utterance], known: set[str], k: int) -> list[str]:
        pool = [u for u in candidates if not (self.exclude_tags & set(u.tags))]
        # ties are broken by a stable per-word hash so different words draw examples from different docs
        ranked = sorted(pool, key=lambda u: (-self.score(u), _stable_hash(entry.key, u.id)))
        chosen: list[Utterance] = []
        used_docs: set[tuple[str, str]] = set()
        for u in ranked:                       # first pass: one per doc
            if len(chosen) >= k:
                break
            if (u.source_id, u.doc_id) not in used_docs:
                chosen.append(u)
                used_docs.add((u.source_id, u.doc_id))
        for u in ranked:                       # fill up if there are fewer docs than k
            if len(chosen) >= k:
                break
            if u not in chosen:
                chosen.append(u)
        return [u.id for u in chosen]


def _stable_hash(*parts: str) -> str:
    return hashlib.blake2b("|".join(parts).encode("utf-8"), digest_size=8).hexdigest()
