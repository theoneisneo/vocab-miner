"""Aggregate indexed tokens into vocabulary entries, attach glosses, flags and learning status."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .index import Index
from .model import Token, VocabEntry

DEFAULT_EXCLUDE_POS = ("PUNCT", "SYM", "NUM", "X")
# function words: learned as grammar from example sentences rather than as flashcards
DEFAULT_GRAMMAR_POS = ("ADP", "PART", "SCONJ", "AUX")


@dataclass
class VocabOptions:
    exclude_pos: Sequence[str] = DEFAULT_EXCLUDE_POS
    include_proper: bool = False
    min_count: int = 1
    max_forms: int = 8
    max_docs: int = 10


@dataclass
class _Acc:
    count: int = 0
    bases: Counter = field(default_factory=Counter)
    forms: Counter = field(default_factory=Counter)
    pos: Counter = field(default_factory=Counter)
    pos_native: Counter = field(default_factory=Counter)
    docs: Counter = field(default_factory=Counter)
    lemma: str = ""
    reading: str | None = None


def collect(index: Index, lang: str, options: VocabOptions,
            word_pattern: re.Pattern | None = None, pos_label: Callable[[str], str] | None = None,
            source_ids: list[str] | None = None, doc_ids: list[str] | None = None) -> list[VocabEntry]:
    """Count lemmas over the (filtered) corpus. Utterances tagged no-stats are not counted."""
    titles = index.doc_titles()
    accs: dict[str, _Acc] = defaultdict(_Acc)
    for _, source_id, doc_id, t in index.iter_tokens(source_ids, doc_ids):
        if not keep_token(t, options, word_pattern):
            continue
        a = accs[t.key]
        a.count += 1
        a.lemma, a.reading = t.lemma, t.lemma_reading
        a.bases[t.base or t.lemma] += 1
        a.forms[t.surface] += 1
        a.pos[t.pos] += 1
        a.pos_native[t.pos_native] += 1
        a.docs[titles.get((source_id, doc_id), doc_id)] += 1

    entries = []
    for key, a in accs.items():
        if a.count < options.min_count:
            continue
        pos_native = a.pos_native.most_common(1)[0][0]
        entries.append(VocabEntry(
            lemma=a.bases.most_common(1)[0][0], lang=lang, pos=a.pos.most_common(1)[0][0], key=key,
            pos_label=pos_label(pos_native) if pos_label else None, reading=a.reading,
            count=a.count, doc_freq=len(a.docs),
            forms=[f for f, _ in a.forms.most_common(options.max_forms)],
            docs=[d for d, _ in a.docs.most_common(options.max_docs)],
        ))
    return entries


def keep_token(t: Token, options: VocabOptions, word_pattern: re.Pattern | None) -> bool:
    if t.pos in options.exclude_pos:
        return False
    if t.is_proper and not options.include_proper:
        return False
    return not (word_pattern is not None and not word_pattern.search(t.lemma))


def add_coverage(entries: Sequence[VocabEntry]) -> None:
    """Cumulative share of counted tokens covered by the entries up to and including each one (rank order)."""
    total = sum(e.count for e in entries) or 1
    running = 0
    for e in entries:
        running += e.count
        e.coverage = running / total


# ---------- known words ----------

def load_word_list(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {ln.split("\t")[0].strip() for ln in path.read_text(encoding="utf-8-sig").splitlines()
            if ln.strip() and not ln.startswith("#")}


def entry_names(e: VocabEntry) -> set[str]:
    """Strings a user may have written in a known-words file for this entry."""
    lemma = e.key.split("\t", 1)[0]
    return {e.lemma, lemma, *(f"{n}\t{e.reading}" for n in (e.lemma, lemma) if e.reading)}


def apply_status(entries: Iterable[VocabEntry], known: set[str], learning: set[str] = frozenset()) -> None:
    for e in entries:
        names = entry_names(e)
        e.status = "known" if names & known else "learning" if names & learning else "new"


# ---------- false friends ----------

def load_false_friends(lang: str, gloss_lang: str) -> dict[tuple[str, str], str]:
    name = f"false_friends_{lang}_{gloss_lang.split('-')[0]}.tsv"
    try:
        text = resources.files("vocab_miner.data").joinpath(name).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    out = {}
    for ln in text.splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        lemma, reading, note = (ln.split("\t") + ["", ""])[:3]
        out[(lemma, reading)] = note
    return out


def apply_false_friends(entries: Iterable[VocabEntry], table: dict[tuple[str, str], str]) -> None:
    for e in entries:
        lemma = e.key.split("\t", 1)[0]
        for w in dict.fromkeys((e.lemma, lemma)):
            note = table.get((w, e.reading or "")) or table.get((w, ""))
            if note:
                e.false_friend = note
                break
