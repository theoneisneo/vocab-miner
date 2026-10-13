"""Wire config -> index -> vocabulary entries -> exporters."""
from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Config, ConfigError, load_plugin
from .index import Index, build_index
from .model import Utterance, VocabEntry
from .vocab import (
    DEFAULT_EXCLUDE_POS,
    VocabOptions,
    add_coverage,
    apply_false_friends,
    apply_status,
    collect,
    load_false_friends,
    load_word_list,
)

DEFAULT_DICTIONARIES = [
    {"plugin": "vocab_miner.dictionaries.jmdict:JMdictDictionary", "path": ".cache/dict/JMdict_e.gz"},
    {"plugin": "vocab_miner.dictionaries.tsv:TsvGlossDictionary", "path": "data/gloss/ja-zh.tsv",
     "gloss_lang": "zh-Hant"},
]
PATH_KEYS = ("path",)


def instantiate(block: dict[str, Any] | None, config: Config, default: str | None = None, **extra):
    block = dict(block or {})
    spec = block.pop("plugin", default)
    if not spec:
        raise ConfigError("missing 'plugin'")
    for k in PATH_KEYS:
        if k in block:
            block[k] = config.resolve(block[k])
    cls = load_plugin(spec, config.root)
    try:
        return cls(**block, **extra)
    except TypeError as e:
        raise ConfigError(f"bad options for {spec}: {e}") from e


def index_path(config: Config) -> Path:
    return config.resolve(config.get("cache_dir", ".cache")) / "index.sqlite"


def names_path(config: Config, source_id: str) -> Path:
    return config.data_dir.joinpath("names", *source_id.split("/")).with_suffix(".txt")


def read_names(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8-sig").splitlines()
            if ln.strip() and not ln.startswith("#")]


def corpus_files(config: Config) -> dict[str, Path]:
    d = config.corpus_dir
    if not d.is_dir():
        return {}
    return {p.relative_to(d).with_suffix("").as_posix(): p for p in sorted(d.rglob("*.jsonl"))}


class Pipeline:
    def __init__(self, config: Config):
        self.config = config
        self._tokenizer = None

    @property
    def tokenizer(self):
        if self._tokenizer is None:
            self._tokenizer = instantiate(self.config.get("tokenizer"), self.config,
                                          "vocab_miner.tokenizers.ja:JapaneseTokenizer")
        return self._tokenizer

    def tokenizer_id(self) -> str:
        block = self.config.get("tokenizer") or {}
        tok = self.tokenizer
        return f"{sorted(block.items())!r}:{type(tok).__module__}.{type(tok).__name__}:{getattr(tok, 'version', '')}"

    def tokenizer_for(self, source_id: str):
        names = read_names(names_path(self.config, source_id))
        if names and hasattr(self.tokenizer, "with_names"):
            return self.tokenizer.with_names(names)
        return self.tokenizer

    def open_index(self) -> Index:
        return Index(index_path(self.config))

    def build(self, force: bool = False, log: Callable[[str], None] = print) -> None:
        with self.open_index() as idx:
            build_index(idx, corpus_files(self.config), self.tokenizer_for, self.tokenizer_id(),
                        lambda s: read_names(names_path(self.config, s)), force=force, log=log)

    # ---------- vocabulary ----------

    def dictionaries(self) -> list:
        return [instantiate(b, self.config) for b in self.config.get("dictionaries", DEFAULT_DICTIONARIES)]

    def romanizer(self):
        return instantiate(self.config.get("romanizer"), self.config, "vocab_miner.tokenizers.ja:HepburnRomanizer")

    def vocab(self, source_ids: list[str] | None = None, doc_ids: list[str] | None = None,
              log: Callable[[str], None] = print) -> tuple[list[VocabEntry], dict[str, Utterance]]:
        cfg = self.config
        lang = cfg.get("target_lang", "ja")
        vcfg = cfg.get("vocab", {})
        opts = VocabOptions(exclude_pos=vcfg.get("exclude_pos", DEFAULT_EXCLUDE_POS),
                            include_proper=vcfg.get("include_proper", False),
                            min_count=vcfg.get("min_count", 1))
        tok = self.tokenizer
        with self.open_index() as idx:
            entries = collect(idx, lang, opts, getattr(tok, "word_pattern", None), getattr(tok, "pos_label", None),
                              source_ids, doc_ids)
            known = load_word_list(cfg.data_dir / "known" / f"{lang}.txt")
            learning = load_word_list(cfg.data_dir / "known" / f"{lang}.learning.txt")
            ranker = instantiate(cfg.get("ranker"), cfg, "vocab_miner.rankers:FrequencyRanker")
            entries = ranker.rank(entries, known)
            add_coverage(entries)
            apply_status(entries, known, learning)

            romanizer = self.romanizer()
            for e in entries:
                if e.reading:
                    e.romaji = romanizer.romanize(e.reading)
                    if e.pos in ("ADP", "PART", "SCONJ") and hasattr(romanizer, "romanize_token"):
                        e.romaji = {"は": "wa", "へ": "e", "を": "o"}.get(e.lemma, e.romaji) if lang == "ja" \
                            else e.romaji

            self._glosses(entries, log)
            for gl in cfg.get("gloss_langs", ["zh-Hant", "en"]):
                if not gl.startswith("en"):
                    apply_false_friends(entries, load_false_friends(lang, gl))
                    break

            ecfg = cfg.get("examples", {})
            selector = instantiate({k: v for k, v in ecfg.items() if k != "per_entry"}, cfg,
                                   "vocab_miner.examples:DefaultExampleSelector")
            k = ecfg.get("per_entry", 3)
            used: dict[str, Utterance] = {}
            for e in entries:
                ids = idx.utterance_ids_for(e.key)
                cands = list(idx.utterances(ids).values())
                e.examples = selector.select(e, cands, known, k)
                for c in cands:
                    if c.id in e.examples:
                        used[c.id] = c
        return entries, used

    def _glosses(self, entries: list[VocabEntry], log: Callable[[str], None]) -> None:
        try:
            dicts = self.dictionaries()
        except ConfigError as e:
            log(f"dictionaries disabled: {e}")
            return
        for d in dicts:
            accepts_base = "base" in inspect.signature(d.lookup).parameters
            for e in entries:
                lemma = e.key.split("\t", 1)[0]
                try:
                    res = d.lookup(lemma, e.reading, e.pos, base=e.lemma) if accepts_base \
                        else d.lookup(lemma, e.reading, e.pos)
                except FileNotFoundError as err:
                    log(f"{type(d).__name__}: {err}")
                    break
                for gl, text in res.items():
                    if text and not e.gloss.get(gl):
                        e.gloss[gl] = text
