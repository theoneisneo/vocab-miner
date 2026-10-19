"""Run configured sources and write data/corpus/<source_id>.jsonl."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import translations
from .config import Config, build_source
from .model import NO_STATS_TAG, Utterance, write_jsonl

# [[sources]] keys handled by the framework instead of being passed to the plugin
FRAMEWORK_KEYS = ("no_stats_docs", "add_tags")


class SourceError(Exception):
    pass


@dataclass
class IngestResult:
    source_id: str
    path: Path
    utterances: int
    docs: int
    no_stats_docs: list[str] = field(default_factory=list)


def checked(utterances: Iterable[Utterance], source_id: str, no_stats_docs: set[str],
            add_tags: list[str]) -> Iterator[Utterance]:
    """Validate the source's output and apply framework-level tags."""
    seen: set[str] = set()
    for u in utterances:
        if u.source_id != source_id or not u.id.startswith(source_id + ":"):
            raise SourceError(f"{source_id}: utterance {u.id!r} has wrong source id {u.source_id!r}")
        if u.id in seen:
            raise SourceError(f"{source_id}: duplicate utterance id {u.id!r}")
        if not u.text.strip():
            raise SourceError(f"{source_id}: utterance {u.id!r} has empty text")
        seen.add(u.id)
        extra = list(add_tags) + ([NO_STATS_TAG] if u.doc_id in no_stats_docs else [])
        for t in extra:
            if t not in u.tags:
                u.tags.append(t)
        yield u


def ingest_source(block: dict[str, Any], config: Config) -> IngestResult:
    source_id = block["id"]
    plugin_block = {k: v for k, v in block.items() if k not in FRAMEWORK_KEYS}
    no_stats = {str(d) for d in block.get("no_stats_docs", [])}
    source = build_source(plugin_block, config)
    docs: set[str] = set()

    def track(us: Iterable[Utterance]) -> Iterator[Utterance]:
        for u in us:
            docs.add(u.doc_id)
            yield u

    path = config.corpus_path(source_id)
    tmp = path.with_suffix(".jsonl.tmp")
    stores = translations.stores_for(config.data_dir, source_id)    # your own translations (vm translate-import)
    try:
        n = write_jsonl(tmp, track(translations.apply(
            checked(source.utterances(), source_id, no_stats, block.get("add_tags", [])), stores)))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    unknown = sorted(no_stats - docs)
    if unknown:
        tmp.unlink()
        raise SourceError(f"{source_id}: no_stats_docs lists unknown docs {unknown}")
    tmp.replace(path)
    return IngestResult(source_id, path, n, len(docs), sorted(no_stats))


def ingest(config: Config, only: list[str] | None = None) -> list[IngestResult]:
    blocks = config.sources()
    if only:
        unknown = set(only) - {b["id"] for b in blocks}
        if unknown:
            raise SourceError(f"unknown source ids: {sorted(unknown)}")
        blocks = [b for b in blocks if b["id"] in only]
    return [ingest_source(b, config) for b in blocks]
