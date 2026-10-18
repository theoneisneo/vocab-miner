"""User-editable gloss table, e.g. data/gloss/ja-zh.tsv.

Columns: lemma <TAB> reading <TAB> gloss <TAB> origin <TAB> pos <TAB> short
  origin = "machine" for generated drafts, anything else (e.g. "user") for your own entries.
  pos    = optional Universal POS (NOUN, VERB, AUX, ...) to tell apart words with the same spelling and reading.
  short  = optional short meaning for the sing-along page's word-by-word line (default: the gloss's first sense).
Rows are never overwritten by tools: generated drafts are only appended for words not in the file yet,
so editing a row (with or without changing origin) is always safe.
"""
from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path

HEADER = ["lemma", "reading", "gloss", "origin", "pos", "short"]


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if rows and rows[0][:2] == HEADER[:2]:
        rows = rows[1:]
    n = len(HEADER)
    return [dict(zip(HEADER, (r + [""] * n)[:n], strict=True)) for r in rows if r and r[0].strip()]


def _key(r: Mapping[str, str]) -> tuple[str, str, str]:
    return r["lemma"], r.get("reading", ""), r.get("pos", "")


def append_rows(path: Path, rows: Iterable[Mapping[str, str]]) -> int:
    """Append rows whose (lemma, reading, pos) is not in the file yet. Returns the number added."""
    seen = {_key(r) for r in read_rows(path)}
    new = []
    for r in rows:
        if _key(r) not in seen:
            seen.add(_key(r))
            new.append(r)
    if not new:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        if write_header:
            w.writerow(HEADER)
        for r in new:
            w.writerow([r["lemma"], r.get("reading", ""), r.get("gloss", ""), r.get("origin", "machine"),
                        r.get("pos", ""), r.get("short", "")])
    return len(new)


class TsvGlossDictionary:
    """Dictionary plugin. Options: path, gloss_lang (e.g. "zh-Hant")."""

    def __init__(self, path: str | Path, gloss_lang: str, lang: str = "ja"):
        self.path = Path(path)
        self.gloss_lang = gloss_lang
        self.lang = lang
        self._table: dict[tuple[str, str, str], dict[str, str]] | None = None

    @property
    def table(self) -> dict[tuple[str, str, str], dict[str, str]]:
        if self._table is None:
            self._table = {}
            for r in read_rows(self.path):
                if r["gloss"]:
                    self._table.setdefault(_key(r), r)
                    self._table.setdefault((r["lemma"], r["reading"], "*"), r)   # any pos
        return self._table

    def lookup(self, lemma: str, reading: str | None = None, pos: str | None = None,
               base: str | None = None) -> Mapping[str, str]:
        """{gloss_lang: gloss}, plus {"<gloss_lang>:short": short} when the row has a short meaning."""
        for p in ([pos] if pos else []) + ["", "*"]:
            for w in (base, lemma):
                for r in (reading or "", ""):
                    if w and (w, r, p) in self.table:
                        row = self.table[(w, r, p)]
                        out = {self.gloss_lang: row["gloss"]}
                        if row.get("short"):
                            out[f"{self.gloss_lang}:short"] = row["short"]
                        return out
        return {}
