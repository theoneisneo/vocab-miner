"""Lines edited in the web app, written back to the material: `vm apply-edits <exported data file>`.

The app exports a data file where
  - a line only joined from others carries "merged": [{id, start, text}, ...] (the original lines). A source that
    can edit its own files implements protocols.LineMerger (groups of start times). Translations stored by
    `vm translate-import` (matched by text) are joined for the merged line too.
  - a line changed in any other way (text, a word deleted, a reading, a split, times, translation) carries
    "edited": true and "orig": [...] (the lines it came from). For such a song the whole list of lines is written
    back at once by a source that implements protocols.LineRewriter, after checking that the lines the edit was
    made on are still the material's (otherwise the song is skipped: export again from fresh data).
Afterwards the sources are ingested again, so the next `vm web` has the edited lines.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, build_source
from .model import EditedLine
from .protocols import LineMerger, LineRewriter
from .textclean import clean
from .translations import read_store, store_path, stores_for, write_store

TR_LANG = "zh-Hant"           # the translation the app shows (export.web translation_lang)


@dataclass
class DocEdits:
    source_id: str
    doc_id: str
    title: str
    groups: list[list[dict]] = field(default_factory=list)     # [[{id, start, text}, ...], ...]


@dataclass
class DocRewrite:
    """A song with edited lines: its whole new list of lines, and the material lines they were made from."""
    source_id: str
    doc_id: str
    title: str
    lines: list[EditedLine]
    refs: list[dict]                                           # [{id, start, text}]: lines the edit was made on
    changes: list[tuple[list[str], str]]                       # (original texts, new text) of the edited lines


def _seg_text(line: dict) -> str:
    return "".join(s[0] for s in line.get("seg") or [])


def _docs(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return [d for d in data.get("docs", []) if d.get("source") and d.get("doc") is not None]


def read_line_edits(path: Path) -> list[DocRewrite]:
    """Songs of an exported data file with edited lines (beyond joining), as whole new lists of lines."""
    out = []
    for d in _docs(path):
        lines = d.get("lines", [])
        if not any(ln.get("edited") for ln in lines):
            continue
        refs, changes, new = [], [], []
        for ln in lines:
            text = _seg_text(ln)
            if ln.get("edited") or ln.get("merged"):
                refs += ln.get("orig") or ln.get("merged") or []
            else:
                refs.append({"id": ln.get("id"), "start": ln.get("start"), "text": text})
            if ln.get("edited"):
                changes.append(([o.get("text", "") for o in ln.get("orig") or []], text))
            new.append(EditedLine(text=text, pieces=[(s[0], s[1]) for s in ln.get("seg") or []],
                                  start=ln.get("start"), end=ln.get("end"), tr=ln.get("tr") or "",
                                  changed=bool(ln.get("edited"))))
        unique = {(r.get("id"), r.get("start"), r.get("text")): r for r in refs}
        out.append(DocRewrite(d["source"], str(d["doc"]), d.get("title", d["doc"]), new, list(unique.values()),
                              changes))
    return out


def read_merges(path: Path, skip: set[tuple[str, str]] = frozenset()) -> list[DocEdits]:
    """The merged lines of an exported data file, per doc (`skip`: (source, doc) written as a whole instead)."""
    out = []
    for d in _docs(path):
        if (d["source"], str(d["doc"])) in skip:
            continue
        groups = [ln["merged"] for ln in d.get("lines", []) if len(ln.get("merged") or []) > 1]
        groups = [g for g in groups if all(isinstance(m.get("start"), (int, float)) for m in g)]
        if groups:
            out.append(DocEdits(d["source"], str(d["doc"]), d.get("title", d["doc"]), groups))
    return out


def _still_there(refs: list[dict], utterances: list) -> list[dict]:
    """The refs no longer in the material: the same text with the same id (ids are positions), or at the same
    start time."""
    by_id = {u.id: u.text for u in utterances}
    by_time = {(round(u.media.start, 2), u.text) for u in utterances if u.media and u.media.start is not None}
    texts = {u.text for u in utterances}
    missing = []
    for r in refs:
        if r.get("id") in by_id and by_id[r["id"]] == r.get("text"):
            continue
        start = r.get("start")
        if isinstance(start, (int, float)) and (round(start, 2), r.get("text")) in by_time:
            continue
        if start is None and r.get("text") in texts:
            continue
        missing.append(r)
    return missing


def apply_rewrites(config: Config, rewrites: list[DocRewrite], log: Callable[[str], None] = print) -> list[str]:
    """Write each edited song back to its source's files; returns the ids of the sources that changed."""
    blocks = {b["id"]: b for b in config.sources()}
    changed = []
    for sid in dict.fromkeys(r.source_id for r in rewrites):
        if sid not in blocks:
            log(f"{sid}: not a source in this project, skipped")
            continue
        source = build_source(blocks[sid], config)
        if not isinstance(source, LineRewriter):
            log(f"{sid}: this source cannot rewrite its files; make the changes in the material by hand")
            continue
        utterances = list(source.utterances())
        n = 0
        for r in (r for r in rewrites if r.source_id == sid):
            missing = _still_there(r.refs, [u for u in utterances if u.doc_id == r.doc_id])
            if missing:
                log(f"  {r.title}: skipped, the material changed since the export (e.g. "
                    f"{missing[0].get('text', '')!r}); export again from a fresh data file")
                continue
            try:
                source.rewrite_lines(r.doc_id, r.lines, TR_LANG)
            except (FileNotFoundError, ValueError) as err:
                log(f"  {r.title}: {err}")
                continue
            n += 1
        if n:
            changed.append(sid)
        log(f"{sid}: {n} song(s) written")
    return changed


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
