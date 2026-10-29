"""Lines merged in the web app, written back to the material: `vm apply-edits <exported data file>`.

The app exports a data file where each line merged on the phone carries "merged": [{id, start, text}, ...] (the
original lines). A source that can edit its own files implements protocols.LineMerger (groups of start times);
afterwards the source is ingested again, so the next `vm web` has the merged lines. Translations stored by
`vm translate-import` (matched by text) are joined for the merged line too.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, build_source
from .protocols import LineMerger
from .textclean import clean
from .translations import read_store, store_path, stores_for, write_store


@dataclass
class DocEdits:
    source_id: str
    doc_id: str
    title: str
    groups: list[list[dict]] = field(default_factory=list)     # [[{id, start, text}, ...], ...]


def read_merges(path: Path) -> list[DocEdits]:
    """The merged lines of an exported data file, per doc."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    out = []
    for d in data.get("docs", []):
        groups = [ln["merged"] for ln in d.get("lines", []) if len(ln.get("merged") or []) > 1]
        groups = [g for g in groups if all(isinstance(m.get("start"), (int, float)) for m in g)]
        if groups and d.get("source") and d.get("doc") is not None:
            out.append(DocEdits(d["source"], str(d["doc"]), d.get("title", d["doc"]), groups))
    return out


def apply_merges(config: Config, edits: list[DocEdits], log: Callable[[str], None] = print) -> list[str]:
    """Merge the lines in each source's files; returns the ids of the sources that changed."""
    blocks = {b["id"]: b for b in config.sources()}
    changed = []
    for sid in dict.fromkeys(e.source_id for e in edits):
        if sid not in blocks:
            log(f"{sid}: not a source in this project, skipped")
            continue
        source = build_source(blocks[sid], config)
        if not isinstance(source, LineMerger):
            log(f"{sid}: this source cannot edit its files; join the lines in the material by hand")
            continue
        n = 0
        for e in (e for e in edits if e.source_id == sid):
            try:
                done = source.merge_lines(e.doc_id, [[m["start"] for m in g] for g in e.groups])
            except (FileNotFoundError, ValueError) as err:
                log(f"  {e.title}: {err}")
                continue
            if done < len(e.groups):
                log(f"  {e.title}: {len(e.groups) - done} merge(s) were already in the files")
            n += done
        if n:
            _join_translations(config, source, [e for e in edits if e.source_id == sid])
            changed.append(sid)
        log(f"{sid}: {n} merge(s) written")
    return changed


def _join_translations(config: Config, source, edits: list[DocEdits]) -> None:
    """Translations kept by text: the merged line gets its parts' translations joined, when all parts had one."""
    stores = stores_for(config.data_dir, source.source_id)
    if not stores:
        return
    docs = {e.doc_id for e in edits}
    new_text = {(u.doc_id, round(u.media.start, 2)): u.text for u in source.utterances()
                if u.doc_id in docs and u.media and u.media.start is not None}
    for lang in stores:
        path = store_path(config.data_dir, source.source_id, lang)
        store = read_store(path)
        added = 0
        for e in edits:
            for g in e.groups:
                parts = [store.get((e.doc_id, m["text"])) for m in g]
                text = new_text.get((e.doc_id, round(g[0]["start"], 2)))
                if text and all(parts) and (e.doc_id, text) not in store:
                    store[(e.doc_id, text)] = clean(" ".join(parts))
                    added += 1
        if added:
            write_store(path, store)
