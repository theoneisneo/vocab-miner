"""Data file for the sing-along web app (web/): every line of every doc with ruby, romaji, translation and timing,
plus the vocabulary (content and grammar words) the lines link to.

The file contains your material, so it is written to out/ and never published with the app; the app imports it
from a local file and keeps it on the device.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from ..model import NO_STATS_TAG, Token, Utterance, VocabEntry
from ..render import segments

FORMAT_VERSION = 1


def load_short_labels(lang: str = "ja", gloss_lang: str = "zh") -> dict[str, str]:
    try:
        text = resources.files("vocab_miner.data").joinpath(f"short_glosses_{lang}_{gloss_lang}.tsv").read_text(
            encoding="utf-8")
    except FileNotFoundError:
        return {}
    return dict(ln.split("\t")[:2] for ln in text.splitlines() if ln.strip() and not ln.startswith("#"))


def short_gloss(gloss: str, limit: int = 6) -> str:
    """First sense of a gloss, for the word-by-word line: "眼淚；同情" -> "眼淚", "在、有（人或動物）" -> "在"."""
    g = re.sub(r"（[^）]*）|\([^)]*\)", "", gloss)
    for sep in ("；", ";", "/", "、", "，", ","):
        g = g.split(sep)[0]
    g = g.strip(" …")
    return g if len(g) <= limit else g[: limit - 1] + "…"


def _word(e: VocabEntry, grammar: bool, labels: dict[str, str]) -> dict:
    zh = e.gloss.get("zh-Hant", "")
    return {
        "key": e.key, "lemma": e.lemma, "reading": e.reading or "", "romaji": e.romaji or "",
        "pos": e.pos_label or e.pos, "upos": e.pos,
        # a short meaning written in the gloss table wins, then the grammar label, then the gloss's first sense
        "short": e.gloss.get("zh-Hant:short") or (labels.get(e.lemma) if grammar else None) or short_gloss(zh),
        "zh": zh, "en": e.gloss.get("en", ""),
        "ff": e.false_friend or "", "rank": e.rank, "count": e.count, "docFreq": e.doc_freq,
        "grammar": grammar, "status": e.status,
    }


def build_web_data(entries: Sequence[VocabEntry], grammar: Sequence[VocabEntry], utterances: Sequence[Utterance],
                   tokens: Mapping[str, list[Token]], titles: Mapping[tuple[str, str], str], lang: str,
                   romanize_tokens: Callable[[Sequence[Token]], str] | None = None,
                   translation_lang: str = "zh-Hant", title: str = "",
                   romanize_token_list: Callable[[Sequence[Token]], list[str]] | None = None,
                   explanations: Mapping[str, str] | None = None) -> dict:
    labels = load_short_labels(lang, translation_lang.split("-")[0])
    words = [_word(e, False, labels) for e in entries] + [_word(e, True, labels) for e in grammar]
    index_of = {w["key"]: i for i, w in enumerate(words)}

    docs: dict[tuple[str, str], dict] = {}
    for u in utterances:
        k = (u.source_id, u.doc_id)
        doc = docs.get(k)
        if doc is None:
            doc = docs[k] = {"id": f"{u.source_id}/{u.doc_id}", "source": u.source_id, "doc": u.doc_id,
                             "title": titles.get(k, u.doc_id), "media": None, "noStats": False, "lines": []}
        if u.media is not None and doc["media"] is None:
            doc["media"] = {"kind": u.media.kind, "uri": u.media.uri}
        doc["noStats"] = doc["noStats"] or NO_STATS_TAG in u.tags
        toks = tokens.get(u.id, [])
        # seg: [text, ruby, word index or null, token index or null]; pieces of one token share the token index
        seg = [[s.text, s.ruby, index_of.get(toks[s.token].key) if s.token is not None else None, s.token]
               for s in segments(u.text, toks)] if toks else [[u.text, None, None, None]]
        doc["lines"].append({
            "id": u.id, "start": u.media.start if u.media else None, "end": u.media.end if u.media else None,
            "seg": seg, "romaji": romanize_tokens(toks) if romanize_tokens and toks else "",
            "wr": romanize_token_list(toks) if romanize_token_list and toks else [],   # romaji per token
            "tr": u.translations.get(translation_lang, ""),
        })
        if explanations and u.id in explanations:
            doc["lines"][-1]["ex"] = explanations[u.id]          # written explanation (shown on demand)
    return {
        "format": "vocab-miner-web", "version": FORMAT_VERSION, "lang": lang,
        "title": title or ", ".join(dict.fromkeys(d["source"] for d in docs.values())),
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "words": words, "docs": list(docs.values()),
    }


def write_web_data(data: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
