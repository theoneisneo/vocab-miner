"""Per-line explanations ("why is it translated like this"), written ahead of time and shown in the sing-along page.

Stored per source in data/explain/<source_id>.jsonl, one JSON object per line:
    {"id": "<utterance id>", "text": "<explanation>", "origin": "machine" | "user"}
Like the gloss table, tools only append explanations for lines that have none, so edits are never overwritten.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from .model import Token, Utterance


def explain_path(data_dir: Path, source_id: str) -> Path:
    return data_dir.joinpath("explain", *source_id.split("/")).with_suffix(".jsonl")


def read_explanations(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("id") and row.get("text"):
            out.setdefault(row["id"], row["text"])
    return out


def append_explanations(path: Path, rows: Iterable[Mapping[str, str]], origin: str = "machine") -> int:
    """Append explanations for lines that have none yet. Returns the number added."""
    existing = set(read_explanations(path))
    new = []
    for r in rows:
        if r.get("id") and r.get("explanation", r.get("text")) and r["id"] not in existing:
            existing.add(r["id"])
            new.append({"id": r["id"], "text": r.get("explanation") or r.get("text"),
                        "origin": r.get("origin") or origin})
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for row in new:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(new)


def source_of(utt_id: str) -> str:
    """'songs/artist:359:001' -> 'songs/artist' (utterance ids are '<source_id>:<local id>')."""
    return utt_id.split(":", 1)[0]


def todo_row(u: Utterance, tokens: Sequence[Token], glosses: Mapping[str, str], title: str,
             prev: Utterance | None, nxt: Utterance | None, lang: str = "zh-Hant") -> dict:
    """Everything a person or an AI needs to explain one line; fill in "explanation" and import it back."""
    words = [{"surface": t.surface, "lemma": t.base or t.lemma, "reading": t.reading or "",
              "gloss": glosses.get(t.key, "")} for t in tokens if t.pos not in ("PUNCT", "SYM")]
    return {
        "id": u.id, "title": title, "text": u.text,
        "reading": "".join(t.reading or t.surface for t in tokens),
        "words": words, "translation": u.translations.get(lang, ""),
        "prev": prev.text if prev else "", "next": nxt.text if nxt else "",
        "explanation": "",
    }
