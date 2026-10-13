"""SQLite index (.cache/index.sqlite): utterances, tokens, lemma -> utterance lookups.

Rebuilt per corpus file when the file, the tokenizer, or the source's name list changes.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Self

from .model import NO_STATS_TAG, Token, Utterance, read_jsonl

SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS corpus_files (
    source_id TEXT PRIMARY KEY, path TEXT NOT NULL, signature TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS utterances (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, doc_id TEXT NOT NULL, seq INTEGER NOT NULL,
    lang TEXT NOT NULL, text TEXT NOT NULL, no_stats INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tokens (
    utt_id TEXT NOT NULL, i INTEGER NOT NULL, surface TEXT NOT NULL, lemma TEXT NOT NULL,
    reading TEXT, pos TEXT NOT NULL, pos_native TEXT NOT NULL, start INTEGER NOT NULL, "end" INTEGER NOT NULL,
    is_proper INTEGER NOT NULL, base TEXT, lemma_reading TEXT, key TEXT NOT NULL,
    PRIMARY KEY (utt_id, i));
CREATE INDEX IF NOT EXISTS tokens_key ON tokens(key);
CREATE INDEX IF NOT EXISTS utterances_source ON utterances(source_id, doc_id, seq);
"""

TOKEN_COLS = ("surface", "lemma", "reading", "pos", "pos_native", "start", "end", "is_proper", "base",
              "lemma_reading")


def file_digest(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


class Index:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if self._meta("schema") not in (None, SCHEMA_VERSION):
            self.clear()
        self._set_meta("schema", SCHEMA_VERSION)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------- meta ----------

    def _meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
        self.db.commit()

    def clear(self) -> None:
        self.db.executescript("DELETE FROM tokens; DELETE FROM utterances; DELETE FROM corpus_files;")
        self.db.commit()

    # ---------- building ----------

    def add_source(self, source_id: str, path: Path, signature: str,
                   utterances: Iterable[Utterance], tokenize: Callable[[Utterance], list[Token]]) -> int:
        with self.db:
            self._delete_source(source_id)
            n = 0
            for u in utterances:
                self.db.execute(
                    "INSERT INTO utterances VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (u.id, u.source_id, u.doc_id, u.seq, u.lang, u.text, int(NO_STATS_TAG in u.tags),
                     json.dumps(asdict(u), ensure_ascii=False)))
                self.db.executemany(
                    "INSERT INTO tokens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(u.id, i, t.surface, t.lemma, t.reading, t.pos, t.pos_native, t.start, t.end,
                      int(t.is_proper), t.base, t.lemma_reading, t.key) for i, t in enumerate(tokenize(u))])
                n += 1
            self.db.execute("INSERT INTO corpus_files VALUES (?, ?, ?)", (source_id, str(path), signature))
        return n

    def _delete_source(self, source_id: str) -> None:
        self.db.execute("DELETE FROM tokens WHERE utt_id IN (SELECT id FROM utterances WHERE source_id = ?)",
                        (source_id,))
        self.db.execute("DELETE FROM utterances WHERE source_id = ?", (source_id,))
        self.db.execute("DELETE FROM corpus_files WHERE source_id = ?", (source_id,))

    def signature(self, source_id: str) -> str | None:
        row = self.db.execute("SELECT signature FROM corpus_files WHERE source_id = ?", (source_id,)).fetchone()
        return row[0] if row else None

    def source_ids(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT source_id FROM corpus_files ORDER BY source_id")]

    def remove_missing(self, keep: set[str]) -> list[str]:
        gone = [s for s in self.source_ids() if s not in keep]
        with self.db:
            for s in gone:
                self._delete_source(s)
        return gone

    # ---------- queries ----------

    def utterance(self, utt_id: str) -> Utterance | None:
        row = self.db.execute("SELECT data FROM utterances WHERE id = ?", (utt_id,)).fetchone()
        return Utterance.from_dict(json.loads(row[0])) if row else None

    def utterances(self, ids: Iterable[str]) -> dict[str, Utterance]:
        out = {}
        for i in ids:
            if (u := self.utterance(i)) is not None:
                out[i] = u
        return out

    def tokens(self, utt_id: str) -> list[Token]:
        rows = self.db.execute(f"SELECT {', '.join(map(_q, TOKEN_COLS))} FROM tokens WHERE utt_id = ? ORDER BY i",
                               (utt_id,))
        return [_token(r) for r in rows]

    def iter_tokens(self, source_ids: list[str] | None = None, doc_ids: list[str] | None = None,
                    include_no_stats: bool = False) -> Iterator[tuple[str, str, str, Token]]:
        """Yield (utt_id, source_id, doc_id, token) in corpus order."""
        where, args = [], []
        if not include_no_stats:
            where.append("u.no_stats = 0")
        if source_ids:
            where.append(f"u.source_id IN ({','.join('?' * len(source_ids))})")
            args += source_ids
        if doc_ids:
            where.append(f"u.doc_id IN ({','.join('?' * len(doc_ids))})")
            args += doc_ids
        sql = (f"SELECT u.id, u.source_id, u.doc_id, {', '.join('t.' + _q(c) for c in TOKEN_COLS)} "
               "FROM tokens t JOIN utterances u ON u.id = t.utt_id "
               f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY u.source_id, u.doc_id, u.seq, t.i")
        for r in self.db.execute(sql, args):
            yield r[0], r[1], r[2], _token(r, offset=3)

    def utterance_ids_for(self, key: str) -> list[str]:
        """Inverted index: every utterance (including no-stats ones) containing the entry."""
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT t.utt_id FROM tokens t JOIN utterances u ON u.id = t.utt_id "
            "WHERE t.key = ? ORDER BY u.source_id, u.doc_id, u.seq", (key,))]

    def iter_utterances(self, source_ids: list[str] | None = None,
                        doc_ids: list[str] | None = None) -> Iterator[Utterance]:
        """All utterances (including no-stats ones) in corpus order."""
        where, args = [], []
        if source_ids:
            where.append(f"source_id IN ({','.join('?' * len(source_ids))})")
            args += source_ids
        if doc_ids:
            where.append(f"doc_id IN ({','.join('?' * len(doc_ids))})")
            args += doc_ids
        sql = (f"SELECT data FROM utterances {'WHERE ' + ' AND '.join(where) if where else ''} "
               "ORDER BY source_id, doc_id, seq")
        for (data,) in self.db.execute(sql, args).fetchall():
            yield Utterance.from_dict(json.loads(data))

    def doc_titles(self) -> dict[tuple[str, str], str]:
        """(source_id, doc_id) -> display title, from a "title:<name>" tag if any, else the doc id."""
        titles: dict[tuple[str, str], str] = {}
        for r in self.db.execute("SELECT source_id, doc_id, data FROM utterances ORDER BY source_id, doc_id, seq"):
            k = (r[0], r[1])
            if k in titles:
                continue
            tags = json.loads(r[2]).get("tags", [])
            titles[k] = next((t[6:] for t in tags if t.startswith("title:")), r[1])
        return titles


def _q(col: str) -> str:
    return f'"{col}"'


def _token(row, offset: int = 0) -> Token:
    vals = [row[offset + i] for i in range(len(TOKEN_COLS))]
    d = dict(zip(TOKEN_COLS, vals, strict=True))
    d["is_proper"] = bool(d["is_proper"])
    return Token(**d)


def build_index(index: Index, corpus_files: dict[str, Path], tokenizer_for: Callable[[str], object],
                tokenizer_id: str, names_for: Callable[[str], list[str]], force: bool = False,
                log: Callable[[str], None] = print) -> None:
    """(Re)index corpus files whose content, tokenizer, or name list changed; drop sources no longer present."""
    for gone in index.remove_missing(set(corpus_files)):
        log(f"{gone}: removed from index")
    for source_id, path in sorted(corpus_files.items()):
        names = names_for(source_id)
        sig = hashlib.sha1("\n".join([file_digest(path), tokenizer_id, *sorted(names)]).encode()).hexdigest()
        if not force and index.signature(source_id) == sig:
            log(f"{source_id}: up to date")
            continue
        tok = tokenizer_for(source_id)
        tokenize = _utterance_tokenizer(tok)
        n = index.add_source(source_id, path, sig, read_jsonl(path), tokenize)
        log(f"{source_id}: indexed {n} utterances")


def _utterance_tokenizer(tok) -> Callable[[Utterance], list[Token]]:
    """Use the source's own reading (Utterance.reading_hint) to correct readings when the tokenizer supports it."""
    with_hint = getattr(tok, "tokenize_with_hint", None)
    if with_hint:
        return lambda u: with_hint(u.text, u.reading_hint)
    return lambda u: tok.tokenize(u.text)
